"""v0.8 financial operations: attribution, independent provider states, and access."""
import re
from datetime import timedelta
import pytest
from test_workflows import app,login
from test_v06 import mock_app,webhook
from test_v07 import paid_app,begin,pay,ended,admin_action,event
from test_v03 import manager,PW
from test_v05 import delete
from app.models import (db,now,User,PaymentOrder,PaymentIdentity,PaymentCancellation,FinancialEvent,PaymentRefund,PaymentNotice,PaymentWorkerHealth,PaymentOperation,AcuityMockAppointment,StripeMockObject,SchemaRevision)
from app import finance,payment_engine as engine,stripe_api as stripe,stripe_mock,acuity

CANCEL={'reason_code':'schedule_conflict','reason':'Verified cancellation requested by the client','password':PW,'confirm':'y'}
def admin_cancel(app,oid,refund=False):
    c=app.test_client();login(c,'admin');data=dict(CANCEL)
    if refund:data['refund']='y'
    return c.post('/support/payments/'+oid+'/cancel-session',data=data,follow_redirects=True)

def test_admin_cancel_paid_exact_actor_and_refund(paid_app):
    app=paid_app;c,oid,_=pay(app)
    res=admin_cancel(app,oid,refund=True);assert res.status_code==200,res.text
    with app.app_context():
        o=db.session.get(PaymentOrder,oid);cancel=PaymentCancellation.query.one()
        assert o.payment_state=='refunded' and o.refunded_cents==10000
        assert o.booking.acuity.cancelled and finance.states(o)['appointment']=='cancelled'
        assert cancel.state=='confirmed' and cancel.performed_by=={'id':1,'name':'Admin','role':'admin'}
        assert finance.cancelled_by(o)=='Admin · Admin'
        assert FinancialEvent.query.filter_by(action='appointment_cancelled').count()==1
    assert 'Cancelled by: Admin · Admin' in res.text
    admin_cancel(app,oid,refund=True)
    with app.app_context():assert StripeMockObject.query.filter_by(kind='refund').count()==1


def test_cancel_without_refund_is_still_paid(paid_app):
    app=paid_app;c,oid,_=pay(app);res=admin_cancel(app,oid)
    with app.app_context():
        o=db.session.get(PaymentOrder,oid);s=finance.states(o)
        assert s['payment']=='paid' and s['appointment']=='cancelled' and s['earnings']=='held'
        assert StripeMockObject.query.filter_by(kind='refund').count()==0
    html=c.get('/payments/orders/'+oid).text
    assert 'Your session has been cancelled.' in html and 'reviewing the payment separately' in html


def test_mentee_unpaid_checkout_cancellation(paid_app):
    app=paid_app;c,oid,sid,_=begin(app)
    response=c.post('/payments/orders/'+oid+'/cancel-session',data=CANCEL,follow_redirects=True)
    assert response.status_code==200,response.text
    with app.app_context():
        o=db.session.get(PaymentOrder,oid)
        assert stripe_mock.get(sid)['status']=='expired'
        assert finance.states(o)['payment']=='cancelled' and not o.slot_key
        assert finance.cancelled_by(o)=='Mentee' and o.booking is None


def test_mentor_and_manager_requests_do_not_move_money(paid_app):
    app=paid_app;c,oid,_=pay(app)
    m=app.test_client();login(m,'mentor');assert m.post('/payments/orders/'+oid+'/cancel-session',data=CANCEL).status_code==302
    with app.app_context():
        o=db.session.get(PaymentOrder,oid);row=PaymentCancellation.query.one();assert row.requested_by['role']=='mentor'
        assert not o.booking.acuity.cancelled and o.payment_state=='paid'
    manager(app);mgr=app.test_client();login(mgr,'other')
    assert mgr.post('/support/payments/'+oid+'/cancel-session',data=CANCEL).status_code==403
    assert mgr.post('/support/payments/'+oid+'/refund',data=CANCEL).status_code==403
    admin_cancel(app,oid)
    with app.app_context():
        row=PaymentCancellation.query.one();assert row.requested_by['role']=='mentor' and row.performed_by['role']=='admin'


