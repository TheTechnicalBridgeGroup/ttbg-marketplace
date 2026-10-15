"""Create once, reconcile uncertain outcomes, and synchronize Acuity's latest state."""
import base64
import hashlib
import hmac
import secrets
from datetime import datetime,timedelta,timezone
from decimal import Decimal,InvalidOperation
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo,ZoneInfoNotFoundError
from flask import Blueprint,abort,current_app,flash,redirect,render_template,request,url_for
from flask_login import current_user,login_required
from flask_wtf import FlaskForm
from itsdangerous import URLSafeTimedSerializer,BadSignature,SignatureExpired
from sqlalchemy.exc import IntegrityError,SQLAlchemyError
from wtforms import StringField,HiddenField,BooleanField,PasswordField,SelectField
from wtforms.validators import DataRequired,Length,Optional,Email
from . import acuity
from .models import (db,User,Service,Booking,PlatformSettings,AcuityRequest,AcuityAppointment,AcuitySyncJob,now)
from .routes import roles
from .security import settings,account_enabled,log
from .registration_security import email_allowed,rate_allowed,public_origin
from .forms import EmptyForm
from .booking_config import split_amount

bp=Blueprint('appointments',__name__)
STAFF=('admin','account_manager')
class ConfirmationForm(FlaskForm):
    quote=HiddenField(validators=[DataRequired(),Length(max=3000)])
    request_id=HiddenField(validators=[DataRequired(),Length(min=32,max=32)])
    first_name=StringField('First name',validators=[DataRequired(),Length(max=100)])
    last_name=StringField('Last name',validators=[DataRequired(),Length(max=100)])
    phone=StringField('Phone (include country code)',validators=[DataRequired(),Length(max=40)])
    acknowledge=BooleanField('I understand this confirms my appointment and does not collect payment.',validators=[DataRequired()])
class IDForm(FlaskForm):
    provider_id=StringField('Acuity appointment ID',validators=[DataRequired(),Length(max=20)])
class ResolveForm(IDForm):
    password=PasswordField('Your staff password',validators=[DataRequired(),Length(max=128)])
    reason=StringField('Reason',validators=[DataRequired(),Length(min=3,max=300)])
class ReleaseForm(FlaskForm):
    password=PasswordField('Your staff password',validators=[DataRequired(),Length(max=128)])
    reason=StringField('What did you verify in Acuity?',validators=[DataRequired(),Length(min=10,max=300)])
    checked=BooleanField('I checked Acuity directly and confirmed that this request created no appointment.',validators=[DataRequired()])
class ImportForm(FlaskForm):
    email=StringField('Existing student account email',validators=[DataRequired(),Email(),Length(max=254)])
    service_id=SelectField('Matching TTBG service',coerce=int,choices=[])
    password=PasswordField('Your staff password',validators=[DataRequired(),Length(max=128)])
    reason=StringField('Reason for linking',validators=[DataRequired(),Length(min=3,max=300)])

def number(value):
    value=str(value)
    if not value.isdigit() or not 0<int(value)<2**63:raise acuity.AcuityError('invalid_response')
    return str(int(value))
def cents(value):
    try:
        amount=Decimal(str(value))
        if not amount.is_finite() or amount<0 or amount>10_000_000 or amount*100!=(amount*100).to_integral_value():raise ValueError()
        return int(amount*100)
    except (InvalidOperation,ValueError,TypeError):raise acuity.AcuityError('invalid_price') from None

def stamp(value):
    try:
        result=datetime.fromisoformat(value)
        if result.tzinfo is None:raise ValueError()
        return result.astimezone(timezone.utc).replace(tzinfo=None)
    except (ValueError,TypeError):raise acuity.AcuityError('invalid_datetime') from None

def write_lock():
    settings()
    db.session.execute(db.select(PlatformSettings).where(PlatformSettings.id==1).with_for_update()).scalar_one()
    db.session.expire_all()

def serializer():return URLSafeTimedSerializer(current_app.config['SECRET_KEY'],salt='acuity-booking-v06')
def direct_enabled():return settings().scheduling_provider=='acuity' and settings().booking_mode=='acuity_confirmed'

