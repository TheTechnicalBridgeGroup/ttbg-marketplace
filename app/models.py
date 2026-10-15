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

# v0.6 additive Acuity tables. Provider records are separated by mode/account.
class AcuityRequest(db.Model):
    __tablename__ = 'market_acuity_request'
    id = db.Column(db.String(32), primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('market_user.id'))
    service_id = db.Column(db.Integer, db.ForeignKey('market_service.id'))
    scope = db.Column(db.String(60), nullable=False, index=True)
    calendar_id = db.Column(db.String(30), nullable=False)
    type_id = db.Column(db.String(30), nullable=False)
    starts_at = db.Column(db.DateTime, nullable=False)
    timezone = db.Column(db.String(80), nullable=False)
    email = db.Column(db.String(254), nullable=False)
    service_name = db.Column(db.String(120), nullable=False)
    price_cents = db.Column(db.Integer, nullable=False)
    duration = db.Column(db.Integer, nullable=False)
    fee_bps = db.Column(db.Integer, nullable=False)
    state = db.Column(db.String(25), nullable=False, default='creating',index=True)
    dedupe_key = db.Column(db.String(64), unique=True)
    error_code = db.Column(db.String(80), default='')
    created_at = db.Column(db.DateTime, default=now, nullable=False)
    updated_at = db.Column(db.DateTime, default=now, onupdate=now, nullable=False)

class AcuityAppointment(db.Model):
    __tablename__ = 'market_acuity_appointment'
    __table_args__ = (db.UniqueConstraint('scope','provider_id'),)
    id = db.Column(db.Integer, primary_key=True)
    scope = db.Column(db.String(60), nullable=False, index=True)
    provider_id = db.Column(db.String(30), nullable=False)
    booking_id = db.Column(db.Integer, db.ForeignKey('market_booking.id'), unique=True)
    booking = db.relationship('Booking',backref=db.backref('acuity',uselist=False))
    request_id = db.Column(db.String(32), db.ForeignKey('market_acuity_request.id'), unique=True)
    request = db.relationship('AcuityRequest')
    calendar_id = db.Column(db.String(30), nullable=False)
    type_id = db.Column(db.String(30), nullable=False)
    starts_at = db.Column(db.DateTime, nullable=False)
    duration = db.Column(db.Integer, nullable=False)
    timezone = db.Column(db.String(80), nullable=False, default='UTC')
    email = db.Column(db.String(254), nullable=False, default='')
    client_name = db.Column(db.String(200), nullable=False, default='')
    price_cents = db.Column(db.Integer, nullable=False)
    paid = db.Column(db.String(40), nullable=False, default='unknown')
    cancelled = db.Column(db.Boolean, nullable=False, default=False)
    location = db.Column(db.String(1000), nullable=False, default='')
    sync_state = db.Column(db.String(30), nullable=False, default='unlinked')
    last_synced_at = db.Column(db.DateTime)
    # Prevent future webhook/refresh operations from restoring identity after deletion.
    identity_removed = db.Column(db.Boolean, nullable=False, default=False)

class AcuitySyncJob(db.Model):
    __tablename__ = 'market_acuity_sync_job'
    __table_args__ = (db.UniqueConstraint('scope','provider_id'),)
    id = db.Column(db.Integer, primary_key=True)
    scope = db.Column(db.String(60), nullable=False)
    provider_id = db.Column(db.String(30), nullable=False)
    pending = db.Column(db.Boolean, nullable=False, default=True,index=True)
    error_code = db.Column(db.String(80), default='')
    received_at = db.Column(db.DateTime, default=now, nullable=False)
    processed_at = db.Column(db.DateTime)

class AcuityMockAppointment(db.Model):
    __tablename__ = 'market_acuity_mock_appointment'
    id = db.Column(db.Integer, primary_key=True)
    payload = db.Column(db.JSON, nullable=False)
    slot = db.Column(db.String(100), unique=True)

class AcuityMockConfig(db.Model):
    __tablename__ = 'market_acuity_mock_config'
    id = db.Column(db.Integer, primary_key=True)
    scenario = db.Column(db.String(40), nullable=False, default='normal')
    webhook_target = db.Column(db.String(255), nullable=False, default='')

# v0.7: additive payment tables; no card, bank, or identity-verification data.
class StripeAccount(db.Model):
    __tablename__ = 'market_stripe_account'
    id = db.Column(db.Integer, primary_key=True)
    mentor_id = db.Column(db.Integer, db.ForeignKey('market_mentor.id'))
    mentor = db.relationship('Mentor')
    scope = db.Column(db.String(100), nullable=False)
    account_id = db.Column(db.String(100))
    ready = db.Column(db.Boolean, default=False, nullable=False)
    status = db.Column(db.String(80), default='not_connected', nullable=False)
    checked_at = db.Column(db.DateTime)
    __table_args__ = (db.UniqueConstraint('scope','mentor_id'), db.UniqueConstraint('scope','account_id'))

