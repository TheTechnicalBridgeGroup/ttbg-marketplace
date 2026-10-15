"""v0.8 financial evidence, independent states, durable cancellation requests."""
import secrets
from datetime import timedelta
from flask import current_app,has_request_context
from flask_login import current_user
from sqlalchemy.exc import IntegrityError
from .models import (db,now,PaymentOrder,PaymentIdentity,FinancialEvent,PaymentCancellation,PaymentRefund,
    PaymentOperation,PaymentNotice,AcuityAppointment,StripeDispute,User)
from . import stripe_api as stripe,acuity,payment_engine as engine

REASONS=[('admin_review','Reviewed by Admin'),('mentee_request','Mentee request'),('mentor_unavailable','Mentor unavailable'),
    ('schedule_conflict','Scheduling conflict'),('technical_issue','Technical issue'),('duplicate_payment','Duplicate payment'),
    ('service_not_delivered','Service not delivered'),('other','Other — explain below')]

def actor(user=None,source=None):
    if source is not None:return {'id':None,'name':source,'role':'external_stripe' if source.startswith('External / Stripe') else 'system'}
    if user is None and has_request_context() and current_user.is_authenticated:user=current_user
    if user is not None:return {'id':user.id,'name':user.name[:150],'role':user.role}
    return {'id':None,'name':source or 'TTBG System','role':'system'}
def actor_label(value):
    if not value:return '—'
    role=value.get('role','system');name=value.get('name','Unknown')
    if role=='student':return 'Mentee'
    return {'admin':'Admin','account_manager':'Account Manager','mentor':'Mentor','external':'External / Acuity','external_stripe':'External / Stripe','system':'System'}.get(role,role.title())+' · '+name

def identity(order):
    if order.identity:return order.identity
    b=order.booking;u=db.session.get(User,order.request.user_id) if order.request.user_id else None
    m=order.account.mentor
    customer=u.name if u else b.student.name if b else 'Deleted account'
    mentor=m.user.name if m else b.mentor.user.name if b else 'Deleted mentor'
    row=PaymentIdentity(order=order,reference='pending-'+secrets.token_hex(16),customer_name=customer,mentor_name=mentor)
    db.session.add(row);db.session.flush()
    prefix='' if order.scope.startswith('live:') else 'SIM-' if order.scope.startswith('mock:') else 'TEST-'
    row.reference=f'{prefix}PAY-{order.created_at.year}-{row.id:06d}';db.session.flush();return row

def cancellations(order):return PaymentCancellation.query.filter_by(order_id=order.id).order_by(PaymentCancellation.created_at.desc(),PaymentCancellation.id.desc()).all()
def cancelled_by(order):
    item=PaymentCancellation.query.filter_by(order_id=order.id,state='confirmed').order_by(PaymentCancellation.cancelled_at.desc()).first()
    return actor_label(item.performed_by) if item else '—'

