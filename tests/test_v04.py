import re
from datetime import datetime,timedelta,timezone
from urllib.parse import urlsplit
import pytest
from sqlalchemy import select
from test_workflows import app, login, payload
from test_v03 import manager, PW
from app.models import (db,User,SupportNote,SupportIncident,PlatformAudit,AccountAccess,Service,PlatformSettings,SchemaRevision,now)
from app.security import settings

SUPPORT_PAGES=['/support','/support/accounts/3','/support/accounts/3/recover','/support/bookings','/support/incidents','/support/integrations']

@pytest.mark.parametrize('name',['student','mentor'])
def test_support_closed_to_nonstaff(app,name):
    c=app.test_client();login(c,name)
    for url in SUPPORT_PAGES:assert c.get(url).status_code==403,url
    assert 'Support Center' not in c.get('/').text
    for url in ['/support/accounts/3','/support/accounts/3/recover','/support/credentials/acuity/reveal','/support/incidents/1','/support/integrations/acuity/check']:
        assert c.post(url,data={'password':PW,'body':'Private note','resolution':'Resolved issue'}).status_code==403,url
    anon=app.test_client()
    for url in SUPPORT_PAGES:assert anon.get(url).status_code==302

@pytest.mark.parametrize('name',['admin','other'])
def test_support_pages_search_and_notes(app,name):
    manager(app);c=app.test_client();login(c,name)
    for url in SUPPORT_PAGES:assert c.get(url).status_code==200,url
    assert 'Student' in c.get('/support?q=3').text
    assert 'Mentor' in c.get('/support?q=mentor%40example.com').text
    assert 'No matching accounts' in c.get('/support?q=%25').text
    assert c.post('/support/accounts/3',data={'body':'<script>alert(1)</script> Helped with login.'}).status_code==302
    r=c.get('/support/accounts/3');assert '&lt;script&gt;' in r.text and '<script>alert(1)</script>' not in r.text
    assert r.headers['Cache-Control'].startswith('no-store')
    with app.app_context():
        assert SupportNote.query.one().author_id==(1 if name=='admin' else 4)
        assert PlatformAudit.query.filter_by(action='Support note added').one().target=='user:3'
    c.post('/support/accounts/3',data={'body':' ' * 10})
    with app.app_context():assert SupportNote.query.count()==1


def test_manager_recovery_boundaries_and_reset(app):
    manager(app);c=app.test_client();login(c,'other')
    for uid in (1,4):
        assert c.get(f'/support/accounts/{uid}/recover').status_code==403
        assert c.post(f'/support/accounts/{uid}/recover',data={'action':'reset','password':PW,'reason':'User requested reset'}).status_code==403
    before=app.test_client();login(before,'student')
    r=c.post('/support/accounts/3/recover',data={'action':'reset','password':'wrong','reason':'User requested reset'})
    assert 'password is incorrect' in r.text
    r=c.post('/support/accounts/3/recover',data={'action':'reset','password':PW,'reason':'User requested reset'})
    assert 'link created' in r.text and '/support/accounts/3' in r.text
    assert before.get('/dashboard').status_code==302
    link=urlsplit(re.search(r'<textarea id="account-link"[^>]*>([^<]+)',r.text).group(1)).path
    user=app.test_client();assert user.post(link,data={'password':'a-new-valid-password','confirm':'a-new-valid-password'}).status_code==302
    assert user.get(link).status_code==400
    assert c.post('/support/accounts/3/recover',data={'action':'revoke','password':PW,'reason':'End stale sessions'}).status_code==302
    assert user.get('/dashboard').status_code==302


def test_api_keys_masked_reauth_and_no_generic_secret_access(app):
    manager(app);app.config.update(ACUITY_API_KEY='private-acuity-value',STRIPE_SECRET_KEY='private-stripe-value')
    c=app.test_client();login(c,'admin')
    r=c.get('/support/integrations')
    assert 'credential-dialog' in r.text
    assert 'private-acuity-value' not in r.text and 'private-stripe-value' not in r.text
    assert c.get('/support/credentials/acuity/reveal').status_code==405
    assert c.post('/support/credentials/SECRET_KEY/reveal',data={'password':PW}).status_code==404
    assert c.post('/support/credentials/acuity/reveal',data={'password':'wrong'}).status_code==403
    r=c.post('/support/credentials/acuity/reveal',data={'password':PW})
    assert r.json=={'value':'private-acuity-value'} and 'no-store' in r.headers['Cache-Control']
    assert c.post('/support/credentials/stripe/reveal',data={'password':''}).status_code==400
    assert 'private-acuity-value' not in c.get('/admin/audit').text
    for table in db.metadata.tables:
        r=c.get('/admin/data',query_string={'table':table,'format':'csv'})
        assert 'private-acuity-value' not in r.text and PW not in r.text and 'scrypt:' not in r.text
    c.post('/logout');login(c,'other')
    assert 'credential-dialog' not in c.get('/support/integrations').text
    assert c.post('/support/credentials/acuity/reveal',data={'password':PW}).status_code==403