class PaymentOrder(db.Model):
    __tablename__ = 'market_payment_order'
    id = db.Column(db.String(32), db.ForeignKey('market_acuity_request.id'), primary_key=True)
    request = db.relationship('AcuityRequest', backref=db.backref('payment', uselist=False))
    account_row_id = db.Column(db.Integer, db.ForeignKey('market_stripe_account.id'), nullable=False)
    account = db.relationship('StripeAccount')
    destination = db.Column(db.String(100), nullable=False)
    scope = db.Column(db.String(100), nullable=False, index=True)
    gross_cents = db.Column(db.Integer, nullable=False)
    mentor_cents = db.Column(db.Integer, nullable=False)
    platform_cents = db.Column(db.Integer, nullable=False)
    stripe_fee_cents = db.Column(db.Integer)
    payment_state = db.Column(db.String(40), default='unpaid', nullable=False)
    booking_state = db.Column(db.String(40), default='waiting', nullable=False)
    session_id = db.Column(db.String(100), unique=True)
    checkout_url = db.Column(db.Text, default='')
    intent_id = db.Column(db.String(100), unique=True)
    charge_id = db.Column(db.String(100), unique=True)
    expires_at = db.Column(db.DateTime, nullable=False)
    slot_key = db.Column(db.String(64), unique=True)
    appointment_payload = db.Column(db.JSON, nullable=False, default=dict)
    refund_requested = db.Column(db.Boolean, default=False, nullable=False)
    refunded_cents = db.Column(db.Integer, default=0, nullable=False)
    transfer_id = db.Column(db.String(100), unique=True)
    reversed_cents = db.Column(db.Integer, default=0, nullable=False)
    completion_reported_at = db.Column(db.DateTime)
    completion_approved_at = db.Column(db.DateTime)
    hold_reason = db.Column(db.String(150), default='')
    error_code = db.Column(db.String(100), default='')
    created_at = db.Column(db.DateTime, default=now, nullable=False)
    checked_at = db.Column(db.DateTime, default=now, nullable=False, index=True)
    @property
    def earnings_stage(self):
        if self.reversed_cents:return 'Transfer recovered / adjusted'
        if self.transfer_id:return 'Transferred to Stripe account'
        if self.hold_reason or self.refund_requested or self.payment_state in ('refunded','disputed','partially_refunded'):return 'Held for review / refund'
        if self.payment_state!='paid':return 'Awaiting payment'
        if not self.completion_approved_at:return 'Awaiting completed-session approval'
        return 'Approved · transfer eligibility checked on submission'
    @property
    def booking(self):
        mirror = AcuityAppointment.query.filter_by(request_id=self.id).first()
        return mirror.booking if mirror else None

class PaymentOperation(db.Model):
    __tablename__ = 'market_payment_operation'
    id = db.Column(db.String(32), primary_key=True)
    scope = db.Column(db.String(100), nullable=False)
    owner_key = db.Column(db.String(150), nullable=False)
    order_id = db.Column(db.String(32), db.ForeignKey('market_payment_order.id'))
    account_row_id = db.Column(db.Integer, db.ForeignKey('market_stripe_account.id'))
    kind = db.Column(db.String(30), nullable=False)
    path = db.Column(db.String(200), nullable=False)
    params = db.Column(db.JSON, nullable=False)
    state = db.Column(db.String(30), default='queued', nullable=False)
    response_id = db.Column(db.String(100))
    error_code = db.Column(db.String(100), default='')
    created_at = db.Column(db.DateTime, default=now, nullable=False)
    attempted_at = db.Column(db.DateTime)
    lease_until = db.Column(db.DateTime)
    __table_args__ = (db.UniqueConstraint('scope','owner_key'),)

class StripeEvent(db.Model):
    __tablename__ = 'market_stripe_event'
    id = db.Column(db.Integer, primary_key=True)
    scope = db.Column(db.String(100), nullable=False)
    event_id = db.Column(db.String(100), nullable=False)
    event_type = db.Column(db.String(100), nullable=False)
    object_id = db.Column(db.String(100), nullable=False)
    pending = db.Column(db.Boolean, default=True, nullable=False)
    error_code = db.Column(db.String(100), default='')
    received_at = db.Column(db.DateTime, default=now, nullable=False)
    checked_at = db.Column(db.DateTime, default=now, nullable=False)
    __table_args__ = (db.UniqueConstraint('scope','event_id'),)

class StripeDispute(db.Model):
    __tablename__ = 'market_stripe_dispute'
    id = db.Column(db.String(100), primary_key=True)
    order_id = db.Column(db.String(32), db.ForeignKey('market_payment_order.id'), nullable=False)
    status = db.Column(db.String(50), nullable=False)

class StripeMockObject(db.Model):
    __tablename__ = 'market_stripe_mock_object'
    id = db.Column(db.String(100), primary_key=True)
    kind = db.Column(db.String(40), nullable=False)
    payload = db.Column(db.JSON, nullable=False)

class StripeMockKey(db.Model):
    __tablename__ = 'market_stripe_mock_key'
    id = db.Column(db.String(100), primary_key=True)
    object_id = db.Column(db.String(100), nullable=False)
