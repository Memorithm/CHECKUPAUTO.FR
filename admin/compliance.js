(()=>{
const $=s=>document.querySelector(s);
let snapshot=null;
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function setMessage(message,error=false){const e=$('#complianceMessage');if(!e)return;e.textContent=message;e.classList.toggle('warning-text',!!error)}
async function api(path,body){
 const options={cache:'no-store',headers:{'Accept':'application/json'}};
 if(body!==undefined){options.method='POST';options.headers['Content-Type']='application/json';options.body=JSON.stringify(body)}
 const r=await fetch(path,options);let data={};try{data=await r.json()}catch(_){}
 if(!r.ok||data.ok===false)throw new Error(data.error||('HTTP '+r.status));
 return data
}
function retentionPolicyFor(id){return (snapshot?.retention?.policies||[]).find(row=>row.id===id)||null}
function retentionDurationLabel(row){
 if(row.activeHours!==undefined&&row.activeHours!==null)return String(row.activeHours)+' h';
 if(row.activeDays!==undefined&&row.activeDays!==null)return String(row.activeDays)+' j';
 if(row.mode==='event')return 'Événement';
 return '—'
}
function fillRetentionPolicy(){
 const id=$('#complianceRetentionRule')?.value,row=retentionPolicyFor(id);if(!row)return;
 $('#complianceRetentionDays').value=row.activeDays??'';
 $('#complianceRetentionJustification').value=row.justification||'';
 $('#complianceRetentionLegalReview').checked=!!row.legalReviewConfirmed;
 $('#complianceRetentionEnabled').checked=row.enabled!==false;
 const configurable=row.mode===undefined;
 $('#complianceRetentionDays').disabled=!configurable;
 $('#complianceRetentionJustification').disabled=!configurable;
 $('#complianceRetentionLegalReview').disabled=!configurable;
 $('#complianceRetentionEnabled').disabled=!configurable;
 $('#complianceRetentionSave').disabled=!configurable;
}
function docFor(type){
 const rows=(snapshot?.documents||[]).filter(x=>x.type===type);
 return rows.find(x=>x.status==='draft')||rows.find(x=>x.status==='published')||null
}
function fillDocument(type){
 const row=docFor(type),meta=snapshot?.documentTypes?.[type]||{};
 $('#complianceDocType').value=type;
 $('#complianceDocVersion').value=row?.version||'1.0';
 $('#complianceDocTitle').value=row?.title||meta.label||'';
 $('#complianceDocBody').value=row?.body||'';
 $('#complianceDocState').textContent=row?(row.status+' · '+(row.contentHash?.slice(0,12)||'—')):'Aucune version';
}
function rightsExecutionPayload(requestId){
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
function rightsPlanFor(requestId){
 return (snapshot?.rightsCompletion?.plans||[]).find(plan=>plan.requestId===requestId)||null
}
function rightsPlanItemText(item){
 const disposition=item.disposition==='not_applicable'?'non applicable':(item.disposition==='required'?'requis':'non planifié');
 const execution=!item.executed?'non exécuté':(item.executionComplete?'exécution complète':('exécution partielle'+(item.executionLimitation?' · '+item.executionLimitation:'')));
 const proof=item.disposition==='not_applicable'&&item.justificationHash?' · preuve '+item.justificationHash.slice(0,12):'';
 return esc(item.adapter)+' · '+esc(disposition)+' · '+esc(execution)+' · '+(item.satisfied?'satisfait':'à traiter')+esc(proof)
}
async function editRightsPlan(requestId){
 const plan=rightsPlanFor(requestId);
 if(!plan||(plan.items||[]).length===0){setMessage('Aucun adaptateur planifiable pour cette demande.',true);return}
 const entries=[];
 for(const item of plan.items){
  if(item.executed){
   entries.push({adapter:item.adapter,disposition:'required'});
   continue;
  }
  const current=item.disposition==='not_applicable'?'not_applicable':'required';
  const answer=window.prompt('Adaptateur '+item.adapter+'\nDisposition: required ou not_applicable',current);
  if(answer===null)return;
  const disposition=answer.trim();
  if(!['required','not_applicable'].includes(disposition)){setMessage('Disposition invalide: utilisez required ou not_applicable.',true);return}
  if(disposition==='not_applicable'){
   const justification=window.prompt('Justification obligatoire pour '+item.adapter+'. Elle sera hachée côté serveur et ne sera pas conservée en clair.','');
   if(justification===null)return;
   if(!justification.trim()){setMessage('Une justification est obligatoire pour un adaptateur non applicable.',true);return}
   entries.push({adapter:item.adapter,disposition:disposition,justification:justification.trim()});
  }else{
   entries.push({adapter:item.adapter,disposition:'required'});
  }
 }
 try{
  await api('/api/admin/compliance/request-plan',{id:requestId,entries:entries});
  await load();setMessage('Plan RGPD enregistré. La couverture globale reste bloquée tant que tous les stores ne sont pas couverts.');
 }catch(e){setMessage(e.message,true)}
}
function mercureCoverageStateLabel(state){
 if(state==='attested')return 'ATTESTÉ';
 if(state==='invalid')return 'INVALIDE';
 return 'NON CONFIGURÉ'
}
function renderMercureProviderCoverage(){
 const coverage=snapshot?.mercureProviderCoverage||{},boundary=coverage.boundary||{},vehicle=boundary.vehicleInventory||{};
 const anchor=$('#complianceMessage');if(!anchor)return;
 let box=$('#complianceMercureProviderCoverage');
 if(!box){box=document.createElement('div');box.id='complianceMercureProviderCoverage';box.className='integration-box';anchor.insertAdjacentElement('afterend',box)}
 const state=String(boundary.state||'unconfigured');
 const attested=state==='attested'&&boundary.attested===true;
 const historyStart=String(boundary.historyStart||'—');
 const futureDays=Number.isInteger(boundary.futureDays)&&boundary.futureDays>=0?String(boundary.futureDays)+' j':'—';
 const evidence=/^[0-9a-f]{64}$/.test(String(boundary.evidenceSha256||''))?String(boundary.evidenceSha256):'—';
 const reason=String(boundary.reason||'');
 const vehicleState=String(vehicle.state||'unconfigured');
 const vehicleAttested=vehicleState==='attested'&&boundary.attested===true;
 const vehicleEvidence=/^[0-9a-f]{64}$/.test(String(vehicle.evidenceSha256||''))?String(vehicle.evidenceSha256):'—';
 const vehicleReason=String(vehicle.reason||'');
 box.innerHTML='<div class="panel-head compact"><div><h3>Frontière DSAR Mercure</h3><p class="hint">Périmètre temporel attesté par une preuve fournisseur ou contractuelle externe. Seule son empreinte SHA-256 est affichée ; aucune preuve brute n’est conservée dans Git ni renvoyée par cette vue.</p></div><span class="gsc-status '+(attested?'online':'warning')+'">'+esc(mercureCoverageStateLabel(state))+'</span></div>'+ 
  '<div class="mercure-live-grid"><article><small>DÉBUT HISTORIQUE</small><strong>'+esc(historyStart)+'</strong></article><article><small>HORIZON FUTUR</small><strong>'+esc(futureDays)+'</strong></article><article><small>PREUVE TEMPORELLE SHA-256</small><strong><code>'+esc(evidence)+'</code></strong></article><article><small>INVENTAIRE VÉHICULES</small><strong>'+esc(mercureCoverageStateLabel(vehicleState))+'</strong><span>Preuve indépendante de la relation sujet→tous véhicules</span></article><article><small>PREUVE VÉHICULE SHA-256</small><strong><code>'+esc(vehicleEvidence)+'</code></strong></article></div>'+ 
  (reason?'<p class="warning-text">Diagnostic temporel : '+esc(reason)+'</p>':'')+
  (vehicleReason?'<p class="warning-text">Diagnostic véhicules : '+esc(vehicleReason)+'</p>':'')+
  '<p class="hint">Une attestation véhicule '+(vehicleAttested?'est présente':'reste requise')+'. Elle ne suffit pas, à elle seule, à déclarer une exécution complète : la frontière temporelle doit être appliquée, les lectures véhicule réussir et l’inventaire ne doit pas être tronqué.</p>';
}
function render(){
 if(!snapshot)return;
 const s=snapshot.summary||{}, settings=snapshot.settings||{};
 $('#complianceState').textContent=s.readyForPublicContracting?'PRÊT':'ACTION REQUISE';
 $('#complianceState').className='gsc-status '+(s.readyForPublicContracting?'online':'warning');
 $('#complianceIdentity').textContent=s.identityComplete?'Complet':((s.missingIdentityFields||[]).length+' manquant(s)');
 $('#complianceDocs').textContent=String(s.publishedDocuments||0)+'/'+String(s.requiredDocuments||0);
 $('#complianceCookies').textContent=s.cookieConsentRequired?'Consentement requis':'Aucun traceur non essentiel actif';
 $('#complianceRights').textContent=String(s.openRightsRequests||0);
 $('#complianceIncidents').textContent=String(s.openIncidents||0);
 $('#complianceCheckout').textContent=s.checkoutAcceptanceBound?'Relié':'À relier à Mercure';
 const withdrawal=snapshot.withdrawal||{};
 $('#complianceWithdrawal').textContent=s.withdrawalFunctionBound
  ? ('Opérationnelle · '+String(withdrawal.pendingReceipts||0)+' accusé(s) en attente')
  : 'À relier au contrat';
 renderMercureProviderCoverage();
 for(const key of ['controllerName','legalForm','capital','registeredAddress','registrationId','vatNumber','publicationDirector','contactEmail','privacyContact','mediatorName','mediatorUrl','mediatorAddress','hostName','hostAddress','hostPhone','approvalAuthority','approvalReference']){
  const el=$('#compliance_'+key);if(el)el.value=settings[key]||'';
 }
 const types=snapshot.documentTypes||{};
 $('#complianceDocType').innerHTML=Object.entries(types).map(([key,m])=>'<option value="'+esc(key)+'">'+esc(m.label)+'</option>').join('');
 const selected=$('#complianceDocType').dataset.current||Object.keys(types)[0]||'terms';
 $('#complianceDocType').dataset.current=selected;fillDocument(selected);
 const cookies=snapshot.cookies?.registry||[];
 $('#complianceCookieRows').innerHTML=cookies.length?cookies.map(row=>'<tr><td>'+esc(row.key)+'</td><td>'+esc(row.provider)+'</td><td>'+esc(row.category)+'</td><td>'+(row.essential?'Exempté/nécessaire':'Consentement')+'</td><td>'+(row.enabled?'Actif':'Inactif')+'</td><td>'+esc(row.durationDays)+' j</td></tr>').join(''):'<tr><td colspan="6">Aucun traceur enregistré. La mesure actuelle reste cookieless.</td></tr>';
 const rights=snapshot.rightsRequests||[],audit=snapshot.rightsExecutionAudit||[];
 updateRightsExecutor();
 $('#complianceRightsRows').innerHTML=rights.length?rights.map(row=>{
  const executed=audit.filter(item=>item.requestId===row.id);
  const execText=executed.length?executed.map(item=>esc(item.adapter)+' / '+esc(item.action)).join('<br>'):'Aucun adaptateur exécuté';
  const plan=rightsPlanFor(row.id),planItems=plan?.items||[];
  const planState=!plan?'Plan indisponible':(plan.knownScopeComplete?'Périmètre connu complet':(plan.planComplete?'Planifié · exécution incomplète':'À planifier'));
  const planText=planItems.length?planItems.map(rightsPlanItemText).join('<br>'):'Aucun adaptateur connu';
  const globalState=plan?.globalCoverageComplete?'Couverture globale complète':'Couverture globale incomplète';
  const actions=(row.status==='closed'||row.status==='rejected')?'—':
   '<button type="button" class="compact-action compliance-execute-right" data-id="'+esc(row.id)+'">Exécuter</button> '+
   '<button type="button" class="compact-action compliance-bind-right" data-id="'+esc(row.id)+'">Lier Mercure</button> '+
   '<button type="button" class="compact-action compliance-plan-right" data-id="'+esc(row.id)+'">Planifier</button>';
  return '<tr><td>'+esc(row.type)+'</td><td>'+esc(row.subjectRefHash)+'</td><td>'+esc(row.status)+(row.overdue?' · EN RETARD':'')+'<br><small>'+execText+'</small><br><strong>'+esc(planState)+'</strong><br><small>'+planText+'<br>'+esc(globalState)+'</small></td><td>'+new Date(row.receivedAt).toLocaleDateString('fr-FR')+'</td><td>'+new Date(row.dueAt).toLocaleDateString('fr-FR')+'</td><td>'+actions+'</td></tr>';
 }).join(''):'<tr><td colspan="6">Aucune demande enregistrée.</td></tr>';
 const incidents=snapshot.incidents||[];
 $('#complianceIncidentRows').innerHTML=incidents.length?incidents.map(row=>'<tr><td>'+esc(row.riskLevel)+'</td><td>'+esc(row.status)+(row.notificationOverdue?' · DÉLAI DÉPASSÉ':'')+'</td><td>'+esc(row.summary)+'</td><td>'+new Date(row.detectedAt).toLocaleString('fr-FR')+'</td><td>'+(row.cnilDueAt?new Date(row.cnilDueAt).toLocaleString('fr-FR'):'—')+'</td><td>'+(row.status==='closed'?'—':'<button type="button" class="compact-action compliance-close-incident" data-id="'+esc(row.id)+'">Clôturer</button>')+'</td></tr>').join(''):'<tr><td colspan="6">Aucun incident enregistré.</td></tr>';
 const retention=snapshot.retention||{},retentionPolicies=retention.policies||[];
 $('#complianceRetentionState').textContent=retention.bound?'PRÊT':String(retention.blockerCount||0)+' BLOQUEUR(S)';
 $('#complianceRetentionState').className='gsc-status '+(retention.bound?'online':'warning');
 const configurable=retentionPolicies.filter(row=>row.mode===undefined);
 $('#complianceRetentionRule').innerHTML=configurable.map(row=>'<option value="'+esc(row.id)+'">'+esc(row.label)+'</option>').join('');
 $('#complianceRetentionRows').innerHTML=retentionPolicies.length?retentionPolicies.map(row=>{
  const duration=retentionDurationLabel(row);
  const state=row.ready?'PRÊT':('BLOQUÉ · '+esc(row.blocker||'configuration requise'));
  return '<tr><td>'+esc(row.label||row.id)+'</td><td>'+esc(row.store||'—')+'</td><td>'+esc(duration)+'</td><td>'+esc(row.trigger||'—')+'</td><td>'+state+'</td><td>'+esc(row.justification||row.source||'—')+'</td></tr>';
 }).join(''):'<tr><td colspan="6">Aucune politique disponible.</td></tr>';
 const retentionAudit=retention.audit||[];
 $('#complianceRetentionAuditRows').innerHTML=retentionAudit.length?retentionAudit.map(row=>'<tr><td>'+new Date(row.createdAt).toLocaleString('fr-FR')+'</td><td>'+esc(row.ruleId)+'</td><td>'+esc(row.mode)+'</td><td>'+esc(row.removedCount)+'</td><td>'+esc(row.cutoffAt||'—')+'</td><td>'+esc((row.evidenceHash||'').slice(0,16))+'</td></tr>').join(''):'<tr><td colspan="6">Aucune exécution.</td></tr>';
 fillRetentionPolicy();
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
 const docs=snapshot.documents||[];
 $('#complianceDocumentRows').innerHTML=Object.entries(types).map(([type,m])=>{
  const pub=docs.find(x=>x.type===type&&x.status==='published');
  return '<tr><td><a href="'+esc(m.slug)+'" target="_blank" rel="noopener">'+esc(m.label)+'</a></td><td>'+(pub?esc(pub.version):'—')+'</td><td>'+(pub?'PUBLIÉ':'MANQUANT')+'</td><td>'+(pub?esc(pub.contentHash.slice(0,16)):'—')+'</td></tr>';
 }).join('');
 document.querySelectorAll('.compliance-execute-right').forEach(b=>b.onclick=async()=>{
  try{
   const result=await api('/api/admin/compliance/request-execute',rightsExecutionPayload(b.dataset.id));
   const data=result.execution?.data;
   if(data){
    const blob=new Blob([JSON.stringify(data,null,2)],{type:'application/json'});
    const url=URL.createObjectURL(blob),a=document.createElement('a');
    a.href=url;a.download='checkupauto-rgpd-'+b.dataset.id+'-'+($('#complianceRightAdapter').value||'export')+'.json';
    document.body.appendChild(a);a.click();a.remove();URL.revokeObjectURL(url);
   }
   $('#complianceRightExecutionRef').value='';$('#complianceRightAccountId').value='';$('#complianceRightDeadlineId').value='';$('#complianceRightDueDate').value='';
   await load();setMessage(data?'Export généré et téléchargé.':'Adaptateur RGPD exécuté.');
  }catch(e){setMessage(e.message,true)}
 });
 document.querySelectorAll('.compliance-bind-right').forEach(b=>b.onclick=async()=>{
  try{
   await api('/api/admin/compliance/request-bind-mercure',{
    id:b.dataset.id,
    installationId:$('#complianceRightBindingInstallation').value,
    mercureSubjectRef:$('#complianceRightBindingMercure').value
   });
   $('#complianceRightBindingInstallation').value='';$('#complianceRightBindingMercure').value='';
   await load();setMessage('Liaison mobile → Mercure prouvée et enregistrée sans référence brute.');
  }catch(e){setMessage(e.message,true)}
 });
 document.querySelectorAll('.compliance-plan-right').forEach(b=>b.onclick=()=>editRightsPlan(b.dataset.id));
 document.querySelectorAll('.compliance-close-incident').forEach(b=>b.onclick=async()=>{try{await api('/api/admin/compliance/incident-status',{id:b.dataset.id,status:'closed'});await load()}catch(e){setMessage(e.message,true)}});
}
async function load(){setMessage('Chargement de la conformité…');snapshot=await api('/api/admin/compliance');render();setMessage('Registre de conformité chargé.')}
$('#complianceRefresh')?.addEventListener('click',()=>load().catch(e=>setMessage(e.message,true)));
$('#complianceSaveIdentity')?.addEventListener('click',async()=>{
 const payload={};for(const key of ['controllerName','legalForm','capital','registeredAddress','registrationId','vatNumber','publicationDirector','contactEmail','privacyContact','mediatorName','mediatorUrl','mediatorAddress','hostName','hostAddress','hostPhone','approvalAuthority','approvalReference'])payload[key]=$('#compliance_'+key)?.value||'';
 try{await api('/api/admin/compliance/settings',payload);await load();setMessage('Identité légale enregistrée.')}catch(e){setMessage(e.message,true)}
});
$('#complianceDocType')?.addEventListener('change',e=>{e.target.dataset.current=e.target.value;fillDocument(e.target.value)});
async function saveDoc(action){
 try{
  const payload={type:$('#complianceDocType').value,version:$('#complianceDocVersion').value,title:$('#complianceDocTitle').value,body:$('#complianceDocBody').value,action:action};
  await api('/api/admin/compliance/document',payload);$('#complianceDocType').dataset.current=payload.type;await load();setMessage(action==='publish'?'Version publiée et figée.':'Brouillon enregistré.');
 }catch(e){setMessage(e.message,true)}
}
$('#complianceDocSave')?.addEventListener('click',()=>saveDoc('save'));
$('#complianceDocPublish')?.addEventListener('click',()=>saveDoc('publish'));
$('#complianceCookieSave')?.addEventListener('click',async()=>{
 try{
  await api('/api/admin/compliance/cookie',{
   key:$('#complianceCookieKey').value,provider:$('#complianceCookieProvider').value,purpose:$('#complianceCookiePurpose').value,
   category:$('#complianceCookieCategory').value,legalBasis:$('#complianceCookieBasis').value,durationDays:Number($('#complianceCookieDuration').value||0),
   storageKind:$('#complianceCookieStorage').value,essential:$('#complianceCookieEssential').checked,enabled:$('#complianceCookieEnabled').checked
  });await load();setMessage('Registre des traceurs mis à jour.');
 }catch(e){setMessage(e.message,true)}
});
$('#complianceRightAdapter')?.addEventListener('change',updateRightsExecutor);
$('#complianceRightCreate')?.addEventListener('click',async()=>{
 try{await api('/api/admin/compliance/request',{type:$('#complianceRightType').value,subjectRef:$('#complianceRightRef').value,notes:$('#complianceRightNotes').value});$('#complianceRightRef').value='';$('#complianceRightNotes').value='';await load();setMessage('Demande RGPD enregistrée avec échéance à un mois.')}catch(e){setMessage(e.message,true)}
});
$('#complianceRetentionRule')?.addEventListener('change',fillRetentionPolicy);
$('#complianceRetentionSave')?.addEventListener('click',async()=>{
 try{
  await api('/api/admin/compliance/retention-policy',{
   ruleId:$('#complianceRetentionRule').value,
   activeDays:Number($('#complianceRetentionDays').value||0),
   justification:$('#complianceRetentionJustification').value,
   legalReviewConfirmed:$('#complianceRetentionLegalReview').checked,
   enabled:$('#complianceRetentionEnabled').checked
  });
  await load();setMessage('Politique de conservation enregistrée.');
 }catch(e){setMessage(e.message,true)}
});
$('#complianceRetentionDryRun')?.addEventListener('click',async()=>{
 try{
  const result=await api('/api/admin/compliance/retention-run',{dryRun:true});
  await load();setMessage('Simulation terminée · '+String((result.retentionRun?.rules||[]).filter(x=>x.state==='ready').length)+' règle(s) évaluée(s).');
 }catch(e){setMessage(e.message,true)}
});
$('#complianceRetentionPurge')?.addEventListener('click',async()=>{
 if(!window.confirm('Exécuter maintenant les purges pour toutes les politiques prêtes ? Les suppressions sont irréversibles.'))return;
 try{
  const result=await api('/api/admin/compliance/retention-run',{dryRun:false,confirm:'PURGE'});
  const removed=(result.retentionRun?.rules||[]).reduce((sum,row)=>sum+Number(row.removedCount||0),0);
  await load();setMessage('Purge terminée · '+String(removed)+' enregistrement(s) supprimé(s).');
 }catch(e){setMessage(e.message,true)}
});
$('#complianceRegisterAttest')?.addEventListener('click',async()=>{
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
$('#complianceIncidentCreate')?.addEventListener('click',async()=>{
 try{await api('/api/admin/compliance/incident',{riskLevel:$('#complianceIncidentRisk').value,summary:$('#complianceIncidentSummary').value,notes:$('#complianceIncidentNotes').value});$('#complianceIncidentSummary').value='';$('#complianceIncidentNotes').value='';await load();setMessage('Incident enregistré.')}catch(e){setMessage(e.message,true)}
});
load().catch(e=>setMessage(e.message,true));
})();