def test_account_manager_request_is_named(paid_app):
    app=paid_app;c,oid,_=pay(app);manager(app);mgr=app.test_client();login(mgr,'other')
    assert mgr.post('/payments/orders/'+oid+'/cancel-session',data=CANCEL).status_code==302
    with app.app_context():
        row=PaymentCancellation.query.one();assert row.requested_by['name']=='Other' and row.requested_by['role']=='account_manager'
    admin_cancel(app,oid)
    with app.app_context():assert finance.cancelled_by(db.session.get(PaymentOrder,oid))=='Admin · Admin'


def test_external_cancellation_unknown_initiator_and_expiry_not_cancellation(paid_app):
    app=paid_app;c,oid,_=pay(app)
    with app.app_context():
        row=AcuityMockAppointment.query.one();data=dict(row.payload);data['canceled']=True;row.payload=data;db.session.commit()
    assert webhook(app,action='canceled').status_code==204
    with app.app_context():
        o=db.session.get(PaymentOrder,oid);assert finance.cancelled_by(o)=='External / Acuity · Initiator unverified'
        assert not o.refunded_cents
    # Plain expired checkouts do not get a fabricated cancelling actor.
    with app.app_context():
        o=db.session.get(PaymentOrder,oid);o.payment_state='expired';db.session.commit()
        row=PaymentCancellation.query.one();assert row.performed_by['role']=='external'


def test_unknown_cancel_response_read_recovery_only(paid_app,monkeypatch):
    app=paid_app;c,oid,_=pay(app);original=acuity.api_request;calls=[]
    def timeout(method,path,*a,**kw):
        value=original(method,path,*a,**kw)
        if method=='PUT':calls.append(path);raise acuity.AcuityError('connection_failed')
        return value
    monkeypatch.setattr(acuity,'api_request',timeout)
    res=admin_cancel(app,oid);assert res.status_code==200
    with app.app_context():assert PaymentCancellation.query.one().state=='uncertain'
    monkeypatch.setattr(acuity,'api_request',original)
    result=app.test_cli_runner().invoke(args=['payments-worker','--once'])
    assert result.exit_code==0,result.output
    with app.app_context():assert PaymentCancellation.query.one().state=='confirmed'
    assert len(calls)==1


def test_completed_booking_requires_refund_review(paid_app):
    app=paid_app;c,oid,_=pay(app);ended(app,oid)
    res=admin_cancel(app,oid);assert res.status_code==200
    with app.app_context():assert PaymentCancellation.query.count()==0 and not db.session.get(PaymentOrder,oid).booking.acuity.cancelled
    assert c.post('/payments/orders/'+oid+'/refund-request',data=CANCEL).status_code==302
    with app.app_context():assert FinancialEvent.query.filter_by(action='refund_review_requested').count()==1


def test_friendly_ids_search_combined_filters_and_csv(paid_app):
    app=paid_app;c,oid,_=pay(app);admin=app.test_client();login(admin,'admin')
    with app.app_context():
        o=db.session.get(PaymentOrder,oid);reference=o.identity.reference;charge=o.charge_id
        assert reference.startswith('SIM-PAY-2026-')
    for search in (reference,charge,'Test','Mentor','Exam prep','1'):
        res=admin.get('/support/payments',query_string={'q':search,'payment':'paid','appointment':'confirmed'})
        assert res.status_code==200 and reference in res.text,res.text
    assert 'No payments match' in admin.get('/support/payments',query_string={'q':reference,'payment':'refunded'}).text
    result=admin.get('/support/payments/export.csv',query_string={'q':reference,'payment':'paid'})
    assert result.status_code==200 and reference in result.text and 'Cancelled by' in result.text
    assert 'password_hash' not in result.text and 'appointment_payload' not in result.text
    assert 'Choose a valid status' in admin.get('/support/payments?payment=forged').text
    assert 'valid date range' in admin.get('/support/payments?period=custom&start=no&end=no').text


