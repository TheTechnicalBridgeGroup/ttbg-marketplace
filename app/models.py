from datetime import datetime, timezone
from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.dialects.mysql import MEDIUMBLOB

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
    @property
    def publicly_visible(self):
        from .registration_security import email_allowed
        return email_allowed(self.user) and self.status=='approved' and not self.is_demo and (not self.user.access or self.user.access.enabled)

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
    fee_bps = db.Column(db.Integer, nullable=False, default=2000)
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

# Additive v0.3 tables: existing production tables and history are preserved.
class AccountAccess(db.Model):
    __tablename__ = 'market_account_access'
    user_id = db.Column(db.Integer, db.ForeignKey('market_user.id'), primary_key=True)
    user = db.relationship('User', backref=db.backref('access', uselist=False))
    enabled = db.Column(db.Boolean, default=True, nullable=False)
    session_version = db.Column(db.Integer, default=0, nullable=False)
    last_login_at = db.Column(db.DateTime)

class PasswordLink(db.Model):
    __tablename__ = 'market_password_link'
    user_id = db.Column(db.Integer, db.ForeignKey('market_user.id'), primary_key=True)
    token_hash = db.Column(db.String(64), unique=True, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    used_at = db.Column(db.DateTime)
    purpose = db.Column(db.String(20), default='reset', nullable=False)

class PlatformSettings(db.Model):
    __tablename__ = 'market_platform_settings'
    id = db.Column(db.Integer, primary_key=True)
    site_title = db.Column(db.String(80), default='TTBG Marketplace', nullable=False)
    description = db.Column(db.String(240), default='Find your next step with The Technical Bridge Group.', nullable=False)
    support_email = db.Column(db.String(254), default='Destinee.Walker@TheTechnicalBridgeGroup.com', nullable=False)
    registration_open = db.Column(db.Boolean, default=True, nullable=False)
    maintenance_mode = db.Column(db.Boolean, default=False, nullable=False)
    fee_bps = db.Column(db.Integer, default=2000, nullable=False)
    scheduling_provider = db.Column(db.String(20), default='unselected', nullable=False)
    booking_mode = db.Column(db.String(20), default='contact', nullable=False)
    updated_at = db.Column(db.DateTime, default=now, onupdate=now, nullable=False)

class PlatformAudit(db.Model):
    __tablename__ = 'market_platform_audit'
    id = db.Column(db.Integer, primary_key=True)
    actor_id = db.Column(db.Integer, db.ForeignKey('market_user.id'))
    actor = db.relationship('User')
    action = db.Column(db.String(100), nullable=False)
    target = db.Column(db.String(100), nullable=False)
    detail = db.Column(db.Text, default='')
    created_at = db.Column(db.DateTime, default=now, nullable=False)

class PhotoSubmission(db.Model):
    __tablename__ = 'market_photo_submission'
    id = db.Column(db.Integer, primary_key=True)
    mentor_id = db.Column(db.Integer, db.ForeignKey('market_mentor.id'), nullable=False, index=True)
    mentor = db.relationship('Mentor')
    submitted_by = db.Column(db.Integer, db.ForeignKey('market_user.id'), nullable=False)
    image = db.Column(db.LargeBinary().with_variant(MEDIUMBLOB(), 'mysql'), nullable=True)
    status = db.Column(db.String(20), default='pending', nullable=False, index=True)
    note = db.Column(db.String(500), default='')
    reviewed_by = db.Column(db.Integer, db.ForeignKey('market_user.id'))
    created_at = db.Column(db.DateTime, default=now, nullable=False)
    reviewed_at = db.Column(db.DateTime)

class MentorPhoto(db.Model):
    __tablename__ = 'market_mentor_photo'
    mentor_id = db.Column(db.Integer, db.ForeignKey('market_mentor.id'), primary_key=True)
    mentor = db.relationship('Mentor', backref=db.backref('photo', uselist=False))
    approved_id = db.Column(db.Integer, db.ForeignKey('market_photo_submission.id'))
    pending_id = db.Column(db.Integer, db.ForeignKey('market_photo_submission.id'))

class ServiceScheduling(db.Model):
    __tablename__ = 'market_service_scheduling'
    service_id = db.Column(db.Integer, db.ForeignKey('market_service.id'), primary_key=True)
    service = db.relationship('Service', backref=db.backref('scheduling', uselist=False))
    provider = db.Column(db.String(20), default='unselected', nullable=False)
    event_type_id = db.Column(db.String(120), default='')
    booking_url = db.Column(db.String(1000), default='')

class MentorIntegration(db.Model):
    __tablename__ = 'market_mentor_integration'
    mentor_id = db.Column(db.Integer, db.ForeignKey('market_mentor.id'), primary_key=True)
    mentor = db.relationship('Mentor', backref=db.backref('integration', uselist=False))
    provider_user_id = db.Column(db.String(120), default='')
    stripe_account_id = db.Column(db.String(120), default='')

class SchemaRevision(db.Model):
    __tablename__ = 'market_schema_revision'
    name = db.Column(db.String(80), primary_key=True)
    applied_at = db.Column(db.DateTime, default=now, nullable=False)

# Additive support tables; existing account, booking and payment data are unchanged.
class SupportNote(db.Model):
    __tablename__ = 'market_support_note'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('market_user.id'), nullable=False, index=True)
    author_id = db.Column(db.Integer, db.ForeignKey('market_user.id'), nullable=False)
    author = db.relationship('User', foreign_keys=[author_id])
    body = db.Column(db.String(2000), nullable=False)
    created_at = db.Column(db.DateTime, default=now, nullable=False)

