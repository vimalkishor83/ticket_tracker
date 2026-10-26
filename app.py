import os
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from flask import Flask, redirect, url_for, send_from_directory, request
from flask_wtf import CSRFProtect
from config import Config
from db import db, login_manager, mail, apply_schema
from credvault_client import get_credential

csrf = CSRFProtect()


def setup_logging():
    log_dir = Path(__file__).resolve().parent / 'logs'
    log_dir.mkdir(exist_ok=True)

    handler = RotatingFileHandler(
        log_dir / 'application.log',
        maxBytes=5 * 1024 * 1024,
        backupCount=10,
        encoding='utf-8',
    )
    handler.setFormatter(logging.Formatter(
        '%(asctime)s  %(levelname)-8s  %(name)s  %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
    ))

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if not root.handlers:
        root.addHandler(handler)

    logging.getLogger('werkzeug').setLevel(logging.WARNING)


setup_logging()


def _create_first_admin():
    """Create the first admin from env vars if no users exist yet."""
    from models.user import User

    if User.query.first():
        return

    username = os.environ.get('ADMIN_USERNAME')
    email = os.environ.get('ADMIN_EMAIL')
    password = get_credential('ticket_tracker_admin_password', os.environ.get('ADMIN_PASSWORD', ''))
    if not (username and email and password):
        logging.getLogger(__name__).warning(
            'no admin env vars set, skipping admin creation. set ADMIN_USERNAME, '
            'ADMIN_EMAIL, ADMIN_PASSWORD and restart.'
        )
        return

    admin = User(
        username=username,
        email=email,
        role='Admin',
        active_flag=True,
    )
    admin.set_password(password)
    db.session.add(admin)
    db.session.commit()
    logging.getLogger(__name__).info('First admin created: username=%s', username)


def _auto_migrate():
    from sqlalchemy import text, inspect
    try:
        inspector = inspect(db.engine)
        if 'tickets' in inspector.get_table_names():
            cols = {c['name'] for c in inspector.get_columns('tickets')}
            if 'sla_justification' not in cols:
                with db.engine.connect() as conn:
                    conn.execute(text("ALTER TABLE tickets ADD COLUMN sla_justification TEXT"))
                    if 'exception_from' in cols:
                        conn.execute(text("UPDATE tickets SET sla_justification = exception_from WHERE sla_justification IS NULL AND exception_from IS NOT NULL"))
                    conn.commit()
    except Exception as exc:
        logging.getLogger(__name__).warning("Auto-migration notice: %s", exc)


def create_app():
    app = Flask(__name__)
    # Behind a reverse proxy under a path prefix (Caddy sets X-Forwarded-Prefix). No effect when served at root.
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
    app.config.from_object(Config)

    os.makedirs(os.path.join(os.path.dirname(__file__), 'database'), exist_ok=True)

    db.init_app(app)
    apply_schema(app)
    login_manager.init_app(app)
    mail.init_app(app)
    csrf.init_app(app)
    login_manager.login_view = 'auth.login'
    login_manager.login_message_category = 'warning'

    from routes.auth import auth_bp
    from routes.dashboard import dashboard_bp
    from routes.tickets import tickets_bp
    from routes.approvals import approvals_bp
    from routes.admin import admin_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(tickets_bp)
    app.register_blueprint(approvals_bp)
    app.register_blueprint(admin_bp)

    # bootstrap/chart.js etc come from the shared common-static folder, not a CDN
    common_static_dir = os.environ.get("COMMON_STATIC_DIR", "/common-static")

    @app.route("/common-static/<path:filename>")
    def common_static(filename):
        return send_from_directory(common_static_dir, filename)

    from services.date_utils import fmt_datetime_display, fmt_date_only_awst
    app.jinja_env.globals['fmt_dt'] = fmt_datetime_display
    app.jinja_env.globals['fmt_date_awst'] = fmt_date_only_awst

    @app.errorhandler(Exception)
    def log_unhandled_exception(e):
        from werkzeug.exceptions import HTTPException
        if isinstance(e, HTTPException):
            raise e
        logging.getLogger(__name__).exception('Unhandled exception on %s', request.path)
        raise e

    with app.app_context():
        from models.user import User
        from models.ticket import Ticket
        from models.history import TicketHistory
        from models.approval import ApprovalRequest
        from models.settings import SystemSettings

        db.create_all()
        _auto_migrate()
        _create_first_admin()

    return app


app = create_app()


@app.route('/')
def root():
    return redirect(url_for('dashboard.index'))


if __name__ == '__main__':
    app.run(debug=True, host='127.0.0.3', port=5000)
