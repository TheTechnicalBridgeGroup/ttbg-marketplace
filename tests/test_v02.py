import re
from decimal import Decimal
from test_workflows import app,login,payload
from app.models import db,User,Mentor,Service,Booking,MentorDetails,MentorInvitation,MentorAudit

DATA={'name':'New Mentor','email':'newmentor@example.com','lane':'Technology','title':'Software mentor','bio':'I help students grow their software skills through practical projects.','experience':'Ten years of software support and automation.','years_experience':10,'languages':'English','timezone':'America/New_York','specialties':'Python, APIs','education':'IT degree','session_approach':'Hands-on practice','phone':'555-0101','internal_notes':'PRIVATE_TEAM_NOTE','application_reference':'APP-001','owner_id':1}
CHECKS=['application_reviewed','credentials_reviewed','agreement_received','orientation_complete','profile_consent']
def create(c,complete=False):
    data=dict(DATA)
    if complete:data.update({k:'y' for k in CHECKS})
    return c.post('/admin/mentors/new',data=data)
def invite(c,mid=2):
    response=c.post(f'/admin/mentors/{mid}/invite')
    return re.search(r'<textarea id="activation-link" readonly>([^<]+)',response.text).group(1).split('localhost')[-1]

def test_admin_crud_readiness_private_fields_and_audit(app):
    c=app.test_client();login(c,'admin');r=create(c);assert r.status_code==302
    assert c.get('/mentor/2').status_code==404
    r=c.post('/admin/mentors/2',data={'status':'approved'});assert b'Before publishing' in r.data
    assert c.get('/mentor/2').status_code==404
    data=dict(DATA);data.update({k:'y' for k in CHECKS})
    assert c.post('/admin/mentors/2/edit',data=data).status_code==302
    assert c.post('/admin/mentors/2/services/new',data={'name':'Python mentoring','price':'75.00','duration':60,'fee_percent':'15'}).status_code==302
    assert c.post('/admin/mentors/2',data={'status':'approved'}).status_code==302
    public=c.get('/mentor/2').text
    assert 'Hands-on practice' in public and 'Python, APIs' in public
    assert 'PRIVATE_TEAM_NOTE' not in public and '555-0101' not in public and 'APP-001' not in public
    assert c.get('/admin/mentors/2/preview').status_code==200
    with app.app_context():assert MentorAudit.query.filter_by(mentor_id=2).count()>=4
    # Removing a required readiness item takes a published profile back to review.
    data.pop('profile_consent');c.post('/admin/mentors/2/edit',data=data)
    assert c.get('/mentor/2').status_code==404

def test_activation_price_ownership_and_old_booking(app):
    c=app.test_client();login(c,'admin');create(c)
    first=invite(c);second=invite(c)
    anon=app.test_client();assert anon.get(first).status_code==400
    assert anon.post(second,data={'password':'mentor-long-password','confirm':'mentor-long-password'}).status_code==302
    assert anon.get(second).status_code==400
    assert anon.get('/dashboard').status_code==200
    with app.app_context():
        db.session.add(Service(mentor_id=2,name='Support',price_cents=7500,duration=60,fee_bps=1500));db.session.commit()
    assert anon.post('/mentor/services/1/price',data={'price':'80.00'}).status_code==403
    assert anon.post('/mentor/services/2/price',data={'price':'89.95','fee_bps':0}).status_code==302
    with app.app_context():
        s=db.session.get(Service,2);assert s.price_cents==8995 and s.fee_bps==1500
    # Existing mentor changes own service; a previous reservation is unchanged.
    student=app.test_client();login(student,'student');student.post('/book/1',data=payload(student))
    mentor=app.test_client();login(mentor,'mentor');assert mentor.post('/mentor/services/1/price',data={'price':'123.45'}).status_code==302
    with app.app_context():assert Booking.query.one().price_cents==10000

def test_suspension_blocks_existing_session_and_delete_retains_history(app):
    mentor=app.test_client();login(mentor,'mentor')
    student=app.test_client();login(student,'student');student.post('/book/1',data=payload(student))
    c=app.test_client();login(c,'admin')
    assert c.post('/admin/mentors/1/lifecycle',data={'action':'suspend','reason':'Temporary pause','confirm_name':'Wrong'}).status_code==200
    with app.app_context():assert db.session.get(Mentor,1).status=='approved'
    c.post('/admin/mentors/1/lifecycle',data={'action':'suspend','reason':'Temporary pause','confirm_name':'Mentor'})
    assert mentor.post('/mentor/services/1/price',data={'price':'5'}).status_code==302
    assert mentor.get('/dashboard').status_code==302
    assert b'Email or password is incorrect' in login(mentor,'mentor').data
    assert student.get('/book/1').status_code==404
    assert student.get('/bookings/1').status_code==200
    assert c.post('/admin/mentors/1',data={'status':'approved'}).status_code==200
    with app.app_context():assert db.session.get(Mentor,1).status=='suspended'
    c.post('/admin/mentors/1/lifecycle',data={'action':'delete','reason':'Remove from marketplace','confirm_name':'Mentor'})
    with app.app_context():assert db.session.get(Mentor,1).status=='deleted' and Booking.query.count()==1
    assert 'Exam mentor' not in c.get('/').text
    assert 'mentor@example.com' not in c.get('/admin').text
    assert 'mentor@example.com' in c.get('/admin?status=deleted').text
    c.post('/admin/mentors/1/lifecycle',data={'action':'restore','reason':'Return for review','confirm_name':'Mentor'})
    with app.app_context():assert db.session.get(Mentor,1).status=='draft'