def checked_service(sid):
    s=db.get_or_404(Service,sid)
    if not s.active or not s.mentor.publicly_visible:abort(404)
    if not direct_enabled():abort(404)
    if not acuity.configured():raise acuity.AcuityError('configuration_missing',True)
    if not acuity.mapping(s):raise acuity.AcuityError('mapping_missing',True)
    return s

def catalog(service):
    ids=acuity.mapping(service)
    calendars=acuity.api_get('calendars');types=acuity.api_get('appointment-types');forms=acuity.api_get('forms')
    if not all(isinstance(x,list) for x in (calendars,types,forms)):raise acuity.AcuityError('invalid_response',True)
    if not any(str(c.get('id'))==ids['calendarID'] for c in calendars):raise acuity.AcuityError('calendar_not_found',True)
    matches=[t for t in types if str(t.get('id'))==ids['appointmentTypeID']]
    if len(matches)!=1:raise acuity.AcuityError('type_not_found',True)
    t=matches[0]
    if not t.get('active',True) or t.get('type') not in ('service',None):raise acuity.AcuityError('one_to_one_type_required',True)
    if ids['calendarID'] not in [str(v) for v in t.get('calendarIDs',[])]:raise acuity.AcuityError('type_calendar_mismatch',True)
    if cents(t.get('price'))!=service.price_cents:raise acuity.AcuityError('price_mismatch',True)
    try:duration=int(t['duration'])
    except (ValueError,TypeError,KeyError):raise acuity.AcuityError('invalid_response',True) from None
    if duration!=service.duration:raise acuity.AcuityError('duration_mismatch',True)
    fields=[]
    for form in forms:
        if form.get('hidden') or ids['appointmentTypeID'] not in [str(v) for v in form.get('appointmentTypeIDs',[])]:continue
        for f in form.get('fields',[]):
            kind=f.get('type');fid=number(f.get('id'))
            if kind=='file':
                if f.get('required'):raise acuity.AcuityError('required_file_intake_not_supported',True)
                continue
            if kind not in ('textbox','textarea','dropdown','checkbox','checkboxlist','yesno','address'):raise acuity.AcuityError('unsupported_intake_field',True)
            options=f.get('options',[])
            if not isinstance(options,list) or any(not isinstance(o,str) for o in options):raise acuity.AcuityError('invalid_response',True)
            fields.append({'id':fid,'name':str(f.get('name','Question'))[:500],'type':kind,'required':bool(f.get('required')),'options':options[:200]})
    if len(fields)>100 or len({f['id'] for f in fields})!=len(fields):raise acuity.AcuityError('invalid_response',True)
    return fields

def read_answers(fields):
    answers=[];errors={}
    for f in fields:
        key='field_'+f['id'];values=request.form.getlist(key)
        value=', '.join(values) if f['type']=='checkboxlist' else (values[0].strip() if values else '')
        if len(value)>4000:errors[key]='Use at most 4000 characters.'
        elif f['required'] and (not value or f['type']=='checkbox' and value!='yes'):errors[key]='This answer is required.'
        elif f['type'] in ('dropdown','checkboxlist') and any(v not in f['options'] for v in values if v):errors[key]='Choose a listed option.'
        elif f['type'] in ('checkbox','yesno') and value and value not in ('yes','no'):errors[key]='Choose yes or no.'
        if value:answers.append({'id':int(f['id']),'value':value})
    return answers,errors

def slot_available(ids,starts,zone):
    local=starts.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(zone))
    result=acuity.api_get('availability/times',dict(ids,date=local.date().isoformat(),timezone=zone))
    if not isinstance(result,list):raise acuity.AcuityError('invalid_response',True)
    return any(stamp(row.get('time'))==starts for row in result)

