from flask_wtf import FlaskForm
from wtforms import (
    BooleanField,
    PasswordField,
    SelectField,
    SelectMultipleField,
    StringField,
    SubmitField,
    TextAreaField,
    widgets,
)
from wtforms.validators import (
    DataRequired,
    Email,
    Length,
    Optional,
)


APPLICATION_STATUSES = [
    ("New", "New"),
    ("Under Review", "Under Review"),
    ("Interview Requested", "Interview Requested"),
    ("Approved", "Approved"),
    ("Declined", "Declined"),
    ("Onboarding", "Onboarding"),
    ("Active Mentor", "Active Mentor"),
]

CONTACT_METHODS = [
    ("", "Select an option"),
    ("Email", "Email"),
    ("Phone Call", "Phone Call"),
    ("Text Message", "Text Message"),
    ("No Preference", "No Preference"),
]

SUPPORT_AREAS = [
    ("Career Guidance", "Career Guidance"),
    ("Technical Skills", "Technical Skills"),
    ("Leadership Development", "Leadership Development"),
    ("Soft Skills", "Soft Skills"),
    ("Resume & Interview Prep", "Resume & Interview Prep"),
    ("Entrepreneurship", "Entrepreneurship"),
    ("Other", "Other"),
]


class MultiCheckboxField(SelectMultipleField):
    widget = widgets.ListWidget(prefix_label=False)
    option_widget = widgets.CheckboxInput()


class MentorApplicationForm(FlaskForm):
    first_name = StringField(
        "First Name",
        validators=[DataRequired(), Length(max=80)],
    )
    last_name = StringField(
        "Last Name",
        validators=[DataRequired(), Length(max=80)],
    )
    email = StringField(
        "Email",
        validators=[DataRequired(), Email(), Length(max=255)],
    )
    phone = StringField(
        "Phone",
        validators=[DataRequired(), Length(max=40)],
    )
    years_experience = StringField(
        "Years of Experience",
        validators=[Optional(), Length(max=80)],
    )
    preferred_contact_method = SelectField(
        "Preferred Contact Method",
        choices=CONTACT_METHODS,
        validators=[Optional()],
    )
    area_of_expertise = StringField(
        "Industry / Area of Expertise",
        validators=[DataRequired(), Length(max=255)],
    )
    about_yourself = TextAreaField(
        "Tell us about yourself",
        validators=[Optional(), Length(max=4000)],
    )
    support_areas = MultiCheckboxField(
        "Mentorship Support Areas",
        choices=SUPPORT_AREAS,
        validators=[Optional()],
    )

    # Honeypot: real users should never fill this field.
    website = StringField(
        "Website",
        validators=[Optional(), Length(max=200)],
    )
    acknowledgement = BooleanField(
        "I understand this is a private form and my information will be "
        "reviewed manually by the TTBG logistics team.",
        validators=[DataRequired()],
    )
    submit = SubmitField("Submit")


class LoginForm(FlaskForm):
    email = StringField(
        "Email address",
        validators=[DataRequired(), Email(), Length(max=255)],
    )
    password = PasswordField(
        "Password",
        validators=[DataRequired(), Length(min=8, max=128)],
    )
    submit = SubmitField("Sign In")


class ApplicationReviewForm(FlaskForm):
    status = SelectField(
        "Application status",
        choices=APPLICATION_STATUSES,
        validators=[DataRequired()],
    )
    assigned_to = StringField(
        "Assigned to",
        validators=[Optional(), Length(max=120)],
    )
    internal_notes = TextAreaField(
        "Internal notes",
        validators=[Optional(), Length(max=5000)],
    )
    submit = SubmitField("Save Changes")
