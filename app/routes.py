import secrets
from decimal import Decimal
from functools import wraps
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, current_app, session
from flask_login import login_user, logout_user, login_required, current_user
from sqlalchemy.exc import IntegrityError
from werkzeug.security import generate_password_hash, check_password_hash
from .models import db, User, Mentor, Service, Booking, LoginAttempt, MentorAudit, now
from .forms import LoginForm, RegisterForm, ProfileForm, ReviewForm, ServiceForm, BookingForm, EmptyForm, LANES
from .onboarding_logic import readiness, audit, details_for
from .security import account_enabled, sign_in, settings
from .models import AccountAccess
bp=Blueprint('main',__name__)

@bp.before_app_request
def block_inactive_mentor():
    if current_user.is_authenticated and current_user.mentor and current_user.mentor.status in ['suspended','deleted']:
        logout_user(); session.clear()
        flash('Your mentor account is unavailable. Contact the TTBG team.','error')
        return redirect(url_for('main.login'))

def after_login():
    target=request.args.get('next','')
    if target == '/onboarding' or (target.startswith('/book/') and target[6:].isdigit()) or (target.startswith('/availability/') and target[14:].isdigit()):
        return redirect(target)
    return redirect(url_for('main.dashboard'))

def roles(*allowed):
    def decorate(fn):
        @wraps(fn)
        @login_required
        def wrapped(*a,**kw):
            if current_user.role not in allowed: abort(403)
            return fn(*a,**kw)
        return wrapped
    return decorate

def test_slots(mentor):
    eastern=ZoneInfo('America/New_York')
    today=datetime.now(eastern).date()
    booked={b.start for b in Booking.query.filter_by(mentor_id=mentor.id,status='demo_reserved')}
    slots=[]
    for day in range(1,8):
        for hour in (10,14,18):
            local=datetime.combine(today+timedelta(days=day),datetime.min.time(),tzinfo=eastern).replace(hour=hour)
            utc=local.astimezone(timezone.utc).replace(tzinfo=None)
            if utc not in booked: slots.append((utc.isoformat(),local.strftime('%a, %b %d · %I:%M %p %Z')))
    return slots

@bp.route('/')
@bp.route('/tutoring')
def browse():
    lane=request.args.get('lane',''); q=request.args.get('q','').strip()[:100]
    mentors=Mentor.query.filter_by(status='approved',is_demo=False).outerjoin(AccountAccess,AccountAccess.user_id==Mentor.user_id).filter(db.or_(AccountAccess.enabled.is_(True),AccountAccess.user_id.is_(None)))
    if lane in LANES: mentors=mentors.filter(Mentor.lane==lane)
    if q: mentors=mentors.join(User,Mentor.user_id==User.id).filter(db.or_(User.name.ilike('%'+q+'%'),Mentor.title.ilike('%'+q+'%'),Mentor.bio.ilike('%'+q+'%')))
    return render_template('browse.html',mentors=[m for m in mentors.order_by(Mentor.id).all() if m.publicly_visible],lanes=LANES,lane=lane,q=q)

@bp.route('/mentor/<int:mid>')
def mentor(mid):
    m=db.get_or_404(Mentor,mid)
    if not m.publicly_visible: abort(404)
    return render_template('mentor.html',m=m)

@bp.route('/register',methods=['GET','POST'])
def register():
    if current_user.is_authenticated: return redirect(url_for('main.dashboard'))
    if not settings().registration_open:
        return render_template('registration_closed.html'),403
    from .registration_security import mail_ready,normalized_email,rate_allowed,verify_turnstile,notify_verification
    if not mail_ready():return render_template('registration_unavailable.html'),503
    form=RegisterForm()
    if request.method=='POST' and not rate_allowed('registration-ip',request.remote_addr or 'unknown',10,900):abort(429)
    if form.validate_on_submit():
        if not verify_turnstile('register'):
            form.email.errors.append('Complete the bot check and try again. If it expired, reload this page.')
        else:
            email=normalized_email(form.email.data)
            u=User(name=form.name.data.strip(),email=email,password_hash=generate_password_hash(form.password.data),role='student')
            db.session.add(u)
            try:db.session.commit()
            except IntegrityError:
                db.session.rollback();form.email.errors.append('An account already uses this email. Sign in to continue or verify it.')
            else:
                sign_in(u);notify_verification(u)
                return redirect(url_for('verification.notice'))
    return render_template('auth.html',form=form,register=True)