def normalize(data):
    try:
        cancelled=data['canceled']
        if not isinstance(cancelled,bool):raise ValueError()
        duration=int(data['duration'])
        if not 1<=duration<=1440:raise ValueError()
        zone=str(data.get('timezone') or 'UTC');ZoneInfo(zone)
        return dict(provider_id=number(data['id']),calendar_id=number(data['calendarID']),type_id=number(data['appointmentTypeID']),
            starts_at=stamp(data['datetime']),duration=duration,timezone=zone,email=str(data.get('email','')).strip().lower()[:254],
            client_name=(str(data.get('firstName',''))+' '+str(data.get('lastName',''))).strip()[:200],price_cents=cents(data['price']),
            paid=str(data.get('paid','unknown'))[:40],cancelled=cancelled,location=str(data.get('location') or '')[:1000])
    except (ValueError,KeyError,TypeError,ZoneInfoNotFoundError):raise acuity.AcuityError('invalid_response') from None

def matches_request(values,req):
    return values['calendar_id']==req.calendar_id and values['type_id']==req.type_id and values['starts_at']==req.starts_at and values['email']==req.email

def new_booking(req,service,student_id):
    split=split_amount(req.price_cents,req.fee_bps)
    b=Booking(student_id=student_id,mentor_id=service.mentor_id,service_id=service.id,service_name=req.service_name,
        start=req.starts_at,duration=req.duration,price_cents=req.price_cents,fee_cents=split['company_cents'],earnings_cents=split['mentor_cents'],
        status='confirmed',payment_status='payment_due',request_key='acuity:'+req.id,slot_key=None,goals='')
    db.session.add(b);db.session.flush();return b

def save_snapshot(data,req=None):
    values=normalize(data);write_lock()
    if req:db.session.refresh(req)
    item=AcuityAppointment.query.filter_by(scope=acuity.scope(),provider_id=values['provider_id']).first()
    if not item:item=AcuityAppointment(scope=acuity.scope(),**values);db.session.add(item)
    if req and (item.request_id not in (None,req.id) or item.booking_id and item.request_id!=req.id):raise acuity.AcuityError('appointment_already_linked')
    if req and not item.booking_id:
        if req.user_id is None or req.service_id is None or req.state=='deleted':
            item.identity_removed=True;item.request_id=req.id
        elif not matches_request(values,req):raise acuity.AcuityError('confirmation_mismatch')
        else:
            service=db.session.get(Service,req.service_id)
            item.booking=new_booking(req,service,req.user_id);item.request_id=req.id
            req.state='confirmed';req.error_code=''
    for key,value in values.items():setattr(item,key,value)
    if item.identity_removed:item.email='';item.client_name='';item.location=''
    db.session.flush()
    item.last_synced_at=now();item.sync_state='unlinked' if not item.booking_id else 'synced'
    if item.booking:
        b=item.booking;original=item.request
        # Never silently transfer ownership or reveal changed client details to an earlier owner.
        changed=original and (item.price_cents!=b.price_cents or item.duration!=original.duration or item.calendar_id!=original.calendar_id or item.type_id!=original.type_id or
            (not item.identity_removed and item.email!=original.email))
        if changed:item.sync_state='needs_review';b.status='sync_review'
        else:
            b.start=item.starts_at;b.duration=item.duration;b.status='cancelled' if item.cancelled else 'confirmed'
            b.payment_status='acuity_reported_paid' if item.paid.lower() in ('yes','true','paid') else 'payment_due'
            if original and (item.cancelled or item.starts_at!=original.starts_at):original.dedupe_key=None
    if req and item.booking:log('Acuity appointment confirmed',f'booking:{item.booking.id}',f'Acuity ID {item.provider_id}; {acuity.mode()}.',actor_id=req.user_id)
    db.session.flush();return item

def queue(provider_id):
    provider_id=number(provider_id)
    obj=AcuitySyncJob.query.filter_by(scope=acuity.scope(),provider_id=provider_id).first()
    if obj:obj.pending=True;obj.received_at=now()
    else:obj=AcuitySyncJob(scope=acuity.scope(),provider_id=provider_id,pending=True);db.session.add(obj)
    try:db.session.commit()
    except IntegrityError:
        db.session.rollback();obj=AcuitySyncJob.query.filter_by(scope=acuity.scope(),provider_id=provider_id).one();obj.pending=True;obj.received_at=now();db.session.commit()
    return obj.id

