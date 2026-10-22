"""Admin-only, bounded, read-only operational investigation.

Only diagnostic access/audit/probe metadata is written. Provider reads never
invoke payment reconciliation, booking writes, refunds, or configuration changes.
"""
import re
import secrets
from datetime import timedelta,datetime,timezone
from urllib.parse import urlsplit
from sqlalchemy import select,text,or_,create_engine
from sqlalchemy.exc import SQLAlchemyError
from flask import Blueprint,abort,current_app,render_template,request,redirect,url_for,flash
from flask_login import current_user
from .models import (db,now,DiagnosticProbe,DiagnosticEvent,SchemaRevision,PaymentWorkerHealth,StripeEvent,
    AcuitySyncJob,PaymentNotice,SupportIncident,PaymentIdentity,AcuityRequest,AcuityAppointment,PaymentOrder,PaymentOperation,FinancialEvent)
from .routes import roles
from .security import log
from .forms import EmptyForm
from .registration_security import rate_allowed,mail_ready,turnstile_ready,turnstile_enabled
from . import acuity,stripe_api as stripe

bp=Blueprint('diagnostics',__name__)
REVISION='v0.9-stability-diagnostics'


def access(action):
    if not rate_allowed('diagnostics',str(current_user.id),30,60):abort(429)
    log('Diagnostic access',action,'Read-only diagnostic view; filters and payloads not logged.');db.session.commit()


def record(component,code,service=None,starts=None,request_id=None):
    # Callers pass classifications, never arbitrary exception text.
    reference=secrets.token_hex(8).upper()
    if not re.fullmatch(r'[a-z_]{1,40}',component):component='application'
    if not re.fullmatch(r'[a-z_]{1,80}',code):code='operation_failed'
    ids=acuity.mapping(service) if service else {}
    db.session.add(DiagnosticEvent(reference=reference,component=component,code=code,
        service_id=service.id if service else None,user_id=current_user.id if current_user.is_authenticated else None,
        request_id=request_id,calendar_id=(ids or {}).get('calendarID'),type_id=(ids or {}).get('appointmentTypeID'),
        starts_at=starts,duration=service.duration if service else None,price_cents=service.price_cents if service else None))
    db.session.commit();return reference


def probe(name,state):
    item=db.session.get(DiagnosticProbe,name) or DiagnosticProbe(name=name)
    item.state=state;item.checked_at=now();db.session.add(item)


def safe_link(value,host):
    try:
        p=urlsplit(value)
        return value if p.scheme=='https' and p.hostname==host and not p.username and not p.password and not p.query and not p.fragment and p.port in (None,443) else None
    except ValueError:return None


@bp.get('/admin/operations')
@roles('admin')
def overview():
    access('operations')
    checks=[]
    def add(name,state,detail):checks.append(dict(name=name,state=state,detail=detail))
    add('Marketplace web service','Responding',f"v0.9.0 · {current_app.config['APP_ENV']} · Deployment: {current_app.config.get('DEPLOYMENT_LABEL') or 'Not supplied'}")
    try:db.session.execute(select(1));add('Database','Reachable','Authenticated SELECT succeeded. This does not measure query latency trends.')
    except SQLAlchemyError:db.session.rollback();add('Database','Unavailable','Use the hosting dashboard to inspect connectivity.')
    ready=db.session.get(SchemaRevision,REVISION)
    add('Schema','Ready' if ready else 'Action required','v0.9 migration applied.' if ready else 'Run the documented init-db upgrade before enabling bookings.')
    worker=db.session.get(PaymentWorkerHealth,stripe.scope())
    last=worker.completed_at if worker else None
    add('Payment worker','Recent reconciliation' if last and now()-last<timedelta(minutes=5) else 'Delayed / unavailable',f'Last completed: {last or "Never observed"} UTC. Check the worker if older than five minutes.')
    for name,label,present in [('stripe','Stripe platform',bool(current_app.config.get('STRIPE_SECRET_KEY'))),('acuity','Acuity API',acuity.configured()),('acuity_webhook','Acuity webhook registration',False)]:
        row=db.session.get(DiagnosticProbe,name)
        add(label,row.state if row else 'Not tested',f'Credential present: {present}. Last read check: {row.checked_at if row else "Never"} UTC. Mode: {stripe.mode() if name=="stripe" else acuity.mode()}. Checks are observations, not ongoing health guarantees.')
    se=StripeEvent.query.filter_by(scope=stripe.scope()).order_by(StripeEvent.received_at.desc()).first()
    add('Stripe webhook delivery','Received' if se else 'Not observed',f'Last signed delivery: {se.received_at if se else "Never"} UTC; pending events: {StripeEvent.query.filter_by(scope=stripe.scope(),pending=True).count()}.')
    aj=AcuitySyncJob.query.filter_by(scope=acuity.scope()).order_by(AcuitySyncJob.received_at.desc()).first()
    add('Acuity synchronization','Review saved jobs',f'Last sync activity: {aj.received_at if aj else "Never"} UTC; pending jobs: {AcuitySyncJob.query.filter_by(scope=acuity.scope(),pending=True).count()}. Sync jobs can also be created manually; activity alone does not prove webhook delivery.')
    delivery=db.session.get(DiagnosticProbe,'acuity_delivery')
    add('Acuity webhook delivery',delivery.state if delivery else 'Not observed',f'Last signed delivery: {delivery.checked_at if delivery else "Never"} UTC. Registration alone is not delivery.')
    add('Email delivery','Configured' if mail_ready() else 'Action required',f'Pending/uncertain financial notices: {PaymentNotice.query.filter(PaymentNotice.state!="sent").count()}. SMTP acceptance is not inbox delivery.')
    add('Turnstile','Configuration ready' if turnstile_enabled() and turnstile_ready() else 'Disabled' if not turnstile_enabled() else 'Incomplete configuration','Registration and verification resend forms are protected when enabled. This is configuration readiness, not a live challenge test.')
    add('PlanetScale Insights','Provider dashboard',f'Database: {current_app.config.get("PLANETSCALE_DATABASE_LABEL") or "Not supplied"}; branch: {current_app.config.get("PLANETSCALE_BRANCH_LABEL") or "Not supplied"}. Query error trends, slow queries and connection metrics must be reviewed in PlanetScale; no monitoring API is connected.')
    return render_template('diagnostics/overview.html',checks=checks,insights=safe_link(current_app.config.get('PLANETSCALE_INSIGHTS_URL',''),'app.planetscale.com') or 'https://app.planetscale.com',form=EmptyForm())


