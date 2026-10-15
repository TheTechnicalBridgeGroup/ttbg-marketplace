"""Persistent, local-only Stripe simulator. Never accepts card or bank information."""
import secrets
import time
from copy import deepcopy
from flask import current_app
from .models import db, StripeMockObject, StripeMockKey
from .stripe_api import StripeError, origin

def get(oid):
    row=db.session.get(StripeMockObject,oid)
    if not row:raise StripeError('stripe_not_found',True)
    return deepcopy(row.payload)
def put(data,kind=None):
    row=db.session.get(StripeMockObject,data['id'])
    if not row:row=StripeMockObject(id=data['id'],kind=kind or data['object'],payload=data);db.session.add(row)
    else:row.payload=deepcopy(data)
    db.session.commit();return deepcopy(data)
def oid(prefix):return prefix+'_'+secrets.token_hex(12)
def disputed(charge):
    records=[x.payload for x in StripeMockObject.query.filter_by(kind='dispute') if x.payload.get('charge')==charge['id']]
    return charge['disputed'] and not (records and all(x.get('status') in ('won','warning_closed') for x in records))

def api(method,path,params,key):
    if current_app.config.get('APP_ENV')!='local' or current_app.config.get('ACUITY_MODE')!='mock':raise StripeError('mock_not_local')
    if method=='GET':
        if path=='account':return {'id':'acct_local','object':'account','country':'US','default_currency':'usd'}
        if path=='refunds':return {'data':[deepcopy(r.payload) for r in StripeMockObject.query.filter_by(kind='refund') if r.payload['charge']==params.get('charge')],'has_more':False}
        if path=='transfers':return {'data':[deepcopy(r.payload) for r in StripeMockObject.query.filter_by(kind='transfer') if r.payload['transfer_group']==params.get('transfer_group')],'has_more':False}
        data=get(path.split('/')[-1])
        if data.get('object')=='checkout.session' and data['status']=='open' and data['expires_at']<=int(time.time()):
            data['status']='expired';data['url']=None;put(data)
        return data
    known=db.session.get(StripeMockKey,key)
    if known:return get(known.object_id)
    meta=params.get('metadata',{})
    if path=='accounts':
        data=dict(id=oid('acct'),object='account',country='US',default_currency='usd',details_submitted=False,payouts_enabled=False,
                  controller={'is_controller':True},capabilities={'transfers':'inactive'},requirements={'currently_due':['external_account'],'disabled_reason':'requirements.past_due'},metadata=meta)
    elif path=='account_links':
        data=dict(id=oid('link'),object='account_link',url=origin()+'/payments/connect',expires_at=int(time.time())+300)
    elif path=='checkout/sessions':
        amount=params['line_items'][0]['price_data']['unit_amount']
        data=dict(id=oid('cs_test'),object='checkout.session',livemode=False,status='open',payment_status='unpaid',currency='usd',amount_total=amount,
                  mode='payment',client_reference_id=params['client_reference_id'],metadata=meta,payment_intent=None,expires_at=params['expires_at'])
        data['url']=origin()+'/payments/mock/checkout/'+data['id']
    elif path.endswith('/expire'):
        data=get(path.split('/')[-2])
        if data['status']!='open':raise StripeError('stripe_rejected',True)
        data['status']='expired';data['url']=None
    elif path=='refunds':
        charge=get(params['charge'])
        if disputed(charge) or params['amount']>charge['amount']-charge['amount_refunded']:raise StripeError('stripe_rejected',True)
        data=dict(id=oid('re'),object='refund',livemode=False,charge=charge['id'],amount=params['amount'],currency='usd',status='succeeded',metadata=meta)
        charge['amount_refunded']+=params['amount'];charge['refunded']=charge['amount_refunded']==charge['amount'];put(charge)
    elif path=='transfers':
        acct=get(params['destination']);charge=get(params['source_transaction'])
        if not acct['payouts_enabled'] or charge['amount_refunded'] or disputed(charge):raise StripeError('stripe_rejected',True)
        data=dict(id=oid('tr'),object='transfer',livemode=False,amount=params['amount'],currency='usd',destination=params['destination'],
                  source_transaction=params['source_transaction'],transfer_group=params['transfer_group'],amount_reversed=0,metadata=meta)
    elif path.endswith('/reversals'):
        transfer=get(path.split('/')[-2])
        if params['amount']>transfer['amount']-transfer['amount_reversed']:raise StripeError('stripe_rejected',True)
        data=dict(id=oid('trr'),object='transfer_reversal',amount=params['amount'],currency='usd',transfer=transfer['id'],metadata=meta)
        transfer['amount_reversed']+=params['amount'];put(transfer)
    else:raise StripeError('unsupported_mock_endpoint',True)
    put(data);db.session.add(StripeMockKey(id=key,object_id=data['id']));db.session.commit();return data

def ready(account_id):
    a=get(account_id);a.update(details_submitted=True,payouts_enabled=True,capabilities={'transfers':'active'},requirements={'currently_due':[],'disabled_reason':None});put(a)

def pay(session_id):
    s=get(session_id)
    if s['payment_status']=='paid':return s
    if s['status']!='open' or s['expires_at']<=int(time.time()):raise StripeError('checkout_expired',True)
    amount=s['amount_total'];pi=oid('pi');ch=oid('ch');tx=oid('txn')
    # Illustrative simulator fee only, not a claim about the merchant's Stripe pricing.
    fee=min(amount,round(amount*0.029)+30)
    put(dict(id=tx,object='balance_transaction',amount=amount,fee=fee,net=amount-fee,currency='usd',status='available',available_on=int(time.time())))
    put(dict(id=ch,object='charge',livemode=False,paid=True,captured=True,status='succeeded',amount=amount,currency='usd',payment_intent=pi,
             balance_transaction=tx,amount_refunded=0,refunded=False,disputed=False))
    put(dict(id=pi,object='payment_intent',livemode=False,status='succeeded',amount=amount,amount_received=amount,currency='usd',latest_charge=ch,metadata=s['metadata']))
    s.update(payment_status='paid',status='complete',payment_intent=pi,url=None);return put(s)
