import io
import re
from datetime import timedelta
from urllib.parse import urlsplit
import pytest
from PIL import Image
from test_workflows import app, login, payload, verify_mail
from app.models import (db,User,Mentor,Service,Booking,AccountAccess,PasswordLink,PlatformAudit,PhotoSubmission,MentorPhoto,ServiceScheduling,PlatformSettings,SchemaRevision,now)
from app.security import settings
from app.booking_config import split_amount,validate_booking_url

PW='long-password-123'
def identity(**kw):return dict(admin_password=PW,reason='Authorized account maintenance',**kw)
def manager(app):
    with app.app_context():db.session.get(User,4).role='account_manager';db.session.commit()
def picture(color='red'):
    out=io.BytesIO();Image.new('RGB',(700,600),color).save(out,'PNG');out.seek(0);return out

def test_role_boundaries_and_admin_creation(app):
    manager(app);c=app.test_client();login(c,'other')
    for url in ['/admin/control','/admin/users','/admin/users/new','/admin/settings','/admin/data','/admin/resources','/admin/audit','/admin/mentors/1/integration']:
        assert c.get(url).status_code==403
    assert c.get('/admin').status_code==200
    assert c.get('/admin/mentors/new').status_code==200
    assert c.get('/team/photos').status_code==200
    assert c.post('/admin/users/1',data=identity(name='Admin',email='admin@example.com',role='account_manager')).status_code==403
    c.post('/logout');login(c,'admin')
    for url in ['/admin/control','/admin/users','/admin/users/1','/admin/settings','/admin/data','/admin/resources','/admin/audit','/admin/mentors/1/integration']:
        assert c.get(url).status_code==200,url
    response=c.post('/admin/users/new',data=identity(name='New Manager',email='manager@example.com',role='account_manager'))
    assert response.status_code==200 and 'link created' in response.text
    link=re.search(r'<textarea id="account-link"[^>]*>([^<]+)',response.text).group(1)
    with app.app_context():
        u=User.query.filter_by(email='manager@example.com').one();assert u.role=='account_manager'
        assert PW not in u.password_hash
    new=app.test_client();assert new.post(urlsplit(link).path,data={'password':'new-manager-password','confirm':'new-manager-password'}).status_code==302
    verify_mail(new,app,'manager@example.com','new-manager-password')
    assert new.get('/admin').status_code==200
    assert new.get('/admin/users').status_code==403


def test_identity_changes_revocation_and_self_protection(app):
    student=app.test_client();login(student,'student')
    admin=app.test_client();login(admin,'admin')
    r=admin.post('/admin/users/1',data=identity(name='Admin',email='admin@example.com',role='student',enabled='y'))
    assert 'cannot disable or demote' in r.text
    with app.app_context():assert db.session.get(User,1).role=='admin'
    assert admin.post('/admin/users/3',data=identity(name='Student',email='student@example.com',role='student')).status_code==302
    assert student.get('/dashboard').status_code==302
    assert 'Email or password is incorrect' in login(student,'student').text
    assert admin.post('/admin/users/3',data=identity(name='Student',email='student@example.com',role='student',enabled='y')).status_code==302
    assert login(student,'student').status_code==302
    assert student.get('/dashboard').status_code==200


def test_password_reset_single_use_expiry_and_link_replacement(app):
    c=app.test_client();login(c,'admin');old=app.test_client();login(old,'student')
    def link():
        result=c.post('/admin/users/3/password',data=identity())
        assert result.status_code==200
        return urlsplit(re.search(r'<textarea id="account-link"[^>]*>([^<]+)',result.text).group(1)).path
    first=link();assert old.get('/dashboard').status_code==302
    second=link();anon=app.test_client();assert anon.get(first).status_code==400
    assert anon.post(second,data={'password':'new-student-password','confirm':'new-student-password'}).status_code==302
    assert anon.get(second).status_code==400
    anon.post('/logout');assert 'Email or password is incorrect' in login(anon,'student').text
    third=link()
    with app.app_context():PasswordLink.query.one().expires_at=now()-timedelta(seconds=1);db.session.commit()
    assert anon.get(third).status_code==400
    assert c.post('/admin/users/3/password',data={'admin_password':'wrong','reason':'Reset requested'}).status_code==200
    with app.app_context():assert PlatformAudit.query.filter_by(action='Password changed').count()==1


