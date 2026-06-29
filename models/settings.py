from db import db
from datetime import datetime


class SystemSettings(db.Model):
    __tablename__ = 'system_settings'

    id = db.Column(db.Integer, primary_key=True)
    freeze_date = db.Column(db.Date)
    updated_by = db.Column(db.String(64))
    updated_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<SystemSettings freeze_date={self.freeze_date}>'
