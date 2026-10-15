"""Staff-only support tools. No credentials or raw exception messages enter diagnostics."""
from datetime import timedelta
import secrets
from flask import Blueprint, abort, current_app, flash, g, jsonify, redirect, render_template, request, session, url_for
from flask_login import current_user, logout_user
from flask_wtf import FlaskForm
from wtforms import PasswordField, TextAreaField, SelectField, StringField
from wtforms.validators import DataRequired, Length
from sqlalchemy import or_
from werkzeug.security import check_password_hash
from .models import (db, User, Mentor, Booking, LoginAttempt, MentorAudit, PlatformAudit,
                     SupportNote, SupportIncident, SensitiveAttempt, now)
from .routes import roles
from .security import account_enabled, invalidate, log, password_link, settings

bp=Blueprint('support',__name__,url_prefix='/support')
staff=roles('admin','account_manager')
# An explicit allowlist: never enumerate arbitrary environment variables or expose the app signing key.
CREDENTIALS={'acuity':('Acuity API key','ACUITY_API_KEY'),
             'acuity_webhook':('Acuity static webhook signing key','ACUITY_WEBHOOK_SECRET'),
             'stripe':('Stripe secret key','STRIPE_SECRET_KEY'),
             'stripe_webhook':('Stripe platform webhook signing secret','STRIPE_WEBHOOK_SECRET'),
             'stripe_connect_webhook':('Stripe connected-account webhook signing secret','STRIPE_CONNECT_WEBHOOK_SECRET'),
             'turnstile':('Turnstile secret key','TURNSTILE_SECRET_KEY')}

class NoteForm(FlaskForm):
    body=TextAreaField('Internal note',validators=[DataRequired(),Length(min=3,max=2000)])
class RecoveryForm(FlaskForm):
    action=SelectField('Support action',choices=[('reset','Create password reset link'),('revoke','Sign out all sessions')])
    password=PasswordField('Your password',validators=[DataRequired(),Length(max=128)])
    reason=StringField('Reason for this action',validators=[DataRequired(),Length(min=3,max=300)])
class RevealForm(FlaskForm):
    password=PasswordField('Your admin password',validators=[DataRequired(),Length(max=128)])
class ResolveForm(FlaskForm):
    resolution=TextAreaField('Resolution notes',validators=[DataRequired(),Length(min=3,max=500)])

def reauthenticate(password,target):
    cutoff=now()-timedelta(minutes=15)
    if SensitiveAttempt.query.filter(SensitiveAttempt.user_id==current_user.id,SensitiveAttempt.created_at>cutoff).count()>=5:
        abort(429)
    if not check_password_hash(current_user.password_hash,password):
        db.session.add(SensitiveAttempt(user_id=current_user.id))
        log('Support verification failed',target,'Password confirmation failed; no action taken.')
        db.session.commit()
        return False
    # Prune only this account's expired attempt records. Success never clears recent failures.
    SensitiveAttempt.query.filter(SensitiveAttempt.user_id==current_user.id,SensitiveAttempt.created_at<=cutoff).delete()
    return True

def paginate(query):
    return query.paginate(page=max(1,request.args.get('page',1,type=int)),per_page=25,error_out=False)

@bp.get('')
@staff
def home():
    q=request.args.get('q','').strip()[:100];role=request.args.get('role','')
    query=User.query.filter(User.role!='archive')
    if q:
        conditions=[User.name.icontains(q,autoescape=True),User.email.icontains(q,autoescape=True)]
        if q.isdigit() and len(q)<10:conditions.append(User.id==int(q))
        query=query.filter(or_(*conditions))
    if role in ('student','mentor','account_manager','admin'):query=query.filter_by(role=role)
    page=paginate(query.order_by(User.id.desc()))
    return render_template('support/home.html',page=page,q=q,role=role,
        total=User.query.filter(User.role!='archive').count(),open_errors=SupportIncident.query.filter_by(status='open').count(),
        recent_logins=LoginAttempt.query.filter(LoginAttempt.created_at>now()-timedelta(minutes=15)).count())

