#!/usr/bin/env python3
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs, urlencode
import base64, datetime, hashlib, hmac, html, json, os, re, secrets
import gsc_client as gsc
import analytics_store as analytics
import app_download as app_download
import booking_bridge as booking
import booking_test as booking_test
import mercure_admin_client as mercure_admin
import mercure_public_client as mercure_public
import mobile_bootstrap as mobile_bootstrap
import mobile_devices as mobile_devices
import mobile_claim_delivery as mobile_claim_delivery
import mobile_authoritative_sync as mobile_authoritative_sync
import mobile_reminder_dispatch as mobile_reminder_dispatch
import geo_marketing as geo_marketing
import security_guard as security
import security_ai as security_ai
import security_integrity as security_integrity
import security_alerts as security_alerts
import competitive_intelligence as competitive
import review_followup as reviews
import integration_hub as integrations
import referral_engine as referrals
import referral_admin as referral_admin
import reminder_engine as reminders
import reminder_dispatch as reminder_dispatch
import notification_broker as notifications
import notification_preflight as notification_preflight
import production_readiness as production_readiness
import site_config_store as site_config_store
ROOT=Path(__file__).resolve().parent
USER='admin'
PRIVATE_DIR=Path(os.environ.get('CYBERCHECK_PRIVATE_DIR','/root/CyberCheckPrivate'))
PASSWORD=(PRIVATE_DIR/'admin-password').read_text().strip()
MAX_BODY=131072
CRAWLERS={
 'googlebot':'Googlebot','bingbot':'Bingbot','oaiSearchBot':'OAI-SearchBot','chatgptUser':'ChatGPT-User','gptBot':'GPTBot',
 'claudeSearchBot':'Claude-SearchBot','claudeUser':'Claude-User','claudeBot':'ClaudeBot','perplexityBot':'PerplexityBot','perplexityUser':'Perplexity-User','googleExtended':'Google-Extended'
}
INCENTIVE_DEFAULTS={
 'enabled':True,'label':'PRIX AVANTAGE',
 'eligibleServices':{'technical':True,'fitted':True},
 'defaultDiscountPercent':0.0,'maxDiscountPercent':0.0,'horizonDays':30,
 'allowedWeekdays':[1,2,3,4,5,6],'timeStart':'09:00','timeEnd':'19:00',
 'showOriginalPrice':True,'showDiscountPercent':True
}
def _hhmm(value,name):
 value=str(value or '')
 if not re.fullmatch(r'\d{2}:\d{2}',value): raise ValueError(f'{name} invalide')
 h,m=map(int,value.split(':'))
 if h>23 or m>59: raise ValueError(f'{name} invalide')
 return value
def incentive_config(c):
 raw=c.get('incentives') if isinstance(c,dict) else {}
 raw=raw if isinstance(raw,dict) else {}
 eligible=raw.get('eligibleServices') if isinstance(raw.get('eligibleServices'),dict) else {}
 days=raw.get('allowedWeekdays',INCENTIVE_DEFAULTS['allowedWeekdays'])
 if not isinstance(days,list): days=INCENTIVE_DEFAULTS['allowedWeekdays']
 out={
  'enabled':bool(raw.get('enabled',INCENTIVE_DEFAULTS['enabled'])),
  'label':str(raw.get('label') or INCENTIVE_DEFAULTS['label'])[:50],
  'eligibleServices':{'technical':bool(eligible.get('technical',True)),'fitted':bool(eligible.get('fitted',True))},
  'defaultDiscountPercent':float(raw.get('defaultDiscountPercent',0) or 0),
  'maxDiscountPercent':float(raw.get('maxDiscountPercent',0) or 0),
  'horizonDays':int(raw.get('horizonDays',30) or 30),
  'allowedWeekdays':sorted({int(x) for x in days if str(x).isdigit() and 0<=int(x)<=6}),
  'timeStart':str(raw.get('timeStart') or '09:00'),
  'timeEnd':str(raw.get('timeEnd') or '19:00'),
  'showOriginalPrice':bool(raw.get('showOriginalPrice',True)),
  'showDiscountPercent':bool(raw.get('showDiscountPercent',True)),
 }
 return out
def load_config(): return site_config_store.load()
def canonical_origin(url):
 p=urlparse(url); return f'{p.scheme}://{p.netloc}'
def asset_url(c,path):
 if path.startswith('https://'): return path
 return canonical_origin(c['seo']['canonicalUrl'])+'/'+path.lstrip('/')