@bp.route('/login',methods=['GET','POST'])
def login():
    if current_user.is_authenticated: return redirect(url_for('main.dashboard'))
    form=LoginForm()
    if form.validate_on_submit():
        email=form.email.data.strip().lower()
        if LoginAttempt.query.filter(LoginAttempt.email==email,LoginAttempt.created_at>now()-timedelta(minutes=15)).count()>=8: abort(429)
        u=User.query.filter_by(email=email).first()
        if u and check_password_hash(u.password_hash,form.password.data) and account_enabled(u):
            LoginAttempt.query.filter_by(email=email).delete(); db.session.commit()
            sign_in(u)
            return after_login()
        db.session.add(LoginAttempt(email=email)); db.session.commit()
        form.password.errors.append('Email or password is incorrect.')
    return render_template('auth.html',form=form,register=False)

@bp.post('/logout')
@login_required
def logout():
    logout_user(); session.clear(); return redirect(url_for('main.browse'))

@bp.route('/onboarding',methods=['GET','POST'])
def onboarding():
    if not current_user.is_authenticated or not current_user.mentor:
        return redirect('https://ttbg-mentor-portal.onrender.com/apply')
    m=current_user.mentor
    form=ProfileForm(obj=m)
    if form.validate_on_submit():
        d=details_for(m)
        if m.experience != form.experience.data.strip():d.credentials_reviewed=False
        d.profile_consent=True
        for field in ('lane','title','bio','experience'): setattr(m,field,getattr(form,field).data.strip())
        audit(m,'Mentor profile resubmitted','Public profile returned to review.')
        m.status='submitted'; m.review_note=''; current_user.role='mentor'
        db.session.commit(); flash('Profile submitted. TTBG will review it before it appears in the directory.','success')
        return redirect(url_for('main.dashboard'))
    return render_template('onboarding.html',form=form,m=m)

@bp.route('/dashboard')
@login_required
def dashboard():
    if current_user.role in ['admin','account_manager','onboarding']: return redirect(url_for('main.admin'))
    m=current_user.mentor
    bookings=Booking.query.filter_by(mentor_id=m.id) if m else Booking.query.filter_by(student_id=current_user.id)
    from .models import AcuityRequest
    pending_requests=AcuityRequest.query.filter(AcuityRequest.user_id==current_user.id,AcuityRequest.state.in_(('creating','uncertain'))).order_by(AcuityRequest.created_at.desc()).all()
    return render_template('dashboard.html',m=m,bookings=bookings.order_by(Booking.start.desc()).all(),pending_requests=pending_requests)

@bp.route('/book/<int:sid>',methods=['GET','POST'])
@roles('student')
def book(sid):
    s=db.get_or_404(Service,sid)
    if not s.active or not s.mentor.publicly_visible: abort(404)
    # Simulated reservations are available only to explicitly configured tests.
    if not (current_app.testing and current_app.config['TEST_RESERVATIONS_ENABLED']):
        if request.method=='POST': abort(403)
        if settings().booking_mode in ('acuity','acuity_confirmed') and settings().scheduling_provider=='acuity':
            return redirect(url_for('acuity.availability',sid=s.id))
        return render_template('booking_unavailable.html',s=s)
    form=BookingForm(); form.slot.choices=test_slots(s.mentor)
    if request.method=='GET':
        form.request_key.data=secrets.token_hex(24)
        session['booking_key']=form.request_key.data
        session['booking_quote']={'service_id':s.id,'price_cents':s.price_cents}
    if request.method=='POST':
        existing=Booking.query.filter_by(request_key=form.request_key.data).first()
        if existing:
            if existing.student_id!=current_user.id: abort(403)
            return redirect(url_for('main.booking_detail',bid=existing.id))
    if form.validate_on_submit():
        if form.request_key.data!=session.get('booking_key'): abort(400)
        if session.get('booking_quote')!={'service_id':s.id,'price_cents':s.price_cents}:
            flash('The mentor updated this price. Please review the new total before reserving.','error')
            return redirect(url_for('main.book',sid=sid))
        start=datetime.fromisoformat(form.slot.data)
        fee=(s.price_cents*s.fee_bps+5000)//10000
        b=Booking(student_id=current_user.id,mentor_id=s.mentor_id,service_id=s.id,service_name=s.name,
            start=start,duration=s.duration,price_cents=s.price_cents,fee_cents=fee,earnings_cents=s.price_cents-fee,
            slot_key=f'{s.mentor_id}:{start.isoformat()}',request_key=form.request_key.data,goals=form.goals.data or '')
        db.session.add(b)
        try: db.session.commit()
        except IntegrityError:
            db.session.rollback(); flash('That time was just taken. Choose another time.','error')
            return redirect(url_for('main.book',sid=sid))
        return redirect(url_for('main.booking_detail',bid=b.id))
    return render_template('book.html',form=form,s=s)

