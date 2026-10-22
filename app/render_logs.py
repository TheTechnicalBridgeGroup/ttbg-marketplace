"""Bounded Render GET transport; arbitrary provider text never reaches the UI."""
import json
import re
from urllib.parse import urlencode
from urllib.request import Request,build_opener
from urllib.error import URLError,HTTPError
from datetime import datetime,timedelta,timezone
from itsdangerous import URLSafeTimedSerializer,BadSignature
from flask import current_app,request,render_template,abort
from flask_login import current_user
from .acuity import NoRedirect
from .registration_security import rate_allowed
from .diagnostics import bp,access
from .routes import roles

class LogUnavailable(Exception):pass


def fetch(params):
    token=current_app.config.get('RENDER_API_KEY')
    if not token:raise LogUnavailable('Log access is not configured. Use the Render dashboard.')
    req=Request('https://api.render.com/v1/logs?'+urlencode(params),headers={'Authorization':'Bearer '+token,'Accept':'application/json'},method='GET')
    try:
        with build_opener(NoRedirect()).open(req,timeout=6) as response:
            raw=response.read(262145)
            if len(raw)>262144:raise LogUnavailable('The log response exceeded the safe size limit. Narrow the time range.')
            data=json.loads(raw)
            if not isinstance(data,dict) or not isinstance(data.get('logs'),list) or len(data['logs'])>50:raise ValueError()
            return data
    except (HTTPError,URLError,TimeoutError,OSError,ValueError):raise LogUnavailable('Render logs are unavailable or access was denied. Check the credential and service permissions in Render.') from None


def safe_entry(entry):
    # Redaction by allowlist, not an incomplete blacklist of possible secrets.
    # Free-form lines may contain arbitrary names, intake, tokens, or headers.
    # They are NEVER returned, even to admins, copied HTML, or exports.
    message=str(entry.get('message',''))[:20000]
    match=re.search(r'\bSupport reference ([A-F0-9]{16})\b',message)
    reference=match.group(1) if match else ''
    labels=entry.get('labels',[])
    labels={x.get('name'):x.get('value') for x in labels if isinstance(x,dict)} if isinstance(labels,list) else {}
    level=labels.get('level','')
    if level not in ('debug','info','warn','warning','error','fatal'):level='unclassified'
    status=str(labels.get('statusCode',''))
    status=status if re.fullmatch(r'[1-5][0-9]{2}',status) else ''
    category='Application log (free-form content withheld)'
    if reference:category='Application error; investigate the support reference'
    elif labels.get('type')=='request':category='HTTP request activity (URL, headers and client information withheld)'
    elif labels.get('type')=='build':category='Build activity (free-form content withheld)'
    elif re.search(r'\b(Booting worker|Starting gunicorn|Listening at)\b',message):category='Server startup activity'
    try:timestamp=datetime.fromisoformat(str(entry.get('timestamp','')).replace('Z','+00:00')).astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
    except (ValueError,TypeError):timestamp='Timestamp unavailable'
    return dict(timestamp=timestamp,level=level,status=status,reference=reference,message=category)


@bp.get('/admin/operations/logs')
@roles('admin')
def logs():
    access('Render logs')
    if not rate_allowed('render-logs','platform',6,60):abort(429)
    service=request.args.get('service','web')
    if service not in ('web','worker'):abort(400)
    resource=current_app.config.get('RENDER_WEB_SERVICE_ID' if service=='web' else 'RENDER_WORKER_SERVICE_ID','')
    if resource and not re.fullmatch(r'srv-[a-zA-Z0-9]+',resource):resource=''
    owner=current_app.config.get('RENDER_OWNER_ID','')
    window=request.args.get('minutes',60,type=int)
    if window not in (15,60,360,1440):abort(400)
    level=request.args.get('level','');status=request.args.get('status','');query=request.args.get('q','').strip()
    if level not in ('','info','warn','error','debug') or status and not re.fullmatch(r'[1-5][0-9]{2}',status) or len(query)>64:abort(400)
    end=datetime.now(timezone.utc);start=end-timedelta(minutes=window);page=1
    def iso(d):return d.isoformat().replace('+00:00','Z')
    params={'ownerId':owner,'resource':resource,'startTime':iso(start),'endTime':iso(end),'limit':50,'direction':'backward'}
    if level:params['level']=level
    if status:params['statusCode']=status
    # Filter safe summaries locally. User text is not sent as provider regex.
    signer=URLSafeTimedSerializer(current_app.secret_key,salt='render-logs-v09')
    token=request.args.get('cursor');next_cursor=None
    if token:
        try:
            state=signer.loads(token,max_age=600)
            if state['user']!=current_user.id or state['service']!=service or state['level']!=level or state['status']!=status or state['window']!=window or not 2<=state['page']<=5:abort(400)
            params.update(startTime=state['start'],endTime=state['end']);page=state['page']
        except (BadSignature,KeyError,TypeError):abort(400)
    error=None;rows=[]
    if not owner or not resource:error='Log access is not configured for this service. Use the Render dashboard.'
    else:
        try:
            data=fetch(params);rows=[safe_entry(row) for row in data['logs'] if isinstance(row,dict)]
            if query:rows=[row for row in rows if query.lower() in ' '.join(row.values()).lower()]
            if data.get('hasMore') and page<5:
                ns=datetime.fromisoformat(data['nextStartTime'].replace('Z','+00:00'));ne=datetime.fromisoformat(data['nextEndTime'].replace('Z','+00:00'))
                ps=datetime.fromisoformat(params['startTime'].replace('Z','+00:00'));pe=datetime.fromisoformat(params['endTime'].replace('Z','+00:00'))
                if not ps<=ns<=ne<=pe:raise ValueError()
                next_cursor=signer.dumps(dict(user=current_user.id,service=service,level=level,status=status,window=window,page=page+1,start=iso(ns),end=iso(ne)))
        except (LogUnavailable,KeyError,ValueError,TypeError) as exc:error=str(exc) if isinstance(exc,LogUnavailable) else 'Render returned an unsupported pagination response. Open the provider dashboard.'
    link='https://dashboard.render.com/web/'+resource+'/logs' if resource else 'https://dashboard.render.com'
    return render_template('diagnostics/logs.html',rows=rows,error=error,service=service,window=window,level=level,status=status,q=query,next_cursor=next_cursor,page=page,link=link)
