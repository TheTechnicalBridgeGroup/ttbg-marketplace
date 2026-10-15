import base64
import hashlib
import hmac
import io
import json
import re
from datetime import datetime,timedelta,timezone
from urllib.parse import urlencode
from urllib.error import HTTPError
import pytest
from test_workflows import app,login
from test_v03 import manager,PW
from test_v05 import delete
from app import create_app
from app.models import (db,User,Service,Booking,AcuityRequest,AcuityAppointment,AcuitySyncJob,AcuityMockAppointment,AcuityMockConfig)
from app.security import settings
from app import acuity
from app.acuity_mock import times,config as mock_config

@pytest.fixture
def mock_app(app,monkeypatch):
    app.config.update(APP_ENV='local',ACUITY_MODE='mock',ACUITY_USER_ID='1',ACUITY_API_KEY='local-dummy-key',ACUITY_WEBHOOK_SECRET='')
    with app.app_context():
        cfg=settings();cfg.scheduling_provider='acuity';cfg.booking_mode='acuity_confirmed'
        s=db.session.get(Service,1);s.mentor.acuity_calendar_id='101';s.acuity_type_id='201';mock_config();db.session.commit()
    def forbidden(*a,**kw):raise AssertionError('Mock mode must never make a network request')
    monkeypatch.setattr('app.acuity.build_opener',forbidden)
    return app

def slot(app):
    with app.app_context():
        day=(datetime.now(timezone.utc)+timedelta(days=2)).date()
        for i in range(7):
            options=times(day+timedelta(days=i),'UTC')
            if options:return options[0]['time']
    raise AssertionError('No local slot')

def form(c,app,time_value=None):
    r=c.get('/appointments/new/1',query_string={'time':time_value or slot(app),'timezone':'UTC'})
    assert r.status_code==200 and 'Confirm my appointment' in r.text,r.text
    data={name:re.search(r'name="'+name+r'"[^>]*value="([^"]+)"',r.text).group(1) for name in ('request_id','quote')}
    data.update(first_name='Test',last_name='Student',phone='+12125550123',acknowledge='y',field_401='Exam practice')
    return data

def book(app,c=None):
    c=c or app.test_client();login(c,'student');data=form(c,app);r=c.post('/appointments/new/1',data=data)
    assert r.status_code==302,r.text
    return c,data,r

def webhook(app,pid=1,action='changed',valid=True):
    raw=urlencode({'action':action,'id':pid,'calendarID':101,'appointmentTypeID':201}).encode()
    sign=base64.b64encode(hmac.new(app.config['ACUITY_API_KEY'].encode(),raw,hashlib.sha256).digest()).decode()
    return app.test_client().post('/webhooks/acuity',data=raw,content_type='application/x-www-form-urlencoded',headers={'X-Acuity-Signature':sign if valid else 'forged'})

def test_confirmed_creation_saved_snapshot_and_repeat_submit(mock_app):
    app=mock_app;c,data,r=book(app)
    page=c.get(r.location,follow_redirects=True);assert 'Your time is confirmed' in page.text and 'Local practice mode' in page.text
    assert 'No payment was collected' in page.text
    with app.app_context():
        b=Booking.query.one();a=AcuityAppointment.query.one();req=AcuityRequest.query.one()
        assert a.booking_id==b.id and a.request_id==req.id and a.sync_state=='synced'
        assert req.state=='confirmed' and b.status=='confirmed' and b.payment_status=='payment_due'
        assert (b.price_cents,b.fee_cents,b.earnings_cents)==(10000,2000,8000)
        assert a.provider_id=='1' and a.scope=='mock:1' and a.calendar_id=='101' and a.type_id=='201'
    assert c.post('/appointments/new/1',data=data).status_code==302
    with app.app_context():assert Booking.query.count()==1 and AcuityMockAppointment.query.count()==1
    mentor=app.test_client();login(mentor,'mentor');assert 'Exam prep' in mentor.get('/dashboard').text
    assert 'Acuity reference #1' in mentor.get('/bookings/1').text
    other=app.test_client();login(other,'other');assert other.get('/bookings/1').status_code==403
    assert other.get(r.location).status_code==403


