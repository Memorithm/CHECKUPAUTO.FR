#!/usr/bin/env python3
"""Rendered responsive regression tests using isolated, synthetic data only.

No server or user session is contacted: every browser request is intercepted.
Run with an environment containing requirements.txt and playwright==1.55.0.
"""
from __future__ import annotations
import argparse
import asyncio
import datetime as dt
import json
import mimetypes
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
ORIGIN = 'https://responsive.checkupauto.test'
VIEWPORTS = [(320,568),(360,800),(375,812),(390,844),(430,932),
             (768,1024),(844,390),(1024,768),(1440,900),(1920,1080)]

GEOMETRY = '''() => {
 const width=document.documentElement.clientWidth;
 const rect=e=>{const r=e.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height,right:r.right,bottom:r.bottom}};
 const outside=[...document.querySelectorAll('body *')].filter(e=>{
   const r=e.getBoundingClientRect(), s=getComputedStyle(e);
   if(!r.width||!r.height||s.visibility==='hidden'||s.display==='none'||s.position==='absolute'&&r.width<=1) return false;
   if(r.left>=-1 && r.right<=width+1) return false;
   for(let p=e.parentElement;p&&p!==document.body;p=p.parentElement){
     if(['auto','scroll','hidden','clip'].includes(getComputedStyle(p).overflowX))return false;
   }
   return true;
 }).slice(0,12).map(e=>({tag:e.tagName,id:e.id,cls:String(e.className),...rect(e)}));
 return {width,innerWidth,scrollWidth:document.documentElement.scrollWidth,
   outside,viewport:document.querySelector('meta[name=viewport]')?.content};
}'''


def fixtures() -> dict[str,bytes]:
    sys.path.insert(0,str(ROOT))
    import customer_http
    import contact_request
    import app_download
    account = {
        'ok':True,'accountId':'00000000-0000-4000-8000-000000000001',
        'kind':'individual','displayName':'Client ' + 'Longnom'*10,
        'email':'client.'+'a'*55+'@example.test','companyName':'','siret':'',
        'phone':'0612345678','addressLine1':'12 rue de Test','addressLine2':'',
        'postalCode':'78130','city':'Les Mureaux','contactDetailsComplete':False,
        'vehicles':[{'vehicleId':'11111111-1111-4111-8111-111111111111','registrationSystem':'siv','registration':'AA-123-AA','formulaNumberPresent':True,'cardIssueDate':'','updatedAt':'2026-10-07T00:00:00+00:00'}],
        'providers':['google'], 'loyalty':{'referralCode':'TEST-1234',
        'balanceCents':500,'pendingCents':100,'earnedReferrals':2,'pendingReferrals':1}}
    with patch.object(customer_http.customer_accounts,'csrf_token',return_value='c'*64), \
         patch.object(customer_http.customer_oidc,'provider_status',return_value=[
             {'id':'google','label':'Google','configured':False},
             {'id':'apple','label':'Apple','configured':False}]), \
         patch.object(customer_http,'_google_review_url',return_value='https://g.page/r/test/review'):
        pages = {
            '/':(ROOT/'index.html').read_bytes(),
            '/compte':customer_http._login_page(),
            '/qa/dashboard':customer_http._dashboard_page('synthetic',account,'test-nonce'),
            '/compte/reserver':customer_http._passage_page(
                'synthetic',account,{'passageToken':'test'},'test-nonce',
                return_to='/go/booking?service=Contr%C3%B4le+technique&preferredDate=2026-10-15&preferredTime=10%3A30',
                vehicles=account['vehicles'],
            ),
            '/contact':contact_request.render_form(account,'c'*64),
            '/qa/suggestion':contact_request.render_form(account,'c'*64,'suggestion'),
            '/qa/confirmation':contact_request.render_confirmation({'requestId':'test-'+'1'*32}),
            '/app':app_download.landing_html({},'site','test-nonce'),
        }
    for relative in ('admin/index.html','admin/payments.html','admin/customers.html'):
        pages['/'+relative]=(ROOT/relative).read_bytes()
    return pages


