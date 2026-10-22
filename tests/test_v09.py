"""v0.9 occupancy, safe diagnostics, and customer clarity."""
import re
from datetime import datetime,timedelta,timezone
import pytest
from test_workflows import app,login
from test_v06 import mock_app,slot,webhook
from test_v07 import paid_app,begin,pay
from test_v03 import manager,PW
from app.models import db,Service,Booking,AcuityRequest,AcuityMockAppointment,PaymentOrder,PaymentOperation,DiagnosticEvent,DiagnosticProbe,PlatformAudit,SchemaRevision
from app import acuity,scheduling
from app.acuity_mock import TYPES

def free_service(app):
    with app.app_context():
        s=Service(mentor_id=1,name='Free consultation',price_cents=0,duration=30,fee_bps=2000,acuity_type_id='202');db.session.add(s);db.session.commit();return s.id

def quote(c,sid,time):
    page=c.get('/appointments/new/'+str(sid),query_string={'time':time,'timezone':'UTC'})
    assert 'name="quote"' in page.text,page.text
    data={n:re.search(r'name="'+n+r'"[^>]*value="([^"]+)"',page.text).group(1) for n in ('request_id','quote')}
    data.update(first_name='Test',last_name='Student',phone='+12125550123',acknowledge='y',field_401='Exam practice')
    return data

def availability(c,sid,time):return c.get('/availability/'+str(sid),query_string={'month':time[:7],'date':time[:10],'timezone':'UTC'})

def test_free_to_paid_same_time_never_substitutes_booking(paid_app):
    a=paid_app;sid=free_service(a);c=a.test_client();login(c,'student');t=slot(a)
    paid=quote(c,1,t);free=quote(c,sid,t)
    assert c.post('/appointments/new/'+str(sid),data=free).status_code==302
    res=c.post('/appointments/new/1',data=paid)
    assert res.status_code==200 and 'That time is no longer available' in res.text
    with a.app_context():
        assert Booking.query.one().service_id==sid and PaymentOrder.query.count()==0
        e=DiagnosticEvent.query.filter_by(code='booking_conflict').one();assert e.service_id==1 and e.price_cents==10000
    assert c.post('/appointments/new/1',data=free).status_code==400

def test_paid_hold_blocks_free_and_releases_after_verified_expiry(paid_app):
    a=paid_app;sid=free_service(a);c=a.test_client();login(c,'student');t=slot(a);free=quote(c,sid,t)
    c,oid,session,data=begin(a)
    assert 'That time is no longer available' in c.post('/appointments/new/'+str(sid),data=free).text
    with a.app_context():
        assert PaymentOrder.query.one().payment_state=='unpaid' and Booking.query.count()==0
        o=db.session.get(PaymentOrder,oid);o.expires_at=datetime.now()-timedelta(hours=1);db.session.commit()
        assert scheduling.conflicts({'calendarID':'101','appointmentTypeID':'202'},datetime.fromisoformat(t).replace(tzinfo=None),30)
    c.post('/payments/orders/'+oid+'/cancel-session',data={'reason_code':'mentee_request','reason':'No longer needed'})
    q=quote(c,sid,t);assert c.post('/appointments/new/'+str(sid),data=q).status_code==302
    with a.app_context():assert Booking.query.one().service_id==sid

def test_cancelled_slot_returns_despite_stale_local_snapshot(paid_app):
    a=paid_app;sid=free_service(a);c=a.test_client();login(c,'student');t=slot(a)
    c.post('/appointments/new/'+str(sid),data=quote(c,sid,t))
    with a.app_context():
        row=AcuityMockAppointment.query.one();acuity.api_request('PUT','appointments/'+str(row.id)+'/cancel',data={})
    assert '/appointments/new/'+str(sid)+'?' in availability(c,sid,t).text
    assert c.post('/appointments/new/'+str(sid),data=quote(c,sid,t)).status_code==302
    with a.app_context():assert AcuityMockAppointment.query.count()==2

