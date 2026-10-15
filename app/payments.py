"""TTBG payment UI, signed webhook inbox, and explicit staff money actions."""
import json
import secrets
from datetime import timedelta,timezone
from zoneinfo import ZoneInfo
from flask import Blueprint,abort,current_app,flash,redirect,render_template,request,url_for
from flask_login import current_user,login_required
from flask_wtf import FlaskForm
from sqlalchemy.exc import IntegrityError
from wtforms import PasswordField,StringField,BooleanField,SelectField
from wtforms.validators import DataRequired,Length
from . import acuity
from . import stripe_api as stripe
from . import payment_engine as engine
from .models import db,User,Mentor,MentorIntegration,PaymentOrder,PaymentOperation,StripeAccount,StripeEvent,StripeDispute,AcuityAppointment,now
from .forms import EmptyForm
from .routes import roles
from .security import log,account_enabled
from .support import reauthenticate
from .appointments import write_lock

bp=Blueprint('payments',__name__)
STAFF=('admin','account_manager')
class MoneyForm(FlaskForm):
    from .finance import REASONS
    reason_code=SelectField('Standard reason',choices=REASONS,default='admin_review',validators=[DataRequired()])
    password=PasswordField('Your admin password',validators=[DataRequired(),Length(max=128)])
    reason=StringField('Reason / completion evidence',validators=[DataRequired(),Length(min=8,max=300)])
    confirm=BooleanField('I verified this action. A refund does not cancel an Acuity appointment.',validators=[DataRequired()])
class ObjectForm(MoneyForm):
    object_id=StringField('Verified Stripe object ID',validators=[DataRequired(),Length(max=100)])

class AttachForm(ObjectForm):
    mentor_id=StringField('TTBG mentor ID',validators=[DataRequired(),Length(max=20)])

def error_message(exc):
    if current_user.is_authenticated and current_user.role not in STAFF:
        if isinstance(exc,stripe.StripeError):return 'We could not verify the payment update. Your saved status is shown; contact TTBG before paying again.'
        if isinstance(exc,acuity.AcuityError):return 'We could not refresh the appointment. Please contact TTBG before booking again.'
    return exc.code.replace('_',' ') if isinstance(exc,(stripe.StripeError,acuity.AcuityError)) else str(exc)
def owned(order):
    if order.request.user_id!=current_user.id and current_user.role not in STAFF and not (current_user.mentor and order.account.mentor_id==current_user.mentor.id):abort(403)
    if order.scope!=stripe.scope():abort(409)
def admin_check(form,target):
    if not form.validate_on_submit():return False
    if not reauthenticate(form.password.data,target):form.password.errors.append('Password confirmation failed.');return False
    write_lock();db.session.refresh(current_user._get_current_object())
    if current_user.role!='admin' or not account_enabled(current_user):abort(403)
    db.session.commit();return True

@bp.get('/payments')
@login_required
def history():
    if current_user.role in STAFF:return redirect(url_for('payments.center'))
    q=PaymentOrder.query.filter_by(scope=stripe.scope())
    if current_user.role=='mentor' and current_user.mentor:q=q.join(StripeAccount).filter(StripeAccount.mentor_id==current_user.mentor.id)
    else:q=q.join(PaymentOrder.request).filter_by(user_id=current_user.id)
    page=q.order_by(PaymentOrder.created_at.desc()).paginate(per_page=25,page=request.args.get('page',1,type=int),error_out=False)
    from . import finance
    for order in page.items:finance.observe(order)
    db.session.commit()
    return render_template('payments/history.html',page=page)

@bp.get('/payments/orders/<oid>')
@login_required
def detail(oid):
    order=db.get_or_404(PaymentOrder,oid);owned(order)
    if order.request.user_id==current_user.id and order.payment_state=='unpaid' and order.session_id:
        try:engine.process_order(order)
        except (engine.PaymentProblem,stripe.StripeError,acuity.AcuityError):pass
    ops=PaymentOperation.query.filter_by(order_id=oid).order_by(PaymentOperation.created_at).all()
    from . import finance
    from .financial_routes import CancelForm
    from .models import FinancialEvent,PaymentRefund
    finance.observe(order);db.session.commit()
    event_page=FinancialEvent.query.filter_by(order_id=oid).order_by(FinancialEvent.created_at.desc(),FinancialEvent.id.desc()).paginate(page=max(1,request.args.get('events',1,type=int)),per_page=50,error_out=False)
    events=event_page.items
    refunds=PaymentRefund.query.filter_by(order_id=oid).order_by(PaymentRefund.created_at.desc()).all()
    return render_template('payments/detail_v08.html',o=order,ops=ops,money_form=MoneyForm(),object_form=ObjectForm(prefix='reconcile-'),
        events=events,event_page=event_page,refunds=refunds,cancellations=finance.cancellations(order),review_form=CancelForm(),state=finance.states(order),blocks=finance.action_blocks(order),
        completion_block='' if order.booking and order.booking.status=='confirmed' and order.booking.start+timedelta(minutes=order.booking.duration)<=now() else 'Completion can be reported only after a confirmed session ends.',
        local_start=(order.booking.start if order.booking else order.request.starts_at).replace(tzinfo=timezone.utc).astimezone(ZoneInfo(order.request.timezone)))

