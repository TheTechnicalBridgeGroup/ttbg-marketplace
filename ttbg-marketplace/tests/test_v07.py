"""Payment lifecycle tests exercise persistent provider simulations and signed events."""
import hashlib,hmac,json,re,time
from datetime import timedelta
import pytest
from test_workflows import app,login
from test_v06 import mock_app,slot,webhook
from test_v03 import manager,PW
from test_v05 import delete
from app.models import db,PaymentOrder,PaymentOperation,StripeAccount,StripeEvent,StripeMockObject,Booking,AcuityRequest,AcuityMockAppointment,Service,now
from app import payment_engine as engine,stripe_api as stripe,stripe_mock
from app.acuity_mock import config as mock_config

@pytest.fixture
def paid_app(mock_app,monkeypatch):
    mock_app.config.update(STRIPE_MODE='mock',STRIPE_ACCOUNT_ID='acct_local',STRIPE_SECRET_KEY='local-stripe-dummy-key',STRIPE_WEBHOOK_SECRET='whsec_local',PAYMENTS_ENABLED=True)
    monkeypatch.setattr('app.stripe_api.build_opener',lambda *a,**k:pytest.fail('No network in mock mode'))
    mentor=mock_app.test_client();login(mentor,'mentor')
    assert mentor.post('/payments/connect').status_code==302
    assert mentor.post('/payments/mock/ready').status_code==302
    return mock_app

def begin(app,who='student'):
    c=app.test_client();login(c,who)
    page=c.get('/appointments/new/1',query_string={'time':slot(app),'timezone':'UTC'})
    assert page.status_code==200 and 'Continue to secure checkout' in page.text,page.text
    data={n:re.search(r'name="'+n+r'"[^>]*value="([^"]+)"',page.text).group(1) for n in ('request_id','quote')}
    data.update(first_name='Test',last_name='Student',phone='+12125550123',acknowledge='y',field_401='Exam practice')
    result=c.post('/appointments/new/1',data=data)
    assert result.status_code==302,result.text
    with app.app_context():
        o=db.session.get(PaymentOrder,data['request_id']);assert o is not None
        oid=o.id;sid=o.session_id
    assert sid
    return c,oid,sid,data

def pay(app):
    c,oid,sid,data=begin(app)
    res=c.post('/payments/mock/checkout/'+sid)
    assert res.status_code==302,res.text
    return c,oid,sid

def admin_action(app,oid,action):
    c=app.test_client();login(c,'admin')
    return c.post('/support/payments/'+oid+'/'+action,data=dict(password=PW,reason='Verified session and financial records',confirm='y'),follow_redirects=True)

def ended(app,oid):
    result=app.test_cli_runner().invoke(args=['stripe-mock-session-ended','--order',oid])
    assert result.exit_code==0,result.output

def event(app,sid,kind='checkout.session.completed',eid='evt_local',valid=True,live=False,timestamp=None):
    raw=json.dumps({'id':eid,'type':kind,'livemode':live,'data':{'object':{'id':sid}}}).encode()
    ts=str(timestamp or int(time.time()));sig=hmac.new(b'whsec_local',ts.encode()+b'.'+raw,hashlib.sha256).hexdigest()
    return app.test_client().post('/webhooks/stripe',data=raw,content_type='application/json',headers={'Stripe-Signature':'t='+ts+',v1='+(sig if valid else '0'*64)})

