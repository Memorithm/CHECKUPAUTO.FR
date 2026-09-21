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
 $('#complianceRightsRows').innerHTML=rights.length?rights.map(row=>{
  const executed=audit.filter(item=>item.requestId===row.id);
  const execText=executed.length?executed.map(item=>esc(item.adapter)+' / '+esc(item.action)).join('<br>'):'Aucun adaptateur exécuté';
  const actions=(row.status==='closed'||row.status==='rejected')?'—':
   '<button type="button" class="compact-action compliance-execute-right" data-id="'+esc(row.id)+'">Exécuter</button> '+
   '<button type="button" class="compact-action compliance-bind-right" data-id="'+esc(row.id)+'">Lier Mercure</button>';
  return '<tr><td>'+esc(row.type)+'</td><td>'+esc(row.subjectRefHash)+'</td><td>'+esc(row.status)+(row.overdue?' · EN RETARD':'')+'<br><small>'+execText+'</small></td><td>'+new Date(row.receivedAt).toLocaleDateString('fr-FR')+'</td><td>'+new Date(row.dueAt).toLocaleDateString('fr-FR')+'</td><td>'+actions+'</td></tr>';
 }).join(''):'<tr><td colspan="6">Aucune demande enregistrée.</td></tr>';
 const incidents=snapshot.incidents||[];
 $('#complianceIncidentRows').innerHTML=incidents.length?incidents.map(row=>'<tr><td>'+esc(row.riskLevel)+'</td><td>'+esc(row.status)+(row.notificationOverdue?' · DÉLAI DÉPASSÉ':'')+'</td><td>'+esc(row.summary)+'</td><td>'+new Date(row.detectedAt).toLocaleString('fr-FR')+'</td><td>'+(row.cnilDueAt?new Date(row.cnilDueAt).toLocaleString('fr-FR'):'—')+'</td><td>'+(row.status==='closed'?'—':'<button type="button" class="compact-action compliance-close-incident" data-id="'+esc(row.id)+'">Clôturer</button>')+'</td></tr>').join(''):'<tr><td colspan="6">Aucun incident enregistré.</td></tr>';
 const retention=snapshot.retention||{},retentionPolicies=retention.policies||[];
 $('#complianceRetentionState').textContent=retention.bound?'PRÊT':String(retention.blockerCount||0)+' BLOQUEUR(S)';
 $('#complianceRetentionState').className='gsc-status '+(retention.bound?'online':'warning');
 const configurable=retentionPolicies.filter(row=>row.mode===undefined);
 $('#complianceRetentionRule').innerHTML=configurable.map(row=>'<option value="'+esc(row.id)+'">'+esc(row.label)+'</option>').join('');
 $('#complianceRetentionRows').innerHTML=retentionPolicies.length?retentionPolicies.map(row=>{
  const days=row.activeDays===undefined||row.activeDays===null?'—':String(row.activeDays)+' j';
  const state=row.ready?'PRÊT':('BLOQUÉ · '+esc(row.blocker||'configuration requise'));
  return '<tr><td>'+esc(row.label||row.id)+'</td><td>'+esc(row.store||'—')+'</td><td>'+days+'</td><td>'+esc(row.trigger||'—')+'</td><td>'+state+'</td><td>'+esc(row.justification||row.source||'—')+'</td></tr>';
 }).join(''):'<tr><td colspan="6">Aucune politique disponible.</td></tr>';
 const retentionAudit=retention.audit||[];
 $('#complianceRetentionAuditRows').innerHTML=retentionAudit.length?retentionAudit.map(row=>'<tr><td>'+new Date(row.createdAt).toLocaleString('fr-FR')+'</td><td>'+esc(row.ruleId)+'</td><td>'+esc(row.mode)+'</td><td>'+esc(row.removedCount)+'</td><td>'+esc(row.cutoffAt||'—')+'</td><td>'+esc((row.evidenceHash||'').slice(0,16))+'</td></tr>').join(''):'<tr><td colspan="6">Aucune exécution.</td></tr>';
 fillRetentionPolicy();
 const docs=snapshot.documents||[];
 $('#complianceDocumentRows').innerHTML=Object.entries(types).map(([type,m])=>{
  const pub=docs.find(x=>x.type===type&&x.status==='published');
  return '<tr><td><a href="'+esc(m.slug)+'" target="_blank" rel="noopener">'+esc(m.label)+'</a></td><td>'+(pub?esc(pub.version):'—')+'</td><td>'+(pub?'PUBLIÉ':'MANQUANT')+'</td><td>'+(pub?esc(pub.contentHash.slice(0,16)):'—')+'</td></tr>';
 }).join('');
 document.querySelectorAll('.compliance-execute-right').forEach(b=>b.onclick=async()=>{
  try{
   const result=await api('/api/admin/compliance/request-execute',{
    id:b.dataset.id,
    adapter:$('#complianceRightAdapter').value,
    subjectRef:$('#complianceRightExecutionRef').value,
    purpose:$('#complianceRightPurpose').value
   });
   const data=result.execution?.data;
   if(data){
    const blob=new Blob([JSON.stringify(data,null,2)],{type:'application/json'});
    const url=URL.createObjectURL(blob),a=document.createElement('a');
    a.href=url;a.download='checkupauto-rgpd-'+b.dataset.id+'-'+($('#complianceRightAdapter').value||'export')+'.json';
    document.body.appendChild(a);a.click();a.remove();URL.revokeObjectURL(url);
   }
   $('#complianceRightExecutionRef').value='';
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
$('#complianceIncidentCreate')?.addEventListener('click',async()=>{
 try{await api('/api/admin/compliance/incident',{riskLevel:$('#complianceIncidentRisk').value,summary:$('#complianceIncidentSummary').value,notes:$('#complianceIncidentNotes').value});$('#complianceIncidentSummary').value='';$('#complianceIncidentNotes').value='';await load();setMessage('Incident enregistré.')}catch(e){setMessage(e.message,true)}
});
load().catch(e=>setMessage(e.message,true));
})();