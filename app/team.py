import hashlib
import secrets
from datetime import timedelta
from decimal import Decimal
from flask import Blueprint, render_template, redirect, url_for, request, flash, abort, session, current_app
from flask_login import current_user, login_user, logout_user
from werkzeug.security import generate_password_hash
from sqlalchemy.exc import IntegrityError
from .routes import roles
from .models import db, User, Mentor, Service, Booking, MentorDetails, MentorInvitation, MentorAudit, now
from .forms import AdminProfileForm, LifecycleForm, ActivateForm, MentorPriceForm, PROFILE_CHECKS
from .onboarding_logic import details_for, audit, readiness
bp=Blueprint('team',__name__)
DETAIL_FIELDS=['phone','timezone','specialties','languages','years_experience','education','session_approach','application_reference','internal_notes']+PROFILE_CHECKS

def owner_choices(form):
    form.owner_id.choices=[(0,'Unassigned')]+[(u.id,u.name) for u in User.query.filter(User.role.in_(['admin','onboarding'])).order_by(User.name)]

@bp.route('/admin/mentors/new',methods=['GET','POST'])
@bp.route('/admin/mentors/<int:mid>/edit',methods=['GET','POST'])
@roles('admin','onboarding')
def profile_edit(mid=None):
    m=db.get_or_404(Mentor,mid) if mid else None
    if m and m.status=='deleted':
        flash('Restore this profile to draft before editing it.','error');return redirect(url_for('main.review',mid=mid))
    form=AdminProfileForm();owner_choices(form)
    if request.method=='GET' and m:
        form.name.data=m.user.name;form.email.data=m.user.email
        for f in ('lane','title','bio','experience','acuity_calendar_id'):getattr(form,f).data=getattr(m,f)
        if m.details:
            for f in DETAIL_FIELDS:getattr(form,f).data=getattr(m.details,f)
            form.owner_id.data=m.details.owner_id or 0
    if form.validate_on_submit():
        email=form.email.data.strip().lower()
        existing=User.query.filter_by(email=email).first()
        if m and existing and existing.id!=m.user_id:
            form.email.errors.append('This email belongs to another account.')
        elif not m and existing and (existing.role!='student' or existing.mentor):
            form.email.errors.append('This account already has a mentor or staff role. Open its existing profile instead.')
        elif not m and existing and not form.confirm_link.data:
            form.confirm_link.errors.append('Confirm the applicant’s identity before linking an existing student account.')
        else:
            creating=m is None
            if creating:
                u=existing or User(email=email,name=form.name.data.strip(),role='mentor',password_hash=generate_password_hash(secrets.token_urlsafe(48)))
                u.role='mentor';db.session.add(u);db.session.flush()
                m=Mentor(user_id=u.id,lane=form.lane.data,title=form.title.data.strip(),bio='',experience='',status='draft')
                db.session.add(m);db.session.flush()
                d=MentorDetails(mentor=m,activated_at=now() if existing else None);db.session.add(d)
            else:d=details_for(m)
            old_email=m.user.email
            m.user.name=form.name.data.strip();m.user.email=email
            for f in ('lane','title','bio','experience','acuity_calendar_id'):setattr(m,f,(getattr(form,f).data or '').strip())
            for f in DETAIL_FIELDS:
                value=getattr(form,f).data
                setattr(d,f,value.strip() if isinstance(value,str) else value)
            d.owner_id=form.owner_id.data or None
            if not creating and old_email!=email:
                MentorInvitation.query.filter_by(mentor_id=m.id).delete()
            # Published profiles with removed readiness requirements return to review.
            db.session.flush()
            if m.status=='approved' and not all(ok for _,ok in readiness(m)):m.status='reviewing'
            audit(m,'Profile created' if creating else 'Profile updated','Admin-managed profile and onboarding details saved.')
            try:db.session.commit()
            except IntegrityError:
                db.session.rollback();form.email.errors.append('That email was just registered elsewhere. Reload and try again.')
            else:
                flash('Draft profile created. Add services, finish the checklist, and prepare account access.' if creating else 'Profile updated.','success')
                return redirect(url_for('main.review',mid=m.id))
    return render_template('profile_edit.html',form=form,m=m,checks=PROFILE_CHECKS)