@bp.post('/payments/orders/<oid>/refresh')
@login_required
def refresh(oid):
    if not EmptyForm().validate_on_submit():abort(400)
    order=db.get_or_404(PaymentOrder,oid);owned(order)
    from .acuity import throttle
    throttle()
    try:engine.process_order(order);flash('Payment and appointment status refreshed.','success')
    except (engine.PaymentProblem,stripe.StripeError,acuity.AcuityError) as exc:flash(error_message(exc),'error')
    return redirect(url_for('payments.detail',oid=oid))

@bp.post('/payments/orders/<oid>/checkout')
@roles('student')
def checkout(oid):
    if not EmptyForm().validate_on_submit():abort(400)
    order=db.get_or_404(PaymentOrder,oid)
    if order.request.user_id!=current_user.id:abort(403)
    engine.check_scope(order)
    if not engine.enabled():abort(409)
    try:
        engine.refresh_payment(order)
        if order.payment_state!='unpaid' or not order.checkout_url:raise engine.PaymentProblem('Checkout is no longer available. Review the saved status.')
        target=stripe.redirect_url(order.checkout_url,'checkout')
        response=redirect(target,303);response.headers['Referrer-Policy']='no-referrer';return response
    except (stripe.StripeError,engine.PaymentProblem,acuity.AcuityError) as exc:flash(error_message(exc),'error');return redirect(url_for('payments.detail',oid=oid))

@bp.route('/payments/connect',methods=['GET','POST'])
@roles('mentor')
def connect():
    if not current_user.mentor:abort(403)
    row=engine.account_for(current_user.mentor.id);db.session.commit()
    form=EmptyForm()
    if form.validate_on_submit():
        from .acuity import throttle
        throttle()
        try:
            stripe.writable()
            if not row.account_id:
                legacy=current_user.mentor.integration
                if legacy and legacy.stripe_account_id:raise engine.PaymentProblem('An existing Stripe reference needs Admin verification in Support → Payments before onboarding. Ask an Admin to link the correct account for this mode.')
                op=engine.operation('account','account:'+str(row.id),{'country':'US','controller':{'fees':{'payer':'application'},'losses':{'payments':'application'},
                    'requirement_collection':'stripe','stripe_dashboard':{'type':'express'}},'capabilities':{'transfers':{'requested':True}},
                    'metadata':{'ttbg_mentor':str(current_user.mentor.id)},'business_profile':{'product_description':'Mentoring and tutoring sessions through TTBG'}},'accounts',account=row,retry=True)
                engine.execute(op)
            engine.refresh_account(row)
            params={'account':row.account_id,'type':'account_onboarding','return_url':stripe.origin()+'/payments/connect/return','refresh_url':stripe.origin()+'/payments/connect/return'}
            op=engine.operation('account_link','link:'+secrets.token_hex(16),params,'account_links',account=row)
            data=engine.execute(op)
            if stripe.mode()=='mock':flash('Local account created. Use Mark local account ready below to simulate completed onboarding.','success');return redirect(url_for('payments.connect'))
            target=stripe.redirect_url(data.get('url'),'onboarding');response=redirect(target,303);response.headers['Referrer-Policy']='no-referrer';return response
        except (stripe.StripeError,engine.PaymentProblem,acuity.AcuityError) as exc:flash(error_message(exc),'error')
    return render_template('payments/connect.html',account=row,form=form)

@bp.get('/payments/connect/return')
@roles('mentor')
def connect_return():
    row=engine.account_for(current_user.mentor.id)
    try:engine.refresh_account(row);flash('Stripe readiness checked. Returning from onboarding does not by itself confirm approval.','success')
    except (stripe.StripeError,engine.PaymentProblem,acuity.AcuityError) as exc:flash(error_message(exc),'error')
    return redirect(url_for('payments.connect'))

