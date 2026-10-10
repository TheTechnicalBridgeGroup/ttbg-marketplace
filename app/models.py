import json
from datetime import datetime, timezone

from flask_login import UserMixin

from .extensions import db, login_manager


def utc_now():
    return datetime.now(timezone.utc)


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(
        db.String(255),
        unique=True,
        nullable=False,
        index=True,
    )
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(
        db.String(40),
        nullable=False,
        default="logistics",
    )
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )

    @property
    def is_active(self):
        return self.active


class MentorApplication(db.Model):
    __tablename__ = "mentor_applications"

    id = db.Column(db.Integer, primary_key=True)

    first_name = db.Column(db.String(80), nullable=False)
    last_name = db.Column(db.String(80), nullable=False)
    email = db.Column(
        db.String(255),
        nullable=False,
        index=True,
    )
    phone = db.Column(db.String(40), nullable=False)

    # Text supports entries such as "10+ years."
    years_experience = db.Column(db.String(80))
    preferred_contact_method = db.Column(db.String(60))
    area_of_expertise = db.Column(
        db.String(255),
        nullable=False,
        index=True,
    )
    about_yourself = db.Column(db.Text)
    support_areas = db.Column(db.Text)
    acknowledgement = db.Column(
        db.Boolean,
        nullable=False,
        default=False,
    )

    status = db.Column(
        db.String(40),
        nullable=False,
        default="New",
        index=True,
    )
    assigned_to = db.Column(db.String(120))
    internal_notes = db.Column(db.Text)

    submitted_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        index=True,
    )
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"

    @property
    def support_area_list(self):
        if not self.support_areas:
            return []

        try:
            parsed = json.loads(self.support_areas)
        except (TypeError, json.JSONDecodeError):
            return [
                item.strip()
                for item in self.support_areas.split(",")
                if item.strip()
            ]

        return parsed if isinstance(parsed, list) else []


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))