def test_reveal_throttle_csrf_and_expired_session(app):
    c=app.test_client();login(c,'admin');app.config['ACUITY_API_KEY']='private-acuity-value'
    for _ in range(5):assert c.post('/support/credentials/acuity/reveal',data={'password':'wrong'}).status_code==403
    assert c.post('/support/credentials/acuity/reveal',data={'password':PW}).status_code==429
    c.post('/logout');login(c,'admin')
    assert c.post('/support/credentials/acuity/reveal',data={'password':PW}).status_code==429
    app.config['WTF_CSRF_ENABLED']=True
    assert c.post('/support/credentials/acuity/reveal',data={'password':PW}).status_code==400
    assert c.post('/support/accounts/3',data={'body':'Should be rejected'}).status_code==400
    with app.app_context():
        db.session.get(User,1).access.enabled=False;db.session.commit()
    assert c.get('/support').status_code==302


def test_https_support_form_and_reveal(app):
    app.config.update(WTF_CSRF_ENABLED=True,ACUITY_API_KEY='private-test-key')
    c=app.test_client();origin='https://market.example.com'
    def csrf(path):
        response=c.get(path,base_url=origin)
        assert response.headers['Referrer-Policy']=='strict-origin'
        return re.search(r'name="csrf_token"[^>]*value="([^"]+)"',response.text).group(1)
    token=csrf('/login')
    assert c.post('/login',base_url=origin,headers={'Referer':origin+'/'},data={'csrf_token':token,'email':'admin@example.com','password':PW}).status_code==302
    token=csrf('/support/integrations')
    r=c.post('/support/credentials/acuity/reveal',base_url=origin,headers={'Referer':origin+'/'},data={'csrf_token':token,'password':PW})
    assert r.status_code==200
    assert c.post('/support/accounts/3',base_url=origin,headers={'Referer':origin+'/'},data={'csrf_token':token,'body':'Helped account owner.'}).status_code==302


def test_captured_exception_metadata_is_safe_and_resolvable(app):
    @app.get('/test-failure/<token>')
    def failure(token):raise RuntimeError('MUST_NOT_LEAK_PASSWORD_OR_SQL')
    app.config.update(TESTING=False,PROPAGATE_EXCEPTIONS=False)
    c=app.test_client();login(c,'student')
    r=c.get('/test-failure/PRIVATE_PATH_TOKEN?key=PRIVATE_QUERY')
    assert r.status_code==500
    with app.app_context():
        item=SupportIncident.query.one();ref=item.reference;iid=item.id
        assert item.route=='/test-failure/<token>' and item.error_type=='RuntimeError'
        assert item.user_id==3
    assert ref in r.text and 'MUST_NOT_LEAK' not in r.text
    c.post('/logout');login(c,'admin')
    detail=c.get(f'/support/incidents/{iid}')
    assert 'PRIVATE_PATH_TOKEN' not in detail.text and 'PRIVATE_QUERY' not in detail.text and 'MUST_NOT_LEAK' not in detail.text
    assert c.post(f'/support/incidents/{iid}',data={'resolution':'Investigated hosting logs and resolved.'}).status_code==302
    with app.app_context():assert SupportIncident.query.one().status=='resolved'


def test_booking_lookup_and_notes_hidden_from_student(app):
    student=app.test_client();login(student,'student');student.post('/book/1',data=payload(student))
    c=app.test_client();login(c,'admin')
    c.post('/support/accounts/3',data={'body':'INTERNAL_NOTE_MUST_NOT_LEAK'})
    assert 'Exam prep' in c.get('/support/bookings?q=student@example.com').text
    r=c.get('/support/bookings/1');assert r.status_code==200 and 'not verification of a charge' in r.text
    assert 'INTERNAL_NOTE_MUST_NOT_LEAK' not in student.get('/dashboard').text
    assert 'INTERNAL_NOTE_MUST_NOT_LEAK' not in student.get('/bookings/1').text


def configure_acuity(app):
    app.config.update(ACUITY_USER_ID='12345',ACUITY_API_KEY='private-acuity-value')
    with app.app_context():
        cfg=settings();cfg.scheduling_provider='acuity';cfg.booking_mode='acuity'
        service=db.session.get(Service,1);service.mentor.acuity_calendar_id='321';service.acuity_type_id='654';db.session.commit()