def sync_one(provider_id):
    jid=queue(provider_id)
    job=db.session.execute(db.select(AcuitySyncJob).where(AcuitySyncJob.id==jid).with_for_update()).scalar_one()
    try:
        data=acuity.api_get('appointments/'+number(provider_id))
        if number(data.get('id'))!=number(provider_id):raise acuity.AcuityError('confirmation_mismatch')
        item=save_snapshot(data);job.pending=False;job.error_code='';job.processed_at=now();db.session.commit();return item
    except acuity.AcuityError as exc:
        db.session.rollback();job=db.session.get(AcuitySyncJob,jid);job.pending=True;job.error_code=exc.code
        item=AcuityAppointment.query.filter_by(scope=acuity.scope(),provider_id=str(provider_id)).first()
        if item:item.sync_state='sync_failed'
        db.session.commit();raise

@bp.route('/appointments/new/<int:sid>',methods=['GET','POST'])
@roles('student')
def book(sid):
    form=ConfirmationForm();fields=[];field_errors={};error=None;service=None;quoted=None
    # Repeat submissions of an accepted request never send another provider POST.
    if request.method=='POST' and form.request_id.data:
        prior=db.session.get(AcuityRequest,form.request_id.data)
        if prior:
            if prior.user_id!=current_user.id or prior.scope!=acuity.scope():abort(403)
            return redirect(url_for('appointments.request_status',rid=prior.id))
    try:
        service=checked_service(sid)
        zone=request.args.get('timezone','America/New_York')[:80]
        if request.method=='POST':
            try:quoted=serializer().loads(form.quote.data or '',max_age=1800)
            except (BadSignature,SignatureExpired):abort(400)
            if quoted['user_id']!=current_user.id or quoted['sid']!=sid or quoted['request_id']!=form.request_id.data:abort(400)
            zone=quoted['zone'];starts=stamp(quoted['time'])
        else:starts=stamp(request.args.get('time',''))
        ZoneInfo(zone)
        if not now()<starts<now()+timedelta(days=187):raise acuity.AcuityError('time_no_longer_available',True)
        ids=acuity.mapping(service)
        if quoted and (quoted['ids']!=ids or quoted['price']!=service.price_cents or quoted['duration']!=service.duration or quoted['fee_bps']!=settings().fee_bps or quoted['scope']!=acuity.scope()):
            raise acuity.AcuityError('booking_details_changed',True)
        acuity.throttle();fields=catalog(service)
        if request.method=='GET':
            rid=secrets.token_hex(16);form.request_id.data=rid
            form.quote.data=serializer().dumps(dict(request_id=rid,user_id=current_user.id,sid=sid,ids=ids,price=service.price_cents,
                duration=service.duration,fee_bps=settings().fee_bps,zone=zone,time=starts.replace(tzinfo=timezone.utc).isoformat(),scope=acuity.scope()))
            names=current_user.name.split(' ',1);form.first_name.data=names[0];form.last_name.data=names[1] if len(names)>1 else ''
        elif form.validate_on_submit():
            answers,field_errors=read_answers(fields)
            if not field_errors:
                if not rate_allowed('acuity-create',str(current_user.id),10,900):abort(429)
                if not slot_available(ids,starts,zone):raise acuity.AcuityError('not_available',True)
                write_lock();service=checked_service(sid)
                if not account_enabled(current_user) or not email_allowed(current_user):abort(403)
                if quoted['ids']!=acuity.mapping(service) or quoted['price']!=service.price_cents or quoted['duration']!=service.duration or quoted['fee_bps']!=settings().fee_bps:
                    raise acuity.AcuityError('booking_details_changed',True)
                fingerprint=hashlib.sha256(f'{acuity.scope()}:{current_user.id}:{ids["calendarID"]}:{starts.isoformat()}'.encode()).hexdigest()
                existing=AcuityRequest.query.filter_by(dedupe_key=fingerprint).first()
                if existing:return redirect(url_for('appointments.request_status',rid=existing.id))
                req=AcuityRequest(id=form.request_id.data,user_id=current_user.id,service_id=sid,scope=acuity.scope(),calendar_id=ids['calendarID'],type_id=ids['appointmentTypeID'],
                    starts_at=starts,timezone=zone,email=current_user.email,service_name=service.name,price_cents=service.price_cents,duration=service.duration,fee_bps=settings().fee_bps,state='creating',dedupe_key=fingerprint)
                db.session.add(req)
                try:db.session.commit()
                except IntegrityError:
                    db.session.rollback();existing=AcuityRequest.query.filter_by(dedupe_key=fingerprint).first()
                    if existing:return redirect(url_for('appointments.request_status',rid=existing.id))
                    raise
                payload=dict(calendarID=int(ids['calendarID']),appointmentTypeID=int(ids['appointmentTypeID']),datetime=starts.replace(tzinfo=timezone.utc).isoformat(),timezone=zone,
                    firstName=form.first_name.data.strip(),lastName=form.last_name.data.strip(),email=req.email,phone=form.phone.data.strip(),fields=answers,smsOptIn=False)
                try:
                    data=acuity.api_request('POST','appointments',data=payload)
                    item=save_snapshot(data,req);db.session.commit()
                except acuity.AcuityError as exc:
                    db.session.rollback();req=db.session.get(AcuityRequest,form.request_id.data)
                    if req.state!='deleted':
                        req.state='rejected' if exc.definitive else 'uncertain';req.error_code=exc.code
                        if exc.definitive:req.dedupe_key=None
                    db.session.commit()
                except SQLAlchemyError:
                    # The creating record was committed before the network request. Never POST again.
                    db.session.rollback()
                    return redirect(url_for('appointments.request_status',rid=form.request_id.data))
                return redirect(url_for('appointments.request_status',rid=form.request_id.data))
    except (acuity.AcuityError,ZoneInfoNotFoundError,ValueError,TypeError,KeyError) as exc:
        error=exc.code if isinstance(exc,acuity.AcuityError) else 'invalid_booking_details'
    return render_template('appointments/confirm.html',s=service,form=form,fields=fields,field_errors=field_errors,error=error,
        starts=starts.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(zone)) if service and 'starts' in locals() and not error else None,zone=zone if 'zone' in locals() else '')