def test_checkout_then_payment_exact_allocation_and_ui(paid_app):
    app=paid_app;c,oid,sid,data=begin(app)
    with app.app_context():
        assert Booking.query.count()==0 and AcuityMockAppointment.query.count()==0
        o=db.session.get(PaymentOrder,oid);assert (o.gross_cents,o.mentor_cents,o.platform_cents)==(10000,8000,2000)
    assert 'not confirmed' in c.get('/payments/orders/'+oid).text
    assert c.post('/payments/orders/'+oid+'/checkout').status_code==303
    assert c.post('/payments/mock/checkout/'+sid).status_code==302
    with app.app_context():
        o=db.session.get(PaymentOrder,oid)
        assert (o.payment_state,o.booking_state)==('paid','confirmed')
        assert o.stripe_fee_cents==320 and o.mentor_cents==8000 and not o.appointment_payload
        assert Booking.query.one().payment_status=='stripe_paid'
    assert 'No payment was collected' not in c.get('/bookings/1').text
    for path in ('/payments','/payments/orders/'+oid,'/bookings/1'):
        assert c.get(path).status_code==200
    c.post('/appointments/new/1',data=data);c.post('/payments/mock/checkout/'+sid)
    with app.app_context():assert AcuityMockAppointment.query.count()==1 and PaymentOrder.query.count()==1
    for who,paths in [('admin',['/support/payments','/payments/orders/'+oid]),('mentor',['/payments','/payments/connect','/payments/orders/'+oid])]:
        client=app.test_client();login(client,who)
        for path in paths:assert client.get(path).status_code==200


def test_signed_inbox_worker_and_replay(paid_app):
    app=paid_app;c,oid,sid,_=begin(app)
    with app.app_context():stripe_mock.pay(sid)
    assert event(app,sid,valid=False).status_code==403
    assert event(app,sid,live=True).status_code==400
    assert event(app,sid,timestamp=int(time.time())-400).status_code==403
    assert event(app,sid).status_code==200 and event(app,sid).status_code==200
    with app.app_context():assert StripeEvent.query.count()==1 and Booking.query.count()==0
    result=app.test_cli_runner().invoke(args=['payments-worker','--once']);assert result.exit_code==0,result.output
    assert event(app,sid,kind='checkout.session.expired',eid='evt_late').status_code==200
    app.test_cli_runner().invoke(args=['payments-worker','--once'])
    with app.app_context():assert Booking.query.count()==1 and db.session.get(PaymentOrder,oid).payment_state=='paid'


def test_slot_taken_after_payment_refunds(paid_app):
    c,oid,sid,_=begin(paid_app)
    with paid_app.app_context():mock_config().scenario='unavailable';db.session.commit()
    c.post('/payments/mock/checkout/'+sid)
    with paid_app.app_context():
        o=db.session.get(PaymentOrder,oid);assert o.payment_state=='refunded' and o.refunded_cents==10000
        assert o.booking_state=='rejected' and not o.slot_key and not o.appointment_payload
        assert Booking.query.count()==0 and StripeMockObject.query.filter_by(kind='refund').count()==1
    c.post('/payments/orders/'+oid+'/refresh')
    with paid_app.app_context():assert StripeMockObject.query.filter_by(kind='refund').count()==1


def test_uncertain_acuity_never_retries_and_reconciles(paid_app):
    app=paid_app;c,oid,sid,_=begin(app)
    with app.app_context():mock_config().scenario='timeout_after_create';db.session.commit()
    c.post('/payments/mock/checkout/'+sid)
    c.post('/payments/orders/'+oid+'/refresh')
    with app.app_context():
        o=db.session.get(PaymentOrder,oid);assert o.payment_state=='paid' and o.booking_state=='uncertain'
        assert AcuityMockAppointment.query.count()==1 and Booking.query.count()==0
    assert 'Reconcile the uncertain' in admin_action(app,oid,'refund').text
    staff=app.test_client();login(staff,'admin')
    assert staff.post('/support/appointment-requests/'+oid,data={'operation':'link','provider_id':'1','password':PW,'reason':'Verified exact appointment in Acuity'}).status_code==302
    c.post('/payments/orders/'+oid+'/refresh')
    with app.app_context():assert db.session.get(PaymentOrder,oid).booking_state=='confirmed' and Booking.query.count()==1


def test_completion_approved_transfer_and_full_refund(paid_app):
    app=paid_app;c,oid,_=pay(app)
    admin_action(app,oid,'transfer')
    with app.app_context():assert StripeMockObject.query.filter_by(kind='transfer').count()==0
    ended(app,oid)
    m=app.test_client();login(m,'mentor');assert m.post('/payments/orders/'+oid+'/complete').status_code==302
    assert admin_action(app,oid,'approve_completion').status_code==200
    result=admin_action(app,oid,'transfer');assert result.status_code==200
    with app.app_context():
        o=db.session.get(PaymentOrder,oid);assert o.transfer_id,result.text
        assert stripe_mock.get(o.transfer_id)['amount']==8000
    admin_action(app,oid,'transfer')
    with app.app_context():assert StripeMockObject.query.filter_by(kind='transfer').count()==1
    admin_action(app,oid,'refund');admin_action(app,oid,'refund')
    with app.app_context():
        o=db.session.get(PaymentOrder,oid);assert o.refunded_cents==10000 and o.reversed_cents==8000
        assert StripeMockObject.query.filter_by(kind='refund').count()==1 and StripeMockObject.query.filter_by(kind='transfer_reversal').count()==1


