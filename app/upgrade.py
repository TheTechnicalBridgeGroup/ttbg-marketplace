from .models import db, User, Service, PlatformSettings, SchemaRevision, EmailIdentity

def upgrade():
    db.create_all()
    if db.session.get(PlatformSettings,1) is None:db.session.add(PlatformSettings(id=1))
    if db.session.get(SchemaRevision,'v0.3-account-management') is None:
        User.query.filter_by(role='onboarding').update({'role':'account_manager'})
        # Applies to future bookings only: previous Booking amount snapshots are untouched.
        Service.query.update({'fee_bps':2000})
        db.session.add(SchemaRevision(name='v0.3-account-management'))
    if db.session.get(SchemaRevision,'v0.4-support-center') is None:
        cfg=db.session.get(PlatformSettings,1)
        if cfg.scheduling_provider=='unselected':cfg.scheduling_provider='acuity'
        db.session.add(SchemaRevision(name='v0.4-support-center'))
    if db.session.get(SchemaRevision,'v0.5-verification') is None:
        # Preserve access for accounts already present at upgrade time. Do not claim mailbox verification.
        for user in User.query.outerjoin(EmailIdentity,EmailIdentity.user_id==User.id).filter(EmailIdentity.user_id.is_(None)):
            db.session.add(EmailIdentity(user_id=user.id,email=user.email,legacy_exempt=True))
        from .models import KnowledgePage,HelpSettings
        if db.session.get(HelpSettings,1) is None:db.session.add(HelpSettings(id=1,enabled=True,phone=''))
        if not KnowledgePage.query.first():
            guides=[
                ('Getting started','Welcome to TTBG documentation','# Your shared knowledge hub\nAdmins, account managers, and mentors can read every page here. Admins and account managers can add, edit, and delete pages.\n\n# Organize a guide\n- Use spaces to group related pages.\n- Add child pages for detailed instructions.\n- Use # headings and - list items in the editor.\n- Upload images with a useful description; the app compresses them automatically.\n\nKeep private account information, passwords, and API keys out of documentation.'),
                ('Mentor guides','Profile photos and booking','# Your profile picture\nOpen your dashboard and submit a JPEG, PNG, or WebP picture. An admin or account manager approves it before it becomes public.\n\n# Booking\nOpen a mentor service to see the configured scheduling experience. Live Acuity availability is a time lookup; a time shown as available is not a confirmed appointment or payment. Follow the contact-to-confirm instructions until TTBG enables a complete booking workflow.\n\n# Get help\nUse the help guide to submit a ticket, email the team, or call the configured team number.'),
                ('Platform guides','Accounts and email verification','# New accounts\nNew accounts must verify their email before using protected features. Open the email link and choose your password. Sign in to resend the email if needed. Links expire after one hour.\n\n# Existing accounts\nAccounts present before the verification upgrade keep their existing access. Changing an email address requires verification.\n\n# Account support\nAdmins and account managers use Support for troubleshooting. Only admins can permanently delete non-admin accounts, from Support > Account lookup > Account details. Admin accounts are protected from deletion. Financial snapshots and shared audit history remain under a non-login deleted-account reference. Passwords are never readable.')]
            for space,title,body in guides:db.session.add(KnowledgePage(space=space,title=title,body=body))
        db.session.add(SchemaRevision(name='v0.5-verification'))
    if db.session.get(SchemaRevision,'v0.6-acuity-appointments') is None:
        from .models import KnowledgePage
        db.session.add(KnowledgePage(space='Platform guides',title='Confirmed appointments and synchronization',body='# Booking a session\nWhen Acuity confirmed appointments is enabled, select a mentor and service, choose an available time, enter the requested details, and confirm. TTBG creates the Acuity appointment and saves its reference. Payment is arranged separately.\n\n# If confirmation is uncertain\nDo not submit another appointment. Contact TTBG with your request reference. Staff can search Acuity and reconcile the original request from Support > Appointment sync.\n\n# Schedule changes\nUse your Acuity confirmation email or contact TTBG for changes and cancellations. Automatic synchronization updates saved appointments after Acuity sends a change notification.\n\n# Staff setup\nVerify calendar and appointment type mappings under Support > Acuity mappings. An Admin enables automatic sync, then selects Acuity confirmed appointments in Settings. Check the v0.6 setup guide for live credentials and local practice mode.'))
        db.session.add(SchemaRevision(name='v0.6-acuity-appointments'))
    if db.session.get(SchemaRevision,'v0.7-stripe-connect') is None:
        from .models import KnowledgePage
        db.session.add(KnowledgePage(space='Platform guides',title='Payments, mentor earnings, and refunds',body='# TTBG payments\nWhen Stripe payments are enabled, paid sessions use secure Stripe Checkout before Acuity confirmation. Free consultations bypass Stripe. If confirmation is uncertain, do not pay again; ask Support to reconcile it.\n\n# Mentor earnings\nOpen Payments > Stripe payment setup and complete hosted onboarding. TTBG absorbs Stripe processing fees. The default allocation is 80% mentor and 20% TTBG; every booking keeps its original allocation. After your session ends, report completion from its payment details. Admins verify completion and approve transfers when funds and the account are ready. A transfer to Stripe is separate from a bank payout.\n\n# Staff operations\nAdmins and account managers use Support > Payments to investigate. Only Admins can approve completed sessions, transfer money, refund, or recover transfers. Each money action requires the Admin password and a reason. Cancellations hold transfers for review. Refunds do not cancel Acuity appointments. Uncertain appointments must be reconciled before refunding. Stripe disputes remain held until reviewed; evidence is submitted in Stripe.\n\n# Technical setup\nThe v0.7.0 ZIP includes STRIPE_V07_SETUP.md with credentials, signed snapshot webhooks, the required payment worker, local dummy-key practice, and the activation checklist. New paid checkout is disabled by default.'))
        db.session.add(SchemaRevision(name='v0.7-stripe-connect'))
    if db.session.get(SchemaRevision,'v0.8-financial-operations') is None:
        from .models import PaymentOrder,PaymentIdentity,KnowledgePage
        from .finance import identity,observe,emit,actor,external_cancel
        for table in (PaymentOrder.__table__,PaymentIdentity.__table__):
            for index in table.indexes:
                if index.name.endswith('_v08'):index.create(bind=db.engine,checkfirst=True)
        for order in PaymentOrder.query.order_by(PaymentOrder.created_at,PaymentOrder.id):
            identity(order)
            from .models import AcuityAppointment
            mirror=AcuityAppointment.query.filter_by(request_id=order.id).first()
            if mirror and mirror.cancelled:external_cancel(order,mirror,historical=True)
            emit(order,'historical_record_imported','succeeded',performed=actor(source='v0.8 migration'),reason='Historical amounts and provider IDs retained. Prior actor attribution not inferred.',key='v08-import:'+order.id)
            observe(order,source='v0.8 migration of last saved provider state')
        db.session.add(KnowledgePage(space='Platform guides',title='Financial operations and cancellation accountability',body='# Payment operations\nUse Support > Payments to search by friendly reference, name, Stripe ID, or Acuity ID. Filters and exports are scoped to the current Stripe account and environment. Test and simulation references are explicitly marked.\n\n# Cancellations\nStudents, mentors, and account managers submit requests. Admins verify and process cancellations. Unpaid student checkout cancellation can be completed directly. Staff names, roles, reasons, and UTC timestamps remain in the financial timeline. External Acuity cancellations have an unverified initiator; do not guess who cancelled.\n\n# Refunds and transfers\nCancellation is independent from payment/refund status. Only Admins approve full remaining refunds and mentor transfers. Refund eligibility requires review until leadership publishes a policy. Partial refunds are not included. Transferred to Stripe does not mean paid to bank.\n\n# Recovery\nKeep the payment worker running. Review uncertain provider outcomes before retrying writes. See FINANCIAL_OPERATIONS_V08.md for setup, migration, monitoring, and acceptance tests.'))
        db.session.add(SchemaRevision(name='v0.8-financial-operations'))
    if db.session.get(SchemaRevision,'v0.9-stability-diagnostics') is None:
        from .models import AcuityRequest
        for index in AcuityRequest.__table__.indexes:
            if index.name.endswith('_v09'):index.create(bind=db.engine,checkfirst=True)
        db.session.add(SchemaRevision(name='v0.9-stability-diagnostics'))
    db.session.commit()
