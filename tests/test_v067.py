import re
from copy import deepcopy
from html import unescape
from datetime import timedelta
import pytest
from test_workflows import app, login
from test_v06 import mock_app, book
from test_v03 import manager
from app import acuity
from app.models import db, User, Mentor, Service, ServiceScheduling, Booking, PlatformAudit
from app.security import settings
from app.service_import import signer

URL = '/admin/mentors/1/services/import-acuity'

def staff(app, who='admin'):
    c = app.test_client(); login(c, who); return c

def preview(c, type_id='201', url=URL):
    r = c.post(url, data={'operation':'fetch','type_id':type_id})
    assert r.status_code == 200 and 'name="preview"' in r.text, r.text
    return r, unescape(re.search(r'name="preview"[^>]*value="([^"]+)"',r.text).group(1))

def save(c, token, **values):
    return c.post(URL, data=dict(operation='save',preview=token,name='Reviewed session',description='Reviewed description',active='y',confirm='y',**values))

@pytest.fixture
def provider(mock_app, monkeypatch):
    raw = acuity.api_get
    source = dict(id=201,name='Surgical Tech Exam Prep',description='<p>Prepare for your exam.</p><p>Build confidence.</p>',
                  active=True,private=False,type='service',duration=45,price='75.00',calendarIDs=[101])
    def get(path, params=None):
        if path=='appointment-types': return [deepcopy(source)]
        return raw(path,params)
    monkeypatch.setattr(acuity,'api_get',get)
    return mock_app, source

def test_new_import_preview_then_save_and_mapping(provider):
    app, source = provider
    with app.app_context(): db.session.get(Service,1).acuity_type_id=''; db.session.commit()
    c=staff(app)
    assert 'Import from Acuity' in c.get('/admin/mentors/1').text
    assert 'Add manually' in c.get(URL).text
    r, token=preview(c,'000201')
    assert 'Surgical Tech Exam Prep' in r.text and '$75.00' in r.text and '45 minutes' in r.text
    assert 'Prepare for your exam.\nBuild confidence.' in r.text
    with app.app_context(): assert Service.query.count()==1
    assert save(c, token, price='0.01',duration='1',fee_bps='0',mentor_id='999',acuity_type_id='999').status_code==302
    with app.app_context():
        s=Service.query.order_by(Service.id.desc()).first()
        assert (s.name,s.description,s.price_cents,s.duration,s.fee_bps,s.mentor_id)==('Reviewed session','Reviewed description',7500,45,2000,1)
        assert s.acuity_type_id=='201' and s.scheduling.provider=='acuity' and s.scheduling.event_type_id=='201'
        assert s.active and PlatformAudit.query.filter_by(action='Acuity service imported').count()==1
    # Replaying a creation preview cannot become an unreviewed update.
    assert save(c,token).status_code==409
    with app.app_context(): assert Service.query.count()==2
    edit=c.get('/admin/mentors/1/services/2')
    assert 'value="45"' in edit.text
    assert c.post('/admin/mentors/1/services/2',data={'name':'Edited name','description':'Text','price':'75','duration':'45','acuity_type_id':'201'}).status_code==302


def test_existing_update_retains_bookings_fee_and_visibility(mock_app):
    app=mock_app;book(app)
    with app.app_context():
        s=db.session.get(Service,1);s.active=False;s.fee_bps=1500;db.session.commit()
        before=(Booking.query.one().price_cents,Booking.query.one().fee_cents,Booking.query.one().service_name)
    c=staff(app);r,token=preview(c)
    assert 'EXISTING SERVICE FOUND' in r.text and 'Current TTBG values compared with Acuity' in r.text
    assert 'value="Exam prep"' not in r.text
    assert c.post(URL,data={'operation':'save','preview':token,'name':'Imported name','description':'','confirm':'y'}).status_code==302
    with app.app_context():
        s=Service.query.one();assert s.name=='Imported name' and s.fee_bps==1500 and not s.active
        assert (Booking.query.one().price_cents,Booking.query.one().fee_cents,Booking.query.one().service_name)==before
        assert PlatformAudit.query.filter_by(action='Acuity service updated').count()==1


def test_missing_description_remains_editable_and_html_safe(provider):
    app, source=provider;c=staff(app)
    source['description']='<p>Hello &amp; welcome.</p><script>alert(1)</script><img src="https://evil.test/x" onerror="bad()"><style>body{}</style>'
    r,token=preview(c)
    assert 'Hello &amp; welcome.' in r.text and 'evil.test' not in r.text and 'alert(1)' not in r.text
    source['description']=None
    r,token=preview(c);assert save(c,token).status_code==302
    with app.app_context(): assert Service.query.one().description=='Reviewed description'