def test_acuity_real_source_mapping_timezone_and_no_reservation(app,monkeypatch):
    from app.models import Booking
    configure_acuity(app);c=app.test_client();login(c,'student')
    chosen=(datetime.now(timezone.utc)+timedelta(days=2)).date().isoformat();month=chosen[:7];seen=[]
    def get(path,params):
        seen.append((path,params))
        if path=='availability/dates':return [{'date':chosen}]
        if path=='appointment-types':return [{'id':654,'duration':60}]
        if path=='appointments':return []
        return [{'time':chosen+'T14:00:00+0000'},{'time':chosen+'T14:00:00+0000'}]
    monkeypatch.setattr('app.acuity.api_get',get)
    r=c.get('/availability/1',query_string={'month':month,'date':chosen,'timezone':'UTC'})
    assert r.status_code==200 and '02:00 PM UTC' in r.text
    assert r.text.count('02:00 PM UTC')==1 and 'does not reserve it' in r.text
    assert 'private-acuity-value' not in r.text
    assert seen[0][1]['calendarID']=='321' and seen[0][1]['appointmentTypeID']=='654'
    assert seen[1][1]['date']==chosen and seen[1][1]['timezone']=='UTC'
    assert c.post('/availability/1').status_code==405
    assert c.get('/availability/1?timezone=MadeUp/Zone').status_code==400
    assert c.get('/availability/1?month=1900-01').status_code==400
    with app.app_context():assert Booking.query.count()==0


def test_acuity_missing_config_and_provider_failure(app,monkeypatch):
    configure_acuity(app);c=app.test_client();login(c,'student')
    from app.acuity import AcuityError
    def fail(*a,**kw):raise AcuityError('authentication_failed')
    monkeypatch.setattr('app.acuity.api_get',fail)
    r=c.get('/availability/1');assert 'could not load availability' in r.text
    assert 'calendar-day available' not in r.text
    with app.app_context():
        item=SupportIncident.query.one();assert item.error_type=='Acuity: authentication_failed'
        assert item.reference in r.text
    app.config['ACUITY_API_KEY']=''
    assert 'not available for this service yet' in c.get('/availability/1').text
    c.post('/logout');login(c,'admin')
    assert c.post('/support/integrations/acuity/check').status_code==302


def test_upgrade_additive_and_preserves_custom_settings(app):
    from app.upgrade import upgrade
    with app.app_context():
        upgrade();cfg=settings();cfg.fee_bps=2500;cfg.scheduling_provider='acuity';cfg.booking_mode='contact';db.session.commit()
        before=db.session.get(User,1).password_hash;upgrade()
        assert cfg.fee_bps==2500 and cfg.booking_mode=='contact'
        assert db.session.get(User,1).password_hash==before and User.query.count()==4
        assert db.session.get(SchemaRevision,'v0.4-support-center')


def test_acuity_transport_uses_fixed_origin_and_basic_auth(app,monkeypatch):
    import base64
    from app.acuity import api_get,NoRedirect,AcuityError
    configure_acuity(app);captured={}
    class Response:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read(self,limit):assert limit==1048577;return b'[{"date":"2026-11-01"}]'
    class Opener:
        def open(self,req,timeout):
            captured['url']=req.full_url;captured['auth']=req.get_header('Authorization');assert timeout==10
            return Response()
    monkeypatch.setattr('app.acuity.build_opener',lambda handler:Opener())
    with app.app_context():
        result=api_get('availability/dates',{'calendarID':'321','appointmentTypeID':'654','month':'2026-11','timezone':'America/New_York'})
        assert result==[{'date':'2026-11-01'}]
        assert captured['url'].startswith('https://acuityscheduling.com/api/v1/availability/dates?')
        assert 'private-acuity-value' not in captured['url']
        assert base64.b64decode(captured['auth'][6:]).decode()=='12345:private-acuity-value'
        with pytest.raises(ValueError):api_get('https://example.com/steal')
        assert NoRedirect().redirect_request(None,None,302,'',{},'https://example.com') is None


def test_native_entry_and_signin_return(app):
    configure_acuity(app);app.config['TEST_RESERVATIONS_ENABLED']=False
    c=app.test_client();r=c.get('/availability/1');assert r.status_code==302
    assert c.post('/login?next=/availability/1',data={'email':'student@example.com','password':PW}).location=='/availability/1'
    assert c.get('/book/1').location=='/availability/1'
    assert c.post('/book/1').status_code==403
    with app.app_context():
        settings().booking_mode='contact';db.session.commit()
    assert c.get('/availability/1').status_code==404


def test_database_independent_error_fallback(app,monkeypatch):
    @app.get('/error-fallback-test')
    def fail():raise RuntimeError('unexpected failure')
    def broken_context():raise RuntimeError('database settings unavailable')
    app.template_context_processors[None].append(broken_context)
    app.config.update(TESTING=False,PROPAGATE_EXCEPTIONS=False)
    r=app.test_client().get('/error-fallback-test')
    assert r.status_code==500 and 'Support reference' in r.text
    assert 'database settings unavailable' not in r.text
