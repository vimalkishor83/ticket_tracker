import logging
from flask_mail import Message
from db import mail
from flask import current_app, url_for
from itsdangerous import URLSafeTimedSerializer

log = logging.getLogger(__name__)


def generate_token(email):
    s = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
    return s.dumps(email, salt='password-set-salt')


def verify_token(token, expiration=None):
    if expiration is None:
        expiration = current_app.config.get('TOKEN_EXPIRY', 86400)
    s = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
    try:
        email = s.loads(token, salt='password-set-salt', max_age=expiration)
    except Exception:
        return None
    return email


def send_set_password_email(user):
    token = generate_token(user.email)
    set_url = url_for('auth.set_password', token=token, _external=True)
    subject = 'Ticket Tracker – Set Your Password'
    body = f"""Hello {user.username},

Your Ticket Tracker account has been created.
Please click the link below to set your password:

{set_url}

This link expires in 24 hours.

If you did not request this, please ignore this email.

Regards,
Ticket Tracker Team
"""
    try:
        msg = Message(subject=subject, recipients=[user.email], body=body)
        mail.send(msg)
        log.info('Set-password email sent: user=%s', user.username)
        return True
    except Exception as e:
        log.error('Set-password email failed: user=%s error=%s', user.username, e)
        return False


def send_approval_notification(requester_username, requester_email, action,
                               request_type, ticket_no, admin_comments=''):
    subject = f'Ticket Tracker – Your {request_type} request was {action}'
    comments_line = f'\nAdmin comments: {admin_comments}\n' if admin_comments else ''
    body = f"""Hello {requester_username},

Your {request_type} request for ticket {ticket_no} has been {action}.
{comments_line}
Regards,
Ticket Tracker Team
"""
    try:
        msg = Message(subject=subject, recipients=[requester_email], body=body)
        mail.send(msg)
        log.info('Approval notification sent: user=%s action=%s ticket=%s',
                 requester_username, action, ticket_no)
        return True
    except Exception as e:
        log.error('Approval notification failed: user=%s error=%s', requester_username, e)
        return False


def send_reset_password_email(user):
    token = generate_token(user.email)
    reset_url = url_for('auth.set_password', token=token, _external=True)
    subject = 'Ticket Tracker – Password Reset'
    body = f"""Hello {user.username},

You requested a password reset.
Please click the link below to set a new password:

{reset_url}

This link expires in 24 hours.

Regards,
Ticket Tracker Team
"""
    try:
        msg = Message(subject=subject, recipients=[user.email], body=body)
        mail.send(msg)
        log.info('Reset-password email sent: user=%s', user.username)
        return True
    except Exception as e:
        log.error('Reset-password email failed: user=%s error=%s', user.username, e)
        return False