def test_scope_isolation_and_formula_safe_export(paid_app):
    app=paid_app;c,oid,_=pay(app);admin=app.test_client();login(admin,'admin')
    with app.app_context():
        o=db.session.get(PaymentOrder,oid);o.identity.customer_name='=1+1';db.session.commit()
    assert "'=1+1" in admin.get('/support/payments/export.csv').text
    app.config['STRIPE_ACCOUNT_ID']='acct_different'
    assert 'SIM-PAY-' not in admin.get('/support/payments').text
    assert 'SIM-PAY-' not in admin.get('/support/payments/export.csv').text


def test_customer_page_hides_internal_panel_and_has_receipt(paid_app):
    app=paid_app;c,oid,_=pay(app);html=c.get('/payments/orders/'+oid).text
    assert 'Your session is confirmed.' in html
    assert 'Financial breakdown' not in html and 'Internal technical reference' not in html and 'FINANCIAL BREAKDOWN' not in html
    assert 'View Stripe receipt' in html and 'TTBG original gross allocation' not in html
    assert c.get('/payments/orders/'+oid+'/receipt').status_code==302
    other=app.test_client();login(other,'other');assert other.get('/payments/orders/'+oid+'/receipt').status_code==403


def test_financial_events_append_only_and_staff_identity_survives_rename(paid_app):
    app=paid_app;c,oid,_=pay(app);admin_cancel(app,oid)
    with app.app_context():
        row=FinancialEvent.query.filter_by(action='appointment_cancelled').one();eventid=row.id
        user=db.session.get(User,1);user.name='Renamed Admin';db.session.commit()
        assert row.performed_by['name']=='Admin'
        row.reason='overwrite history'
        with pytest.raises(ValueError):db.session.commit()
        db.session.rollback();assert db.session.get(FinancialEvent,eventid).reason!='overwrite history'
        db.session.delete(db.session.get(FinancialEvent,eventid))
        with pytest.raises(ValueError):db.session.commit()
        db.session.rollback()


def test_refund_requester_approver_and_history(paid_app):
    app=paid_app;c,oid,_=pay(app)
    assert c.post('/payments/orders/'+oid+'/refund-request',data=CANCEL).status_code==302
    admin_action(app,oid,'refund')
    with app.app_context():
        row=PaymentRefund.query.one();assert row.status=='succeeded' and row.requested_by['role']=='student' and row.approved_by['id']==1
        assert row.amount_cents==10000 and row.provider_id.startswith('re_')
        assert FinancialEvent.query.filter_by(action='refund_verified').count()==1
    admin_action(app,oid,'refund')
    with app.app_context():assert PaymentRefund.query.count()==1


def test_bad_auth_no_cancellation_and_csrf(paid_app):
    app=paid_app;c,oid,_=pay(app);admin=app.test_client();login(admin,'admin')
    assert admin.post('/support/payments/'+oid+'/cancel-session',data=dict(CANCEL,password='wrong')).status_code==403
    with app.app_context():assert PaymentCancellation.query.count()==0
    assert admin.post('/support/payments/'+oid+'/cancel-session',data=dict(CANCEL,reason_code='forged')).status_code==200
    app.config['WTF_CSRF_ENABLED']=True
    assert admin.post('/support/payments/'+oid+'/cancel-session',data=CANCEL).status_code==400


def test_worker_heartbeat_notifications_and_manage_stripe(paid_app):
    app=paid_app;c,oid,_=pay(app);admin_cancel(app,oid,refund=True)
    result=app.test_cli_runner().invoke(args=['payments-worker','--once']);assert result.exit_code==0,result.output
    with app.app_context():
        h=db.session.get(PaymentWorkerHealth,stripe.scope());assert h.completed_at and not h.failures
        assert PaymentNotice.query.count()>0 and not PaymentNotice.query.filter_by(state='sent').first()
    mentor=app.test_client();login(mentor,'mentor');assert mentor.post('/payments/connect/manage').status_code==303
    assert c.post('/payments/connect/manage').status_code==403


