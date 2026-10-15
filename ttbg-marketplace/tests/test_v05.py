from datetime import timedelta
from urllib.parse import urlsplit,parse_qs
import re
import smtplib
import pytest
from werkzeug.security import check_password_hash,generate_password_hash
from test_workflows import app,login,payload,verify_mail
from test_v03 import PW,manager,picture
from app.models import (db,User,EmailIdentity,SecurityRate,SupportNote,PlatformAudit,Booking,AccountAccess,
    Mentor,MentorAudit,MentorDetails,PhotoSubmission,MentorPhoto,PasswordLink,SupportIncident,Service,SchemaRevision,now)
from app.registration_security import email_allowed,issue_email,mark_pending,rate_allowed,send_email as real_send_email

REG={'name':'New Learner','email':'new@example.com','password':'initial-password-123','confirm':'initial-password-123'}
def token(app,email='new@example.com'):
    link=next(link for recipient,link in reversed(app.mail_outbox) if recipient==email)
    return parse_qs(urlsplit(link).fragment)['token'][0]
def confirm(c,t,pw='new-owner-password-123'):
    return c.post('/verify-email/confirm',data={'token':t,'password':pw,'confirm':pw})
def delete(c,uid,email,**kw):
    data={'confirm_email':email,'admin_password':PW,'reason':'Remove requested test account'};data.update(kw)
    return c.post(f'/admin/users/{uid}/delete',data=data)


def test_registration_pending_verify_single_use_and_password_ownership(app):
    c=app.test_client();r=c.post('/register',data=REG);assert r.location=='/verify-email'
    assert len(app.mail_outbox)==1
    t=token(app)
    with app.app_context():
        u=User.query.filter_by(email=REG['email']).one();assert not email_allowed(u)
        assert u.email_identity.token_hash!=t and len(u.email_identity.token_hash)==64
    for path in ['/dashboard','/book/1','/availability/1','/support','/admin']:
        assert c.get(path).location=='/verify-email'
    assert c.get('/verify-email/confirm').status_code==200
    assert t not in c.get('/verify-email').text
    # Email scanners visiting GET do not consume anything. A different browser can prove ownership.
    owner=app.test_client();r=confirm(owner,t);assert r.status_code==200 and 'Your email is verified' in r.text
    assert owner.get('/dashboard').status_code==302 # confirmation is not automatic sign-in
    assert c.get('/dashboard').location.startswith('/login') # old pending session revoked
    assert confirm(owner,t).status_code==400
    assert 'Email or password is incorrect' in owner.post('/login',data={'email':REG['email'],'password':REG['password']}).text
    assert owner.post('/login',data={'email':REG['email'],'password':'new-owner-password-123'}).status_code==302
    assert owner.get('/dashboard').status_code==200


def test_resend_expiry_and_old_link_invalidation(app):
    c=app.test_client();c.post('/register',data=REG);first=token(app)
    c.post('/verify-email');assert len(app.mail_outbox)==1
    with app.app_context():
        SecurityRate.query.update({'expires_at':now()-timedelta(seconds=1)});db.session.commit()
    c.post('/verify-email');second=token(app);assert first!=second
    assert confirm(app.test_client(),first).status_code==400
    with app.app_context():
        row=User.query.filter_by(email=REG['email']).one().email_identity;row.expires_at=now()-timedelta(seconds=1);db.session.commit()
    assert confirm(app.test_client(),second).status_code==400


def test_delivery_failure_retains_pending_account_and_no_secret_leak(app,monkeypatch):
    def fail(*a):raise smtplib.SMTPException('SECRET_SMTP_PASSWORD')
    monkeypatch.setattr('app.registration_security.send_email',fail)
    c=app.test_client();r=c.post('/register',data=REG,follow_redirects=True)
    assert r.status_code==200 and 'SECRET_SMTP_PASSWORD' not in r.text
    with app.app_context():
        u=User.query.filter_by(email=REG['email']).one()
        assert not email_allowed(u) and u.email_identity.token_hash is None
        assert PlatformAudit.query.filter_by(action='Verification email failed').count()==1


