"""Role-checked financial operations, filtered reporting and customer receipts."""
import csv,io,secrets
from datetime import datetime,timedelta,time,timezone
from zoneinfo import ZoneInfo,ZoneInfoNotFoundError
from flask import Blueprint,abort,request,render_template,redirect,url_for,flash,Response,current_app
from flask_login import current_user,login_required
from flask_wtf import FlaskForm
from wtforms import SelectField,StringField,BooleanField,PasswordField
from wtforms.validators import DataRequired,Length
from sqlalchemy import or_,func
from .models import (db,now,PaymentOrder,PaymentIdentity,PaymentCancellation,FinancialEvent,PaymentRefund,
 PaymentWorkerHealth,PaymentNotice,StripeEvent,PaymentOperation,AcuityAppointment,StripeAccount,User)
from . import finance,acuity,stripe_api as stripe,payment_engine as engine
from .forms import EmptyForm
from .routes import roles

bp=Blueprint('financial',__name__)
class CancelForm(FlaskForm):
    reason_code=SelectField('Reason',choices=[('','Select a reason')]+finance.REASONS,validators=[DataRequired()])
    reason=StringField('Details for staff',validators=[DataRequired(),Length(min=8,max=500)])
class CancelApproval(CancelForm):
    password=PasswordField('Your Admin password',validators=[DataRequired(),Length(max=128)])
    refund=BooleanField('Approve a full remaining refund after cancellation is confirmed')
    confirm=BooleanField('I verified the appointment and financial impact.',validators=[DataRequired()])

PAYMENTS=['unpaid','checkout_open','paid','failed','expired','cancelled','refund_pending','refund_failed','refunded','partially_refunded','disputed']
APPOINTMENTS=['no_show','waiting','confirmed','cancellation_requested','cancelled','completed','rescheduled','booking_failed','needs_review']
EARNINGS=['awaiting_payment','pending_session','awaiting_completion','awaiting_approval','approved','transfer_pending','transferred','held','reversal_pending','reversed','needs_review']

def allowed(order):
    from .payments import owned
    owned(order)

def sync_identities():
    # Only missing legacy identities are backfilled here; normal writes update their own cached states.
    missing=PaymentOrder.query.outerjoin(PaymentIdentity).filter(PaymentOrder.scope==stripe.scope(),PaymentIdentity.id.is_(None)).all()
    for order in missing:finance.observe(order,source='Legacy saved-state import')
    stale=PaymentOrder.query.join(PaymentIdentity).filter(PaymentOrder.scope==stripe.scope(),PaymentIdentity.observed_at<now()-timedelta(minutes=1)).order_by(PaymentIdentity.observed_at).limit(1000).all()
    for order in stale:finance.observe(order)
    db.session.commit()