def test_pagination_preserves_filters_and_totals(paid_app):
    app=paid_app;c,oid,sid,_=begin(app)
    from app.models import AcuityRequest
    with app.app_context():
        original=db.session.get(PaymentOrder,oid)
        for i in range(27):
            rid=f'{i:032x}';req=AcuityRequest(id=rid,user_id=3,service_id=1,scope=original.request.scope,calendar_id='101',type_id='201',starts_at=original.request.starts_at,
                timezone='UTC',email='student@example.com',service_name='Pagination session',price_cents=10000,duration=60,fee_bps=2000,state='payment_pending')
            db.session.add(req);db.session.flush()
            o=PaymentOrder(id=rid,account_row_id=original.account_row_id,destination=original.destination,scope=original.scope,gross_cents=10000,mentor_cents=8000,platform_cents=2000,expires_at=now()+timedelta(minutes=30))
            db.session.add(o);db.session.flush();finance.observe(o)
        db.session.commit()
    admin=app.test_client();login(admin,'admin');html=admin.get('/support/payments?q=Pagination&sort=oldest').text
    assert '27 payments' in html and 'q=Pagination' in html and 'page=2' in html
    assert '27 payments' in admin.get('/support/payments?q=Pagination&sort=oldest&page=2').text


def test_unpaid_checkout_payment_race_requires_admin_review(paid_app):
    app=paid_app;c,oid,sid,_=begin(app)
    with app.app_context():stripe_mock.pay(sid)
    c.post('/payments/orders/'+oid+'/cancel-session',data=CANCEL)
    with app.app_context():
        o=db.session.get(PaymentOrder,oid);assert o.payment_state=='paid' and not o.booking and o.hold_reason
        assert not o.refunded_cents
    res=admin_cancel(app,oid,refund=True)
    with app.app_context():
        o=db.session.get(PaymentOrder,oid);assert o.payment_state=='refunded',res.text
        assert not o.booking and o.booking_state=='cancelled'
        assert finance.cancelled_by(o)=='Admin · Admin'


def test_external_pending_partial_never_expands_to_full_refund(paid_app):
    app=paid_app;c,oid,_=pay(app)
    with app.app_context():
        o=db.session.get(PaymentOrder,oid);original=stripe_mock.get(o.charge_id)
        r=stripe.api('POST','refunds',{'charge':o.charge_id,'amount':2000},key='external-pending')
        r['status']='pending';stripe_mock.put(r);stripe_mock.put(original)
        engine.process_order(o)
        assert o.payment_state=='refund_pending' and not o.refund_requested
        r['status']='succeeded';stripe_mock.put(r);original['amount_refunded']=2000;stripe_mock.put(original)
        engine.process_order(o)
        assert o.refunded_cents==2000 and o.payment_state=='partially_refunded'
        assert StripeMockObject.query.filter_by(kind='refund').count()==1


def test_migration_backfills_without_fabricated_actor_or_changed_amounts(paid_app):
    from app.upgrade import upgrade
    app=paid_app;c,oid,_=pay(app)
    with app.app_context():
        o=db.session.get(PaymentOrder,oid);before=(o.gross_cents,o.mentor_cents,o.platform_cents,o.charge_id,o.request.fee_bps)
        identity=o.identity;reference=identity.reference
        # Simulate a v0.7 order with no v0.8 identity; no financial events are removed.
        db.session.delete(identity);db.session.commit()
        upgrade();upgrade();db.session.refresh(o)
        assert (o.gross_cents,o.mentor_cents,o.platform_cents,o.charge_id,o.request.fee_bps)==before
        assert o.identity and FinancialEvent.query.filter_by(action='historical_record_imported').count()==1
        imported=FinancialEvent.query.filter_by(action='historical_record_imported').one()
        assert imported.performed_by['role']=='system' and not imported.performed_by['id']
        assert finance.cancelled_by(o)=='—'