@pytest.mark.parametrize('change,message',[
    ({'calendarIDs':[999]},'not offered on the mentor'),
    ({'active':False},'inactive or deleted'),
    ({'type':'class'},'Classes and series'),
    ({'price':'-1'},'prices from $0.00'),
    ({'price':'NaN'},'prices from $0.00'),
    ({'price':'10.999'},'two decimal places'),
    ({'duration':45.5},'whole number'),
    ({'duration':1441},'1,440 minutes'),
])
def test_reject_unsupported_types_without_writes(provider,change,message):
    app,source=provider;source.update(change);c=staff(app)
    r=c.post(URL,data={'operation':'fetch','type_id':'201'})
    assert message in r.text and 'name="preview"' not in r.text
    with app.app_context(): assert Service.query.one().name=='Exam prep' and ServiceScheduling.query.count()==0


def test_missing_calendar_wrong_id_and_invalid_input(mock_app):
    app=mock_app;c=staff(app)
    for value in ('0','-1','abc','https://evil.test/1','9223372036854775808'):
        r=c.post(URL,data={'operation':'fetch','type_id':value});assert 'name="preview"' not in r.text
    assert 'not found' in c.post(URL,data={'operation':'fetch','type_id':'999'}).text
    with app.app_context(): db.session.get(Mentor,1).acuity_calendar_id='';db.session.commit()
    assert 'Calendar ID in Review' in c.post(URL,data={'operation':'fetch','type_id':'201'}).text


def test_roles_csrf_and_suspended_mentor(mock_app):
    app=mock_app
    assert app.test_client().get(URL).status_code==302
    for role in ('student','mentor'):
        c=staff(app,role);assert c.get(URL).status_code==403
        assert c.post(URL,data={'operation':'fetch','type_id':'201'}).status_code==403
    manager(app);c=staff(app,'other');r,token=preview(c);assert save(c,token).status_code==302
    app.config['WTF_CSRF_ENABLED']=True
    assert c.post(URL,data={'operation':'fetch','type_id':'201'}).status_code==400
    app.config['WTF_CSRF_ENABLED']=False
    with app.app_context(): db.session.get(Mentor,1).status='suspended';db.session.commit()
    assert c.get(URL).status_code==403


@pytest.mark.parametrize('target',['provider','service','calendar','commission','mapping','new_duplicate'])
def test_stale_previews_cannot_overwrite_changes(provider,target):
    app,source=provider;c=staff(app);r,token=preview(c)
    if target=='provider': source['price']='80.00'
    else:
        with app.app_context():
            s=db.session.get(Service,1)
            if target=='service':s.description='Saved by someone else'
            elif target=='calendar':s.mentor.acuity_calendar_id='999'
            elif target=='commission':settings().fee_bps=2500
            elif target=='mapping':db.session.add(ServiceScheduling(service=s,provider='acuity',event_type_id='202',booking_url=''))
            elif target=='new_duplicate':db.session.add(Service(mentor_id=1,name='Another mapping',price_cents=7500,duration=45,acuity_type_id='201'))
            db.session.commit()
    assert save(c,token).status_code==409
    with app.app_context():assert db.session.get(Service,1).name=='Exam prep'


def test_preview_expiry_tamper_actor_and_mentor_binding(mock_app,monkeypatch):
    app=mock_app;c=staff(app);r,token=preview(c)
    assert save(c,token+'bad').status_code==409
    manager(app);other=staff(app,'other');assert save(other,token).status_code==400
    with app.app_context():
        db.session.add(Mentor(user_id=4,lane='Technology',title='Other',bio='Other',experience='Other',acuity_calendar_id='101'));db.session.commit()
    assert c.post('/admin/mentors/2/services/import-acuity',data={'operation':'save','preview':token}).status_code==400
    import itsdangerous.timed
    original=itsdangerous.timed.time.time
    monkeypatch.setattr(itsdangerous.timed.time,'time',lambda:original()+901)
    assert 'expired' in save(c,token).text


def test_duplicate_checks_modern_mapping_and_multiple_matches(mock_app):
    app=mock_app;c=staff(app)
    with app.app_context():
        s=db.session.get(Service,1);s.acuity_type_id=''
        db.session.add(ServiceScheduling(service=s,provider='acuity',event_type_id='000201',booking_url=''));db.session.commit()
    r,token=preview(c);assert 'EXISTING SERVICE FOUND' in r.text
    with app.app_context():
        db.session.add(Service(mentor_id=1,name='Duplicate legacy',price_cents=10000,duration=60,acuity_type_id='201'));db.session.commit()
    assert 'Multiple services' in c.post(URL,data={'operation':'fetch','type_id':'201'}).text


def test_shared_type_can_be_imported_for_another_mentor(mock_app):
    app=mock_app
    with app.app_context():
        u=db.session.get(User,4);u.role='mentor'
        db.session.add(Mentor(user_id=4,lane='Healthcare',title='Another mentor',bio='Bio',experience='Experience',status='draft',acuity_calendar_id='101'))
        db.session.commit()
    c=staff(app);url='/admin/mentors/2/services/import-acuity';r,token=preview(c,url=url)
    assert 'EXISTING SERVICE FOUND' not in r.text
    assert c.post(url,data={'operation':'save','preview':token,'name':'Another service','description':'Text','confirm':'y'}).status_code==302
    with app.app_context(): assert Service.query.filter_by(acuity_type_id='201').count()==2


