import hashlib
import secrets
from datetime import timedelta
from flask import session, request, current_app, url_for
from flask_login import current_user, login_user
from .models import db, AccountAccess, PasswordLink, PlatformAudit, PlatformSettings, MentorInvitation, now

STAFF_ROLES = ('admin', 'account_manager', 'onboarding')
ROLE_LABELS = {'admin':'Admin', 'account_manager':'Account Manager', 'onboarding':'Account Manager', 'mentor':'Mentor', 'student':'Mentee / Student'}

def access_for(user):
    if not user.access:
        row=AccountAccess(user=user, enabled=True, session_version=0)
        db.session.add(row);db.session.flush()
    return user.access

def account_enabled(user):
    return (not user.access or user.access.enabled) and not (user.mentor and user.mentor.status in ('suspended','deleted'))

def sign_in(user):
    row=access_for(user);row.last_login_at=now();db.session.commit()
    session.clear();login_user(user);session.permanent=True
    session['auth_version']=row.session_version

def invalidate(user):
    row=access_for(user)
    AccountAccess.query.filter_by(user_id=user.id).update({AccountAccess.session_version:AccountAccess.session_version+1},synchronize_session='fetch')
    PasswordLink.query.filter_by(user_id=user.id).delete()
    if user.mentor:MentorInvitation.query.filter_by(mentor_id=user.mentor.id).delete()

def log(action,target,detail='',actor_id=None):
    actor=actor_id if actor_id is not None else (current_user.id if current_user.is_authenticated else None)
    db.session.add(PlatformAudit(actor_id=actor,action=action,target=str(target),detail=detail))

def settings():
    item=db.session.get(PlatformSettings,1)
    if item is None:
        item=PlatformSettings(id=1)
        db.session.add(item);db.session.flush()
    return item

def password_link(user,purpose='reset'):
    invalidate(user)
    token=secrets.token_urlsafe(32)
    db.session.add(PasswordLink(user_id=user.id,token_hash=hashlib.sha256(token.encode()).hexdigest(),expires_at=now()+timedelta(hours=1),purpose=purpose))
    log('Password link issued',f'user:{user.id}',f'{purpose}; expires in one hour. Existing sessions revoked.')
    db.session.commit()
    base=current_app.config.get('PUBLIC_BASE_URL') or request.url_root.rstrip('/')
    return base.rstrip('/')+url_for('control.password_reset',token=token)
