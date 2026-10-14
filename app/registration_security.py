"""Email ownership and Turnstile checks; no public token or mail debugging mode."""
import hashlib
import hmac
import json
import secrets
import smtplib
import ssl
from datetime import timedelta
from email.message import EmailMessage
from html import escape
from urllib.parse import urlsplit, urlencode
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import URLError, HTTPError
from email_validator import validate_email, EmailNotValidError
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, logout_user
from .models import db,User,EmailIdentity,SecurityRate,now
from .forms import EmptyForm, ActivateForm

bp=Blueprint('verification',__name__)

def normalized_email(value):
    return validate_email(value.strip(),check_deliverability=False).normalized.lower()

def email_allowed(user):
    item=user.email_identity
    return bool(item and item.email==user.email and (item.verified_at or item.legacy_exempt))

def mark_pending(user):
    item=user.email_identity or EmailIdentity(user=user,email=user.email)
    db.session.add(item);item.email=user.email;item.legacy_exempt=False;item.verified_at=None;item.token_hash=None;item.expires_at=None;item.last_sent_at=None
    return item

def mark_trusted(user):
    item=user.email_identity or EmailIdentity(user=user,email=user.email)
    db.session.add(item);item.email=user.email;item.legacy_exempt=True;item.verified_at=None

def email_label(user):
    item=user.email_identity
    if not email_allowed(user):return 'Verification required'
    return 'Verified email' if item.verified_at else 'Existing / administrator-provisioned account'

def public_origin():
    value=current_app.config.get('PUBLIC_BASE_URL','').rstrip('/')
    try:
        parsed=urlsplit(value)
        local=parsed.scheme=='http' and parsed.hostname in ('localhost','127.0.0.1')
        if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path or (parsed.scheme!='https' and not local):return None
        if parsed.port is not None and not 1<=parsed.port<=65535:return None
        return value
    except ValueError:return None

def mail_ready():
    c=current_app.config
    try:normalized_email(c.get('SMTP_FROM',''))
    except EmailNotValidError:return False
    return bool(public_origin() and c.get('SMTP_HOST') and c.get('SMTP_USERNAME') and c.get('SMTP_PASSWORD') and c.get('SMTP_SECURITY') in ('starttls','ssl'))

def rate_allowed(scope,identifier,limit,seconds):
    """Atomic DB counter; hashes identifiers and never trusts user-supplied proxy headers."""
    digest=hmac.new(current_app.secret_key.encode(),(scope+':'+str(identifier)).encode(),hashlib.sha256).hexdigest()
    row=db.session.get(SecurityRate,digest)
    if row is None:
        try:
            with db.session.begin_nested():
                db.session.add(SecurityRate(key=digest,count=0,expires_at=now()+timedelta(seconds=seconds)));db.session.flush()
        except IntegrityError:pass
    db.session.execute(update(SecurityRate).where(SecurityRate.key==digest,SecurityRate.expires_at<=now()).values(count=0,expires_at=now()+timedelta(seconds=seconds)))
    changed=db.session.execute(update(SecurityRate).where(SecurityRate.key==digest,SecurityRate.count<limit).values(count=SecurityRate.count+1)).rowcount
    db.session.commit()
    return changed==1

def turnstile_enabled():
    c=current_app.config
    return bool(c.get('TURNSTILE_ENABLED') or c.get('TURNSTILE_SITE_KEY') or c.get('TURNSTILE_SECRET_KEY'))

def turnstile_ready():
    c=current_app.config
    return bool(c.get('TURNSTILE_SITE_KEY') and c.get('TURNSTILE_SECRET_KEY') and c.get('TURNSTILE_HOSTNAMES'))

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None

def verify_turnstile(action):
    if not turnstile_enabled():return True
    if not turnstile_ready():return False
    token=request.form.get('cf-turnstile-response','')
    if not token or len(token)>2048:return False
    body=urlencode({'secret':current_app.config['TURNSTILE_SECRET_KEY'],'response':token}).encode()
    req=Request('https://challenges.cloudflare.com/turnstile/v0/siteverify',data=body,headers={'Content-Type':'application/x-www-form-urlencoded'},method='POST')
    try:
        with build_opener(NoRedirect()).open(req,timeout=8) as response:
            raw=response.read(16385)
            if len(raw)>16384:return False
            result=json.loads(raw)
        hosts=[h.strip().lower() for h in current_app.config['TURNSTILE_HOSTNAMES'].split(',') if h.strip()]
        valid=isinstance(result,dict) and result.get('success') is True and result.get('action')==action and result.get('hostname','').lower() in hosts
        if not valid:return False
        # Local replay guard in addition to Cloudflare's single-use validation.
        return rate_allowed('turnstile-token',token,1,600)
    except (URLError,HTTPError,TimeoutError,OSError,ValueError,AttributeError,TypeError):return False

