"""Durable payment operations and post-payment booking coordination."""
import hashlib
import secrets
from datetime import timedelta, timezone
from flask import current_app
from sqlalchemy.exc import IntegrityError
from . import stripe_api as stripe, acuity
from .models import (db, User, Service, Mentor, MentorIntegration, StripeAccount, PaymentOrder, PaymentOperation,
                     AcuityRequest, AcuityAppointment, StripeDispute, now)
from .security import settings, account_enabled, log
from .booking_config import split_amount
from .appointments import write_lock

class PaymentProblem(Exception):pass

def enabled():return current_app.config.get('PAYMENTS_ENABLED',False)
def check_scope(order):
    if order.scope!=stripe.scope():raise PaymentProblem('This record belongs to a different Stripe account or mode.')

def account_for(mentor_id):
    row=StripeAccount.query.filter_by(mentor_id=mentor_id,scope=stripe.scope()).first()
    if not row:row=StripeAccount(mentor_id=mentor_id,scope=stripe.scope());db.session.add(row);db.session.flush()
    return row

def refresh_account(row):
    if row.scope!=stripe.scope() or not row.account_id:raise PaymentProblem('Connect this mentor’s Stripe account first.')
    data=stripe.api('GET','accounts/'+row.account_id)
    if data.get('id')!=row.account_id:raise stripe.StripeError('stripe_account_mismatch')
    requirements=data.get('requirements') or {}
    row.ready=(data.get('country')=='US' and data.get('default_currency')=='usd' and data.get('details_submitted') is True
        and data.get('payouts_enabled') is True and data.get('capabilities',{}).get('transfers')=='active' and not requirements.get('disabled_reason')
        and not requirements.get('currently_due'))
    row.status='ready' if row.ready else 'onboarding_or_verification_required';row.checked_at=now();db.session.commit();return row.ready

def checkout_check(service,starts):
    if not enabled() or service.price_cents==0:return None
    stripe.writable()
    if not current_app.config.get('STRIPE_WEBHOOK_SECRET'):raise PaymentProblem('Payment webhooks are not configured.')
    if service.price_cents<50:raise PaymentProblem('Paid Stripe sessions must cost at least $0.50. Free consultations remain available.')
    if starts>now()+timedelta(days=current_app.config['PAYMENT_MAX_ADVANCE_DAYS']):raise PaymentProblem('This session is too far ahead for paid checkout.')
    if starts<now()+timedelta(hours=1):raise PaymentProblem('Paid sessions require at least one hour before the start time.')
    row=account_for(service.mentor_id)
    if not row.account_id or not refresh_account(row):raise PaymentProblem('This mentor is still completing payment setup. Please contact TTBG.')
    return row

def operation(kind,owner,params,path,order=None,account=None,retry=False):
    write_lock()
    op=PaymentOperation.query.filter_by(scope=stripe.scope(),owner_key=owner).first()
    if op and retry and op.state=='rejected':op.owner_key=owner+':old:'+op.id[:12];db.session.flush();op=None
    if not op:
        op=PaymentOperation(id=secrets.token_hex(16),scope=stripe.scope(),owner_key=owner,kind=kind,path=path,
             params={},order_id=order.id if order else None,account_row_id=account.id if account else None)
        params=dict(params)
        if kind not in ('account_link','login_link','expire'):params['metadata']=dict(params.get('metadata',{}),ttbg_operation=op.id)
        op.params=params;db.session.add(op)
    if order:
        from . import finance
        finance.emit(order,'operation_'+kind,'requested',amount=params.get('amount'),provider=op.id,key='operation-request:'+op.id)
        if kind=='refund':finance.refund_operation(order,op)
    try:db.session.commit()
    except IntegrityError:
        db.session.rollback();winner=PaymentOperation.query.filter_by(scope=stripe.scope(),owner_key=owner).first()
        if not winner:raise
        return winner
    return op

