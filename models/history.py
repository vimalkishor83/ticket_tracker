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

    ticket = db.relationship('Ticket', backref=db.backref('history', lazy='dynamic'))

    def __repr__(self):
        return f'<History ticket={self.ticket_id} field={self.field_name}>'
