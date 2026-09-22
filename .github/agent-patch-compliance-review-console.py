from pathlib import Path

html_path = Path("admin/index.html")
html = html_path.read_text(encoding="utf-8")
html_anchor = '<div class="integration-box">\n<div class="panel-head compact"><div><h3>7 · Vente à distance : garde de conclusion</h3>'
html_replacement = '''<div class="integration-box">
<div class="panel-head compact"><div><h3>7 · Attestation des registres opérationnels</h3><p class="hint">L’attestation est liée à l’empreinte SHA-256 exacte affichée ici. Si les registres changent avant la confirmation, le serveur refuse l’opération.</p></div><span id="complianceRegisterReviewState" class="gsc-status warning">Diagnostic…</span></div>
<div class="promo-form-grid"><label>Empreinte actuelle revue<input id="complianceRegisterCurrentHash" readonly autocomplete="off"></label><label>Dernière empreinte attestée<input id="complianceRegisterAttestedHash" readonly autocomplete="off"></label></div>
<p class="hint">Dernière revue : <span id="complianceRegisterReviewedAt">—</span></p>
<div class="incentive-service-row"><label><input id="complianceRegisterReviewConfirm" type="checkbox">Je confirme avoir relu les registres correspondant exactement à l’empreinte affichée</label><button type="button" id="complianceRegisterAttest">Attester l’empreinte affichée</button></div>
</div>

<div class="integration-box">
<div class="panel-head compact"><div><h3>8 · Revues sécurité & vie privée des traitements à risque élevé</h3><p class="hint">Chaque revue est liée à l’empreinte exacte de l’activité. La preuve brute sert uniquement à calculer une empreinte côté serveur et n’est pas persistée dans le registre de revue.</p></div><span id="complianceProcessingReviewState" class="gsc-status warning">Diagnostic…</span></div>
<div class="table-scroll"><table class="funnel-table"><thead><tr><th>Activité</th><th>Sécurité</th><th>Vie privée</th><th>Empreinte actuelle</th><th>Empreinte revue</th><th>Revue</th></tr></thead><tbody id="complianceProcessingReviewRows"><tr><td colspan="6">Chargement…</td></tr></tbody></table></div>
<div class="promo-form-grid"><label>Activité sélectionnée<input id="complianceProcessingActivityId" readonly autocomplete="off"></label><label>Empreinte exacte à revoir<input id="complianceProcessingExpectedHash" readonly autocomplete="off"></label><label>Revue sécurité<select id="complianceProcessingSecurityStatus"><option value="in_progress">En cours</option><option value="approved">Approuvée</option><option value="changes_required">Corrections requises</option></select></label><label>Revue vie privée<select id="complianceProcessingPrivacyStatus"><option value="in_progress">En cours</option><option value="approved">Approuvée</option><option value="changes_required">Corrections requises</option></select></label></div>
<label>Preuve de revue à hacher<textarea id="complianceProcessingEvidence" rows="4" maxlength="1000000" autocomplete="off" placeholder="Référence interne, note de revue ou contenu probant. La valeur brute n’est pas renvoyée par l’API."></textarea></label>
<div class="button-row"><button type="button" id="complianceProcessingReviewSubmit">Enregistrer la revue liée à cette empreinte</button></div>
</div>

<div class="integration-box">
<div class="panel-head compact"><div><h3>9 · Vente à distance : garde de conclusion</h3>'''
if html.count(html_anchor) != 1:
    raise SystemExit("compliance HTML insertion anchor changed")
html = html.replace(html_anchor, html_replacement, 1)
html_path.write_text(html, encoding="utf-8")

