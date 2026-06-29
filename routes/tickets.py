import logging
from flask import Blueprint, render_template, redirect, url_for, flash, request, send_file, current_app
from flask_login import login_required, current_user
from db import db
from models.ticket import Ticket
from models.approval import ApprovalRequest
from models.settings import SystemSettings
from models.user import User
from services.history_service import log_ticket_created, log_ticket_changes, log_ticket_deleted
import pandas as pd
import io
from datetime import datetime, date
from dateutil.relativedelta import relativedelta

tickets_bp = Blueprint('tickets', __name__)
log = logging.getLogger(__name__)

STATUSES = ['Open', 'In Progress', 'UAT', 'Closed', 'On Hold']
TICKET_TYPES = ['Enhancement', 'Bug Fix', 'New Feature', 'Maintenance', 'Support', 'Other']

def get_months():
    months = []

    current_month = datetime.today().replace(day=1)

    for i in range(5):  # Current month + next 4 months
        month = current_month + relativedelta(months=i)
        months.append(month.strftime('%b-%Y'))

    return months

MONTHS = get_months()

def is_frozen():
    settings = SystemSettings.query.first()
    if settings and settings.freeze_date:
        return date.today() >= settings.freeze_date
    return False


def parse_date(val):
    if not val:
        return None
    for fmt in ('%Y-%m-%d', '%d-%m-%Y', '%d/%m/%Y'):
        try:
            return datetime.strptime(val, fmt).date()
        except ValueError:
            pass
    return None


def form_to_dict(form):
    return {
        'ticket_no': form.get('ticket_no', '').strip(),
        'ticket_type': form.get('ticket_type', '').strip(),
        'service': form.get('service', '').strip(),
        'description': form.get('description', '').strip(),
        'status': form.get('status', 'Open').strip(),
        'planned_month': form.get('planned_month', '').strip(),
        'actual_implementation_month': form.get('actual_implementation_month', '').strip(),
        'planned_efforts': form.get('planned_efforts', '0') or '0',
        'utilized_efforts': form.get('utilized_efforts', '0') or '0',
        'approved_by': form.get('approved_by', '').strip(),
        'assigned_to': form.get('assigned_to', '').strip(),
        'estimated_uat': form.get('estimated_uat', '').strip(),
        'estimated_prod': form.get('estimated_prod', '').strip(),
        'actual_uat': form.get('actual_uat', '').strip(),
        'actual_prod': form.get('actual_prod', '').strip(),
        'revised_uat_date': form.get('revised_uat_date', '').strip(),
        'revised_prod_date': form.get('revised_prod_date', '').strip(),
        'exception_from': form.get('exception_from', '').strip(),
        'business_benefits': form.get('business_benefits', '').strip(),
        'remarks': form.get('remarks', '').strip(),
    }


def apply_dict_to_ticket(ticket, data):
    ticket.ticket_no = data['ticket_no']
    ticket.ticket_type = data['ticket_type']
    ticket.service = data['service']
    ticket.description = data['description']
    ticket.status = data['status']
    ticket.planned_month = data['planned_month']
    ticket.actual_implementation_month = data['actual_implementation_month']
    try:
        ticket.planned_efforts = float(data['planned_efforts'])
    except (ValueError, TypeError):
        ticket.planned_efforts = 0
    try:
        ticket.utilized_efforts = float(data['utilized_efforts'])
    except (ValueError, TypeError):
        ticket.utilized_efforts = 0
    ticket.approved_by = data['approved_by']
    ticket.assigned_to = data.get('assigned_to', '')
    ticket.estimated_uat = parse_date(data['estimated_uat'])
    ticket.estimated_prod = parse_date(data['estimated_prod'])
    ticket.actual_uat = parse_date(data['actual_uat'])
    ticket.actual_prod = parse_date(data['actual_prod'])
    ticket.revised_uat_date = parse_date(data['revised_uat_date'])
    ticket.revised_prod_date = parse_date(data['revised_prod_date'])
    ticket.exception_from = data['exception_from']
    ticket.business_benefits = data['business_benefits']
    ticket.remarks = data['remarks']