def test_confirmation_name_validation_and_private_default(provider):
    app,source=provider;source['private']=True;source['name']='X'*130;source['description']='Y'*1100
    with app.app_context():db.session.get(Service,1).acuity_type_id='';db.session.commit()
    c=staff(app);r,token=preview(c)
    assert 'shortened' in r.text and 'private in Acuity' in r.text
    active=re.search(r'<input[^>]+name="active"[^>]*>',r.text).group(0);assert 'checked' not in active
    for values in ({'name':'Good','confirm':''},{'name':' '*3,'confirm':'y'},{'name':'Z'*121,'confirm':'y'}):
        assert c.post(URL,data=dict(operation='save',preview=token,**values)).status_code==200
    with app.app_context():assert Service.query.count()==1


def test_provider_failure_redaction_and_retry(mock_app,monkeypatch):
    app=mock_app;c=staff(app)
    def failed(*a,**kw):raise acuity.AcuityError('authentication_failed')
    monkeypatch.setattr(acuity,'api_get',failed)
    r=c.post(URL,data={'operation':'fetch','type_id':'201'})
    assert r.status_code==503 and 'rejected the credentials' in r.text and 'Support reference' in r.text
    assert 'local-dummy-key' not in r.text
    with app.app_context():assert Service.query.count()==1 and ServiceScheduling.query.count()==0


def test_external_mapping_replaced_only_after_confirmation(mock_app):
    app=mock_app;c=staff(app)
    with app.app_context():
        db.session.add(ServiceScheduling(service_id=1,provider='calcom',event_type_id='anything',booking_url='https://cal.com/ttbg/example'));db.session.commit()
    r,token=preview(c);assert 'removes its previous hosted booking link' in r.text
    with app.app_context():assert ServiceScheduling.query.one().provider=='calcom'
    assert save(c,token).status_code==302
    with app.app_context():
        s=ServiceScheduling.query.one();assert s.provider=='acuity' and s.event_type_id=='201' and s.booking_url==''


def test_health_version(mock_app):
    assert mock_app.test_client().get('/health').json['version']=='0.7.0'


def test_free_import_booking_and_synchronization(mock_app):
    from test_v06 import webhook
    app=mock_app
    with app.app_context():db.session.get(Service,1).acuity_type_id='202';db.session.commit()
    c=staff(app);r,token=preview(c,'202')
    assert 'FREE' in r.text and '30 minutes' in r.text
    assert save(c,token).status_code==302
    public=app.test_client()
    assert 'FREE' in public.get('/').text and 'FREE' in public.get('/mentor/1').text
    student,_,response=book(app)
    page=student.get(response.location,follow_redirects=True).text
    assert 'FREE' in page and 'no payment is required' in page
    assert 'Payment is arranged separately' not in page
    with app.app_context():
        b=Booking.query.one()
        assert b.price_cents==b.fee_cents==b.earnings_cents==0
        assert b.payment_status=='no_payment_required'
        assert app.jinja_env.filters['money'](0)=='$0.00'
        assert app.jinja_env.filters['service_price'](7500)=='$75.00'
        assert app.jinja_env.filters['service_price'](0)=='FREE'
    assert webhook(app).status_code==204
    with app.app_context():assert Booking.query.one().payment_status=='no_payment_required'
    mentor_client=staff(app,'mentor')
    details=mentor_client.get('/bookings/1').text
    assert 'FREE' in details and '$0.00' in details # money amounts remain numeric


def test_manual_and_mentor_zero_price_supported(mock_app):
    app=mock_app;c=staff(app)
    assert c.post('/admin/mentors/1/services/new',data={'name':'Free consultation','description':'Intro','price':'0','duration':'15'}).status_code==302
    with app.app_context():
        s=Service.query.order_by(Service.id.desc()).first();assert s.price_cents==0 and s.duration==15
    mentor_client=staff(app,'mentor')
    assert mentor_client.post('/mentor/services/1/price',data={'price':'0.00'}).status_code==302
    assert 'FREE' in mentor_client.get('/dashboard').text
    assert 'FREE' in mentor_client.get('/mentor/services/1/price').text
    assert mentor_client.post('/mentor/services/1/price',data={'price':''}).status_code==200


def test_fetch_rate_limit_and_scope_change(mock_app):
    from app.models import AvailabilityRequest
    app=mock_app;c=staff(app);_,token=preview(c)
    app.config['ACUITY_USER_ID']='2'
    assert save(c,token).status_code==400
    app.config['ACUITY_USER_ID']='1'
    with app.app_context():
        db.session.add_all([AvailabilityRequest(user_id=1) for _ in range(20)]);db.session.commit()
    assert c.post(URL,data={'operation':'fetch','type_id':'201'}).status_code==429
