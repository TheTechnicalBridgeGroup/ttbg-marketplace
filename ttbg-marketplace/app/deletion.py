"""Explicit, admin-only hard deletion; preserve unrelated records and shared audit provenance."""
import secrets
from flask import Blueprint,abort,flash,redirect,render_template,url_for
from flask_login import current_user
from sqlalchemy import select,or_
from sqlalchemy.exc import IntegrityError
from werkzeug.security import generate_password_hash
from flask_wtf import FlaskForm
from wtforms import StringField,PasswordField
from wtforms.validators import DataRequired,Length
from .models import (db,User,Mentor,Service,Booking,MentorDetails,MentorInvitation,MentorAudit,
    AccountAccess,PasswordLink,PlatformAudit,PhotoSubmission,MentorPhoto,ServiceScheduling,
    MentorIntegration,SupportNote,SupportIncident,SensitiveAttempt,AvailabilityRequest,EmailIdentity)
from .routes import roles
from .security import log
from .control import lock_identity
from .support import reauthenticate

bp=Blueprint('deletion',__name__)
class DeleteAccountForm(FlaskForm):
    confirm_email=StringField('Type the account email to confirm',validators=[DataRequired(),Length(max=254)])
    admin_password=PasswordField('Your admin password',validators=[DataRequired(),Length(max=128)])
    reason=StringField('Reason for permanent deletion',validators=[DataRequired(),Length(min=3,max=300)])

def related_bookings(u):
    terms=[Booking.student_id==u.id]
    if u.mentor:terms.append(Booking.mentor_id==u.mentor.id)
    return Booking.query.filter(or_(*terms))

@bp.route('/admin/users/<int:uid>/delete',methods=['GET','POST'])
@roles('admin')
def delete_account(uid):
    u=db.get_or_404(User,uid)
    if u.role=='archive':abort(404)
    if u.role=='admin':abort(403)
    form=DeleteAccountForm()
    if form.validate_on_submit():
        if not reauthenticate(form.admin_password.data,f'user:{uid}'):
            form.admin_password.errors.append('Your admin password is incorrect.')
        elif form.confirm_email.data.strip().lower()!=u.email.lower():
            form.confirm_email.errors.append('The email does not match this account.')
        elif uid==current_user.id:
            form.confirm_email.errors.append('You cannot delete your own admin account.')
        else:
            lock_identity()
            u=db.session.execute(select(User).where(User.id==uid).with_for_update()).scalar_one_or_none()
            if not u:abort(404)
            # Recheck after acquiring locks; never trust GET state or a client-supplied flag.
            if u.email.lower()!=form.confirm_email.data.strip().lower():abort(409)
            if u.role in ('admin','archive'):abort(403)
            if not form.confirm_email.errors:
                try:
                    purge(u,form.reason.data.strip());db.session.commit()
                except IntegrityError:
                    db.session.rollback();form.confirm_email.errors.append('A linked record changed or prevents deletion. No deletion was applied. Disable the account or review its history.')
                else:
                    flash('Account permanently deleted. Existing sessions and links no longer work.','success')
                    return redirect(url_for('support.home'))
    return render_template('delete_account.html',u=u,form=form,
        booking_count=related_bookings(u).count(),service_count=len(u.mentor.services) if u.mentor else 0)

