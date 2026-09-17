import secrets
import click
from werkzeug.security import generate_password_hash
from .models import db, User, Mentor, Service, now, MentorInvitation

def register_commands(app):
    @app.cli.command('init-db')
    def init_db():
        db.create_all(); click.echo('Marketplace tables created. No existing tables or data were replaced.')
    @app.cli.command('create-admin')
    @click.option('--email',prompt=True)
    @click.option('--name',prompt=True)
    @click.password_option(confirmation_prompt=True)
    def create_admin(email,name,password):
        if len(password)<12: raise click.ClickException('Use at least 12 characters.')
        if User.query.filter_by(email=email.strip().lower()).first(): raise click.ClickException('Email already exists; no changes made.')
        db.session.add(User(email=email.strip().lower(),name=name,password_hash=generate_password_hash(password),role='admin'))
        db.session.commit(); click.echo('Admin created.')
    @app.cli.command('create-onboarding-user')
    @click.option('--email',prompt=True)
    @click.option('--name',prompt=True)
    @click.password_option(confirmation_prompt=True)
    def create_onboarding_user(email,name,password):
        from email_validator import validate_email, EmailNotValidError
        try: email=validate_email(email,check_deliverability=False).normalized.lower()
        except EmailNotValidError as e: raise click.ClickException(str(e))
        if len(password)<12:raise click.ClickException('Use at least 12 characters.')
        if not name.strip() or len(name)>100:raise click.ClickException('Enter a name of 1–100 characters.')
        if User.query.filter_by(email=email).first():raise click.ClickException('Email already exists; no changes made.')
        db.session.add(User(email=email,name=name.strip(),password_hash=generate_password_hash(password),role='onboarding'))
        db.session.commit();click.echo('Onboarding team account created. They can manage mentor profiles and services in Workspace.')
    @app.cli.command('reset-password')
    @click.option('--email',prompt=True)
    @click.password_option(confirmation_prompt=True)
    def reset_password(email,password):
        u=User.query.filter_by(email=email.strip().lower()).first()
        if not u: raise click.ClickException('Account not found.')
        if len(password)<12: raise click.ClickException('Use at least 12 characters.')
        u.password_hash=generate_password_hash(password)
        if u.mentor:
            from .onboarding_logic import details_for
            details_for(u.mentor).activated_at=now()
            MentorInvitation.query.filter_by(mentor_id=u.mentor.id).delete()
        db.session.commit();click.echo('Password updated; any mentor activation link was revoked.')
    @app.cli.command('seed-demo')
    def seed_demo():
        profiles=[('Jordan Ellis','Healthcare','Surgical technology mentor','JE','CST exam preparation',10000,'Build confidence in surgical concepts, instrumentation, and exam preparation. Bring your questions and leave with a focused study plan.'),
        ('Avery Morgan','Technology','Software & career mentor','AM','Career direction & portfolio review',7500,'Make your next step in technology clearer. Work through programming fundamentals, projects, and a practical plan for entering the field.'),
        ('Taylor Brooks','Beauty & Wellness','Beauty industry mentor','TB','Cosmetology study support',6500,'Turn classroom learning into confident practice with structured study support and guidance for your next career milestone.'),
        ('Riley Carter','Business & More','Career development mentor','RC','Resume & interview preparation',8000,'Translate your experience into a clear career story. Get support preparing your resume, interviews, and next professional step.')]
        for name,lane,title,initials,service,price,bio in profiles:
            email=initials.lower()+'@demo.invalid'
            if User.query.filter_by(email=email).first(): continue
            u=User(name=name,email=email,role='mentor',password_hash=generate_password_hash(secrets.token_urlsafe(40)));db.session.add(u);db.session.flush()
            m=Mentor(user_id=u.id,lane=lane,title=title,bio=bio,experience='Fictional demonstration profile. Credentials have not been verified.',status='approved',is_demo=True)
            db.session.add(m);db.session.flush()
            db.session.add(Service(mentor_id=m.id,name=service,description='A focused, one-to-one online mentoring session.',price_cents=price,duration=60))
        db.session.commit();click.echo('Four fictional sample profiles are ready. No real people or accounts were imported.')