def validate_result(op,data):
    oid=data.get('id','')
    if op.kind in ('account_link','login_link'):return data
    if op.kind=='expire':
        if oid!=op.path.split('/')[-2] or data.get('status')!='expired':raise stripe.StripeError('stripe_operation_mismatch')
        return data
    if data.get('metadata',{}).get('ttbg_operation')!=op.id:raise stripe.StripeError('stripe_operation_mismatch')
    p=op.params
    if op.kind=='checkout':
        if not oid.startswith('cs_') or data.get('client_reference_id')!=op.order_id or data.get('currency')!='usd' or data.get('amount_total')!=p['line_items'][0]['price_data']['unit_amount']:
            raise stripe.StripeError('stripe_operation_mismatch')
    elif op.kind=='account':
        if not oid.startswith('acct_') or data.get('metadata',{}).get('ttbg_mentor')!=p['metadata']['ttbg_mentor']:raise stripe.StripeError('stripe_operation_mismatch')
    elif op.kind in ('refund','transfer','reversal'):
        fields=('amount','currency')+({'refund':('charge',),'transfer':('destination','source_transaction','transfer_group'),'reversal':('transfer',)}[op.kind])
        wanted=dict(p,transfer=op.path.split('/')[1] if op.kind=='reversal' else '')
        for f in fields:
            if data.get(f)!=wanted.get(f,'usd'):raise stripe.StripeError('stripe_operation_mismatch')
    return data

def apply_result(op,data):
    validate_result(op,data)
    op.state='succeeded';op.response_id=data.get('id');op.error_code='';op.lease_until=None
    if op.kind=='account':
        a=db.session.get(StripeAccount,op.account_row_id);a.account_id=data['id'];a.status='onboarding_required'
        if a.mentor_id:
            m=db.session.get(Mentor,a.mentor_id);ref=m.integration or MentorIntegration(mentor=m);ref.stripe_account_id=data['id'];db.session.add(ref)
    if op.order_id:
        order=db.session.get(PaymentOrder,op.order_id)
        if op.kind=='checkout':order.session_id=data['id'];order.checkout_url=data.get('url') or ''
        elif op.kind=='transfer':order.transfer_id=data['id']
        elif op.kind=='reversal':order.reversed_cents=max(order.reversed_cents,data['amount'])
        elif op.kind=='refund':order.payment_state={'succeeded':'refunded','failed':'refund_failed','canceled':'refund_failed'}.get(data.get('status'),'refund_pending')
    if op.order_id:
        from . import finance
        order=db.session.get(PaymentOrder,op.order_id)
        from .models import FinancialEvent
        prior=FinancialEvent.query.filter_by(dedupe_key='operation-request:'+op.id).first()
        finance.emit(order,'operation_'+op.kind,('succeeded' if data.get('status')=='succeeded' else 'failed' if data.get('status') in ('failed','canceled') else 'pending') if op.kind=='refund' else 'succeeded',requested=prior.requested_by if prior else None,
            approved=prior.approved_by if prior else None,performed=finance.actor(source='Stripe verified response'),amount=op.params.get('amount'),provider=data.get('id',''),key='operation-result:'+op.id)
    db.session.commit();return data

def execute(op):
    if op.scope!=stripe.scope():raise PaymentProblem('Operation belongs to another Stripe scope.')
    if op.state=='succeeded':return None
    if op.state in ('rejected','manual_review'):raise PaymentProblem('This operation needs staff review before retrying.')
    write_lock();db.session.refresh(op)
    if op.state=='succeeded':return None
    if op.lease_until and op.lease_until>now():raise PaymentProblem('This operation is already being processed.')
    if op.attempted_at and now()-op.attempted_at>timedelta(hours=23):
        op.state='manual_review';op.error_code='idempotency_window_elapsed';db.session.commit()
        raise PaymentProblem('The safe retry window ended. Reconcile the Stripe object before taking further action.')
    if op.kind=='transfer':
        o=db.session.get(PaymentOrder,op.order_id)
        if o.refund_requested or o.hold_reason or o.payment_state!='paid':raise PaymentProblem('Transfer held for payment review.')
    claimed=db.session.execute(db.update(PaymentOperation).where(PaymentOperation.id==op.id,
        db.or_(PaymentOperation.lease_until.is_(None),PaymentOperation.lease_until<=now()),
        PaymentOperation.state.in_(['queued','running','uncertain'])).values(state='running',lease_until=now()+timedelta(minutes=2),attempted_at=op.attempted_at or now()))
    if claimed.rowcount!=1:db.session.rollback();raise PaymentProblem('This operation is already being processed.')
    db.session.commit();db.session.refresh(op)
    try:data=stripe.api('POST',op.path,op.params,key=op.id);return apply_result(op,data)
    except stripe.StripeError as exc:
        db.session.rollback();op=db.session.get(PaymentOperation,op.id);op.state='rejected' if exc.definitive else 'uncertain';op.error_code=exc.code;op.lease_until=None
        if op.order_id:
            from . import finance
            finance.emit(db.session.get(PaymentOrder,op.order_id),'operation_'+op.kind,'failed' if exc.definitive else 'needs_review',provider=op.id,error=exc.code)
        db.session.commit();raise