def test_privacy_role_checks_and_csrf(paid_app):
    app=paid_app;c,oid,_=pay(app)
    for who in ('other','mentor'):
        other=app.test_client();login(other,who)
        assert other.post('/support/payments/'+oid+'/refund',data=dict(password=PW,reason='Full refund',confirm='y')).status_code==403
        if who=='other':assert other.get('/payments/orders/'+oid).status_code==403
    manager(app);mgr=app.test_client();login(mgr,'other')
    assert mgr.get('/support/payments').status_code==200
    assert mgr.post('/support/payments/'+oid+'/refund').status_code==403
    admin=app.test_client();login(admin,'admin')
    admin.post('/support/payments/'+oid+'/refund',data=dict(password='wrong',reason='Full refund',confirm='y'))
    with app.app_context():assert StripeMockObject.query.filter_by(kind='refund').count()==0
    app.config['WTF_CSRF_ENABLED']=True
    assert admin.post('/support/payments/'+oid+'/refund').status_code==400


def test_expired_checkout_releases_slot_and_no_booking(paid_app):
    app=paid_app;c,oid,sid,_=begin(app)
    with app.app_context():
        data=stripe_mock.get(sid);data['expires_at']=int(time.time())-10;stripe_mock.put(data)
    c.post('/payments/orders/'+oid+'/refresh')
    with app.app_context():
        o=db.session.get(PaymentOrder,oid);assert o.payment_state=='expired' and not o.slot_key and not o.appointment_payload
        assert not o.request.dedupe_key and Booking.query.count()==0


def test_amount_tamper_fails_closed(paid_app):
    app=paid_app;c,oid,sid,_=begin(app)
    with app.app_context():
        stripe_mock.pay(sid);data=stripe_mock.get(sid);data['amount_total']=1;stripe_mock.put(data)
    c.post('/payments/orders/'+oid+'/refresh')
    with app.app_context():assert Booking.query.count()==0 and not db.session.get(PaymentOrder,oid).charge_id


def test_idempotency_unknown_result_recovers_without_second_charge(paid_app,monkeypatch):
    app=paid_app;original=stripe.api
    def timeout(method,path,*args,**kw):
        result=original(method,path,*args,**kw)
        if method=='POST' and path=='checkout/sessions':raise stripe.StripeError('connection_lost')
        return result
    monkeypatch.setattr(stripe,'api',timeout)
    # Get and submit manually: first result deliberately has no session ID.
    c=app.test_client();login(c,'student');html=c.get('/appointments/new/1',query_string={'time':slot(app),'timezone':'UTC'}).text
    data={n:re.search(r'name="'+n+r'"[^>]*value="([^"]+)"',html).group(1) for n in ('request_id','quote')}
    data.update(first_name='Test',last_name='Student',phone='+12125550123',acknowledge='y',field_401='Help')
    assert c.post('/appointments/new/1',data=data).status_code==302
    monkeypatch.setattr(stripe,'api',original)
    c.post('/payments/orders/'+data['request_id']+'/refresh')
    with app.app_context():
        assert db.session.get(PaymentOrder,data['request_id']).session_id
        assert StripeMockObject.query.filter_by(kind='checkout.session').count()==1


def test_retry_window_requires_reconcile(paid_app):
    with paid_app.app_context():
        op=engine.operation('account','old-op',{'metadata':{'ttbg_mentor':'1'}},'accounts')
        op.attempted_at=now()-timedelta(hours=24);op.state='uncertain';db.session.commit()
        with pytest.raises(engine.PaymentProblem):engine.execute(op)
        assert op.state=='manual_review'