@bp.route('/accounts/<int:uid>',methods=['GET','POST'])
@staff
def account(uid):
    u=db.get_or_404(User,uid);form=NoteForm()
    if u.role=='archive':abort(404)
    if form.validate_on_submit():
        body=form.body.data.strip()
        if len(body)<3:form.body.errors.append('Enter at least three non-space characters.')
        else:
            db.session.add(SupportNote(user_id=uid,author_id=current_user.id,body=body))
            log('Support note added',f'user:{uid}','Internal note recorded.')
            db.session.commit();flash('Internal note saved.','success')
            return redirect(url_for('support.account',uid=uid)+'#notes')
    targets=[f'user:{uid}']
    if u.mentor:targets.append(f'mentor:{u.mentor.id}')
    events=[{'when':e.created_at,'action':e.action,'detail':e.detail,'actor':e.actor.name if e.actor else 'System'}
            for e in PlatformAudit.query.filter(PlatformAudit.target.in_(targets)).order_by(PlatformAudit.id.desc()).limit(50)]
    if u.mentor:
        events += [{'when':e.created_at,'action':e.action,'detail':e.detail,'actor':e.actor.name if e.actor else 'System'}
                   for e in MentorAudit.query.filter_by(mentor_id=u.mentor.id).order_by(MentorAudit.id.desc()).limit(50)]
    events.append({'when':u.created_at,'action':'Account created','detail':'','actor':'System'})
    if u.access and u.access.last_login_at:events.append({'when':u.access.last_login_at,'action':'Most recent sign-in','detail':'','actor':u.name})
    events=sorted(events,key=lambda x:x['when'],reverse=True)[:50]
    query=Booking.query.filter(or_(Booking.student_id==uid,Booking.mentor_id==u.mentor.id)) if u.mentor else Booking.query.filter_by(student_id=uid)
    return render_template('support/account.html',u=u,form=form,events=events,enabled=account_enabled(u),
        can_recover=current_user.role=='admin' or u.role in ('student','mentor'),
        failed_logins=LoginAttempt.query.filter(LoginAttempt.email==u.email,LoginAttempt.created_at>now()-timedelta(minutes=15)).count(),
        notes=paginate(SupportNote.query.filter_by(user_id=uid).order_by(SupportNote.id.desc())),
        bookings=query.order_by(Booking.created_at.desc()).limit(10).all(),
        incidents=SupportIncident.query.filter_by(user_id=uid).order_by(SupportIncident.id.desc()).limit(10).all())

@bp.route('/accounts/<int:uid>/recover',methods=['GET','POST'])
@staff
def recover(uid):
    u=db.get_or_404(User,uid)
    if u.role=='archive':abort(404)
    if current_user.role!='admin' and u.role not in ('student','mentor'):abort(403)
    form=RecoveryForm()
    if form.validate_on_submit():
        if not reauthenticate(form.password.data,f'user:{uid}'):
            form.password.errors.append('Your password is incorrect.')
        elif form.action.data=='reset' and not account_enabled(u):
            form.reason.errors.append('An admin must restore access before a reset link can be issued.')
        elif form.action.data=='reset':
            log('Support password reset requested',f'user:{uid}',form.reason.data.strip())
            link=password_link(u)
            if uid==current_user.id:session['auth_version']=u.access.session_version
            return render_template('password_link.html',u=u,link=link,purpose='Password reset',support_return=True)
        else:
            invalidate(u);log('Support sessions revoked',f'user:{uid}',form.reason.data.strip());db.session.commit()
            if uid==current_user.id:logout_user();session.clear();return redirect(url_for('main.login'))
            flash('Sessions and unused account links revoked.','success')
            return redirect(url_for('support.account',uid=uid))
    return render_template('support/recover.html',u=u,form=form)

