import csv
import hashlib
import io
import math
import os
import platform
import shutil
import sys
from datetime import timedelta
from importlib.metadata import version
from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for, make_response
from flask_login import current_user, logout_user
from sqlalchemy import select, func, or_
from sqlalchemy.exc import IntegrityError
from werkzeug.security import generate_password_hash, check_password_hash
import secrets
from .models import (db, User, Mentor, Service, Booking, AccountAccess, PasswordLink, PlatformAudit,
                     PlatformSettings, PhotoSubmission, MentorIntegration, ServiceScheduling, now)
from .routes import roles
from .security import (settings, access_for, account_enabled, invalidate, sign_in, password_link, log, ROLE_LABELS)
from .forms import ActivateForm
from .control_forms import CreateUserForm, EditUserForm, ConfirmAdmin, SettingsForm, IntegrationForm, SchedulingForm
from .booking_config import validate_booking_url, split_amount

bp=Blueprint('control',__name__)

def confirmed(form):
    if not check_password_hash(current_user.password_hash,form.admin_password.data or ''):
        form.admin_password.errors.append('Your admin password is incorrect.')
        return False
    return True

def lock_identity():
    settings()
    db.session.execute(select(PlatformSettings).where(PlatformSettings.id==1).with_for_update()).scalar_one()
    db.session.refresh(current_user._get_current_object())
    if current_user.role!='admin' or not account_enabled(current_user):abort(403)

@bp.get('/admin/control')
@roles('admin')
def overview():
    counts={t.name:db.session.scalar(select(func.count()).select_from(t)) for t in db.metadata.sorted_tables}
    roles_count=dict(db.session.query(User.role,func.count(User.id)).group_by(User.role).all())
    states=dict(db.session.query(Mentor.status,func.count(Mentor.id)).filter_by(is_demo=False).group_by(Mentor.status).all())
    recent=User.query.filter(User.created_at>=now()-timedelta(days=30)).count()
    published=Mentor.query.filter_by(status='approved',is_demo=False).outerjoin(AccountAccess,AccountAccess.user_id==Mentor.user_id).filter(or_(AccountAccess.enabled.is_(True),AccountAccess.user_id.is_(None))).count()
    return render_template('control.html',counts=counts,role_counts=roles_count,states=states,recent=recent,published=published,pending=PhotoSubmission.query.filter_by(status='pending').count())

@bp.get('/admin/users')
@roles('admin')
def users():
    q=request.args.get('q','').strip()[:100]
    role=request.args.get('role','')
    query=User.query
    if q:query=query.filter(or_(User.name.ilike('%'+q+'%'),User.email.ilike('%'+q+'%')))
    if role in ROLE_LABELS:query=query.filter_by(role=role)
    page=query.order_by(User.id).paginate(page=request.args.get('page',1,type=int),per_page=30,error_out=False)
    return render_template('users.html',page=page,q=q,role=role)

@bp.route('/admin/users/new',methods=['GET','POST'])
@roles('admin')
def create_user():
    form=CreateUserForm()
    if form.validate_on_submit() and confirmed(form):
        email=form.email.data.strip().lower()
        if User.query.filter_by(email=email).first():form.email.errors.append('An account with that email already exists.')
        else:
            u=User(name=form.name.data.strip(),email=email,role=form.role.data,password_hash=generate_password_hash(secrets.token_urlsafe(48)))
            db.session.add(u)
            try:
                db.session.flush();log('Account created',f'user:{u.id}',ROLE_LABELS[u.role]+': '+form.reason.data.strip())
                link=password_link(u,'setup')
            except IntegrityError:
                db.session.rollback();form.email.errors.append('This email was just registered. Choose the existing account.')
            else:return render_template('password_link.html',u=u,link=link,purpose='Account setup')
    return render_template('user_edit.html',form=form,u=None)