@bp.post('/payments/connect/refresh')
@roles('mentor')
def connect_refresh():
    if not EmptyForm().validate_on_submit():abort(400)
    return connect_return()

@bp.get('/support/payments')
@roles(*STAFF)
def center():
    from .financial_routes import center as financial_center
    return financial_center()

@bp.post('/support/payments/check')
@roles('admin')
def check():
    if not EmptyForm().validate_on_submit():abort(400)
    try:
        a=stripe.api('GET','account')
        if a.get('country')!='US' or a.get('default_currency')!='usd':raise engine.PaymentProblem('This release requires a US Stripe platform settling in USD.')
        log('Stripe connection checked','payments','Account and country/currency verified.');db.session.commit();flash('Stripe account verified. Mentor onboarding and webhook delivery still require testing.','success')
    except (stripe.StripeError,engine.PaymentProblem,acuity.AcuityError) as exc:flash(error_message(exc),'error')
    return redirect(url_for('payments.center'))

@bp.post('/payments/orders/<oid>/complete')
@roles('mentor')
def complete(oid):
    if not EmptyForm().validate_on_submit():abort(400)
    order=db.get_or_404(PaymentOrder,oid);owned(order);b=order.booking
    if order.account.mentor_id!=current_user.mentor.id:abort(403)
    if not b or b.status!='confirmed' or b.start+timedelta(minutes=b.duration)>now():abort(409)
    from . import finance
    finance.emit(order,'completion_reported','requested',reason='Mentor submitted completion for Admin verification.')
    order.completion_reported_at=now();log('Session completion reported','payment:'+oid,'Mentor submitted completion for admin review.');db.session.commit()
    flash('Completion submitted for Admin review. No funds were transferred.','success');return redirect(url_for('payments.detail',oid=oid))

