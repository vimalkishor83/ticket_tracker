import logging
from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, login_required, current_user
from db import db
from models.user import User
from services.email_service import send_set_password_email, send_reset_password_email, verify_token

auth_bp = Blueprint('auth', __name__)
log = logging.getLogger(__name__)


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.index'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password) and user.active_flag:
            log.info('Login success: user=%s', username)
            login_user(user)
            if user.force_password_change:
                flash('Please change your password.', 'warning')
                return redirect(url_for('auth.change_password'))
            next_page = request.args.get('next')
            return redirect(next_page or url_for('dashboard.index'))
        log.warning('Login failed: user=%s', username)
        flash('Invalid username or password.', 'danger')
    return render_template('login.html')


@auth_bp.route('/logout')
@login_required
def logout():
    log.info('Logout: user=%s', current_user.username)
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('auth.login'))


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()

        if not username or not email:
            flash('Username and email are required.', 'danger')
            return render_template('register.html')

        if User.query.filter_by(username=username).first():
            flash('Username already taken.', 'danger')
            return render_template('register.html')

        if User.query.filter_by(email=email).first():
            flash('Email already registered.', 'danger')
            return render_template('register.html')

        user = User(username=username, email=email, role='User', active_flag=True)
        db.session.add(user)
        db.session.commit()

        log.info('User registered: username=%s email=%s', username, email)
        sent = send_set_password_email(user)
        if sent:
            flash('Registration successful! Check your email to set your password.', 'success')
        else:
            log.warning('Set-password email not sent for user=%s', username)
            flash('Account created, but email could not be sent. Contact your admin.', 'warning')
        return redirect(url_for('auth.login'))
    return render_template('register.html')


@auth_bp.route('/set-password/<token>', methods=['GET', 'POST'])
def set_password(token):
    email = verify_token(token)
    if not email:
        flash('The link is invalid or has expired.', 'danger')
        return redirect(url_for('auth.login'))

    user = User.query.filter_by(email=email).first()
    if not user:
        flash('User not found.', 'danger')
        return redirect(url_for('auth.login'))

    if request.method == 'POST':
        password = request.form.get('password', '')
        confirm = request.form.get('confirm_password', '')
        if len(password) < 6:
            flash('Password must be at least 6 characters.', 'danger')
            return render_template('set_password.html', token=token)
        if password != confirm:
            flash('Passwords do not match.', 'danger')
            return render_template('set_password.html', token=token)
        user.set_password(password)
        user.force_password_change = False
        db.session.commit()
        log.info('Password set via token: user=%s', user.username)
        flash('Password set successfully! You can now log in.', 'success')
        return redirect(url_for('auth.login'))
    return render_template('set_password.html', token=token)


@auth_bp.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    if request.method == 'POST':
        current_password = request.form.get('current_password', '')
        new_password = request.form.get('new_password', '')
        confirm = request.form.get('confirm_password', '')

        if not current_user.check_password(current_password):
            flash('Current password is incorrect.', 'danger')
            return render_template('change_password.html')
        if len(new_password) < 6:
            flash('New password must be at least 6 characters.', 'danger')
            return render_template('change_password.html')
        if new_password != confirm:
            flash('Passwords do not match.', 'danger')
            return render_template('change_password.html')

        current_user.set_password(new_password)
        current_user.force_password_change = False
        db.session.commit()
        log.info('Password changed: user=%s', current_user.username)
        flash('Password changed successfully.', 'success')
        return redirect(url_for('dashboard.index'))
    return render_template('change_password.html')


@auth_bp.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        user = User.query.filter_by(email=email).first()
        if user:
            sent = send_reset_password_email(user)
            if sent:
                flash('Password reset email sent.', 'success')
            else:
                flash('Could not send email. Contact your admin.', 'warning')
        else:
            flash('If that email is registered, a reset link has been sent.', 'info')
        return redirect(url_for('auth.login'))
    return render_template('forgot_password.html')
