from pathlib import Path

html_path = Path("admin/index.html")
html = html_path.read_text(encoding="utf-8")
old_html = '''<div class="promo-form-grid">
<label>Adaptateur<select id="complianceRightAdapter"><option value="mobile_installation">Installation mobile</option><option value="mercure_customer_contact">Contact Mercure</option><option value="privacy_suppression">Suppression / opposition</option></select></label>
<label>Référence brute à revalider<input id="complianceRightExecutionRef" maxlength="240" autocomplete="off"></label>
<label>Finalité suppression<select id="complianceRightPurpose"><option value="direct_marketing">Prospection commerciale</option><option value="google_review">Demande d’avis Google</option><option value="">Automatique selon le droit</option></select></label>
</div>'''
new_html = '''<div class="promo-form-grid">
<label>Adaptateur<select id="complianceRightAdapter"><option value="mobile_installation">Installation mobile</option><option value="mercure_customer_contact">Contact Mercure</option><option value="compliance_contracts">Contrats / consentements</option><option value="privacy_suppression">Suppression / opposition</option><option value="mobile_deadline_rectification">Rectification échéance locale</option><option value="referral_wallet">Cagnotte de parrainage</option></select></label>
<label>Référence brute à revalider<input id="complianceRightExecutionRef" maxlength="240" autocomplete="off"><small id="complianceRightSubjectHint">Référence du sujet correspondant à la demande.</small></label>
<label id="complianceRightPurposeWrap" hidden>Finalité suppression<select id="complianceRightPurpose"><option value="direct_marketing">Prospection commerciale</option><option value="google_review">Demande d’avis Google</option><option value="">Automatique selon le droit</option></select></label>
<label id="complianceRightWalletWrap" hidden>Identifiant de cagnotte<input id="complianceRightAccountId" maxlength="36" autocomplete="off" placeholder="UUID de la cagnotte prouvée"></label>
<div id="complianceRightRectificationWrap" class="promo-form-grid" hidden><label>Échéance locale<input id="complianceRightDeadlineId" maxlength="36" autocomplete="off" placeholder="UUID de l’échéance créée sur l’appareil"></label><label>Nouvelle date<input id="complianceRightDueDate" type="date"></label></div>
</div>'''
if html.count(old_html) != 1:
    raise SystemExit("typed DSAR HTML anchor changed")
html = html.replace(old_html, new_html, 1)
html_path.write_text(html, encoding="utf-8")

js_path = Path("admin/compliance.js")
js = js_path.read_text(encoding="utf-8")
helper_anchor = '''function fillDocument(type){
 const row=docFor(type),meta=snapshot?.documentTypes?.[type]||{};
 $('#complianceDocType').value=type;
 $('#complianceDocVersion').value=row?.version||'1.0';
 $('#complianceDocTitle').value=row?.title||meta.label||'';
 $('#complianceDocBody').value=row?.body||'';
 $('#complianceDocState').textContent=row?(row.status+' · '+(row.contentHash?.slice(0,12)||'—')):'Aucune version';
}
'''
helper_insert = helper_anchor + '''function rightsExecutionPayload(requestId){
 const adapter=$('#complianceRightAdapter').value;
 const payload={id:requestId,subjectRef:$('#complianceRightExecutionRef').value,adapter:adapter};
 if(adapter==='privacy_suppression')payload.purpose=$('#complianceRightPurpose').value;
 if(adapter==='referral_wallet')payload.accountId=$('#complianceRightAccountId').value;
 if(adapter==='mobile_deadline_rectification')payload.correction={deadlineId:$('#complianceRightDeadlineId').value,dueDate:$('#complianceRightDueDate').value};
 return payload
}
function updateRightsExecutor(){
 const adapter=$('#complianceRightAdapter')?.value||'';
 const purpose=$('#complianceRightPurposeWrap'),wallet=$('#complianceRightWalletWrap'),rectification=$('#complianceRightRectificationWrap'),hint=$('#complianceRightSubjectHint');
 if(purpose)purpose.hidden=adapter!=='privacy_suppression';
 if(wallet)wallet.hidden=adapter!=='referral_wallet';
 if(rectification)rectification.hidden=adapter!=='mobile_deadline_rectification';
 if(hint)hint.textContent=(adapter==='referral_wallet'||adapter==='mobile_deadline_rectification')?'UUID de l’installation mobile ayant créé la demande.':'Référence du sujet correspondant à la demande.';
}
'''
if js.count(helper_anchor) != 1:
    raise SystemExit("typed DSAR JS helper anchor changed")
js = js.replace(helper_anchor, helper_insert, 1)

render_anchor = " const rights=snapshot.rightsRequests||[],audit=snapshot.rightsExecutionAudit||[];\n"
render_replace = render_anchor + " updateRightsExecutor();\n"
if js.count(render_anchor) != 1:
    raise SystemExit("typed DSAR JS render anchor changed")
js = js.replace(render_anchor, render_replace, 1)

old_handler = '''   const result=await api('/api/admin/compliance/request-execute',{
    id:b.dataset.id,
    adapter:$('#complianceRightAdapter').value,
    subjectRef:$('#complianceRightExecutionRef').value,
    purpose:$('#complianceRightPurpose').value
   });'''
new_handler = "   const result=await api('/api/admin/compliance/request-execute',rightsExecutionPayload(b.dataset.id));"
if js.count(old_handler) != 1:
    raise SystemExit("typed DSAR execution handler anchor changed")
js = js.replace(old_handler, new_handler, 1)

clear_anchor = "   $('#complianceRightExecutionRef').value='';\n   await load();setMessage(data?'Export généré et téléchargé.':'Adaptateur RGPD exécuté.');"
clear_replace = "   $('#complianceRightExecutionRef').value='';$('#complianceRightAccountId').value='';$('#complianceRightDeadlineId').value='';$('#complianceRightDueDate').value='';\n   await load();setMessage(data?'Export généré et téléchargé.':'Adaptateur RGPD exécuté.');"
if js.count(clear_anchor) != 1:
    raise SystemExit("typed DSAR clear anchor changed")
js = js.replace(clear_anchor, clear_replace, 1)

event_anchor = "$('#complianceRightCreate')?.addEventListener('click',async()=>{\n"
event_replace = "$('#complianceRightAdapter')?.addEventListener('change',updateRightsExecutor);\n" + event_anchor
if js.count(event_anchor) != 1:
    raise SystemExit("typed DSAR event anchor changed")
js = js.replace(event_anchor, event_replace, 1)
js_path.write_text(js, encoding="utf-8")