def states(order):
    mirror=AcuityAppointment.query.filter_by(request_id=order.id).first();b=order.booking
    c=PaymentCancellation.query.filter_by(order_id=order.id,active_key=order.id).first()
    payment=order.payment_state
    if payment=='unpaid':
        op=PaymentOperation.query.filter_by(scope=order.scope,owner_key='checkout:'+order.id).first()
        failed_attempt=FinancialEvent.query.filter_by(order_id=order.id,action='payment_attempt_failed').first()
        payment='failed' if (op and op.state=='rejected') or failed_attempt else 'checkout_open' if order.session_id else 'unpaid'
    if payment=='expired' and PaymentCancellation.query.filter_by(order_id=order.id,target='checkout',state='confirmed').first():payment='cancelled'
    appointment=order.booking_state
    if mirror:
        appointment='cancelled' if mirror.cancelled else 'needs_review' if mirror.sync_state!='synced' else 'confirmed'
        attendance=FinancialEvent.query.filter(FinancialEvent.order_id==order.id,FinancialEvent.action.in_(['no_show_verified','no_show_cleared'])).order_by(FinancialEvent.id.desc()).first()
        if mirror.cancelled and attendance and attendance.action=='no_show_verified':appointment='no_show'
        if not mirror.cancelled and b and b.status=='confirmed':
            if order.completion_approved_at:appointment='completed'
            elif b.start!=order.request.starts_at:appointment='rescheduled'
    elif appointment=='cancelled':appointment='cancelled'
    elif appointment=='rejected':appointment='booking_failed'
    elif appointment in ('creating','uncertain'):appointment='needs_review'
    if c and c.state in ('requested','processing','uncertain') and appointment!='cancelled':appointment='cancellation_requested'
    transfer_op=PaymentOperation.query.filter_by(scope=order.scope,owner_key='transfer:'+order.id).first()
    reverse_op=PaymentOperation.query.filter_by(scope=order.scope,owner_key='reversal:'+order.id).first()
    if order.reversed_cents:earnings='reversed' if order.reversed_cents>=order.mentor_cents else 'needs_review'
    elif reverse_op and reverse_op.state!='succeeded':earnings='reversal_pending' if reverse_op.state in ('queued','running') else 'needs_review'
    elif order.transfer_id and (order.hold_reason or order.refund_requested or payment in ('disputed','refunded','partially_refunded','refund_pending','refund_failed')):earnings='held'
    elif order.transfer_id:earnings='transferred'
    elif order.hold_reason or order.refund_requested or c or payment in ('disputed','refunded','partially_refunded','refund_pending','refund_failed'):earnings='held'
    elif transfer_op and transfer_op.state in ('queued','running','uncertain','manual_review'):earnings='transfer_pending'
    elif payment!='paid':earnings='awaiting_payment'
    elif order.completion_approved_at:earnings='approved'
    elif order.completion_reported_at:earnings='awaiting_approval'
    elif b and b.start+timedelta(minutes=b.duration)<=now():earnings='awaiting_completion'
    else:earnings='pending_session'
    overdue=order.payment_state=='paid' and not order.booking and now()-order.created_at>timedelta(minutes=5)
    uncertain=PaymentOperation.query.filter(PaymentOperation.order_id==order.id,PaymentOperation.state.in_(['uncertain','manual_review','rejected'])).first()
    review=bool(order.hold_reason or overdue or uncertain or appointment in ('needs_review','cancellation_requested') or payment in ('refund_pending','refund_failed','disputed','partially_refunded') or earnings in ('awaiting_completion','awaiting_approval','approved','needs_review','reversal_pending'))
    return {'payment':payment,'appointment':appointment,'earnings':earnings,'review':review,
        'refund_cents':order.refunded_cents,'transfer':order.transfer_id or '', 'reversed_cents':order.reversed_cents}

def emit(order,action,outcome,requested=None,performed=None,approved=None,reason='',reason_code='',amount=None,provider='',error='',before=None,after=None,key=None,notice=False):
    if key and FinancialEvent.query.filter_by(dedupe_key=key).first():return None
    item=FinancialEvent(order_id=order.id,action=action,outcome=outcome,requested_by=requested or actor(),performed_by=performed or actor(),
        approved_by=approved or {},before=before or {},after=after or {},amount_cents=amount,reason=(reason or '')[:500],reason_code=reason_code,
        provider_ref=provider[:120],error_code=error[:100],dedupe_key=key)
    db.session.add(item);db.session.flush()
    if notice:db.session.add(PaymentNotice(order_id=order.id,event_id=item.id))
    return item

def observe(order,source='Saved application state'):
    row=identity(order);current=states(order);previous=row.last_snapshot or {}
    if previous!=current:
        emit(order,'status_verified' if source.startswith('Verified') else 'status_snapshot','succeeded' if source.startswith('Verified') else 'saved',performed=actor(source=source),before=previous,after=current,provider=order.charge_id or order.session_id or '',
             reason='Provider reconciliation result.' if source.startswith('Verified') else 'Saved application status; check provider verification timestamps.',notice=bool(previous and previous.get('payment')!=current['payment'] and current['payment'] in ('refunded','refund_pending','refund_failed','partially_refunded')))
    row.payment_status=current['payment'];row.appointment_status=current['appointment'];row.earnings_status=current['earnings'];row.needs_review=current['review'];row.last_snapshot=current;row.observed_at=now()
    db.session.flush();return row

