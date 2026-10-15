"""Explicit, staff-reviewed Acuity service imports. Provider reads only."""
import hashlib
import json
import re
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user
from flask_wtf import FlaskForm
from itsdangerous import URLSafeTimedSerializer, BadSignature
from sqlalchemy.orm.attributes import set_committed_value
from wtforms import StringField, TextAreaField, HiddenField, BooleanField
from wtforms.validators import DataRequired, Length, Regexp, Optional
from . import acuity
from .models import db, Mentor, Service, ServiceScheduling, PlatformSettings
from .onboarding_logic import audit
from .routes import roles
from .security import settings, account_enabled

bp = Blueprint('service_import', __name__)
STAFF = ('admin', 'account_manager')

class FetchForm(FlaskForm):
    type_id = StringField('Acuity Appointment Type ID', filters=[lambda x: x.strip() if x else x],
        validators=[DataRequired(), Regexp(r'^[0-9]{1,19}$', message='Enter a positive numeric appointment type ID.')])

class SaveForm(FlaskForm):
    preview = HiddenField(validators=[DataRequired(), Length(max=3000)])
    name = StringField('Service name', filters=[lambda x: x.strip() if x else x], validators=[DataRequired(), Length(max=120)])
    description = TextAreaField('Description', validators=[Optional(), Length(max=1000)])
    active = BooleanField('Make this service active on the mentor’s published profile')
    confirm = BooleanField('I reviewed these values and confirm the Acuity account uses USD.', validators=[DataRequired()])

class ImportProblem(Exception):
    pass

