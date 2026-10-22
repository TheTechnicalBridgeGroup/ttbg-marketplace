import os
from datetime import timedelta
from flask import Flask, render_template, request, session, redirect, url_for, flash, got_request_exception, g
from flask_login import LoginManager, current_user, logout_user
from flask_wtf import CSRFProtect
from dotenv import load_dotenv
from .models import db, User

def create_app(config=None):
    load_dotenv()
    app = Flask(__name__)
    url = os.getenv('DATABASE_URL','sqlite:///marketplace.db')
    if url.startswith('postgres://'): url = url.replace('postgres://','postgresql+psycopg://',1)
    elif url.startswith('postgresql://'): url = url.replace('postgresql://','postgresql+psycopg://',1)
    elif url.startswith('mysql://'): url = url.replace('mysql://','mysql+pymysql://',1)
    app.config.update(SECRET_KEY=os.getenv('SECRET_KEY'), SQLALCHEMY_DATABASE_URI=url,
        SQLALCHEMY_TRACK_MODIFICATIONS=False, SQLALCHEMY_ENGINE_OPTIONS={'pool_pre_ping':True},
        SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax',
        SESSION_COOKIE_SECURE=os.getenv('COOKIE_SECURE','true' if os.getenv('RENDER') else 'false').lower()=='true',
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8), MAX_CONTENT_LENGTH=6*1024*1024,
        PUBLIC_BASE_URL=os.getenv('PUBLIC_BASE_URL',''),
        TEST_RESERVATIONS_ENABLED=False)
    for key in ('ACUITY_USER_ID','ACUITY_API_KEY','STRIPE_SECRET_KEY','STRIPE_WEBHOOK_SECRET'):
        app.config[key]=os.getenv(key,'')
    for key in ('SMTP_HOST','SMTP_USERNAME','SMTP_PASSWORD','SMTP_FROM','TURNSTILE_SITE_KEY','TURNSTILE_SECRET_KEY','TURNSTILE_HOSTNAMES'):
        app.config[key]=os.getenv(key,'')
    app.config['SMTP_SECURITY']=os.getenv('SMTP_SECURITY','starttls')
    app.config['SMTP_PORT']=int(os.getenv('SMTP_PORT','465' if app.config['SMTP_SECURITY']=='ssl' else '587'))
    app.config['TURNSTILE_ENABLED']=os.getenv('TURNSTILE_ENABLED','false').lower()=='true'
    app.config['APP_ENV']=os.getenv('APP_ENV','production')
    app.config['ACUITY_MODE']=os.getenv('ACUITY_MODE','live').lower()
    app.config['ACUITY_WEBHOOK_SECRET']=os.getenv('ACUITY_WEBHOOK_SECRET','')
    app.config['STRIPE_MODE']=os.getenv('STRIPE_MODE','test').lower()
    app.config['PAYMENTS_ENABLED']=os.getenv('PAYMENTS_ENABLED','false').lower()=='true'
    app.config['STRIPE_LIVE_CONFIRMED']=os.getenv('STRIPE_LIVE_CONFIRMED','false').lower()=='true'
    app.config['STRIPE_ACCOUNT_ID']=os.getenv('STRIPE_ACCOUNT_ID','')
    app.config['STRIPE_CONNECT_WEBHOOK_SECRET']=os.getenv('STRIPE_CONNECT_WEBHOOK_SECRET','')
    app.config['PAYMENT_MAX_ADVANCE_DAYS']=int(os.getenv('PAYMENT_MAX_ADVANCE_DAYS','60'))
    app.config['PAYMENT_POLICY_TEXT']=os.getenv('PAYMENT_POLICY_TEXT','If TTBG cannot confirm your paid appointment, we refund the session payment. For other cancellations, contact TTBG for review before your session. Mentor transfers require completed-session approval.')
    for key in ('RENDER_API_KEY','RENDER_OWNER_ID','RENDER_WEB_SERVICE_ID','RENDER_WORKER_SERVICE_ID','PLANETSCALE_INSIGHTS_URL','PLANETSCALE_DATABASE_LABEL','PLANETSCALE_BRANCH_LABEL','DEPLOYMENT_LABEL','DIAGNOSTICS_DATABASE_URL'):
        app.config[key]=os.getenv(key,'')
    if config: app.config.update(config)
    from . import stripe_api
    with app.app_context():stripe_api.validate_runtime()
    if not 1<=app.config['PAYMENT_MAX_ADVANCE_DAYS']<=60:raise RuntimeError('PAYMENT_MAX_ADVANCE_DAYS must be between 1 and 60')
    from sqlalchemy.engine import make_url
    from urllib.parse import urlsplit
    dburl=make_url(app.config['SQLALCHEMY_DATABASE_URI'])
    if app.config['ACUITY_MODE'] not in ('live','mock'):raise RuntimeError('ACUITY_MODE must be live or mock.')
    if app.config['ACUITY_MODE']=='mock':
        base=urlsplit(app.config.get('PUBLIC_BASE_URL') or 'http://127.0.0.1:5000')
        if (app.config['APP_ENV']!='local' or os.getenv('RENDER') or base.hostname not in ('localhost','127.0.0.1','::1') or
            dburl.get_backend_name()!='sqlite' or not (app.testing and not dburl.database or os.path.basename(dburl.database or '')=='marketplace-mock.db')):
            raise RuntimeError('Mock Acuity requires APP_ENV=local, a localhost origin, and the separate SQLite marketplace-mock.db database. It is forbidden on Render.')
    elif os.path.basename(dburl.database or '')=='marketplace-mock.db':
        raise RuntimeError('Do not connect the mock database to live Acuity. Use your separate production database.')
    if not app.config['SECRET_KEY'] or len(app.config['SECRET_KEY'])<32:
        raise RuntimeError('Set SECRET_KEY to a random string of at least 32 characters in .env.')
    if os.getenv('RENDER'):
        from werkzeug.middleware.proxy_fix import ProxyFix
        hops=int(os.getenv('TRUSTED_PROXY_HOPS','1'))
        if not 0<=hops<=5:raise RuntimeError('TRUSTED_PROXY_HOPS must be between 0 and 5.')
        app.wsgi_app=ProxyFix(app.wsgi_app,x_proto=1,x_for=hops)
    db.init_app(app)
    CSRFProtect(app)
    login = LoginManager(app)
    login.login_view='main.login'
    @login.user_loader
    def load_user(uid): return db.session.get(User,int(uid)) if uid.isdigit() else None
    from .security import account_enabled, settings, ROLE_LABELS
    @app.before_request
    def enforce_access():
        if app.config['ACUITY_MODE']=='mock' and request.remote_addr not in ('127.0.0.1','::1'):
            return 'Local practice mode accepts loopback connections only.',403
        if request.endpoint in ('appointments.webhook','payments.webhook'):return None
        if current_user.is_authenticated:
            current_version=current_user.access.session_version if current_user.access else 0
            if not account_enabled(current_user) or session.get('auth_version',0)!=current_version:
                logout_user();session.clear()
                flash('Your session has ended. Sign in again or contact your administrator.','error')
                return redirect(url_for('main.login'))
        if current_user.is_authenticated:
            from .registration_security import email_allowed
            allowed=('static','main.logout','main.health','verification.notice','verification.confirm','control.password_reset','team.activate')
            if not email_allowed(current_user) and request.endpoint not in allowed:
                return redirect(url_for('verification.notice'))
        if request.endpoint not in ('static' ,'main.health','main.login','main.logout','control.password_reset','verification.notice','verification.confirm'):
            cfg=settings()
            if cfg.maintenance_mode and not (current_user.is_authenticated and current_user.role=='admin'):
                return render_template('maintenance.html'),503
    from .routes import bp
    app.register_blueprint(bp)
    from .team import bp as team_bp
    app.register_blueprint(team_bp)
    from .control import bp as control_bp
    app.register_blueprint(control_bp)
    from .photos import bp as photos_bp
    app.register_blueprint(photos_bp)
    from .support import bp as support_bp, capture_error
    app.register_blueprint(support_bp)
    from .acuity import bp as acuity_bp
    app.register_blueprint(acuity_bp)
    got_request_exception.connect(capture_error,app,weak=False)
    from .registration_security import bp as verification_bp
    app.register_blueprint(verification_bp)
    from .deletion import bp as deletion_bp
    app.register_blueprint(deletion_bp)
    from .knowledge import bp as knowledge_bp
    app.register_blueprint(knowledge_bp)
    from .appointments import bp as appointments_bp,webhook
    app.register_blueprint(appointments_bp)
    from .service_import import bp as service_import_bp
    app.register_blueprint(service_import_bp)
    app.extensions['csrf'].exempt(webhook)
    from .payments import bp as payments_bp,webhook as stripe_webhook
    app.register_blueprint(payments_bp)
    app.extensions['csrf'].exempt(stripe_webhook)
    from .payment_commands import register as register_payments
    register_payments(app)
    from .financial_routes import bp as financial_bp
    app.register_blueprint(financial_bp)
    from .diagnostics import bp as diagnostics_bp
    from . import render_logs
    app.register_blueprint(diagnostics_bp)
    from .finance import actor_label,cancelled_by,states,identity
    app.jinja_env.globals.update(actor_label=actor_label,cancelled_by=cancelled_by,financial_states=states,payment_identity=identity)
    from .acuity_commands import register as register_acuity_commands
    register_acuity_commands(app)
    from .commands import register_commands
    register_commands(app)
    from .forms import EmptyForm
    @app.context_processor
    def common():
        from .booking_config import scheduler_link
        from .registration_security import turnstile_enabled, email_label, mail_ready, turnstile_ready
        from .security import help_settings
        return {'payments_enabled':app.config['PAYMENTS_ENABLED'],'stripe_mode':app.config['STRIPE_MODE'],'payment_policy':app.config['PAYMENT_POLICY_TEXT'],'acuity_mode':app.config['ACUITY_MODE'],'help_settings':help_settings(),'turnstile_enabled':turnstile_enabled(),'turnstile_site_key':app.config.get('TURNSTILE_SITE_KEY',''),'email_label':email_label,'mail_ready':mail_ready(),'turnstile_ready':turnstile_ready(),'action_form':EmptyForm(formdata=None), 'platform_settings':settings(), 'role_labels':ROLE_LABELS, 'scheduler_link':scheduler_link, 'test_reservations_enabled':app.testing and app.config['TEST_RESERVATIONS_ENABLED']}
    @app.template_filter('money')
    def money(value): return f'${value/100:,.2f}'
    @app.template_filter('service_price')
    def service_price(value): return 'FREE' if value == 0 else money(value)
    @app.after_request
    def headers(response):
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['X-Frame-Options']='DENY'
        response.headers.setdefault('Referrer-Policy','strict-origin')
        response.headers['Content-Security-Policy']="default-src 'self'; style-src 'self'; img-src 'self' data:; script-src 'self'; form-action 'self' https://connect.stripe.com https://checkout.stripe.com; frame-ancestors 'none'; base-uri 'self'"
        from .registration_security import turnstile_enabled
        if turnstile_enabled() and request.endpoint in ('main.register','verification.notice'):
            response.headers['Content-Security-Policy']="default-src 'self'; style-src 'self'; img-src 'self' data:; script-src 'self' https://challenges.cloudflare.com; frame-src https://challenges.cloudflare.com; connect-src 'self' https://challenges.cloudflare.com; form-action 'self' https://connect.stripe.com https://checkout.stripe.com; frame-ancestors 'none'; base-uri 'self'"
        if response.mimetype=='text/html': response.headers['Cache-Control']='no-store'
        return response
    def error_page(error):
        if error.code==500:
            from .models import db
            db.session.rollback()
            try:return render_template('error.html',code=500),500
            except Exception:
                db.session.rollback()
                return app.jinja_env.get_template('error_fallback.html').render(reference=getattr(g,'error_reference',None)),500
        return render_template('error.html',code=error.code),error.code
    for code in (400,403,404,413,429,500):
        app.register_error_handler(code,error_page)
    return app