def test_duration_overlap_and_buffers_across_types(mock_app,monkeypatch):
    a=mock_app;t=datetime.fromisoformat(slot(a)).replace(tzinfo=None)
    with a.app_context():
        external={'id':999,'calendarID':101,'appointmentTypeID':202,'datetime':(t+timedelta(minutes=30)).replace(tzinfo=timezone.utc).isoformat(),'duration':'30','canceled':False}
        original=acuity.api_get
        monkeypatch.setattr(acuity,'api_get',lambda path,params=None:[external] if path=='appointments' else original(path,params))
        ids={'calendarID':'101','appointmentTypeID':'201'}
        assert scheduling.conflicts(ids,t,60)
        assert not scheduling.conflicts(ids,t-timedelta(hours=2),60)
        external['datetime']=(t+timedelta(minutes=70)).replace(tzinfo=timezone.utc).isoformat()
        assert not scheduling.conflicts(ids,t,60)
        monkeypatch.setitem(TYPES,'201',dict(TYPES['201'],paddingAfter=15))
        assert scheduling.conflicts(ids,t,60)
        external['canceled']=True;assert not scheduling.conflicts(ids,t,60)

def test_saturated_provider_list_never_offers_slot(mock_app,monkeypatch):
    a=mock_app;c=a.test_client();login(c,'student');t=slot(a);original=acuity.api_get
    monkeypatch.setattr(acuity,'api_get',lambda path,params=None:[{}]*100 if path=='appointments' else original(path,params))
    assert 'name="quote"' not in c.get('/appointments/new/1',query_string={'time':t,'timezone':'UTC'}).text
    assert '/appointments/new/1?' not in availability(c,1,t).text

def test_different_available_time_and_idempotent_retry(paid_app):
    a=paid_app;c,oid,session,data=begin(a)
    assert c.post('/appointments/new/1',data=data).status_code==302
    with a.app_context():
        assert PaymentOrder.query.count()==1 and PaymentOperation.query.filter_by(kind='checkout').count()==1
        start=db.session.get(AcuityRequest,oid).starts_at
    t=(start+timedelta(hours=3)).replace(tzinfo=timezone.utc).isoformat()
    assert c.post('/appointments/new/1',data=quote(c,1,t)).status_code==302
    with a.app_context():assert PaymentOrder.query.count()==2

def test_disabled_checkout_blocks_live_paid_service(mock_app,monkeypatch):
    a=mock_app;c=a.test_client();login(c,'student');t=slot(a);data=quote(c,1,t)
    monkeypatch.setattr(acuity,'configured',lambda:True);monkeypatch.setattr(acuity,'mode',lambda:'live');monkeypatch.setattr('app.appointments.catalog',lambda service:[])
    res=c.get('/appointments/new/1',query_string={'time':t,'timezone':'UTC'})
    assert 'Paid booking is temporarily unavailable' in res.text and 'name="quote"' not in res.text
    c.post('/appointments/new/1',data=data)
    with a.app_context():assert Booking.query.count()==0 and AcuityRequest.query.count()==0

@pytest.mark.parametrize('who',['student','mentor','other'])
def test_diagnostics_admin_only(app,who):
    if who=='other':manager(app)
    c=app.test_client();login(c,who)
    for path in ['/admin/operations','/admin/operations/logs','/admin/operations/investigate','/admin/data']:assert c.get(path).status_code==403,path
    assert c.post('/admin/operations/check').status_code==403

def test_explorer_allowlists_and_limits(app):
    from app.diagnostics import VIEWS
    c=app.test_client();login(c,'admin')
    for table in VIEWS:
        response=c.get('/admin/data',query_string={'table':table});assert response.status_code==200,response.text
        for secret in ['password_hash','token_hash','student@example.com','appointment_payload','scrypt:']:assert secret not in response.text
    for table in ['market_email_identity','market_support_note','market_stripe_mock_object','market_platform_settings']:assert c.get('/admin/data',query_string={'table':table}).status_code==404
    assert c.get('/admin/data?format=csv').status_code==400
    assert c.get('/admin/data?page=21').status_code==400
    assert c.get('/admin/data?q=SELECT+1').status_code==400
    with app.app_context():assert PlatformAudit.query.filter_by(action='Diagnostic access').count()>0