def test_local_free_consultation_skips_stripe(paid_app):
    from test_v06 import book
    with paid_app.app_context():
        s=db.session.get(Service,1);s.acuity_type_id='202';s.price_cents=0;s.duration=30;db.session.commit()
    paid_app.config['STRIPE_SECRET_KEY']=''
    c,_,r=book(paid_app)
    assert 'FREE' in c.get(r.location,follow_redirects=True).text
    with paid_app.app_context():assert PaymentOrder.query.count()==0 and Booking.query.count()==1


def test_cancellation_holds_transfer_and_reschedule_resets_approval(paid_app):
    app=paid_app;c,oid,_=pay(app);ended(app,oid);admin_action(app,oid,'approve_completion')
    with app.app_context():
        assert db.session.get(PaymentOrder,oid).completion_approved_at
        a=AcuityMockAppointment.query.one();data=dict(a.payload);data['datetime']=slot(app);a.payload=data;db.session.commit()
    assert webhook(app).status_code==204
    with app.app_context():
        assert db.session.get(PaymentOrder,oid).completion_approved_at is None
        a=AcuityMockAppointment.query.one();data=dict(a.payload);data['canceled']=True;a.payload=data;db.session.commit()
    webhook(app);admin_action(app,oid,'transfer')
    with app.app_context():assert db.session.get(PaymentOrder,oid).hold_reason=='cancellation_review' and StripeMockObject.query.filter_by(kind='transfer').count()==0


def test_delete_mentor_preserves_financial_record(paid_app):
    app=paid_app;c,oid,_=pay(app)
    admin=app.test_client();login(admin,'admin');response=delete(admin,2,'mentor@example.com')
    assert response.status_code==302,response.text
    with app.app_context():
        o=db.session.get(PaymentOrder,oid);assert o.account.mentor_id is None and o.hold_reason=='account_deleted'
        assert o.request.service_id is None and Booking.query.count()==1


def test_deleted_student_late_payment_refunds(paid_app):
    app=paid_app;c,oid,sid,_=begin(app)
    admin=app.test_client();login(admin,'admin');assert delete(admin,3,'student@example.com').status_code==302
    with app.app_context():stripe_mock.pay(sid);engine.process_order(db.session.get(PaymentOrder,oid))
    with app.app_context():
        o=db.session.get(PaymentOrder,oid);assert o.payment_state=='refunded' and not o.request.user_id and not o.appointment_payload
        assert Booking.query.count()==0


def test_onboarding_return_is_not_approval(mock_app):
    app=mock_app;app.config.update(STRIPE_MODE='mock',STRIPE_ACCOUNT_ID='acct_local',STRIPE_SECRET_KEY='local-stripe-dummy-key')
    c=app.test_client();login(c,'mentor');assert c.post('/payments/connect').status_code==302
    c.get('/payments/connect/return')
    with app.app_context():assert not StripeAccount.query.one().ready
    app.config['PAYMENTS_ENABLED']=True;app.config['STRIPE_WEBHOOK_SECRET']='whsec_local'
    student=app.test_client();login(student,'student')
    assert 'still completing payment setup' in student.get('/appointments/new/1',query_string={'time':slot(app),'timezone':'UTC'}).text


def test_feature_flag_new_checkout_only(paid_app):
    c,oid,sid,_=begin(paid_app);paid_app.config['PAYMENTS_ENABLED']=False
    assert c.post('/payments/orders/'+oid+'/checkout').status_code==409
    # An already-open Stripe session is still settled and reconciled.
    c.post('/payments/mock/checkout/'+sid)
    with paid_app.app_context():assert db.session.get(PaymentOrder,oid).booking_state=='confirmed'


def test_external_refund_recovers_transfer_and_partial_does_not_auto_refund(paid_app):
    app=paid_app;c,oid,_=pay(app);ended(app,oid);admin_action(app,oid,'approve_completion');admin_action(app,oid,'transfer')
    with app.app_context():
        o=db.session.get(PaymentOrder,oid)
        stripe.api('POST','refunds',{'charge':o.charge_id,'amount':2000},key='external-partial')
        engine.process_order(o)
        assert o.payment_state=='partially_refunded' and o.refunded_cents==2000 and o.reversed_cents==0
        assert not o.refund_requested
        stripe.api('POST','refunds',{'charge':o.charge_id,'amount':8000},key='external-remainder')
        engine.process_order(o)
        assert o.payment_state=='refunded' and o.reversed_cents==8000


