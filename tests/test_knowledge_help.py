import io
import pytest
from PIL import Image
from test_workflows import app,login,payload
from test_v03 import manager,picture,PW,identity
from test_v05 import delete
from app.models import db,User,KnowledgePage,KnowledgeImage,HelpSettings,Booking,Mentor,Service,PlatformAudit

PAGE={'title':'First steps','space':'Mentor guides','parent_id':'0','body':'# Welcome\n\nUse your dashboard.\n- Upload a picture\n- Ask for help'}
def create(c,**kw):
    data=dict(PAGE);data.update(kw);return c.post('/documentation/new',data=data)

def test_documentation_role_access_and_navigation(app):
    manager(app);admin=app.test_client();login(admin,'admin');assert create(admin).status_code==302
    for role in ('admin','other','mentor','student'):
        c=app.test_client();login(c,role)
        allowed=role!='student';edit=role in ('admin','other')
        r=c.get('/documentation');assert r.status_code==(200 if allowed else 403)
        assert ('href="/documentation"' in c.get('/dashboard',follow_redirects=True).text)==allowed
        assert c.get('/documentation/1').status_code==(200 if allowed else 403)
        assert c.get('/documentation/1/edit').status_code==(200 if edit else 403)
        assert c.get('/documentation/1/delete').status_code==(200 if edit else 403)
        if not edit:
            assert c.post('/documentation/1/edit',data=PAGE).status_code==403
            assert c.post('/documentation/1/delete',data={'version':'1'}).status_code==403
            assert c.post('/documentation/new',data=PAGE).status_code==403
        else:
            assert '>Edit</a>' in c.get('/documentation/1').text
    assert app.test_client().get('/documentation').status_code==302


def test_documentation_crud_search_hierarchy_and_escape(app):
    manager(app);c=app.test_client();login(c,'other')
    assert create(c,body='# Safety\n<script>alert(1)</script>\n- useful item').status_code==302
    assert create(c,title='Child page',parent_id='1').status_code==302
    assert create(c,title='Grandchild page',parent_id='2').status_code==302
    r=c.get('/documentation/1');assert '<script>alert(1)</script>' not in r.text and '&lt;script&gt;' in r.text
    assert '<h2>Safety</h2>' in r.text and '<li>useful item</li>' in r.text
    assert 'Search results' in c.get('/documentation?q=Safety').text
    assert 'No pages found' in c.get('/documentation?q=%25').text
    assert c.post('/documentation/1/edit',data=dict(PAGE,parent_id='3',version='1')).status_code==200
    with app.app_context():assert db.session.get(KnowledgePage,1).parent_id is None
    assert c.post('/documentation/2/edit',data=dict(PAGE,space='Wrong space',parent_id='1',version='1')).status_code==200
    assert c.post('/documentation/1/edit',data=dict(PAGE,title='Updated guide',version='1')).status_code==302
    assert c.post('/documentation/1/edit',data=dict(PAGE,title='Stale overwrite',version='1')).status_code==409
    assert c.post('/documentation/1/delete',data={'version':'1'}).status_code==409
    assert c.post('/documentation/1/delete',data={'version':'2'}).status_code==302
    with app.app_context():
        assert db.session.get(KnowledgePage,1) is None
        assert db.session.get(KnowledgePage,2).parent_id is None
        assert db.session.get(KnowledgePage,3).parent_id==2
    assert c.get('/documentation/1').status_code==404


def test_documentation_images_compressed_private_and_removed(app):
    c=app.test_client();login(c,'admin')
    raw=io.BytesIO();Image.new('RGB',(2400,1200),'navy').save(raw,'JPEG',comment=b'private camera metadata');raw.seek(0)
    assert create(c,image=(raw,'camera.jpg'),caption='An example workflow').status_code==302
    with app.app_context():
        image=KnowledgeImage.query.one();assert len(image.image)<=500_000 and b'private camera metadata' not in image.image
        decoded=Image.open(io.BytesIO(image.image));assert decoded.format=='WEBP' and decoded.size==(1600,800)
    mentor=app.test_client();login(mentor,'mentor');r=mentor.get('/documentation/images/1')
    assert r.status_code==200 and r.mimetype=='image/webp' and r.headers['Cache-Control']=='private, no-store'
    student=app.test_client();login(student,'student');assert student.get('/documentation/images/1').status_code==403
    assert app.test_client().get('/documentation/images/1').status_code==302
    assert mentor.post('/documentation/images/1/delete',data={'version':'1'}).status_code==403
    assert c.post('/documentation/images/1/delete',data={'version':'2'}).status_code==409
    assert c.post('/documentation/images/1/delete',data={'version':'1'}).status_code==302
    assert c.get('/documentation/images/1').status_code==404
    assert c.post('/documentation/1/edit',data=dict(PAGE,version='2',image=(picture(),'photo.png'),caption='Photo')).status_code==302
    assert c.post('/documentation/1/delete',data={'version':'3'}).status_code==302
    with app.app_context():assert KnowledgeImage.query.count()==0