@bp.route('/admin/users/<int:uid>',methods=['GET','POST'])
@roles('admin')
def edit_user(uid):
    u=db.get_or_404(User,uid);form=EditUserForm()
    form.role.choices=[(r,ROLE_LABELS[r]) for r in ('student','mentor','account_manager','admin')]
    if request.method=='GET':
        form.name.data=u.name;form.email.data=u.email;form.role.data='account_manager' if u.role=='onboarding' else u.role
        form.enabled.data=not u.access or u.access.enabled
    if form.validate_on_submit() and confirmed(form):
        lock_identity()
        old_role=u.role
        new_role=form.role.data;email=form.email.data.strip().lower()
        if u.id==current_user.id and (new_role!='admin' or not form.enabled.data):
            form.role.errors.append('You cannot disable or demote your own admin account.')
        elif (u.mentor and new_role!='mentor') or (not u.mentor and new_role=='mentor'):
            form.role.errors.append('Mentor roles are managed through mentor profiles. Keep this account’s mentor role or create a mentor profile first.')
        elif User.query.filter(User.email==email,User.id!=uid).first():form.email.errors.append('That email is already in use.')
        else:
            active_admins=User.query.outerjoin(AccountAccess).filter(User.role=='admin',or_(AccountAccess.enabled.is_(True),AccountAccess.user_id.is_(None))).count()
            if u.role=='admin' and account_enabled(u) and (new_role!='admin' or not form.enabled.data) and active_admins<=1:
                form.role.errors.append('The platform must retain an enabled admin.')
            else:
                u.name=form.name.data.strip();u.email=email;u.role=new_role
                access_for(u).enabled=form.enabled.data;invalidate(u)
                log('Account updated',f'user:{uid}',f'Role {old_role} → {new_role}; enabled={form.enabled.data}. '+form.reason.data.strip())
                try:db.session.commit()
                except IntegrityError:db.session.rollback();form.email.errors.append('That email was just registered elsewhere.')
                else:
                    if uid==current_user.id:session['auth_version']=access_for(u).session_version
                    flash('Account updated. Previous sessions and unused setup links were revoked.','success')
                    return redirect(url_for('control.edit_user',uid=uid))
    return render_template('user_edit.html',u=u,form=form)

@bp.route('/admin/users/<int:uid>/password',methods=['GET','POST'])
@roles('admin')
def reset_user(uid):
    u=db.get_or_404(User,uid);form=ConfirmAdmin()
    if form.validate_on_submit() and confirmed(form):
        if not account_enabled(u):form.reason.errors.append('Enable the account and restore any suspended mentor profile before issuing a link.')
        else:
            log('Password reset requested',f'user:{uid}',form.reason.data.strip())
            link=password_link(u)
            if uid==current_user.id:session['auth_version']=access_for(u).session_version
            return render_template('password_link.html',u=u,link=link,purpose='Password reset')
    return render_template('confirm_action.html',form=form,title='Reset password',description=f'Create a one-time password reset link for {u.name}. The user chooses their new password. Existing sessions and older links are revoked.')

@bp.post('/admin/users/<int:uid>/revoke-sessions')
@roles('admin')
def revoke_sessions(uid):
    u=db.get_or_404(User,uid);form=ConfirmAdmin()
    if not form.validate_on_submit() or not confirmed(form):abort(400)
    invalidate(u);log('Sessions revoked',f'user:{uid}',form.reason.data.strip());db.session.commit()
    if uid==current_user.id:logout_user();session.clear()
    flash('Sessions and unused reset links revoked.','success')
    return redirect(url_for('control.users'))

