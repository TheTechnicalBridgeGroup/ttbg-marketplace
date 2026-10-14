from .models import db, MentorDetails, MentorAudit, now
from .forms import PROFILE_CHECKS
from flask_login import current_user

def details_for(m):
    if m.details: return m.details
    d=MentorDetails(mentor=m,activated_at=now())
    db.session.add(d)
    return d

def audit(m,action,detail=''):
    db.session.add(MentorAudit(mentor_id=m.id,actor_id=current_user.id,action=action,detail=detail))
    from .security import log
    log(action,f'mentor:{m.id}',detail)

def readiness(m):
    d=m.details
    checks=[('Biography complete',len((m.bio or '').strip())>=40),
            ('Experience recorded',len((m.experience or '').strip())>=10)]
    labels=['Application reviewed','Credentials reviewed','Agreement received','Orientation completed','Publication consent recorded']
    checks += [(label,bool(d and getattr(d,key))) for label,key in zip(labels,PROFILE_CHECKS)]
    from .registration_security import email_allowed
    checks.append(('Email verified or existing account',email_allowed(m.user)))
    checks.append(('Active service added',any(s.active for s in m.services)))
    return checks
