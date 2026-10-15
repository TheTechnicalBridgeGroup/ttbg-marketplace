"""Acuity transport and availability; appointment workflows live in appointments.py."""
import re
import base64
import json
import secrets
import calendar
from datetime import datetime, date, timedelta, timezone
from urllib.parse import urlencode, quote
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError, URLError
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from flask import Blueprint, current_app, request, render_template, abort, flash, redirect, url_for
from flask_login import current_user
from .models import db, Service, SupportIncident, AvailabilityRequest, now
from .security import settings, log
from .routes import roles
from .forms import EmptyForm

bp=Blueprint('acuity',__name__)
class AcuityError(Exception):
    def __init__(self,code,definitive=False):self.code=code;self.definitive=definitive
class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):return None

def mode():return current_app.config.get('ACUITY_MODE','live')
def scope():return mode()+':'+str(current_app.config.get('ACUITY_USER_ID',''))
def configured():
    key=current_app.config.get('ACUITY_API_KEY','')
    user=str(current_app.config.get('ACUITY_USER_ID',''))
    valid=user.isdigit() and 0<int(user)<2**31 and bool(key)
    if mode()=='mock':return valid and key=='local-dummy-key'
    return valid and not key.lower().startswith(('dummy','local-dummy','test-dummy'))

def api_get(path,params=None):return api_request('GET',path,params=params)
def api_request(method,path,params=None,data=None):
    reads=('availability/dates','availability/times','me','calendars','appointment-types','forms','appointments','webhooks')
    if not ((method=='GET' and (path in reads or re.fullmatch(r'appointments/[1-9][0-9]{0,19}',path))) or
            (method=='POST' and path in ('appointments','webhooks')) or (method=='PUT' and re.fullmatch(r'appointments/[1-9][0-9]{0,19}/cancel',path))):raise ValueError('Unsupported Acuity endpoint')
    if not configured():raise AcuityError('configuration_missing',True)
    if mode()=='mock':
        from .acuity_mock import mock_request
        return mock_request(method,path,params or {},data)
    auth=base64.b64encode((str(current_app.config['ACUITY_USER_ID'])+':'+current_app.config['ACUITY_API_KEY']).encode()).decode()
    url='https://acuityscheduling.com/api/v1/'+path+('?' + urlencode(params) if params else '')
    headers={'Authorization':'Basic '+auth,'Accept':'application/json','User-Agent':'TTBG-Marketplace/0.6.7'}
    if data is not None:headers['Content-Type']='application/json'
    req=Request(url,data=json.dumps(data).encode() if data is not None else None,headers=headers,method=method)
    try:
        with build_opener(NoRedirect()).open(req,timeout=10) as response:
            raw=response.read(1024*1024+1)
            if len(raw)>1024*1024:raise AcuityError('response_too_large')
            return json.loads(raw)
    except HTTPError as error:
        code='authentication_failed' if error.code in (401,403) else 'rate_limited' if error.code==429 else 'not_found' if error.code==404 else 'provider_error'
        definitive=error.code in (400,401,403,404,422)
        if error.code==400:
            code='validation_rejected'
            try:
                detail=json.loads(error.read(8192))
                # Only documented codes reach UI/audit. Never reflect provider messages or PII.
                known=('not_available','not_available_min_hours_in_advance','not_available_max_days_in_advance',
                       'no_available_calendar','required_field','invalid_fields','required_phone','invalid_calendar',
                       'invalid_appointment_type','invalid_datetime','invalid_timezone','required_first_name','required_last_name')
                if detail.get('error') in known:code=detail['error']
            except (ValueError,TypeError,AttributeError):pass
        error.close();raise AcuityError(code,definitive) from None
    except (URLError,TimeoutError,OSError):raise AcuityError('connection_failed') from None
    except (ValueError,UnicodeError):raise AcuityError('invalid_response') from None

def mapping(service):
    calendar_id=(service.mentor.acuity_calendar_id or '').strip()
    type_id=((service.scheduling.event_type_id if service.scheduling and service.scheduling.provider=='acuity' else '') or service.acuity_type_id or '').strip()
    if not calendar_id.isdigit() or not type_id.isdigit() or int(calendar_id)<=0 or int(type_id)<=0:return None
    return {'calendarID':calendar_id,'appointmentTypeID':type_id}

def throttle():
    cutoff=now()-timedelta(minutes=1)
    if AvailabilityRequest.query.filter(AvailabilityRequest.user_id==current_user.id,AvailabilityRequest.created_at>cutoff).count()>=20:abort(429)
    AvailabilityRequest.query.filter(AvailabilityRequest.user_id==current_user.id,AvailabilityRequest.created_at<=cutoff).delete()
    db.session.add(AvailabilityRequest(user_id=current_user.id));db.session.commit()

