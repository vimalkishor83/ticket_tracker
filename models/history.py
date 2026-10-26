from db import db
from datetime import datetime


class TicketHistory(db.Model):
    __tablename__ = 'ticket_history'

    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey('tickets.id'), nullable=False)
    action = db.Column(db.String(20))  # CREATED / UPDATED / DELETED / RESTORED
    field_name = db.Column(db.String(100))
    old_value = db.Column(db.Text)
    new_value = db.Column(db.Text)
    changed_by = db.Column(db.String(64))
    changed_at = db.Column(db.DateTime, default=datetime.utcnow)

    # so you can do history_row.ticket to get the Ticket this row belongs to
    ticket = db.relationship('Ticket', overlaps="history")