def filtered():
    sync_identities()
    q=PaymentOrder.query.join(PaymentIdentity).outerjoin(AcuityAppointment,AcuityAppointment.request_id==PaymentOrder.id).filter(PaymentOrder.scope==stripe.scope())
    args={k:request.args.get(k,'').strip() for k in ('q','payment','appointment','earnings','period','start','end','attention','sort','view','tz')}
    error=None
    search=args['q'][:120]
    if search:
        pattern='%'+search.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
        fields=[PaymentIdentity.reference,PaymentIdentity.customer_name,PaymentIdentity.mentor_name,PaymentOrder.id,PaymentOrder.session_id,
                PaymentOrder.intent_id,PaymentOrder.charge_id,PaymentOrder.transfer_id,AcuityAppointment.provider_id]
        from .models import AcuityRequest
        q=q.join(PaymentOrder.request)
        fields.extend([AcuityRequest.service_name,AcuityRequest.email])
        q=q.filter(or_(*[f.ilike(pattern,escape='\\') for f in fields]))
    for key,field,values in [('payment',PaymentIdentity.payment_status,PAYMENTS),('appointment',PaymentIdentity.appointment_status,APPOINTMENTS),('earnings',PaymentIdentity.earnings_status,EARNINGS)]:
        if args[key]:
            if args[key] not in values:error='Choose a valid status filter.'
            else:q=q.filter(field==args[key])
    if args['attention']=='yes':q=q.filter(PaymentIdentity.needs_review==True)
    if args['view']=='refunds':q=q.filter(or_(PaymentOrder.refund_requested==True,PaymentIdentity.payment_status.in_(['refund_pending','refund_failed','partially_refunded'])))
    elif args['view']=='ready':q=q.filter(PaymentIdentity.earnings_status=='approved')
    elif args['view']=='awaiting_approval':q=q.filter(PaymentIdentity.earnings_status.in_(['awaiting_completion','awaiting_approval']))
    try:
        tz=ZoneInfo(args['tz'] or 'America/New_York');today=datetime.now(tz).date();start=end=None
        if args['period'] in ('today','7','30'):
            start=today-timedelta(days={'today':0,'7':6,'30':29}[args['period']]);end=today
        elif args['period']=='custom':
            start=datetime.strptime(args['start'],'%Y-%m-%d').date();end=datetime.strptime(args['end'],'%Y-%m-%d').date()
            if end<start:raise ValueError()
        elif args['period']:raise ValueError()
        if start:
            lower=datetime.combine(start,time.min,tz).astimezone(timezone.utc).replace(tzinfo=None)
            upper=datetime.combine(end+timedelta(days=1),time.min,tz).astimezone(timezone.utc).replace(tzinfo=None)
            q=q.filter(PaymentOrder.created_at>=lower,PaymentOrder.created_at<upper)
    except (ValueError,ZoneInfoNotFoundError):error='Enter a valid date range and timezone.'
    if error:q=q.filter(db.false())
    sorts={'newest':PaymentOrder.created_at.desc(),'oldest':PaymentOrder.created_at.asc(),'amount_high':PaymentOrder.gross_cents.desc(),
           'amount_low':PaymentOrder.gross_cents.asc(),'status':PaymentIdentity.payment_status.asc(),'mentor':PaymentIdentity.mentor_name.asc()}
    sorting=sorts.get(args['sort'] or 'newest',sorts['newest'])
    if args['view']=='awaiting_approval':sorting=PaymentOrder.request.property.mapper.class_.starts_at.asc();q=q.join(PaymentOrder.request) if not search else q
    return q.order_by(sorting,PaymentOrder.id),args,error

def page_url(page):
    args=request.args.to_dict();args['page']=page;return url_for('payments.center',**args)

def center():
    q,args,error=filtered();count=q.count()
    # Aggregate over the complete filtered set, never the current page; current scope only.
    paid=q.order_by(None).with_entities(PaymentOrder).filter(PaymentOrder.charge_id.is_not(None)).subquery()
    totals=db.session.execute(db.select(func.coalesce(func.sum(paid.c.gross_cents),0),func.coalesce(func.sum(paid.c.refunded_cents),0),
        func.coalesce(func.sum(paid.c.stripe_fee_cents),0),func.coalesce(func.sum(paid.c.platform_cents),0))).one()
    obligations=q.order_by(None).filter(PaymentOrder.charge_id.is_not(None),PaymentOrder.payment_state.notin_(['refunded']),PaymentOrder.transfer_id.is_(None)).with_entities(func.coalesce(func.sum(PaymentOrder.mentor_cents),0)).scalar()
    review=q.order_by(None).filter(PaymentIdentity.needs_review==True).count()
    page=q.paginate(per_page=25,page=max(1,request.args.get('page',1,type=int)),error_out=False)
    accounts=StripeAccount.query.filter_by(scope=stripe.scope()).order_by(StripeAccount.id.desc()).limit(100).all()
    pending=StripeEvent.query.filter_by(scope=stripe.scope(),pending=True).count()
    health=db.session.get(PaymentWorkerHealth,stripe.scope())
    healthy=bool(health and health.completed_at and health.completed_at>now()-timedelta(minutes=5) and not health.failures)
    last_event=StripeEvent.query.filter_by(scope=stripe.scope(),pending=False).order_by(StripeEvent.checked_at.desc()).first()
    ops=PaymentOperation.query.filter(PaymentOperation.scope==stripe.scope(),PaymentOperation.state.in_(['uncertain','manual_review','rejected','running'])).order_by(PaymentOperation.created_at).limit(30).all()
    from .payments import ObjectForm,AttachForm
    notices=PaymentNotice.query.join(PaymentOrder).filter(PaymentOrder.scope==stripe.scope(),PaymentNotice.state.in_(['queued','failed','uncertain','sending'])).count()
    return render_template('payments/center_v08.html',page=page,args=args,error=error,page_url=page_url,payment_choices=PAYMENTS,appointment_choices=APPOINTMENTS,earnings_choices=EARNINGS,
        totals=totals,obligations=obligations,review=review,accounts=accounts,pending=pending,ops=ops,health=health,healthy=healthy,last_event=last_event,notices=notices,
        object_form=ObjectForm(prefix='reconcile-'),attach_form=AttachForm(prefix='attach-'),count=count)