@tickets_bp.route('/add', methods=['GET', 'POST'])
@login_required
def add_ticket():
    frozen = is_frozen()
    if request.method == 'POST':
        data = form_to_dict(request.form)

        if not data['ticket_no']:
            flash('Ticket number is required.', 'danger')
            return render_template('add_ticket.html', data=data, statuses=STATUSES,
                                   ticket_types=TICKET_TYPES, months=MONTHS, frozen=frozen)

        if Ticket.query.filter_by(ticket_no=data['ticket_no']).first():
            flash('Ticket number already exists.', 'danger')
            return render_template('add_ticket.html', data=data, statuses=STATUSES,
                                   ticket_types=TICKET_TYPES, months=MONTHS, frozen=frozen)

        if frozen:
            # Requires approval
            ar = ApprovalRequest(
                request_type='ADD',
                ticket_id=None,
                requested_by=current_user.username,
            )
            ar.set_request_data(data)
            db.session.add(ar)
            db.session.commit()
            log.info('Add request pending approval: ticket_no=%s by=%s', data['ticket_no'], current_user.username)
            flash('Freeze is active. Add request submitted for approval.', 'warning')
            return redirect(url_for('dashboard.index'))
        else:
            # Direct save
            ticket = Ticket(created_by=current_user.username)
            apply_dict_to_ticket(ticket, data)
            db.session.add(ticket)
            db.session.commit()
            log_ticket_created(ticket, current_user.username)
            log.info('Ticket created: ticket_no=%s by=%s', ticket.ticket_no, current_user.username)
            flash('Ticket added successfully.', 'success')
            return redirect(url_for('dashboard.index'))

    active_users = User.query.filter_by(active_flag=True).order_by(User.username).all()
    return render_template('add_ticket.html', data={}, statuses=STATUSES,
                           ticket_types=TICKET_TYPES, months=MONTHS, frozen=frozen,
                           active_users=active_users)


@tickets_bp.route('/edit/<int:ticket_id>', methods=['GET', 'POST'])
@login_required
def edit_ticket(ticket_id):
    ticket = Ticket.query.filter_by(id=ticket_id, deleted_flag=False).first_or_404()
    frozen = is_frozen()

    if request.method == 'POST':
        new_data = form_to_dict(request.form)
        old_data = ticket.to_dict()

        # Determine changed fields
        date_fields = {'estimated_uat', 'estimated_prod', 'actual_uat', 'actual_prod',
                       'revised_uat_date', 'revised_prod_date'}
        changed_fields = []
        for field in new_data:
            old_val = str(old_data.get(field) or '')
            new_val = str(new_data.get(field) or '')
            if old_val != new_val:
                changed_fields.append(field)

        if not changed_fields:
            flash('No changes detected.', 'info')
            return redirect(url_for('dashboard.index'))

        # Always requires approval for edit
        ar = ApprovalRequest(
            request_type='EDIT',
            ticket_id=ticket.id,
            requested_by=current_user.username,
        )
        ar.set_request_data({
            'old_data': old_data,
            'new_data': new_data,
            'changed_fields': changed_fields,
        })
        db.session.add(ar)
        db.session.commit()
        log.info('Edit request pending approval: ticket=%s fields=%s by=%s', ticket.ticket_no, changed_fields, current_user.username)
        flash('Edit request submitted for approval.', 'warning')
        return redirect(url_for('dashboard.index'))

    # Pre-populate form
    def fmt_date(d):
        return d.strftime('%Y-%m-%d') if d else ''

    data = {
        'ticket_no': ticket.ticket_no,
        'ticket_type': ticket.ticket_type or '',
        'service': ticket.service or '',
        'description': ticket.description or '',
        'status': ticket.status or 'Open',
        'planned_month': ticket.planned_month or '',
        'actual_implementation_month': ticket.actual_implementation_month or '',
        'planned_efforts': ticket.planned_efforts or 0,
        'utilized_efforts': ticket.utilized_efforts or 0,
        'approved_by': ticket.approved_by or '',
        'estimated_uat': fmt_date(ticket.estimated_uat),
        'estimated_prod': fmt_date(ticket.estimated_prod),
        'actual_uat': fmt_date(ticket.actual_uat),
        'actual_prod': fmt_date(ticket.actual_prod),
        'revised_uat_date': fmt_date(ticket.revised_uat_date),
        'revised_prod_date': fmt_date(ticket.revised_prod_date),
        'exception_from': ticket.exception_from or '',
        'business_benefits': ticket.business_benefits or '',
        'remarks': ticket.remarks or '',
        'assigned_to': ticket.assigned_to or '',
    }
    active_users = User.query.filter_by(active_flag=True).order_by(User.username).all()
    return render_template('edit_ticket.html', ticket=ticket, data=data,
                           statuses=STATUSES, ticket_types=TICKET_TYPES,
                           months=MONTHS, frozen=frozen, active_users=active_users)


