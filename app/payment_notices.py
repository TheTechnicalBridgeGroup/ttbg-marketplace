"""Durable financial notices; appointment confirmations remain owned by Acuity."""
import ssl,smtplib
from datetime import timedelta
from email.message import EmailMessage
from flask import current_app
from .models import db,now,PaymentNotice,PaymentOrder,FinancialEvent
from . import stripe_api as stripe
from .security import settings

def run_notices(limit=25):
    from .registration_security import mail_ready,normalized_email
    rows=PaymentNotice.query.join(PaymentOrder).filter(PaymentOrder.scope==stripe.scope(),PaymentNotice.state.in_(['queued','failed'])).order_by(PaymentNotice.id).limit(limit).all()
    for row in rows:
        if row.attempted_at and row.attempted_at>now()-timedelta(minutes=5):continue
        order=db.session.get(PaymentOrder,row.order_id)
        user=order.request.user_id
        from .models import User
        recipient=db.session.get(User,user) if user else None
        if not recipient:row.state='identity_removed';db.session.commit();continue
        if stripe.mode()=='mock':row.state='local_suppressed';db.session.commit();continue
        if not mail_ready():continue
        # A process interruption after send can be ambiguous. Never blindly resend an in-flight email.
        claimed=db.session.execute(db.update(PaymentNotice).where(PaymentNotice.id==row.id,PaymentNotice.state.in_(['queued','failed'])).values(state='sending',attempted_at=now(),attempts=PaymentNotice.attempts+1))
        if claimed.rowcount!=1:db.session.rollback();continue
        db.session.commit()
        event=db.session.get(FinancialEvent,row.event_id);c=current_app.config
        title='TTBG session and payment update'
        status=(event.after or {}).get('payment',order.payment_state).replace('_',' ')
        appointment='Cancelled' if event.action=='appointment_cancelled' else (event.after or {}).get('appointment','See your account').replace('_',' ')
        msg=EmailMessage();msg['Subject']=title;msg['From']=normalized_email(c['SMTP_FROM']);msg['To']=normalized_email(recipient.email)
        msg.set_content('Your TTBG session: '+order.request.service_name+'\n\nAppointment: '+appointment+'\nPayment / refund: '+status+'\nOriginal session amount: $'+format(order.gross_cents/100,'.2f')+' USD\n\nAppointment cancellation and a Stripe refund are separate. A refund is issued only after Stripe confirms it. Your bank determines credit timing.\n\nReview your current status: '+stripe.origin()+'/payments/orders/'+order.id+'\nContact: '+settings().support_email)
        try:
            ctx=ssl.create_default_context();cls=smtplib.SMTP_SSL if c['SMTP_SECURITY']=='ssl' else smtplib.SMTP
            kwargs={'host':c['SMTP_HOST'],'port':c['SMTP_PORT'],'timeout':10}
            if c['SMTP_SECURITY']=='ssl':kwargs['context']=ctx
            with cls(**kwargs) as smtp:
                if c['SMTP_SECURITY']=='starttls':smtp.ehlo();smtp.starttls(context=ctx);smtp.ehlo()
                smtp.login(c['SMTP_USERNAME'],c['SMTP_PASSWORD']);smtp.send_message(msg)
            row.state='sent';row.delivered_at=now();row.error_code=''
        except (smtplib.SMTPException,OSError,ValueError):
            row.state='uncertain';row.error_code='delivery_requires_review'
        db.session.commit()
    return len(rows)