def test_availability_direct_mode_and_server_owned_fields(mock_app):
    c=mock_app.test_client();login(c,'student');time_value=slot(mock_app)
    r=c.get('/availability/1',query_string={'month':time_value[:7],'date':time_value[:10],'timezone':'UTC'})
    assert '/appointments/new/1?' in r.text
    data=form(c,mock_app,time_value);data.update(email='attacker@example.com',calendarID='999',appointmentTypeID='999',price_cents='1',admin='true')
    assert c.post('/appointments/new/1',data=data).status_code==302
    with mock_app.app_context():
        payload=AcuityMockAppointment.query.one().payload
        assert payload['email']=='student@example.com' and payload['calendarID']==101 and payload['appointmentTypeID']==201
        assert Booking.query.one().price_cents==10000


def test_quote_tamper_stale_price_missing_intake_and_csrf(mock_app):
    c=mock_app.test_client();login(c,'student');data=form(c,mock_app)
    assert c.post('/appointments/new/1',data=dict(data,quote=data['quote']+'x')).status_code==400
    assert c.post('/appointments/new/1',data=dict(data,field_401='')).status_code==200
    with mock_app.app_context():assert AcuityMockAppointment.query.count()==0 and AcuityRequest.query.count()==0
    with mock_app.app_context():db.session.get(Service,1).price_cents=15000;db.session.commit()
    assert 'Booking details changed' in c.post('/appointments/new/1',data=data).text
    mock_app.config['WTF_CSRF_ENABLED']=True
    assert c.post('/appointments/new/1',data=data).status_code==400


def test_stale_availability_and_role_restrictions(mock_app):
    c=mock_app.test_client();login(c,'student');data=form(c,mock_app)
    with mock_app.app_context():mock_config().scenario='unavailable';db.session.commit()
    r=c.post('/appointments/new/1',data=data);assert r.status_code==302
    assert 'wasn’t created' in c.get(r.location).text
    with mock_app.app_context():assert AcuityRequest.query.one().state=='rejected' and AcuityMockAppointment.query.count()==0
    for who in ('admin','mentor'):
        other=mock_app.test_client();login(other,who)
        assert other.post('/appointments/new/1',data=data).status_code==403
    with mock_app.app_context():settings().booking_mode='contact';db.session.commit()
    assert c.get('/appointments/new/1').status_code==404


def test_uncertain_creation_does_not_retry_and_staff_reconciles(mock_app):
    app=mock_app
    with app.app_context():mock_config().scenario='timeout_after_create';db.session.commit()
    c,data,r=book(app)
    assert 'Checking your confirmation' in c.get(r.location).text
    with app.app_context():
        assert AcuityMockAppointment.query.count()==1 and Booking.query.count()==0
        req=AcuityRequest.query.one();rid=req.id;assert req.state=='uncertain'
    c.post('/appointments/new/1',data=data)
    with app.app_context():assert AcuityMockAppointment.query.count()==1
    assert 'Awaiting confirmation' in c.get('/dashboard').text
    staff=app.test_client();login(staff,'admin')
    assert '#1' in staff.post('/support/appointment-requests/'+rid,data={'operation':'search'}).text
    r=staff.post('/support/appointment-requests/'+rid,data={'operation':'link','provider_id':'1','password':PW,'reason':'Confirmed exact appointment in Acuity'})
    assert r.status_code==302,r.text
    with app.app_context():assert Booking.query.count()==1 and AcuityRequest.query.one().state=='confirmed'
    assert 'Your time is confirmed' in c.get('/appointments/requests/'+rid,follow_redirects=True).text


def test_signed_webhooks_reschedule_cancel_paid_and_replay(mock_app):
    app=mock_app;c,_,_=book(app)
    with app.app_context():
        row=AcuityMockAppointment.query.one();data=dict(row.payload);data['datetime']=slot(app);data['paid']='yes';row.payload=data;db.session.commit();newtime=data['datetime']
    assert webhook(app,valid=False).status_code==403
    with app.app_context():assert Booking.query.one().payment_status=='payment_due'
    assert webhook(app,action='rescheduled').status_code==204
    assert webhook(app,action='scheduled').status_code==204 # old action cannot undo current provider state
    with app.app_context():
        b=Booking.query.one();assert b.start==datetime.fromisoformat(newtime).replace(tzinfo=None)
        assert b.payment_status=='acuity_reported_paid' and AcuityAppointment.query.count()==1
        row=AcuityMockAppointment.query.one();data=dict(row.payload);data['canceled']=True;row.payload=data;db.session.commit()
    assert webhook(app,action='canceled').status_code==204
    assert 'Appointment cancelled' in c.get('/bookings/1').text
    with app.app_context():assert Booking.query.one().status=='cancelled' and not AcuityRequest.query.one().dedupe_key


