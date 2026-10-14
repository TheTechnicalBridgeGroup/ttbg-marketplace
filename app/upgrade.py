from .models import db, User, Service, PlatformSettings, SchemaRevision

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
    db.session.commit()
