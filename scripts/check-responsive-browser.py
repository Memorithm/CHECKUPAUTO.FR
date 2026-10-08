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
from urllib.parse import urlsplit, parse_qs

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


async def check_document_guide(page, guide_id: str, photo: str, width: int) -> None:
    """Exercise native disclosure, real image loading and expanded mobile layout."""
    guide = page.locator('#'+guide_id)
    assert await guide.is_visible(), guide_id
    summary = guide.locator('summary')
    box = await summary.bounding_box()
    assert box['height'] >= 44, box
    await summary.focus()
    await page.keyboard.press('Enter')
    assert await guide.get_attribute('open') is not None, guide_id
    image = guide.locator('img')
    await image.scroll_into_view_if_needed()
    assert await image.get_attribute('src') == f'/assets/guides/carte-grise-{photo}-photo.webp'
    await page.wait_for_function(
        "id => {const image=document.querySelector('#'+id+' img'); return image.complete && image.naturalWidth>0;}",
        arg=guide_id,
    )
    assert await image.is_visible()
    data = await page.evaluate(GEOMETRY)
    assert data['scrollWidth'] <= width+1, data
    assert not data['outside'], data['outside']


async def run(args) -> int:
    from playwright.async_api import async_playwright
    out=Path(args.output).resolve();out.mkdir(parents=True,exist_ok=True)
    results=[]; failures=[]; logout_requests=[]; model_requests=[]
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
            if path == '/compte/deconnexion':
                logout_requests.append({'method':req.method,'fields':parse_qs(req.post_data or '',keep_blank_values=True)})
                # Playwright does not re-route a fulfilled redirect. Serve the login
                # fixture here; the real handler's 303 is covered by customer_logout_test.
                await route.fulfill(status=200,content_type='text/html; charset=utf-8',body=pages['/compte'],
                    headers={'Cache-Control':'no-store',
                    'Set-Cookie':'checkupauto_customer=; Path=/; Max-Age=0; Secure; HttpOnly; SameSite=Lax'});return
            if path == '/qa/dashboard-script-blocked':
                await route.fulfill(content_type='text/html; charset=utf-8',body=pages['/qa/dashboard'],
                    headers={'Content-Security-Policy':"script-src 'none'; style-src 'self' 'unsafe-inline'; form-action 'self'"});return
            if path == '/assets/3d/CyberCheckVehicle_Photo3D.glb':
                model_requests.append(req.url)
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
                    page_errors=[]; page.on('pageerror',lambda error:page_errors.append(str(error)))
                    for path in pages:
                        label=f'{args.browser} {width}x{height} {path}'
                        try:
                            page_errors.clear()
                            await page.goto(ORIGIN+path,wait_until='load')
                            if path=='/':
                                await page.locator('.booking-day').first.wait_for()
                                await page.get_by_role('button',name='Tout refuser',exact=True).click()
                                assert await page.locator('body.premium-home').count()==1
                                assert await page.locator('.lavis-caption,.lavis-topline,.hero .offer-seal,#lavisReplay,#lavisStill,.lavis-controls').count()==0
                                premium=await page.evaluate('''() => {
                                    const box=s=>{const r=document.querySelector(s).getBoundingClientRect();return {top:r.top,bottom:r.bottom,left:r.left,right:r.right,width:r.width,height:r.height}};
                                    const img=document.querySelector('#lavisArtwork');const css=getComputedStyle(img);
                                    return {intro:box('.hero-intro'),art:box('#lavisArtwork'),details:box('.hero-details'),font:getComputedStyle(document.querySelector('.hero h1')).fontFamily,fit:css.objectFit,animation:css.animationName,opacity:css.opacity,naturalWidth:img.naturalWidth,loaded:img.complete};
                                }''')
                                assert 'Georgia' in premium['font'],premium
                                assert premium['loaded'] and premium['naturalWidth']>0,premium
                                assert premium['fit']=='contain' and premium['animation']=='none' and premium['opacity']=='1',premium
                                assert premium['art']['left']>=0 and premium['art']['right']<=width+1,premium
                                if width<=980:
                                    assert premium['intro']['bottom']<=premium['art']['top']+1,premium
                                    assert premium['art']['bottom']<=premium['details']['top']+1,premium
                                if width in (375,390,1440):
                                    await page.evaluate('scrollTo(0,0)')
                                    await page.screenshot(path=str(out/f'{args.browser}-{width}-premium-home.png'))
                            data=await page.evaluate(GEOMETRY)
                            assert data['scrollWidth']<=width+1, f'page width overflow: {data}'
                            assert abs(data['innerWidth']-width)<=1, f'mobile viewport expanded: {data}'
                            assert not data['outside'], f'elements outside viewport: {data["outside"]}'
                            if not path.startswith('/admin/'):
                                assert not page_errors, page_errors
                            if path == '/qa/dashboard':
                                nav=page.get_by_role('navigation',name='Actions de votre espace client')
                                controls=nav.locator('a,button')
                                assert await controls.count()==3
                                for control in await controls.all():
                                    box=await control.bounding_box()
                                    assert box['height']>=46 and box['width']>=44,box
                                    assert box['x']>=0 and box['x']+box['width']<=width+1,box
                                    await control.focus()
                                    outline=await control.evaluate("e=>getComputedStyle(e).outlineStyle")
                                    assert outline != 'none',outline
                                await nav.get_by_role('link',name='Mes véhicules',exact=True).click()
                                assert urlsplit(page.url).fragment == 'mes-vehicules'
                                assert await nav.get_by_role('link',name='Nous contacter',exact=True).get_attribute('href') == '/contact'
                                if width in (375,1440):
                                    await page.evaluate('scrollTo(0,0)')
                                    await page.screenshot(path=str(out/f'{args.browser}-{width}-dashboard-actions.png'),full_page=True)
                            if path in ('/compte/reserver', '/qa/dashboard'):
                                booking = path == '/compte/reserver'
                                system_id = 'registrationSystem' if booking else 'vehicleRegistrationSystem'
                                formula_id = 'formulaField' if booking else 'vehicleFormulaLabel'
                                date_id = 'issueDateField' if booking else 'vehicleCardIssueLabel'
                                if not booking:
                                    await page.locator('#vehicleEditor > summary').click()
                                assert await page.locator('#'+formula_id).is_visible()
                                assert not await page.locator('#'+date_id).is_visible()
                                assert not await page.locator('#vehicleDateGuide').is_visible()
                                await check_document_guide(page, 'vehicleFormulaGuide', 'formule', width)
                                if booking and width in (375,430):
                                    await page.screenshot(path=str(out/f'{args.browser}-{width}-booking-formule.png'), full_page=True)
                                await page.locator('#'+system_id).select_option('fni')
                                assert not await page.locator('#'+formula_id).is_visible()
                                assert await page.locator('#'+date_id).is_visible()
                                assert not await page.locator('#vehicleFormulaGuide').is_visible()
                                date_input = 'cardIssueDate' if booking else 'vehicleCardIssueDate'
                                assert await page.locator('#'+date_input).get_attribute('required') is not None
                                await check_document_guide(page, 'vehicleDateGuide', 'date', width)
                                if booking:
                                    if width in (375,430):
                                        await page.screenshot(path=str(out/f'{args.browser}-{width}-booking-date.png'), full_page=True)
                                    await page.locator('#vehicleChoice').select_option('11111111-1111-4111-8111-111111111111')
                                    assert not await page.locator('#newVehicleFields').is_visible()
                                    assert not await page.locator('#vehicleFormulaGuide').is_visible()
                                    assert not await page.locator('#vehicleDateGuide').is_visible()
                                    assert await page.locator('#cardIssueDate').get_attribute('required') is None
                                    await page.locator('#vehicleChoice').select_option('')
                                    assert await page.locator('#vehicleDateGuide').is_visible()
                                await page.locator('#'+system_id).select_option('siv')
                                assert await page.locator('#vehicleFormulaGuide').is_visible()
                                assert not await page.locator('#vehicleDateGuide').is_visible()
                            if path=='/':
                                # A previously hidden, tall reservation section cannot stay invisible.
                                assert await page.locator('#reservation').evaluate("e=>getComputedStyle(e).opacity")=='1'
                                stage=await page.locator('#inkCarStage').bounding_box()
                                assert stage['x']>=-1 and stage['x']+stage['width']<=width+1, stage
                                assert await page.locator('#lavisArtwork').is_visible()
                                assert not model_requests, model_requests
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
                # The approved image is now always static, without presentation controls.
                for motion in ('no-preference','reduce'):
                    context=await browser.new_context(viewport={'width':390,'height':844},
                        is_mobile=True,has_touch=True,reduced_motion=motion)
                    await context.route('**/*',route_request)
                    page=await context.new_page();page.set_default_timeout(10000)
                    await page.goto(ORIGIN,wait_until='load')
                    image=page.locator('#lavisArtwork')
                    await image.scroll_into_view_if_needed()
                    await page.get_by_role('button',name='Tout refuser',exact=True).click()
                    assert await image.evaluate('el=>el.complete && el.naturalWidth>0')
                    assert await page.locator('#lavisReplay,#lavisStill,#lavisStatus,.lavis-controls').count()==0
                    assert await page.locator('#vehicle3DCanvas').count()==0
                    for delay in (0,350):
                        await page.wait_for_timeout(delay)
                        complete=await image.evaluate('el=>({animation:getComputedStyle(el).animationName,opacity:parseFloat(getComputedStyle(el).opacity),clip:getComputedStyle(el).clipPath,source:el.currentSrc,width:el.naturalWidth,activeAnimations:el.getAnimations().length})')
                        assert complete['opacity']==1 and complete['animation']=='none' and complete['clip']=='none',complete
                        assert complete['activeAnimations']==0,complete
                        assert complete['width']>0,complete
                        assert any(complete['source'].endswith(f'-{w}.webp') for w in (765,1020,1530)),complete
                    assert not model_requests,model_requests
                    await page.screenshot(path=str(out/f'{args.browser}-390-lavis-static-{motion}.png'))
                    results.append({'case':args.browser+f' lavis static image without controls {motion}',
                        'passed':True,'complete':complete,'GLBRequests':0})
                    await context.close()
                # Normal-motion mode must not hide a planner taller than the viewport.
                context=await browser.new_context(viewport={'width':320,'height':568},is_mobile=True)
                await context.route('**/*',route_request); page=await context.new_page()
                await page.goto(ORIGIN); await page.locator('.booking-day').first.wait_for()
                assert await page.locator('#reservation').evaluate("e=>getComputedStyle(e).opacity")=='1'
                results.append({'case':args.browser+' normal-motion tall planner','passed':True})
                await context.close()
                # Deep-link users must see the entire artwork below the sticky header.
                for viewport_w,viewport_h in ((390,844),(1440,900)):
                    context=await browser.new_context(viewport={'width':viewport_w,'height':viewport_h},
                        is_mobile=viewport_w<600,reduced_motion='reduce')
                    await context.route('**/*',route_request)
                    page=await context.new_page()
                    await page.goto(ORIGIN+'/#lavisHero',wait_until='load')
                    geometry=await page.evaluate("() => ({top:document.querySelector('#lavisHero').getBoundingClientRect().top,header:document.querySelector('.header').getBoundingClientRect().bottom})")
                    assert geometry['top']>=geometry['header']+10,geometry
                    assert await page.locator('#lavisArtwork').is_visible()
                    results.append({'case':args.browser+f' {viewport_w} ink deep-link clears sticky header','passed':True,**geometry})
                    await context.close()
                # Native mobile menu still works when scripts cannot run.
                context=await browser.new_context(viewport={'width':375,'height':812},java_script_enabled=False)
                await context.route('**/*',route_request);page=await context.new_page()
                await page.goto(ORIGIN);await page.locator('.mobile-navigation summary').click()
                assert await page.locator('.mobile-nav-links a[href="/compte"]').is_visible()
                assert await page.locator('#lavisArtwork').is_visible()
                assert await page.locator('#vehicle3DCanvas').count()==0
                results.append({'case':args.browser+' native menu and ink art without JavaScript','passed':True})
                await context.close()
                # Native logout is independent of dashboard JavaScript and browser CSP.
                # This browser assertion verifies the submitted POST and fallback rendering;
                # customer_logout_test.py verifies the real 303, DB revocation and security.
                for width in (375,1440):
                    for mode in ('normal','no-js','script-blocked'):
                        context=await browser.new_context(viewport={'width':width,'height':900},
                            java_script_enabled=mode!='no-js')
                        await context.route('**/*',route_request)
                        await context.add_cookies([{'name':'checkupauto_customer','value':'synthetic',
                            'url':ORIGIN,'secure':True,'httpOnly':True,'sameSite':'Lax'}])
                        page=await context.new_page();page.set_default_timeout(8000)
                        path='/qa/dashboard-script-blocked' if mode=='script-blocked' else '/qa/dashboard'
                        await page.goto(ORIGIN+path)
                        before=len(logout_requests)
                        logout=page.get_by_role('button',name='Se déconnecter',exact=True)
                        if width==1440:
                            await logout.focus();await page.keyboard.press('Enter')
                        else:
                            await logout.click()
                        await page.wait_for_url(ORIGIN+'/compte/deconnexion')
                        assert len(logout_requests)==before+1,logout_requests
                        assert logout_requests[-1]=={'method':'POST','fields':{'csrf':['c'*64]}},logout_requests[-1]
                        assert not any(c['name']=='checkupauto_customer' for c in await context.cookies())
                        assert await page.get_by_role('button',name='Se connecter par e-mail',exact=True).is_visible()
                        results.append({'case':f'{args.browser} {width} native logout submission {mode}','passed':True})
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