def test_v071_checkout_and_csp_fixes_preserved(paid_app):
    app=paid_app;c,oid,sid,_=begin(app)
    with app.app_context():
        op=PaymentOperation.query.filter_by(owner_key='checkout:'+oid).one()
        assert 'payment_method_types' not in op.params
    csp=c.get('/payments/orders/'+oid).headers['Content-Security-Policy']
    assert "form-action 'self' https://connect.stripe.com https://checkout.stripe.com" in csp
    assert "form-action *" not in csp


def test_receipt_allowlist_rejects_unsafe_provider_url(paid_app,monkeypatch):
    app=paid_app;c,oid,_=pay(app);original=stripe.api
    app.config['STRIPE_MODE']='test'
    with app.app_context():db.session.get(PaymentOrder,oid).scope='test:acct_local';db.session.commit()
    def forged(method,path,*args,**kwargs):
        result=original(method,path,*args,**kwargs)
        result=dict(result,receipt_url='https://evil.example/receipt')
        return result
    # Return a controlled canonical charge without contacting an external provider.
    with app.app_context():
        o=db.session.get(PaymentOrder,oid);chargeid=o.charge_id;amount=o.gross_cents
    monkeypatch.setattr(stripe,'api',lambda *a,**kw:{'id':chargeid,'amount':amount,'receipt_url':'https://evil.example/receipt'})
    res=c.get('/payments/orders/'+oid+'/receipt');assert res.status_code==302 and 'evil.example' not in res.location


def test_no_show_from_acuity_is_independent_and_holds_earnings(paid_app):
    app=paid_app;c,oid,_=pay(app)
    with app.app_context():
        row=AcuityMockAppointment.query.one();payload=dict(row.payload);payload.update(canceled=True,noShow=True);row.payload=payload;db.session.commit()
    webhook(app)
    with app.app_context():
        o=db.session.get(PaymentOrder,oid);state=finance.states(o)
        assert state['appointment']=='no_show' and state['earnings']=='held' and o.payment_state=='paid'


def test_refund_pending_failed_and_retry_are_separate_history(paid_app,monkeypatch):
    app=paid_app;c,oid,_=pay(app);original=stripe.api
    with app.app_context():charge=stripe_mock.get(db.session.get(PaymentOrder,oid).charge_id)
    def pending(method,path,*args,**kwargs):
        result=original(method,path,*args,**kwargs)
        if method=='POST' and path=='refunds':
            result=dict(result,status='pending');stripe_mock.put(result);stripe_mock.put(charge)
        return result
    monkeypatch.setattr(stripe,'api',pending);admin_action(app,oid,'refund');monkeypatch.setattr(stripe,'api',original)
    with app.app_context():
        o=db.session.get(PaymentOrder,oid);assert o.payment_state=='refund_pending' and o.refunded_cents==0
        assert FinancialEvent.query.filter_by(order_id=oid,action='admin_refund').order_by(FinancialEvent.id.desc()).first().outcome=='pending'
        assert FinancialEvent.query.filter_by(order_id=oid,action='operation_refund').order_by(FinancialEvent.id.desc()).first().outcome=='pending'
        record=PaymentRefund.query.one();provider=stripe_mock.get(record.provider_id);provider['status']='failed';stripe_mock.put(provider);engine.process_order(o)
        assert o.payment_state=='refund_failed' and record.status=='failed'
    admin_action(app,oid,'retry_refund')
    with app.app_context():
        assert db.session.get(PaymentOrder,oid).payment_state=='refunded'
        assert PaymentRefund.query.count()==2
        assert PaymentRefund.query.filter_by(status='failed').count()==1
        assert PaymentRefund.query.filter_by(status='succeeded').count()==1