@tickets_bp.route('/delete/<int:ticket_id>', methods=['POST'])
@login_required
def delete_ticket(ticket_id):
    ticket = Ticket.query.filter_by(id=ticket_id, deleted_flag=False).first_or_404()

    existing = ApprovalRequest.query.filter_by(
        ticket_id=ticket_id, request_type='DELETE', status='PENDING'
    ).first()
    if existing:
        flash('A delete request is already pending for this ticket.', 'warning')
        return redirect(url_for('dashboard.index'))

    ar = ApprovalRequest(
        request_type='DELETE',
        ticket_id=ticket.id,
        requested_by=current_user.username,
    )
    ar.set_request_data(ticket.to_dict())
    db.session.add(ar)
    ticket.delete_requested = True
    ticket.delete_requested_by = current_user.username
    ticket.delete_requested_date = datetime.utcnow()
    db.session.commit()
    log.info('Delete request pending approval: ticket=%s by=%s', ticket.ticket_no, current_user.username)
    flash('Delete request submitted for approval.', 'warning')
    return redirect(url_for('dashboard.index'))


@tickets_bp.route('/view/<int:ticket_id>')
@login_required
def view_ticket(ticket_id):
    ticket = Ticket.query.filter_by(id=ticket_id, deleted_flag=False).first_or_404()
    def fmt_date(d):
        return d.strftime('%d-%b-%Y') if d else '–'
    return render_template('view_ticket.html', ticket=ticket, fmt_date=fmt_date)


@tickets_bp.route('/history/<int:ticket_id>')
@login_required
def ticket_history(ticket_id):
    ticket = Ticket.query.get_or_404(ticket_id)
    history = ticket.history.order_by(db.text('changed_at desc')).all()
    return render_template('history.html', ticket=ticket, history=history)


