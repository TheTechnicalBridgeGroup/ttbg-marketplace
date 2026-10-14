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
    if config: app.config.update(config)
    if not app.config['SECRET_KEY'] or len(app.config['SECRET_KEY'])<32:
        raise RuntimeError('Set SECRET_KEY to a random string of at least 32 characters in .env.')
    if os.getenv('RENDER'):
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app=ProxyFix(app.wsgi_app,x_proto=1)
    db.init_app(app)
    CSRFProtect(app)
    login = LoginManager(app)
    login.login_view='main.login'
    @login.user_loader
    def load_user(uid): return db.session.get(User,int(uid)) if uid.isdigit() else None
    from .security import account_enabled, settings, ROLE_LABELS
    @app.before_request
    def enforce_access():
        if current_user.is_authenticated:
            current_version=current_user.access.session_version if current_user.access else 0
            if not account_enabled(current_user) or session.get('auth_version',0)!=current_version:
                logout_user();session.clear()
                flash('Your session has ended. Sign in again or contact your administrator.','error')
                return redirect(url_for('main.login'))
        if request.endpoint not in ('static','main.health','main.login','main.logout','control.password_reset'):
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
    from .commands import register_commands
    register_commands(app)
    from .forms import EmptyForm
    @app.context_processor
    def common():
        from .booking_config import scheduler_link
        return {'action_form':EmptyForm(formdata=None), 'platform_settings':settings(), 'role_labels':ROLE_LABELS, 'scheduler_link':scheduler_link, 'test_reservations_enabled':app.testing and app.config['TEST_RESERVATIONS_ENABLED']}
    @app.template_filter('money')
    def money(value): return f'${value/100:,.2f}'
    @app.after_request
    def headers(response):
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['X-Frame-Options']='DENY'
        response.headers.setdefault('Referrer-Policy','strict-origin')
        response.headers['Content-Security-Policy']="default-src 'self'; style-src 'self'; img-src 'self' data:; script-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'self'"
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
