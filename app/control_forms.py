from decimal import Decimal
from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileRequired
from wtforms import StringField, PasswordField, SelectField, BooleanField, TextAreaField, DecimalField, HiddenField
from wtforms.validators import DataRequired, Email, Length, Optional, NumberRange, Regexp
from .forms import finite_number
from .booking_config import PROVIDERS

class ConfirmAdmin(FlaskForm):
    admin_password=PasswordField('Confirm your admin password',validators=[DataRequired(),Length(max=128)])
    reason=StringField('Reason',validators=[DataRequired(),Length(min=3,max=300)])

class CreateUserForm(ConfirmAdmin):
    name=StringField('Full name',validators=[DataRequired(),Length(min=2,max=100)])
    email=StringField('Account email',validators=[DataRequired(),Email(),Length(max=254)])
    role=SelectField('Role',choices=[('account_manager','Account Manager'),('admin','Admin'),('student','Mentee / Student')])

class EditUserForm(CreateUserForm):
    enabled=BooleanField('Account enabled')

class SettingsForm(ConfirmAdmin):
    site_title=StringField('Site title',validators=[DataRequired(),Length(max=80)])
    description=StringField('Search description',validators=[DataRequired(),Length(max=240)])
    support_email=StringField('Support email',validators=[DataRequired(),Email(),Length(max=254)])
    registration_open=BooleanField('Allow new student registrations')
    maintenance_mode=BooleanField('Maintenance mode (only admins can access the platform)')
    fee_percent=DecimalField('TTBG share of session price (%)',places=2,validators=[finite_number,NumberRange(min=Decimal('0'),max=Decimal('100'))])
    scheduling_provider=SelectField('Scheduling provider',choices=PROVIDERS)
    booking_mode=SelectField('Booking experience',choices=[('contact','Contact TTBG'),('acuity','Acuity live availability + contact to confirm'),('external','Open configured provider booking links')])

class PhotoForm(FlaskForm):
    photo=FileField('Profile picture',validators=[FileRequired()])

class PhotoReviewForm(FlaskForm):
    decision=SelectField('Decision',choices=[('approve','Approve'),('reject','Request a replacement')])
    note=TextAreaField('Feedback for the mentor',validators=[Optional(),Length(max=500)])

class SchedulingForm(FlaskForm):
    provider=SelectField('Provider',choices=PROVIDERS)
    event_type_id=StringField('Provider event / appointment type ID',validators=[Optional(),Length(max=120)])
    booking_url=StringField('Hosted booking URL (HTTPS)',validators=[Optional(),Length(max=1000)])

class IntegrationForm(ConfirmAdmin):
    provider_user_id=StringField('Provider mentor / calendar reference',validators=[Optional(),Length(max=120)])
    stripe_account_id=StringField('Stripe connected account ID',validators=[Optional(),Regexp(r'^acct_[A-Za-z0-9]+$'),Length(max=120)])
