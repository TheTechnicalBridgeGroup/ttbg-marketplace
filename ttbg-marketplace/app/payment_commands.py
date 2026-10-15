"""Run from a dedicated worker or scheduled job; does not retry Acuity creation."""
import time
from datetime import timedelta
import click
from .models import db,PaymentOrder,PaymentOperation,StripeAccount,StripeEvent,StripeDispute,PaymentWorkerHealth,PaymentCancellation,now
from . import stripe_api as stripe
from . import payment_engine as engine

def process_event(event):
    kind=event.event_type;oid=event.object_id;order=None
    if kind=='account.updated':
        row=StripeAccount.query.filter_by(scope=stripe.scope(),account_id=oid).first()
        if row:engine.refresh_account(row)
    elif kind.startswith('checkout.session.'):
        data=stripe.api('GET','checkout/sessions/'+oid)
        order=db.session.get(PaymentOrder,data.get('metadata',{}).get('ttbg_order',''))
        if order and order.scope==stripe.scope() and not order.session_id:
            op=PaymentOperation.query.filter_by(scope=stripe.scope(),owner_key='checkout:'+order.id).first()
            if op:engine.apply_result(op,data)
    elif kind.startswith('charge.dispute.'):
        data=stripe.api('GET','disputes/'+oid)
        order=PaymentOrder.query.filter_by(scope=stripe.scope(),charge_id=data.get('charge')).first()
        if order:
            record=db.session.get(StripeDispute,oid)
            if not record:record=StripeDispute(id=oid,order_id=order.id,status=data['status']);db.session.add(record)
            record.status=data['status'];order.hold_reason='dispute';db.session.commit()
    elif kind.startswith('charge.'):
        order=PaymentOrder.query.filter_by(scope=stripe.scope(),charge_id=oid).first()
    elif kind.startswith('payment_intent.'):
        data=stripe.api('GET','payment_intents/'+oid)
        order=db.session.get(PaymentOrder,data.get('metadata',{}).get('ttbg_order',''))
        if order and order.scope==stripe.scope() and kind=='payment_intent.payment_failed' and data.get('status')=='requires_payment_method':
            from . import finance
            finance.emit(order,'payment_attempt_failed','failed',performed=finance.actor(source='Stripe'),provider=data['id'],error='payment_not_completed',key='stripe-attempt:'+event.event_id)
            db.session.commit()
    elif kind.startswith('refund.'):
        data=stripe.api('GET','refunds/'+oid)
        order=PaymentOrder.query.filter_by(scope=stripe.scope(),charge_id=data.get('charge')).first()
    elif kind.startswith('transfer.'):
        # transfer.reversed events contain the transfer itself.
        data=stripe.api('GET','transfers/'+oid)
        order=db.session.get(PaymentOrder,data.get('metadata',{}).get('ttbg_order',''))
        if order and order.scope==stripe.scope():
            op=PaymentOperation.query.filter_by(scope=stripe.scope(),owner_key='transfer:'+order.id).first()
            if op:engine.apply_result(op,data)
    if order and order.scope==stripe.scope():engine.process_order(order)
    event.pending=False;event.error_code='';event.checked_at=now();db.session.commit()

