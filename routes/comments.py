import logging
from flask import Blueprint, redirect, url_for, flash, request
from flask_login import login_required, current_user
from db import db
from models.ticket import Ticket
from models.comment import TicketComment

comments_bp = Blueprint('comments', __name__)
log = logging.getLogger(__name__)


@comments_bp.route('/tickets/<int:ticket_id>/comments/add', methods=['POST'])
@login_required
def add_comment(ticket_id):
    ticket = Ticket.query.filter_by(id=ticket_id, deleted_flag=False).first_or_404()
    body = request.form.get('body', '').strip()

    if not body:
        flash('Comment cannot be empty.', 'danger')
        return redirect(url_for('tickets.view_ticket', ticket_id=ticket_id))

    if len(body) > 2000:
        flash('Comment is too long (max 2000 characters).', 'danger')
        return redirect(url_for('tickets.view_ticket', ticket_id=ticket_id))

    comment = TicketComment(
        ticket_id=ticket.id,
        body=body,
        created_by=current_user.username,
    )
    db.session.add(comment)
    db.session.commit()
    log.info('Comment added: ticket=%s by=%s', ticket.ticket_no, current_user.username)
    flash('Comment added.', 'success')
    return redirect(url_for('tickets.view_ticket', ticket_id=ticket_id))


@comments_bp.route('/tickets/<int:ticket_id>/comments/<int:comment_id>/delete', methods=['POST'])
@login_required
def delete_comment(ticket_id, comment_id):
    comment = TicketComment.query.filter_by(id=comment_id, ticket_id=ticket_id).first_or_404()

    if comment.created_by != current_user.username and not current_user.is_admin():
        flash('You can only delete your own comments.', 'danger')
        return redirect(url_for('tickets.view_ticket', ticket_id=ticket_id))

    db.session.delete(comment)
    db.session.commit()
    log.info('Comment deleted: id=%s ticket=%s by=%s', comment_id, ticket_id, current_user.username)
    flash('Comment deleted.', 'info')
    return redirect(url_for('tickets.view_ticket', ticket_id=ticket_id))