def start_checkout(req,service,payload,account):
    stripe.writable();write_lock()
    if not enabled():raise PaymentProblem('Paid checkout was disabled. Refresh availability.')
    existing=db.session.get(PaymentOrder,req.id)
    if existing:return existing
    key=hashlib.sha256(f'{acuity.scope()}:{req.calendar_id}:{req.starts_at.isoformat()}'.encode()).hexdigest()
    if PaymentOrder.query.filter_by(slot_key=key).first():raise PaymentProblem('Someone is checking out for this time. Choose another time or try again shortly.')
    split=split_amount(req.price_cents,req.fee_bps)
    order=PaymentOrder(id=req.id,account_row_id=account.id,destination=account.account_id,scope=stripe.scope(),gross_cents=req.price_cents,
        mentor_cents=split['mentor_cents'],platform_cents=split['company_cents'],expires_at=now()+timedelta(minutes=31),slot_key=key,appointment_payload=payload)
    req.state='payment_pending';db.session.add(order);db.session.flush()
    from . import finance
    finance.identity(order)
    finance.emit(order,'checkout_created','requested',amount=order.gross_cents,key='checkout-created:'+order.id)
    base=stripe.origin();expiry=int(order.expires_at.replace(tzinfo=timezone.utc).timestamp())
    params={'mode':'payment','client_reference_id':order.id,'customer_email':req.email,
        'line_items':[{'price_data':{'currency':'usd','unit_amount':order.gross_cents,'product_data':{'name':req.service_name}},'quantity':1}],
        'metadata':{'ttbg_order':order.id},'payment_intent_data':{'metadata':{'ttbg_order':order.id},'transfer_group':'ttbg_'+order.id},
        'expires_at':expiry,'success_url':base+'/payments/orders/'+order.id,'cancel_url':base+'/payments/orders/'+order.id}
    op=operation('checkout','checkout:'+order.id,params,'checkout/sessions',order=order)
    try:execute(op)
    except (stripe.StripeError,PaymentProblem):pass
    return db.session.get(PaymentOrder,order.id)

