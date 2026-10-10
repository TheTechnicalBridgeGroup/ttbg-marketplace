from urllib.parse import urljoin, urlparse

from flask import (
    Blueprint,
    abort,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required, login_user, logout_user
from werkzeug.security import check_password_hash

from .extensions import db
from .forms import ApplicationReviewForm, LoginForm
from .models import MentorApplication, User

admin_bp = Blueprint("admin", __name__)


def is_safe_redirect(target):
    host_url = urlparse(request.host_url)
    redirect_url = urlparse(urljoin(request.host_url, target))
    return (
        redirect_url.scheme in ("http", "https")
        and host_url.netloc == redirect_url.netloc
    )


@admin_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("admin.dashboard"))

    form = LoginForm()
    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        user = User.query.filter_by(email=email, active=True).first()

        if user and check_password_hash(user.password_hash, form.password.data):
            login_user(user)
            next_url = request.args.get("next")
            if next_url and is_safe_redirect(next_url):
                return redirect(next_url)
            return redirect(url_for("admin.dashboard"))

        flash("The email address or password was incorrect.", "error")

    return render_template("login.html", form=form)


@admin_bp.post("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("admin.login"))


@admin_bp.get("/admin")
@login_required
def dashboard():
    applications = MentorApplication.query.order_by(
        MentorApplication.submitted_at.desc()
    ).all()

    counts = {
        "total": MentorApplication.query.count(),
        "new": MentorApplication.query.filter_by(status="New").count(),
        "review": MentorApplication.query.filter_by(status="Under Review").count(),
        "approved": MentorApplication.query.filter(
            MentorApplication.status.in_(["Approved", "Onboarding", "Active Mentor"])
        ).count(),
    }

    return render_template(
        "dashboard.html", applications=applications, counts=counts
    )


@admin_bp.route("/admin/applications/<int:application_id>", methods=["GET", "POST"])
@login_required
def application_detail(application_id):
    application = db.session.get(MentorApplication, application_id)
    if application is None:
        abort(404)

    form = ApplicationReviewForm(obj=application)

    if form.validate_on_submit():
        application.status = form.status.data
        application.assigned_to = (form.assigned_to.data or "").strip() or None
        application.internal_notes = (
            (form.internal_notes.data or "").strip() or None
        )
        db.session.commit()
        flash("Application updated.", "success")
        return redirect(
            url_for("admin.application_detail", application_id=application.id)
        )

    return render_template(
        "application_detail.html", application=application, form=form
    )
