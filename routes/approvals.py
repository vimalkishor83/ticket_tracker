import logging
from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from db import db
from models.ticket import Ticket
from models.approval import ApprovalRequest
from models.user import User
from services.history_service import log_ticket_created, log_ticket_changes, log_ticket_deleted
from services.email_service import send_approval_notification
from routes.tickets import apply_dict_to_ticket, parse_date
from datetime import datetime
from functools import wraps

approvals_bp = Blueprint('approvals', __name__)
log = logging.getLogger(__name__)

FIELD_LABELS = {
    'ticket_no': 'Ticket No',
    'ticket_type': 'Ticket Type',
    'service': 'Service',
    'description': 'Description',
    'status': 'Status',
    'planned_month': 'Planned Month',
    'actual_implementation_month': 'Actual Impl. Month',
    'planned_efforts': 'Planned Efforts',
    'utilized_efforts': 'Utilized Efforts',
    'approved_by': 'Approved By',
    'estimated_uat': 'Estimated UAT',
    'estimated_prod': 'Estimated Prod',
    'actual_uat': 'Actual UAT',
    'actual_prod': 'Actual Prod',
    'revised_uat_date': 'Revised UAT Date',
    'revised_prod_date': 'Revised Prod Date',
    'exception_from': 'Exception From',
    'business_benefits': 'Business Benefits',
    'remarks': 'Remarks',
    'assigned_to': 'Assigned To',
}


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin():
            flash('Admin access required.', 'danger')
            return redirect(url_for('dashboard.index'))
        return f(*args, **kwargs)
    return decorated


def _process_single_approval(approval, action, admin_username, comments):
    """Apply approve/reject logic for one ApprovalRequest. Caller must commit."""
    approval.approved_by = admin_username
    approval.approved_at = datetime.utcnow()
    approval.comments = comments

    ticket_no = 'N/A'

    if action == 'approve':
        approval.status = 'APPROVED'
        data = approval.get_request_data()

        if approval.request_type == 'ADD':
            ticket = Ticket(created_by=approval.requested_by)
            apply_dict_to_ticket(ticket, data)
            db.session.add(ticket)
            db.session.flush()
            approval.ticket_id = ticket.id
            log_ticket_created(ticket, approval.requested_by)
            ticket_no = ticket.ticket_no
            log.info('ADD approved: ticket=%s by=%s', ticket.ticket_no, admin_username)

        elif approval.request_type == 'EDIT':
            ticket = approval.ticket
            if ticket:
                old_data = ticket.to_dict()
                apply_dict_to_ticket(ticket, data['new_data'])
                ticket.updated_at = datetime.utcnow()
                db.session.flush()
                log_ticket_changes(ticket.id, old_data, data['new_data'],
                                   approval.requested_by, 'UPDATED')
                ticket_no = ticket.ticket_no
                log.info('EDIT approved: ticket=%s by=%s', ticket.ticket_no, admin_username)

        elif approval.request_type == 'DELETE':
            ticket = approval.ticket
            if ticket:
                ticket.deleted_flag = True
                ticket.delete_requested = False
                db.session.flush()
                log_ticket_deleted(ticket, approval.requested_by)
                ticket_no = ticket.ticket_no
                log.info('DELETE approved: ticket=%s by=%s', ticket.ticket_no, admin_username)

    elif action == 'reject':
        approval.status = 'REJECTED'
        if approval.request_type == 'DELETE' and approval.ticket:
            approval.ticket.delete_requested = False
        if approval.ticket:
            ticket_no = approval.ticket.ticket_no
        log.info('Request rejected: approval_id=%s type=%s by=%s',
                 approval.id, approval.request_type, admin_username)

    # Send email notification to requester (non-blocking)
    requester = User.query.filter_by(username=approval.requested_by).first()
    if requester and requester.email:
        send_approval_notification(
            requester.username, requester.email,
            action, approval.request_type, ticket_no, comments
        )

    return ticket_no


@approvals_bp.route('/approvals')
@login_required
@admin_required
def pending_approvals():
    pending = ApprovalRequest.query.filter_by(status='PENDING').order_by(
        ApprovalRequest.requested_at.desc()
    ).all()
    return render_template('pending_approvals.html', approvals=pending)


@approvals_bp.route('/approvals/<int:approval_id>')
@login_required
@admin_required
def approval_details(approval_id):
    approval = ApprovalRequest.query.get_or_404(approval_id)
    data = approval.get_request_data()
    ticket = approval.ticket

    diff = None
    if approval.request_type == 'EDIT' and 'changed_fields' in data:
        diff = []
        old_data = data.get('old_data', {})
        new_data = data.get('new_data', {})
        for field in data['changed_fields']:
            diff.append({
                'label': FIELD_LABELS.get(field, field),
                'old': old_data.get(field, ''),
                'new': new_data.get(field, ''),
            })

    return render_template('approval_details.html',
        approval=approval,
        data=data,
        ticket=ticket,
        diff=diff,
        field_labels=FIELD_LABELS,
    )


@approvals_bp.route('/approvals/<int:approval_id>/action', methods=['POST'])
@login_required
@admin_required
def approval_action(approval_id):
    approval = ApprovalRequest.query.get_or_404(approval_id)
    if approval.status != 'PENDING':
        flash('This request has already been processed.', 'warning')
        return redirect(url_for('approvals.pending_approvals'))

    action = request.form.get('action')
    comments = request.form.get('comments', '').strip()

    if action not in ('approve', 'reject'):
        flash('Invalid action.', 'danger')
        return redirect(url_for('approvals.pending_approvals'))

    _process_single_approval(approval, action, current_user.username, comments)
    db.session.commit()

    if action == 'approve':
        type_msg = {'ADD': 'Ticket created.', 'EDIT': 'Ticket updated.', 'DELETE': 'Ticket deleted.'}
        flash(f'{approval.request_type} request approved. {type_msg.get(approval.request_type, "")}', 'success')
    else:
        flash('Request rejected.', 'info')

    return redirect(url_for('approvals.pending_approvals'))


@approvals_bp.route('/approvals/bulk-action', methods=['POST'])
@login_required
@admin_required
def bulk_approval_action():
    approval_ids = request.form.getlist('approval_ids')
    action = request.form.get('action')

    if action not in ('approve', 'reject'):
        flash('Invalid action.', 'danger')
        return redirect(url_for('approvals.pending_approvals'))

    if not approval_ids:
        flash('No approvals selected.', 'warning')
        return redirect(url_for('approvals.pending_approvals'))

    processed = 0
    for aid in approval_ids:
        try:
            approval = ApprovalRequest.query.get(int(aid))
            if approval and approval.status == 'PENDING':
                _process_single_approval(approval, action, current_user.username, '')
                processed += 1
        except Exception as e:
            log.error('Bulk action failed for id=%s: %s', aid, e)
            db.session.rollback()

    db.session.commit()
    flash(f'{processed} request(s) {action}d successfully.', 'success')
    return redirect(url_for('approvals.pending_approvals'))