async def run(args) -> int:
    from playwright.async_api import async_playwright
    out=Path(args.output).resolve();out.mkdir(parents=True,exist_ok=True)
    results=[]; failures=[]
    with tempfile.TemporaryDirectory(prefix='checkupauto-responsive-') as tmp:
        # Keep any incidental module configuration lookup outside real runtime directories.
        os.environ['CYBERCHECK_PRIVATE_DIR']=tmp+'/private'
        os.environ['CYBERCHECK_DATA_DIR']=tmp+'/data'
        os.environ['CYBERCHECK_SECURITY_DIR']=tmp+'/security'
        pages=fixtures()
        config=json.loads((ROOT/'data/site-config.json').read_text())
        config['analytics']={'enabled':False}
        today=dt.date.today()
        availability={'service':{'basePrice':80},'days':[
            {'available':True,'date':str(today+dt.timedelta(days=i)),
             'weekday':'Jeudi','day':str((today+dt.timedelta(days=i)).day),'month':'oct.',
             'slots':[{'time':f'{8+j//4:02d}:{15*(j%4):02d}','price':80,
                       'basePrice':80,'saving':0,'promotion':False,'discountPercent':0}
                      for j in range(48)]} for i in range(6)]}
        async def route_request(route):
            req=route.request;url=urlsplit(req.url);path=url.path
            if url.netloc!=urlsplit(ORIGIN).netloc:
                await route.abort();return
            if path in pages:
                await route.fulfill(content_type='text/html; charset=utf-8',body=pages[path]);return
            api={
                '/api/site-config':config,
                '/api/booking/services':{'businessDate':str(today),'horizonEnd':str(today+dt.timedelta(days=30))},
                '/api/booking/availability':availability,
                '/api/compliance/cookies':{'consentRequired':True},
                '/api/customer/reports':{'ok':True,'reports':[]},
                '/api/events':{'ok':True},
            }
            if path in api:
                await route.fulfill(json=api[path]);return
            candidate=(ROOT/path.lstrip('/')).resolve()
            allowed = path in ('/style.css','/app.js','/consent.js') or path.startswith('/assets/') or path.startswith('/admin/')
            if allowed and candidate.is_relative_to(ROOT) and candidate.is_file():
                mime=mimetypes.guess_type(candidate.name)[0] or 'application/octet-stream'
                await route.fulfill(content_type=mime,body=candidate.read_bytes());return
            await route.fulfill(status=404,json={'ok':False,'error':'synthetic_not_found'})
        async with async_playwright() as p:
            browser=await getattr(p,args.browser).launch(headless=True)
            try:
                for width,height in VIEWPORTS:
                    context=await browser.new_context(viewport={'width':width,'height':height},
                        is_mobile=width<=1024,has_touch=width<=1024,device_scale_factor=1,reduced_motion='reduce')
                    await context.route('**/*',route_request)
                    page=await context.new_page(); page.set_default_timeout(8000)
                    for path in pages:
                        label=f'{args.browser} {width}x{height} {path}'
                        try:
                            await page.goto(ORIGIN+path,wait_until='load')
                            if path=='/':
                                await page.locator('.booking-day').first.wait_for()
                                await page.get_by_role('button',name='Tout refuser',exact=True).click()
                            data=await page.evaluate(GEOMETRY)
                            assert data['scrollWidth']<=width+1, f'page width overflow: {data}'
                            assert abs(data['innerWidth']-width)<=1, f'mobile viewport expanded: {data}'
                            assert not data['outside'], f'elements outside viewport: {data["outside"]}'
                            if path=='/compte/reserver':
                                assert await page.locator('#formulaField').is_visible()
                                assert not await page.locator('#issueDateField').is_visible()
                                await page.locator('#registrationSystem').select_option('fni')
                                assert not await page.locator('#formulaField').is_visible()
                                assert await page.locator('#issueDateField').is_visible()
                                assert await page.locator('#cardIssueDate').get_attribute('required') is not None
                            if path=='/':
                                # A previously hidden, tall reservation section cannot stay invisible.
                                assert await page.locator('#reservation').evaluate("e=>getComputedStyle(e).opacity")=='1'
                                stage=await page.locator('#vehicle3DStage').bounding_box()
                                assert stage['x']>=0 and stage['x']+stage['width']<=width+1, stage
                                if width<=1100:
                                    menu=page.locator('.mobile-navigation')
                                    await menu.locator('summary').click()
                                    assert await menu.locator('a[href="/compte"]').is_visible()
                                    for link in await menu.locator('a').all():
                                        box=await link.bounding_box()
                                        assert box['height']>=44 and box['x']+box['width']<=width+1,box
                                    await menu.locator('a[href="#services"]').click()
                                    assert await menu.get_attribute('open') is None
                                    await menu.locator('summary').click()
                                    await page.keyboard.press('Escape')
                                    assert await menu.get_attribute('open') is None
                                # Booking order is explicit: control type, slot, then reserve.
                                selection=page.locator('#bookingSelection')
                                assert await selection.is_visible()
                                assert 'booking-awaiting' in (await selection.get_attribute('class') or '')
                                initial_cta=page.locator('#bookingContinue')
                                assert await initial_cta.get_attribute('aria-disabled')=='true'
                                fitted=page.locator('.control-type-option[data-service="fitted"]')
                                await fitted.click()
                                assert 'selected' in (await fitted.get_attribute('class') or '')
                                assert await page.locator('#service').input_value()=='fitted'
                                await page.locator('.booking-day').first.locator('.slot-button').first.click()
                                assert await selection.is_visible()
                                assert 'booking-awaiting' not in (await selection.get_attribute('class') or '')
                                assert await initial_cta.get_attribute('aria-disabled') is None
                                assert (await initial_cta.inner_text()).strip()=='Réserver →'
                                cta=await initial_cta.bounding_box()
                                assert cta['x']>=-1 and cta['x']+cta['width']<=width+1,cta
                                # Preferences must remain scrollable and reachable in landscape.
                                await page.locator('#cc-consent-manage').click()
                                panel=page.locator('#cc-consent-panel');box=await panel.bounding_box()
                                assert box['y']>=-1 and box['y']+box['height']<=height+1,box
                                await panel.get_by_role('button',name='Tout refuser',exact=True).click()
                                await page.evaluate('scrollTo(0,0)')
                                if width in (375,768,1440):
                                    await page.screenshot(path=str(out/f'{args.browser}-{width}-home.png'),full_page=True)
                            results.append({'case':label,**data,'passed':True})
                        except Exception as exc:
                            failures.append({'case':label,'error':str(exc)})
                            await page.screenshot(path=str(out/f'failed-{args.browser}-{width}-{path.strip("/").replace("/","-") or "home"}.png'),full_page=True)
                            print('FAIL',label,str(exc)[:600],flush=True)
                    await context.close()
                # Normal-motion mode must not hide a planner taller than the viewport.
                context=await browser.new_context(viewport={'width':320,'height':568},is_mobile=True)
                await context.route('**/*',route_request); page=await context.new_page()
                await page.goto(ORIGIN); await page.locator('.booking-day').first.wait_for()
                assert await page.locator('#reservation').evaluate("e=>getComputedStyle(e).opacity")=='1'
                results.append({'case':args.browser+' normal-motion tall planner','passed':True})
                await context.close()
                # Native mobile menu still works when scripts cannot run.
                context=await browser.new_context(viewport={'width':375,'height':812},java_script_enabled=False)
                await context.route('**/*',route_request);page=await context.new_page()
                await page.goto(ORIGIN);await page.locator('.mobile-navigation summary').click()
                assert await page.locator('.mobile-nav-links a[href="/compte"]').is_visible()
                results.append({'case':args.browser+' native menu without JavaScript','passed':True})
                await context.close()
            finally:
                await browser.close()
    report={'browser':args.browser,'syntheticDataOnly':True,'passed':len(results),
        'failed':len(failures),'failures':failures,'cases':results}
    (out/f'{args.browser}-responsive-results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'browser':args.browser,'passed':len(results),'failed':len(failures)},ensure_ascii=False),flush=True)
    return bool(failures)

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--browser',choices=('chromium','webkit'),default='chromium')
    parser.add_argument('--output',default='responsive-evidence')
    raise SystemExit(asyncio.run(run(parser.parse_args())))
