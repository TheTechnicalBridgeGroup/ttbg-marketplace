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
    db.session.commit()