@bp.get('/bookings')
@staff
def bookings():
    q=request.args.get('q','').strip()[:100]
    query=Booking.query
    if q:
        users=db.select(User.id).where(or_(User.name.icontains(q,autoescape=True),User.email.icontains(q,autoescape=True)))
        mentors=db.select(Mentor.id).where(Mentor.user_id.in_(users))
        terms=[Booking.student_id.in_(users),Booking.mentor_id.in_(mentors),Booking.service_name.icontains(q,autoescape=True)]
        if q.isdigit() and len(q)<10:terms.append(Booking.id==int(q))
        query=query.filter(or_(*terms))
    return render_template('support/bookings.html',page=paginate(query.order_by(Booking.created_at.desc())),q=q)

@bp.get('/bookings/<int:bid>')
@staff
def booking(bid):
    return render_template('support/booking.html',b=db.get_or_404(Booking,bid))

@bp.get('/incidents')
@staff
def incidents():
    q=request.args.get('q','').strip()[:100];state=request.args.get('state','open')
    query=SupportIncident.query
    if state in ('open','resolved'):query=query.filter_by(status=state)
    if q:query=query.filter(SupportIncident.reference.icontains(q,autoescape=True))
    return render_template('support/incidents.html',page=paginate(query.order_by(SupportIncident.id.desc())),q=q,state=state)

@bp.route('/incidents/<int:iid>',methods=['GET','POST'])
@staff
def incident(iid):
    item=db.get_or_404(SupportIncident,iid);form=ResolveForm()
    if form.validate_on_submit():
        if item.status=='resolved':flash('This issue is already resolved.','info')
        else:
            item.status='resolved';item.resolution=form.resolution.data.strip();item.resolved_by=current_user.id;item.resolved_at=now()
            log('Support issue resolved',f'user:{item.user_id}' if item.user_id else f'incident:{item.id}',f'{item.reference}: '+item.resolution)
            db.session.commit();flash('Issue marked resolved.','success')
        return redirect(url_for('support.incident',iid=iid))
    return render_template('support/incident.html',item=item,form=form)

@bp.get('/integrations')
@staff
def integrations():
    cfg=settings()
    credentials=[{'id':key,'label':label,'configured':bool(current_app.config.get(env))} for key,(label,env) in CREDENTIALS.items()]
    return render_template('support/integrations.html',credentials=credentials,cfg=cfg,form=RevealForm(),acuity_user_id_present=bool(current_app.config.get('ACUITY_USER_ID')))

@bp.post('/credentials/<key>/reveal')
@roles('admin')
def reveal(key):
    if key not in CREDENTIALS:abort(404)
    form=RevealForm()
    if not form.validate_on_submit():return jsonify(error='Enter your password and try again.'),400
    if not reauthenticate(form.password.data,f'credential:{key}'):
        return jsonify(error='Your admin password is incorrect.'),403
    value=current_app.config.get(CREDENTIALS[key][1])
    if not value:return jsonify(error='This credential is not configured.'),404
    log('API credential revealed',f'credential:{key}','Admin password verified. Value not recorded.')
    db.session.commit()
    return jsonify(value=value)

@bp.after_request
def private_response(response):
    response.headers['Cache-Control']='no-store, private, max-age=0'
    response.headers['Pragma']='no-cache'
    response.headers['Referrer-Policy']='strict-origin'
    return response

def capture_error(sender,exception,**extra):
    """Store only safe metadata; never request bodies, URLs, query strings, or exception text."""
    reference=secrets.token_hex(8).upper();g.error_reference=reference
    actor=current_user.id if current_user.is_authenticated else None
    route=request.url_rule.rule if request.url_rule else '(unmatched route)'
    sender.logger.error('Support reference %s; endpoint=%s; type=%s',reference,request.endpoint,type(exception).__name__)
    try:
        db.session.rollback()
        db.session.add(SupportIncident(reference=reference,user_id=actor,route=route[:200],
            method=request.method,error_type=type(exception).__name__[:100]))
        db.session.commit()
    except Exception:
        db.session.rollback()
        sender.logger.error('Unable to persist support reference %s; inspect hosting logs.',reference)
