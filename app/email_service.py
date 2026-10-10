import logging
import os
import smtplib
import ssl
from email.message import EmailMessage

from flask import current_app, url_for

logger = logging.getLogger(__name__)


def send_new_application_notification(application):
    """
    Notify the logistics team after an application has been committed.

    Email is intentionally non-blocking from the applicant's perspective:
    failures are logged, while the database record remains safely stored.
    """
    if not _email_is_configured():
        current_app.logger.info(
            "Application %s saved; email notification is not configured.",
            application.id,
        )
        return False

    recipient = (
        os.getenv("NOTIFICATION_EMAIL", "").strip()
        or os.getenv("ADMIN_EMAIL", "").strip()
    )

    review_url = _build_review_url(application.id)
    message = EmailMessage()
    message["Subject"] = (
        f"New Mentor Application — {application.full_name}"
    )
    message["From"] = _sender_address()
    message["To"] = recipient

    support_areas = ", ".join(application.support_area_list)
    if not support_areas:
        support_areas = "Not provided"

    message.set_content(
        "\n".join(
            [
                "A new mentor application has been received.",
                "",
                f"Applicant: {application.full_name}",
                f"Email: {application.email}",
                f"Phone: {application.phone}",
                (
                    "Preferred contact method: "
                    f"{application.preferred_contact_method or 'Not provided'}"
                ),
                (
                    "Industry / area of expertise: "
                    f"{application.area_of_expertise}"
                ),
                f"Mentorship support areas: {support_areas}",
                f"Status: {application.status}",
                "",
                f"Review application: {review_url}",
                "",
                (
                    "This email is a notification only. The application "
                    "record is stored in the TTBG logistics dashboard."
                ),
            ]
        )
    )

    try:
        _deliver(message)
    except Exception:
        logger.exception(
            "Application %s was saved, but its notification email failed.",
            application.id,
        )
        return False

    return True


def _email_is_configured():
    required_values = [
        os.getenv("SMTP_HOST", "").strip(),
        os.getenv("SMTP_USERNAME", "").strip(),
        os.getenv("SMTP_PASSWORD", "").strip(),
        (
            os.getenv("NOTIFICATION_EMAIL", "").strip()
            or os.getenv("ADMIN_EMAIL", "").strip()
        ),
    ]
    return all(required_values)


def _sender_address():
    return (
        os.getenv("SMTP_FROM_EMAIL", "").strip()
        or os.getenv("SMTP_USERNAME", "").strip()
    )


def _build_review_url(application_id):
    base_url = os.getenv("PORTAL_BASE_URL", "").strip().rstrip("/")

    if base_url:
        return f"{base_url}/admin/applications/{application_id}"

    return url_for(
        "admin.application_detail",
        application_id=application_id,
        _external=True,
    )


def _deliver(message):
    host = os.getenv("SMTP_HOST", "").strip()
    port = int(os.getenv("SMTP_PORT", "587"))
    username = os.getenv("SMTP_USERNAME", "").strip()
    password = os.getenv("SMTP_PASSWORD", "")
    use_ssl = _env_flag("SMTP_USE_SSL", default=False)
    use_tls = _env_flag("SMTP_USE_TLS", default=True)

    context = ssl.create_default_context()

    if use_ssl:
        with smtplib.SMTP_SSL(
            host,
            port,
            context=context,
            timeout=20,
        ) as server:
            server.login(username, password)
            server.send_message(message)
        return

    with smtplib.SMTP(host, port, timeout=20) as server:
        server.ehlo()

        if use_tls:
            server.starttls(context=context)
            server.ehlo()

        server.login(username, password)
        server.send_message(message)


def _env_flag(name, default=False):
    raw_value = os.getenv(name)
    if raw_value is None:
        return default

    return raw_value.strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