def test_health_reads_only_and_does_not_fake_delivery(paid_app,monkeypatch):
    a=paid_app;c=a.test_client();login(c,'admin');original=acuity.api_request;calls=[]
    def guarded(method,path,*args,**kw):
        assert method=='GET';calls.append(path);return original(method,path,*args,**kw)
    monkeypatch.setattr(acuity,'api_request',guarded)
    res=c.post('/admin/operations/check',follow_redirects=True)
    assert res.status_code==200,res.text
    assert 'Account verified' in res.text and 'Not observed' in res.text
    with a.app_context():
        assert DiagnosticProbe.query.filter_by(name='acuity_delivery').first() is None
        assert PaymentOrder.query.count()==0 and AcuityRequest.query.count()==0
    assert set(calls)=={'me','webhooks'}

def test_investigation_saved_service_and_history(paid_app):
    a=paid_app;c,oid,session=pay(a);admin=a.test_client();login(admin,'admin')
    res=admin.get('/admin/operations/investigate',query_string={'q':oid})
    assert res.status_code==200 and 'Exam prep' in res.text and 'checkout created' in res.text,res.text
    assert 'Exam practice' not in res.text and 'student@example.com' not in res.text

def test_render_logs_withhold_sensitive_text_and_bound_requests(app,monkeypatch):
    from app import render_logs
    app.config.update(RENDER_OWNER_ID='tea_test',RENDER_WEB_SERVICE_ID='srv-web',RENDER_API_KEY='super-secret')
    c=app.test_client();login(c,'admin');seen=[]
    def fake(params):
        seen.append(params)
        return {'logs':[{'timestamp':'2026-10-22T12:00:00Z','message':'Support reference ABCDEF0123456789; Authorization: Bearer secret; student@example.com private intake','labels':[{'name':'level','value':'error'}]}],'hasMore':False}
    monkeypatch.setattr(render_logs,'fetch',fake)
    res=c.get('/admin/operations/logs')
    assert res.status_code==200 and 'ABCDEF0123456789' in res.text
    for value in ['super-secret','student@example.com','Bearer secret','private intake']:assert value not in res.text
    assert seen[0]['limit']==50 and seen[0]['resource']=='srv-web'
    assert c.get('/admin/operations/logs?minutes=99999').status_code==400
    assert c.get('/admin/operations/logs?service=attacker').status_code==400
    def unavailable(params):raise render_logs.LogUnavailable('Provider temporarily unavailable')
    monkeypatch.setattr(render_logs,'fetch',unavailable)
    assert 'Provider temporarily unavailable' in c.get('/admin/operations/logs').text

def test_csrf_and_password_controls_loaded(app):
    c=app.test_client();login(c,'admin');assert '/static/js/passwords.js' in c.get('/admin/operations').text
    app.config['WTF_CSRF_ENABLED']=True;assert c.post('/admin/operations/check').status_code==400

def test_upgrade_preserves_payment_history(paid_app):
    a=paid_app;c,oid,_=pay(a)
    from app.upgrade import upgrade
    with a.app_context():
        before=(db.session.get(PaymentOrder,oid).gross_cents,Booking.query.one().service_name)
        upgrade();upgrade();assert db.session.get(SchemaRevision,'v0.9-stability-diagnostics')
        assert before==(db.session.get(PaymentOrder,oid).gross_cents,Booking.query.one().service_name)

def test_real_concurrent_requests_one_winner(mock_app,tmp_path):
    """Two HTTP clients, separate SQLite connections, one durable slot claim."""
    import sqlite3
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from app import create_app
    sid=free_service(mock_app);path=tmp_path/'marketplace-mock.db'
    with mock_app.app_context():
        raw=db.engine.raw_connection();destination=sqlite3.connect(path)
        raw.driver_connection.backup(destination);destination.close();raw.close()
    config=dict(mock_app.config);config['SQLALCHEMY_DATABASE_URI']='sqlite:///'+str(path)
    concurrent=create_app(config)
    one=concurrent.test_client();two=concurrent.test_client();login(one,'student');login(two,'other')
    t=slot(concurrent);first=quote(one,sid,t);second=quote(two,sid,t);barrier=Barrier(2)
    def submit(client,data):
        barrier.wait(timeout=5)
        return client.post('/appointments/new/'+str(sid),data=data)
    with ThreadPoolExecutor(max_workers=2) as pool:
        a=pool.submit(submit,one,first);b=pool.submit(submit,two,second)
        responses=[a.result(timeout=20),b.result(timeout=20)]
    assert sorted(r.status_code for r in responses)==[200,302]
    assert any('That time is no longer available' in r.text for r in responses)
    with concurrent.app_context():assert AcuityRequest.query.count()==1 and AcuityMockAppointment.query.count()==1