@bp.post('/support/payments/<oid>/<action>')
@roles('admin')
def money_action(oid,action):
    if action not in ('approve_completion','transfer','refund','retry_refund','close_failed','recover_transfer','clear_review'):abort(404)
    order=db.get_or_404(PaymentOrder,oid);engine.check_scope(order);form=MoneyForm()
    from . import finance
    before=finance.states(order)
    if not admin_check(form,'payment:'+oid):
        finance.emit(order,'admin_'+action,'failed',reason='Authorization or form confirmation failed.',error='authorization_failed');db.session.commit()
        flash('Enter your password, a reason, and confirmation. No money action was performed.','error');return redirect(url_for('payments.detail',oid=oid))
    from .models import FinancialEvent
    prior_review=FinancialEvent.query.filter_by(order_id=oid,action='refund_review_requested').order_by(FinancialEvent.id.desc()).first() if action in ('refund','retry_refund') else None
    finance.emit(order,'refund_requested' if action in ('refund','retry_refund') else 'admin_'+action,'requested',requested=prior_review.requested_by if prior_review else finance.actor(),approved=finance.actor(),
        reason=form.reason.data.strip(),reason_code=form.reason_code.data,amount=order.gross_cents-order.refunded_cents if action in ('refund','retry_refund') else order.mentor_cents,before=before)
    db.session.commit()
    if action in ('refund','retry_refund'):order.hold_reason=order.hold_reason or 'refund_review_requested'
    log('Payment action requested: '+action,'payment:'+oid,form.reason.data.strip());db.session.commit()
    try:
        if action=='close_failed':
            op=PaymentOperation.query.filter_by(scope=order.scope,owner_key='checkout:'+oid).first()
            if not op or op.state!='rejected' or order.session_id or order.intent_id:raise engine.PaymentProblem('Only a definitely rejected checkout without a Stripe session can be closed.')
            order.payment_state='expired';order.slot_key=None;order.appointment_payload={};order.request.state='rejected';order.request.dedupe_key=None;db.session.commit()
        else:
            engine.process_order(order,recover=action not in ('retry_refund','recover_transfer'))
            if action=='approve_completion':
                from .appointments import sync_one
                mirror=AcuityAppointment.query.filter_by(request_id=oid).first()
                if not mirror:raise engine.PaymentProblem('A confirmed appointment is required.')
                sync_one(mirror.provider_id);b=order.booking
                if not b or b.status!='confirmed' or b.start+timedelta(minutes=b.duration)>now() or order.payment_state!='paid' or order.refund_requested or order.hold_reason:
                    raise engine.PaymentProblem('Verify the ended session and resolve payment/appointment issues before approval.')
                order.completion_approved_at=now();db.session.commit()
            elif action=='transfer':engine.transfer(order,retry=True)
            elif action=='clear_review':
                if order.hold_reason not in ('dispute','appointment_changed','cancellation_review'):raise engine.PaymentProblem('This hold needs another recovery action.')
                from .appointments import sync_one
                mirror=AcuityAppointment.query.filter_by(request_id=oid).first()
                if not mirror:raise engine.PaymentProblem('Reconcile the appointment first.')
                mirror=sync_one(mirror.provider_id)
                for dispute in StripeDispute.query.filter_by(order_id=oid):
                    data=stripe.api('GET','disputes/'+dispute.id)
                    if data.get('charge')!=order.charge_id or data.get('status') not in ('won','warning_closed'):raise engine.PaymentProblem('An unresolved or lost dispute prevents release.')
                    dispute.status=data['status']
                db.session.commit();engine.refresh_payment(order)
                if mirror.sync_state!='synced' or mirror.cancelled or order.payment_state!='paid' or order.refund_requested or order.refunded_cents or order.reversed_cents:
                    raise engine.PaymentProblem('Appointment, refund, dispute, or recovered-funds review is still required.')
                order.hold_reason='';order.error_code='';order.completion_approved_at=None;db.session.commit()
            elif action=='recover_transfer':
                if order.payment_state not in ('refunded','disputed') and order.hold_reason!='dispute':raise engine.PaymentProblem('Recovery requires a full refund or dispute.')
                engine.recover_transfer(order,retry=True)
            else:
                if order.booking_state in ('creating','uncertain'):raise engine.PaymentProblem('Reconcile the uncertain Acuity appointment before refunding.')
                if action=='retry_refund':
                    op=PaymentOperation.query.filter_by(scope=order.scope,owner_key='refund:'+oid).first()
                    if op and op.response_id:
                        result=stripe.api('GET','refunds/'+op.response_id)
                        if result.get('status') not in ('failed','canceled'):raise engine.PaymentProblem('The refund is not definitively failed; do not create another.')
                        op.state='rejected';order.payment_state='paid';db.session.commit()
                engine.request_refund(order,'admin_refund');engine.refund(order,retry=action=='retry_refund')
        finance.observe(order)
        finance.emit(order,'admin_'+action,('pending' if order.payment_state=='refund_pending' else 'needs_review' if order.payment_state=='refund_failed' else 'succeeded') if action in ('refund','retry_refund') else 'succeeded',approved=finance.actor(),reason=form.reason.data.strip(),reason_code=form.reason_code.data,before=before,after=finance.states(order),provider=order.transfer_id if action=='transfer' else order.charge_id or '')
        log('Payment action: '+action,'payment:'+oid,form.reason.data.strip());db.session.commit();flash('Action processed. Review the saved provider status below.','success')
    except (stripe.StripeError,engine.PaymentProblem,acuity.AcuityError) as exc:
        finance.emit(order,'admin_'+action,'needs_review',approved=finance.actor(),reason=form.reason.data.strip(),reason_code=form.reason_code.data,error=getattr(exc,'code','eligibility_or_recovery_required'),before=before,after=finance.states(order));finance.observe(order);db.session.commit();flash(error_message(exc),'error')
    return redirect(url_for('payments.detail',oid=oid))

@bp.post('/support/payments/operations/<opid>/reconcile')
@roles('admin')
def reconcile(opid):
    op=db.get_or_404(PaymentOperation,opid);form=ObjectForm(prefix='reconcile-')
    if op.scope!=stripe.scope():abort(409)
    if not admin_check(form,'payment-operation:'+opid):abort(400)
    value=form.object_id.data.strip()
    roots={'checkout':'checkout/sessions/','account':'accounts/','refund':'refunds/','transfer':'transfers/','reversal':op.path+'/'}
    if op.kind not in roots or op.state=='succeeded':abort(409)
    try:
        data=stripe.api('GET',roots[op.kind]+value);engine.validate_result(op,data)
        engine.apply_result(op,data);log('Stripe operation reconciled','payment-operation:'+opid,form.reason.data.strip());db.session.commit()
        flash('Verified Stripe object linked to the original operation.','success')
    except (stripe.StripeError,engine.PaymentProblem,ValueError) as exc:flash('Stripe object could not be verified. No new operation was submitted.','error')
    return redirect(url_for('payments.detail',oid=op.order_id)) if op.order_id else redirect(url_for('payments.center'))