@bp.post('/admin/operations/check')
@roles('admin')
def check():
    if not EmptyForm().validate_on_submit():abort(400)
    access('connectivity checks')
    if not rate_allowed('diagnostic-probes','platform',2,60):abort(429)
    try:
        data=stripe.api('GET','account')
        verified=data.get('country')=='US' and data.get('default_currency')=='usd' and data.get('id')==current_app.config.get('STRIPE_ACCOUNT_ID')
        probe('stripe','Account verified' if verified else 'Account configuration needs review')
    except (stripe.StripeError,ValueError,TypeError):probe('stripe','Connection failed')
    try:
        data=acuity.api_get('me')
        if not isinstance(data,dict):raise acuity.AcuityError('invalid_response')
        probe('acuity','Connection verified')
        hooks=acuity.api_get('webhooks')
        target=(current_app.config.get('PUBLIC_BASE_URL') or '').rstrip('/')+'/webhooks/acuity'
        present=isinstance(hooks,list) and any(h.get('target')==target for h in hooks if isinstance(h,dict))
        probe('acuity_webhook','Registered; delivery is separate' if present else 'Destination not found')
    except (acuity.AcuityError,ValueError,TypeError):probe('acuity','Connection check failed')
    db.session.commit();flash('Read checks completed. No provider settings or financial records were changed.','success')
    return redirect(url_for('diagnostics.overview'))


# Explicit table AND column allowlists. No model discovery, SELECT *, PII, JSON
# payloads, free-text intake, credentials, reset tokens, or arbitrary SQL.
VIEWS={
 'market_user':('Accounts',('id','role','created_at')),
 'market_booking':('Bookings',('id','student_id','mentor_id','service_id','start','duration','price_cents','status','payment_status')),
 'market_acuity_request':('Booking requests',('id','user_id','service_id','calendar_id','type_id','starts_at','duration','price_cents','state','error_code','created_at')),
 'market_acuity_appointment':('Acuity snapshots',('id','provider_id','request_id','booking_id','calendar_id','type_id','starts_at','duration','cancelled','sync_state','last_synced_at')),
 'market_acuity_sync_job':('Acuity sync jobs',('id','provider_id','pending','error_code','received_at','processed_at')),
 'market_payment_order':('Payments',('id','payment_state','booking_state','session_id','intent_id','charge_id','transfer_id','gross_cents','refunded_cents','error_code','created_at','checked_at')),
 'market_payment_identity':('Payment references',('id','order_id','reference','payment_status','appointment_status','earnings_status','needs_review')),
 'market_payment_operation':('Payment operations',('id','order_id','kind','state','response_id','error_code','created_at','attempted_at','lease_until')),
 'market_stripe_event':('Stripe webhook events',('id','event_id','event_type','object_id','pending','error_code','received_at','checked_at')),
 'market_schema_revision':('Schema revisions',('name','applied_at')),
 'market_diagnostic_event':('Diagnostic events',('id','reference','component','code','service_id','user_id','request_id','calendar_id','type_id','starts_at','duration','price_cents','created_at')),
}