@bp.route('/reset-password/<token>',methods=['GET','POST'])
def password_reset(token):
    digest=hashlib.sha256(token.encode()).hexdigest()
    link=PasswordLink.query.filter_by(token_hash=digest).first()
    u=db.session.get(User,link.user_id) if link else None
    if not link or link.used_at or link.expires_at<=now() or not u or not account_enabled(u):
        return render_template('reset_password.html',form=None),400
    form=ActivateForm()
    if form.validate_on_submit():
        count=PasswordLink.query.filter_by(user_id=u.id,token_hash=digest,used_at=None).filter(PasswordLink.expires_at>now()).update({'used_at':now()},synchronize_session=False)
        if count!=1:db.session.rollback();return render_template('reset_password.html',form=None),400
        u.password_hash=generate_password_hash(form.password.data)
        invalidate(u)
        if u.mentor:
            from .onboarding_logic import details_for
            details_for(u.mentor).activated_at=now()
        log('Password changed',f'user:{u.id}','One-time link consumed.',actor_id=u.id)
        db.session.commit();sign_in(u)
        flash('Your password has been saved.','success');return redirect(url_for('main.dashboard'))
    return render_template('reset_password.html',form=form)

@bp.route('/admin/settings',methods=['GET','POST'])
@roles('admin')
def platform_settings():
    cfg=settings();form=SettingsForm(obj=cfg)
    if request.method=='GET':form.fee_percent.data=cfg.fee_bps/100
    if form.validate_on_submit() and confirmed(form):
        if form.booking_mode.data=='acuity' and form.scheduling_provider.data!='acuity':
            form.scheduling_provider.errors.append('Choose Acuity Scheduling for native availability.')
        elif form.booking_mode.data=='external' and form.scheduling_provider.data=='unselected':
            form.scheduling_provider.errors.append('Select a provider before enabling hosted booking links.')
        else:
            before=f'share={cfg.fee_bps}; provider={cfg.scheduling_provider}; mode={cfg.booking_mode}; maintenance={cfg.maintenance_mode}'
            for key in ('site_title','description','support_email','registration_open','maintenance_mode','scheduling_provider','booking_mode'):
                setattr(cfg,key,getattr(form,key).data)
            cfg.fee_bps=int(form.fee_percent.data*100)
            Service.query.update({'fee_bps':cfg.fee_bps})
            log('Platform settings updated','platform',before+f' → share={cfg.fee_bps}; provider={cfg.scheduling_provider}; mode={cfg.booking_mode}; maintenance={cfg.maintenance_mode}. '+form.reason.data.strip())
            db.session.commit();flash('Settings saved. Commission applies to future sessions; existing booking snapshots are unchanged.','success')
            return redirect(url_for('control.platform_settings'))
    return render_template('settings.html',form=form,cfg=cfg,example=split_amount(10000,cfg.fee_bps))

@bp.route('/admin/services/<int:sid>/scheduling',methods=['GET','POST'])
@roles('admin','account_manager','onboarding')
def service_scheduling(sid):
    s=db.get_or_404(Service,sid)
    if s.mentor.status in ('suspended','deleted'):abort(403)
    form=SchedulingForm(obj=s.scheduling)
    if form.validate_on_submit():
        value=(form.booking_url.data or '').strip()
        if form.provider.data=='acuity' and form.event_type_id.data and (not form.event_type_id.data.strip().isdigit() or len(form.event_type_id.data.strip())>20 or int(form.event_type_id.data.strip())<=0):
            form.event_type_id.errors.append('Use a positive numeric Acuity appointment type ID, up to 20 digits.')
        elif not validate_booking_url(form.provider.data,value):form.booking_url.errors.append('Use an HTTPS booking URL on the selected provider’s domain (Acuity/as.me, Cal.com, or Calendly).')
        else:
            item=s.scheduling or ServiceScheduling(service=s);db.session.add(item)
            item.provider=form.provider.data;item.event_type_id=(form.event_type_id.data or '').strip();item.booking_url=value
            log('Scheduling mapping updated',f'service:{sid}',f'Provider: {item.provider}');db.session.commit()
            flash('Scheduling mapping saved. Acuity availability uses the appointment type and mentor calendar IDs. Appointment and payment synchronization are not enabled.','success')
            return redirect(url_for('main.review',mid=s.mentor_id))
    return render_template('scheduling.html',form=form,s=s)

