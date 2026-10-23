import logging
from db import db
from models.history import TicketHistory
from services.field_labels import FIELD_LABELS
from services.time_utils import utcnow_naive

log = logging.getLogger(__name__)


def _log_simple(ticket, action, field_name, old_value, new_value, changed_by):
    log.info('History: %s ticket=%s by=%s', action, ticket.ticket_no, changed_by)
    h = TicketHistory(
        ticket_id=ticket.id,
        action=action,
        field_name=field_name,
        old_value=old_value,
        new_value=new_value,
        changed_by=changed_by,
        changed_at=utcnow_naive()
    )
    db.session.add(h)
    db.session.commit()


def log_ticket_created(ticket, changed_by):
    _log_simple(ticket, 'CREATED', 'ticket_no', None, ticket.ticket_no, changed_by)


def log_ticket_changes(ticket_id, old_data, new_data, changed_by, action='UPDATED'):
    def fmt(val):
        if val is None:
            return ''
        return str(val)

    for field in FIELD_LABELS.keys():
        old_val = old_data.get(field)
        new_val = new_data.get(field)
        if fmt(old_val) != fmt(new_val):
            h = TicketHistory(
                ticket_id=ticket_id,
                action=action,
                field_name=field,
                old_value=fmt(old_val),
                new_value=fmt(new_val),
                changed_by=changed_by,
                changed_at=utcnow_naive()
            )
            db.session.add(h)
    db.session.commit()


def log_ticket_deleted(ticket, changed_by):
    _log_simple(ticket, 'DELETED', 'deleted_flag', 'False', 'True', changed_by)


def log_ticket_restored(ticket, changed_by):
    _log_simple(ticket, 'RESTORED', 'deleted_flag', 'True', 'False', changed_by)
