import re
import pytest
from app import create_app
from app.models import db, User, Mentor, Service, Booking
from werkzeug.security import generate_password_hash
@pytest.fixture
def app():
    app=create_app({'TESTING':True,'SECRET_KEY':'x'*40,'SQLALCHEMY_DATABASE_URI':'sqlite://','WTF_CSRF_ENABLED':False})
    with app.app_context():
        db.create_all()
        for name,role in [('Admin','admin'),('Mentor','mentor'),('Student','student'),('Other','student')]:
            db.session.add(User(name=name,email=name.lower()+'@example.com',role=role,password_hash=generate_password_hash('long-password-123')))
        db.session.flush()
        m=Mentor(user_id=2,lane='Healthcare',title='Exam mentor',bio='Practical study support for students preparing for exams.',experience='Ten years of mentoring experience.',status='approved')
        db.session.add(m);db.session.flush()
        db.session.add(Service(mentor_id=m.id,name='Exam prep',price_cents=10000,duration=60,fee_bps=1500));db.session.commit()
    yield app

def login(c,email):return c.post('/login',data={'email':email+'@example.com','password':'long-password-123'})
def payload(c):
    html=c.get('/book/1').text
    key=re.search(r'name="request_key"[^>]*value="([^"]+)"',html).group(1)
    slot=re.search(r'<option value="([^"]+)"',html).group(1)
    return {'request_key':key,'slot':slot,'acknowledge':'y','goals':'Study instruments'}

def test_booking_financial_snapshot_idempotency_cancel(app):
    c=app.test_client();login(c,'student');data=payload(c)
    r=c.post('/book/1',data=data);assert r.status_code==302
    assert c.post('/book/1',data=data).location==r.location
    with app.app_context():
        b=Booking.query.one();assert (b.price_cents,b.fee_cents,b.earnings_cents)==(10000,1500,8500)
        s=db.session.get(Service,1);s.price_cents=20000;db.session.commit();assert b.price_cents==10000
    assert c.get(r.location).status_code==200
    assert c.post('/bookings/1/cancel').status_code==302
    with app.app_context():assert Booking.query.one().slot_key is None

def test_access_boundaries(app):
    c=app.test_client();assert c.get('/admin').status_code==302
    login(c,'student');assert c.get('/admin').status_code==403
    assert c.post('/admin/mentors/1',data={'status':'approved'}).status_code==403
    c.post('/book/1',data=payload(c));c.post('/logout');login(c,'other')
    assert c.get('/bookings/1').status_code==403
    assert c.post('/bookings/1/cancel').status_code==403
    c.post('/logout');login(c,'mentor');assert c.get('/bookings/1').status_code==200
    assert c.get('/book/1').status_code==403

def test_slot_conflict_and_bad_slot(app):
    a=app.test_client();b=app.test_client();login(a,'student');login(b,'other')
    da=payload(a);dbb=payload(b);assert da['slot']==dbb['slot'];a.post('/book/1',data=da)
    assert b.post('/book/1',data=dbb).status_code==200
    with app.app_context():assert Booking.query.count()==1
    dbb['slot']='1900-01-01T12:00:00';b.post('/book/1',data=dbb)
    with app.app_context():assert Booking.query.count()==1

def test_apply_stays_in_existing_portal(app):
    c=app.test_client()
    assert c.get('/onboarding').location=='https://ttbg-mentor-portal.onrender.com/apply'
    login(c,'student')
    assert c.get('/onboarding').location=='https://ttbg-mentor-portal.onrender.com/apply'
    assert 'https://ttbg-mentor-portal.onrender.com/apply' in c.get('/').text

def test_registration_validation_and_role(app):
    c=app.test_client();data={'name':'New Student','email':'new@example.com','password':'long-password-123','confirm':'long-password-123','role':'admin'}
    assert c.post('/register',data=data).status_code==302
    with app.app_context():assert User.query.filter_by(email='new@example.com').one().role=='student'
    c.post('/logout');assert c.post('/register',data=data).status_code==200

def test_login_throttle(app):
    c=app.test_client()
    for _ in range(8):c.post('/login',data={'email':'student@example.com','password':'wrong'})
    assert c.post('/login',data={'email':'student@example.com','password':'wrong'}).status_code==429

def test_csrf_protected(app):
    app.config['WTF_CSRF_ENABLED']=True
    c=app.test_client();assert c.post('/register',data={}).status_code==400
    assert c.post('/logout').status_code==400

def test_browse_filter_and_pages(app):
    c=app.test_client();assert 'Exam mentor' in c.get('/?lane=Healthcare&q=Mentor').text
    assert 'No mentors in this view' in c.get('/?lane=Technology').text
    for path in ['/','/mentor/1','/login','/register','/health']:assert c.get(path).status_code==200
    login(c,'admin')
    for path in ['/admin','/admin/mentors/1','/admin/mentors/1/services/new','/admin/mentors/1/services/1']:assert c.get(path).status_code==200

def test_disabled_bookings(app):
    app.config['DEMO_BOOKING_ENABLED']=False
    c=app.test_client();login(c,'student');assert c.get('/book/1').status_code==403

def test_signin_preserves_only_safe_next(app):
    c=app.test_client()
    data={'email':'student@example.com','password':'long-password-123'}
    assert c.post('/login?next=/book/1',data=data).location=='/book/1'
    c.post('/logout')
    assert c.post('/login?next=https://example.org',data=data).location=='/dashboard'