def esc(v): return html.escape(str(v),quote=True)
class Handler(SimpleHTTPRequestHandler):
 server_version='CyberCheck'
 sys_version=''
 def version_string(self): return 'CyberCheck'
 def list_directory(self,path):
  self.send_error(404); return None
 def _guard(self):
  if getattr(self,'_security_checked',False): return getattr(self,'_security_allowed',True)
  self._security_checked=True
  raw_target=self.path
  if urlparse(raw_target).path=='/api/integrations/google/oauth/callback':
   raw_target=urlparse(raw_target).path
  d=security.evaluate(self.command,raw_target,self.headers,self.client_address[0] if self.client_address else '')
  self._security_client=d.get('client',''); self._security_fingerprint=d.get('fingerprint',''); self._security_path=d.get('path',''); self._security_risk=d.get('risk',0); self._security_allowed=bool(d.get('allow'))
  if self._security_allowed: return True
  status=int(d.get('status') or 403)
  if status==404: self.send_json({'error':'not_found'},404)
  elif self._security_path.startswith('/api/'): self.send_json({'ok':False,'error':'request_rejected'},status)
  else: self.send_bytes(b'Request rejected','text/plain; charset=utf-8',status)
  return False
 def send_response(self,code,message=None):
  try:
   if getattr(self,'_security_client','') and not getattr(self,'_security_response_recorded',False):
    security.observe_response(self._security_client,self.command,getattr(self,'_security_path',urlparse(self.path).path),int(code),getattr(self,'_security_risk',0),getattr(self,'_security_fingerprint','')); self._security_response_recorded=True
  except Exception: pass
  return super().send_response(code,message)
 def end_headers(self):
  self.send_header('X-Content-Type-Options','nosniff'); self.send_header('X-Frame-Options','DENY')
  self.send_header('Referrer-Policy',getattr(self,'_referrer_policy','strict-origin-when-cross-origin')); self.send_header('Cross-Origin-Opener-Policy','same-origin')
  self.send_header('Cross-Origin-Resource-Policy','same-site'); self.send_header('Permissions-Policy','camera=(), microphone=(), geolocation=(self)')
  nonce=getattr(self,'_csp_nonce',''); nonce_src=(" 'nonce-"+nonce+"'") if nonce else ''
  self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'"+nonce_src+" https://challenges.cloudflare.com; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; media-src 'self'; font-src 'self' data:; connect-src 'self' https://challenges.cloudflare.com; frame-src https://challenges.cloudflare.com; frame-ancestors 'none'; object-src 'none'; base-uri 'self'; form-action 'self' https://rdv.checkupauto.fr")
  self.send_header('Strict-Transport-Security','max-age=31536000; includeSubDomains')
  response_path=urlparse(self.path).path
  if response_path.startswith('/admin') or response_path=='/app/claim': self.send_header('X-Robots-Tag','noindex, nofollow, noarchive')
  return super().end_headers()
 def do_OPTIONS(self):
  if not self._guard(): return
  self.send_response(204); self.send_header('Allow','GET, HEAD, POST, DELETE, OPTIONS'); self.send_header('Content-Length','0'); self.end_headers()
 def _unsupported_method(self):
  self._guard()
 def do_PUT(self): return self._unsupported_method()
 def do_PATCH(self): return self._unsupported_method()
 def do_TRACE(self): return self._unsupported_method()
 def do_CONNECT(self): return self._unsupported_method()
 def translate_path(self,path):
  clean=urlparse(path).path
  if clean=='/admin': clean='/admin/'
  if clean=='/admin/': clean='/admin/index.html'
  return str(ROOT/clean.lstrip('/'))
 def send_bytes(self,data,ctype,status=200,cache='no-store'):
  self.send_response(status); self.send_header('Content-Type',ctype); self.send_header('Cache-Control',cache); self.send_header('Content-Length',str(len(data))); self.end_headers(); self.wfile.write(data)
 def send_json(self,obj,status=200): self.send_bytes(json.dumps(obj,ensure_ascii=False).encode(),'application/json; charset=utf-8',status)
 def send_redirect(self,location,status=302):
  self.send_response(status); self.send_header('Location',str(location)); self.send_header('Cache-Control','no-store'); self.send_header('Content-Length','0'); self.end_headers()
 def authorized(self):
  raw=self.headers.get('Authorization','')
  if not raw.startswith('Basic '): return False
  try: userpw=base64.b64decode(raw[6:]).decode('utf-8'); user,pw=userpw.split(':',1)
  except Exception: return False
  return hmac.compare_digest(user,USER) and hmac.compare_digest(pw,PASSWORD)
 def _request_origin(self):
  return canonical_origin(load_config()['seo']['canonicalUrl'])
 def _admin_origin_ok(self):
  origin=(self.headers.get('Origin') or '').strip()
  if not origin: return True
  try: origin_host=urlparse(origin).netloc.lower()
  except Exception: return False
  host=(self.headers.get('Host') or '').strip().lower()
  return bool(origin_host and host and hmac.compare_digest(origin_host,host))
 def require_auth(self):
  if self.headers.get('Authorization') and getattr(self,'_security_client',''):
   try: security.auth_failure(self._security_client,urlparse(self.path).path)
   except Exception: pass
  self.send_response(401); self.send_header('WWW-Authenticate','Basic realm="CyberCheck Administration", charset="UTF-8"'); self.send_header('Cache-Control','no-store'); self.end_headers();
  if self.command!='HEAD': self.wfile.write(b'Authentication required')
 def log_message(self,format,*args):
  # Do not persist client IP addresses in prototype access logs.
  return
 def do_HEAD(self):
  if not self._guard(): return
  path=urlparse(self.path).path
  dynamic={'/','/index.html','/app','/robots.txt','/sitemap.xml','/llms.txt','/zone-tarifs','/.well-known/security.txt','/api/site-config','/api/app/status','/api/mobile/bootstrap','/api/booking/services','/api/geo/coverage','/api/geo/quote'}
  if path in dynamic or path=='/api/booking/availability':
   self.send_response(200); self.send_header('Cache-Control','no-cache'); self.end_headers(); return
  if path=='/go/app':
   c=load_config(); q=parse_qs(urlparse(self.path).query); source=app_download.normalize_source((q.get('src') or ['direct'])[0]); app=app_download.status(c)
   target=app['ios'].get('targetUrl') if app['ios']['available'] else f'/app?src={source}'
   return self.send_redirect(target)
  if path.startswith('/admin'):
   if not self.authorized(): return self.require_auth()
   static_path='/admin/index.html' if path in ('/admin','/admin/') else path
   if security.static_allowed(static_path,True):
    original=self.path
    try:
     self.path=static_path
     return super().do_HEAD()
    finally:
     self.path=original
   self.send_response(404); self.end_headers(); return
  if security.static_allowed(path,False): return super().do_HEAD()
  self.send_response(404); self.end_headers(); return
 def render_index(self,c):
  nonce=secrets.token_urlsafe(18); self._csp_nonce=nonce
  raw=(ROOT/'index.html').read_text()
  seo=c['seo']; robots='index,follow,max-image-preview:large,max-snippet:-1,max-video-preview:-1' if seo['indexingEnabled'] else 'noindex,nofollow'
  raw=re.sub(r'<title>.*?</title>',f'<title>{esc(seo["title"])}</title>',raw,count=1,flags=re.S)
  raw=re.sub(r'<meta name="description" content="[^"]*">',f'<meta name="description" content="{esc(seo["description"])}">',raw,count=1)
  raw=re.sub(r'<!-- SEO_DYNAMIC_START -->.*?<!-- SEO_DYNAMIC_END -->\s*','',raw,flags=re.S)
  verify=f'<meta name="google-site-verification" content="{esc(seo["googleVerification"])}">' if seo.get('googleVerification') else ''
  structured=build_structured_data(c)
  block='''<!-- SEO_DYNAMIC_START -->
<meta name="robots" content="{robots}">
<link rel="canonical" href="{canonical}">
<meta property="og:type" content="website"><meta property="og:locale" content="fr_FR">
<meta property="og:site_name" content="{site}"><meta property="og:title" content="{title}">
<meta property="og:description" content="{description}"><meta property="og:url" content="{canonical}">
<meta property="og:image" content="{image}"><meta name="twitter:card" content="summary_large_image">
{verify}
<script nonce="{nonce}" type="application/ld+json">{jsonld}</script>
<!-- SEO_DYNAMIC_END -->'''.format(robots=robots,canonical=esc(seo['canonicalUrl']),site=esc(seo['siteName']),title=esc(seo['title']),description=esc(seo['description']),image=esc(asset_url(c,seo['ogImage'])),verify=verify,nonce=nonce,jsonld=json.dumps(structured,ensure_ascii=False,separators=(',',':')).replace('</','<\\/'))
  return raw.replace('</head>',block+'\n</head>',1).encode()
 def do_GET(self):
  if not self._guard(): return
  parsed=urlparse(self.path); path=parsed.path
  if path=='/api/integrations/google/oauth/callback':
   try:
    q=parse_qs(parsed.query)
    integrations.handle_oauth_callback(self._request_origin(),(q.get('state') or [''])[0],(q.get('code') or [''])[0],(q.get('error') or [''])[0])
    doc=('<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="robots" content="noindex,nofollow">'
         '<meta http-equiv="refresh" content="0;url=/admin/#integrations"><title>Google connecté</title></head>'
         '<body><p>Connexion Google enregistrée. <a href="/admin/#integrations">Retour à l’administration</a></p></body></html>').encode()
    return self.send_bytes(doc,'text/html; charset=utf-8',cache='no-store')
   except Exception:
    return self.send_bytes(('<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="robots" content="noindex,nofollow">'
      '<title>Connexion Google impossible</title></head><body><h1>Connexion Google impossible</h1><p>'+'La connexion Google n’a pas pu être finalisée.'+'</p>'
      '<p><a href="/admin/#integrations">Retour à l’administration</a></p></body></html>').encode(),'text/html; charset=utf-8',400,'no-store')
  if path=='/api/admin/readiness':
   if not self.authorized(): return self.require_auth()
   try:
    c=load_config(); return self.send_json(production_readiness.status(c,build_seo_health(c)))
   except Exception as exc: return self.send_json({'ok':False,'error':'readiness_unavailable'},500)
  if path=='/api/admin/integrations/google/status':
   if not self.authorized(): return self.require_auth()
   try:
    result=integrations.status(gsc.credential_info())
    result['redirectUri']=self._request_origin()+'/api/integrations/google/oauth/callback'
    return self.send_json(result)
   except Exception: return self.send_json({'ok':False,'error':'google_integration_status_unavailable'},500)
  if path=='/api/admin/referrals/accounts':
   if not self.authorized(): return self.require_auth()
   try:
    q=parse_qs(parsed.query); limit=int((q.get('limit') or ['100'])[0])
    return self.send_json(referral_admin.status(limit))
   except (TypeError,ValueError): return self.send_json({'ok':False,'error':'referral_request_invalid'},400)
   except Exception as exc: return self.send_json({'ok':False,'error':'referral_admin_unavailable'},500)
  if path=='/api/admin/referrals/summary':
   if not self.authorized(): return self.require_auth()
   try:
    q=parse_qs(parsed.query); code=(q.get('code') or [''])[0]
    return self.send_json(referrals.account_summary(code))
   except Exception as exc: return self.send_json({'ok':False,'error':'referral_summary_unavailable'},400)
  if path=='/api/admin/reminders/status':
   if not self.authorized(): return self.require_auth()
   try: return self.send_json(reminder_dispatch.status())
   except Exception as exc: return self.send_json({'ok':False,'error':'reminder_status_unavailable'},400)
  if path=='/api/admin/reminders/plan':
   if not self.authorized(): return self.require_auth()
   try:
    q=parse_qs(parsed.query); due=(q.get('due') or [''])[0]; timezone=(q.get('timezone') or [reminders.DEFAULT_TIMEZONE])[0]
    return self.send_json({'dueDate':due,'timezone':timezone,'events':reminders.plan_dicts(due,timezone=timezone)})
   except Exception as exc: return self.send_json({'ok':False,'error':'reminder_plan_invalid'},400)
  if path=='/api/admin/mobile/devices/status':
   if not self.authorized(): return self.require_auth()
   try:
    result=mobile_devices.status(); result['reminderDispatch']=mobile_reminder_dispatch.status(); result['claimDelivery']=mobile_claim_delivery.status(load_config()); return self.send_json(result)
   except Exception as exc: return self.send_json({'ok':False,'error':'mobile_status_unavailable'},400)
  if path=='/api/admin/mobile/claims/candidates':
   if not self.authorized(): return self.require_auth()
   try:
    q=parse_qs(parsed.query); limit=int((q.get('limit') or ['30'])[0])
    return self.send_json({'ok':True,'claimDelivery':mobile_claim_delivery.status(load_config()),'candidates':mobile_claim_delivery.candidates(limit)})
   except Exception as exc: return self.send_json({'ok':False,'error':'mobile_claim_candidates_unavailable'},400)
  if path=='/api/admin/notifications/status':
   if not self.authorized(): return self.require_auth()
   try:
    q=parse_qs(parsed.query); limit=int((q.get('limit') or ['20'])[0])
    return self.send_json(notifications.status(limit))
   except Exception as exc: return self.send_json({'ok':False,'error':'notification_status_unavailable'},400)
  if path=='/api/admin/analytics':
   if not self.authorized(): return self.require_auth()
   try:
    q=parse_qs(parsed.query); days=int(q.get('days',['30'])[0]); return self.send_json(booking.merge_into_analytics(analytics.summary(days)))
   except Exception as exc: return self.send_json({'ok':False,'error':'analytics_summary_unavailable'},400)
  if path=='/api/admin/seo-health':
   if not self.authorized(): return self.require_auth()
   return self.send_json(build_seo_health(load_config()))
  if path=='/api/admin/reviews/status':
   if not self.authorized(): return self.require_auth()
   try: return self.send_json(reviews.status())
   except Exception as exc: return self.send_json({'ok':False,'error':'review_status_unavailable'},400)
  if path=='/api/admin/competitive/summary':
   if not self.authorized(): return self.require_auth()
   try: return self.send_json(competitive.summary())
   except Exception as exc: return self.send_json({'ok':False,'error':'competitive_summary_unavailable'},400)
  if path=='/api/admin/competitive/connectors':
   if not self.authorized(): return self.require_auth()
   try: return self.send_json(competitive.connector_status())
   except Exception as exc: return self.send_json({'ok':False,'error':'competitive_connectors_unavailable'},400)
  if path=='/api/admin/security/status':
   if not self.authorized(): return self.require_auth()
   try:
    q=parse_qs(parsed.query); days=int((q.get('days') or ['1'])[0]); return self.send_json(security.status(days))
   except Exception as exc: return self.send_json({'ok':False,'error':'security_status_unavailable'},400)
  if path=='/api/admin/security/ai':
   if not self.authorized(): return self.require_auth()
   try: return self.send_json(security_ai.latest())
   except Exception as exc: return self.send_json({'ok':False,'error':'security_ai_unavailable'},400)
  if path=='/api/admin/security/posture':
   if not self.authorized(): return self.require_auth()
   try: return self.send_json(security_integrity.posture())
   except Exception as exc: return self.send_json({'ok':False,'error':'security_posture_unavailable'},400)
  if path=='/api/admin/security/alerts':
   if not self.authorized(): return self.require_auth()
   try: return self.send_json(security_alerts.summary())
   except Exception as exc: return self.send_json({'ok':False,'error':'security_alerts_unavailable'},400)
  if path=='/api/admin/security/sbom':
   if not self.authorized(): return self.require_auth()
   try: return self.send_json(security_integrity.generate_sbom())
   except Exception as exc: return self.send_json({'ok':False,'error':'security_sbom_unavailable'},400)
  if path=='/api/booking-test/status':
   try:
    q=parse_qs(parsed.query); token=(q.get('token') or [''])[0]
    return self.send_json(booking_test.status(token))
   except PermissionError as exc: return self.send_json({'ok':False,'error':str(exc)},403)
   except Exception: return self.send_json({'ok':False,'error':'booking_test_status_unavailable'},400)
  if path=='/api/booking/services':
   c=load_config(); return self.send_json({'centreId':240,'services':mercure_public.public_services(),'callOnly':True,'incentives':incentive_config(c)})
  if path=='/api/geo/coverage':
   try: return self.send_json(geo_marketing.coverage(load_config(),mercure_public.public_services()))
   except Exception: return self.send_json({'ok':False,'error':'geo_coverage_unavailable'},400)
  if path=='/api/geo/quote':
   try:
    q=parse_qs(parsed.query); city=(q.get('city') or q.get('postalCode') or [''])[0]
    return self.send_json(geo_marketing.quote(load_config(),city,mercure_public.public_services()))
   except ValueError as exc: return self.send_json({'ok':False,'error':str(exc)},400)
   except Exception: return self.send_json({'ok':False,'error':'geo_quote_unavailable'},502)
  if path=='/api/booking/availability':
   try:
    q=parse_qs(parsed.query); service=(q.get('service') or ['technical'])[0]; date=(q.get('date') or [datetime.date.today().isoformat()])[0]; c=load_config(); policy=incentive_config(c)
    requested=datetime.date.fromisoformat(date); limit=datetime.date.today()+datetime.timedelta(days=int(policy['horizonDays']))
    if requested>limit: raise ValueError(f"Date hors horizon de réservation ({policy['horizonDays']} jours)")
    result=mercure_public.availability(service,date); result['incentives']=policy; return self.send_json(result)
   except ValueError as exc: return self.send_json({'ok':False,'error':str(exc)},400)
   except Exception: return self.send_json({'ok':False,'error':'booking_availability_unavailable'},502)
  if path=='/go/app':
   c=load_config(); q=parse_qs(parsed.query); source=app_download.normalize_source((q.get('src') or ['direct'])[0]); app=app_download.status(c); ios=app['ios']
   if not ios['available']: return self.send_redirect(f'/app?src={source}')
   try:
    event='app_store_click' if ios['channel']=='app-store' else 'app_testflight_click'
    analytics.record_event({'event':event,'path':'/app','device':'unknown','referrer':self.headers.get('Referer',''),'utmSource':'app:'+source,'utmCampaign':app['campaign'],'service':ios['channel']},int((c.get('analytics') or {}).get('retentionDays',180)))
   except Exception: pass
   return self.send_redirect(ios['targetUrl'])
  if path=='/go/booking':
   try:
    c=load_config(); q=parse_qs(parsed.query)
    params={k:(v[0] if v else '') for k,v in q.items()}; service=params.get('service','')
    if not booking.mercure_prestation(service):
     phone=esc(c['business']['phone']); tel=re.sub(r'[^+\d]','',c['business']['phone'])
     doc=f'''<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,nofollow"><title>Réservation par téléphone</title><style>body{{font-family:system-ui;background:#f5f6f1;color:#111;padding:32px}}main{{max-width:620px;margin:auto}}a{{display:inline-block;padding:14px 20px;border-radius:999px;background:#111;color:#fff;text-decoration:none}}</style></head><body><main><h1>Cette prestation se réserve par téléphone.</h1><p>La réservation en ligne est limitée aux contrôles à 80 € et 90 €.</p><a href="tel:{tel}">Appeler le centre · {phone}</a></main></body></html>'''.encode()
     return self.send_bytes(doc,'text/html; charset=utf-8',cache='no-store')
    result=booking.create_intent(params,c['business']['bookingUrl']); nonce=secrets.token_urlsafe(18); self._csp_nonce=nonce; doc=booking.auto_submit_html(result['token'],service,nonce)
    return self.send_bytes(doc,'text/html; charset=utf-8',cache='no-store')
   except Exception: return self.send_json({'ok':False,'error':'booking_request_failed'},400)
  if path.startswith('/api/admin/mercure/'):
   if not self.authorized(): return self.require_auth()
   try:
    c=load_config(); days=int(parse_qs(parsed.query).get('days',['30'])[0])
    if path=='/api/admin/mercure/status':
     return self.send_json({'provider':'AutoBilan-Systems / Mercure RDV','centreId':240,'bookingUrl':c['business']['bookingUrl'],'secret':booking.secret_info(False),'stats':booking.stats(days),'providerProtection':mercure_public.provider_health(),'webhookUrl':canonical_origin(c['seo']['canonicalUrl'])+'/api/integrations/mercure/booking-confirmed','browserCallbackUrl':canonical_origin(c['seo']['canonicalUrl'])+'/api/integrations/mercure/browser-confirmed'})
    if path=='/api/admin/mercure/live-summary': return self.send_json(mercure_admin.live_summary(days))
    if path=='/api/admin/mercure/session-status': return self.send_json(mercure_admin.session_status())
    if path=='/api/admin/mercure/promotions':
     q=parse_qs(parsed.query); today=datetime.date.today(); start=(q.get('start') or [today.isoformat()])[0]; end=(q.get('end') or [(today+datetime.timedelta(days=30)).isoformat()])[0]
     return self.send_json({'promotions':mercure_admin.list_promotions(),'events':mercure_admin.promotion_events(start,end),'start':start,'end':end})
    if path=='/api/admin/mercure/secret': return self.send_json(booking.secret_info(True))
    return self.send_json({'error':'not_found'},404)
   except Exception as exc: return self.send_json({'ok':False,'error':'mercure_admin_request_failed'},400)
  if path.startswith('/api/admin/google/'):
   if not self.authorized(): return self.require_auth()
   c=load_config(); site=c['seo'].get('searchConsoleProperty') or c['seo']['canonicalUrl']
   try:
    if path=='/api/admin/google/status':
     info=gsc.credential_info(); result={'credentials':info,'property':site,'connected':False}
     if info['configured']:
      check=gsc.property_status(site); result.update(check); result['connected']=check['accessible']
     return self.send_json(result)
    if path=='/api/admin/google/properties': return self.send_json({'properties':gsc.list_properties()})
    if path=='/api/admin/google/performance':
     q=parse_qs(parsed.query); days=int(q.get('days',['28'])[0]); return self.send_json(gsc.performance(site,days))
    if path=='/api/admin/google/sitemaps': return self.send_json({'sitemaps':gsc.list_sitemaps(site)})
   except Exception: return self.send_json({'ok':False,'error':'google_search_console_unavailable'},502)
  if path.startswith('/p/'):
   code=referrals.valid_code_or_empty(path[3:])
   if not code: return self.send_json({'error':'referral_not_found'},404)
   target='/?'+urlencode({'ref':code})
   self.send_response(302); self.send_header('Location',target); self.send_header('Cache-Control','no-store'); self.send_header('X-Robots-Tag','noindex, nofollow'); self.end_headers(); return
  if path=='/.well-known/security.txt':
   return self.send_bytes(build_security_txt(load_config()).encode(),'text/plain; charset=utf-8',cache='public, max-age=3600')
  if path in ('/.well-known/apple-app-site-association','/apple-app-site-association'):
   try:
    return self.send_bytes(mobile_claim_delivery.association_document(load_config()),'application/json',cache='public, max-age=3600')
   except Exception:
    return self.send_json({'error':'association_not_ready'},503)
  if path=='/zone-tarifs':
   return self.send_bytes(build_geo_pricing_page(load_config()),'text/html; charset=utf-8',cache='no-cache')
  if path=='/app/claim':
   self._referrer_policy='no-referrer'
   return self.send_bytes(mobile_claim_delivery.claim_landing_html(load_config()),'text/html; charset=utf-8',cache='no-store')
  if path=='/app':
   c=load_config(); q=parse_qs(parsed.query); source=app_download.normalize_source((q.get('src') or ['direct'])[0]); nonce=secrets.token_urlsafe(18); self._csp_nonce=nonce
   return self.send_bytes(app_download.landing_html(c,source,nonce),'text/html; charset=utf-8',cache='no-cache')
  if path in ('/','/index.html'):
   return self.send_bytes(self.render_index(load_config()),'text/html; charset=utf-8',cache='no-cache')
  if path=='/robots.txt': return self.send_bytes(build_robots(load_config()).encode(),'text/plain; charset=utf-8',cache='no-cache')
  if path=='/sitemap.xml': return self.send_bytes(build_sitemap(load_config()).encode(),'application/xml; charset=utf-8',cache='no-cache')
  if path=='/llms.txt': return self.send_bytes(build_llms(load_config()).encode(),'text/plain; charset=utf-8',cache='no-cache')
  if path=='/api/site-config': return self.send_json(load_config())
  if path=='/api/app/status': return self.send_json(app_download.status(load_config()))
  if path=='/api/mobile/bootstrap':
   try: return self.send_json(mobile_bootstrap.status(load_config()))
   except Exception: return self.send_json({'ok':False,'error':'mobile_bootstrap_unavailable'},500)
  if path=='/api/admin/config':
   if not self.authorized(): return self.require_auth()
   return self.send_json(load_config())
  if path.startswith('/admin'):
   if not self.authorized(): return self.require_auth()
   static_path='/admin/index.html' if path in ('/admin','/admin/') else path
   if security.static_allowed(static_path,True):
    original=self.path
    try:
     self.path=static_path
     return super().do_GET()
    finally:
     self.path=original
   return self.send_json({'error':'not_found'},404)
  if security.static_allowed(path,False): return super().do_GET()
  return self.send_json({'error':'not_found'},404)
 def _read_json(self, allow_empty=False):
  length=int(self.headers.get('Content-Length','0'))
  if length==0 and allow_empty: return {}
  if length<=0 or length>MAX_BODY: raise ValueError('invalid body size')
  return json.loads(self.rfile.read(length))
 def do_POST(self):
  if not self._guard(): return
  path=urlparse(self.path).path
  if path=='/api/integrations/mercure/browser-confirmed':
   try:
    origin=self.headers.get('Origin','')
    if origin and origin!='https://rdv.checkupauto.fr': return self.send_json({'ok':False,'error':'origin_not_allowed'},403)
    payload=self._read_json(); result=booking.browser_confirmation(payload)
    data=json.dumps(result,ensure_ascii=False).encode()
    self.send_response(201); self.send_header('Content-Type','application/json; charset=utf-8')
    self.send_header('Cache-Control','no-store'); self.send_header('Access-Control-Allow-Origin','https://rdv.checkupauto.fr')
    self.send_header('Vary','Origin'); self.send_header('Content-Length',str(len(data))); self.end_headers(); self.wfile.write(data); return
   except PermissionError as exc: return self.send_json({'ok':False,'error':str(exc)},401)
   except Exception: return self.send_json({'ok':False,'error':'mercure_browser_confirmation_invalid'},400)
  if path=='/api/integrations/mercure/booking-confirmed':
   try:
    length=int(self.headers.get('Content-Length','0'))
    if length<=0 or length>MAX_BODY: raise ValueError('invalid body size')
    raw=self.rfile.read(length)
    if not booking.verify_signature(raw,self.headers.get('X-CyberCheck-Signature')):
     return self.send_json({'ok':False,'error':'invalid signature'},401)
    payload=json.loads(raw); return self.send_json(booking.apply_conversion(payload),200)
   except Exception: return self.send_json({'ok':False,'error':'mercure_booking_confirmation_invalid'},400)
  if path=='/api/mobile/installations/register':
   try:
    ctype=(self.headers.get('Content-Type') or '').split(';',1)[0].strip().lower()
    if ctype!='application/json': return self.send_json({'ok':False,'error':'content_type_not_allowed'},415)
    return self.send_json(mobile_devices.register_installation(self._read_json()),201)
   except PermissionError as exc: return self.send_json({'ok':False,'error':str(exc)},403)
   except Exception: return self.send_json({'ok':False,'error':'mobile_request_invalid'},400)
  if path=='/api/mobile/installations/delete':
   try:
    ctype=(self.headers.get('Content-Type') or '').split(';',1)[0].strip().lower()
    if ctype!='application/json': return self.send_json({'ok':False,'error':'content_type_not_allowed'},415)
    return self.send_json(mobile_devices.delete_installation(self._read_json()),200)
   except PermissionError as exc: return self.send_json({'ok':False,'error':str(exc)},403)
   except Exception: return self.send_json({'ok':False,'error':'mobile_request_invalid'},400)
  if path=='/api/mobile/devices/register':
   try:
    ctype=(self.headers.get('Content-Type') or '').split(';',1)[0].strip().lower()
    if ctype!='application/json': return self.send_json({'ok':False,'error':'content_type_not_allowed'},415)
    return self.send_json(mobile_devices.register(self._read_json()),201)
   except PermissionError as exc: return self.send_json({'ok':False,'error':str(exc)},403)
   except Exception: return self.send_json({'ok':False,'error':'mobile_request_invalid'},400)
  if path=='/api/mobile/devices/unregister':
   try:
    ctype=(self.headers.get('Content-Type') or '').split(';',1)[0].strip().lower()
    if ctype!='application/json': return self.send_json({'ok':False,'error':'content_type_not_allowed'},415)
    return self.send_json(mobile_devices.unregister(self._read_json()))
   except PermissionError as exc: return self.send_json({'ok':False,'error':str(exc)},403)
   except Exception: return self.send_json({'ok':False,'error':'mobile_request_invalid'},400)
  if path=='/api/mobile/claims/consume':
   try:
    ctype=(self.headers.get('Content-Type') or '').split(';',1)[0].strip().lower()
    if ctype!='application/json': return self.send_json({'ok':False,'error':'content_type_not_allowed'},415)
    payload=self._read_json()
    result=mobile_devices.consume_vehicle_claim(payload)
    try:
     mobile_authoritative_sync.sync_installation(str(payload.get('installationId') or ''))
    except Exception:
     pass
    return self.send_json(result,200)
   except PermissionError as exc: return self.send_json({'ok':False,'error':str(exc)},403)
   except Exception: return self.send_json({'ok':False,'error':'mobile_request_invalid'},400)
  if path=='/api/mobile/inventory':
   try:
    ctype=(self.headers.get('Content-Type') or '').split(';',1)[0].strip().lower()
    if ctype!='application/json': return self.send_json({'ok':False,'error':'content_type_not_allowed'},415)
    payload=self._read_json()
    mobile_devices.bound_inventory(payload)
    try:
     mobile_authoritative_sync.sync_installation(str(payload.get('installationId') or ''))
    except Exception:
     pass
    return self.send_json(mobile_devices.bound_inventory(payload),200)
   except PermissionError as exc: return self.send_json({'ok':False,'error':str(exc)},403)
   except Exception: return self.send_json({'ok':False,'error':'mobile_request_invalid'},400)
  if path=='/api/mobile/reminders/sync':
   try:
    ctype=(self.headers.get('Content-Type') or '').split(';',1)[0].strip().lower()
    if ctype!='application/json': return self.send_json({'ok':False,'error':'content_type_not_allowed'},415)
    return self.send_json(mobile_devices.sync_deadlines(self._read_json()))
   except PermissionError as exc: return self.send_json({'ok':False,'error':str(exc)},403)
   except Exception: return self.send_json({'ok':False,'error':'mobile_request_invalid'},400)
  if path=='/api/events':
   try:
    c=load_config(); cfg=c.get('analytics',{})
    if not cfg.get('enabled',True): return self.send_json({'ok':True,'disabled':True})
    payload=self._read_json(); result=analytics.record_event(payload,int(cfg.get('retentionDays',180)))
    return self.send_json(result,201)
   except Exception: return self.send_json({'ok':False,'error':'analytics_event_invalid'},400)
  if path=='/api/booking-test/create':
   try:
    payload=self._read_json(); result=booking_test.create_appointment(str(payload.get('token') or ''),str(payload.get('service') or ''),str(payload.get('date') or ''),str(payload.get('time') or ''))
    return self.send_json(result,201)
   except PermissionError as exc: return self.send_json({'ok':False,'error':str(exc)},403)
   except Exception: return self.send_json({'ok':False,'error':'booking_test_request_invalid'},400)
  if path=='/api/booking-test/remove':
   try:
    payload=self._read_json(); return self.send_json(booking_test.remove_appointment(str(payload.get('token') or '')))
   except PermissionError as exc: return self.send_json({'ok':False,'error':str(exc)},403)
   except Exception: return self.send_json({'ok':False,'error':'booking_test_request_invalid'},400)
  if path.startswith('/api/admin/'):
   if not self.authorized(): return self.require_auth()
   if not self._admin_origin_ok(): return self.send_json({'ok':False,'error':'origin_not_allowed'},403)
   ctype=(self.headers.get('Content-Type') or '').split(';',1)[0].strip().lower()
   if ctype!='application/json': return self.send_json({'ok':False,'error':'content_type_not_allowed'},415)
  if path=='/api/admin/mobile/claims/issue':
   try:
    payload=self._read_json(); claim=mobile_claim_delivery.issue_for_vehicle(load_config(),payload.get('vehicleId'),payload.get('ttlSeconds'))
    return self.send_json({'ok':True,'claim':claim},201)
   except LookupError as exc: return self.send_json({'ok':False,'error':'mobile_claim_not_found'},404)
   except RuntimeError as exc: return self.send_json({'ok':False,'error':'mobile_claim_conflict'},409)
   except Exception as exc: return self.send_json({'ok':False,'error':'mobile_claim_request_invalid'},400)
  if path=='/api/admin/referrals/account':
   try:
    payload=self._read_json(allow_empty=True); account=referrals.create_account(payload.get('code') or '',payload.get('rewardCents'))
    return self.send_json({'ok':True,'account':account},201)
   except Exception as exc: return self.send_json({'ok':False,'error':'referral_request_invalid'},400)
  if path=='/api/admin/referrals/redeem':
   try:
    payload=self._read_json(); result=referrals.redeem(payload.get('code'),int(payload.get('amountCents')),payload.get('reference'))
    return self.send_json({'ok':True,'account':result})
   except Exception as exc: return self.send_json({'ok':False,'error':'referral_request_invalid'},400)
  if path=='/api/admin/integrations/google/oauth-client':
   try:
    payload=self._read_json(); return self.send_json({'ok':True,'oauthClient':integrations.save_oauth_client(payload)})
   except Exception: return self.send_json({'ok':False,'error':'google_integration_request_failed'},400)
  if path=='/api/admin/integrations/google/settings':
   try:
    payload=self._read_json(); return self.send_json({'ok':True,'settings':integrations.save_settings(payload)})
   except Exception: return self.send_json({'ok':False,'error':'google_integration_request_failed'},400)
  if path=='/api/admin/integrations/google/oauth/start':
   try:
    payload=self._read_json(); connectors=payload.get('connectors') or []
    if not isinstance(connectors,list): raise ValueError('connectors doit être une liste')
    result=integrations.create_authorization_url(self._request_origin(),[str(x) for x in connectors])
    return self.send_json({'ok':True,**result})
   except Exception: return self.send_json({'ok':False,'error':'google_integration_request_failed'},400)
  if path=='/api/admin/mercure/login':
   try:
    payload=self._read_json(); result=mercure_admin.login(payload.get('username'),payload.get('password'))
    return self.send_json({'ok':True,**result})
   except PermissionError as exc: return self.send_json({'ok':False,'error':'mercure_auth_failed'},401)
   except Exception as exc: return self.send_json({'ok':False,'error':'mercure_login_failed'},400)
  if path=='/api/admin/booking-test/session':
   try:
    booking_test.purge_expired(); result=booking_test.create_session(); c=load_config()
    host=(self.headers.get('Host') or '').strip(); proto=(self.headers.get('X-Forwarded-Proto') or 'https').split(',')[0].strip()
    origin=(proto+'://'+host) if host else canonical_origin(c['seo']['canonicalUrl'])
    result['url']=origin+'/?bookingTest='+result['token']+'#reservation'
    return self.send_json({'ok':True,**result},201)
   except Exception as exc: return self.send_json({'ok':False,'error':'booking_test_session_failed'},400)
  if path=='/api/admin/notifications/preflight':
   try:
    self._read_json(allow_empty=True); return self.send_json(notification_preflight.run())
   except Exception as exc: return self.send_json({'ok':False,'error':'notification_preflight_failed'},400)
  if path=='/api/admin/notifications/permanent/recipient-check':
   try:
    payload=self._read_json(); return self.send_json(reminder_dispatch.permanent_recipient_check(payload.get('incidentId')))
   except LookupError as exc: return self.send_json({'ok':False,'error':'permanent_failure_not_found'},404)
   except ValueError as exc: return self.send_json({'ok':False,'error':'recipient_check_invalid'},400)
   except Exception as exc: return self.send_json({'ok':False,'error':'recipient_check_unavailable'},500)
  if path=='/api/admin/notifications/permanent/retry':
   try:
    payload=self._read_json(); result=reminder_dispatch.permanent_recipient_retry(payload.get('incidentId'))
    return self.send_json(result,200 if result.get('ok') else 409)
   except LookupError as exc: return self.send_json({'ok':False,'error':'permanent_failure_not_found'},404)
   except ValueError as exc: return self.send_json({'ok':False,'error':'recipient_retry_invalid'},400)
   except Exception as exc: return self.send_json({'ok':False,'error':'recipient_retry_unavailable'},500)
  if path=='/api/admin/notifications/permanent/action':
   try:
    payload=self._read_json(); return self.send_json(notifications.permanent_failure_action(payload.get('incidentId'),payload.get('action')))
   except LookupError: return self.send_json({'ok':False,'error':'permanent_failure_not_found'},404)
   except ValueError as exc: return self.send_json({'ok':False,'error':'permanent_failure_action_invalid'},400)
   except Exception as exc: return self.send_json({'ok':False,'error':'permanent_failure_action_unavailable'},500)
  if path=='/api/admin/reminders/process':
   try: return self.send_json(reminder_dispatch.process_once())
   except Exception as exc: return self.send_json({'ok':False,'error':'reminder_process_failed'},400)
  if path=='/api/admin/reviews/process':
   try: return self.send_json(reviews.process_once())
   except Exception as exc: return self.send_json({'ok':False,'error':'review_process_failed'},400)
  if path=='/api/admin/competitive/observation':
   try:
    payload=self._read_json(); cid=str(payload.get('competitorId') or '').strip(); category=str(payload.get('category') or '').strip(); source=str(payload.get('source') or 'admin').strip(); data=payload.get('data')
    if not cid or not category or not isinstance(data,dict): raise ValueError('Observation invalide')
    competitive.add_observation(cid,source,category,data,str(payload.get('sourceUrl') or '')); return self.send_json({'ok':True},201)
   except Exception as exc: return self.send_json({'ok':False,'error':'competitive_request_invalid'},400)
  if path=='/api/admin/competitive/review':
   try:
    payload=self._read_json(); cid=str(payload.get('competitorId') or '').strip(); review_text=str(payload.get('text') or '').strip()
    if not cid or not review_text: raise ValueError('Avis invalide')
    competitive.add_review(cid,str(payload.get('source') or 'admin'),review_text,payload.get('rating'),str(payload.get('externalId') or ''),str(payload.get('reviewedAt') or ''),bool(payload.get('ownerResponse'))); return self.send_json({'ok':True},201)
   except Exception as exc: return self.send_json({'ok':False,'error':'competitive_request_invalid'},400)
  if path=='/api/admin/security/alerts/ack':
   try:
    payload=self._read_json(); return self.send_json(security_alerts.acknowledge(int(payload.get('id'))))
   except Exception as exc: return self.send_json({'ok':False,'error':'security_alert_request_invalid'},400)
  if path=='/api/admin/security/vulnerability-refresh':
   try: return self.send_json({'ok':True,'audit':security_integrity.audit_vulnerabilities(True)})
   except Exception as exc: return self.send_json({'ok':False,'error':'security_vulnerability_refresh_failed'},502)
  if path=='/api/admin/security/assess':
   try: return self.send_json({'ok':True,'assessment':security_ai.assess()})
   except Exception as exc: return self.send_json({'ok':False,'error':'security_assessment_failed'},400)
  if path=='/api/admin/mercure/promo-slot':
   try:
    payload=self._read_json(); c=load_config(); policy=incentive_config(c)
    if not policy['enabled']: raise ValueError('Le système d’incitation est désactivé')
    service_key=str(payload.get('service') or '').strip(); meta=mercure_public.service(service_key)
    if not policy['eligibleServices'].get(service_key,False): raise ValueError('Cette prestation n’est pas éligible aux remises')
    final=float(payload.get('finalPrice')); base=float(meta['basePrice'])
    if final<=0 or final>=base: raise ValueError(f'Le prix promotionnel doit être compris entre 0 et {base:.0f} €')
    discount=round((base-final)/base*100,2)
    cap=float(policy.get('maxDiscountPercent') or 0)
    if cap>0 and discount>cap+0.001: raise ValueError(f'La remise dépasse le plafond administrateur de {cap:g} %')
    ds=str(payload.get('dateStart') or ''); de=str(payload.get('dateEnd') or ds); ts=_hhmm(payload.get('timeStart'),'Heure de début'); te=_hhmm(payload.get('timeEnd'),'Heure de fin')
    d1=datetime.date.fromisoformat(ds); d2=datetime.date.fromisoformat(de); today=datetime.date.today()
    if d1<today: raise ValueError('La promotion doit commencer aujourd’hui ou plus tard')
    if d2<d1: raise ValueError('La date de fin doit être postérieure à la date de début')
    if d2>today+datetime.timedelta(days=int(policy['horizonDays'])): raise ValueError(f"La promotion dépasse l’horizon autorisé de {policy['horizonDays']} jours")
    if ts>=te: raise ValueError('L’heure de fin doit être postérieure à l’heure de début')
    if ts<policy['timeStart'] or te>policy['timeEnd']: raise ValueError(f"Plage autorisée : {policy['timeStart']}–{policy['timeEnd']}")
    raw_days=payload.get('weekdays'); weekdays=[]
    if isinstance(raw_days,list):
     for x in raw_days:
      try: v=int(x)
      except Exception: continue
      if 0<=v<=6 and v not in weekdays: weekdays.append(v)
    if not weekdays and d1==d2: weekdays=[(d1.weekday()+1)%7]
    if not weekdays: raise ValueError('Sélectionnez au moins un jour')
    allowed=set(policy['allowedWeekdays'])
    if any(v not in allowed for v in weekdays): raise ValueError('Un ou plusieurs jours ne sont pas autorisés par la politique d’incitation')
    name=f"CYBERCHECK · {policy['label']} · {meta['label']} · {final:.2f} EUR"
    result=mercure_admin.plan_promotion_slot(name=name,final_price=final,prestation_id=meta['id'],date_start=ds,date_end=de,time_start=ts,time_end=te,weekdays=[str(v) for v in weekdays])
    return self.send_json({'ok':True,'service':service_key,'basePrice':base,'finalPrice':round(final,2),'discountPercent':discount,'policy':policy,**result},201)
   except Exception as exc: return self.send_json({'ok':False,'error':'mercure_promotion_invalid'},400)
  if path=='/api/admin/mercure/rotate-secret':
   try: return self.send_json({'ok':True,**booking.rotate_secret()})
   except Exception as exc: return self.send_json({'ok':False,'error':'mercure_secret_rotation_failed'},400)
  if path.startswith('/api/admin/google/'):
   c=load_config(); site=c['seo'].get('searchConsoleProperty') or c['seo']['canonicalUrl']
   try:
    payload=self._read_json(allow_empty=True)
    if path=='/api/admin/google/credentials': return self.send_json({'ok':True,'credentials':gsc.save_credentials(payload)})
    if path=='/api/admin/google/test':
     check=gsc.property_status(site); return self.send_json({'ok':True,'property':site,**check})
    if path=='/api/admin/google/sitemap-submit':
     sitemap=payload.get('sitemapUrl') or canonical_origin(c['seo']['canonicalUrl'])+'/sitemap.xml'
     if not isinstance(sitemap,str) or not sitemap.startswith('https://'): raise ValueError('sitemapUrl must use https')
     return self.send_json({'ok':True,**gsc.submit_sitemap(site,sitemap)})
    if path=='/api/admin/google/inspect':
     target=payload.get('url') or c['seo']['canonicalUrl']
     if not isinstance(target,str) or not target.startswith('https://'): raise ValueError('inspection URL must use https')
     return self.send_json({'ok':True,'result':gsc.inspect_url(site,target)})
    return self.send_json({'error':'not_found'},404)
   except Exception: return self.send_json({'ok':False,'error':'google_search_console_request_failed'},400)
  if path!='/api/admin/config': return self.send_json({'error':'not_found'},404)
  try:
   current=load_config(); incoming=self._read_json(); validated=validate_config(incoming)
   enabling_public_indexing=not bool((current.get('seo') or {}).get('indexingEnabled')) and bool((validated.get('seo') or {}).get('indexingEnabled'))
   if enabling_public_indexing:
    report=production_readiness.status(validated,build_seo_health(validated))
    try: production_readiness.require_activation(report)
    except production_readiness.ProductionActivationBlocked as exc:
     return self.send_json({'ok':False,'error':'production_activation_blocked','blockingComponents':list(exc.blockers)},409)
   site_config_store.save(validated); return self.send_json({'ok':True,'config':validated})
  except Exception as exc: return self.send_json({'ok':False,'error':'config_update_invalid'},400)
 def do_DELETE(self):
  if not self._guard(): return
  parsed=urlparse(self.path); path=parsed.path
  if not self.authorized(): return self.require_auth()
  if not self._admin_origin_ok(): return self.send_json({'ok':False,'error':'origin_not_allowed'},403)
  if path=='/api/admin/integrations/google/oauth':
   try: return self.send_json({'ok':True,**integrations.revoke_oauth()})
   except Exception: return self.send_json({'ok':False,'error':'google_request_failed'},400)
  if path=='/api/admin/google/credentials':
   try: return self.send_json({'ok':True,'credentials':gsc.remove_credentials()})
   except Exception: return self.send_json({'ok':False,'error':'google_request_failed'},400)
  if path=='/api/admin/mercure/promo-slot':
   try:
    q=parse_qs(parsed.query); cid=(q.get('id') or [''])[0]
    return self.send_json(mercure_admin.remove_promotion_slot(cid))
   except Exception as exc: return self.send_json({'ok':False,'error':'mercure_promotion_delete_failed'},400)
  return self.send_json({'error':'not_found'},404)

