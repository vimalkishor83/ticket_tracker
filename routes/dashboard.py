from flask import Blueprint, render_template, request
from flask_login import login_required
from db import db
from models.ticket import Ticket
from models.approval import ApprovalRequest
from sqlalchemy import func
from services.ticket_constants import STATUSES, TICKET_TYPES
from services.excel_export import dataframe_to_xlsx_response
from datetime import datetime

dashboard_bp = Blueprint('dashboard', __name__)


from services.date_utils import fmt_date_display as _fmt_date_display, fmt_datetime_display


def fmt_date_display(d):
    return _fmt_date_display(d, empty='')


def _build_query(search_no, search_desc, filter_month, filter_status, filter_ticket_type):
    query = Ticket.query.filter_by(deleted_flag=False)
    if search_no:
        query = query.filter(Ticket.ticket_no.ilike(f'%{search_no}%'))
    if search_desc:
        query = query.filter(Ticket.description.ilike(f'%{search_desc}%'))
    if filter_month:
        query = query.filter(Ticket.planned_month == filter_month)
    if filter_status:
        query = query.filter(Ticket.status == filter_status)
    if filter_ticket_type:
        query = query.filter(Ticket.ticket_type == filter_ticket_type)
    return query


@dashboard_bp.route('/')
@login_required
def index():
    search_no = request.args.get('search_no', '').strip()
    search_desc = request.args.get('search_desc', '').strip()
    filter_month = request.args.get('filter_month', '').strip()
    filter_status = request.args.get('filter_status', '').strip()
    filter_ticket_type = request.args.get('filter_ticket_type', '').strip()
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 25, type=int)
    if per_page not in (25, 50, 100):
        per_page = 25

    query = _build_query(search_no, search_desc, filter_month, filter_status,
                         filter_ticket_type)
    tickets = query.order_by(Ticket.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    # Effort totals: current page (in-memory) + all filtered (SQL aggregate)
    page_planned_total  = sum(t.planned_efforts or 0 for t in tickets.items)
    page_utilized_total = sum(t.utilized_efforts or 0 for t in tickets.items)

    # same filters as `query` above, just summing instead of listing rows
    effort_row = query.with_entities(
        func.sum(Ticket.planned_efforts),
        func.sum(Ticket.utilized_efforts)
    ).first()
    all_planned_total  = float(effort_row[0] or 0)
    all_utilized_total = float(effort_row[1] or 0)
    all_variance_total = all_planned_total - all_utilized_total

    # Dashboard counts — single grouped query instead of 6 separate counts
    status_counts = db.session.query(
        Ticket.status, func.count(Ticket.id)
    ).filter(Ticket.deleted_flag == False).group_by(Ticket.status).all()
    sc = {row[0]: row[1] for row in status_counts}
    total            = sum(sc.values())
    open_count       = sc.get('Open', 0)
    closed_count     = sc.get('Closed', 0)
    inprogress_count = sc.get('In Progress', 0)
    uat_count        = sc.get('UAT', 0)
    onhold_count     = sc.get('On Hold', 0)

    # Pending approval counts — single grouped query
    pending_counts = db.session.query(
        ApprovalRequest.request_type, func.count(ApprovalRequest.id)
    ).filter_by(status='PENDING').group_by(ApprovalRequest.request_type).all()
    pc = {r[0]: r[1] for r in pending_counts}
    pending_add    = pc.get('ADD', 0)
    pending_edit   = pc.get('EDIT', 0)
    pending_delete = pc.get('DELETE', 0)

    months_used = db.session.query(Ticket.planned_month).filter(
        Ticket.planned_month.isnot(None), Ticket.deleted_flag == False
    ).distinct().all()
    months_used = [m[0] for m in months_used if m[0]]

    return render_template('dashboard.html',
        tickets=tickets,
        total=total,
        open_count=open_count,
        closed_count=closed_count,
        inprogress_count=inprogress_count,
        uat_count=uat_count,
        onhold_count=onhold_count,
        pending_add=pending_add,
        pending_edit=pending_edit,
        pending_delete=pending_delete,
        months=months_used,
        statuses=STATUSES,
        ticket_types=TICKET_TYPES,
        search_no=search_no,
        search_desc=search_desc,
        filter_month=filter_month,
        filter_status=filter_status,
        filter_ticket_type=filter_ticket_type,
        per_page=per_page,
        page_planned_total=page_planned_total,
        page_utilized_total=page_utilized_total,
        all_planned_total=all_planned_total,
        all_utilized_total=all_utilized_total,
        all_variance_total=all_variance_total,
        fmt_date=fmt_date_display,
    )


@dashboard_bp.route('/export')
@login_required
def export():
    search_no          = request.args.get('search_no', '').strip()
    search_desc        = request.args.get('search_desc', '').strip()
    filter_month       = request.args.get('filter_month', '').strip()
    filter_status      = request.args.get('filter_status', '').strip()
    filter_ticket_type = request.args.get('filter_ticket_type', '').strip()

    tickets = _build_query(
        search_no, search_desc, filter_month, filter_status, filter_ticket_type
    ).order_by(Ticket.created_at.desc()).all()

    def fd(d):
        return _fmt_date_display(d, empty='')

    data = []
    for t in tickets:
        data.append({
            'Ticket No': t.ticket_no,
            'Type': t.ticket_type,
            'Service': t.service,
            'Description': t.description,
            'Status': t.status,
            'Planned Month': t.planned_month,
            'Actual Impl. Month': t.actual_implementation_month,
            'Planned Efforts': t.planned_efforts,
            'Utilized Efforts': t.utilized_efforts,
            'Approved By': t.approved_by,
            'Est. UAT': fd(t.estimated_uat),
            'Est. Prod': fd(t.estimated_prod),
            'Actual UAT': fd(t.actual_uat),
            'Actual Prod': fd(t.actual_prod),
            'Revised UAT': fd(t.revised_uat_date),
            'Revised Prod': fd(t.revised_prod_date),
            'Exception From': t.exception_from,
            'Business Benefits': t.business_benefits,
            'Remarks': t.remarks,
            'Created By': t.created_by,
            'Created At': fmt_datetime_display(t.created_at, empty=''),
        })

    filename = f'tickets_{datetime.now().strftime("%Y%m%d_%H%M%S")}.xlsx'
    return dataframe_to_xlsx_response(data, filename)