@pytest.mark.parametrize('raw,caption',[(b'<svg onload="alert(1)"/>','Unsafe image'),(b'x'*(5*1024*1024+1),'Oversized')])
def test_documentation_rejects_invalid_images_without_creating_page(app,raw,caption):
    c=app.test_client();login(c,'admin')
    assert create(c,image=(io.BytesIO(raw),'image.png'),caption=caption).status_code==200
    with app.app_context():assert KnowledgePage.query.count()==0


def test_documentation_requires_caption_limits_images_and_csrf(app):
    c=app.test_client();login(c,'admin');assert create(c,image=(picture(),'photo.png')).status_code==200
    with app.app_context():assert KnowledgePage.query.count()==0
    create(c)
    with app.app_context():
        for _ in range(10):db.session.add(KnowledgeImage(page_id=1,caption='Existing',image=b'placeholder'))
        db.session.commit()
    assert c.post('/documentation/1/edit',data=dict(PAGE,version='1',image=(picture(),'photo.png'),caption='Eleventh image')).status_code==200
    with app.app_context():assert KnowledgeImage.query.count()==10 and db.session.get(KnowledgePage,1).version==1
    app.config['WTF_CSRF_ENABLED']=True
    assert create(c).status_code==400
    assert c.post('/documentation/1/delete',data={'version':'1'}).status_code==400
    assert c.post('/documentation/images/1/delete',data={'version':'1'}).status_code==400


def test_any_nonadmin_can_be_deleted_but_no_admin(app):
    c=app.test_client();login(c,'admin')
    with app.app_context():db.session.get(User,4).role='admin';db.session.commit()
    assert 'Delete account</a>' not in c.get('/support/accounts/4').text
    assert c.get('/admin/users/4/delete').status_code==403
    assert delete(c,4,'other@example.com').status_code==403
    with app.app_context():assert db.session.get(User,4) is not None
    assert 'Delete account</a>' in c.get('/support/accounts/3').text
    manager(app);staff=app.test_client();login(staff,'other')
    assert 'Delete account</a>' not in staff.get('/support/accounts/3').text
    create(staff)
    assert delete(c,4,'other@example.com').status_code==302
    with app.app_context():assert KnowledgePage.query.one().editor.role=='archive'
    assert 'Deleted account' in c.get('/documentation/1').text


def test_mentor_deletion_preserves_paid_booking_snapshots(app):
    student=app.test_client();login(student,'student');student.post('/book/1',data=payload(student))
    with app.app_context():
        b=Booking.query.one();b.payment_status='paid';b.status='confirmed';b.goals='Personal goals';db.session.commit()
        amounts=(b.price_cents,b.fee_cents,b.earnings_cents)
    c=app.test_client();login(c,'admin');assert delete(c,2,'mentor@example.com').status_code==302
    with app.app_context():
        assert db.session.get(User,2) is None and db.session.get(Mentor,1) is None and db.session.get(Service,1) is None
        b=Booking.query.one();assert b.mentor.user.role=='archive' and b.student_id==3 and not b.goals
        assert (b.price_cents,b.fee_cents,b.earnings_cents)==amounts and b.payment_status=='paid'
    assert 'Deleted account' in c.get('/support/bookings/1').text
    assert 'Deleted account' in student.get('/dashboard').text
    assert c.get('/admin?status=deleted').status_code==200
    assert 'Archived service' not in c.get('/admin?status=deleted').text
    assert delete(c,3,'student@example.com').status_code==302
    with app.app_context():assert Booking.query.one().student.role=='archive'


def test_help_settings_phone_roles_and_public_contact(app):
    c=app.test_client();login(c,'admin')
    data=identity(site_title='TTBG',description='Mentorship',support_email='help@example.com',registration_open='y',fee_percent='20',scheduling_provider='acuity',booking_mode='contact',help_enabled='y',help_phone='+12125550123')
    assert c.post('/admin/settings',data=data).status_code==302
    public=app.test_client();r=public.get('/')
    assert 'href="tel:+12125550123"' in r.text and 'not a live chat' in r.text
    assert 'href="/support"' not in r.text and 'href="/documentation"' not in r.text
    assert 'help.thetechnicalbridgegroup.com/tickets/new' in r.text
    assert c.post('/admin/settings',data=dict(data,help_phone='javascript:alert(1)')).status_code==200
    with app.app_context():assert db.session.get(HelpSettings,1).phone=='+12125550123'
    manager(app);staff=app.test_client();login(staff,'other');assert staff.post('/admin/settings',data=data).status_code==403
    data.pop('help_enabled');assert c.post('/admin/settings',data=data).status_code==302
    assert 'id="help-guide"' not in public.get('/').text


def test_upgrade_seeds_documentation_once_and_preserves_edits(app):
    from app.upgrade import upgrade
    with app.app_context():
        upgrade();assert KnowledgePage.query.count()==3
        page=KnowledgePage.query.first();page.body='Our edited guide';db.session.commit()
        upgrade();assert KnowledgePage.query.count()==3 and page.body=='Our edited guide'