def build_seo_health(c):
 seo=c.get('seo',{}); cr=seo.get('crawlers',{}); sd=seo.get('structuredData',{}); ac=c.get('analytics',{})
 checks=[]
 def add(key,label,status,detail): checks.append({'key':key,'label':label,'status':status,'detail':detail})
 indexing=bool(seo.get('indexingEnabled'))
 add('indexing','Indexation globale','pass' if indexing else 'warning','Autorisée' if indexing else 'Désactivée sur cette préversion')
 canonical=seo.get('canonicalUrl',''); add('canonical','URL canonique','pass' if canonical.startswith('https://') else 'fail',canonical or 'Absente')
 title=seo.get('title',''); add('title','Titre SEO','pass' if 25<=len(title)<=70 else 'warning',f'{len(title)} caractères')
 desc=seo.get('description',''); add('description','Méta-description','pass' if 90<=len(desc)<=200 else 'warning',f'{len(desc)} caractères')
 add('opengraph','Image Open Graph','pass' if seo.get('ogImage') else 'fail',seo.get('ogImage') or 'Absente')
 complete=all(sd.get(k) for k in ('businessName','streetAddress','postalCode','locality','country'))
 add('schema','Schema.org LocalBusiness','pass' if complete else 'fail','Complet' if complete else 'Champs locaux manquants')
 add('sitemap','Sitemap XML','pass',f'{len(sitemap_entries(c))} URL(s) publique(s) déclarée(s)')
 def crawler_status(enabled):
  if not indexing: return ('info','Préférence autorisée, mais indexation globale coupée') if enabled else ('info','Bloqué par préférence et par indexation globale')
  return ('pass','Autorisé') if enabled else ('warning','Bloqué')
 status_,detail=crawler_status(bool(cr.get('googlebot'))); add('googlebot','Googlebot',status_,detail)
 status_,detail=crawler_status(bool(cr.get('oaiSearchBot'))); add('oai-search','OAI-SearchBot',status_,detail)
 status_,detail=crawler_status(bool(cr.get('perplexityBot'))); add('perplexity','PerplexityBot',status_,detail)
 add('training-openai','GPTBot entraînement','pass' if not cr.get('gptBot') else 'warning','Bloqué' if not cr.get('gptBot') else 'Autorisé')
 add('training-anthropic','ClaudeBot entraînement','pass' if not cr.get('claudeBot') else 'warning','Bloqué' if not cr.get('claudeBot') else 'Autorisé')
 cred=gsc.credential_info(); add('gsc','Google Search Console','pass' if cred.get('configured') else 'warning',cred.get('clientEmail') or 'Identifiants non installés')
 add('google-verification','Vérification Google','pass' if seo.get('googleVerification') else 'warning','Configurée' if seo.get('googleVerification') else 'Code non renseigné')
 add('analytics','Mesure first-party','pass' if ac.get('enabled',True) else 'warning','Sans cookie / sans identifiant' if ac.get('enabled',True) else 'Désactivée')
 bs=booking.stats(30); has_flux=bool(bs.get('recent'))
 add('mercure','Mercure RDV confirmations','pass' if has_flux else 'warning',f"Flux HMAC reçu · {bs.get('confirmedBookings',0)} RDV confirmés sur 30 j" if has_flux else 'Bridge HMAC prêt · activation fournisseur encore requise')
 totals={k:sum(1 for x in checks if x['status']==k) for k in ('pass','info','warning','fail')}
 return {'checks':checks,'totals':totals,'generatedAt':datetime.datetime.now().astimezone().isoformat(timespec='seconds')}