def record_refunds(order,results):
    for data in results:
        if data.get('charge')!=order.charge_id or data.get('currency')!='usd':raise stripe.StripeError('refund_verification_failed')
        row=PaymentRefund.query.filter_by(provider_id=data['id']).first()
        if not row:
            opid=data.get('metadata',{}).get('ttbg_operation')
            op=db.session.get(PaymentOperation,opid) if opid else None
            row=db.session.get(PaymentRefund,opid) if op and op.order_id==order.id else None
        if not row:
            row=PaymentRefund(id=secrets.token_hex(16),order_id=order.id,amount_cents=data['amount'],status='unverified',reason_code='external_stripe',requested_by=actor(source='External / Stripe · Initiator unverified'),approved_by={});db.session.add(row)
        old=row.status;row.provider_id=data['id'];row.status=data.get('status','unknown');row.amount_cents=data['amount'];row.verified_at=now()
        if row.status!=old:
            emit(order,'refund_verified',row.status,requested=row.requested_by,approved=row.approved_by,performed=actor(source='Stripe'),amount=row.amount_cents,provider=row.provider_id,reason_code=row.reason_code,
                 reason=row.reason,key='refund:'+row.id+':'+row.status,notice=True)

def refund_operation(order,op):
    if db.session.get(PaymentRefund,op.id):return
    previous=FinancialEvent.query.filter_by(order_id=order.id,action='refund_requested').order_by(FinancialEvent.id.desc()).first()
    db.session.add(PaymentRefund(id=op.id,order_id=order.id,amount_cents=op.params['amount'],status='requested',
        requested_by=previous.requested_by if previous else actor(source='TTBG recovery system'),approved_by=previous.approved_by if previous else {},
        reason_code=previous.reason_code if previous else 'booking_failed',reason=previous.reason if previous else 'Automatic refund after verified booking failure.'))

def external_cancel(order,mirror,historical=False):
    if not mirror.cancelled:return
    existing=PaymentCancellation.query.filter_by(order_id=order.id,state='confirmed').first()
    if existing:return
    pending=PaymentCancellation.query.filter(PaymentCancellation.order_id==order.id,PaymentCancellation.state.in_(['processing','uncertain'])).first()
    # An in-flight admin cancellation is confirmed by its dedicated reconciliation, not guessed here.
    if pending:return
    who={'id':None,'name':'Initiator unverified','role':'external'}
    row=PaymentCancellation(id=secrets.token_hex(16),order_id=order.id,state='confirmed',target='appointment',requested_by=who,performed_by=who,
        approved_by={},reason_code='external_acuity',reason='Historical saved Acuity cancellation; original time and initiator unverified.' if historical else 'Cancellation observed directly in Acuity; initiator could not be verified.',provider_ref=mirror.provider_id,cancelled_at=None if historical else now())
    db.session.add(row);order.hold_reason=order.hold_reason or 'cancellation_review'
    emit(order,'appointment_cancelled','succeeded',requested=who,performed=who,reason=row.reason,reason_code=row.reason_code,provider=mirror.provider_id,key='external-cancel:'+order.id,notice=not historical)

def request_cancel(order,reason_code,reason):
    engine.check_scope(order)
    from .appointments import write_lock
    write_lock()
    existing=PaymentCancellation.query.filter_by(active_key=order.id).first()
    if existing:return existing
    confirmed=PaymentCancellation.query.filter_by(order_id=order.id,state='confirmed').first()
    if confirmed:raise engine.PaymentProblem('This cancellation is already confirmed.')
    b=order.booking
    if b and b.start+timedelta(minutes=b.duration)<=now():raise engine.PaymentProblem('This session has ended. Request a post-session refund review instead.')
    row=PaymentCancellation(id=secrets.token_hex(16),order_id=order.id,active_key=order.id,target='appointment' if order.booking or order.payment_state!='unpaid' else 'checkout',
        requested_by=actor(),performed_by={},approved_by={},reason_code=reason_code,reason=reason.strip())
    db.session.add(row);order.hold_reason=order.hold_reason or 'cancellation_requested'
    emit(order,'cancellation_requested','requested',requested=row.requested_by,reason=reason,reason_code=reason_code,amount=order.gross_cents)
    observe(order);db.session.commit();return row

