import os

import click
from dotenv import load_dotenv
from flask import Flask, request
from sqlalchemy import inspect, text
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import generate_password_hash

from .extensions import csrf, db, login_manager
from .models import MentorApplication, User


def create_app():
    load_dotenv()

    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.getenv(
        "SECRET_KEY",
        "development-only-change-me",
    )
    database_url = _database_url()
    app.config["SQLALCHEMY_DATABASE_URI"] = database_url
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    if database_url.startswith("postgresql"):
        app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
            "pool_pre_ping": True,
            "pool_recycle": 300,
            "pool_size": 3,
            "max_overflow": 2,
            "pool_timeout": 30,
        }

    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

    if _is_production():
        app.config["SESSION_COOKIE_SECURE"] = True
        app.config["PREFERRED_URL_SCHEME"] = "https"

    app.wsgi_app = ProxyFix(
        app.wsgi_app,
        x_for=1,
        x_proto=1,
        x_host=1,
    )

    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)

    login_manager.login_view = "admin.login"
    login_manager.login_message = (
        "Please sign in to access the logistics dashboard."
    )

    from .admin import admin_bp
    from .public import public_bp

    app.register_blueprint(public_bp)
    app.register_blueprint(admin_bp)

    @app.get("/healthz")
    def health_check():
        try:
            db.session.execute(text("SELECT 1"))
        except Exception:
            app.logger.exception("Database health check failed.")
            return {"status": "unhealthy"}, 503

        return {"status": "ok"}, 200

    @app.after_request
    def add_security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        if request.path.startswith("/admin") or request.path == "/login":
            response.headers["Cache-Control"] = (
                "no-store, no-cache, must-revalidate, max-age=0"
            )
            response.headers["Pragma"] = "no-cache"
            response.headers["X-Frame-Options"] = "DENY"

        return response

    @app.cli.command("create-admin")
    @click.option("--email", prompt=True)
    @click.option(
        "--password",
        prompt=True,
        hide_input=True,
        confirmation_prompt=True,
    )
    def create_admin(email, password):
        normalized_email = email.strip().lower()
        existing = User.query.filter_by(email=normalized_email).first()

        if existing:
            raise click.ClickException(
                "A user with that email already exists."
            )

        user = User(
            name="Administrator",
            email=normalized_email,
            password_hash=generate_password_hash(password),
            role="admin",
            active=True,
        )
        db.session.add(user)
        db.session.commit()
        click.echo(f"Created administrator: {normalized_email}")

    @app.cli.command("reset-admin-password")
    @click.option("--email", prompt=True)
    @click.option(
        "--password",
        prompt=True,
        hide_input=True,
        confirmation_prompt=True,
    )
    def reset_admin_password(email, password):
        normalized_email = email.strip().lower()
        user = User.query.filter_by(email=normalized_email).first()

        if user is None:
            raise click.ClickException(
                "No user exists with that email address."
            )

        user.password_hash = generate_password_hash(password)
        user.active = True
        db.session.commit()
        click.echo(f"Password reset for: {normalized_email}")

    with app.app_context():
        _reset_local_prototype_schema_if_needed(app)
        db.create_all()
        _create_environment_admin()

    return app


def _database_url():
    database_url = os.getenv(
        "DATABASE_URL",
        "sqlite:///ttbg.db",
    ).strip()

    if database_url.startswith("postgresql://"):
        return database_url.replace(
            "postgresql://",
            "postgresql+psycopg://",
            1,
        )

    if database_url.startswith("postgres://"):
        return database_url.replace(
            "postgres://",
            "postgresql+psycopg://",
            1,
        )

    return database_url


def _is_production():
    return bool(
        os.getenv("RENDER")
        or os.getenv("RENDER_EXTERNAL_HOSTNAME")
    )


def _reset_local_prototype_schema_if_needed(app):
    """
    During local SQLite development only, reset the disposable application
    table when the real TTBG form schema is introduced. User accounts remain.
    Production databases must use proper migrations instead.
    """
    database_uri = app.config["SQLALCHEMY_DATABASE_URI"]

    if not database_uri.startswith("sqlite"):
        return

    inspector = inspect(db.engine)
    if MentorApplication.__tablename__ not in inspector.get_table_names():
        return

    existing_columns = {
        column["name"]
        for column in inspector.get_columns(
            MentorApplication.__tablename__
        )
    }
    required_columns = {
        "preferred_contact_method",
        "area_of_expertise",
        "about_yourself",
        "support_areas",
        "acknowledgement",
    }

    if not required_columns.issubset(existing_columns):
        MentorApplication.__table__.drop(db.engine)


def _create_environment_admin():
    email = os.getenv("ADMIN_EMAIL", "").strip().lower()
    password = os.getenv("ADMIN_PASSWORD", "")

    if not email or not password:
        return

    if User.query.filter_by(email=email).first():
        return

    user = User(
        name="Destinee / Logistics",
        email=email,
        password_hash=generate_password_hash(password),
        role="admin",
        active=True,
    )
    db.session.add(user)
    db.session.commit()
