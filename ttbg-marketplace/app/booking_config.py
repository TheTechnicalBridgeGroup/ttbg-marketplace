from urllib.parse import urlsplit
from .security import settings

PROVIDERS=[('unselected','Not selected'),('acuity','Acuity Scheduling'),('calcom','Cal.com'),('calendly','Calendly')]
HOSTS={'acuity':('acuityscheduling.com','as.me'),'calcom':('cal.com',),'calendly':('calendly.com',)}

def validate_booking_url(provider,value):
    if not value:return True
    try:
        u=urlsplit(value)
        if u.scheme!='https' or not u.hostname or u.username or u.password or u.port not in (None,443):return False
        if any(ord(c)<33 for c in value) or '\\' in value:return False
        return any(u.hostname==host or u.hostname.endswith('.'+host) for host in HOSTS.get(provider,()))
    except ValueError:return False

def scheduler_link(service):
    cfg=settings();link=service.scheduling
    if cfg.booking_mode!='external' or not link or link.provider!=cfg.scheduling_provider:return None
    return link.booking_url if validate_booking_url(link.provider,link.booking_url) else None

def split_amount(amount_cents,fee_bps=2000):
    if isinstance(amount_cents,bool) or not isinstance(amount_cents,int) or amount_cents<0:raise ValueError('Use non-negative integer cents.')
    if not isinstance(fee_bps,int) or not 0<=fee_bps<=10000:raise ValueError('Invalid commission.')
    company=(amount_cents*fee_bps+5000)//10000
    return {'gross_cents':amount_cents,'company_cents':company,'mentor_cents':amount_cents-company,'fee_bps':fee_bps}