def confirm_cancel(order,row,source=None):
    row.state='confirmed';row.active_key=None;row.cancelled_at=now()
    if source:row.performed_by=source
    emit(order,{'checkout':'checkout_cancelled','booking_request':'booking_request_cancelled'}.get(row.target,'appointment_cancelled'),'succeeded',requested=row.requested_by,performed=row.performed_by,approved=row.approved_by,
        reason=row.reason,reason_code=row.reason_code,provider=row.provider_ref,key='cancel-confirmed:'+row.id,notice=row.target=='appointment')
    if row.target=='checkout':
        order.payment_state='expired';order.slot_key=None;order.checkout_url='';order.appointment_payload={};order.request.dedupe_key=None
    if row.refund_requested and order.charge_id:engine.request_refund(order,'approved_cancel_refund')
    observe(order);db.session.commit()

def execute_cancel(order,row,with_refund=False):
    from .appointments import write_lock,sync_one
    engine.refresh_payment(order)
    if row.state=='confirmed':return
    if row.target=='checkout' and order.booking:row.target='appointment'
    if row.state in ('processing','uncertain'):
        reconcile_cancel(order,row);return
    b=order.booking
    if b and b.start+timedelta(minutes=b.duration)<=now():raise engine.PaymentProblem('Completed sessions require post-session refund review.')
    if order.booking_state in ('creating','uncertain'):raise engine.PaymentProblem('Reconcile the uncertain appointment before cancellation.')
    if row.target=='checkout' and order.payment_state in ('paid','refunded','refund_pending') and not order.booking and order.booking_state=='waiting' and actor().get('role')=='admin':row.target='booking_request'
    if row.target=='checkout' and order.payment_state not in ('unpaid','expired'):
        raise engine.PaymentProblem('Payment completed during cancellation. Review and cancel the paid session through the appointment workflow.')
    if row.target=='appointment' and not order.booking and order.booking_state=='waiting':
        row.target='booking_request'
    elif row.target=='appointment' and not order.booking:raise engine.PaymentProblem('A verified appointment is required. Review the failed or pending booking first.')
    mirror=AcuityAppointment.query.filter_by(request_id=order.id).first()
    if mirror:
        mirror=sync_one(mirror.provider_id)
        if mirror.cancelled:
            confirm_cancel(order,row,{'id':None,'name':'Initiator unverified','role':'external'});return
    write_lock();db.session.refresh(row)
    who=actor();reference=mirror.provider_id if mirror else order.session_id or ''
    claimed=db.session.execute(db.update(PaymentCancellation).where(PaymentCancellation.id==row.id,PaymentCancellation.state=='requested').values(
        state='processing',performed_by=who,approved_by=who,attempted_at=now(),refund_requested=with_refund,provider_ref=reference))
    if claimed.rowcount!=1:db.session.rollback();raise engine.PaymentProblem('Cancellation is already processing. Recheck its status.')
    db.session.refresh(row)
    emit(order,'cancellation_approved','requested',requested=row.requested_by,performed=row.performed_by,approved=row.approved_by,reason=row.reason,reason_code=row.reason_code,amount=order.gross_cents)
    db.session.commit()
    try:
        if row.target=='booking_request':
            order.booking_state='cancelled';order.request.state='rejected';order.appointment_payload={};order.slot_key=None;order.request.dedupe_key=None
            db.session.commit();confirm_cancel(order,row)
        elif row.target=='checkout':
            data=stripe.api('GET','checkout/sessions/'+order.session_id)
            if data.get('status')=='open':
                op=engine.operation('expire','cancel-checkout:'+order.id,{},'checkout/sessions/'+order.session_id+'/expire',order=order);engine.execute(op)
            reconcile_cancel(order,row)
        else:
            from .registration_security import mail_ready
            acuity.api_request('PUT','appointments/'+mirror.provider_id+'/cancel',params={'admin':'true','noEmail':'true' if mail_ready() else 'false'},data={'cancelNote':'Cancelled through TTBG. Contact TTBG for payment/refund status.'})
            reconcile_cancel(order,row)
    except (stripe.StripeError,acuity.AcuityError,engine.PaymentProblem) as exc:
        db.session.rollback();db.session.refresh(row);row.state='uncertain';row.error_code=getattr(exc,'code','cancellation_review_required')
        emit(order,'cancellation_result','needs_review',requested=row.requested_by,performed=row.performed_by,approved=row.approved_by,reason=row.reason,error=row.error_code)
        observe(order);db.session.commit();raise