@bp.route('/admin/mentors/<int:mid>/integration',methods=['GET','POST'])
@roles('admin')
def mentor_integration(mid):
    m=db.get_or_404(Mentor,mid);form=IntegrationForm(obj=m.integration)
    if form.validate_on_submit() and confirmed(form):
        item=m.integration or MentorIntegration(mentor=m);db.session.add(item)
        item.provider_user_id=(form.provider_user_id.data or '').strip();item.stripe_account_id=(form.stripe_account_id.data or '').strip()
        log('Mentor integration references updated',f'mentor:{mid}',form.reason.data.strip());db.session.commit()
        flash('References saved. Account verification and automated payments require a connected integration.','success')
        return redirect(url_for('control.mentor_integration',mid=mid))
    return render_template('integration.html',form=form,m=m)

@bp.get('/admin/audit')
@roles('admin')
def audit_log():
    page=PlatformAudit.query.order_by(PlatformAudit.id.desc()).paginate(page=request.args.get('page',1,type=int),per_page=50,error_out=False)
    return render_template('audit.html',page=page)

REDACTED={'password_hash','token_hash','image'}
def display_value(key,value):
    if key in REDACTED:return '[redacted]' if value is not None else ''
    if value is None:return ''
    if isinstance(value,bytes):return f'[binary: {len(value)} bytes]'
    return str(value)

@bp.get('/admin/data')
@roles('admin')
def data():
    tables={t.name:t for t in db.metadata.sorted_tables}
    name=request.args.get('table','market_user')
    if name not in tables:abort(404)
    table=tables[name];page=max(1,request.args.get('page',1,type=int));size=50
    count=db.session.scalar(select(func.count()).select_from(table))
    # Do not fetch hashes, reset tokens, or image bytes from the database at all.
    cols=[c for c in table.columns if c.name not in REDACTED]
    query=select(*cols).order_by(*table.primary_key.columns).offset((page-1)*size).limit(size)
    rows=[{c.name:display_value(c.name,row[c.name]) for c in cols} for row in db.session.execute(query).mappings()]
    if request.args.get('format')=='csv':
        out=io.StringIO();writer=csv.writer(out);writer.writerow([c.name for c in cols])
        for row in rows:
            writer.writerow([("'"+v if v.startswith(('=','+','-','@','\t','\r','\n')) else v) for v in row.values()])
        log('Database page exported',name,f'Page {page}; {len(rows)} records.');db.session.commit()
        response=make_response(out.getvalue());response.mimetype='text/csv';response.headers['Content-Disposition']=f'attachment; filename="{name}-page-{page}.csv"';response.headers['Cache-Control']='no-store';return response
    return render_template('data.html',tables=tables,name=name,rows=rows,columns=cols,count=count,page=page,pages=max(1,math.ceil(count/size)),redacted=[c.name for c in table.columns if c.name in REDACTED])

@bp.get('/admin/resources')
@roles('admin')
def resources():
    from flask import current_app
    usage=shutil.disk_usage(current_app.instance_path if os.path.isdir(current_app.instance_path) else current_app.root_path)
    try:db.session.execute(select(1));database='Reachable'
    except Exception:db.session.rollback();database='Unavailable'
    info={'Release':'0.4.1','Python':platform.python_version(),'Flask':version('flask'),'Database engine':db.engine.dialect.name,'Database connection':database,'Runtime disk free':f'{usage.free/(1024**3):.1f} GiB','Runtime disk total':f'{usage.total/(1024**3):.1f} GiB','Photo storage':'Database (included in database backups)','Session cookies secure':str(current_app.config['SESSION_COOKIE_SECURE']),'Scheduling API':'Acuity read-only availability; verify in Support Center','Payment processing':'Not connected'}
    return render_template('resources.html',info=info)