def test_sync_failure_saved_retry_and_cli_recovery(mock_app):
    app=mock_app;book(app)
    with app.app_context():mock_config().scenario='sync_failure';db.session.commit()
    assert webhook(app).status_code==500
    with app.app_context():
        assert AcuitySyncJob.query.one().pending and AcuityAppointment.query.one().sync_state=='sync_failed'
        mock_config().scenario='normal';db.session.commit()
    result=app.test_cli_runner().invoke(args=['sync-acuity']);assert result.exit_code==0,result.output
    with app.app_context():assert not AcuitySyncJob.query.one().pending and AcuityAppointment.query.one().sync_state=='synced'


def test_webhook_during_maintenance_csrf_and_disabled_cookie(mock_app):
    app=mock_app;book(app);app.config['WTF_CSRF_ENABLED']=True
    with app.app_context():settings().maintenance_mode=True;db.session.commit()
    assert webhook(app).status_code==204
    assert app.test_client().post('/webhooks/acuity',data='x').status_code==403


def test_external_appointment_stays_private_until_staff_links(mock_app):
    app=mock_app
    with app.app_context():
        stamp=slot(app)
        acuity.api_request('POST','appointments',data={'calendarID':101,'appointmentTypeID':201,'datetime':stamp,'timezone':'UTC','firstName':'External','lastName':'Student','email':'student@example.com','fields':[{'id':401,'value':'Prep'}]})
    assert webhook(app).status_code==204
    with app.app_context():assert AcuityAppointment.query.one().sync_state=='unlinked' and Booking.query.count()==0
    student=app.test_client();login(student,'student');assert student.get('/support/appointments/1').status_code==403
    manager(app);staff=app.test_client();login(staff,'other')
    assert staff.post('/support/appointments/1',data={'email':'student@example.com','service_id':'1','password':PW,'reason':'Verified student identity with owner'}).status_code==302
    with app.app_context():assert Booking.query.one().student_id==3
    assert 'Your time is confirmed' in student.get('/bookings/1').text


def test_provider_identity_change_is_reviewed_not_reassigned(mock_app):
    app=mock_app;book(app)
    with app.app_context():
        row=AcuityMockAppointment.query.one();data=dict(row.payload);data['email']='other@example.com';data['location']='PRIVATE NEW LOCATION';row.payload=data;db.session.commit()
    assert webhook(app).status_code==204
    with app.app_context():assert Booking.query.one().student_id==3 and AcuityAppointment.query.one().sync_state=='needs_review'
    student=app.test_client();login(student,'student');assert 'PRIVATE NEW LOCATION' not in student.get('/bookings/1').text


def test_deletion_keeps_link_and_does_not_resurrect_provider_identity(mock_app):
    app=mock_app;book(app);c=app.test_client();login(c,'admin')
    assert delete(c,3,'student@example.com').status_code==302
    with app.app_context():
        assert db.session.get(User,3) is None
        assert AcuityAppointment.query.one().identity_removed and not AcuityAppointment.query.one().email
        assert AcuityRequest.query.one().user_id is None and not AcuityRequest.query.one().email
    assert webhook(app).status_code==204
    with app.app_context():assert not AcuityAppointment.query.one().client_name and Booking.query.one().student.role=='archive'
    assert delete(c,2,'mentor@example.com').status_code==302
    assert webhook(app).status_code==204
    with app.app_context():assert Booking.query.one().mentor.user.role=='archive'


def test_mapping_checks_and_webhook_setup_idempotency(mock_app):
    c=mock_app.test_client();login(c,'admin')
    r=c.post('/support/acuity-mappings',data={'service_id':'1'});assert 'Verified ✓' in r.text
    assert '101' in r.text and '201' in r.text
    assert c.post('/support/appointments/enable-webhook').status_code==302
    assert c.post('/support/appointments/enable-webhook').status_code==302
    with mock_app.app_context():assert len(acuity.api_get('webhooks'))==1
    with mock_app.app_context():db.session.get(Service,1).acuity_type_id='999';db.session.commit()
    assert 'type not found' in c.post('/support/acuity-mappings',data={'service_id':'1'}).text