def build_security_txt(c):
 origin=canonical_origin(c['seo']['canonicalUrl'])
 expires=(datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(days=365)).replace(microsecond=0).isoformat().replace('+00:00','Z')
 return f'Contact: mailto:contact@checkupauto.fr\nExpires: {expires}\nPreferred-Languages: fr, en\nCanonical: {origin}/.well-known/security.txt\n'

def build_robots(c):
 seo=c['seo']; canonical=seo['canonicalUrl']; lines=[]
 if not seo['indexingEnabled']:
  return 'User-agent: *\nDisallow: /\n\n# Preview environment: global indexing disabled\n'
 for key,ua in CRAWLERS.items():
  lines += [f'User-agent: {ua}', 'Allow: /' if seo['crawlers'].get(key,False) else 'Disallow: /']
  if seo['crawlers'].get(key,False): lines += ['Disallow: /admin/','Disallow: /api/admin/']
  lines.append('')
 lines += ['User-agent: *','Allow: /','Disallow: /admin/','Disallow: /api/admin/','',f'Sitemap: {canonical_origin(canonical)}/sitemap.xml','']
 return '\n'.join(lines)
def sitemap_entries(c):
 origin=canonical_origin(c['seo']['canonicalUrl'])
 rows=[
  {'loc':origin+'/', 'changefreq':'weekly', 'priority':'1.0'},
  {'loc':origin+'/zone-tarifs', 'changefreq':'weekly', 'priority':'0.8'},
 ]
 if app_download.status(c).get('ios',{}).get('channel')=='app-store':
  rows.append({'loc':origin+'/app', 'changefreq':'monthly', 'priority':'0.6'})
 return rows
