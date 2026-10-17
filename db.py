from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_mail import Mail

db = SQLAlchemy()
login_manager = LoginManager()
mail = Mail()


def apply_schema(app):
    """Central place to set the DB schema for every table.
    SQLite (local dev) doesn't support schemas, so skip it there.
    """
    if not app.config['SQLALCHEMY_DATABASE_URI'].startswith('sqlite'):
        db.metadata.schema = 'ticket_tracker'