js_path = Path("admin/compliance.js")
js = js_path.read_text(encoding="utf-8")
render_anchor = " fillRetentionPolicy();\n const docs=snapshot.documents||[];"
render_insert = """ fillRetentionPolicy();
 const registerReview=snapshot.operationalRegisterAttestation||{};
 const registerState=$('#complianceRegisterReviewState');
 if(registerState){
  const label=registerReview.current?'À JOUR':(registerReview.stale?'OBSOLÈTE':'À ATTESTER');
  registerState.textContent=label;registerState.className='gsc-status '+(registerReview.current?'online':'warning');
 }
 if($('#complianceRegisterCurrentHash'))$('#complianceRegisterCurrentHash').value=registerReview.currentRegisterHash||'';
 if($('#complianceRegisterAttestedHash'))$('#complianceRegisterAttestedHash').value=registerReview.attestedRegisterHash||'';
 if($('#complianceRegisterReviewedAt'))$('#complianceRegisterReviewedAt').textContent=registerReview.reviewedAt?new Date(registerReview.reviewedAt).toLocaleString('fr-FR'):'Jamais';
 if($('#complianceRegisterAttest'))$('#complianceRegisterAttest').disabled=!registerReview.currentRegisterHash||!!registerReview.current;
 const processingReview=snapshot.processingRiskReview||{};
 const processingState=$('#complianceProcessingReviewState');
 if(processingState){processingState.textContent=processingReview.ready?'PRÊT':String(processingReview.blockerCount||0)+' BLOQUEUR(S)';processingState.className='gsc-status '+(processingReview.ready?'online':'warning')}
 const processingRows=processingReview.activities||[];
 $('#complianceProcessingReviewRows').innerHTML=processingRows.length?processingRows.map(row=>{
  const reviewed=row.reviewedActivityHash||'—',reviewedAt=row.reviewedAt?new Date(row.reviewedAt).toLocaleString('fr-FR'):'Jamais';
  const state=row.stale?'OBSOLÈTE':reviewedAt;
  const sec=['in_progress','approved','changes_required'].includes(row.securityStatus)?row.securityStatus:'in_progress';
  const priv=['in_progress','approved','changes_required'].includes(row.privacyStatus)?row.privacyStatus:'in_progress';
  return '<tr><td>'+esc(row.name||row.activityId)+'</td><td>'+esc(row.securityStatus||'not_reviewed')+'</td><td>'+esc(row.privacyStatus||'not_reviewed')+'</td><td><code>'+esc(row.currentActivityHash||'')+'</code></td><td><code>'+esc(reviewed)+'</code></td><td>'+esc(state)+'<br><button type="button" class="compact-action compliance-select-processing-review" data-id="'+esc(row.activityId)+'" data-hash="'+esc(row.currentActivityHash||'')+'" data-security="'+esc(sec)+'" data-privacy="'+esc(priv)+'">Revoir</button></td></tr>';
 }).join(''):'<tr><td colspan="6">Aucun traitement actif à risque élevé.</td></tr>';
 document.querySelectorAll('.compliance-select-processing-review').forEach(button=>button.onclick=()=>{
  $('#complianceProcessingActivityId').value=button.dataset.id||'';
  $('#complianceProcessingExpectedHash').value=button.dataset.hash||'';
  $('#complianceProcessingSecurityStatus').value=button.dataset.security||'in_progress';
  $('#complianceProcessingPrivacyStatus').value=button.dataset.privacy||'in_progress';
  $('#complianceProcessingEvidence').value='';
  setMessage('Activité sélectionnée. Relisez le traitement correspondant à cette empreinte avant de soumettre la revue.');
 });
 const docs=snapshot.documents||[];"""
if js.count(render_anchor) != 1:
    raise SystemExit("compliance JS render anchor changed")
js = js.replace(render_anchor, render_insert, 1)

event_anchor = "$('#complianceIncidentCreate')?.addEventListener('click',async()=>{"
event_insert = """$('#complianceRegisterAttest')?.addEventListener('click',async()=>{
 if(!$('#complianceRegisterReviewConfirm').checked){setMessage('Confirmez explicitement la revue des registres avant l’attestation.',true);return}
 const expected=$('#complianceRegisterCurrentHash').value;
 if(!/^[0-9a-f]{64}$/.test(expected)){setMessage('Empreinte de registre invalide ou absente.',true);return}
 try{
  await api('/api/admin/compliance/register-attestation',{confirm:'CURRENT-REGISTERS-REVIEWED',expectedRegisterHash:$('#complianceRegisterCurrentHash').value});
  $('#complianceRegisterReviewConfirm').checked=false;await load();setMessage('Revue des registres attestée pour l’empreinte affichée.');
 }catch(e){setMessage(e.message,true)}
});
$('#complianceProcessingReviewSubmit')?.addEventListener('click',async()=>{
 const activityId=$('#complianceProcessingActivityId').value,expected=$('#complianceProcessingExpectedHash').value,evidence=$('#complianceProcessingEvidence').value;
 if(!activityId||!/^[0-9a-f]{64}$/.test(expected)){setMessage('Sélectionnez d’abord une activité et son empreinte courante.',true);return}
 if(!evidence.trim()){setMessage('Une preuve de revue est requise et sera hachée côté serveur.',true);return}
 try{
  await api('/api/admin/compliance/processing-review',{
   activityId:activityId,
   expectedActivityHash:$('#complianceProcessingExpectedHash').value,
   securityStatus:$('#complianceProcessingSecurityStatus').value,
   privacyStatus:$('#complianceProcessingPrivacyStatus').value,
   evidence:$('#complianceProcessingEvidence').value
  });
  $('#complianceProcessingEvidence').value='';await load();setMessage('Revue sécurité / vie privée enregistrée pour l’empreinte affichée.');
 }catch(e){setMessage(e.message,true)}
});
$('#complianceIncidentCreate')?.addEventListener('click',async()=>{"""
if js.count(event_anchor) != 1:
    raise SystemExit("compliance JS event anchor changed")
js = js.replace(event_anchor, event_insert, 1)
js_path.write_text(js, encoding="utf-8")