def build_sitemap(c):
 last=c['updatedAt'][:10]
 rows=''.join(
  '<url><loc>{}</loc><lastmod>{}</lastmod><changefreq>{}</changefreq><priority>{}</priority></url>'.format(
   esc(item['loc']),last,item['changefreq'],item['priority'])
  for item in sitemap_entries(c)
 )
 return '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'+rows+'</urlset>\n'
def build_geo_pricing_page(c):
 services=mercure_public.public_services(); cov=geo_marketing.coverage(c,services); markets=cov.get('markets') or []
 canonical=canonical_origin(c['seo']['canonicalUrl'])+'/zone-tarifs'
 rows=[]
 for m in markets:
  prices=m.get('prices') or {}; pct=float(m.get('discountPercent') or 0)
  price80=prices.get('technical',80); price90=prices.get('fitted',90)
  rows.append(f"<tr><td>{esc(m.get('name',''))}</td><td>{float(m.get('distanceKm') or 0):.1f} km</td><td>{float(price80):.2f} €</td><td>{float(price90):.2f} €</td><td>{pct:g} %</td></tr>")
 body=''.join(rows)
 title='Tarifs contrôle technique dans un rayon de 50,01 km | Checkup Auto'
 desc='Consultez les tarifs et avantages Checkup Auto selon votre éloignement du centre des Mureaux, dans un rayon maximal de 50,01 km.'
 robots='index,follow' if c['seo'].get('indexingEnabled') else 'noindex,nofollow'
 doc=(f'<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
      f'<title>{esc(title)}</title><meta name="description" content="{esc(desc)}"><link rel="canonical" href="{esc(canonical)}">'
      f'<meta name="robots" content="{robots}"><style>body{{font-family:system-ui;margin:0;background:#f4f5f0;color:#17372b}}'
      'main{max-width:1080px;margin:auto;padding:48px 22px}a{color:#1f5845}h1{font-size:clamp(38px,6vw,72px);letter-spacing:-.05em}'
      'p{line-height:1.7;color:#52675d}table{width:100%;border-collapse:collapse;background:#fff;margin-top:30px}'
      'th,td{padding:12px;border-bottom:1px solid #dbe1d8;text-align:left}th{font-size:12px}.note{background:#fff;padding:18px;border:1px solid #dbe1d8;border-radius:12px}'
      f'</style></head><body><main><a href="/">← Checkup Auto</a><h1>Tarifs et zone de service</h1>'
      f'<p>Checkup Auto dessert les automobilistes situés dans un rayon maximal de <strong>{float(cov.get("radiusKm") or 50.01):.2f} km</strong> autour du centre des Mureaux. '
      'Les deux prestations réservables en ligne sont le contrôle technique à 80 € et le véhicule aménagé à 90 €. Des créneaux promotionnels peuvent ponctuellement réduire ces tarifs.</p>'
      f'<div class="note"><strong>{int(cov.get("communeCount") or 0)} communes</strong> sont référencées dans notre catalogue géographique. '
      'Les tarifs ci-dessous sont calculés à partir de la politique d’incitation active et restent soumis aux disponibilités réelles.</div>'
      '<table><thead><tr><th>Commune</th><th>Distance</th><th>Contrôle technique</th><th>Véhicule aménagé</th><th>Avantage distance</th></tr></thead>'
      f'<tbody>{body}</tbody></table></main></body></html>')
 return doc.encode()