def record_failure(code):
    reference=secrets.token_hex(8).upper()
    db.session.add(SupportIncident(reference=reference,user_id=current_user.id,route=request.url_rule.rule,
        method=request.method,error_type='Acuity: '+code))
    db.session.commit();return reference

@bp.post('/support/integrations/acuity/check')
@roles('admin','account_manager')
def check_connection():
    if not EmptyForm().validate_on_submit():abort(400)
    throttle()
    try:
        result=api_get('me')
        if not isinstance(result,dict):raise AcuityError('invalid_response')
    except AcuityError as error:
        reference=record_failure(error.code)
        flash('Acuity check failed: '+error.code.replace('_',' ')+'. Support reference '+reference+'.','error')
    else:
        log('Acuity connection checked','integration:acuity','Authenticated API read succeeded. Availability and payment setup still require verification.')
        db.session.commit();flash('Acuity accepted the credentials. Check a mapped service to verify mentor availability.','success')
    return redirect(url_for('support.integrations'))

@bp.get('/availability/<int:sid>')
@roles('student','mentor','admin','account_manager')
def availability(sid):
    service=db.get_or_404(Service,sid)
    if not service.active or not service.mentor.publicly_visible:abort(404)
    cfg=settings()
    if cfg.scheduling_provider!='acuity' or (cfg.booking_mode not in ('acuity','acuity_confirmed') and current_user.role in ('student','mentor')):abort(404)
    zone=request.args.get('timezone','America/New_York')[:80]
    try:tz=ZoneInfo(zone)
    except (ZoneInfoNotFoundError,ValueError):abort(400)
    today=datetime.now(tz).date();month=request.args.get('month',today.strftime('%Y-%m'))
    try:
        first=date.fromisoformat(month+'-01')
        distance=(first.year-today.year)*12+first.month-today.month
        if len(month)!=7 or not 0<=distance<=6:abort(400)
        selected=request.args.get('date','')
        selected_date=date.fromisoformat(selected) if selected else None
        if selected_date and (selected_date.year!=first.year or selected_date.month!=first.month or selected_date<today):abort(400)
    except ValueError:abort(400)
    dates=set();slots=[];error=None;reference=None;ids=mapping(service)
    if not configured() or not ids:error='Availability is not available for this service yet. Please contact TTBG.'
    else:
        throttle()
        try:
            data=api_get('availability/dates',dict(ids,month=month,timezone=zone))
            if not isinstance(data,list):raise AcuityError('invalid_response')
            for item in data:
                parsed=date.fromisoformat(item['date'])
                if parsed.year==first.year and parsed.month==first.month and parsed>=today:dates.add(parsed.isoformat())
            if selected and selected in dates:
                data=api_get('availability/times',dict(ids,date=selected,timezone=zone))
                if not isinstance(data,list):raise AcuityError('invalid_response')
                seen=set()
                for item in data:
                    stamp=datetime.fromisoformat(item['time'])
                    if stamp.tzinfo is None:raise AcuityError('invalid_response')
                    local=stamp.astimezone(tz)
                    if local.date()!=selected_date or stamp<=datetime.now(timezone.utc) or stamp in seen:continue
                    seen.add(stamp)
                    body=f'I would like to book {service.name} with {service.mentor.user.name} on {local.isoformat()} ({zone}). Please confirm availability and payment arrangements.'
                    slots.append({'label':local.strftime('%I:%M %p %Z'),'time':local.isoformat(),
                        'contact':'mailto:'+cfg.support_email+'?'+urlencode({'subject':'TTBG session request','body':body},quote_via=quote)})
                slots.sort(key=lambda s:s['time'])
        except (AcuityError,ValueError,KeyError,TypeError,AttributeError) as exc:
            code=exc.code if isinstance(exc,AcuityError) else 'invalid_response'
            reference=record_failure(code);error='We could not load availability right now. Please try again or contact TTBG.';dates=set();slots=[]
    choices=['America/New_York','America/Chicago','America/Denver','America/Los_Angeles','America/Phoenix','Pacific/Honolulu','Europe/London','UTC']
    if zone not in choices:choices.append(zone)
    cells=[[{'day':day,'iso':date(first.year,first.month,day).isoformat() if day else ''} for day in week] for week in calendar.Calendar(firstweekday=6).monthdayscalendar(first.year,first.month)]
    def month_shift(delta):
        index=first.year*12+first.month-1+delta
        return f'{index//12:04d}-{index%12+1:02d}'
    return render_template('availability.html',s=service,month=month,month_label=first.strftime('%B %Y'),
        previous=month_shift(-1) if distance>0 else None,next_month=month_shift(1) if distance<6 else None,
        zone=zone,zones=choices,selected=selected,direct_booking=cfg.booking_mode=='acuity_confirmed',cells=cells,dates=dates,slots=slots,error=error,reference=reference)
