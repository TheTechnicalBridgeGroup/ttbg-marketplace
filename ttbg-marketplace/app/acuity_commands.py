"""Operational sync and loopback-only local scenario commands."""
import base64
import hashlib
import hmac
from datetime import datetime,timezone
from urllib.parse import urlencode
import click
from werkzeug.security import generate_password_hash
from .models import (db,User,Mentor,Service,ServiceScheduling,MentorDetails,AcuityAppointment,AcuitySyncJob,AcuityMockAppointment)
from . import acuity
from .security import settings

def local_only():
    from flask import current_app
    if acuity.mode()!='mock' or current_app.config['APP_ENV']!='local':raise click.ClickException('This command is available only in local mock mode.')

def register(app):
    @app.cli.command('setup-acuity-local')
    @click.password_option(confirmation_prompt=True)
    def setup(password):
        """Create local practice admin, mentor, and student accounts in the isolated mock DB."""
        local_only()
        if not acuity.configured():raise click.ClickException('Set ACUITY_USER_ID=1 and ACUITY_API_KEY=local-dummy-key.')
        if not 12<=len(password)<=128:raise click.ClickException('Use a password of 12–128 characters.')
        from .upgrade import upgrade
        from .registration_security import mark_trusted
        upgrade()
        addresses=['local.admin@example.com','local.mentor@example.com','local.student@example.com']
        if User.query.filter(User.email.in_(addresses)).first():raise click.ClickException('Practice accounts already exist. No passwords or data were changed.')
        users=[]
        for name,role,email in zip(('Local Admin','Local Mentor','Local Student'),('admin','mentor','student'),addresses):
            u=User(name=name,role=role,email=email,password_hash=generate_password_hash(password));db.session.add(u);mark_trusted(u);users.append(u)
        db.session.flush()
        m=Mentor(user_id=users[1].id,lane='Healthcare',title='Local practice mentor',bio='Practice the full TTBG scheduling flow locally.',experience='Local practice profile.',status='approved',acuity_calendar_id='101')
        db.session.add(m);db.session.flush()
        db.session.add(MentorDetails(mentor_id=m.id,activated_at=datetime.now(timezone.utc).replace(tzinfo=None),application_reviewed=True,credentials_reviewed=True,agreement_received=True,orientation_complete=True,profile_consent=True))
        s=Service(mentor_id=m.id,name='Mentoring practice session',description='A local-only session for testing appointment creation and sync.',price_cents=10000,duration=60,fee_bps=2000,acuity_type_id='201')
        db.session.add(s);db.session.flush();db.session.add(ServiceScheduling(service_id=s.id,provider='acuity',event_type_id='201'))
        cfg=settings();cfg.scheduling_provider='acuity';cfg.booking_mode='acuity_confirmed';cfg.fee_bps=2000
        from .acuity_mock import config
        config();db.session.commit()
        click.echo('Local accounts created with your chosen password (email verification exempt in this isolated practice DB):')
        for email in addresses:click.echo(email)
        click.echo('Calendar ID: 101; appointment type ID: 201. Sign in as the student to book.')

    @app.cli.command('acuity-mock-scenario')
    @click.argument('scenario',type=click.Choice(['normal','unavailable','timeout_after_create','sync_failure']))
    def scenario(scenario):
        local_only()
        from .acuity_mock import config
        config().scenario=scenario;db.session.commit();click.echo('Local scenario: '+scenario)

    @app.cli.command('acuity-mock-change')
    @click.option('--id','pid',required=True,type=int)
    @click.option('--action',required=True,type=click.Choice(['reschedule','cancel','paid']))
    @click.option('--time','time_value',help='New ISO timestamp with UTC offset for reschedule.')
    def change(pid,action,time_value):
        """Change a simulated provider record and deliver a correctly signed local webhook."""
        local_only();item=db.session.get(AcuityMockAppointment,pid)
        if not item:raise click.ClickException('Local appointment not found.')
        data=dict(item.payload)
        if action=='reschedule':
            from .appointments import stamp
            from .acuity_mock import times
            from zoneinfo import ZoneInfo
            try:
                utc=stamp(time_value).replace(tzinfo=timezone.utc)
                if not any(datetime.fromisoformat(x['time'])==utc for x in times(utc.astimezone(ZoneInfo(data['timezone'])).date(),data['timezone'])):raise ValueError()
            except (acuity.AcuityError,ValueError,TypeError):raise click.ClickException('Choose a free weekday slot at 10:00, 13:00, or 15:00 America/New_York, using an explicit UTC offset.')
            item.slot='101:'+utc.isoformat();data['datetime']=utc.isoformat();data['canceled']=False
        elif action=='cancel':item.slot=None;data['canceled']=True
        elif action=='paid':data['paid']='yes'
        item.payload=data;db.session.commit()
        action_name={'reschedule':'rescheduled','cancel':'canceled','paid':'changed'}[action]
        raw=urlencode({'action':action_name,'id':pid,'calendarID':101,'appointmentTypeID':201}).encode()
        signature=base64.b64encode(hmac.new(app.config['ACUITY_API_KEY'].encode(),raw,hashlib.sha256).digest()).decode()
        response=app.test_client().post('/webhooks/acuity',data=raw,content_type='application/x-www-form-urlencoded',headers={'X-Acuity-Signature':signature})
        click.echo(f'Local provider updated; signed webhook response {response.status_code}.')
        if response.status_code!=204:raise click.ClickException('Synchronization did not finish. The retry is saved; use sync-acuity after restoring normal mode.')

    @app.cli.command('sync-acuity')
    @click.option('--limit',default=500,type=click.IntRange(1,5000))
    def sync(limit):
        """Retry saved sync jobs, then refresh the least-recently-synced appointments."""
        from .appointments import sync_one
        if not acuity.configured():raise click.ClickException('Acuity credentials are not configured.')
        ids=[j.provider_id for j in AcuitySyncJob.query.filter_by(scope=acuity.scope(),pending=True).order_by(AcuitySyncJob.received_at).limit(limit)]
        ids+= [a.provider_id for a in AcuityAppointment.query.filter_by(scope=acuity.scope()).order_by(AcuityAppointment.last_synced_at).limit(limit)]
        ids=list(dict.fromkeys(ids))[:limit];success=failed=0
        for pid in ids:
            try:sync_one(pid);success+=1
            except acuity.AcuityError:failed+=1
        click.echo(f'Synchronized: {success}; pending retry: {failed}. No appointment creation requests were retried.')
        if failed:raise click.ClickException('Some records need another sync attempt. See Support > Appointment sync.')
