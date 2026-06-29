from db import db
from datetime import datetime


class Ticket(db.Model):
    __tablename__ = 'tickets'

    id = db.Column(db.Integer, primary_key=True)
    ticket_no = db.Column(db.String(50), nullable=False, unique=True)
    ticket_type = db.Column(db.String(50))
    service = db.Column(db.String(100))
    description = db.Column(db.Text)
    status = db.Column(db.String(30), default='Open')
    planned_month = db.Column(db.String(20))
    actual_implementation_month = db.Column(db.String(20))
    planned_efforts = db.Column(db.Float, default=0)
    utilized_efforts = db.Column(db.Float, default=0)
    approved_by = db.Column(db.String(100))
    estimated_uat = db.Column(db.Date)
    estimated_prod = db.Column(db.Date)
    actual_uat = db.Column(db.Date)
    actual_prod = db.Column(db.Date)
    revised_uat_date = db.Column(db.Date)
    revised_prod_date = db.Column(db.Date)
    exception_from = db.Column(db.String(200))
    business_benefits = db.Column(db.Text)
    remarks = db.Column(db.Text)

    assigned_to = db.Column(db.String(64), nullable=True)

    # Soft delete
    deleted_flag = db.Column(db.Boolean, default=False)
    delete_requested = db.Column(db.Boolean, default=False)
    delete_requested_by = db.Column(db.String(64))
    delete_requested_date = db.Column(db.DateTime)

    created_by = db.Column(db.String(64))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        db.Index('ix_tickets_status', 'status'),
        db.Index('ix_tickets_planned_month', 'planned_month'),
        db.Index('ix_tickets_deleted_flag', 'deleted_flag'),
        db.Index('ix_tickets_ticket_type', 'ticket_type'),
        db.Index('ix_tickets_assigned_to', 'assigned_to'),
    )

    def to_dict(self):
        def fmt_date(d):
            return d.strftime('%Y-%m-%d') if d else None

        return {
            'id': self.id,
            'ticket_no': self.ticket_no,
            'ticket_type': self.ticket_type,
            'service': self.service,
            'description': self.description,
            'status': self.status,
            'planned_month': self.planned_month,
            'actual_implementation_month': self.actual_implementation_month,
            'planned_efforts': self.planned_efforts,
            'utilized_efforts': self.utilized_efforts,
            'approved_by': self.approved_by,
            'estimated_uat': fmt_date(self.estimated_uat),
            'estimated_prod': fmt_date(self.estimated_prod),
            'actual_uat': fmt_date(self.actual_uat),
            'actual_prod': fmt_date(self.actual_prod),
            'revised_uat_date': fmt_date(self.revised_uat_date),
            'revised_prod_date': fmt_date(self.revised_prod_date),
            'exception_from': self.exception_from,
            'business_benefits': self.business_benefits,
            'remarks': self.remarks,
            'assigned_to': self.assigned_to,
            'deleted_flag': self.deleted_flag,
            'created_by': self.created_by,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else None,
        }

    def __repr__(self):
        return f'<Ticket {self.ticket_no}>'