class SupportIncident(db.Model):
    __tablename__ = 'market_support_incident'
    id = db.Column(db.Integer, primary_key=True)
    reference = db.Column(db.String(32), unique=True, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('market_user.id'), index=True)
    route = db.Column(db.String(200), nullable=False)
    method = db.Column(db.String(10), nullable=False)
    error_type = db.Column(db.String(100), nullable=False)
    status = db.Column(db.String(20), default='open', nullable=False, index=True)
    resolution = db.Column(db.String(500), default='')
    resolved_by = db.Column(db.Integer, db.ForeignKey('market_user.id'))
    resolved_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=now, nullable=False, index=True)

class SensitiveAttempt(db.Model):
    __tablename__ = 'market_sensitive_attempt'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('market_user.id'), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=now, nullable=False, index=True)

class AvailabilityRequest(db.Model):
    __tablename__ = 'market_availability_request'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('market_user.id'), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=now, nullable=False, index=True)

class EmailIdentity(db.Model):
    __tablename__ = 'market_email_identity'
    user_id = db.Column(db.Integer, db.ForeignKey('market_user.id'), primary_key=True)
    user = db.relationship('User', backref=db.backref('email_identity', uselist=False))
    email = db.Column(db.String(254), nullable=False)
    verified_at = db.Column(db.DateTime)
    legacy_exempt = db.Column(db.Boolean, nullable=False, default=False)
    token_hash = db.Column(db.String(64), unique=True)
    expires_at = db.Column(db.DateTime)
    last_sent_at = db.Column(db.DateTime)

class SecurityRate(db.Model):
    __tablename__ = 'market_security_rate'
    key = db.Column(db.String(64), primary_key=True)
    count = db.Column(db.Integer, nullable=False, default=0)
    expires_at = db.Column(db.DateTime, nullable=False, index=True)

# Every ORM-created account starts pending, including staff-created mentors.
from sqlalchemy import event
from sqlalchemy.orm import Session
@event.listens_for(Session, 'before_flush')
def require_new_identity(session, flush_context, instances):
    from sqlalchemy import inspect
    for item in list(session.dirty):
        if isinstance(item,User) and inspect(item).attrs.email.history.has_changes():
            identity=item.email_identity or EmailIdentity(user=item,email=item.email)
            identity.email=item.email;identity.verified_at=None;identity.legacy_exempt=False
            identity.token_hash=None;identity.expires_at=None;identity.last_sent_at=None
    for item in list(session.new):
        if isinstance(item,User) and item.email_identity is None:
            item.email_identity=EmailIdentity(email=item.email,legacy_exempt=False)

class HelpSettings(db.Model):
    __tablename__ = 'market_help_settings'
    id = db.Column(db.Integer, primary_key=True)
    enabled = db.Column(db.Boolean, nullable=False, default=True)
    phone = db.Column(db.String(20), nullable=False, default='')

class KnowledgePage(db.Model):
    __tablename__ = 'market_knowledge_page'
    id = db.Column(db.Integer, primary_key=True)
    space = db.Column(db.String(80), nullable=False)
    title = db.Column(db.String(160), nullable=False)
    body = db.Column(db.Text, nullable=False)
    parent_id = db.Column(db.Integer, db.ForeignKey('market_knowledge_page.id'))
    updated_by = db.Column(db.Integer, db.ForeignKey('market_user.id'))
    editor = db.relationship('User')
    version = db.Column(db.Integer, nullable=False, default=1)
    created_at = db.Column(db.DateTime, default=now, nullable=False)
    updated_at = db.Column(db.DateTime, default=now, onupdate=now, nullable=False)

class KnowledgeImage(db.Model):
    __tablename__ = 'market_knowledge_image'
    id = db.Column(db.Integer, primary_key=True)
    page_id = db.Column(db.Integer, db.ForeignKey('market_knowledge_page.id'), nullable=False, index=True)
    caption = db.Column(db.String(200), nullable=False)
    image = db.Column(db.LargeBinary().with_variant(MEDIUMBLOB(), 'mysql'), nullable=False)