def safe_csv(value):
    text=str(value if value is not None else '')
    return "'"+text if text.lstrip().startswith(('=','+','-','@')) or text.startswith(('\t','\r','\n')) else text

@bp.get('/support/payments/export.csv')
@roles('admin','account_manager')
def export():
    q,args,error=filtered()
    if error:abort(400)
    from .security import log
    log('Financial CSV exported','payments','Current scope; filtered records.');db.session.commit()
    out=io.StringIO();writer=csv.writer(out)
    writer.writerow(['Payment ID','Mode','Created UTC','Mentee','Mentor','Service','Payment','Appointment','Mentor earnings','Cancelled by','Gross cents','Refunded cents','Mentor allocation cents','TTBG gross cents','Stripe reported fee cents','Stripe charge','Acuity appointment','Stripe transfer'])
    # Bound exports; staff can narrow the date range instead of truncating silently.
    if q.count()>10000:abort(413,description='Narrow your filters to at most 10,000 records.')
    for order in q:
        ref=order.identity;mirror=AcuityAppointment.query.filter_by(request_id=order.id).first()
        writer.writerow([safe_csv(v) for v in (ref.reference,stripe.mode(),order.created_at.isoformat(),ref.customer_name,ref.mentor_name,order.request.service_name,
            ref.payment_status,ref.appointment_status,ref.earnings_status,finance.cancelled_by(order),order.gross_cents,order.refunded_cents,order.mentor_cents,order.platform_cents,
            order.stripe_fee_cents,order.charge_id,mirror.provider_id if mirror else '',order.transfer_id)])
    return Response(out.getvalue(),mimetype='text/csv',headers={'Content-Disposition':'attachment; filename=ttbg-payments-'+stripe.mode()+'.csv','Cache-Control':'no-store'})

@bp.route('/payments/orders/<oid>/cancel-session',methods=['GET','POST'])
@login_required
def cancel_request(oid):
    order=db.get_or_404(PaymentOrder,oid);allowed(order);form=CancelForm()
    if form.validate_on_submit():
        try:
            row=finance.request_cancel(order,form.reason_code.data,form.reason.data)
            # Only the owner's verified unpaid Checkout can be closed without Admin policy review.
            if current_user.role=='student' and row.target=='checkout':finance.execute_cancel(order,row)
            flash('Cancellation '+('confirmed.' if row.state=='confirmed' else 'requested. Staff will review the appointment and refund separately.'),'success')
        except (engine.PaymentProblem,stripe.StripeError,acuity.AcuityError) as exc:
            flash('Cancellation needs review: '+getattr(exc,'code',str(exc)).replace('_',' '),'error')
        return redirect(url_for('payments.detail',oid=oid))
    return render_template('payments/cancel.html',o=order,form=form)

@bp.route('/support/payments/<oid>/cancel-session',methods=['GET','POST'])
@roles('admin')
def cancel_admin(oid):
    from .payments import admin_check
    order=db.get_or_404(PaymentOrder,oid);allowed(order);form=CancelApproval()
    if form.validate_on_submit():
        if not admin_check(form,'cancel:'+oid):
            finance.emit(order,'cancellation_authorization','failed',error='authorization_failed');db.session.commit();abort(403)
        try:
            row=finance.request_cancel(order,form.reason_code.data,form.reason.data)
            # Preserve the original requester/reason; approval has its own event.
            finance.emit(order,'cancellation_review','approved',requested=row.requested_by,approved=finance.actor(),reason=form.reason.data,reason_code=form.reason_code.data,amount=order.gross_cents);db.session.commit()
            finance.execute_cancel(order,row,with_refund=form.refund.data)
            engine.process_order(order)
            flash('Provider status checked. Appointment cancellation and refund results are shown separately.','success')
        except (engine.PaymentProblem,stripe.StripeError,acuity.AcuityError) as exc:
            flash('Review required: '+getattr(exc,'code',str(exc)).replace('_',' '),'error')
        return redirect(url_for('payments.detail',oid=oid))
    return render_template('payments/cancel.html',o=order,form=form,admin=True)