def test_photo_review_ownership_publication_and_replacement(app):
    manager(app);mentor=app.test_client();login(mentor,'mentor');staff=app.test_client();login(staff,'other');public=app.test_client()
    assert mentor.post('/mentors/1/photo',data={'photo':(picture(),'photo.png')}).status_code==302
    assert public.get('/media/mentors/1/photo').status_code==404
    with app.app_context():
        item=PhotoSubmission.query.one();assert item.status=='pending';pid=item.id
        img=Image.open(io.BytesIO(item.image));assert img.size==(512,512) and img.format=='JPEG'
    assert public.get(f'/team/photos/{pid}/image').status_code==302
    student=app.test_client();login(student,'student');assert student.get(f'/team/photos/{pid}/image').status_code==403
    assert student.post('/mentors/1/photo',data={'photo':(picture(),'p.png')}).status_code==403
    assert mentor.post(f'/team/photos/{pid}/review',data={'decision':'approve'}).status_code==403
    assert staff.post(f'/team/photos/{pid}/review',data={'decision':'approve'}).status_code==302
    original=public.get('/media/mentors/1/photo').data
    assert public.get('/media/mentors/1/photo').mimetype=='image/jpeg'
    assert '/media/mentors/1/photo' in public.get('/').text
    mentor.post('/mentors/1/photo',data={'photo':(picture('blue'),'p.png')})
    with app.app_context():new=PhotoSubmission.query.filter_by(status='pending').one().id
    assert public.get('/media/mentors/1/photo').data==original
    staff.post(f'/team/photos/{new}/review',data={'decision':'reject','note':'Please use a clear headshot.'})
    assert public.get('/media/mentors/1/photo').data==original
    assert 'Please use a clear headshot' in mentor.get('/mentors/1/photo').text
    mentor.post('/mentors/1/photo',data={'photo':(picture('green'),'p.png')})
    with app.app_context():new=PhotoSubmission.query.filter_by(status='pending').one().id
    staff.post(f'/team/photos/{new}/review',data={'decision':'approve'})
    assert public.get('/media/mentors/1/photo').data!=original
    assert staff.post(f'/team/photos/{pid}/review',data={'decision':'approve'}).status_code==302
    staff.post('/team/mentors/1/photo/remove',data={})
    assert public.get('/media/mentors/1/photo').status_code==404


def test_invalid_images_and_oversized_uploads(app):
    c=app.test_client();login(c,'mentor')
    for content in (b'<svg onload="alert(1)"></svg>', b'not a picture'):
        r=c.post('/mentors/1/photo',data={'photo':(io.BytesIO(content),'fake.jpg')})
        assert r.status_code==200
    r=c.post('/mentors/1/photo',data={'photo':(io.BytesIO(b'x'*(5*1024*1024+1)),'big.jpg')})
    assert 'smaller than 5 MB' in r.text
    r=c.post('/mentors/1/photo',data={'photo':(io.BytesIO(b'x'*(7*1024*1024)),'big.jpg')})
    assert r.status_code==413
    with app.app_context():assert PhotoSubmission.query.count()==0


def test_split_and_provider_configuration(app):
    assert split_amount(10000)=={'gross_cents':10000,'company_cents':2000,'mentor_cents':8000,'fee_bps':2000}
    assert split_amount(9999)['company_cents']+split_amount(9999)['mentor_cents']==9999
    for url in ('javascript:alert(1)','https://cal.com.evil.test/x','https://cal.com@evil.test/','http://cal.com/x','https://cal.com:444/x'):
        assert not validate_booking_url('calcom',url)
    assert validate_booking_url('calcom','https://cal.com/ttbg/support')
    manager(app);c=app.test_client();login(c,'other')
    assert c.post('/admin/services/1/scheduling',data={'provider':'calcom','event_type_id':'123','booking_url':'https://cal.com/ttbg/support'}).status_code==302
    assert 'View availability' not in app.test_client().get('/mentor/1').text
    # Managers cannot override platform commission via a forged form value.
    assert c.post('/admin/mentors/1/services/1',data={'name':'Exam prep','price':'100','duration':'60','fee_percent':'0'}).status_code==302
    with app.app_context():assert db.session.get(Service,1).fee_bps==2000
    c.post('/logout');login(c,'admin')
    data=identity(site_title='TTBG Marketplace',description='Mentoring and learning',support_email='support@example.com',registration_open='y',fee_percent='20',scheduling_provider='calcom',booking_mode='external')
    assert c.post('/admin/settings',data=data).status_code==302
    assert 'https://cal.com/ttbg/support' in app.test_client().get('/mentor/1').text
    assert c.post('/admin/services/1/scheduling',data={'provider':'calcom','booking_url':'https://evil.test'}).status_code==200
    with app.app_context():assert ServiceScheduling.query.one().booking_url=='https://cal.com/ttbg/support'


