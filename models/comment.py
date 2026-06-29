from db import db
from datetime import datetime


class TicketComment(db.Model):
    __tablename__ = 'ticket_comments'

    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey('tickets.id'), nullable=False)
    body = db.Column(db.Text, nullable=False)
    created_by = db.Column(db.String(64), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    ticket = db.relationship('Ticket', backref=db.backref(
        'comments', lazy='dynamic', order_by='TicketComment.created_at'
    ))

    __table_args__ = (
        db.Index('ix_comments_ticket_created', 'ticket_id', 'created_at'),
    )

    def __repr__(self):
        return f'<TicketComment ticket={self.ticket_id} by={self.created_by}>'
