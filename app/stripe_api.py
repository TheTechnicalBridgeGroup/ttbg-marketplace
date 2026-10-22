"""Narrow Stripe v1 transport. Fixed origin, pinned version, bounded reads, no redirects."""
import base64
import hashlib
import hmac
import json
import re
import time
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError, URLError
from flask import current_app

API_VERSION = '2026-09-30.endive'
class StripeError(Exception):
    def __init__(self, code, definitive=False): self.code=code; self.definitive=definitive
class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args): return None

def mode(): return current_app.config.get('STRIPE_MODE','test')
def scope(): return mode()+':'+current_app.config.get('STRIPE_ACCOUNT_ID','')
def live(): return mode()=='live'
def configured():
    key=current_app.config.get('STRIPE_SECRET_KEY',''); account=current_app.config.get('STRIPE_ACCOUNT_ID','')
    if not re.fullmatch(r'acct_[A-Za-z0-9]+',account): return False
    if mode()=='mock':return key=='local-stripe-dummy-key' and account=='acct_local'
    return mode() in ('test','live') and key.startswith('sk_'+mode()+'_')

def origin():
    value=current_app.config.get('PUBLIC_BASE_URL','').rstrip('/'); u=urlsplit(value)
    if not u.hostname or u.username or u.password or u.query or u.fragment or u.path not in ('','/'):
        raise StripeError('public_origin_missing')
    if live() and u.scheme!='https':raise StripeError('https_required')
    if u.scheme not in ('https','http'):raise StripeError('public_origin_missing')
    return value

def validate_runtime():
    if mode() not in ('mock','test','live'):raise RuntimeError('STRIPE_MODE must be mock, test, or live')
    if mode()=='mock':
        if current_app.config.get('APP_ENV')!='local' or current_app.config.get('ACUITY_MODE')!='mock':
            raise RuntimeError('Stripe mock mode requires isolated local Acuity mock mode')
    if live() and current_app.config.get('ACUITY_MODE')=='mock':raise RuntimeError('Live Stripe cannot use mock Acuity')

def writable():
    if not configured():raise StripeError('stripe_configuration_missing')
    origin()
    if live() and (not current_app.config.get('STRIPE_LIVE_CONFIRMED') or current_app.config.get('APP_ENV')!='production'):
        raise StripeError('live_payments_not_confirmed')
    if mode()=='test' and current_app.config.get('APP_ENV')=='production':raise StripeError('test_payments_require_staging')

def flatten(data,prefix=''):
    pairs=[]
    if isinstance(data,dict):
        for k,v in data.items():pairs+=flatten(v,f'{prefix}[{k}]' if prefix else k)
    elif isinstance(data,list):
        for i,v in enumerate(data):pairs+=flatten(v,f'{prefix}[{i}]')
    elif data is not None:pairs.append((prefix,str(data).lower() if isinstance(data,bool) else str(data)))
    return pairs

def _raw(method,path,params=None,key=None):
    headers={'Authorization':'Basic '+base64.b64encode((current_app.config['STRIPE_SECRET_KEY']+':').encode()).decode(),
        'Stripe-Version':API_VERSION,'User-Agent':'TTBG-Marketplace/0.9.0','Accept':'application/json'}
    body=urlencode(flatten(params or {})).encode(); url='https://api.stripe.com/v1/'+path
    if key:headers['Idempotency-Key']='ttbg-v07-'+key
    if method=='GET':url+=('?'+body.decode()) if body else '';body=None
    else:headers['Content-Type']='application/x-www-form-urlencoded'
    try:
        with build_opener(NoRedirect()).open(Request(url,data=body,headers=headers,method=method),timeout=10) as r:
            raw=r.read(1024*1024+1)
            if len(raw)>1024*1024:raise StripeError('stripe_response_too_large')
            result=json.loads(raw)
            if not isinstance(result,dict):raise StripeError('stripe_invalid_response')
            return result
    except HTTPError as e:
        status=e.code;classification=None
        if status==400:
            try:
                detail=json.loads(e.read(8192));message=str((detail.get('error') or {}).get('message','')).lower()
                if 'platform profile' in message:classification='stripe_platform_profile_incomplete'
            except (ValueError,TypeError,AttributeError):pass
        e.close()
        if classification:raise StripeError(classification,True) from None
        raise StripeError('stripe_authentication_failed' if status in (401,403) else 'stripe_rate_limited' if status==429 else 'stripe_rejected' if status in (400,402,404) else 'stripe_unavailable',status in (400,401,402,403,404)) from None
    except (URLError,TimeoutError,OSError):raise StripeError('stripe_connection_failed') from None
    except (ValueError,UnicodeError):raise StripeError('stripe_invalid_response') from None

def api(method,path,params=None,key=None):
    if not configured():raise StripeError('stripe_configuration_missing')
    if method not in ('GET','POST') or not re.fullmatch(r'(account|accounts(?:/acct_[A-Za-z0-9]+(?:/login_links)?)?|account_links|checkout/sessions(?:/cs_[A-Za-z0-9_]+(?:/expire)?)?|payment_intents/pi_[A-Za-z0-9]+|charges/ch_[A-Za-z0-9]+|balance_transactions/txn_[A-Za-z0-9]+|refunds(?:/re_[A-Za-z0-9]+)?|transfers(?:/tr_[A-Za-z0-9]+(?:/reversals(?:/trr_[A-Za-z0-9]+)?)?)?|disputes/dp_[A-Za-z0-9]+)',path):
        raise ValueError('Unsupported Stripe endpoint')
    if method=='POST':
        writable()
        if not key:raise ValueError('Stripe writes require durable idempotency keys')
    if mode()=='mock':
        from .stripe_mock import api as mock_api
        return mock_api(method,path,params or {},key)
    platform=_raw('GET','account')
    if platform.get('id')!=current_app.config['STRIPE_ACCOUNT_ID'] or platform.get('country')!='US' or platform.get('default_currency')!='usd':raise StripeError('stripe_platform_mismatch')
    result=platform if path=='account' else _raw(method,path,params,key)
    if 'livemode' in result and result['livemode'] is not live():raise StripeError('stripe_mode_mismatch')
    return result

def verify_signature(raw,header,secret):
    if not secret or len(header)>2048:return False
    try:
        parts=[x.split('=',1) for x in header.split(',')]
        stamps=[v for k,v in parts if k=='t']; signatures=[v for k,v in parts if k=='v1']
        if len(stamps)!=1 or abs(time.time()-int(stamps[0]))>300:return False
        expected=hmac.new(secret.encode(),stamps[0].encode()+b'.'+raw,hashlib.sha256).hexdigest()
        return any(re.fullmatch(r'[0-9a-f]{64}',s) and hmac.compare_digest(expected,s) for s in signatures)
    except (ValueError,TypeError):return False

def redirect_url(value,kind):
    u=urlsplit(value or '')
    if mode()=='mock':
        expected=urlsplit(origin())
        if (u.scheme,u.netloc)==(expected.scheme,expected.netloc) and u.path.startswith('/payments/'):return value
    allowed={'checkout':'checkout.stripe.com','onboarding':'connect.stripe.com','receipt':'pay.stripe.com'}
    if u.scheme=='https' and u.hostname==allowed[kind] and not u.username and not u.password and u.port in (None,443):return value
    raise StripeError('stripe_invalid_redirect')
