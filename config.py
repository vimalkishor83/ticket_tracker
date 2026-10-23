import os

import credvault_client

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-production-abc123xyz'
    # SQLite by default; for SQL Server use a driver-based URI (mssql+pyodbc://...)
    SQLALCHEMY_DATABASE_URI = 'sqlite:///' + os.path.join(BASE_DIR, 'database', 'ticket_tracker.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Flask-Mail config (Gmail SMTP)
    MAIL_SERVER = os.environ.get('MAIL_SERVER') or ''
    MAIL_PORT = int(os.environ.get('MAIL_PORT') or 587)
    MAIL_USE_TLS = True
    MAIL_USERNAME = credvault_client.get_credential(
        'ticket_tracker_mail_username', default=os.environ.get('MAIL_USERNAME') or ''
    )
    MAIL_PASSWORD = credvault_client.get_credential(
        'ticket_tracker_mail_password', default=os.environ.get('MAIL_PASSWORD') or ''
    )
    MAIL_DEFAULT_SENDER = os.environ.get('MAIL_DEFAULT_SENDER') or ''

    # Token expiry in seconds (24 hours)
    TOKEN_EXPIRY = 86400
