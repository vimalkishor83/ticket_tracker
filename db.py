from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_mail import Mail

db = SQLAlchemy()
login_manager = LoginManager()
mail = Mail()

SQLSERVER_SCHEMA = "ticket_tracker"


def apply_schema(app):
    """Sets the DB schema for every table; SQLite has no schemas, so skip it there."""
    if not app.config['SQLALCHEMY_DATABASE_URI'].startswith('sqlite'):
        db.metadata.schema = SQLSERVER_SCHEMA