def refresh_payment(order):
    check_scope(order)
    if order.payment_state=='expired' and not order.session_id:return None
    if not order.session_id:
        op=PaymentOperation.query.filter_by(scope=order.scope,owner_key='checkout:'+order.id).first()
        if op:execute(op)
        if not order.session_id:raise PaymentProblem('Checkout creation is awaiting recovery.')
    data=stripe.api('GET','checkout/sessions/'+order.session_id)
    if (data.get('id')!=order.session_id or data.get('mode')!='payment' or data.get('livemode') is not stripe.live()
        or data.get('client_reference_id')!=order.id or data.get('metadata',{}).get('ttbg_order')!=order.id
        or data.get('amount_total')!=order.gross_cents or data.get('currency')!='usd'):
        raise stripe.StripeError('checkout_verification_failed')
    if data.get('payment_status')!='paid':
        if data.get('status')=='expired':
            order.payment_state='expired';order.slot_key=None;order.checkout_url='';order.appointment_payload={}
            order.request.state='rejected';order.request.dedupe_key=None
        from .finance import verified
        verified(order,'stripe')
        order.checked_at=now();db.session.commit();return None
    pi=stripe.api('GET','payment_intents/'+data['payment_intent'])
    if pi.get('id')!=data['payment_intent']:raise stripe.StripeError('payment_verification_failed')
    if pi.get('status')!='succeeded' or pi.get('amount_received')!=order.gross_cents or pi.get('currency')!='usd' or pi.get('metadata',{}).get('ttbg_order')!=order.id:
        raise stripe.StripeError('payment_verification_failed')
    ch=stripe.api('GET','charges/'+pi['latest_charge'])
    if ch.get('id')!=pi['latest_charge'] or ch.get('payment_intent')!=pi['id'] or ch.get('paid') is not True or ch.get('captured') is not True or ch.get('amount')!=order.gross_cents or ch.get('currency')!='usd':
        raise stripe.StripeError('charge_verification_failed')
    order.intent_id=pi['id'];order.charge_id=ch['id'];order.checkout_url=''
    order.refunded_cents=ch.get('amount_refunded',0)
    disputes=StripeDispute.query.filter_by(order_id=order.id).all()
    dispute_resolved=bool(disputes) and all(d.status in ('won','warning_closed') for d in disputes)
    if ch.get('disputed') and not dispute_resolved:order.hold_reason='dispute';order.payment_state='disputed'
    elif order.refunded_cents>=order.gross_cents:order.payment_state='refunded'
    elif order.refunded_cents:order.payment_state='partially_refunded';order.hold_reason=order.hold_reason or 'partial_refund'
    else:order.payment_state='paid'
    txid=ch.get('balance_transaction')
    tx=stripe.api('GET','balance_transactions/'+txid) if isinstance(txid,str) else None
    if tx:
        if tx.get('currency')!='usd' or tx.get('amount')!=order.gross_cents or not isinstance(tx.get('fee'),int):raise stripe.StripeError('settlement_currency_mismatch')
        order.stripe_fee_cents=tx.get('fee')
    transfers=stripe.api('GET','transfers',{'transfer_group':'ttbg_'+order.id,'limit':100})
    if transfers.get('has_more'):order.hold_reason='transfer_history_review'
    for tr in transfers.get('data',[]):
        if tr.get('id')!=order.transfer_id:
            op=PaymentOperation.query.filter_by(scope=order.scope,owner_key='transfer:'+order.id).first()
            if op and tr.get('metadata',{}).get('ttbg_operation')==op.id:apply_result(op,tr)
            else:order.hold_reason='unrecognized_transfer_review'
    if order.transfer_id:
        tr=stripe.api('GET','transfers/'+order.transfer_id)
        if tr.get('destination')!=order.destination or tr.get('source_transaction')!=order.charge_id or tr.get('amount')!=order.mentor_cents:raise stripe.StripeError('transfer_verification_failed')
        order.reversed_cents=tr.get('amount_reversed',0)
    # Pending/failed refunds must not be mistaken for completed refunds.
    refunds=stripe.api('GET','refunds',{'charge':order.charge_id,'limit':100})
    from . import finance
    finance.record_refunds(order,refunds.get('data',[]))
    if refunds.get('has_more'):order.hold_reason='refund_history_review'
    refund_op=PaymentOperation.query.filter_by(scope=order.scope,owner_key='refund:'+order.id).first()
    if refund_op and refund_op.state not in ('succeeded','rejected'):
        for result in refunds.get('data',[]):
            if result.get('metadata',{}).get('ttbg_operation')==refund_op.id:apply_result(refund_op,result)
    if any(x.get('status') in ('pending','requires_action') for x in refunds.get('data',[])):
        order.payment_state='refund_pending';order.hold_reason=order.hold_reason or 'refund_pending_review'
    latest=PaymentOperation.query.filter_by(scope=order.scope,owner_key='refund:'+order.id).first()
    if latest and any(x.get('id')==latest.response_id and x.get('status') in ('failed','canceled') for x in refunds.get('data',[])) and order.refund_requested and order.payment_state not in ('refunded','refund_pending'):
        order.payment_state='refund_failed';order.error_code='refund_failed_review_required'
    if order.refunded_cents and order.refunded_cents<order.gross_cents:order.hold_reason=order.hold_reason or 'partial_refund_review'
    finance.verified(order,'stripe')
    order.checked_at=now();db.session.commit();return tx

