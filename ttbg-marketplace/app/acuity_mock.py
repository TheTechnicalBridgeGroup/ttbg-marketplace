"""Local-only deterministic Acuity simulator. It never makes network calls."""
import calendar
from copy import deepcopy
from datetime import date,datetime,timedelta,timezone
from zoneinfo import ZoneInfo
from sqlalchemy.exc import IntegrityError
from flask import current_app
from .models import db,AcuityMockAppointment,AcuityMockConfig
from .acuity import AcuityError

CALENDAR_ID=101
TYPE_ID=201
TYPES={
    '201': {'id':201,'name':'Local mentoring session','description':'<p>A focused session with your TTBG mentor.</p>',
            'private':False,'active':True,'type':'service','duration':60,'price':'100.00','calendarIDs':[101]},
    '202': {'id':202,'name':'Free introductory consultation','description':'Meet your mentor and discuss your goals.',
            'private':False,'active':True,'type':'service','duration':30,'price':'0.00','calendarIDs':[101]},
}

def config():
    obj=db.session.get(AcuityMockConfig,1)
    if obj is None:obj=AcuityMockConfig(id=1,scenario='normal',webhook_target='');db.session.add(obj);db.session.flush()
    return obj

def times(day,zone):
    tz=ZoneInfo('America/New_York');target=ZoneInfo(zone);result=[]
    # Interpret requested dates in the client's timezone, as the live API does.
    for shift in (-1,0,1):
        d=day+timedelta(days=shift)
        if d.weekday()>=5:continue
        for hour in (10,13,15):
            stamp=datetime(d.year,d.month,d.day,hour,tzinfo=tz)
            if stamp.astimezone(target).date()!=day or stamp<=datetime.now(timezone.utc)+timedelta(hours=2):continue
            slot=f'{CALENDAR_ID}:'+stamp.astimezone(timezone.utc).isoformat()
            if not AcuityMockAppointment.query.filter_by(slot=slot).first():result.append({'time':stamp.astimezone(target).isoformat()})
    return result

def mock_request(method,path,params,data):
    if current_app.config.get('APP_ENV')!='local':raise AcuityError('mock_not_local',True)
    if str(current_app.config.get('ACUITY_USER_ID'))!='1':raise AcuityError('authentication_failed',True)
    cfg=config()
    if method=='GET' and path=='me':return {'id':1,'name':'TTBG local scheduling','currency':'USD','timezone':'America/New_York'}
    if method=='GET' and path=='calendars':return [{'id':101,'name':'Local TTBG mentor','timezone':'America/New_York'}]
    if method=='GET' and path=='appointment-types':return deepcopy(list(TYPES.values()))
    if method=='GET' and path=='forms':return [{'id':301,'name':'Session preparation','hidden':False,'appointmentTypeIDs':[201],
        'fields':[{'id':401,'name':'What would you like to focus on?','type':'textarea','required':True,'options':[]}]}]
    if path.startswith('availability/'):
        if str(params.get('calendarID'))!='101' or str(params.get('appointmentTypeID')) not in TYPES:raise AcuityError('invalid_calendar',True)
        zone=params.get('timezone','America/New_York')
        if path=='availability/times':return times(date.fromisoformat(params['date']),zone)
        first=date.fromisoformat(params['month']+'-01')
        return [{'date':date(first.year,first.month,d).isoformat()} for d in range(1,calendar.monthrange(first.year,first.month)[1]+1) if times(date(first.year,first.month,d),zone)]
    if method=='POST' and path=='appointments':
        if cfg.scenario=='unavailable':raise AcuityError('not_available',True)
        if str(data.get('calendarID'))!='101' or str(data.get('appointmentTypeID')) not in TYPES:raise AcuityError('invalid_calendar',True)
        kind=TYPES[str(data['appointmentTypeID'])]
        stamp=datetime.fromisoformat(data['datetime']);zone=data['timezone']
        if stamp.tzinfo is None:raise AcuityError('invalid_datetime',True)
        choices=times(stamp.astimezone(ZoneInfo(zone)).date(),zone)
        if not any(datetime.fromisoformat(c['time'])==stamp for c in choices):raise AcuityError('not_available',True)
        if kind['id']==201 and not any(str(f['id'])=='401' and str(f['value']).strip() for f in data.get('fields',[])):raise AcuityError('required_field',True)
        item=AcuityMockAppointment(slot='101:'+stamp.astimezone(timezone.utc).isoformat(),payload={})
        db.session.add(item)
        try:db.session.flush()
        except IntegrityError:db.session.rollback();raise AcuityError('not_available',True) from None
        item.payload=dict(id=item.id,calendarID=101,appointmentTypeID=kind['id'],datetime=stamp.isoformat(),duration=str(kind['duration']),
            timezone=zone,firstName=data['firstName'],lastName=data['lastName'],email=data['email'],price=kind['price'],paid='no',
            canceled=False,location='Local practice session — no real meeting',forms=[])
        db.session.commit()
        if cfg.scenario=='timeout_after_create':raise AcuityError('connection_failed')
        return deepcopy(item.payload)
    if method=='PUT' and path.startswith('appointments/') and path.endswith('/cancel'):
        item=db.session.get(AcuityMockAppointment,int(path.split('/')[1]))
        if not item:raise AcuityError('not_found',True)
        payload=dict(item.payload);payload['canceled']=True;payload['noShow']=False;item.payload=payload;item.slot=None;db.session.commit()
        return deepcopy(payload)
    if method=='GET' and path.startswith('appointments/'):
        if cfg.scenario=='sync_failure':raise AcuityError('connection_failed')
        item=db.session.get(AcuityMockAppointment,int(path.split('/')[-1]))
        if not item:raise AcuityError('not_found',True)
        return deepcopy(item.payload)
    if method=='GET' and path=='appointments':
        rows=[]
        for item in AcuityMockAppointment.query.order_by(AcuityMockAppointment.id.desc()):
            data=deepcopy(item.payload)
            if params.get('email') and data['email']!=params['email']:continue
            if params.get('calendarID') and str(data['calendarID'])!=str(params['calendarID']):continue
            if params.get('appointmentTypeID') and str(data['appointmentTypeID'])!=str(params['appointmentTypeID']):continue
            if params.get('minDate') and data['datetime'][:10]<params['minDate']:continue
            if params.get('maxDate') and data['datetime'][:10]>params['maxDate']:continue
            if not params.get('showall') and data['canceled']:continue
            rows.append(data)
        return rows[:int(params.get('max',100))]
    if path=='webhooks':
        if method=='POST':cfg.webhook_target=data['target'];db.session.commit()
        return ([{'id':1,'event':'appointment.changed','target':cfg.webhook_target,'status':'active'}] if cfg.webhook_target else []) if method=='GET' else {'id':1,'event':'appointment.changed','target':cfg.webhook_target,'status':'active'}
    raise AcuityError('unsupported_mock_endpoint',True)