@bp.route('/bookings/<int:bid>')
@login_required
def booking_detail(bid):
    b=db.get_or_404(Booking,bid)
    if current_user.role not in ['admin','account_manager','onboarding'] and current_user.id not in (b.student_id,b.mentor.user_id): abort(403)
    if b.acuity:
        from datetime import timezone
        from zoneinfo import ZoneInfo
        return render_template('appointments/detail.html',b=b,a=b.acuity,local_start=b.start.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(b.acuity.timezone)))
    return render_template('booking.html',b=b)

@bp.post('/bookings/<int:bid>/cancel')
@login_required
def cancel(bid):
    b=db.get_or_404(Booking,bid)
    if current_user.role not in ['admin','account_manager','onboarding'] and current_user.id not in (b.student_id,b.mentor.user_id): abort(403)
    if b.status=='demo_reserved' and b.payment_status=='not_charged':
        b.status='cancelled'; b.slot_key=None; db.session.commit(); flash('Archived test reservation cancelled. No charge was made.','success')
    return redirect(url_for('main.booking_detail',bid=bid))

@bp.route('/admin')
@roles('admin','account_manager','onboarding')
def admin():
    mentors=Mentor.query.filter(Mentor.user.has(User.role!='archive'))
    state=request.args.get('status','')
    if state:mentors=mentors.filter_by(status=state)
    else:mentors=mentors.filter(Mentor.status!='deleted')
    q=request.args.get('q','').strip()[:100]
    if q:mentors=mentors.join(User,Mentor.user_id==User.id).filter(db.or_(User.name.ilike('%'+q+'%'),User.email.ilike('%'+q+'%')))
    mentors=mentors.order_by(Mentor.created_at.desc()).all()
    bookings=Booking.query.order_by(Booking.created_at.desc()).all()
    return render_template('admin.html',mentors=mentors,bookings=bookings,q=q,state=state)

@bp.route('/admin/mentors/<int:mid>',methods=['GET','POST'])
@roles('admin','account_manager','onboarding')
def review(mid):
    m=db.get_or_404(Mentor,mid); form=ReviewForm(obj=m)
    if m.user.role=='archive':abort(404)
    if form.validate_on_submit():
        missing=[label for label,ok in readiness(m) if not ok]
        if m.status in ['deleted','suspended']:
            flash('Use Restore to draft before changing this profile’s review status.','error')
        elif form.status.data=='approved' and missing:
            flash('Before publishing, complete: '+', '.join(missing)+'.','error')
        else:
            old=m.status;m.status=form.status.data;m.review_note=form.review_note.data;m.acuity_calendar_id=form.acuity_calendar_id.data
            audit(m,'Review decision saved',f'{old} → {m.status}')
            db.session.commit();flash('Review saved.','success')
            return redirect(url_for('main.review',mid=mid))
    logs=MentorAudit.query.filter_by(mentor_id=mid).order_by(MentorAudit.created_at.desc(),MentorAudit.id.desc()).limit(50).all()
    return render_template('review.html',m=m,form=form,checklist=readiness(m),logs=logs)

@bp.route('/admin/mentors/<int:mid>/services/new',methods=['GET','POST'])
@bp.route('/admin/mentors/<int:mid>/services/<int:sid>',methods=['GET','POST'])
@roles('admin','account_manager','onboarding')
def service_edit(mid,sid=None):
    m=db.get_or_404(Mentor,mid); s=db.get_or_404(Service,sid) if sid else None
    if s and s.mentor_id!=mid: abort(404)
    if m.status in ['suspended','deleted']:abort(403)
    form=ServiceForm(obj=s)
    form.fee_percent.data=Decimal(settings().fee_bps)/100
    if request.method=='GET' and s:
        form.price.data=Decimal(s.price_cents)/100
    if form.validate_on_submit():
        if not s: s=Service(mentor_id=mid); db.session.add(s)
        for f in ('name','description','duration','acuity_type_id'): setattr(s,f,getattr(form,f).data)
        s.price_cents=int(form.price.data.quantize(Decimal('.01'))*100)
        s.fee_bps=settings().fee_bps
        audit(m,'Service saved',s.name+'; starting price can be changed by the mentor.')
        db.session.commit(); flash('Service saved.','success'); return redirect(url_for('main.review',mid=mid))
    return render_template('service.html',form=form,m=m,s=s)

@bp.post('/admin/services/<int:sid>/toggle')
@roles('admin','account_manager','onboarding')
def toggle_service(sid):
    s=db.get_or_404(Service,sid)
    if s.mentor.status in ['suspended','deleted']:abort(403)
    s.active=not s.active;audit(s.mentor,'Service visibility changed',s.name);db.session.commit()
    return redirect(url_for('main.review',mid=s.mentor_id))

@bp.get('/health')
def health(): return {'status':'ok','version':'0.7.0'}