def request_refund(order,reason):
    check_scope(order);write_lock();db.session.refresh(order)
    order.refund_requested=True;order.hold_reason=order.hold_reason or reason;db.session.commit()

def refund(order,retry=False):
    check_scope(order)
    if not order.charge_id:raise PaymentProblem('A verified charge is required before refunding.')
    if order.payment_state=='disputed':raise PaymentProblem('Resolve the dispute in Stripe before issuing a refund.')
    if not order.refund_requested:raise PaymentProblem('Refund has not been requested.')
    op=PaymentOperation.query.filter_by(scope=order.scope,owner_key='transfer:'+order.id).first()
    if op and op.state not in ('succeeded','rejected'):raise PaymentProblem('Reconcile the transfer outcome before refunding.')
    if order.payment_state not in ('refunded','refund_pending','refund_failed'):
        amount=order.gross_cents-order.refunded_cents
        if amount>0:
            op=operation('refund','refund:'+order.id,{'charge':order.charge_id,'amount':amount,'metadata':{'ttbg_order':order.id}},'refunds',order=order,retry=retry)
            execute(op)
    refresh_payment(order)
    if order.payment_state=='refunded':recover_transfer(order,retry=retry)

def recover_transfer(order,retry=False):
    # Only recover the contractual mentor share, never issue a second mentor transfer.
    if order.transfer_id and order.reversed_cents<order.mentor_cents:
        op=operation('reversal','reversal:'+order.id,{'amount':order.mentor_cents-order.reversed_cents,'metadata':{'ttbg_order':order.id}},'transfers/'+order.transfer_id+'/reversals',order=order,retry=retry)
        try:execute(op);refresh_payment(order)
        except (stripe.StripeError,PaymentProblem):
            order.error_code='mentor_funds_recovery_required';db.session.commit();raise


def fulfill(order):
    from .appointments import save_snapshot,slot_available,catalog
    check_scope(order);req=order.request
    mirror=AcuityAppointment.query.filter_by(request_id=req.id).first()
    if mirror and mirror.booking_id:
        order.booking_state='confirmed';order.appointment_payload={};order.slot_key=None
        mirror.booking.payment_status='stripe_'+order.payment_state
        if mirror.cancelled:order.hold_reason=order.hold_reason or 'cancellation_review'
        db.session.commit();return
    if order.payment_state!='paid' or order.refund_requested or order.hold_reason:return
    if order.booking_state in ('creating','uncertain'):
        order.booking_state='uncertain';order.error_code='acuity_confirmation_review';db.session.commit();return
    if order.booking_state=='rejected':request_refund(order,'booking_failed');return
    service=db.session.get(Service,req.service_id) if req.service_id else None
    if not req.user_id or not service or not service.active or not service.mentor.publicly_visible or req.scope!=acuity.scope() or req.starts_at<=now():
        order.booking_state='rejected';request_refund(order,'booking_no_longer_eligible');return
    try:
        if acuity.mapping(service)!={'calendarID':req.calendar_id,'appointmentTypeID':req.type_id} or service.price_cents!=req.price_cents or service.duration!=req.duration:
            raise acuity.AcuityError('booking_details_changed',True)
        catalog(service)
        if not slot_available(acuity.mapping(service),req.starts_at,req.timezone):raise acuity.AcuityError('not_available',True)
    except acuity.AcuityError as exc:
        if exc.definitive:order.booking_state='rejected';request_refund(order,'booking_failed')
        else:order.error_code=exc.code;db.session.commit()
        return
    write_lock();db.session.refresh(order);db.session.refresh(req)
    if order.booking_state!='waiting' or order.refund_requested or order.hold_reason:return
    claimed=db.session.execute(db.update(PaymentOrder).where(PaymentOrder.id==order.id,PaymentOrder.booking_state=='waiting',PaymentOrder.refund_requested==False,PaymentOrder.hold_reason=='').values(booking_state='creating'))
    if claimed.rowcount!=1:db.session.rollback();return
    req.state='creating';db.session.commit()
    try:
        result=acuity.api_request('POST','appointments',data=order.appointment_payload)
        item=save_snapshot(result,req);order.booking_state='confirmed';order.appointment_payload={};order.slot_key=None
        item.booking.payment_status='stripe_paid';db.session.commit()
    except acuity.AcuityError as exc:
        db.session.rollback();db.session.refresh(order);db.session.refresh(req)
        order.booking_state='rejected' if exc.definitive else 'uncertain';order.error_code=exc.code
        req.state='rejected' if exc.definitive else 'uncertain'
        if exc.definitive:request_refund(order,'booking_failed')
        db.session.commit()
    # If database persistence fails after Acuity succeeds, the durable creating state prevents a second POST.


