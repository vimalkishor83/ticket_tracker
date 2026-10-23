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


def _send_token_email(user, label, subject, intro):
    token = generate_token(user.email)
    url = url_for('auth.set_password', token=token, _external=True)
    body = f"""Hello {user.username},

{intro}

{url}

This link expires in 24 hours.

Regards,
Ticket Tracker Team
"""
    try:
        msg = Message(subject=subject, recipients=[user.email], body=body)
        mail.send(msg)
        log.info('%s email sent: user=%s', label, user.username)
        return True
    except Exception as e:
        log.error('%s email failed: user=%s error=%s', label, user.username, e)
        return False


def send_set_password_email(user):
    return _send_token_email(
        user, 'Set-password', 'Ticket Tracker – Set Your Password',
        'Your Ticket Tracker account has been created.\n'
        'Please click the link below to set your password:'
    )


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
    return _send_token_email(
        user, 'Reset-password', 'Ticket Tracker – Password Reset',
        'You requested a password reset.\n'
        'Please click the link below to set a new password:'
    )
