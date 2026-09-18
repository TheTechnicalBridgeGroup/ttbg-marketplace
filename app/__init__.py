import os
from datetime import timedelta
from flask import Flask, render_template
from flask_login import LoginManager
from flask_wtf import CSRFProtect
from dotenv import load_dotenv
from .models import db, User
import certifi

def create_app(config=None):
    load_dotenv()
    app = Flask(__name__)
    url = os.getenv('DATABASE_URL','sqlite:///marketplace.db')
    if url.startswith('postgres://'): url = url.replace('postgres://','postgresql+psycopg://',1)
    elif url.startswith('postgresql://'): url = url.replace('postgresql://','postgresql+psycopg://',1)
    elif url.startswith('mysql://'): url = url.replace('mysql://','mysql+pymysql://',1)
            engine_options = {'pool_pre_ping': True}
        
        if url.startswith('postgresql+psycopg://'):
            engine_options['connect_args'] = {
                'sslmode': 'verify-full',
                'sslrootcert': certifi.where()
            }
        
        app.config.update(
            SECRET_KEY=os.getenv('SECRET_KEY'),
            SQLALCHEMY_DATABASE_URI=url,
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
            SQLALCHEMY_ENGINE_OPTIONS=engine_options,
        SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax',
        SESSION_COOKIE_SECURE=os.getenv('COOKIE_SECURE','false').lower()=='true',
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8), MAX_CONTENT_LENGTH=64*1024,
        PUBLIC_BASE_URL=os.getenv('PUBLIC_BASE_URL',''),
        DEMO_BOOKING_ENABLED=os.getenv('DEMO_BOOKING_ENABLED','true').lower()=='true')
    if config: app.config.update(config)
    if not app.config['SECRET_KEY'] or len(app.config['SECRET_KEY'])<32:
        raise RuntimeError('Set SECRET_KEY to a random string of at least 32 characters in .env.')
    db.init_app(app)
    CSRFProtect(app)
    login = LoginManager(app)
    login.login_view='main.login'
    @login.user_loader
    def load_user(uid): return db.session.get(User,int(uid)) if uid.isdigit() else None
    from .routes import bp
    app.register_blueprint(bp)
    from .team import bp as team_bp
    app.register_blueprint(team_bp)
    from .commands import register_commands
    register_commands(app)
    from .forms import EmptyForm
    @app.context_processor
    def common(): return {'action_form':EmptyForm(), 'demo_enabled':app.config['DEMO_BOOKING_ENABLED']}
    @app.template_filter('money')
    def money(value): return f'${value/100:,.2f}'
    @app.after_request
    def headers(response):
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['X-Frame-Options']='DENY'
        response.headers['Referrer-Policy']='no-referrer'
        response.headers['Content-Security-Policy']="default-src 'self'; style-src 'self'; img-src 'self' data:; script-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'self'"
        if response.mimetype=='text/html': response.headers['Cache-Control']='no-store'
        return response
    for code in (400,403,404,429,500):
        app.register_error_handler(code, lambda e: (render_template('error.html',code=e.code),e.code))
    return app
