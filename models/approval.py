from db import db
from datetime import datetime
import json


class ApprovalRequest(db.Model):
    __tablename__ = 'approval_requests'

    id = db.Column(db.Integer, primary_key=True)
    request_type = db.Column(db.String(10), nullable=False)  # ADD / EDIT / DELETE
    ticket_id = db.Column(db.Integer, db.ForeignKey('tickets.id'), nullable=True)
    request_data = db.Column(db.Text)  # JSON
    requested_by = db.Column(db.String(64))
    requested_at = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(10), default='PENDING')  # PENDING / APPROVED / REJECTED
    approved_by = db.Column(db.String(64))
    approved_at = db.Column(db.DateTime)
    comments = db.Column(db.Text)

    ticket = db.relationship('Ticket', backref=db.backref('approvals', lazy='dynamic'))

    def get_request_data(self):
        if self.request_data:
            return json.loads(self.request_data)
        return {}

    def set_request_data(self, data):
        self.request_data = json.dumps(data)

    def __repr__(self):
        return f'<ApprovalRequest {self.request_type} ticket={self.ticket_id}>'