def test_settings_maintenance_registration_and_redacted_exports(app):
    c=app.test_client();login(c,'admin')
    from app.diagnostics import VIEWS
    for table in VIEWS:
        assert c.get('/admin/data',query_string={'table':table}).status_code==200,table
    export=c.get('/admin/data?table=market_user&format=csv')
    assert export.status_code==400  # Diagnostic exports intentionally removed in v0.9.
    assert c.get('/admin/data?table=not_real').status_code==404
    with app.app_context():
        cfg=settings();cfg.registration_open=False;db.session.commit()
    anon=app.test_client();assert anon.get('/register').status_code==403
    with app.app_context():settings().maintenance_mode=True;db.session.commit()
    assert anon.get('/').status_code==503
    assert anon.get('/health').status_code==200
    assert anon.get('/login').status_code==200
    assert c.get('/admin/settings').status_code==200
    assert c.get('/admin/control').status_code==200


def test_upgrade_preserves_identity_history_and_changes_future_split(app):
    from app.upgrade import upgrade
    c=app.test_client();login(c,'student');c.post('/book/1',data=payload(c))
    with app.app_context():
        db.session.get(User,4).role='onboarding';db.session.commit()
        before=db.session.get(User,1).password_hash
        upgrade()
        assert db.session.get(User,4).role=='account_manager'
        assert db.session.get(User,1).role=='admin' and db.session.get(User,1).password_hash==before
        assert db.session.get(Service,1).fee_bps==2000
        assert Booking.query.one().fee_cents==1500
        assert SchemaRevision.query.count()==7
        upgrade();assert SchemaRevision.query.count()==7 and User.query.count()==4


def test_disabled_mentor_hides_photo_profile_and_blocks_existing_session(app):
    mentor=app.test_client();login(mentor,'mentor');admin=app.test_client();login(admin,'admin')
    mentor.post('/mentors/1/photo',data={'photo':(picture(),'p.png')})
    admin.post('/team/photos/1/review',data={'decision':'approve'})
    admin.post('/admin/users/2',data=identity(name='Mentor',email='mentor@example.com',role='mentor'))
    public=app.test_client()
    assert public.get('/mentor/1').status_code==404
    assert public.get('/media/mentors/1/photo').status_code==404
    assert 'Exam mentor' not in public.get('/').text
    assert mentor.get('/dashboard').status_code==302
    assert admin.get('/mentors/1/photo').status_code==200
    assert admin.post('/team/mentors/1/photo/remove',data={}).status_code==302


def test_new_admin_actions_enforce_csrf_and_confirmation(app):
    c=app.test_client();login(c,'admin')
    bad=identity(name='Bad',email='bad@example.com',role='account_manager')
    bad['admin_password']='incorrect'
    response=c.post('/admin/users/new',data=bad)
    assert response.status_code==200 and 'admin password is incorrect' in response.text
    with app.app_context():assert User.query.filter_by(email='bad@example.com').first() is None
    app.config['WTF_CSRF_ENABLED']=True
    assert c.post('/admin/users/new',data=identity(name='Blocked',email='blocked@example.com',role='admin')).status_code==400
    assert c.post('/team/photos/1/review',data={'decision':'approve'}).status_code==400


def test_https_csrf_login_and_admin_forms(app):
    app.config['WTF_CSRF_ENABLED']=True
    c=app.test_client();origin='https://market.example.com'
    html=c.get('/login',base_url=origin)
    assert html.headers['Referrer-Policy']=='strict-origin'
    token=re.search(r'name="csrf_token"[^>]*value="([^"]+)"',html.text).group(1)
    response=c.post('/login',base_url=origin,headers={'Referer':origin+'/'},data={'csrf_token':token,'email':'admin@example.com','password':PW})
    assert response.status_code==302
    html=c.get('/admin/users/new',base_url=origin)
    assert html.headers['Referrer-Policy']=='strict-origin'
    token=re.search(r'name="csrf_token"[^>]*value="([^"]+)"',html.text).group(1)
    response=c.post('/admin/users/new',base_url=origin,headers={'Referer':origin+'/'},data=identity(csrf_token=token,name='Manager Two',email='manager2@example.com',role='account_manager'))
    assert response.status_code==200 and 'link created' in response.text
