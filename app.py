import os
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from flask import Flask, redirect, url_for
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
    """Add new columns to existing tables idempotently."""
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


def _seed_dummy_data():
    from models.ticket import Ticket
    from datetime import date

    tickets = [
        Ticket(ticket_no='TKT-001', ticket_type='Enhancement', service='Payment Gateway', description='Integrate new payment provider for faster checkout', status='Closed', planned_month='Jan-2026', actual_implementation_month='Jan-2026', planned_efforts=12.0, utilized_efforts=10.5, approved_by='Sarah Johnson', assigned_to='admin', estimated_uat=date(2026,1,10), estimated_prod=date(2026,1,20), actual_uat=date(2026,1,11), actual_prod=date(2026,1,22), business_benefits='Reduces transaction fees by 15%', created_by='admin'),
        Ticket(ticket_no='TKT-002', ticket_type='Bug Fix', service='User Authentication', description='Fix session timeout not working correctly on mobile browsers', status='Closed', planned_month='Jan-2026', actual_implementation_month='Jan-2026', planned_efforts=4.0, utilized_efforts=5.0, approved_by='Mike Chen', assigned_to='admin', estimated_uat=date(2026,1,5), estimated_prod=date(2026,1,8), actual_uat=date(2026,1,6), actual_prod=date(2026,1,9), business_benefits='Improves security compliance', created_by='admin'),
        Ticket(ticket_no='TKT-003', ticket_type='New Feature', service='Reporting', description='Add PDF export functionality to monthly reports dashboard', status='In Progress', planned_month='Feb-2026', planned_efforts=16.0, utilized_efforts=8.0, approved_by='Sarah Johnson', assigned_to='admin', estimated_uat=date(2026,2,15), estimated_prod=date(2026,2,25), business_benefits='Saves 3 hours per month for finance team', created_by='admin'),
        Ticket(ticket_no='TKT-004', ticket_type='Maintenance', service='Database', description='Upgrade PostgreSQL from 14 to 16 and run performance tuning', status='UAT', planned_month='Feb-2026', planned_efforts=8.0, utilized_efforts=9.5, approved_by='Mike Chen', assigned_to='admin', estimated_uat=date(2026,2,10), estimated_prod=date(2026,2,20), actual_uat=date(2026,2,12), remarks='Requires downtime window approval', created_by='admin'),
        Ticket(ticket_no='TKT-005', ticket_type='Enhancement', service='Email Notifications', description='Add HTML templates for transactional emails and unsubscribe link', status='Open', planned_month='Mar-2026', planned_efforts=10.0, utilized_efforts=0.0, approved_by='Lisa Park', assigned_to='admin', estimated_uat=date(2026,3,10), estimated_prod=date(2026,3,20), business_benefits='Improves email open rate by 20%', created_by='admin'),
        Ticket(ticket_no='TKT-006', ticket_type='Bug Fix', service='Inventory', description='Stock count mismatch when concurrent users update same product', status='In Progress', planned_month='Feb-2026', planned_efforts=6.0, utilized_efforts=4.0, approved_by='Sarah Johnson', assigned_to='admin', estimated_uat=date(2026,2,18), estimated_prod=date(2026,2,28), business_benefits='Prevents overselling', created_by='admin'),
        Ticket(ticket_no='TKT-007', ticket_type='New Feature', service='Mobile App', description='Implement push notifications for order status updates', status='On Hold', planned_month='Mar-2026', planned_efforts=20.0, utilized_efforts=0.0, approved_by='Mike Chen', assigned_to='admin', estimated_uat=date(2026,3,20), estimated_prod=date(2026,3,31), remarks='On hold pending vendor API agreement', business_benefits='Reduces customer support calls by 25%', created_by='admin'),
        Ticket(ticket_no='TKT-008', ticket_type='Support', service='User Management', description='Bulk user import failing for CSV files larger than 10MB', status='Closed', planned_month='Jan-2026', actual_implementation_month='Jan-2026', planned_efforts=3.0, utilized_efforts=3.0, approved_by='Lisa Park', assigned_to='admin', estimated_uat=date(2026,1,15), estimated_prod=date(2026,1,16), actual_uat=date(2026,1,15), actual_prod=date(2026,1,16), created_by='admin'),
        Ticket(ticket_no='TKT-009', ticket_type='Enhancement', service='Search', description='Implement Elasticsearch for product search with faceted filtering', status='Open', planned_month='Mar-2026', planned_efforts=24.0, utilized_efforts=0.0, approved_by='Sarah Johnson', assigned_to='admin', estimated_uat=date(2026,3,15), estimated_prod=date(2026,3,28), business_benefits='Search response time improves from 2s to 200ms', created_by='admin'),
        Ticket(ticket_no='TKT-010', ticket_type='Maintenance', service='CDN', description='Migrate static assets to new CDN provider and update cache policies', status='UAT', planned_month='Feb-2026', planned_efforts=5.0, utilized_efforts=5.5, approved_by='Mike Chen', assigned_to='admin', estimated_uat=date(2026,2,20), estimated_prod=date(2026,2,27), actual_uat=date(2026,2,21), business_benefits='Reduces page load time by 30%', created_by='admin'),
        Ticket(ticket_no='TKT-011', ticket_type='Bug Fix', service='Checkout', description='Discount coupon not applying correctly when cart has mixed tax rates', status='Closed', planned_month='Jan-2026', actual_implementation_month='Feb-2026', planned_efforts=5.0, utilized_efforts=7.0, approved_by='Lisa Park', assigned_to='admin', estimated_uat=date(2026,1,28), estimated_prod=date(2026,2,1), actual_uat=date(2026,2,2), actual_prod=date(2026,2,3), exception_from='Finance', business_benefits='Fixes revenue leakage of ~$5k/month', created_by='admin'),
        Ticket(ticket_no='TKT-012', ticket_type='New Feature', service='Analytics', description='Build real-time sales dashboard with live chart updates via WebSocket', status='In Progress', planned_month='Mar-2026', planned_efforts=30.0, utilized_efforts=12.0, approved_by='Sarah Johnson', assigned_to='admin', estimated_uat=date(2026,3,25), estimated_prod=date(2026,4,5), business_benefits='Enables real-time business decisions', created_by='admin'),
        Ticket(ticket_no='TKT-013', ticket_type='Enhancement', service='API', description='Add GraphQL endpoint alongside existing REST API for mobile clients', status='Open', planned_month='Apr-2026', planned_efforts=40.0, utilized_efforts=0.0, approved_by='Mike Chen', assigned_to='admin', estimated_uat=date(2026,4,15), estimated_prod=date(2026,4,25), business_benefits='Reduces mobile data usage by 40%', created_by='admin'),
        Ticket(ticket_no='TKT-014', ticket_type='Support', service='Reporting', description='Monthly revenue report showing incorrect figures for refunded orders', status='Closed', planned_month='Jan-2026', actual_implementation_month='Jan-2026', planned_efforts=2.0, utilized_efforts=2.0, approved_by='Lisa Park', assigned_to='admin', estimated_uat=date(2026,1,20), estimated_prod=date(2026,1,21), actual_uat=date(2026,1,20), actual_prod=date(2026,1,21), created_by='admin'),
        Ticket(ticket_no='TKT-015', ticket_type='Maintenance', service='Security', description='Rotate all API keys and update secret management to HashiCorp Vault', status='In Progress', planned_month='Feb-2026', planned_efforts=6.0, utilized_efforts=3.0, approved_by='Sarah Johnson', assigned_to='admin', estimated_uat=date(2026,2,25), estimated_prod=date(2026,2,28), business_benefits='Meets SOC2 compliance requirements', created_by='admin'),
        Ticket(ticket_no='TKT-016', ticket_type='Bug Fix', service='Payment Gateway', description='Duplicate charge occurring when user double-clicks submit on slow connections', status='UAT', planned_month='Feb-2026', planned_efforts=8.0, utilized_efforts=8.0, approved_by='Mike Chen', assigned_to='admin', estimated_uat=date(2026,2,22), estimated_prod=date(2026,3,1), actual_uat=date(2026,2,23), exception_from='Legal', business_benefits='Prevents financial disputes and chargebacks', created_by='admin'),
        Ticket(ticket_no='TKT-017', ticket_type='New Feature', service='User Management', description='SSO integration with Google Workspace and Microsoft Entra ID', status='Open', planned_month='Apr-2026', planned_efforts=35.0, utilized_efforts=0.0, approved_by='Lisa Park', assigned_to='admin', estimated_uat=date(2026,4,20), estimated_prod=date(2026,4,30), business_benefits='Reduces IT helpdesk password reset tickets by 60%', created_by='admin'),
        Ticket(ticket_no='TKT-018', ticket_type='Enhancement', service='Mobile App', description='Add biometric authentication (Face ID / fingerprint) for app login', status='On Hold', planned_month='Apr-2026', planned_efforts=18.0, utilized_efforts=0.0, approved_by='Sarah Johnson', assigned_to='admin', estimated_uat=date(2026,4,10), estimated_prod=date(2026,4,20), remarks='Awaiting security review sign-off', business_benefits='Improves login speed and user satisfaction', created_by='admin'),
        Ticket(ticket_no='TKT-019', ticket_type='Maintenance', service='Monitoring', description='Set up Grafana dashboards and PagerDuty alerts for all critical services', status='In Progress', planned_month='Mar-2026', planned_efforts=12.0, utilized_efforts=6.0, approved_by='Mike Chen', assigned_to='admin', estimated_uat=date(2026,3,12), estimated_prod=date(2026,3,18), business_benefits='Reduces MTTR from 45 min to 10 min', created_by='admin'),
        Ticket(ticket_no='TKT-020', ticket_type='Bug Fix', service='Search', description='Search results not respecting user locale for date and currency formatting', status='Open', planned_month='Mar-2026', planned_efforts=4.0, utilized_efforts=0.0, approved_by='Lisa Park', assigned_to='admin', estimated_uat=date(2026,3,8), estimated_prod=date(2026,3,12), business_benefits='Fixes UX issues for international users', created_by='admin'),
    ]
    for t in tickets:
        db.session.add(t)
    db.session.commit()
    logging.getLogger(__name__).info('Seeded 20 dummy tickets.')


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

        # Create default admin if no users exist
        if not User.query.first():
            admin = User(
                username='admin',
                email='admin@tickettracker',
                role='Admin',
                active_flag=True,
                force_password_change=False
            )
            admin.set_password('Admin@123')
            db.session.add(admin)
            db.session.commit()
            logging.getLogger(__name__).info('Default admin created: admin / Admin@123')

        # Seed dummy tickets if none exist
        if not Ticket.query.first():
            _seed_dummy_data()

    return app


app = create_app()


@app.route('/')
def root():
    return redirect(url_for('dashboard.index'))


if __name__ == '__main__':
    app.run(debug=True, host='127.0.0.3', port=5000)