def test_date_filters_use_explicit_local_boundaries(paid_app):
    from datetime import datetime
    app=paid_app;c,oid,_=pay(app);admin=app.test_client();login(admin,'admin')
    with app.app_context():o=db.session.get(PaymentOrder,oid);o.created_at=datetime(2026,10,15,2,30);db.session.commit()
    args={'period':'custom','start':'2026-10-14','end':'2026-10-14','tz':'America/New_York'}
    assert '1 payments' in admin.get('/support/payments',query_string=args).text
    args['tz']='UTC';assert 'No payments match' in admin.get('/support/payments',query_string=args).text


def test_notification_review_is_admin_only_and_audited(paid_app):
    app=paid_app;c,oid,_=pay(app);admin_cancel(app,oid,refund=True)
    with app.app_context():
        row=PaymentNotice.query.first();noticeid=row.id;row.state='uncertain';row.attempted_at=now()-timedelta(minutes=15);db.session.commit()
    manager(app);mgr=app.test_client();login(mgr,'other')
    assert mgr.get('/support/payments/notices').status_code==200
    assert mgr.post('/support/payments/notices',data=dict(CANCEL,notice_id=noticeid,action='retry')).status_code==403
    admin=app.test_client();login(admin,'admin')
    assert admin.post('/support/payments/notices',data=dict(CANCEL,notice_id=noticeid,action='retry')).status_code==302
    with app.app_context():assert db.session.get(PaymentNotice,noticeid).state=='queued' and FinancialEvent.query.filter_by(action='notification_retry').count()==1


def test_atomic_operation_lease_prevents_duplicate_money_write(paid_app,monkeypatch):
    app=paid_app;c,oid,_=pay(app);original=stripe.api;calls=[]
    with app.app_context():
        order=db.session.get(PaymentOrder,oid);engine.request_refund(order,'admin_refund')
        op=engine.operation('refund','refund:'+oid,{'charge':order.charge_id,'amount':10000,'metadata':{'ttbg_order':oid}},'refunds',order=order)
        def interleaved(method,path,*args,**kwargs):
            if method=='POST' and path=='refunds':
                calls.append(path)
                # A second attempt observes the committed running lease before provider submission.
                with pytest.raises(engine.PaymentProblem):engine.execute(db.session.get(PaymentOperation,op.id))
            return original(method,path,*args,**kwargs)
        monkeypatch.setattr(stripe,'api',interleaved);engine.execute(op)
        assert len(calls)==1 and StripeMockObject.query.filter_by(kind='refund').count()==1


def test_failed_refresh_does_not_advance_successful_verification(paid_app,monkeypatch):
    app=paid_app;c,oid,_=pay(app)
    with app.app_context():
        o=db.session.get(PaymentOrder,oid);assert o.identity.stripe_verified_at and o.identity.acuity_verified_at
        before=o.identity.stripe_verified_at
        monkeypatch.setattr(stripe,'api',lambda *a,**kw:(_ for _ in ()).throw(stripe.StripeError('connection_failed')))
        with pytest.raises(stripe.StripeError):engine.process_order(o)
        assert o.identity.stripe_verified_at==before


def test_acuity_no_show_correction_appends_without_erasing_history(paid_app):
    app=paid_app;c,oid,_=pay(app)
    with app.app_context():
        row=AcuityMockAppointment.query.one();payload=dict(row.payload);payload.update(canceled=True,noShow=True);row.payload=payload;db.session.commit()
    webhook(app)
    with app.app_context():
        row=AcuityMockAppointment.query.one();payload=dict(row.payload);payload['noShow']=False;row.payload=payload;db.session.commit()
    webhook(app)
    with app.app_context():
        assert finance.states(db.session.get(PaymentOrder,oid))['appointment']=='cancelled'
        assert FinancialEvent.query.filter_by(action='no_show_verified').count()==1
        assert FinancialEvent.query.filter_by(action='no_show_cleared').count()==1
