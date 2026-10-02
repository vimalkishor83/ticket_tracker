from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_mail import Mail

db = SQLAlchemy()
login_manager = LoginManager()
mail = Mail()

# UAT/Prod binds this app to its own schema (TicketTracekr) on the shared
# SQL Server database, since all three office apps share one DB login
# (svc_Autom_ams) with no per-app DEFAULT_SCHEMA of its own. Dev/local
# SQLite has no schema concept, so app.py only sets this when the
# configured DATABASE_URI isn't sqlite:///.
SQLSERVER_SCHEMA = "TicketTracekr"