def read_rows(query):
    # Dedicated least-privilege SELECT credentials may be supplied. Audit writes
    # remain on the normal app connection, never on this read-only connection.
    uri=current_app.config.get('DIAGNOSTICS_DATABASE_URL')
    engine=db.engine
    if uri:
        engine=current_app.extensions.get('diagnostics_engine')
        if engine is None:
            engine=create_engine(uri,pool_pre_ping=True,pool_size=2,max_overflow=0,pool_timeout=3)
            current_app.extensions['diagnostics_engine']=engine
    with engine.connect() as con:
        dialect=con.dialect.name
        raw=None
        try:
            if dialect=='postgresql':con.execute(text("SET LOCAL statement_timeout = '2000ms'"));con.execute(text('SET TRANSACTION READ ONLY'))
            elif dialect=='mysql':
                con.execute(text('START TRANSACTION READ ONLY'))
                # Vitess can ignore MySQL's session max_execution_time. Use its
                # documented per-query directive as well as the MySQL hint.
                query=query.prefix_with('/*vt+ QUERY_TIMEOUT_MS=2000 */ /*+ MAX_EXECUTION_TIME(2000) */')
            elif dialect=='sqlite':
                import time
                deadline=time.monotonic()+2;raw=con.connection.driver_connection
                raw.set_progress_handler(lambda:int(time.monotonic()>deadline),1000)
            return list(con.execute(query).mappings())
        finally:
            con.rollback()
            if raw:raw.set_progress_handler(None,0)


def explorer():
    access('record explorer')
    name=request.args.get('table','market_user')
    if name not in VIEWS:abort(404)
    if request.args.get('format'):abort(400)
    page=request.args.get('page',1,type=int)
    if not 1<=page<=20:abort(400)
    table=db.metadata.tables[name];label,names=VIEWS[name]
    cols=[table.c[n] for n in names if n in table.c]
    q=request.args.get('q','').strip()
    if len(q)>100 or q and not re.fullmatch(r'[A-Za-z0-9_.:-]+',q):abort(400)
    query=select(*cols)
    if q:
        targets=[c for c in cols if c.name in ('id','user_id','student_id','mentor_id','service_id','booking_id','request_id','order_id','reference','provider_id','response_id','intent_id','session_id','charge_id','transfer_id','event_id','object_id','name')]
        clauses=[]
        for col in targets:
            if isinstance(col.type,db.Integer):
                if q.isdigit() and len(q)<19:clauses.append(col==int(q))
            else:clauses.append(col==q)
        if not clauses:abort(400)
        query=query.where(or_(*clauses))
    for key,operator in [('from',lambda c,d:c>=d),('to',lambda c,d:c<d+timedelta(days=1))]:
        value=request.args.get(key)
        if value:
            if 'created_at' not in table.c:abort(400)
            try:day=datetime.strptime(value,'%Y-%m-%d')
            except ValueError:abort(400)
            query=query.where(operator(table.c.created_at,day))
    query=query.order_by(*[c.desc() for c in table.primary_key.columns]).offset((page-1)*25).limit(26)
    error=None
    try:rows=read_rows(query)
    except SQLAlchemyError:rows=[];error='Records could not be read within the diagnostic limit. Check the read-only connection or narrow the search.'
    return render_template('diagnostics/records.html',views=VIEWS,name=name,label=label,columns=cols,rows=rows[:25],more=len(rows)>25,page=page,q=q,error=error)


@bp.get('/admin/operations/investigate')
@roles('admin')
def investigate():
    access('booking and incident investigation')
    q=request.args.get('q','').strip()
    if len(q)>100 or q and not re.fullmatch(r'[A-Za-z0-9_-]+',q):abort(400)
    request_row=None;order=None;events=[];operations=[];mirror=None;incident=None
    diagnostic=DiagnosticEvent.query.filter_by(reference=q).first() if q else None
    if q:
        identity=PaymentIdentity.query.filter_by(reference=q).first()
        request_row=db.session.get(AcuityRequest,identity.order_id if identity else q)
        if not request_row and q.isdigit():
            mirror=AcuityAppointment.query.filter_by(booking_id=int(q)).first()
            if mirror and mirror.request_id:request_row=db.session.get(AcuityRequest,mirror.request_id)
        incident=SupportIncident.query.filter_by(reference=q).first()
    if request_row:
        order=db.session.get(PaymentOrder,request_row.id)
        mirror=AcuityAppointment.query.filter_by(request_id=request_row.id).first()
        events=FinancialEvent.query.filter_by(order_id=request_row.id).order_by(FinancialEvent.created_at.desc()).limit(50).all()
        operations=PaymentOperation.query.filter_by(order_id=request_row.id).order_by(PaymentOperation.created_at.desc()).limit(25).all()
    recent=DiagnosticEvent.query.order_by(DiagnosticEvent.id.desc()).limit(25).all() if not q else []
    return render_template('diagnostics/investigate.html',q=q,r=request_row,order=order,mirror=mirror,events=events,operations=operations,incident=incident,diagnostic=diagnostic,recent=recent)