def run_once(limit):
    health=db.session.get(PaymentWorkerHealth,stripe.scope())
    if not health:health=PaymentWorkerHealth(scope=stripe.scope());db.session.add(health)
    health.started_at=now();db.session.commit()
    events=StripeEvent.query.filter_by(scope=stripe.scope(),pending=True).order_by(StripeEvent.checked_at).limit(limit).all()
    failures=0
    for e in events:
        eid=e.id
        try:process_event(e)
        except Exception as exc:
            db.session.rollback();e=db.session.get(StripeEvent,eid);e.pending=True;e.checked_at=now()
            e.error_code=exc.code if isinstance(exc,stripe.StripeError) else 'processing_review_required';db.session.commit();failures+=1
    # Active recovery has priority; settled history is checked hourly, or immediately by events.
    active=db.or_(PaymentOrder.payment_state.in_(['unpaid','refund_pending','refund_failed']),
        PaymentOrder.booking_state.in_(['waiting','creating','uncertain']) & PaymentOrder.payment_state.notin_(['expired','refunded']),
        (PaymentOrder.refund_requested==True) & (PaymentOrder.payment_state!='refunded'),
        (PaymentOrder.payment_state=='refunded') & PaymentOrder.transfer_id.is_not(None) & (PaymentOrder.reversed_cents<PaymentOrder.mentor_cents))
    due=db.or_(active & (PaymentOrder.checked_at<=now()-timedelta(seconds=30)),~active & (PaymentOrder.checked_at<=now()-timedelta(hours=1)))
    orders=PaymentOrder.query.filter(PaymentOrder.scope==stripe.scope(),due).order_by(db.case((active,0),else_=1),PaymentOrder.checked_at).limit(limit).all()
    for o in orders:
        oid=o.id
        try:engine.process_order(o)
        except Exception as exc:
            db.session.rollback();o=db.session.get(PaymentOrder,oid);o.checked_at=now()
            o.error_code=exc.code if isinstance(exc,stripe.StripeError) else 'processing_review_required';db.session.commit();failures+=1
    # Cancellation writes are never retried by the worker: only read canonical provider state.
    for row in PaymentCancellation.query.join(PaymentOrder,PaymentOrder.id==PaymentCancellation.order_id).filter(PaymentOrder.scope==stripe.scope(),PaymentCancellation.state.in_(['processing','uncertain'])).limit(limit):
        try:
            from .finance import reconcile_cancel
            reconcile_cancel(db.session.get(PaymentOrder,row.order_id),row)
        except Exception:
            db.session.rollback();failures+=1
    from .payment_notices import run_notices
    run_notices(min(limit,25))
    health=db.session.get(PaymentWorkerHealth,stripe.scope());health.completed_at=now();health.failures=failures
    health.events_processed=len(events);health.orders_processed=len(orders);db.session.commit()
    return len(events),len(orders),failures

def register(app):
    @app.cli.command('payments-worker')
    @click.option('--once',is_flag=True,help='Run one batch, suitable for a one-minute scheduler.')
    @click.option('--limit',default=100,type=click.IntRange(1,1000))
    def worker(once,limit):
        if not stripe.configured():raise click.ClickException('Configure Stripe credentials and account scope first.')
        while True:
            events,orders,failures=run_once(limit)
            click.echo(f'Payments: {events} webhook jobs, {orders} orders, {failures} requiring retry/review.')
            db.session.remove()
            if once:
                if failures:raise click.ClickException('Some payment jobs require retry or staff review; no raw provider data was logged.')
                return
            time.sleep(10)

    @app.cli.command('stripe-mock-session-ended')
    @click.option('--order',required=True)
    def ended(order):
        if stripe.mode()!='mock':raise click.ClickException('Only available in isolated local Stripe mock mode.')
        from datetime import timedelta,timezone
        from .models import AcuityAppointment,AcuityMockAppointment
        from .appointments import sync_one
        row=db.session.get(PaymentOrder,order)
        mirror=AcuityAppointment.query.filter_by(request_id=order).first()
        if not row or not mirror:raise click.ClickException('Create a paid local mock appointment first.')
        provider=db.session.get(AcuityMockAppointment,int(mirror.provider_id))
        starts=now()-timedelta(minutes=row.request.duration+10)
        payload=dict(provider.payload);payload['datetime']=starts.replace(tzinfo=timezone.utc).isoformat();provider.payload=payload
        row.request.starts_at=starts;db.session.commit();sync_one(mirror.provider_id)
        click.echo('Local simulated session moved into the past. Mentor completion and Admin approval are still required.')