def test_refund_unknown_result_does_not_refund_twice(paid_app,monkeypatch):
    app=paid_app;c,oid,_=pay(app);original=stripe.api
    def timeout(method,path,*a,**kw):
        data=original(method,path,*a,**kw)
        if method=='POST' and path=='refunds':raise stripe.StripeError('stripe_connection_failed')
        return data
    monkeypatch.setattr(stripe,'api',timeout);admin_action(app,oid,'refund');monkeypatch.setattr(stripe,'api',original)
    c.post('/payments/orders/'+oid+'/refresh')
    with app.app_context():
        o=db.session.get(PaymentOrder,oid);assert o.payment_state=='refunded'
        assert StripeMockObject.query.filter_by(kind='refund').count()==1


def test_dispute_hold_recovery_and_won_review(paid_app):
    app=paid_app;c,oid,_=pay(app);ended(app,oid);admin_action(app,oid,'approve_completion')
    with app.app_context():
        o=db.session.get(PaymentOrder,oid);ch=stripe_mock.get(o.charge_id);ch['disputed']=True;stripe_mock.put(ch)
        stripe_mock.put({'id':'dp_test','object':'dispute','charge':o.charge_id,'status':'needs_response'})
    assert event(app,'dp_test',kind='charge.dispute.created').status_code==200
    app.test_cli_runner().invoke(args=['payments-worker','--once']);admin_action(app,oid,'transfer')
    with app.app_context():assert not db.session.get(PaymentOrder,oid).transfer_id
    with app.app_context():
        d=stripe_mock.get('dp_test');d['status']='won';stripe_mock.put(d)
    admin_action(app,oid,'clear_review')
    with app.app_context():
        o=db.session.get(PaymentOrder,oid);assert o.payment_state=='paid' and not o.hold_reason and not o.completion_approved_at
    admin_action(app,oid,'approve_completion');admin_action(app,oid,'transfer')
    with app.app_context():assert db.session.get(PaymentOrder,oid).transfer_id


def test_transfer_readiness_available_balance_and_unknown_transfer(paid_app):
    app=paid_app;c,oid,_=pay(app);ended(app,oid);admin_action(app,oid,'approve_completion')
    with app.app_context():
        o=db.session.get(PaymentOrder,oid);charge=stripe_mock.get(o.charge_id);tx=stripe_mock.get(charge['balance_transaction']);tx['status']='pending';stripe_mock.put(tx)
    admin_action(app,oid,'transfer')
    with app.app_context():
        o=db.session.get(PaymentOrder,oid);assert not o.transfer_id
        tx['status']='available';stripe_mock.put(tx)
        stripe.api('POST','transfers',dict(amount=8000,currency='usd',destination=o.destination,source_transaction=o.charge_id,transfer_group='ttbg_'+oid),key='external-transfer')
    admin_action(app,oid,'transfer')
    with app.app_context():assert not db.session.get(PaymentOrder,oid).transfer_id and StripeMockObject.query.filter_by(kind='transfer').count()==1


def test_reconcile_old_checkout_via_verified_object(paid_app):
    app=paid_app;c,oid,sid,_=begin(app)
    with app.app_context():
        o=db.session.get(PaymentOrder,oid);op=PaymentOperation.query.filter_by(owner_key='checkout:'+oid).one();opid=op.id
        o.session_id=None;o.checkout_url='';op.state='manual_review';op.response_id=None;db.session.commit()
    admin=app.test_client();login(admin,'admin')
    data={'reconcile-object_id':sid,'reconcile-password':PW,'reconcile-reason':'Verified original Stripe checkout metadata','reconcile-confirm':'y'}
    assert admin.post('/support/payments/operations/'+opid+'/reconcile',data=data).status_code==302
    with app.app_context():assert db.session.get(PaymentOrder,oid).session_id==sid