def test_admin_creation_cannot_hijack_staff_or_link_without_confirmation(app):
    c=app.test_client();login(c,'admin');data=dict(DATA)
    data['email']='admin@example.com';assert c.post('/admin/mentors/new',data=data).status_code==200
    data['email']='student@example.com';assert c.post('/admin/mentors/new',data=data).status_code==200
    with app.app_context():assert Mentor.query.count()==1
    data['confirm_link']='y';assert c.post('/admin/mentors/new',data=data).status_code==302
    with app.app_context():assert db.session.get(User,3).role=='mentor'
    assert b'already has account access' in c.post('/admin/mentors/2/invite',follow_redirects=True).data

def test_staff_delegation_and_student_denial(app):
    c=app.test_client();login(c,'student')
    for path in ['/admin/mentors/new','/admin/mentors/1/edit','/admin/mentors/1/lifecycle','/admin/mentors/1/preview']:
        assert c.get(path).status_code==403
    assert c.post('/admin/mentors/1/invite').status_code==403
    with app.app_context():db.session.get(User,4).role='onboarding';db.session.commit()
    c.post('/logout');login(c,'other');assert c.get('/admin').status_code==200
    assert create(c).status_code==302

def test_price_changed_during_booking_requires_new_review(app):
    c=app.test_client();login(c,'student');data=payload(c)
    mentor=app.test_client();login(mentor,'mentor');mentor.post('/mentor/services/1/price',data={'price':'135'})
    r=c.post('/book/1',data=data);assert r.location=='/book/1'
    with app.app_context():assert Booking.query.count()==0
    assert c.post('/book/1',data=payload(c)).status_code==302
    with app.app_context():assert Booking.query.one().price_cents==13500

def test_v01_database_additive_upgrade(tmp_path):
    from app import create_app
    from sqlalchemy import create_engine,text
    dbfile=tmp_path/'old.db';engine=create_engine('sqlite:///'+str(dbfile))
    # Existing v0.1 tables contain no v0.2 columns; init-db only adds new tables.
    old_tables=[t for t in db.metadata.sorted_tables if t.name not in ['market_mentor_details','market_mentor_invitation','market_mentor_audit']]
    db.metadata.create_all(engine,tables=old_tables)
    with engine.begin() as conn:conn.execute(text("INSERT INTO market_user(id,name,email,password_hash,role,created_at) VALUES(1,'Existing','existing@example.com','hash','student',CURRENT_TIMESTAMP)"))
    upgraded=create_app({'TESTING':True,'SECRET_KEY':'z'*40,'SQLALCHEMY_DATABASE_URI':'sqlite:///'+str(dbfile)})
    result=upgraded.test_cli_runner().invoke(args=['init-db']);assert result.exit_code==0
    with upgraded.app_context():assert db.session.get(User,1).name=='Existing' and MentorDetails.query.count()==0


def test_invalid_prices_are_rejected(app):
    c=app.test_client();login(c,'mentor')
    for price in ['-1','0','1001','NaN','Infinity','text']:
        assert c.post('/mentor/services/1/price',data={'price':price}).status_code==200
    with app.app_context():assert db.session.get(Service,1).price_cents==10000

def test_mentor_credential_change_requires_review(app):
    with app.app_context():
        m=db.session.get(Mentor,1);db.session.add(MentorDetails(mentor=m,credentials_reviewed=True));db.session.commit()
    c=app.test_client();login(c,'mentor')
    r=c.post('/onboarding',data={'lane':'Healthcare','title':'Exam mentor','bio':'Practical study support for students preparing for exams.','experience':'Newly updated credentials and practical experience.','consent':'y'})
    assert r.status_code==302
    with app.app_context():
        m=db.session.get(Mentor,1);assert m.status=='submitted' and m.details.credentials_reviewed is False and m.details.profile_consent is True

def test_expired_invitation_is_rejected(app):
    from datetime import timedelta
    from app.models import now
    c=app.test_client();login(c,'admin');create(c);link=invite(c)
    with app.app_context():
        inv=MentorInvitation.query.one();inv.expires_at=now()-timedelta(seconds=1);db.session.commit()
    anon=app.test_client();assert anon.get(link).status_code==400
    assert anon.post(link,data={'password':'test-password-12345','confirm':'test-password-12345'}).status_code==400