@bp.get('/appointments/requests/<rid>')
@login_required
def request_status(rid):
    req=db.get_or_404(AcuityRequest,rid)
    if req.user_id!=current_user.id and current_user.role not in STAFF:abort(403)
    linked=AcuityAppointment.query.filter_by(request_id=rid).first()
    if req.state=='confirmed' and linked and linked.booking_id:return redirect(url_for('main.booking_detail',bid=linked.booking_id))
    return render_template('appointments/pending.html',req=req,staff=current_user.role in STAFF)

@bp.post('/webhooks/acuity')
def webhook():
    if not acuity.configured():return '',500
    if request.content_length is not None and request.content_length>8192:abort(413)
    raw=request.get_data(cache=True)
    if len(raw)>8192:abort(413)
    signature=request.headers.get('X-Acuity-Signature','')
    if not signature.isascii() or len(signature)>128:abort(403)
    keys=[current_app.config['ACUITY_API_KEY'],current_app.config.get('ACUITY_WEBHOOK_SECRET','')]
    if not any(key and hmac.compare_digest(base64.b64encode(hmac.new(key.encode(),raw,hashlib.sha256).digest()).decode(),signature) for key in keys):abort(403)
    if request.form.get('action') not in ('scheduled','rescheduled','canceled','changed'):return '',204
    try:pid=number(request.form.get('id'))
    except acuity.AcuityError:abort(400)
    try:sync_one(pid)
    except (acuity.AcuityError,SQLAlchemyError):db.session.rollback();return '',500
    return '',204

@bp.get('/support/appointments')
@roles(*STAFF)
def support():
    page=AcuityAppointment.query.filter_by(scope=acuity.scope()).order_by(AcuityAppointment.id.desc()).paginate(page=request.args.get('page',1,type=int),per_page=25,error_out=False)
    pending=AcuityRequest.query.filter(AcuityRequest.scope==acuity.scope(),AcuityRequest.state.in_(('creating','uncertain','rejected'))).order_by(AcuityRequest.created_at.desc()).limit(30).all()
    failures=AcuitySyncJob.query.filter_by(scope=acuity.scope(),pending=True).order_by(AcuitySyncJob.received_at.desc()).limit(30).all()
    return render_template('appointments/support.html',page=page,pending=pending,failures=failures,id_form=IDForm())