def test_money_transport_is_pinned_and_flattened(app,monkeypatch):
    import io
    captured=[]
    class Response(io.BytesIO):
        def __enter__(self):return self
        def __exit__(self,*args):self.close()
    class Opener:
        def open(self,req,timeout):
            captured.append(req)
            return Response(json.dumps({'id':'acct_expected','country':'US','default_currency':'usd'} if req.full_url.endswith('/account') else {'id':'cs_test_123','livemode':False}).encode())
    monkeypatch.setattr(stripe,'build_opener',lambda *a:Opener())
    app.config.update(APP_ENV='staging',STRIPE_MODE='test',STRIPE_SECRET_KEY='sk_test_fake',STRIPE_ACCOUNT_ID='acct_expected')
    with app.app_context():
        stripe.api('POST','checkout/sessions',{'metadata':{'ttbg_order':'order'},'payment_method_types':['card']},key='durable')
        assert captured[-1].get_header('Stripe-version')==stripe.API_VERSION
        assert captured[-1].get_header('Idempotency-key')=='ttbg-v07-durable'
        assert b'metadata%5Bttbg_order%5D=order' in captured[-1].data
        assert captured[-1].full_url=='https://api.stripe.com/v1/checkout/sessions'
        with pytest.raises(ValueError):stripe.api('POST','checkout/sessions',{})
        with pytest.raises(ValueError):stripe.api('GET','https://evil.invalid')
        app.config['APP_ENV']='production'
        with pytest.raises(stripe.StripeError):stripe.writable()
        app.config.update(STRIPE_MODE='live',STRIPE_SECRET_KEY='sk_live_fake',PUBLIC_BASE_URL='https://example.com')
        with pytest.raises(stripe.StripeError):stripe.writable()


def test_all_schema_dialects_compile_and_upgrade_preserves_accounts(app):
    from sqlalchemy.schema import CreateTable,CreateIndex
    from sqlalchemy.dialects import postgresql,mysql
    from app.upgrade import upgrade
    from app.models import User
    with app.app_context():
        before=[(u.id,u.password_hash,u.role) for u in User.query]
        upgrade();upgrade()
        assert [(u.id,u.password_hash,u.role) for u in User.query]==before
        assert len(db.metadata.tables)==44
        for dialect in (postgresql.dialect(),mysql.dialect()):
            for table in db.metadata.sorted_tables:
                assert str(CreateTable(table).compile(dialect=dialect))
                for index in table.indexes:assert str(CreateIndex(index).compile(dialect=dialect))


def test_definitive_refund_rejection_can_be_explicitly_retried(paid_app,monkeypatch):
    app=paid_app;c,oid,_=pay(app);original=stripe.api
    def rejected(method,path,*a,**kw):
        if method=='POST' and path=='refunds':raise stripe.StripeError('stripe_rejected',True)
        return original(method,path,*a,**kw)
    monkeypatch.setattr(stripe,'api',rejected);admin_action(app,oid,'refund')
    with app.app_context():assert db.session.get(PaymentOrder,oid).payment_state=='paid'
    monkeypatch.setattr(stripe,'api',original);result=admin_action(app,oid,'retry_refund')
    with app.app_context():assert db.session.get(PaymentOrder,oid).payment_state=='refunded',result.text


def test_failed_reversal_does_not_undo_refund_and_can_retry(paid_app,monkeypatch):
    app=paid_app;c,oid,_=pay(app);ended(app,oid);admin_action(app,oid,'approve_completion');admin_action(app,oid,'transfer')
    original=stripe.api
    def rejected(method,path,*a,**kw):
        if method=='POST' and path.endswith('/reversals'):raise stripe.StripeError('stripe_rejected',True)
        return original(method,path,*a,**kw)
    monkeypatch.setattr(stripe,'api',rejected);admin_action(app,oid,'refund')
    with app.app_context():
        o=db.session.get(PaymentOrder,oid);assert o.payment_state=='refunded' and o.refunded_cents==10000 and o.reversed_cents==0
    monkeypatch.setattr(stripe,'api',original);result=admin_action(app,oid,'recover_transfer')
    with app.app_context():assert db.session.get(PaymentOrder,oid).reversed_cents==8000,result.text