def purge(u,reason):
    uid=u.id;mid=u.mentor.id if u.mentor else None
    from .models import AcuityRequest,AcuityAppointment,StripeAccount,PaymentOrder,PaymentOperation
    terms=[AcuityRequest.user_id==uid]
    if mid:terms.append(AcuityRequest.service_id.in_([s.id for s in u.mentor.services]))
    request_ids=[r.id for r in AcuityRequest.query.filter(or_(*terms))]
    for order in PaymentOrder.query.filter(PaymentOrder.id.in_(request_ids)):
        order.appointment_payload={};order.hold_reason='account_deleted'
        if order.booking_state=='waiting':order.refund_requested=True
        for op in PaymentOperation.query.filter_by(order_id=order.id,kind='checkout'):
            params=dict(op.params);params.pop('customer_email',None);op.params=params
            if op.state not in ('succeeded','rejected'):
                op.state='manual_review';op.error_code='deleted_identity_reconcile_only'
    if mid:StripeAccount.query.filter_by(mentor_id=mid).update({'mentor_id':None,'ready':False,'status':'account_deleted'},synchronize_session=False)
    bids=[b.id for b in related_bookings(u)]
    if bids:AcuityAppointment.query.filter(AcuityAppointment.booking_id.in_(bids)).update({'identity_removed':True,'email':'','client_name':'','location':''},synchronize_session=False)
    AcuityRequest.query.filter_by(user_id=uid).update({'user_id':None,'email':'','state':'deleted','dedupe_key':None},synchronize_session=False)
    if mid:
        service_ids=[s.id for s in u.mentor.services]
        if service_ids:
            AcuityRequest.query.filter(AcuityRequest.service_id.in_(service_ids)).update({'service_id':None,'dedupe_key':None},synchronize_session=False)
    # A non-login principal holds shared audit attribution. Allocating it before deletion also
    # prevents SQLite from reusing the removed user ID (old session cookies must never resurrect).
    archive=User(name='Deleted account',email=secrets.token_hex(24)+'@deleted.invalid',
                 role='archive',password_hash=generate_password_hash(secrets.token_urlsafe(48)))
    db.session.add(archive);db.session.flush()
    db.session.add(AccountAccess(user_id=archive.id,enabled=False,session_version=1))
    # Remove unpaid test reservations, retain actual financial snapshots without the original account.
    related_bookings(u).filter(Booking.status=='demo_reserved',Booking.payment_status=='not_charged').delete(synchronize_session=False)
    if mid and related_bookings(u).filter(Booking.mentor_id==mid).first():
        retired=Mentor(user_id=archive.id,lane='Archive',title='Deleted mentor',bio='Account deleted.',
                       experience='',status='deleted',is_demo=False)
        db.session.add(retired);db.session.flush()
        service=Service(mentor_id=retired.id,name='Archived service',description='',price_cents=0,active=False)
        db.session.add(service);db.session.flush()
        Booking.query.filter_by(mentor_id=mid).update({'mentor_id':retired.id,'service_id':service.id,'goals':''},synchronize_session=False)
    Booking.query.filter_by(student_id=uid).update({'student_id':archive.id,'goals':''},synchronize_session=False)
    if mid:
        ids=[s.id for s in u.mentor.services]
        if ids:ServiceScheduling.query.filter(ServiceScheduling.service_id.in_(ids)).delete(synchronize_session=False)
        Service.query.filter_by(mentor_id=mid).delete(synchronize_session=False)
        MentorPhoto.query.filter_by(mentor_id=mid).delete(synchronize_session=False)
        PhotoSubmission.query.filter_by(mentor_id=mid).delete(synchronize_session=False)
        for model in (MentorInvitation,MentorIntegration,MentorDetails,MentorAudit):model.query.filter_by(mentor_id=mid).delete(synchronize_session=False)
        Mentor.query.filter_by(id=mid).delete(synchronize_session=False)
    from .models import KnowledgePage
    KnowledgePage.query.filter_by(updated_by=uid).update({'updated_by':archive.id},synchronize_session=False)
    MentorDetails.query.filter_by(owner_id=uid).update({'owner_id':None},synchronize_session=False)
    SupportNote.query.filter_by(user_id=uid).delete(synchronize_session=False)
    SupportNote.query.filter_by(author_id=uid).update({'author_id':archive.id},synchronize_session=False)
    MentorAudit.query.filter_by(actor_id=uid).update({'actor_id':archive.id},synchronize_session=False)
    PlatformAudit.query.filter_by(actor_id=uid).update({'actor_id':archive.id},synchronize_session=False)
    PhotoSubmission.query.filter_by(submitted_by=uid).update({'submitted_by':archive.id},synchronize_session=False)
    PhotoSubmission.query.filter_by(reviewed_by=uid).update({'reviewed_by':archive.id},synchronize_session=False)
    SupportIncident.query.filter_by(user_id=uid).update({'user_id':None},synchronize_session=False)
    SupportIncident.query.filter_by(resolved_by=uid).update({'resolved_by':archive.id},synchronize_session=False)
    for model in (EmailIdentity,PasswordLink,AccountAccess,SensitiveAttempt,AvailabilityRequest):model.query.filter_by(user_id=uid).delete(synchronize_session=False)
    from .models import LoginAttempt
    LoginAttempt.query.filter_by(email=u.email).delete(synchronize_session=False)
    log('Account permanently deleted',f'user:{uid}',reason+' Shared audit attribution retained as deleted account.')
    # Bulk SQL avoids ORM relationships attempting to null already-deleted dependent primary keys.
    db.session.execute(db.delete(User).where(User.id==uid),execution_options={'synchronize_session':False})