def test_missing_mail_config_blocks_registration_but_not_existing_accounts(app):
    app.config['SMTP_HOST']='';c=app.test_client()
    assert c.get('/register').status_code==503 and c.post('/register',data=REG).status_code==503
    assert login(c,'admin').status_code==302 and c.get('/admin').status_code==200
    with app.app_context():assert User.query.count()==4


def test_email_change_invalidates_verification_and_old_links(app):
    c=app.test_client();login(c,'student')
    with app.app_context():
        u=db.session.get(User,3);u.email='changed@example.com';db.session.commit()
        assert not email_allowed(u) and u.email_identity.email=='changed@example.com'
    assert c.get('/dashboard').location=='/verify-email'
    c.post('/verify-email');t=token(app,'changed@example.com')
    with app.app_context():
        u=db.session.get(User,3);u.email='student@example.com';db.session.commit();assert not email_allowed(u)
    assert confirm(app.test_client(),t).status_code==400


def test_verification_links_use_configured_origin_not_host(app):
    app.config['PUBLIC_BASE_URL']='https://market.example.com'
    c=app.test_client();c.post('/register',data=REG,headers={'Host':'evil.example','X-Forwarded-Host':'evil.example'})
    link=app.mail_outbox[-1][1]
    assert link.startswith('https://market.example.com/verify-email/confirm#token=') and 'evil.example' not in link
    app.config['PUBLIC_BASE_URL']='https://market.example.com@evil.example/path'
    from app.registration_security import mail_ready
    with app.app_context():assert not mail_ready()


def test_verification_csrf_invalid_password_and_disabled_account(app):
    c=app.test_client();c.post('/register',data=REG);t=token(app)
    r=confirm(c,t,'short');assert r.status_code==200
    with app.app_context():assert not email_allowed(User.query.filter_by(email=REG['email']).one())
    app.config['WTF_CSRF_ENABLED']=True
    assert confirm(c,t).status_code==400
    app.config['WTF_CSRF_ENABLED']=False
    with app.app_context():
        u=User.query.filter_by(email=REG['email']).one();u.access.enabled=False;db.session.commit()
    assert confirm(app.test_client(),t).status_code==400


def turnstile(app):
    app.config.update(TURNSTILE_ENABLED=True,TURNSTILE_SITE_KEY='site',TURNSTILE_SECRET_KEY='secret-private',TURNSTILE_HOSTNAMES='market.example.com')
def fake_cloudflare(monkeypatch,response):
    import json
    class Response:
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def read(self,n):return json.dumps(response).encode()
    class Opener:
        def open(self,req,timeout):
            assert req.full_url=='https://challenges.cloudflare.com/turnstile/v0/siteverify'
            assert timeout==8 and req.method=='POST' and b'secret-private' in req.data
            return Response()
    monkeypatch.setattr('app.registration_security.build_opener',lambda handler:Opener())

@pytest.mark.parametrize('response',[{'success':False},{'success':True,'hostname':'evil.example','action':'register'},{'success':True,'hostname':'market.example.com','action':'login'}])
def test_turnstile_rejects_invalid_results(app,monkeypatch,response):
    turnstile(app);fake_cloudflare(monkeypatch,response);c=app.test_client()
    r=c.post('/register',data=dict(REG,**{'cf-turnstile-response':'token-one'}))
    assert 'Complete the bot check' in r.text
    with app.app_context():assert User.query.count()==4


def test_turnstile_success_replay_and_csp_scope(app,monkeypatch):
    turnstile(app);fake_cloudflare(monkeypatch,{'success':True,'hostname':'market.example.com','action':'register'})
    c=app.test_client();r=c.get('/register')
    assert 'secret-private' not in r.text
    assert 'https://challenges.cloudflare.com' in r.headers['Content-Security-Policy']
    assert 'https://challenges.cloudflare.com' not in c.get('/login').headers['Content-Security-Policy']
    data=dict(REG,**{'cf-turnstile-response':'token-one'})
    assert c.post('/register',data=data).status_code==302
    data['email']='second@example.com'
    assert 'Complete the bot check' in app.test_client().post('/register',data=data).text
    with app.app_context():assert User.query.count()==5


