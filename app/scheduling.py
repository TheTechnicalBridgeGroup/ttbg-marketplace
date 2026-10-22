"""Cross-service, full-duration occupancy. Provider reads are never reservations.

Every new TTBG request checks this under the database write lock and commits a
creating/payment_pending record before network writes. Unknown outcomes remain
held until reconciliation; elapsed checkout timers alone do not release holds.
"""
from datetime import timedelta
from . import acuity
from .models import db,AcuityRequest,AcuityAppointment


def type_catalog():
    rows=acuity.api_get('appointment-types',{'includeDeleted':'true'})
    if not isinstance(rows,list):raise acuity.AcuityError('invalid_response')
    result={}
    for row in rows:
        if not isinstance(row,dict) or not str(row.get('id','')).isdigit() or str(row['id']) in result:
            raise acuity.AcuityError('invalid_response')
        result[str(row['id'])]=row
    return result


def minutes(value,minimum=0):
    try:
        number=int(value)
        if str(number)!=str(value) or not minimum<=number<=1440:raise ValueError()
        return number
    except (ValueError,TypeError):raise acuity.AcuityError('invalid_scheduling_duration') from None


def interval(start,duration,types,type_id):
    kind=types.get(str(type_id))
    if kind is None:raise acuity.AcuityError('scheduling_type_unverified')
    before=minutes(kind.get('paddingBefore',0));after=minutes(kind.get('paddingAfter',0))
    return start-timedelta(minutes=before),start+timedelta(minutes=minutes(duration,1)+after)


def overlaps(a,b):return a[0]<b[1] and b[0]<a[1]


def occupied(calendar_id,lo,hi,types,exclude_request=None):
    from .appointments import stamp
    # Three-day margin covers a 24h session plus supported 24h buffers and
    # provider-calendar/client timezone boundaries. Never filter by service type.
    lower=lo-timedelta(days=3);upper=hi+timedelta(days=3)
    rows=acuity.api_get('appointments',{'calendarID':calendar_id,'minDate':lower.date().isoformat(),
        'maxDate':upper.date().isoformat(),'max':100,'excludeForms':'true'})
    # Acuity has no offset pagination here. A saturated response is unsafe to
    # assume complete; staff must narrow/investigate rather than sell a slot.
    if not isinstance(rows,list) or len(rows)>=100:raise acuity.AcuityError('occupancy_not_verified')
    result=[]
    for row in rows:
        if not isinstance(row,dict):raise acuity.AcuityError('invalid_response')
        if row.get('canceled') is True:continue
        if row.get('canceled') is not False or str(row.get('calendarID'))!=str(calendar_id):raise acuity.AcuityError('invalid_response')
        result.append(interval(stamp(row.get('datetime')),row.get('duration'),types,row.get('appointmentTypeID')))
    query=AcuityRequest.query.filter(AcuityRequest.scope==acuity.scope(),AcuityRequest.calendar_id==str(calendar_id),
        AcuityRequest.starts_at>=lower,AcuityRequest.starts_at<=upper,
        AcuityRequest.state.in_(['creating','uncertain','payment_pending','deleted']))
    # Current locking read avoids a stale MySQL REPEATABLE READ snapshot after
    # a concurrent transaction has finished waiting for the global write lock.
    for req in query.with_for_update().all():
        if req.id==exclude_request:continue
        if req.state=='deleted' and AcuityAppointment.query.filter_by(request_id=req.id).first():continue
        payment=req.payment
        if payment and (payment.payment_state=='expired' or payment.booking_state in ('rejected','cancelled')):continue
        result.append(interval(req.starts_at,req.duration,types,req.type_id))
    return result


def conflicts(ids,starts,duration=None,exclude_request=None):
    types=type_catalog();kind=types.get(ids['appointmentTypeID'])
    if not kind:raise acuity.AcuityError('scheduling_type_unverified')
    candidate=interval(starts,duration if duration is not None else kind['duration'],types,ids['appointmentTypeID'])
    return any(overlaps(candidate,row) for row in occupied(ids['calendarID'],candidate[0],candidate[1],types,exclude_request))
