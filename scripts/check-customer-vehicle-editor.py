#!/usr/bin/env python3
"""Browser-level vehicle editor regression; intercept every HTTP request."""
import argparse,asyncio,importlib.util,json,os,sys,tempfile
from pathlib import Path
from urllib.parse import urlsplit,parse_qs
from playwright.async_api import async_playwright
ROOT=Path(__file__).resolve().parents[1]
ORIGIN='https://responsive.checkupauto.test'
async def run(browser_name):
    with tempfile.TemporaryDirectory(prefix='vehicle-editor-') as tmp:
        for name in ('DATA','PRIVATE','SECURITY','INTEGRITY'):os.environ['CYBERCHECK_'+name+'_DIR']=tmp+'/'+name
        spec=importlib.util.spec_from_file_location('responsive',ROOT/'scripts/check-responsive-browser.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        pages=module.fixtures();requests=[];errors=[];slow_failure=False;outage=False
        refs={'ok':True,'brands':[{'id':'132','label':'PEUGEOT'},{'id':'145','label':'RENAULT'}],'energies':[{'id':'2','label':'Essence'}]}
        async def route(route):
            nonlocal slow_failure,outage
            request=route.request;url=urlsplit(request.url)
            if url.netloc!=urlsplit(ORIGIN).netloc:await route.abort();return
            if url.path=='/qa/dashboard':await route.fulfill(content_type='text/html',body=pages[url.path]);return
            if url.path=='/api/customer/reports':await route.fulfill(json={'ok':True,'reports':[]});return
            if url.path=='/api/customer/vehicle-references':
                brand=parse_qs(url.query).get('brandId',[''])[0]
                if outage:await route.fulfill(status=503,json={'ok':False});return
                if slow_failure and brand=='132':
                    await asyncio.sleep(0.3);await route.fulfill(status=503,json={'ok':False});return
                models=[{'id':'10','label':'208' if brand=='132' else 'Clio'},{'id':'99','label':'AUTRES MODELES'}]
                await route.fulfill(json={**refs,**({'models':models} if brand else {})});return
            if url.path=='/api/customer/vehicles' and request.method=='POST':
                payload=request.post_data_json;requests.append(payload)
                row={**payload,'vehicleId':'11111111-1111-4111-8111-111111111111','formulaNumberPresent':bool(payload.get('formulaNumber'))}
                row.pop('formulaNumber',None)
                await route.fulfill(status=201,json={'ok':True,'vehicles':[row]});return
            target=(ROOT/url.path.lstrip('/')).resolve()
            if url.path.startswith('/assets/') and target.is_relative_to(ROOT) and target.is_file():
                import mimetypes
                await route.fulfill(content_type=mimetypes.guess_type(target.name)[0] or 'application/octet-stream',body=target.read_bytes());return
            await route.fulfill(status=404,json={'ok':False})
        async with async_playwright() as playwright:
            browser=await getattr(playwright,browser_name).launch()
            context=await browser.new_context(viewport={'width':390,'height':844})
            await context.route('**/*',route);page=await context.new_page();page.set_default_timeout(5000)
            page.on('pageerror',lambda error:errors.append(str(error)))
            await page.goto(ORIGIN+'/qa/dashboard');await page.locator('#vehicleEditor > summary').click()
            await page.wait_for_function("document.querySelector('#vehicleBrand').options.length===3")
            await page.locator('#vehicleBrand').select_option(label='PEUGEOT')
            await page.wait_for_function("!document.querySelector('#vehicleModel').disabled")
            await page.locator('#vehicleModel').select_option(label='208');await page.locator('#vehicleEnergy').select_option(label='Essence')
            assert await page.locator('#vehicleModel option').count()==2, 'generic model leaked'
            await page.locator('#vehicleRegistration').fill('ab123cd');await page.locator('#vehicleFormulaNumber').fill('2020AB12345')
            assert await page.locator('#vehicleSave').is_disabled(), 'CT date must be mandatory'
            due=page.locator('#vehicleNextControlDate')
            assert await due.get_attribute('inputmode')=='numeric'
            await due.fill('31022027')
            assert await due.input_value()=='31/02/2027', 'slashes must be inserted automatically'
            assert await page.locator('#vehicleSave').is_disabled(), 'impossible CT date accepted'
            await due.fill('14102027')
            assert await due.input_value()=='14/10/2027', 'eight numeric digits must format as JJ/MM/AAAA'
            # Editing immediately after a slash deletes a digit rather than
            # trapping the user at an automatically reinserted separator.
            await due.evaluate("""field=>{
                field.focus();field.setSelectionRange(3,3);
                field.dispatchEvent(new InputEvent('beforeinput',{
                    bubbles:true,cancelable:true,inputType:'deleteContentBackward'
                }));
            }""")
            assert await due.input_value()=='11/02/027'
            assert await page.locator('#vehicleSave').is_disabled()
            await due.fill('14102027')
            assert await due.input_value()=='14/10/2027'
            await due.fill('14/10/2027')
            assert await due.input_value()=='14/10/2027', 'existing formatted dates must remain supported'
            await page.locator('.vehicle-optional > summary').click();await page.locator('#vehicleType').fill('VL')
            await page.locator('#vehicleSave').click();await page.wait_for_function("document.querySelector('#vehicleStatus').textContent==='Véhicule enregistré.'")
            assert len(requests)==1 and requests[0]['characteristics']['vehicleType']=='VL',requests
            assert requests[0]['characteristics']['model']=='208',requests
            assert requests[0]['nextControlDate']=='2027-10-14',requests
            await page.get_by_role('button',name='Modifier',exact=True).click()
            await page.wait_for_function("document.querySelector('#vehicleId').value!==''")
            assert await page.locator('#vehicleModel').input_value()=='208'
            assert await page.locator('#vehicleType').input_value()=='VL'
            assert await page.locator('#vehicleNextControlDate').input_value()=='14/10/2027'
            # An obsolete failing request must not destroy the later brand's model list.
            slow_failure=True
            await page.locator('#vehicleBrand').select_option(label='PEUGEOT')
            await page.locator('#vehicleBrand').select_option(label='RENAULT')
            await page.wait_for_function("[...document.querySelector('#vehicleModel').options].some(x=>x.text==='Clio')")
            await asyncio.sleep(0.4)
            assert not await page.locator('#vehicleModel').is_disabled()
            await page.locator('#vehicleModel').select_option(label='Clio')
            # FNI uses the issue date, not a retained formula number.
            await page.locator('#vehicleRegistrationSystem').select_option('fni')
            await page.locator('#vehicleRegistration').fill('1234ab78');await page.locator('#vehicleCardIssueDate').fill('2005-01-01')
            await page.locator('#vehicleNextControlDate').fill('29022028')
            assert await page.locator('#vehicleNextControlDate').input_value()=='29/02/2028'
            await page.locator('#vehicleSave').click();await page.wait_for_function("document.querySelector('#vehicleStatus').textContent==='Véhicule enregistré.'")
            assert len(requests)==2 and requests[1]['formulaNumber']=='' and requests[1]['cardIssueDate']=='2005-01-01',requests
            assert requests[1]['nextControlDate']=='2028-02-29',requests
            outage=True;await page.locator('#vehicleReferencesRetry').click()
            await page.wait_for_function("document.querySelector('#vehicleBrand').disabled")
            assert await page.locator('#vehicleSave').is_disabled()
            await page.locator('#vehicleForm').evaluate("e=>e.dispatchEvent(new Event('submit',{cancelable:true,bubbles:true}))")
            assert len(requests)==2
            outage=False;slow_failure=False;await page.locator('#vehicleReferencesRetry').click()
            await page.wait_for_function("!document.querySelector('#vehicleBrand').disabled")
            assert not errors,errors
            await browser.close()
        print(json.dumps({'browser':browser_name,'saved_siv_and_fni':True,'edit_restored':True,'stale_response_ignored':True,'outage_blocks_save':True,'retry_recovers':True,'javascript_errors':len(errors)}))
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--browser',choices=['chromium','webkit'],required=True)
    asyncio.run(run(parser.parse_args().browser))
