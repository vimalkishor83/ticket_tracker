import os
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from flask import Flask, redirect, url_for, send_from_directory
from config import Config
from db import db, login_manager, mail


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


def _run_migrations(app):
    """Add new columns to existing tables idempotently.

    SQL SERVER MIGRATION NOTE: this whole approach (raw ALTER TABLE run on
    every startup, relying on the DB driver to error out when a column/index
    already exists) is SQLite-idiomatic. On SQL Server:
    - "CREATE INDEX IF NOT EXISTS" is not valid syntax -- use
      "IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = '...') CREATE INDEX ..."
      or a T-SQL guard block.
    - "ALTER TABLE ... ADD COLUMN" is SQLite syntax; SQL Server uses
      "ALTER TABLE tickets ADD assigned_to VARCHAR(64)" (no "COLUMN" keyword),
      and re-running it will raise a real error (column already exists) rather
      than something you can blanket try/except -- check
      INFORMATION_SCHEMA.COLUMNS first instead of relying on exception swallowing.
    - Prefer a real migration tool (e.g. Flask-Migrate/Alembic) over this
      idempotent-by-retry pattern once on a database that isn't file-based.
    """
    migrations = [
        "ALTER TABLE tickets ADD COLUMN assigned_to VARCHAR(64)",
        "CREATE INDEX IF NOT EXISTS ix_tickets_status ON tickets (status)",
        "CREATE INDEX IF NOT EXISTS ix_tickets_planned_month ON tickets (planned_month)",
        "CREATE INDEX IF NOT EXISTS ix_tickets_deleted_flag ON tickets (deleted_flag)",
        "CREATE INDEX IF NOT EXISTS ix_tickets_ticket_type ON tickets (ticket_type)",
        "CREATE INDEX IF NOT EXISTS ix_tickets_assigned_to ON tickets (assigned_to)",
    ]
    with app.app_context():
        for sql in migrations:
            try:
                db.session.execute(db.text(sql))
                db.session.commit()
            except Exception:
                db.session.rollback()


def _create_first_admin():
    """Create the first Admin user from environment variables, if none exists
    yet and the required variables are set. Never hardcodes a username or
    password -- if ADMIN_USERNAME/ADMIN_EMAIL/ADMIN_PASSWORD aren't all set,
    this silently does nothing (fails closed: no default account is ever
    created), and an operator sets up the first admin by setting these
    variables once and restarting the app."""
    from models.user import User

    if User.query.first():
        return

    username = os.environ.get('ADMIN_USERNAME')
    email = os.environ.get('ADMIN_EMAIL')
    password = os.environ.get('ADMIN_PASSWORD')
    if not (username and email and password):
        logging.getLogger(__name__).warning(
            'No users exist yet and ADMIN_USERNAME/ADMIN_EMAIL/ADMIN_PASSWORD '
            'are not all set -- skipping first-admin creation. Set all three '
            'and restart the app to create the first admin account.'
        )
        return

    admin = User(
        username=username,
        email=email,
        role='Admin',
        active_flag=True,
        force_password_change=False,
    )
    admin.set_password(password)
    db.session.add(admin)
    db.session.commit()
    logging.getLogger(__name__).info('First admin created: username=%s', username)


def create_app():
    app = Flask(__name__)
    # Behind a reverse proxy under a path prefix (Caddy sets X-Forwarded-Prefix). No effect when served at root.
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
    app.config.from_object(Config)

    # Ensure database directory exists
    os.makedirs(os.path.join(os.path.dirname(__file__), 'database'), exist_ok=True)

    # Init extensions
    db.init_app(app)
    login_manager.init_app(app)
    mail.init_app(app)
    login_manager.login_view = 'auth.login'
    login_manager.login_message_category = 'warning'

    # Register blueprints
    from routes.auth import auth_bp
    from routes.dashboard import dashboard_bp
    from routes.tickets import tickets_bp
    from routes.approvals import approvals_bp
    from routes.admin import admin_bp
    from routes.comments import comments_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(tickets_bp)
    app.register_blueprint(approvals_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(comments_bp)

    # Shared, pre-built library files (Bootstrap, Chart.js), bind-mounted
    # read-only at /common-static from the host's
    # /home/claudedev/office/common-static -- one copy shared across office
    # apps instead of each app vendoring its own from a CDN.
    common_static_dir = os.environ.get("COMMON_STATIC_DIR", "/common-static")

    @app.route("/common-static/<path:filename>")
    def common_static(filename):
        return send_from_directory(common_static_dir, filename)

    # Create tables
    with app.app_context():
        # Import models to ensure they are registered
        from models.user import User
        from models.ticket import Ticket
        from models.history import TicketHistory
        from models.approval import ApprovalRequest
        from models.settings import SystemSettings
        from models.comment import TicketComment

        db.create_all()
        _run_migrations(app)
        _create_first_admin()

    return app


app = create_app()


@app.route('/')
def root():
    return redirect(url_for('dashboard.index'))


if __name__ == '__main__':
    app.run(debug=True, host='127.0.0.3', port=5000)