def test_turnstile_fail_closed_missing_key_and_network_error(app,monkeypatch):
    turnstile(app);app.config['TURNSTILE_SECRET_KEY']=''
    c=app.test_client();assert 'Complete the bot check' in c.post('/register',data=REG).text
    app.config['TURNSTILE_SECRET_KEY']='secret-private'
    class Broken:
        def open(self,*a,**kw):raise TimeoutError()
    monkeypatch.setattr('app.registration_security.build_opener',lambda *a:Broken())
    r=c.post('/register',data=dict(REG,**{'cf-turnstile-response':'valid-shape'}));assert r.status_code==200
    with app.app_context():assert User.query.count()==4


def test_registration_rate_limit_and_invalid_email(app):
    c=app.test_client()
    assert c.post('/register',data=dict(REG,email='not-an-email')).status_code==200
    for _ in range(9):c.post('/register',data={'email':'invalid'})
    assert c.post('/register',data=REG).status_code==429
    with app.app_context():assert User.query.count()==4


def test_delete_student_is_hard_delete_and_old_sessions_cannot_revive(app):
    old=app.test_client();login(old,'other')
    c=app.test_client();login(c,'admin')
    c.post('/support/accounts/4',data={'body':'Account deletion requested.'})
    assert c.get('/admin/users/4/delete').status_code==200
    assert delete(c,4,'other@example.com').status_code==302
    with app.app_context():
        assert db.session.get(User,4) is None
        assert EmailIdentity.query.filter_by(user_id=4).count()==0
        assert SupportNote.query.filter_by(user_id=4).count()==0
        archive=User.query.filter_by(role='archive').one();assert archive.id>4 and not archive.access.enabled
        new=User(name='New owner',email='other@example.com',role='student',password_hash=generate_password_hash(PW));db.session.add(new);db.session.commit();assert new.id>4
        assert PlatformAudit.query.filter_by(action='Account permanently deleted').count()==1
    assert old.get('/dashboard').status_code==302
    assert 'deleted.invalid' not in c.get('/admin/users').text


def test_delete_mentor_removes_dependent_records_with_foreign_keys(app):
    mentor=app.test_client();login(mentor,'mentor');mentor.post('/mentors/1/photo',data={'photo':(picture(),'headshot.png')})
    student=app.test_client();login(student,'student');student.post('/book/1',data=payload(student))
    c=app.test_client();login(c,'admin');c.post('/team/photos/1/review',data={'decision':'approve'})
    assert delete(c,2,'mentor@example.com').status_code==302
    with app.app_context():
        assert db.session.get(User,2) is None and Mentor.query.count()==0 and Service.query.count()==0
        assert PhotoSubmission.query.count()==0 and MentorPhoto.query.count()==0 and Booking.query.count()==0
    assert app.test_client().get('/mentor/1').status_code==404


def test_delete_staff_preserves_shared_audit_notes_and_photos(app):
    manager(app);staff=app.test_client();login(staff,'other')
    staff.post('/support/accounts/3',data={'body':'Shared note that must remain.'})
    staff.post('/mentors/1/photo',data={'photo':(picture(),'headshot.png')})
    staff.post('/team/photos/1/review',data={'decision':'approve'})
    with app.app_context():
        db.session.add(MentorAudit(mentor_id=1,actor_id=4,action='Staff reviewed profile',detail='Existing history'))
        db.session.add(MentorDetails(mentor_id=1,owner_id=4));db.session.commit()
    c=app.test_client();login(c,'admin');r=delete(c,4,'other@example.com');assert r.status_code==302,r.text
    with app.app_context():
        assert db.session.get(User,4) is None
        assert SupportNote.query.one().author.role=='archive'
        assert MentorAudit.query.one().actor.role=='archive'
        assert PhotoSubmission.query.one().image and PhotoSubmission.query.one().submitted_by!=4
        assert MentorDetails.query.one().owner_id is None
    assert app.test_client().get('/media/mentors/1/photo').status_code==200