@bp.route('/admin/mentors/<int:mid>/lifecycle',methods=['GET','POST'])
@roles('admin','onboarding')
def lifecycle(mid):
    m=db.get_or_404(Mentor,mid);form=LifecycleForm()
    if request.method=='GET':
        action=request.args.get('action','suspend')
        form.action.data=action if action in ['suspend','delete','restore'] else 'suspend'
    if form.validate_on_submit():
        if form.confirm_name.data.strip()!=m.user.name:
            form.confirm_name.errors.append('The name does not match.')
        else:
            action=form.action.data
            if (action=='restore' and m.status not in ['deleted','suspended']) or (action=='suspend' and m.status=='deleted'):abort(400)
            old=m.status;m.status={'suspend':'suspended','delete':'deleted','restore':'draft'}[action]
            MentorInvitation.query.filter_by(mentor_id=mid).delete()
            audit(m,'Profile '+m.status,form.reason.data.strip()+f' (previous status: {old})')
            db.session.commit()
            flash('Profile removed from the directory. Account access is blocked; session history is retained.' if action=='delete' else 'Profile suspended; new bookings and account access are blocked. Existing reservations are unchanged.' if action=='suspend' else 'Profile restored to draft. Review it before publishing.','success')
            return redirect(url_for('main.review',mid=mid))
    active=Booking.query.filter_by(mentor_id=mid,status='demo_reserved').count()
    return render_template('lifecycle.html',m=m,form=form,active=active)

@bp.post('/admin/mentors/<int:mid>/invite')
@roles('admin','onboarding')
def invite(mid):
    m=db.get_or_404(Mentor,mid)
    if m.status in ['deleted','suspended']:abort(403)
    d=details_for(m)
    if d.activated_at:
        flash('This mentor already has account access. They should sign in with their existing password.','error')
        return redirect(url_for('main.review',mid=mid))
    token=secrets.token_urlsafe(32)
    inv=MentorInvitation.query.filter_by(mentor_id=mid).first()
    if not inv:inv=MentorInvitation(mentor_id=mid);db.session.add(inv)
    inv.token_hash=hashlib.sha256(token.encode()).hexdigest();inv.expires_at=now()+timedelta(days=7);inv.used_at=None
    audit(m,'Activation link generated','Expires in seven days; earlier links are revoked.')
    db.session.commit()
    # Render once; tokens are not stored in session cookies or database plaintext.
    base=current_app.config.get('PUBLIC_BASE_URL') or request.url_root.rstrip('/')
    link=base.rstrip('/')+url_for('team.activate',token=token)
    return render_template('invite.html',m=m,link=link)

@bp.route('/activate/<token>',methods=['GET','POST'])
def activate(token):
    token_hash=hashlib.sha256(token.encode()).hexdigest()
    inv=MentorInvitation.query.filter_by(token_hash=token_hash).first()
    m=db.session.get(Mentor,inv.mentor_id) if inv else None
    valid=inv and not inv.used_at and inv.expires_at>now() and m and m.status not in ['deleted','suspended']
    if not valid:return render_template('activation_expired.html'),400
    form=ActivateForm()
    if form.validate_on_submit():
        # Atomic token consumption prevents concurrent reuse.
        count=MentorInvitation.query.filter_by(id=inv.id,used_at=None).filter(MentorInvitation.expires_at>now()).update({'used_at':now()},synchronize_session=False)
        if count!=1:db.session.rollback();return render_template('activation_expired.html'),400
        m.user.password_hash=generate_password_hash(form.password.data)
        d=details_for(m);d.activated_at=now()
        db.session.add(MentorAudit(mentor_id=m.id,actor_id=m.user_id,action='Account activated',detail='Mentor chose their own password.'))
        db.session.commit();logout_user();session.clear();login_user(m.user);session.permanent=True
        flash('Your account is ready. You can review your profile and set your prices.','success')
        return redirect(url_for('main.dashboard'))
    return render_template('activate.html',m=m,form=form)

@bp.route('/mentor/services/<int:sid>/price',methods=['GET','POST'])
@roles('mentor')
def price(sid):
    s=db.get_or_404(Service,sid)
    if s.mentor.user_id!=current_user.id:abort(403)
    if s.mentor.status in ['suspended','deleted']:abort(403)
    form=MentorPriceForm()
    if request.method=='GET':form.price.data=Decimal(s.price_cents)/100
    if form.validate_on_submit():
        old=s.price_cents;s.price_cents=int(form.price.data.quantize(Decimal('.01'))*100)
        audit(s.mentor,'Mentor price updated',f'{s.name}: ${old/100:.2f} → ${s.price_cents/100:.2f}. Existing reservations unchanged.')
        db.session.commit();flash('Your new price is saved. Existing reservations keep their original price.','success')
        return redirect(url_for('main.dashboard'))
    return render_template('price.html',s=s,form=form)

@bp.get('/admin/mentors/<int:mid>/preview')
@roles('admin','onboarding')
def preview(mid):
    m=db.get_or_404(Mentor,mid)
    return render_template('mentor.html',m=m,preview=True)