def process_order(order,recover=True):
    check_scope(order)
    try:
        refresh_payment(order)
        mirror=AcuityAppointment.query.filter_by(request_id=order.id).first()
        if mirror:
            if mirror.scope!=acuity.scope():raise PaymentProblem('Restore the original Acuity scope to reconcile this appointment.')
            from .appointments import sync_one
            sync_one(mirror.provider_id)
        fulfill(order)
        if recover and order.refund_requested and order.charge_id:refund(order)
        elif recover and order.payment_state=='refunded':recover_transfer(order)
        if order.payment_state in ('refunded','expired') and order.booking_state not in ('creating','uncertain'):
            order.slot_key=None;order.appointment_payload={};order.request.dedupe_key=None
        if order.booking:order.booking.payment_status='stripe_'+order.payment_state
        order.checked_at=now()
        from . import finance
        finance.observe(order,source='Verified Stripe / Acuity reconciliation')
        db.session.commit()
    except (stripe.StripeError,PaymentProblem) as exc:
        db.session.rollback();db.session.refresh(order);order.error_code=exc.code if isinstance(exc,stripe.StripeError) else 'staff_review_required';order.checked_at=now();db.session.commit();raise


def transfer(order,retry=False):
    from .appointments import sync_one
    check_scope(order)
    process_order(order)
    mirror=AcuityAppointment.query.filter_by(request_id=order.id).first()
    if not mirror:raise PaymentProblem('There is no confirmed appointment.')
    sync_one(mirror.provider_id);db.session.refresh(order)
    tx=refresh_payment(order);ready=refresh_account(order.account)
    b=order.booking
    if not b or b.status!='confirmed' or b.start+timedelta(minutes=b.duration)>now() or not order.completion_approved_at:
        raise PaymentProblem('The session must have ended and completion must be approved.')
    if (order.payment_state!='paid' or order.refund_requested or order.hold_reason or order.refunded_cents or order.reversed_cents
        or StripeDispute.query.filter(StripeDispute.order_id==order.id,StripeDispute.status.notin_(['won','warning_closed'])).first()):raise PaymentProblem('Refund, dispute, or payment review blocks this transfer.')
    if not ready or order.destination!=order.account.account_id or not order.account.mentor or not order.account.mentor.publicly_visible:
        raise PaymentProblem('Mentor payment readiness must be resolved.')
    if not tx or tx.get('status')!='available' or tx.get('available_on',2**63)>int(now().replace(tzinfo=timezone.utc).timestamp()):
        raise PaymentProblem('Stripe has not made the payment funds available yet.')
    if order.mentor_cents==0:raise PaymentProblem('No mentor transfer is due for this allocation.')
    op=operation('transfer','transfer:'+order.id,{'amount':order.mentor_cents,'currency':'usd','destination':order.destination,
        'source_transaction':order.charge_id,'transfer_group':'ttbg_'+order.id,'metadata':{'ttbg_order':order.id}},'transfers',order=order,retry=retry)
    execute(op)
