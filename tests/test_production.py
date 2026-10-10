import re
from test_workflows import app, login, payload
from app import create_app
from app.models import db, Mentor, User, Service, Booking


def test_normal_runtime_cannot_create_simulated_reservations(app, monkeypatch):
    monkeypatch.setenv('DEMO_BOOKING_ENABLED', 'true')
    normal = create_app({'SECRET_KEY': 'x'*40, 'SQLALCHEMY_DATABASE_URI': 'sqlite://'})
    assert normal.config['TEST_RESERVATIONS_ENABLED'] is False
    assert 'seed-demo' not in normal.cli.commands
    # Even an explicit simulation flag cannot bypass the normal-runtime gate.
    app.config.update(TESTING=False, TEST_RESERVATIONS_ENABLED=True)
    c=app.test_client();login(c,'student')
    response=c.get('/book/1')
    assert response.status_code==200
    assert 'Online scheduling and checkout are not available' in response.text
    assert 'name="slot"' not in response.text
    assert c.post('/book/1',data={}).status_code==403
    with app.app_context():assert Booking.query.count()==0


def test_fictional_profiles_hidden_without_deleting_data(app):
    with app.app_context():
        u=User(name='Fictional Person',email='fiction@example.com',password_hash='unused',role='mentor')
        db.session.add(u);db.session.flush()
        m=Mentor(user_id=u.id,lane='Healthcare',title='Fictional mentor',bio='Fixture',experience='Fixture',status='approved',is_demo=True)
        db.session.add(m);db.session.flush()
        db.session.add(Service(mentor_id=m.id,name='Fictional service',price_cents=10000,duration=60));db.session.commit()
        mid=m.id
    c=app.test_client()
    assert 'Fictional Person' not in c.get('/').text
    assert c.get(f'/mentor/{mid}').status_code==404
    login(c,'student');assert c.get('/book/2').status_code==404
    c.post('/logout');login(c,'admin')
    html=c.get('/admin').text
    assert 'Fictional Person' in html
    assert 'Published mentors</span><strong>1</strong>' in html
    assert c.get(f'/admin/mentors/{mid}').status_code==200
    with app.app_context():assert Mentor.query.count()==2


def test_production_copy_and_archived_records(app):
    c=app.test_client()
    for path in ['/', '/login', '/register', '/mentor/1', '/health']:
        response=c.get(path);assert response.status_code==200
        assert not re.search(r'beta|demo',response.text,re.I)
    login(c,'student');c.post('/book/1',data=payload(c))
    app.config.update(TESTING=False)
    for path in ['/dashboard','/bookings/1']:
        response=c.get(path);assert response.status_code==200
        assert 'Archived test' in response.text
        assert not re.search(r'beta|demo',response.text,re.I)
    c.post('/logout');login(c,'admin')
    for path in ['/admin','/admin/mentors/1','/admin/mentors/1/edit','/admin/mentors/1/lifecycle','/admin/mentors/1/preview']:
        response=c.get(path);assert response.status_code==200
        assert not re.search(r'beta|demo',response.text,re.I)
    html=c.get('/admin').text
    assert 'Estimated TTBG share' not in html
    assert 'session value' not in html
    with app.app_context():assert Booking.query.count()==1
