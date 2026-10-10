import json

from flask import Blueprint, flash, redirect, render_template, url_for

from .email_service import send_new_application_notification
from .extensions import db
from .forms import MentorApplicationForm
from .models import MentorApplication

public_bp = Blueprint("public", __name__)


@public_bp.get("/")
def home():
    return redirect(url_for("public.apply"))


@public_bp.route("/apply", methods=["GET", "POST"])
def apply():
    form = MentorApplicationForm()

    if form.validate_on_submit():
        if form.website.data:
            # Silently accept obvious bot submissions without storing them.
            return redirect(url_for("public.application_success"))

        application = MentorApplication(
            first_name=form.first_name.data.strip(),
            last_name=form.last_name.data.strip(),
            email=form.email.data.strip().lower(),
            phone=form.phone.data.strip(),
            years_experience=(
                (form.years_experience.data or "").strip() or None
            ),
            preferred_contact_method=(
                form.preferred_contact_method.data or None
            ),
            area_of_expertise=form.area_of_expertise.data.strip(),
            about_yourself=(
                (form.about_yourself.data or "").strip() or None
            ),
            support_areas=json.dumps(form.support_areas.data or []),
            acknowledgement=bool(form.acknowledgement.data),
            status="New",
        )

        # Commit first so an email problem can never lose the application.
        db.session.add(application)
        db.session.commit()

        send_new_application_notification(application)

        return redirect(url_for("public.application_success"))

    if form.is_submitted():
        flash(
            "Please review the highlighted fields and try again.",
            "error",
        )

    return render_template("apply.html", form=form)


@public_bp.get("/apply/success")
def application_success():
    return render_template("success.html")
