import logging
from db import db
from models.history import TicketHistory
from datetime import datetime

log = logging.getLogger(__name__)


FIELD_LABELS = {
    'ticket_no': 'Ticket No',
    'ticket_type': 'Ticket Type',
    'service': 'Service',
    'description': 'Description',
    'status': 'Status',
    'planned_month': 'Planned Month',
    'actual_implementation_month': 'Actual Implementation Month',
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
    'deleted_flag': 'Deleted',
}


def log_ticket_created(ticket, changed_by):
    log.info('History: CREATED ticket=%s by=%s', ticket.ticket_no, changed_by)
    h = TicketHistory(
        ticket_id=ticket.id,
        action='CREATED',
        field_name='ticket_no',
        old_value=None,
        new_value=ticket.ticket_no,
        changed_by=changed_by,
        changed_at=datetime.utcnow()
    )
    db.session.add(h)
    db.session.commit()


def log_ticket_changes(ticket_id, old_data, new_data, changed_by, action='UPDATED'):
    def fmt(val):
        if val is None:
            return ''
        return str(val)

    for field in FIELD_LABELS.keys():
        old_val = old_data.get(field)
        new_val = new_data.get(field)
        if str(old_val or '') != str(new_val or ''):
            h = TicketHistory(
                ticket_id=ticket_id,
                action=action,
                field_name=field,
                old_value=fmt(old_val),
                new_value=fmt(new_val),
                changed_by=changed_by,
                changed_at=datetime.utcnow()
            )
            db.session.add(h)
    db.session.commit()


def log_ticket_deleted(ticket, changed_by):
    log.info('History: DELETED ticket=%s by=%s', ticket.ticket_no, changed_by)
    h = TicketHistory(
        ticket_id=ticket.id,
        action='DELETED',
        field_name='deleted_flag',
        old_value='False',
        new_value='True',
        changed_by=changed_by,
        changed_at=datetime.utcnow()
    )
    db.session.add(h)
    db.session.commit()


def log_ticket_restored(ticket, changed_by):
    log.info('History: RESTORED ticket=%s by=%s', ticket.ticket_no, changed_by)
    h = TicketHistory(
        ticket_id=ticket.id,
        action='RESTORED',
        field_name='deleted_flag',
        old_value='True',
        new_value='False',
        changed_by=changed_by,
        changed_at=datetime.utcnow()
    )
    db.session.add(h)
    db.session.commit()
