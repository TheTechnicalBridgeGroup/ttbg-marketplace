from decimal import Decimal
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SelectField, TextAreaField, IntegerField, BooleanField, HiddenField, DecimalField
from wtforms.validators import DataRequired, Email, Length, EqualTo, NumberRange, Optional, Regexp, StopValidation

def finite_number(form, field):
    if field.data is not None and not field.data.is_finite():
        raise StopValidation('Enter a finite number.')

LANES = ['Healthcare','Technology','Skilled Trades','Automotive','Beauty & Wellness','Animal Care','Business & More']
class LoginForm(FlaskForm):
    email = StringField('Email address', validators=[DataRequired(), Email(), Length(max=254)])
    password = PasswordField('Password', validators=[DataRequired(), Length(max=128)])
class RegisterForm(LoginForm):
    name = StringField('Full name', validators=[DataRequired(), Length(min=2,max=100)])
    password = PasswordField('Password', validators=[DataRequired(), Length(min=12,max=128)])
    confirm = PasswordField('Confirm password', validators=[DataRequired(), EqualTo('password')])
class ProfileForm(FlaskForm):
    lane = SelectField('Your lane', choices=LANES)
    title = StringField('Professional title', validators=[DataRequired(), Length(max=120)])
    bio = TextAreaField('About you', validators=[DataRequired(), Length(min=40,max=3000)])
    experience = TextAreaField('Experience and credentials', validators=[DataRequired(), Length(min=10,max=500)])
    consent = BooleanField('I consent to TTBG reviewing my profile and publishing it if approved.', validators=[DataRequired()])
class ReviewForm(FlaskForm):
    status = SelectField('Review decision', choices=[('draft','Draft'),('submitted','Submitted'),('reviewing','In review'),('changes_requested','Request changes'),('approved','Approved'),('declined','Declined')])
    review_note = TextAreaField('Feedback for the mentor', validators=[Optional(),Length(max=2000)])
    acuity_calendar_id = StringField('Acuity calendar ID (optional)', validators=[Optional(),Regexp(r'^\d{1,20}$',message='Use a numeric calendar ID.')])
class ServiceForm(FlaskForm):
    name = StringField('Service name', validators=[DataRequired(),Length(max=120)])
    description = TextAreaField('Description', validators=[Optional(),Length(max=1000)])
    price = DecimalField('Starting session price (USD)', places=2, validators=[DataRequired(), finite_number, NumberRange(min=Decimal('1'),max=Decimal('1000'))])
    duration = SelectField('Session length', choices=[(30,'30 minutes'),(60,'60 minutes'),(90,'90 minutes')], coerce=int)
    fee_percent = DecimalField('TTBG commission (%)', places=2, validators=[finite_number, NumberRange(min=Decimal('0'),max=Decimal('100'))], default=Decimal('15'))
    acuity_type_id = StringField('Acuity appointment type ID (optional)', validators=[Optional(),Regexp(r'^\d{1,20}$',message='Use a numeric appointment type ID.')])
class BookingForm(FlaskForm):
    slot = SelectField('Choose a demo time', validators=[DataRequired()])
    goals = TextAreaField('What would you like help with?', validators=[Optional(),Length(max=1000)])
    request_key = HiddenField(validators=[DataRequired(),Length(min=32,max=64)])
    acknowledge = BooleanField('I understand this is a demo reservation. No payment or real appointment will be created.', validators=[DataRequired()])
class EmptyForm(FlaskForm): pass

from decimal import Decimal
from wtforms import DecimalField
from wtforms.validators import ValidationError
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

def valid_timezone(form, field):
    try: ZoneInfo(field.data)
    except (ZoneInfoNotFoundError, ValueError): raise ValidationError('Enter an IANA timezone, such as America/New_York.')

PROFILE_CHECKS = ['application_reviewed','credentials_reviewed','agreement_received','orientation_complete','profile_consent']
class AdminProfileForm(FlaskForm):
    name = StringField('Public display name', validators=[DataRequired(),Length(min=2,max=100)])
    email = StringField('Account email (private)', validators=[DataRequired(),Email(),Length(max=254)])
    phone = StringField('Phone (private)', validators=[Optional(),Length(max=40)])
    lane = SelectField('Primary lane', choices=LANES)
    title = StringField('Professional title', validators=[DataRequired(),Length(max=120)])
    bio = TextAreaField('Public biography', validators=[Optional(),Length(max=3000)])
    experience = TextAreaField('Credentials and experience', validators=[Optional(),Length(max=500)])
    years_experience = IntegerField('Years of experience', default=0,validators=[NumberRange(min=0,max=80)])
    education = TextAreaField('Education and certifications', validators=[Optional(),Length(max=2000)])
    specialties = StringField('Specialties', validators=[Optional(),Length(max=500)])
    languages = StringField('Languages', default='English',validators=[Optional(),Length(max=200)])
    timezone = StringField('Timezone', default='America/New_York',validators=[DataRequired(),Length(max=80),valid_timezone])
    session_approach = TextAreaField('How they support students',validators=[Optional(),Length(max=2000)])
    application_reference = StringField('Application reference (private)',validators=[Optional(),Length(max=200)])
    owner_id = SelectField('Onboarding owner',coerce=int)
    internal_notes = TextAreaField('Team notes (private)',validators=[Optional(),Length(max=5000)])
    application_reviewed = BooleanField('Application reviewed in the mentor portal')
    credentials_reviewed = BooleanField('Credentials reviewed by TTBG')
    agreement_received = BooleanField('Mentor agreement received')
    orientation_complete = BooleanField('Orientation completed')
    profile_consent = BooleanField('Mentor consent to publish recorded')
    acuity_calendar_id = StringField('Acuity calendar ID (optional)',validators=[Optional(),Regexp(r'^\d{1,20}$',message='Use a numeric calendar ID.')])
    confirm_link = BooleanField('If this email already belongs to a student, I confirm this is the approved applicant and authorize linking their account.')

class MentorPriceForm(FlaskForm):
    price = DecimalField('Your session price (USD)',places=2,validators=[DataRequired(),finite_number,NumberRange(min=Decimal('1'),max=Decimal('1000'))])

class LifecycleForm(FlaskForm):
    action = SelectField('Action',choices=[('suspend','Suspend profile'),('delete','Delete profile'),('restore','Restore to draft')])
    reason = TextAreaField('Reason (team only)',validators=[DataRequired(),Length(min=5,max=1000)])
    confirm_name = StringField('Type the mentor’s display name to confirm',validators=[DataRequired()])

class ActivateForm(FlaskForm):
    password = PasswordField('Choose your password',validators=[DataRequired(),Length(min=12,max=128)])
    confirm = PasswordField('Confirm password',validators=[DataRequired(),EqualTo('password')])
