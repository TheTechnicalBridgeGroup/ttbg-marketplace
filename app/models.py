from datetime import datetime, timezone
from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()
def now(): return datetime.now(timezone.utc).replace(tzinfo=None)

class User(UserMixin, db.Model):
    __tablename__ = 'market_user'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(254), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='student')
    created_at = db.Column(db.DateTime, default=now, nullable=False)
    mentor = db.relationship('Mentor', backref='user', uselist=False)

class Mentor(db.Model):
    __tablename__ = 'market_mentor'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('market_user.id'), nullable=False, unique=True)
    lane = db.Column(db.String(60), nullable=False)
    title = db.Column(db.String(120), nullable=False)
    bio = db.Column(db.Text, nullable=False)
    experience = db.Column(db.String(500), nullable=False)
    status = db.Column(db.String(25), default='submitted', nullable=False)
    review_note = db.Column(db.Text, default='')
    acuity_calendar_id = db.Column(db.String(40), default='')
    is_demo = db.Column(db.Boolean, default=False, nullable=False)
    services = db.relationship('Service', backref='mentor', lazy=True)
    created_at = db.Column(db.DateTime, default=now, nullable=False)

class Service(db.Model):
    __tablename__ = 'market_service'
    id = db.Column(db.Integer, primary_key=True)
    mentor_id = db.Column(db.Integer, db.ForeignKey('market_mentor.id'), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.String(1000), default='')
    price_cents = db.Column(db.Integer, nullable=False)
    duration = db.Column(db.Integer, nullable=False, default=60)
    fee_bps = db.Column(db.Integer, nullable=False, default=1500)
    acuity_type_id = db.Column(db.String(40), default='')
    active = db.Column(db.Boolean, default=True, nullable=False)

class Booking(db.Model):
    __tablename__ = 'market_booking'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('market_user.id'), nullable=False)
    mentor_id = db.Column(db.Integer, db.ForeignKey('market_mentor.id'), nullable=False)
    service_id = db.Column(db.Integer, db.ForeignKey('market_service.id'), nullable=False)
    student = db.relationship('User')
    mentor = db.relationship('Mentor')
    service = db.relationship('Service')
    service_name = db.Column(db.String(120), nullable=False)
    start = db.Column(db.DateTime, nullable=False)
    duration = db.Column(db.Integer, nullable=False)
    price_cents = db.Column(db.Integer, nullable=False)
    fee_cents = db.Column(db.Integer, nullable=False)
    earnings_cents = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(25), default='demo_reserved', nullable=False)
    payment_status = db.Column(db.String(25), default='not_charged', nullable=False)
    slot_key = db.Column(db.String(100), unique=True)
    request_key = db.Column(db.String(64), unique=True, nullable=False)
    goals = db.Column(db.String(1000), default='')
    created_at = db.Column(db.DateTime, default=now, nullable=False)

class LoginAttempt(db.Model):
    __tablename__ = 'market_login_attempt'
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(254), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=now, nullable=False)

class MentorDetails(db.Model):
    """v0.2 additions use a new table so v0.1 data needs no column alterations."""
    __tablename__ = 'market_mentor_details'
    mentor_id = db.Column(db.Integer, db.ForeignKey('market_mentor.id'), primary_key=True)
    mentor = db.relationship('Mentor', backref=db.backref('details', uselist=False))
    phone = db.Column(db.String(40), default='')
    timezone = db.Column(db.String(80), default='America/New_York')
    specialties = db.Column(db.String(500), default='')
    languages = db.Column(db.String(200), default='English')
    years_experience = db.Column(db.Integer, default=0)
    education = db.Column(db.Text, default='')
    session_approach = db.Column(db.Text, default='')
    application_reference = db.Column(db.String(200), default='')
    internal_notes = db.Column(db.Text, default='')
    owner_id = db.Column(db.Integer, db.ForeignKey('market_user.id'))
    owner = db.relationship('User')
    application_reviewed = db.Column(db.Boolean, default=False, nullable=False)
    credentials_reviewed = db.Column(db.Boolean, default=False, nullable=False)
    agreement_received = db.Column(db.Boolean, default=False, nullable=False)
    orientation_complete = db.Column(db.Boolean, default=False, nullable=False)
    profile_consent = db.Column(db.Boolean, default=False, nullable=False)
    activated_at = db.Column(db.DateTime)
    updated_at = db.Column(db.DateTime, default=now, onupdate=now, nullable=False)

class MentorInvitation(db.Model):
    __tablename__ = 'market_mentor_invitation'
    id = db.Column(db.Integer, primary_key=True)
    mentor_id = db.Column(db.Integer, db.ForeignKey('market_mentor.id'), nullable=False, unique=True)
    token_hash = db.Column(db.String(64), unique=True, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    used_at = db.Column(db.DateTime)

class MentorAudit(db.Model):
    __tablename__ = 'market_mentor_audit'
    id = db.Column(db.Integer, primary_key=True)
    mentor_id = db.Column(db.Integer, db.ForeignKey('market_mentor.id'), nullable=False)
    actor_id = db.Column(db.Integer, db.ForeignKey('market_user.id'), nullable=False)
    actor = db.relationship('User')
    action = db.Column(db.String(100), nullable=False)
    detail = db.Column(db.Text, default='')
    created_at = db.Column(db.DateTime, default=now, nullable=False)