def test_deletion_permissions_password_self_history_and_csrf(app):
    manager(app)
    for name in ('other','student','mentor'):
        c=app.test_client();login(c,name)
        assert c.get('/admin/users/3/delete').status_code==403
        assert delete(c,3,'student@example.com').status_code==403
    c=app.test_client();login(c,'admin')
    assert delete(c,1,'admin@example.com').status_code==403
    assert delete(c,3,'wrong@example.com').status_code==200
    assert delete(c,3,'student@example.com',admin_password='wrong').status_code==200
    student=app.test_client();login(student,'student');student.post('/book/1',data=payload(student))
    with app.app_context():Booking.query.one().payment_status='paid';db.session.commit()
    assert delete(c,3,'student@example.com').status_code==302
    with app.app_context():
        assert db.session.get(User,3) is None and Booking.query.count()==1
        assert Booking.query.one().student.role=='archive' and Booking.query.one().payment_status=='paid'
    app.config['WTF_CSRF_ENABLED']=True
    assert delete(c,4,'other@example.com').status_code==400


def test_upgrade_grandfathers_existing_accounts_without_enabling_disabled(app):
    from app.upgrade import upgrade
    with app.app_context():
        EmailIdentity.query.delete();db.session.add(AccountAccess(user_id=3,enabled=False));db.session.commit()
        before=db.session.get(User,1).password_hash
        upgrade();db.session.expire_all()
        assert all(email_allowed(u) for u in User.query)
        assert db.session.get(User,1).password_hash==before
        assert not db.session.get(User,3).access.enabled
        new=User(name='Pending',email='pending@example.com',role='student',password_hash='hash');db.session.add(new);db.session.commit()
        upgrade();assert not email_allowed(new)


def test_cli_bootstrap_admin_is_trusted_not_mailbox_verified(app):
    result=app.test_cli_runner().invoke(args=['create-admin','--email','bootstrap@example.com','--name','Bootstrap','--password',PW])
    assert result.exit_code==0,result.output
    with app.app_context():
        u=User.query.filter_by(email='bootstrap@example.com').one();assert email_allowed(u) and not u.email_identity.verified_at


def test_smtp_transport_uses_tls_and_sends_only_to_target(app,monkeypatch):
    calls=[]
    class SMTP:
        def __init__(self,**kwargs):assert kwargs['timeout']==10 and kwargs['port']==587
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def ehlo(self):calls.append('ehlo')
        def starttls(self,context):assert context.check_hostname;calls.append('tls')
        def login(self,username,password):calls.append('login')
        def send_message(self,message):
            assert message['To']=='owner@example.com' and message['From']=='support@example.com'
            assert '#token=private-test-token' in message.get_body(preferencelist=('plain',)).get_content()
            calls.append('sent')
    monkeypatch.setattr('app.registration_security.smtplib.SMTP',SMTP)
    with app.app_context():real_send_email('owner@example.com','https://market.example.com/verify-email/confirm#token=private-test-token')
    assert calls==['ehlo','tls','ehlo','login','sent']


def test_proxy_trust_uses_rightmost_configured_hop(monkeypatch):
    from app import create_app
    from flask import request
    monkeypatch.setenv('RENDER','true');monkeypatch.setenv('TRUSTED_PROXY_HOPS','1')
    instance=create_app({'TESTING':True,'SECRET_KEY':'p'*40,'SQLALCHEMY_DATABASE_URI':'sqlite://'})
    with instance.app_context():
        db.create_all()
    @instance.get('/proxy-check')
    def proxy_check():return request.remote_addr
    r=instance.test_client().get('/proxy-check',headers={'X-Forwarded-For':'203.0.113.99, 198.51.100.8','X-Forwarded-Proto':'https'})
    assert r.text=='198.51.100.8'


def test_deletion_does_not_offer_an_archive_account_for_recovery(app):
    c=app.test_client();login(c,'admin');delete(c,4,'other@example.com')
    with app.app_context():archive_id=User.query.filter_by(role='archive').one().id
    assert c.get(f'/admin/users/{archive_id}').status_code==404
    assert c.get(f'/admin/users/{archive_id}/delete').status_code==404
    from app.security import account_enabled
    with app.app_context():assert not account_enabled(db.session.get(User,archive_id))