@bp.post('/payments/orders/<oid>/refund-request')
@login_required
def refund_request(oid):
    order=db.get_or_404(PaymentOrder,oid);allowed(order)
    if current_user.role not in ('student','account_manager','admin') or (current_user.role=='student' and order.request.user_id!=current_user.id):abort(403)
    form=CancelForm()
    if not form.validate_on_submit():abort(400)
    from .appointments import write_lock
    write_lock();order.hold_reason=order.hold_reason or 'refund_review_requested'
    finance.emit(order,'refund_review_requested','requested',reason=form.reason.data,reason_code=form.reason_code.data,amount=order.gross_cents-order.refunded_cents)
    finance.observe(order);db.session.commit();flash('Refund review requested. No refund is reported until Stripe confirms it.','success')
    return redirect(url_for('payments.detail',oid=oid))

@bp.get('/payments/orders/<oid>/receipt')
@login_required
def receipt(oid):
    order=db.get_or_404(PaymentOrder,oid);allowed(order)
    if not order.charge_id:abort(409)
    try:charge=stripe.api('GET','charges/'+order.charge_id)
    except stripe.StripeError:
        flash('Your receipt could not be retrieved. Contact TTBG for assistance.','info');return redirect(url_for('payments.detail',oid=oid))
    if charge.get('id')!=order.charge_id or charge.get('amount')!=order.gross_cents:abort(409)
    if stripe.mode()=='mock':flash('Local simulation has no real Stripe receipt.','info');return redirect(url_for('payments.detail',oid=oid))
    try:target=stripe.redirect_url(charge.get('receipt_url'),'receipt')
    except stripe.StripeError:flash('Receipt is not available yet. Contact TTBG for help.','info');return redirect(url_for('payments.detail',oid=oid))
    response=redirect(target,303);response.headers['Referrer-Policy']='no-referrer';return response

@bp.post('/payments/connect/manage')
@roles('mentor')
def manage_stripe():
    if not EmptyForm().validate_on_submit():abort(400)
    from .acuity import throttle
    throttle()
    row=engine.account_for(current_user.mentor.id)
    try:
        engine.refresh_account(row)
        op=engine.operation('login_link','login:'+secrets.token_hex(16),{},'accounts/'+row.account_id+'/login_links',account=row)
        result=engine.execute(op);target=stripe.redirect_url(result.get('url'),'onboarding')
        response=redirect(target,303);response.headers['Referrer-Policy']='no-referrer';return response
    except (stripe.StripeError,engine.PaymentProblem):flash('Stripe account access is unavailable. Check onboarding or contact TTBG.','error');return redirect(url_for('payments.connect'))

@bp.route('/support/payments/notices',methods=['GET','POST'])
@roles('admin','account_manager')
def notices():
    from .payments import MoneyForm,admin_check
    form=MoneyForm();form.confirm.label.text='I checked the mail-provider logs. Retrying may send another copy.'
    if request.method=='POST':
        if current_user.role!='admin':abort(403)
        if not admin_check(form,'payment-notice'):abort(403)
        notice=db.get_or_404(PaymentNotice,request.form.get('notice_id',type=int));order=db.get_or_404(PaymentOrder,notice.order_id);allowed(order)
        if notice.state not in ('uncertain','sending') or (notice.attempted_at and notice.attempted_at>now()-timedelta(minutes=10)):abort(409)
        action=request.form.get('action')
        if action not in ('retry','confirm_sent'):abort(400)
        notice.state='queued' if action=='retry' else 'staff_confirmed_sent'
        finance.emit(order,'notification_'+action,'approved',approved=finance.actor(),reason=form.reason.data,reason_code=form.reason_code.data,provider='notice:'+str(notice.id))
        db.session.commit();flash('Notice review recorded. Queued retries are delivered by the payment worker.','success')
        return redirect(url_for('financial.notices'))
    page=PaymentNotice.query.join(PaymentOrder).filter(PaymentOrder.scope==stripe.scope()).order_by(PaymentNotice.id.desc()).paginate(page=max(1,request.args.get('page',1,type=int)),per_page=25,error_out=False)
    return render_template('payments/notices.html',page=page,form=form)