def reconcile_cancel(order,row):
    from .appointments import sync_one
    if row.state=='confirmed':return
    if row.target=='booking_request':
        if order.booking_state=='cancelled':confirm_cancel(order,row);return
        row.state='uncertain';row.error_code='booking_cancellation_review';db.session.commit();return
    if row.target=='checkout':
        engine.refresh_payment(order)
        data=stripe.api('GET','checkout/sessions/'+order.session_id)
        if data.get('status')=='expired' and data.get('payment_status')!='paid':confirm_cancel(order,row);return
        if data.get('payment_status')=='paid':
            row.state='needs_review';row.active_key=None;row.error_code='payment_completed_during_cancellation'
            emit(order,'cancellation_result','needs_review',requested=row.requested_by,performed=row.performed_by,error=row.error_code,key='cancel-paid-race:'+row.id)
            db.session.commit();return
    else:
        mirror=sync_one(row.provider_ref)
        if mirror.cancelled:confirm_cancel(order,row);return
    row.state='uncertain';row.error_code='provider_cancellation_not_confirmed';db.session.commit()

def action_blocks(order):
    """Explain cached eligibility; every write still refreshes providers server-side."""
    b=order.booking;ended=bool(b and b.start+timedelta(minutes=b.duration)<=now());base=''
    if not b or b.status!='confirmed':base='A confirmed appointment is required.'
    elif not ended:base='The session has not ended.'
    elif order.payment_state!='paid':base='The verified payment is not paid.'
    elif order.hold_reason or order.refund_requested:base='Resolve the payment or cancellation hold first.'
    transfer=base or ('' if order.completion_approved_at else 'Admin completion approval is required.')
    if order.transfer_id:transfer='A mentor transfer already exists; review its status instead.'
    refund=''
    if not order.charge_id:refund='A verified charge is required.'
    elif order.payment_state in ('disputed','refund_pending','refunded'):refund='Resolve the dispute/pending refund, or review the completed refund.'
    elif order.booking_state in ('creating','uncertain'):refund='Reconcile the uncertain Acuity appointment first.'
    rejected=PaymentOperation.query.filter_by(scope=order.scope,owner_key='checkout:'+order.id,state='rejected').first()
    refund_op=PaymentOperation.query.filter_by(scope=order.scope,owner_key='refund:'+order.id).first()
    return {'approve_completion':base or ('Completion is already approved.' if order.completion_approved_at else ''),'transfer':transfer,'refund':refund,
        'retry_refund':'' if refund_op and (refund_op.state=='rejected' or order.payment_state=='refund_failed') and order.payment_state!='refunded' else 'Only a definitively failed refund can be retried.',
        'recover_transfer':'' if order.transfer_id and order.reversed_cents<order.mentor_cents and (order.payment_state in ('refunded','disputed') or order.hold_reason=='dispute') else 'Recovery requires an unrecovered transfer and a full refund or dispute.',
        'clear_review':'' if order.hold_reason in ('dispute','appointment_changed','cancellation_review') else 'No releasable appointment or won-dispute hold.',
        'close_failed':'' if rejected and not order.session_id and not order.intent_id else 'Only a definitely rejected checkout with no Stripe session can be closed.'}


def verified(order,provider):
    row=identity(order)
    if provider=='stripe':row.stripe_verified_at=now()
    elif provider=='acuity':row.acuity_verified_at=now()
    else:raise ValueError('Unknown financial verification provider')