def test_mock_guard_and_dummy_live_key_rejection(monkeypatch,tmp_path):
    config={'TESTING':True,'SECRET_KEY':'x'*40,'APP_ENV':'local','ACUITY_MODE':'mock','PUBLIC_BASE_URL':'http://127.0.0.1:5000','SQLALCHEMY_DATABASE_URI':'sqlite:///'+str(tmp_path/'marketplace-mock.db')}
    for change in ({'APP_ENV':'production'},{'PUBLIC_BASE_URL':'https://market.example.com'},{'SQLALCHEMY_DATABASE_URI':'sqlite:///marketplace.db'}):
        with pytest.raises(RuntimeError):create_app(dict(config,**change))
    monkeypatch.setenv('RENDER','true')
    with pytest.raises(RuntimeError):create_app(config)
    monkeypatch.delenv('RENDER')
    local=create_app(config)
    assert local.test_client().get('/health',environ_overrides={'REMOTE_ADDR':'203.0.113.2'}).status_code==403
    with pytest.raises(RuntimeError):create_app(dict(config,ACUITY_MODE='live'))
    live=create_app(dict(config,ACUITY_MODE='live',SQLALCHEMY_DATABASE_URI='sqlite://',ACUITY_USER_ID='1',ACUITY_API_KEY='local-dummy-key'))
    with live.app_context():assert not acuity.configured()


def test_local_setup_cli_and_signed_change(tmp_path):
    local=create_app({'TESTING':True,'SECRET_KEY':'x'*40,'APP_ENV':'local','ACUITY_MODE':'mock','PUBLIC_BASE_URL':'http://localhost:5000','SQLALCHEMY_DATABASE_URI':'sqlite:///'+str(tmp_path/'marketplace-mock.db'),'ACUITY_USER_ID':'1','ACUITY_API_KEY':'local-dummy-key','WTF_CSRF_ENABLED':False})
    runner=local.test_cli_runner();result=runner.invoke(args=['setup-acuity-local','--password',PW]);assert result.exit_code==0,result.output
    c=local.test_client();r=c.post('/login',data={'email':'local.student@example.com','password':PW});assert r.status_code==302
    data=form(c,local);assert c.post('/appointments/new/1',data=data).status_code==302
    result=runner.invoke(args=['acuity-mock-change','--id','1','--action','cancel']);assert result.exit_code==0,result.output
    with local.app_context():assert Booking.query.one().status=='cancelled'
    result=runner.invoke(args=['setup-acuity-local','--password',PW]);assert result.exit_code!=0 and 'already exist' in result.output


def test_live_post_transport_does_not_bypass_validation(app,monkeypatch):
    app.config.update(ACUITY_MODE='live',ACUITY_USER_ID='123',ACUITY_API_KEY='real-private-key')
    captured={}
    class Response:
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def read(self,n):return b'{"id":123}'
    class Opener:
        def open(self,req,timeout):captured['request']=req;assert timeout==10;return Response()
    monkeypatch.setattr('app.acuity.build_opener',lambda *a:Opener())
    with app.app_context():acuity.api_request('POST','appointments',data={'calendarID':101,'appointmentTypeID':201})
    r=captured['request'];assert r.full_url=='https://acuityscheduling.com/api/v1/appointments'
    assert r.method=='POST' and json.loads(r.data)['calendarID']==101
    assert 'real-private-key' not in r.full_url and base64.b64decode(r.get_header('Authorization')[6:])==b'123:real-private-key'


@pytest.mark.parametrize('status,definitive',[(400,True),(401,True),(429,False),(500,False)])
def test_live_post_error_classification_sanitized(app,monkeypatch,status,definitive):
    app.config.update(ACUITY_MODE='live',ACUITY_USER_ID='123',ACUITY_API_KEY='private-key')
    class Broken:
        def open(self,*a,**kw):raise HTTPError('https://acuityscheduling.com',status,'private error',{},io.BytesIO(b'{"error":"required_field","message":"PRIVATE VALUE"}'))
    monkeypatch.setattr('app.acuity.build_opener',lambda *a:Broken())
    with app.app_context(),pytest.raises(acuity.AcuityError) as result:acuity.api_request('POST','appointments',data={})
    assert result.value.definitive is definitive and 'PRIVATE' not in result.value.code