@bp.post('/support/appointments/fetch')
@roles(*STAFF)
def fetch():
    form=IDForm()
    if not form.validate_on_submit():abort(400)
    acuity.throttle()
    try:item=sync_one(number(form.provider_id.data))
    except acuity.AcuityError as exc:flash('Sync could not finish: '+exc.code.replace('_',' ')+'. The retry is saved.','error');return redirect(url_for('appointments.support'))
    return redirect(url_for('appointments.inspect',aid=item.id))

@bp.route('/support/appointments/<int:aid>',methods=['GET','POST'])
@roles(*STAFF)
def inspect(aid):
    item=db.get_or_404(AcuityAppointment,aid)
    if item.scope!=acuity.scope():abort(404)
    form=ImportForm()
    services=[s for s in Service.query.filter_by(active=True) if s.mentor.publicly_visible and acuity.mapping(s)=={'calendarID':item.calendar_id,'appointmentTypeID':item.type_id}]
    form.service_id.choices=[(s.id,s.mentor.user.name+' / '+s.name) for s in services]
    if request.method=='GET':form.email.data=item.email
    if form.validate_on_submit():
        from .support import reauthenticate
        if not reauthenticate(form.password.data,f'acuity:{item.provider_id}'):form.password.errors.append('Your password is incorrect.')
        elif item.booking_id or item.identity_removed:abort(409)
        else:
            u=User.query.filter_by(email=form.email.data.strip().lower(),role='student').first()
            if not u or u.email!=item.email or not account_enabled(u) or not email_allowed(u):form.email.errors.append('Choose an enabled, verified student whose email matches this Acuity appointment.')
            else:
                write_lock();db.session.refresh(item)
                if item.booking_id or item.identity_removed:abort(409)
                service=db.session.get(Service,form.service_id.data)
                if not service or not service.active or not service.mentor.publicly_visible or acuity.mapping(service)!={'calendarID':item.calendar_id,'appointmentTypeID':item.type_id}:abort(409)
                req=AcuityRequest(id=secrets.token_hex(16),user_id=u.id,service_id=service.id,scope=acuity.scope(),calendar_id=item.calendar_id,type_id=item.type_id,
                    starts_at=item.starts_at,timezone=item.timezone,email=u.email,service_name=service.name,price_cents=item.price_cents,duration=item.duration,fee_bps=settings().fee_bps,state='confirmed')
                db.session.add(req);db.session.flush();item.booking=new_booking(req,service,u.id);item.request_id=req.id
                item.booking.status='cancelled' if item.cancelled else 'confirmed';item.booking.payment_status='acuity_reported_paid' if item.paid.lower() in ('yes','true','paid') else 'payment_due';item.sync_state='synced'
                log('External Acuity appointment linked',f'booking:{item.booking.id}',form.reason.data.strip());db.session.commit()
                flash('Appointment linked. The student and mentor can see it in their dashboards.','success');return redirect(url_for('appointments.inspect',aid=aid))
    return render_template('appointments/inspect.html',item=item,form=form)

