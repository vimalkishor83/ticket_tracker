import logging
from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from db import db
from models.user import User
from models.ticket import Ticket
from models.settings import SystemSettings
from services.history_service import log_ticket_restored
from functools import wraps
from datetime import datetime

admin_bp = Blueprint('admin', __name__)
log = logging.getLogger(__name__)


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin():
            flash('Admin access required.', 'danger')
            return redirect(url_for('dashboard.index'))
        return f(*args, **kwargs)
    return decorated


@admin_bp.route('/admin/users')
@login_required
@admin_required
def users():
    all_users = User.query.order_by(User.created_at.desc()).all()
    return render_template('users.html', users=all_users)


@admin_bp.route('/admin/users/<int:user_id>/toggle-active', methods=['POST'])
@login_required
@admin_required
def toggle_active(user_id):
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash('You cannot deactivate yourself.', 'danger')
        return redirect(url_for('admin.users'))
    user.active_flag = not user.active_flag
    db.session.commit()
    status = 'activated' if user.active_flag else 'deactivated'
    log.info('User %s: by=%s', status, current_user.username)
    flash(f'User {user.username} has been {status}.', 'success')
    return redirect(url_for('admin.users'))


@admin_bp.route('/admin/users/<int:user_id>/promote', methods=['POST'])
@login_required
@admin_required
def promote_user(user_id):
    user = User.query.get_or_404(user_id)
    user.role = 'Admin' if user.role == 'User' else 'User'
    db.session.commit()
    log.info('Role changed: user=%s new_role=%s by=%s', user.username, user.role, current_user.username)
    flash(f'User {user.username} role set to {user.role}.', 'success')
    return redirect(url_for('admin.users'))


@admin_bp.route('/admin/users/<int:user_id>/reset-password', methods=['POST'])
@login_required
@admin_required
def reset_password(user_id):
    from services.email_service import send_reset_password_email
    user = User.query.get_or_404(user_id)
    sent = send_reset_password_email(user)
    if sent:
        flash(f'Password reset email sent to {user.email}.', 'success')
    else:
        flash('Could not send email. Check mail config.', 'warning')
    return redirect(url_for('admin.users'))

@admin_bp.route('/admin/freeze', methods=['GET', 'POST'])
@login_required
@admin_required
def freeze_settings():
    settings = SystemSettings.query.first()
    if request.method == 'POST':
        freeze_date_str = request.form.get('freeze_date', '').strip()
        freeze_date = None
        if freeze_date_str:
            try:
                freeze_date = datetime.strptime(freeze_date_str, '%Y-%m-%d').date()
            except ValueError:
                flash('Invalid date format.', 'danger')
                return render_template('freeze_settings.html', settings=settings)

        if settings:
            settings.freeze_date = freeze_date
            settings.updated_by = current_user.username
            settings.updated_at = datetime.utcnow()
        else:
            settings = SystemSettings(
                freeze_date=freeze_date,
                updated_by=current_user.username
            )
            db.session.add(settings)
        db.session.commit()
        log.info('Freeze date set to %s by=%s', freeze_date, current_user.username)
        flash('Freeze date updated successfully.', 'success')
        return redirect(url_for('admin.freeze_settings'))

    return render_template('freeze_settings.html', settings=settings)


@admin_bp.route('/admin/deleted-tickets')
@login_required
@admin_required
def deleted_tickets():
    tickets = Ticket.query.filter_by(deleted_flag=True).order_by(Ticket.updated_at.desc()).all()
    return render_template('deleted_tickets.html', tickets=tickets)


@admin_bp.route('/admin/restore/<int:ticket_id>', methods=['POST'])
@login_required
@admin_required
def restore_ticket(ticket_id):
    ticket = Ticket.query.filter_by(id=ticket_id, deleted_flag=True).first_or_404()
    ticket.deleted_flag = False
    ticket.delete_requested = False
    db.session.commit()
    log_ticket_restored(ticket, current_user.username)
    log.info('Ticket restored: ticket=%s by=%s', ticket.ticket_no, current_user.username)
    flash(f'Ticket {ticket.ticket_no} has been restored.', 'success')
    return redirect(url_for('admin.deleted_tickets'))


@admin_bp.route('/admin/analytics')
@login_required
@admin_required
def analytics():
    from sqlalchemy import func

    # SQL SERVER MIGRATION NOTE: func.strftime(...) below compiles to SQLite's
    # strftime() function, which does not exist on SQL Server. Replace with
    # func.format(Ticket.created_at, 'yyyy-MM') (SQL Server's FORMAT()) or
    # a CONVERT()-based equivalent when moving databases.
    monthly = db.session.query(
        func.strftime('%Y-%m', Ticket.created_at).label('month'),
        func.count(Ticket.id)
    ).filter(Ticket.deleted_flag == False).group_by('month').order_by('month').all()

    effort_by_month = db.session.query(
        Ticket.planned_month,
        func.sum(Ticket.planned_efforts),
        func.sum(Ticket.utilized_efforts)
    ).filter(
        Ticket.deleted_flag == False,
        Ticket.planned_month.isnot(None)
    ).group_by(Ticket.planned_month).all()

    by_type = db.session.query(
        Ticket.ticket_type,
        func.count(Ticket.id)
    ).filter(Ticket.deleted_flag == False).group_by(Ticket.ticket_type).all()

    by_status = db.session.query(
        Ticket.status,
        func.count(Ticket.id)
    ).filter(Ticket.deleted_flag == False).group_by(Ticket.status).all()

    return render_template('admin_analytics.html',
        monthly_labels=[r[0] for r in monthly],
        monthly_counts=[r[1] for r in monthly],
        effort_months=[r[0] for r in effort_by_month],
        effort_planned=[float(r[1] or 0) for r in effort_by_month],
        effort_utilized=[float(r[2] or 0) for r in effort_by_month],
        type_labels=[r[0] or 'Unset' for r in by_type],
        type_counts=[r[1] for r in by_type],
        status_labels=[r[0] for r in by_status],
        status_counts=[r[1] for r in by_status],
    )