def test_public_profile_enters_confirmed_booking_flow(mock_app):
    c=mock_app.test_client()
    assert 'href="/availability/1"' in c.get('/mentor/1').text
    assert c.get('/availability/1').status_code==302
    login(c,'student');mock_app.config['TEST_RESERVATIONS_ENABLED']=False
    assert c.get('/book/1').location=='/availability/1'


def test_database_failure_after_provider_success_retains_request(mock_app,monkeypatch):
    from sqlalchemy.exc import SQLAlchemyError
    def fail(*args):raise SQLAlchemyError('simulated local persistence failure')
    monkeypatch.setattr('app.appointments.save_snapshot',fail)
    c,data,r=book(mock_app)
    with mock_app.app_context():
        assert AcuityMockAppointment.query.count()==1 and AcuityRequest.query.one().state=='creating'
        assert Booking.query.count()==0
    c.post('/appointments/new/1',data=data)
    with mock_app.app_context():assert AcuityMockAppointment.query.count()==1
    assert 'Checking your confirmation' in c.get(r.location).text


def test_distinct_forms_cannot_create_duplicate_and_expired_quote(mock_app):
    from app.appointments import serializer
    c=mock_app.test_client();login(c,'student');time_value=slot(mock_app)
    first=form(c,mock_app,time_value);second=form(c,mock_app,time_value)
    assert c.post('/appointments/new/1',data=first).status_code==302
    c.post('/appointments/new/1',data=second)
    with mock_app.app_context():assert AcuityMockAppointment.query.count()==1 and Booking.query.count()==1


def test_uncertain_request_staff_release_requires_password_time_and_confirmation(mock_app):
    with mock_app.app_context():mock_config().scenario='timeout_after_create';db.session.commit()
    _,_,_=book(mock_app)
    with mock_app.app_context():rid=AcuityRequest.query.one().id
    c=mock_app.test_client();login(c,'admin')
    data={'operation':'release','release-password':PW,'release-reason':'Checked provider directly; no appointment exists','release-checked':'y'}
    assert c.post('/support/appointment-requests/'+rid,data=data).status_code==409
    with mock_app.app_context():req=db.session.get(AcuityRequest,rid);req.updated_at=datetime.now(timezone.utc).replace(tzinfo=None)-timedelta(minutes=2);db.session.commit()
    assert c.post('/support/appointment-requests/'+rid,data=dict(data,**{'release-password':'wrong'})).status_code==403
    # Releasing is a deliberate staff statement, never an automatic timeout retry.
    assert c.post('/support/appointment-requests/'+rid,data=data).status_code==200
    with mock_app.app_context():assert AcuityRequest.query.one().state=='rejected' and not AcuityRequest.query.one().dedupe_key


def test_booking_id_links_survive_duplicate_webhook_before_confirmation(mock_app,monkeypatch):
    from app.appointments import save_snapshot
    original=acuity.api_request
    def webhook_first(method,path,**kwargs):
        result=original(method,path,**kwargs)
        if method=='POST' and path=='appointments':
            save_snapshot(result);db.session.commit()
        return result
    monkeypatch.setattr('app.acuity.api_request',webhook_first)
    book(mock_app)
    with mock_app.app_context():assert Booking.query.count()==1 and AcuityAppointment.query.count()==1 and AcuityRequest.query.one().state=='confirmed'


def test_normalizer_rejects_naive_datetime_and_distinguishes_dst_offsets():
    from app.appointments import stamp
    with pytest.raises(acuity.AcuityError):stamp('2026-11-01T01:30:00')
    assert stamp('2026-11-01T01:30:00-05:00')-stamp('2026-11-01T01:30:00-04:00')==timedelta(hours=1)


@pytest.mark.parametrize('change',[{'price':'150.00'},{'duration':'90'}])
def test_provider_price_or_duration_change_preserves_financial_snapshot(mock_app,change):
    book(mock_app)
    with mock_app.app_context():
        item=AcuityMockAppointment.query.one();payload=dict(item.payload);payload.update(change);item.payload=payload;db.session.commit()
    assert webhook(mock_app).status_code==204
    with mock_app.app_context():
        assert AcuityAppointment.query.one().sync_state=='needs_review'
        b=Booking.query.one();assert b.status=='sync_review' and (b.price_cents,b.fee_cents,b.earnings_cents)==(10000,2000,8000)