def send_email(recipient,link):
    c=current_app.config;msg=EmailMessage()
    msg['Subject']='Verify your TTBG Marketplace email'
    msg['From']=normalized_email(c['SMTP_FROM']);msg['To']=normalized_email(recipient)
    msg.set_content('Confirm your email address for TTBG Marketplace. This link expires in 1 hour and can be used once.\n\n'+link+'\n\nIf you did not request this, ignore this email.')
    msg.add_alternative('<html><body><h1>Welcome to TTBG.</h1><p>Confirm your email address to continue.</p><p><a href="'+escape(link,quote=True)+'">Verify my email</a></p><p>This link expires in one hour and works once. If you did not request it, you can ignore this email.</p></body></html>',subtype='html')
    context=ssl.create_default_context()
    cls=smtplib.SMTP_SSL if c['SMTP_SECURITY']=='ssl' else smtplib.SMTP
    kwargs={'host':c['SMTP_HOST'],'port':c['SMTP_PORT'],'timeout':10}
    if c['SMTP_SECURITY']=='ssl':kwargs['context']=context
    with cls(**kwargs) as smtp:
        if c['SMTP_SECURITY']=='starttls':smtp.ehlo();smtp.starttls(context=context);smtp.ehlo()
        smtp.login(c['SMTP_USERNAME'],c['SMTP_PASSWORD']);smtp.send_message(msg)

def issue_email(user):
    from .security import log
    if email_allowed(user):return 'already_verified'
    if not mail_ready():return 'unavailable'
    if not rate_allowed('verification-send',user.id,1,60):return 'limited'
    if not rate_allowed('verification-daily',user.id,8,86400):return 'limited'
    item=user.email_identity
    if item is None or item.email!=user.email:item=mark_pending(user)
    token=secrets.token_urlsafe(32);digest=hashlib.sha256(token.encode()).hexdigest()
    item.token_hash=digest;item.expires_at=now()+timedelta(hours=1);item.last_sent_at=now();db.session.commit()
    link=public_origin()+url_for('verification.confirm')+'#token='+token
    try:send_email(user.email,link)
    except (smtplib.SMTPException,OSError,ValueError):
        # Invalidate only the token this attempt created; don't erase a newer resend.
        EmailIdentity.query.filter_by(user_id=user.id,token_hash=digest).update({'token_hash':None,'expires_at':None})
        log('Verification email failed',f'user:{user.id}','SMTP delivery failed; no credentials or token recorded.');db.session.commit()
        current_app.logger.warning('Verification email delivery failed for account %s',user.id)
        return 'failed'
    log('Verification email sent',f'user:{user.id}','SMTP server accepted message; expires in one hour.');db.session.commit();return 'sent'

def notify_verification(user):
    result=issue_email(user)
    if result=='sent':flash('Check your inbox for a verification email. The link expires in one hour.','success')
    elif result!='already_verified':flash('Email verification is required. Open the verification page to retry sending, or contact TTBG.','info')

@bp.route('/verify-email',methods=['GET','POST'])
@login_required
def notice():
    if email_allowed(current_user):return redirect(url_for('main.dashboard'))
    form=EmptyForm()
    if form.validate_on_submit():
        if not verify_turnstile('verify_email'):flash('Complete the bot check and try again.','error')
        else:
            result=issue_email(current_user)
            flash({'sent':'Verification email sent. Check your inbox and spam folder.','limited':'Please wait before resending. Limit: once per minute and eight per day.','unavailable':'Email delivery is not configured yet. Contact TTBG.','failed':'Email could not be sent. Please retry later or contact TTBG.'}.get(result,'Your email is already verified.'),'success' if result=='sent' else 'error')
        return redirect(url_for('verification.notice'))
    return render_template('verify_notice.html',form=form)

@bp.route('/verify-email/confirm',methods=['GET','POST'])
def confirm():
    form=ActivateForm();valid=None
    if form.validate_on_submit():
        if not rate_allowed('verify-attempt',request.remote_addr or 'unknown',30,900):abort(429)
        token=request.form.get('token','')
        if len(token)!=43:return render_template('verify_confirm.html',form=form,valid=False),400
        digest=hashlib.sha256(token.encode()).hexdigest()
        row=EmailIdentity.query.filter_by(token_hash=digest).first();u=db.session.get(User,row.user_id) if row else None
        from .security import account_enabled,log,invalidate
        if not row or not u or row.email!=u.email or not row.expires_at or row.expires_at<=now() or not account_enabled(u):
            return render_template('verify_confirm.html',form=form,valid=False),400
        count=EmailIdentity.query.filter_by(user_id=u.id,token_hash=digest,email=u.email).filter(EmailIdentity.expires_at>now()).update({'verified_at':now(),'legacy_exempt':False,'token_hash':None,'expires_at':None},synchronize_session=False)
        if count!=1:db.session.rollback();return render_template('verify_confirm.html',form=form,valid=False),400
        # Verification never signs the bearer in; revoke sessions created before ownership was proved.
        from werkzeug.security import generate_password_hash
        u.password_hash=generate_password_hash(form.password.data)
        if u.mentor:
            from .onboarding_logic import details_for
            details_for(u.mentor).activated_at=now()
        invalidate(u);log('Email verified',f'user:{u.id}','Mailbox ownership confirmed.',actor_id=u.id);db.session.commit()
        if current_user.is_authenticated and current_user.id==u.id:logout_user();session.clear()
        valid=True
    return render_template('verify_confirm.html',form=form,valid=valid)

@bp.after_request
def private_headers(response):
    response.headers['Cache-Control']='no-store'
    response.headers['Referrer-Policy']='strict-origin'
    return response