def test_pending_different_start_blocks_full_duration(paid_app):
    a=paid_app;c,oid,_,_=begin(a)
    with a.app_context():
        o=db.session.get(PaymentOrder,oid);start=o.request.starts_at
        ids={'calendarID':'101','appointmentTypeID':'202'}
        assert scheduling.conflicts(ids,start+timedelta(minutes=30),30)
        assert not scheduling.conflicts(ids,start+timedelta(minutes=60),30)


def test_rescheduled_slot_uses_current_provider_time(mock_app,monkeypatch):
    a=mock_app;t=datetime.fromisoformat(slot(a)).replace(tzinfo=None)
    with a.app_context():
        original=acuity.api_get
        moved={'id':1,'calendarID':101,'appointmentTypeID':202,'datetime':(t+timedelta(hours=3)).replace(tzinfo=timezone.utc).isoformat(),'duration':30,'canceled':False}
        monkeypatch.setattr(acuity,'api_get',lambda path,params=None:[moved] if path=='appointments' else original(path,params))
        ids={'calendarID':'101','appointmentTypeID':'201'}
        assert not scheduling.conflicts(ids,t,60)
        assert scheduling.conflicts(ids,t+timedelta(hours=3),60)


def test_calendar_hides_paid_hold_from_actual_clickable_links(paid_app):
    from urllib.parse import urlsplit,parse_qs
    from html import unescape
    a=paid_app;c,oid,_,_=begin(a)
    with a.app_context():t=db.session.get(PaymentOrder,oid).request.starts_at.replace(tzinfo=timezone.utc).isoformat()
    html=availability(c,1,t).text
    urls=[unescape(url) for url in re.findall(r'href="([^"]+)"',html) if '/appointments/new/1?' in url]
    assert urls  # Other free times remain clickable.
    for url in urls:assert datetime.fromisoformat(parse_qs(urlsplit(url).query)['time'][0])!=datetime.fromisoformat(t)


def test_failed_provider_read_hides_all_time_links(mock_app,monkeypatch):
    a=mock_app;c=a.test_client();login(c,'student');t=slot(a);original=acuity.api_get
    def fail(path,params=None):
        if path=='appointments':raise acuity.AcuityError('connection_failed')
        return original(path,params)
    monkeypatch.setattr(acuity,'api_get',fail)
    assert '/appointments/new/1?' not in availability(c,1,t).text


def test_connect_error_is_setup_specific_and_has_reference(paid_app,monkeypatch):
    from app import stripe_api
    a=paid_app;c=a.test_client();login(c,'mentor')
    def fail(*a,**kw):raise stripe_api.StripeError('stripe_platform_profile_incomplete')
    monkeypatch.setattr(stripe_api,'api',fail)
    page=c.get('/payments/connect/return',follow_redirects=True)
    assert 'account setup' in page.text and 'before paying again' not in page.text
    with a.app_context():assert DiagnosticEvent.query.filter_by(component='stripe_connect',code='stripe_platform_profile_incomplete').one()

def test_mysql_diagnostic_query_uses_vitess_timeout(app):
    from types import SimpleNamespace
    from sqlalchemy.dialects import mysql
    from app.diagnostics import read_rows
    statements=[]
    class Connection:
        dialect=SimpleNamespace(name='mysql')
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def rollback(self):pass
        def execute(self,query):
            statements.append(str(query.compile(dialect=mysql.dialect())))
            return SimpleNamespace(mappings=lambda:[])
    class Engine:
        def connect(self):return Connection()
    app.config['DIAGNOSTICS_DATABASE_URL']='mysql+pymysql://readonly@localhost/test'
    app.extensions['diagnostics_engine']=Engine()
    with app.app_context():assert read_rows(db.select(Service.id).limit(26))==[]
    assert statements[0]=='START TRANSACTION READ ONLY'
    assert 'QUERY_TIMEOUT_MS=2000' in statements[1] and 'MAX_EXECUTION_TIME(2000)' in statements[1]
    assert 'LIMIT' in statements[1] and '*' not in statements[1].replace('/*vt+ QUERY_TIMEOUT_MS=2000 */ /*+ MAX_EXECUTION_TIME(2000) */','')