def build_llms(c):
 seo=c['seo']; s=c['services']; offer=c['offer']; b=c['business']
 return f'''# {seo['siteName']}

> {seo['aiSummary']}

- Site officiel: {seo['canonicalUrl']}
- Téléphone: {b['phone']}
- Adresse: {b['address']}
- Réservation: {b['bookingUrl']}
- Offre principale: {offer['title'] if offer['enabled'] else 'Aucune offre active'}

## Prestations
- {s['technical']['label']}: {s['technical']['price']} EUR
- {s['fitted']['label']}: {s['fitted']['price']} EUR
- {s['pollution']['label']}: {s['pollution']['price']} EUR

## Référencement
Le contenu canonique et les règles d’exploration sont définis par robots.txt et les métadonnées HTML du site.
'''
def build_structured_data(c):
 seo=c['seo']; sd=seo['structuredData']; b=c['business']; s=c['services']
 offers=[{'@type':'Offer','name':v['label'],'price':v['price'],'priceCurrency':'EUR'} for v in s.values()]
 return {'@context':'https://schema.org','@type':'LocalBusiness','name':sd['businessName'],'url':seo['canonicalUrl'],'description':seo['description'],'telephone':b['phone'],'priceRange':sd['priceRange'],'address':{'@type':'PostalAddress','streetAddress':sd['streetAddress'],'postalCode':sd['postalCode'],'addressLocality':sd['locality'],'addressCountry':sd['country']},'makesOffer':offers}