@tickets_bp.route('/bulk-upload', methods=['GET', 'POST'])
@login_required
def bulk_upload():
    frozen = is_frozen()
    if request.method == 'POST':
        file = request.files.get('file')
        if not file or not file.filename.endswith(('.xlsx', '.xls')):
            flash('Please upload a valid Excel file.', 'danger')
            return render_template('bulk_upload.html')

        try:
            df = pd.read_excel(file)
            df.columns = [c.strip().lower().replace(' ', '_') for c in df.columns]
        except Exception as e:
            flash(f'Error reading file: {e}', 'danger')
            return render_template('bulk_upload.html')

        required_cols = ['ticket_no', 'description']
        missing = [c for c in required_cols if c not in df.columns]
        if missing:
            flash(f'Missing required columns: {", ".join(missing)}', 'danger')
            return render_template('bulk_upload.html')

        added = 0
        skipped = 0
        pending = 0
        errors = []

        for idx, row in df.iterrows():
            ticket_no = str(row.get('ticket_no', '')).strip()
            if not ticket_no or ticket_no == 'nan':
                skipped += 1
                continue

            if Ticket.query.filter_by(ticket_no=ticket_no).first():
                errors.append(f'Row {idx+2}: Ticket {ticket_no} already exists.')
                skipped += 1
                continue

            def safe_str(val):
                v = str(val).strip() if pd.notna(val) else ''
                return '' if v == 'nan' else v

            def safe_date(val):
                if pd.isna(val):
                    return None
                try:
                    if hasattr(val, 'date'):
                        return val.date()
                    return parse_date(str(val))
                except:
                    return None

            data = {
                'ticket_no': ticket_no,
                'ticket_type': safe_str(row.get('ticket_type', '')),
                'service': safe_str(row.get('service', '')),
                'description': safe_str(row.get('description', '')),
                'status': safe_str(row.get('status', 'Open')) or 'Open',
                'planned_month': safe_str(row.get('planned_month', '')),
                'actual_implementation_month': safe_str(row.get('actual_implementation_month', '')),
                'planned_efforts': str(row.get('planned_efforts', '0') or '0'),
                'utilized_efforts': str(row.get('utilized_efforts', '0') or '0'),
                'approved_by': safe_str(row.get('approved_by', '')),
                'estimated_uat': safe_str(row.get('estimated_uat', '')),
                'estimated_prod': safe_str(row.get('estimated_prod', '')),
                'actual_uat': safe_str(row.get('actual_uat', '')),
                'actual_prod': safe_str(row.get('actual_prod', '')),
                'revised_uat_date': safe_str(row.get('revised_uat_date', '')),
                'revised_prod_date': safe_str(row.get('revised_prod_date', '')),
                'exception_from': safe_str(row.get('exception_from', '')),
                'business_benefits': safe_str(row.get('business_benefits', '')),
                'remarks': safe_str(row.get('remarks', '')),
            }

            if frozen:
                ar = ApprovalRequest(request_type='ADD', requested_by=current_user.username)
                ar.set_request_data(data)
                db.session.add(ar)
                pending += 1
            else:
                ticket = Ticket(created_by=current_user.username)
                apply_dict_to_ticket(ticket, data)
                db.session.add(ticket)
                db.session.flush()
                log_ticket_created(ticket, current_user.username)
                added += 1

        db.session.commit()

        msg = f'Bulk upload: {added} added, {pending} pending approval, {skipped} skipped.'
        if errors:
            msg += ' Errors: ' + '; '.join(errors[:5])
        log.info('Bulk upload: added=%d pending=%d skipped=%d by=%s', added, pending, skipped, current_user.username)
        flash(msg, 'info')
        return redirect(url_for('dashboard.index'))

    return render_template('bulk_upload.html')


@tickets_bp.route('/template')
@login_required
def download_template():
    data = {
        'ticket_no': ['TKT-001'],
        'ticket_type': ['Enhancement'],
        'service': ['Service Name'],
        'description': ['Ticket description here'],
        'status': ['Open'],
        'planned_month': ['Jan-2025'],
        'actual_implementation_month': [''],
        'planned_efforts': [8],
        'utilized_efforts': [0],
        'approved_by': ['Manager Name'],
        'estimated_uat': ['2025-03-15'],
        'estimated_prod': ['2025-03-31'],
        'actual_uat': [''],
        'actual_prod': [''],
        'revised_uat_date': [''],
        'revised_prod_date': [''],
        'exception_from': [''],
        'business_benefits': ['Improves efficiency'],
        'remarks': [''],
    }
    df = pd.DataFrame(data)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Tickets')
    output.seek(0)
    return send_file(output, download_name='bulk_upload_template.xlsx', as_attachment=True,
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