@bp.post('/webhooks/stripe')
def webhook():
    if not stripe.configured():return '',503
    if request.content_length and request.content_length>262144:abort(413)
    raw=request.get_data();header=request.headers.get('Stripe-Signature','')
    secrets_=[current_app.config.get('STRIPE_WEBHOOK_SECRET',''),current_app.config.get('STRIPE_CONNECT_WEBHOOK_SECRET','')]
    if len(raw)>262144 or not any(stripe.verify_signature(raw,header,s) for s in secrets_):abort(403)
    try:
        event=json.loads(raw);kind=event['type'];obj=event['data']['object'];eid=event['id'];oid=obj['id']
        if not isinstance(kind,str) or len(kind)>100:abort(400)
        if event['livemode'] is not stripe.live() or not isinstance(eid,str) or not eid.startswith('evt_') or len(eid)>100 or not isinstance(oid,str) or len(oid)>100:abort(400)
        if not (kind.startswith(('checkout.session.','charge.','refund.','payment_intent.','transfer.')) or kind=='account.updated'):return '',204
        # Platform charge events only. Connected accounts only send readiness updates.
        if event.get('account') and kind!='account.updated':return '',204
        if StripeEvent.query.filter_by(scope=stripe.scope(),event_id=eid).first():return '',200
        db.session.add(StripeEvent(scope=stripe.scope(),event_id=eid,event_type=kind,object_id=oid));db.session.commit()
    except IntegrityError:db.session.rollback()
    except (ValueError,KeyError,TypeError):abort(400)
    return '',200

@bp.route('/payments/mock/checkout/<sid>',methods=['GET','POST'])
@roles('student')
def mock_checkout(sid):
    if stripe.mode()!='mock':abort(404)
    order=PaymentOrder.query.filter_by(session_id=sid,scope=stripe.scope()).first_or_404();owned(order)
    if order.request.user_id!=current_user.id:abort(403)
    if EmptyForm().validate_on_submit():
        from .stripe_mock import pay
        try:pay(sid);engine.process_order(order)
        except (stripe.StripeError,engine.PaymentProblem,acuity.AcuityError) as exc:flash(error_message(exc),'error')
        return redirect(url_for('payments.detail',oid=order.id))
    return render_template('payments/mock_checkout.html',o=order)

@bp.post('/payments/mock/ready')
@roles('mentor')
def mock_ready():
    if stripe.mode()!='mock':abort(404)
    if not EmptyForm().validate_on_submit():abort(400)
    from .stripe_mock import ready
    row=engine.account_for(current_user.mentor.id)
    if not row.account_id:abort(409)
    ready(row.account_id);engine.refresh_account(row);return redirect(url_for('payments.connect'))

@bp.post('/support/payments/accounts/attach')
@roles('admin')
def attach_account():
    form=AttachForm(prefix='attach-')
    if not admin_check(form,'stripe-account-link'):abort(400)
    try:
        if not form.mentor_id.data.isdigit():raise engine.PaymentProblem('Enter a valid mentor ID.')
        mentor=db.get_or_404(Mentor,int(form.mentor_id.data));row=engine.account_for(mentor.id)
        value=form.object_id.data.strip()
        if row.account_id:raise engine.PaymentProblem('This mentor already has an account in the current Stripe scope.')
        if PaymentOperation.query.filter_by(account_row_id=row.id,kind='account').filter(PaymentOperation.state!='rejected').first():raise engine.PaymentProblem('Reconcile the existing account creation operation first.')
        if StripeAccount.query.filter_by(scope=stripe.scope(),account_id=value).first():raise engine.PaymentProblem('This account is already associated with a mentor.')
        data=stripe.api('GET','accounts/'+value)
        if data.get('id')!=value or data.get('country')!='US' or data.get('default_currency')!='usd' or not data.get('controller',{}).get('is_controller'):
            raise engine.PaymentProblem('Use a US/USD connected account controlled by this Stripe platform.')
        marked=data.get('metadata',{}).get('ttbg_mentor')
        if marked and marked!=str(mentor.id):raise engine.PaymentProblem('The account metadata identifies a different mentor.')
        row.account_id=value;db.session.commit();engine.refresh_account(row)
        log('Existing Stripe account linked','mentor:'+str(mentor.id),form.reason.data.strip());db.session.commit();flash('Connected account verified and linked.','success')
    except (engine.PaymentProblem,stripe.StripeError,ValueError) as exc:
        db.session.rollback();flash(error_message(exc) if not isinstance(exc,ValueError) else 'Invalid account ID.','error')
    return redirect(url_for('payments.center'))