class PlainText(HTMLParser):
    """Keep readable description text; no remote assets or HTML reach the page."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0
    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'): self.hidden += 1
        if not self.hidden and tag in ('p', 'div', 'li', 'br', 'h1', 'h2', 'h3'): self.parts.append('\n')
    def handle_endtag(self, tag):
        if tag in ('script', 'style'): self.hidden = max(0, self.hidden - 1)
        if not self.hidden and tag in ('p', 'div', 'li'): self.parts.append('\n')
    def handle_data(self, data):
        if not self.hidden: self.parts.append(data)

def plain_description(value):
    parser = PlainText(); parser.feed(value); parser.close()
    return '\n'.join(line.strip() for line in ''.join(parser.parts).splitlines() if line.strip())

def numeric_id(value):
    value = str(value).strip()
    return str(int(value)) if re.fullmatch(r'[0-9]{1,19}', value) and 0 < int(value) < 2**63 else None

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()

def signer():
    return URLSafeTimedSerializer(current_app.config['SECRET_KEY'], salt='acuity-service-import-v067')

def mentor(mid, lock=False):
    query = db.select(Mentor).where(Mentor.id == mid)
    if lock: query = query.with_for_update().execution_options(populate_existing=True)
    m = db.session.execute(query).scalar_one_or_none()
    if not m: abort(404)
    if m.status in ('suspended', 'deleted') or not account_enabled(m.user): abort(403)
    return m

def read_type(m, type_id):
    calendar_id = numeric_id(m.acuity_calendar_id)
    if not calendar_id: raise ImportProblem('Save this mentor’s Acuity Calendar ID in Review & publish before importing.')
    calendars = acuity.api_get('calendars')
    types = acuity.api_get('appointment-types')
    if not isinstance(calendars, list) or not isinstance(types, list) or not all(isinstance(x, dict) for x in calendars + types):
        raise acuity.AcuityError('invalid_response')
    matches = [x for x in types if numeric_id(x.get('id')) == type_id]
    if len(matches) != 1: raise ImportProblem('That appointment type was not found. Use its Appointment Type ID, not the Calendar ID.')
    if not any(numeric_id(c.get('id')) == calendar_id for c in calendars):
        raise ImportProblem('The mentor’s calendar was not found in the connected Acuity account. Check the saved Calendar ID.')
    item = matches[0]
    if item.get('active') is not True: raise ImportProblem('This Acuity appointment type is inactive or deleted. Activate it in Acuity first.')
    if item.get('type') != 'service': raise ImportProblem('Only one-to-one Acuity service types are supported. Classes and series cannot be imported.')
    ids = item.get('calendarIDs')
    if not isinstance(ids, list): raise acuity.AcuityError('invalid_response')
    if calendar_id not in [numeric_id(x) for x in ids]:
        raise ImportProblem('This appointment type is not offered on the mentor’s saved calendar. Update the assignment in Acuity or correct the Calendar ID.')
    try:
        price = Decimal(str(item.get('price')))
        if not price.is_finite() or not Decimal('0') <= price <= Decimal('1000') or price * 100 != (price * 100).to_integral_value():
            raise ValueError()
    except (InvalidOperation, ValueError):
        raise ImportProblem('TTBG supports session prices from $0.00 to $1,000.00, with at most two decimal places. Update the type in Acuity before importing.') from None
    duration = str(item.get('duration'))
    if not re.fullmatch(r'[0-9]{1,4}', duration) or not 1 <= int(duration) <= 1440:
        raise ImportProblem('The Acuity duration must be a whole number from 1 to 1,440 minutes.')
    name = item.get('name'); description = item.get('description') or ''
    if not isinstance(name, str) or not name.strip() or not isinstance(description, str):
        raise acuity.AcuityError('invalid_response')
    private = item.get('private', False)
    if not isinstance(private, bool): raise acuity.AcuityError('invalid_response')
    description = plain_description(description)
    # Fingerprint full text before fitting the existing database limits.
    result = dict(type_id=type_id, calendar_id=calendar_id, name=name.strip(), description=description,
                  price_cents=int(price * 100), duration=int(duration), private=private)
    fingerprint = digest(result)
    result['shortened'] = len(result['name']) > 120 or len(description) > 1000
    result['name'] = result['name'][:120]; result['description'] = description[:1000]
    result['fingerprint'] = fingerprint
    return result

def existing_service(mid, type_id, lock=False):
    query = db.select(Service).where(Service.mentor_id == mid).order_by(Service.id)
    if lock: query = query.with_for_update().execution_options(populate_existing=True)
    services = db.session.execute(query).scalars().all()
    found = []
    for s in services:
        if lock:
            # Current read also refreshes the mapping under MySQL REPEATABLE READ.
            mapping = db.session.execute(db.select(ServiceScheduling).where(ServiceScheduling.service_id == s.id)
                .with_for_update().execution_options(populate_existing=True)).scalar_one_or_none()
            set_committed_value(s, 'scheduling', mapping)
        else: mapping = s.scheduling
        ids = [numeric_id(s.acuity_type_id)]
        if mapping and mapping.provider == 'acuity': ids.append(numeric_id(mapping.event_type_id))
        if type_id in ids: found.append(s)
    if len(found) > 1:
        raise ImportProblem('Multiple services for this mentor already reference that appointment type. Correct their mappings before importing; nothing was changed.')
    return found[0] if found else None

def state(s):
    if not s: return None
    mapping = s.scheduling
    return {'id': s.id, 'digest': digest(dict(name=s.name, description=s.description, price=s.price_cents,
        duration=s.duration, fee=s.fee_bps, active=s.active, type_id=s.acuity_type_id,
        mapping=[mapping.provider, mapping.event_type_id, mapping.booking_url] if mapping else None))}

def preview_token(m, item, existing):
    return signer().dumps(dict(uid=current_user.id, mid=m.id, type_id=item['type_id'], calendar_id=item['calendar_id'],
        scope=acuity.scope(), source=item['fingerprint'], existing=state(existing), fee=settings().fee_bps))

@bp.route('/admin/mentors/<int:mid>/services/import-acuity', methods=['GET', 'POST'])
@roles(*STAFF)
def import_service(mid):
    m = mentor(mid); fetch = FetchForm(); form = None; item = None; existing = None; error = None; status = 200
    operation = request.form.get('operation')
    if request.method == 'POST' and operation not in ('fetch', 'save'): abort(400)
    try:
        if request.method == 'POST' and operation == 'fetch' and fetch.validate_on_submit():
            type_id = numeric_id(fetch.type_id.data)
            if not type_id: raise ImportProblem('Enter a positive numeric appointment type ID.')
            acuity.throttle()
            item = read_type(m, type_id); existing = existing_service(mid, type_id)
            form = SaveForm(formdata=None, name=item['name'], description=item['description'],
                active=existing.active if existing else not item['private'], preview=preview_token(m, item, existing))
        elif request.method == 'POST' and operation == 'save':
            form = SaveForm()
            try: token = signer().loads(form.preview.data or '', max_age=900)
            except BadSignature: raise ImportProblem('This preview expired or is invalid. Fetch the appointment type again.') from None
            if not isinstance(token, dict) or token.get('uid') != current_user.id or token.get('mid') != mid or token.get('scope') != acuity.scope():
                abort(400)
            type_id = numeric_id(token.get('type_id'))
            if not type_id: abort(400)
            acuity.throttle()
            item = read_type(m, type_id)
            if item['fingerprint'] != token.get('source') or item['calendar_id'] != token.get('calendar_id'):
                raise ImportProblem('Acuity details or the mentor’s calendar changed after this preview. Fetch again to review the current values.')
            existing = existing_service(mid, type_id)
            if form.validate_on_submit():
                # Match the booking/settings lock order. Provider reads happen before locks.
                cfg = db.session.execute(db.select(PlatformSettings).where(PlatformSettings.id == 1)
                    .with_for_update().execution_options(populate_existing=True)).scalar_one()
                m = mentor(mid, lock=True)
                db.session.refresh(current_user._get_current_object())
                if current_user.role not in STAFF or not account_enabled(current_user): abort(403)
                if numeric_id(m.acuity_calendar_id) != item['calendar_id']:
                    raise ImportProblem('The mentor’s calendar changed. Fetch the appointment type again.')
                existing = existing_service(mid, type_id, lock=True)
                if state(existing) != token.get('existing') or cfg.fee_bps != token.get('fee'):
                    raise ImportProblem('A TTBG service or commission setting changed after this preview. Fetch again to review the current values; nothing was overwritten.')
                s = existing or Service(mentor_id=mid, fee_bps=cfg.fee_bps)
                db.session.add(s)
                s.name = form.name.data; s.description = form.description.data or ''
                s.price_cents = item['price_cents']; s.duration = item['duration']; s.acuity_type_id = type_id
                s.active = form.active.data
                mapping = s.scheduling or ServiceScheduling(service=s)
                if mapping.provider != 'acuity': mapping.booking_url = ''
                mapping.provider = 'acuity'; mapping.event_type_id = type_id; db.session.add(mapping)
                db.session.flush()
                audit(m, 'Acuity service updated' if existing else 'Acuity service imported',
                    f'Service {s.id}; type {type_id}; calendar {item["calendar_id"]}; price {s.price_cents} cents; duration {s.duration}; active={s.active}. Staff confirmed import.')
                db.session.commit()
                flash('Service updated from Acuity.' if existing else 'Service imported from Acuity.', 'success')
                return redirect(url_for('main.review', mid=mid))
    except ImportProblem as exc:
        db.session.rollback(); error = str(exc); form = None; item = None; existing = None
        status = 409 if operation == 'save' else 200
    except acuity.AcuityError as exc:
        db.session.rollback(); reference = acuity.record_failure(exc.code)
        messages = {'configuration_missing': 'Acuity credentials are not configured. Ask an Admin to check Support → Integrations.',
                    'authentication_failed': 'Acuity rejected the credentials. Ask an Admin to check Support → Integrations.',
                    'rate_limited': 'Acuity is busy. Please wait a minute and fetch again.'}
        error = messages.get(exc.code, 'We could not read the appointment type from Acuity. Please try again.') + ' Support reference ' + reference + '.'
        form = None; item = None; existing = None; status = 503
    return render_template('service_import.html', m=m, fetch=fetch, form=form, item=item, existing=existing, error=error), status