@bp.route('/support/appointment-requests/<rid>',methods=['GET','POST'])
@roles(*STAFF)
def reconcile(rid):
    req=db.get_or_404(AcuityRequest,rid)
    if req.scope!=acuity.scope():abort(404)
    form=ResolveForm();release=ReleaseForm(prefix='release-');candidates=[]
    if request.method=='POST':
        from .support import reauthenticate
        if request.form.get('operation')=='release':
            if not release.validate_on_submit():abort(400)
            if not reauthenticate(release.password.data,f'acuity-request:{rid}'):abort(403)
            write_lock();db.session.refresh(req)
            if req.state not in ('uncertain','creating') or req.updated_at>now()-timedelta(seconds=60):abort(409)
            req.state='rejected';req.dedupe_key=None;req.error_code='staff_confirmed_not_created'
            log('Acuity request released',f'acuity-request:{rid}',release.reason.data.strip());db.session.commit()
            flash('Request released after your Acuity check. The student may choose a time again.','success')
        elif request.form.get('operation')=='search':
            if not EmptyForm().validate_on_submit():abort(400)
            acuity.throttle()
            try:
                data=acuity.api_get('appointments',dict(email=req.email,calendarID=req.calendar_id,appointmentTypeID=req.type_id,minDate=(req.starts_at-timedelta(days=1)).date().isoformat(),maxDate=(req.starts_at+timedelta(days=1)).date().isoformat(),showall='true',max=100))
                candidates=[normalize(x) for x in data if matches_request(normalize(x),req)]
            except (acuity.AcuityError,TypeError):flash('Could not search Acuity. Check directly before making a decision.','error')
        elif form.validate_on_submit():
            if not reauthenticate(form.password.data,f'acuity-request:{rid}'):form.password.errors.append('Your password is incorrect.')
            elif req.state not in ('creating','uncertain'):abort(409)
            else:
                try:
                    data=acuity.api_get('appointments/'+number(form.provider_id.data))
                    if not matches_request(normalize(data),req):raise acuity.AcuityError('confirmation_mismatch')
                    item=save_snapshot(data,req);log('Uncertain appointment reconciled',f'acuity-request:{rid}',form.reason.data.strip());db.session.commit()
                except acuity.AcuityError as exc:db.session.rollback();flash('Could not link: '+exc.code.replace('_',' ')+'.','error')
                else:return redirect(url_for('appointments.inspect',aid=item.id))
    return render_template('appointments/reconcile.html',req=req,form=form,release=release,candidates=candidates)

@bp.post('/support/appointments/enable-webhook')
@roles('admin')
def enable_webhook():
    if not EmptyForm().validate_on_submit():abort(400)
    origin=public_origin()
    if not origin or acuity.mode()=='live' and urlsplit(origin).scheme!='https':flash('Set PUBLIC_BASE_URL to the public HTTPS marketplace origin first.','error');return redirect(url_for('appointments.support'))
    target=origin+url_for('appointments.webhook')
    if len(target)>256:abort(400)
    try:
        existing=acuity.api_get('webhooks')
        if not isinstance(existing,list):raise acuity.AcuityError('invalid_response')
        if not any(x.get('target')==target and x.get('event')=='appointment.changed' and x.get('status','active')=='active' for x in existing):
            acuity.api_request('POST','webhooks',data={'event':'appointment.changed','target':target})
        log('Acuity webhook enabled','integration:acuity','appointment.changed → marketplace callback');db.session.commit()
        flash('Appointment change webhook registered. Run a booking and verify its last-synced time.','success')
    except acuity.AcuityError as exc:flash('Webhook setup failed: '+exc.code.replace('_',' ')+'.','error')
    return redirect(url_for('appointments.support'))

@bp.route('/support/acuity-mappings',methods=['GET','POST'])
@roles(*STAFF)
def mappings():
    services=Service.query.join(Service.mentor).filter(Service.active.is_(True)).order_by(Service.id).all()
    calendars=[];types=[];error=None;checked=None
    if request.method=='POST':
        if not EmptyForm().validate_on_submit():abort(400)
        acuity.throttle()
        try:
            sid=request.form.get('service_id',type=int)
            if sid:
                service=db.get_or_404(Service,sid)
                if not acuity.mapping(service):raise acuity.AcuityError('mapping_missing',True)
                catalog(service);checked=sid
                flash('Calendar, appointment type, duration, price, and supported intake forms verified.','success')
            calendars=acuity.api_get('calendars');types=acuity.api_get('appointment-types')
            if not isinstance(calendars,list) or not isinstance(types,list):raise acuity.AcuityError('invalid_response')
        except acuity.AcuityError as exc:error=exc.code.replace('_',' ')
    return render_template('appointments/mappings.html',services=services,calendars=calendars,types=types,error=error,checked=checked,mapping=acuity.mapping)