def text(v,name,maxlen=300,allow_empty=False):
 if not isinstance(v,str): raise ValueError(f'{name} must be text')
 v=v.strip()
 if (not v and not allow_empty) or len(v)>maxlen: raise ValueError(f'{name} invalid length')
 return v
def price(v,name):
 if isinstance(v,bool) or not isinstance(v,(int,float)) or v<0 or v>1000: raise ValueError(f'{name} invalid')
 return round(float(v),2)
def https_url(v,name):
 v=text(v,name,500)
 if not v.startswith('https://'): raise ValueError(f'{name} must use https')
 return v
def validate_config(c):
 if not isinstance(c,dict): raise ValueError('invalid config')
 offer=c.get('offer',{}); business=c.get('business',{}); hero=c.get('hero',{}); services=c.get('services',{}); vehicles=c.get('vehicleCatalog',{}); seo=c.get('seo',{}); analytics_cfg=c.get('analytics',{}); inc=c.get('incentives',{})
 out={'version':5,'updatedAt':datetime.datetime.now().astimezone().isoformat(timespec='seconds')}
 out['offer']={'enabled':bool(offer.get('enabled',False)),'title':text(offer.get('title',''),'offer.title',80),'subtitle':text(offer.get('subtitle',''),'offer.subtitle',240),'heroLine':text(offer.get('heroLine',''),'offer.heroLine',180),'finalTitle':text(offer.get('finalTitle',''),'offer.finalTitle',180)}
 out['business']={'phone':text(business.get('phone',''),'business.phone',40),'address':text(business.get('address',''),'business.address',120),'bookingUrl':https_url(business.get('bookingUrl',''),'bookingUrl')}
 out['hero']={'kicker':text(hero.get('kicker',''),'hero.kicker',160)}
 out['services']={}
 for key in ('technical','fitted','pollution'):
  sv=services.get(key,{})
  out['services'][key]={'label':text(sv.get('label',''),f'services.{key}.label',80),'price':price(sv.get('price'),f'services.{key}.price')}
 defaults={'peugeot208':('Peugeot 208','technical'),'suv4x4':('4×4 / SUV','technical'),'utility':('Utilitaire','technical'),'ambulance':('Ambulance VASP','fitted'),'foodtruck':('Food-truck VASP','fitted')}
 out['vehicleCatalog']={}
 for key,(default_label,default_service) in defaults.items():
  row=vehicles.get(key,{}) if isinstance(vehicles,dict) else {}
  service_key=str(row.get('service') or default_service)
  if service_key not in ('technical','fitted'): raise ValueError(f'vehicleCatalog.{key}.service invalid')
  out['vehicleCatalog'][key]={'label':text(row.get('label') or default_label,f'vehicleCatalog.{key}.label',60),'service':service_key,'price':price(row.get('price',services.get(service_key,{}).get('price',0)),f'vehicleCatalog.{key}.price')}
 eligible=inc.get('eligibleServices',{}) if isinstance(inc.get('eligibleServices',{}),dict) else {}
 def pct(name,default=0):
  v=inc.get(name,default)
  if isinstance(v,bool) or not isinstance(v,(int,float)) or v<0 or v>90: raise ValueError(f'incentives.{name} invalid')
  return round(float(v),2)
 horizon=inc.get('horizonDays',30)
 if isinstance(horizon,bool) or not isinstance(horizon,(int,float)) or horizon<1 or horizon>180: raise ValueError('incentives.horizonDays invalid')
 days=inc.get('allowedWeekdays',[1,2,3,4,5,6])
 if not isinstance(days,list): raise ValueError('incentives.allowedWeekdays invalid')
 clean_days=[]
 for d in days:
  if isinstance(d,bool): raise ValueError('incentives.allowedWeekdays invalid')
  try: d=int(d)
  except Exception: raise ValueError('incentives.allowedWeekdays invalid')
  if d<0 or d>6: raise ValueError('incentives.allowedWeekdays invalid')
  if d not in clean_days: clean_days.append(d)
 if not clean_days: raise ValueError('Sélectionnez au moins un jour autorisé')
 ts=_hhmm(inc.get('timeStart','09:00'),'incentives.timeStart'); te=_hhmm(inc.get('timeEnd','19:00'),'incentives.timeEnd')
 if ts>=te: raise ValueError('La plage horaire d’incitation est invalide')
 out['incentives']={
  'enabled':bool(inc.get('enabled',True)),
  'label':text(inc.get('label','PRIX AVANTAGE'),'incentives.label',50),
  'eligibleServices':{'technical':bool(eligible.get('technical',True)),'fitted':bool(eligible.get('fitted',True))},
  'defaultDiscountPercent':pct('defaultDiscountPercent',0),
  'maxDiscountPercent':pct('maxDiscountPercent',0),
  'horizonDays':int(horizon),
  'allowedWeekdays':clean_days,
  'timeStart':ts,'timeEnd':te,
  'showOriginalPrice':bool(inc.get('showOriginalPrice',True)),
  'showDiscountPercent':bool(inc.get('showDiscountPercent',True))
 }
 cr=seo.get('crawlers',{}); sd=seo.get('structuredData',{})
 og=text(seo.get('ogImage',''),'seo.ogImage',500)
 if not (og.startswith('/') or og.startswith('https://')): raise ValueError('seo.ogImage must be an absolute https URL or /path')
 out['seo']={'indexingEnabled':bool(seo.get('indexingEnabled',False)),'siteName':text(seo.get('siteName',''),'seo.siteName',80),'title':text(seo.get('title',''),'seo.title',120),'description':text(seo.get('description',''),'seo.description',320),'canonicalUrl':https_url(seo.get('canonicalUrl',''),'seo.canonicalUrl'),'ogImage':og,'googleVerification':text(seo.get('googleVerification',''),'seo.googleVerification',300,True),'searchConsoleProperty':text(seo.get('searchConsoleProperty',''),'seo.searchConsoleProperty',500,True),'aiSummary':text(seo.get('aiSummary',''),'seo.aiSummary',800)}
 out['seo']['structuredData']={'businessName':text(sd.get('businessName',''),'seo.structuredData.businessName',100),'streetAddress':text(sd.get('streetAddress',''),'seo.structuredData.streetAddress',120),'postalCode':text(sd.get('postalCode',''),'seo.structuredData.postalCode',20),'locality':text(sd.get('locality',''),'seo.structuredData.locality',80),'country':text(sd.get('country',''),'seo.structuredData.country',2).upper(),'priceRange':text(sd.get('priceRange',''),'seo.structuredData.priceRange',20)}
 out['seo']['crawlers']={k:bool(cr.get(k,False)) for k in CRAWLERS}
 retention=analytics_cfg.get('retentionDays',180)
 if isinstance(retention,bool) or not isinstance(retention,(int,float)) or retention<7 or retention>730: raise ValueError('analytics.retentionDays invalid')
 out['analytics']={'enabled':bool(analytics_cfg.get('enabled',True)),'retentionDays':int(retention),'privacyMode':'cookieless'}
 return out
if __name__=='__main__':
 os.chdir(ROOT)
 analytics.init_db(); referrals.init_db(); notifications.init_db(); mobile_devices.init_db(); reminder_dispatch.init_db(); booking.init_db(); booking_test.init_db(); competitive.seed_public_baseline(); competitive.seed_review_baseline(); booking_test.start(300); reviews.start(); reminder_dispatch.start(); mobile_authoritative_sync.start(); mobile_reminder_dispatch.start(); security.init_db(); security_alerts.start(120); security_integrity.start(60); security_ai.start(300)
 print('CyberCheck admin/SEO server on http://127.0.0.1:8765',flush=True)
 ThreadingHTTPServer(('127.0.0.1',8765),Handler).serve_forever()
