(()=>{
'use strict';
const $=selector=>document.querySelector(selector);
const text=value=>String(value??'');
const list=value=>Array.isArray(value)?value.map(item=>text(item)).filter(Boolean):[];
const lines=value=>text(value).split(/\r?\n/).map(item=>item.trim()).filter(Boolean);

function setMessage(message,error=false){
 const node=$('#operationsMessage');
 if(!node)return;
 node.textContent=message;
 node.classList.toggle('warning-text',Boolean(error));
}

function cell(value){
 const node=document.createElement('td');
 node.textContent=text(value)||'—';
 return node;
}

function listCell(values){
 const node=document.createElement('td');
 const items=list(values);
 node.textContent=items.length?items.join(' · '):'—';
 return node;
}

function actionCell(label,handler){
 const node=document.createElement('td');
 const button=document.createElement('button');
 button.type='button';button.className='secondary';button.textContent=label;
 button.addEventListener('click',handler);node.append(button);return node;
}

function value(selector,value){const node=$(selector);if(node)node.value=text(value);}
function values(selector,items){value(selector,list(items).join('\n'));}

function reviewLabel(row){
 const due=text(row?.reviewDueAt);
 if(!due)return '—';
 return due+(row?.reviewOverdue?' · EN RETARD':'');
}

function statusLabel(value){
 const labels={
  controller:'Responsable',processor:'Sous-traitant',joint_controller:'Responsables conjoints',
  standard:'Standard',high:'Élevé',not_screened:'Non évaluée',not_required:'Non requis',
  required_pending:'Requise · en attente',in_progress:'En cours',approved:'Approuvée',
  signed:'Signé',pending:'En attente',inactive:'Inactif',active:'Actif'
 };
 return labels[text(value)]||text(value)||'—';
}

function resetActivity(){
 $('#activityForm')?.reset();value('#activityId','');
 value('#activityRole','controller');value('#activityStatus','active');value('#activityRisk','standard');value('#activityDpia','not_screened');
}

function editActivity(row){
 value('#activityId',row?.id);value('#activityName',row?.name);value('#activityRole',row?.role);value('#activityStatus',row?.status);
 value('#activityOwner',row?.owner);value('#activityRisk',row?.riskLevel);value('#activityDpia',row?.dpiaStatus);value('#activityReviewDue',row?.reviewDueAt);value('#activityRetention',row?.retention);
 values('#activityPurposes',row?.purposes);values('#activityDataCategories',row?.dataCategories);values('#activityDataSubjects',row?.dataSubjects);values('#activityLegalBases',row?.legalBases);
 values('#activityRecipients',row?.recipients);values('#activityTransfers',row?.transfers);values('#activitySecurityControls',row?.securityControls);values('#activitySystems',row?.systems);
 $('#activityForm')?.scrollIntoView({behavior:'smooth',block:'start'});
}

function activityPayload(){
 const payload={
  name:text($('#activityName')?.value).trim(),role:text($('#activityRole')?.value),status:text($('#activityStatus')?.value),
  owner:text($('#activityOwner')?.value).trim(),riskLevel:text($('#activityRisk')?.value),dpiaStatus:text($('#activityDpia')?.value),reviewDueAt:text($('#activityReviewDue')?.value),retention:text($('#activityRetention')?.value).trim(),
  purposes:lines($('#activityPurposes')?.value),dataCategories:lines($('#activityDataCategories')?.value),dataSubjects:lines($('#activityDataSubjects')?.value),legalBases:lines($('#activityLegalBases')?.value),
  recipients:lines($('#activityRecipients')?.value),transfers:lines($('#activityTransfers')?.value),securityControls:lines($('#activitySecurityControls')?.value),systems:lines($('#activitySystems')?.value)
 };
 const id=text($('#activityId')?.value).trim();if(id)payload.id=id;return payload;
}

const DPA_EVIDENCE_MAX_BYTES=20*1024*1024;

async function hashDpaEvidenceFile(file){
 if(!file)return;
 if(!(globalThis.crypto&&globalThis.crypto.subtle)){throw new Error('SHA-256 navigateur indisponible');}
 if(!Number.isFinite(file.size)||file.size<1||file.size>DPA_EVIDENCE_MAX_BYTES){
  throw new Error('Document DPA invalide ou supérieur à 20 Mo');
 }
 const buffer=await file.arrayBuffer();
 const digest=await globalThis.crypto.subtle.digest('SHA-256',buffer);
 const hex=Array.from(new Uint8Array(digest),byte=>byte.toString(16).padStart(2,'0')).join('');
 if(!/^[0-9a-f]{64}$/.test(hex))throw new Error('Empreinte DPA invalide');
 value('#processorDpaEvidence',hex);
 setMessage('Empreinte SHA-256 calculée localement. Le document brut n’a pas été envoyé.');
}

function resetProcessor(){
 $('#processorForm')?.reset();value('#processorId','');value('#processorStatus','active');value('#processorDpa','pending');
}

function editProcessor(row){
 value('#processorId',row?.id);value('#processorName',row?.name);value('#processorService',row?.service);value('#processorStatus',row?.status);value('#processorDpa',row?.dpaStatus);
 value('#processorDpaEvidence',row?.dpaEvidenceSha256);value('#processorHosting',row?.hostingLocation);value('#processorReviewDue',row?.reviewDueAt);value('#processorTransferMechanism',row?.transferMechanism);values('#processorSubprocessors',row?.subprocessors);
 const checkbox=$('#processorTransferRequired');if(checkbox)checkbox.checked=row?.transferRequired===true;
 $('#processorForm')?.scrollIntoView({behavior:'smooth',block:'start'});
}

function processorPayload(){
 const payload={
  name:text($('#processorName')?.value).trim(),service:text($('#processorService')?.value).trim(),status:text($('#processorStatus')?.value),dpaStatus:text($('#processorDpa')?.value),
  dpaEvidenceSha256:text($('#processorDpaEvidence')?.value).trim().toLowerCase(),
  hostingLocation:text($('#processorHosting')?.value).trim(),reviewDueAt:text($('#processorReviewDue')?.value),transferRequired:$('#processorTransferRequired')?.checked===true,
  transferMechanism:text($('#processorTransferMechanism')?.value).trim(),subprocessors:lines($('#processorSubprocessors')?.value)
 };
 const id=text($('#processorId')?.value).trim();if(id)payload.id=id;return payload;
}

function renderBlockers(blockers){
 const body=$('#operationsBlockerRows');
 if(!body)return;
 body.replaceChildren();
 const rows=Array.isArray(blockers)?blockers:[];
 if(!rows.length){
  const tr=document.createElement('tr');
  const td=cell('Aucun bloqueur opérationnel.');td.colSpan=3;tr.append(td);body.append(tr);return;
 }
 for(const row of rows){
  const tr=document.createElement('tr');
  tr.append(cell(row?.type),cell(row?.name),cell(row?.id));
  body.append(tr);
 }
}

function renderActivities(rows){
 const body=$('#operationsActivityRows');
 if(!body)return;
 body.replaceChildren();
 const activities=Array.isArray(rows)?rows:[];
 if(!activities.length){
  const tr=document.createElement('tr');
  const td=cell('Aucune activité de traitement enregistrée.');td.colSpan=9;tr.append(td);body.append(tr);return;
 }
 for(const row of activities){
  const tr=document.createElement('tr');
  tr.append(
   cell(row?.name),cell(statusLabel(row?.role)),listCell(row?.purposes),listCell(row?.legalBases),listCell(row?.systems),cell(row?.owner),
   cell(statusLabel(row?.riskLevel)+' · '+statusLabel(row?.dpiaStatus)),cell(reviewLabel(row)),actionCell('Modifier',()=>editActivity(row))
  );
  body.append(tr);
 }
}

function renderProcessors(rows){
 const body=$('#operationsProcessorRows');
 if(!body)return;
 body.replaceChildren();
 const processors=Array.isArray(rows)?rows:[];
 if(!processors.length){
  const tr=document.createElement('tr');
  const td=cell('Aucun sous-traitant enregistré.');td.colSpan=9;tr.append(td);body.append(tr);return;
 }
 for(const row of processors){
  const transfer=row?.transferRequired?('Requis · '+(text(row?.transferMechanism)||'MÉCANISME MANQUANT')):'Non requis';
  const tr=document.createElement('tr');
  const dpaEvidence=text(row?.dpaEvidenceSha256);
  tr.append(cell(row?.name),cell(row?.service),cell(statusLabel(row?.dpaStatus)),cell(dpaEvidence?dpaEvidence.slice(0,16)+'…':'—'),cell(row?.hostingLocation),cell(transfer),listCell(row?.subprocessors),cell(reviewLabel(row)),actionCell('Modifier',()=>editProcessor(row)));
  body.append(tr);
 }
}

function renderBookingReconciliation(snapshot){
 const booking=snapshot?.bookingConversionReconciliation||{};
 const available=booking.available===true;
 const residual=Number.isInteger(booking.localResidualRows)?booking.localResidualRows:0;
 const withoutAttribution=Number.isInteger(booking.syntheticRowsWithoutAttribution)?booking.syntheticRowsWithoutAttribution:0;
 const state=$('#bookingSyntheticState');
 if(state){
  state.textContent=!available?'INDISPONIBLE':(residual===0?'AUCUN RÉSIDU LOCAL':'RÉSIDUS À TRAITER');
  state.className='gsc-status '+(available&&residual===0?'online':'warning');
 }
 if($('#bookingSyntheticResidual'))$('#bookingSyntheticResidual').textContent=available?String(residual):'—';
 if($('#bookingSyntheticWithoutAttribution'))$('#bookingSyntheticWithoutAttribution').textContent=available?String(withoutAttribution):'—';
 if($('#bookingProviderInference'))$('#bookingProviderInference').textContent=booking.providerIdInferenceUsed===true?'OUI':'NON';
 if($('#bookingProviderCoverage'))$('#bookingProviderCoverage').textContent=booking.providerCoverageProven===true?'PROUVÉE':'NON PROUVÉE';
 const diagnostic=$('#bookingSyntheticDiagnostic');
 if(diagnostic){
  diagnostic.textContent=!available
   ? 'Le store analytics n’est pas disponible ou n’est pas initialisé ; aucune conclusion de couverture ne peut être tirée.'
   : (residual===0
      ? 'Aucun résidu synthétique local n’est actuellement observé. Ce résultat ne prouve pas que Mercure a exposé tous les rendez-vous fournisseur.'
      : 'Des lignes synthétiques locales restent sans correspondance fournisseur prouvée. Le rapprochement reste strictement limité à la même clé d’attribution dérivée.');
 }
}

function render(snapshot){
 const operations=snapshot?.operations||{};
 const summary=operations.summary||{};
 const attestation=snapshot?.operationalRegisterAttestation||{};
 const ready=summary.operationalRegistersReady===true;
 const state=$('#operationsState');
 if(state){state.textContent=ready?'PRÊT':'ACTION REQUISE';state.className='gsc-status '+(ready?'online':'warning');}
 if($('#operationsActivities'))$('#operationsActivities').textContent=String(summary.activeActivityCount??0)+' / '+String(summary.activityCount??0);
 if($('#operationsProcessors'))$('#operationsProcessors').textContent=String(summary.activeProcessorCount??0)+' / '+String(summary.processorCount??0);
 if($('#operationsBlockers'))$('#operationsBlockers').textContent=String(summary.blockerCount??0);
 if($('#operationsAttestation'))$('#operationsAttestation').textContent=attestation.current?'À JOUR':(attestation.stale?'OBSOLÈTE':'À ATTESTER');
 const detail=$('#operationsAttestationDetail');
 if(detail){detail.textContent=attestation.current?'À JOUR':(attestation.stale?'OBSOLÈTE':'À ATTESTER');detail.className='gsc-status '+(attestation.current?'online':'warning');}
 value('#operationsRegisterHash',attestation.currentRegisterHash||'');
 if($('#operationsReviewedAt'))$('#operationsReviewedAt').textContent=attestation.reviewedAt?new Date(attestation.reviewedAt).toLocaleString('fr-FR'):'Jamais';
 if($('#operationsAttest'))$('#operationsAttest').disabled=!attestation.currentRegisterHash||attestation.current===true;
 renderBlockers(summary.blockers);renderActivities(operations.processingActivities);renderProcessors(operations.processors);renderBookingReconciliation(snapshot);
}

async function jsonResponse(response){
 let payload={};try{payload=await response.json();}catch(_){payload={};}
 if(!response.ok||payload.ok===false)throw new Error(payload.error||('HTTP '+response.status));
 return payload;
}

async function load(){
 setMessage('Chargement des registres…');
 const response=await fetch('/api/admin/compliance',{cache:'no-store',headers:{Accept:'application/json'}});
 const payload=await jsonResponse(response);render(payload);setMessage('Registres opérationnels chargés depuis le snapshot de conformité.');return payload;
}

async function postJson(path,payload){
 return jsonResponse(await fetch(path,{method:'POST',cache:'no-store',headers:{Accept:'application/json','Content-Type':'application/json'},body:JSON.stringify(payload)}));
}

$('#operationsRefresh')?.addEventListener('click',()=>load().catch(error=>setMessage(error.message,true)));
$('#operationsAttest')?.addEventListener('click',async()=>{
 const confirmed=$('#operationsReviewConfirm')?.checked===true;
 const expected=text($('#operationsRegisterHash')?.value).trim().toLowerCase();
 if(!confirmed){setMessage('Confirmez explicitement la revue des registres avant l’attestation.',true);return;}
 if(!/^[0-9a-f]{64}$/.test(expected)){setMessage('Empreinte de registre invalide ou absente.',true);return;}
 try{
  await postJson('/api/admin/compliance/register-attestation',{
   confirm:'CURRENT-REGISTERS-REVIEWED',
   expectedRegisterHash:expected
  });
  if($('#operationsReviewConfirm'))$('#operationsReviewConfirm').checked=false;
  await load();
  setMessage('Revue attestée pour l’empreinte exacte affichée.');
 }catch(error){setMessage(error.message,true);}
});
$('#activityReset')?.addEventListener('click',resetActivity);
$('#processorReset')?.addEventListener('click',resetProcessor);
$('#processorDpaEvidenceFile')?.addEventListener('change',async event=>{
 const file=event.target?.files?.[0];
 if(!file)return;
 try{await hashDpaEvidenceFile(file);}
 catch(error){value('#processorDpaEvidence','');setMessage(error.message||'Empreinte DPA impossible',true);}
 finally{event.target.value='';}
});
$('#activityForm')?.addEventListener('submit',async event=>{
 event.preventDefault();setMessage('Enregistrement de l’activité…');
 try{await postJson('/api/admin/compliance/processing-activity',activityPayload());resetActivity();await load();setMessage('Activité de traitement enregistrée. L’attestation doit être revue si son empreinte a changé.');}
 catch(error){setMessage(error.message,true);}
});
$('#processorForm')?.addEventListener('submit',async event=>{
 event.preventDefault();setMessage('Enregistrement du sous-traitant…');
 try{await postJson('/api/admin/compliance/processor',processorPayload());resetProcessor();await load();setMessage('Sous-traitant enregistré. L’attestation doit être revue si son empreinte a changé.');}
 catch(error){setMessage(error.message,true);}
});
load().catch(error=>setMessage(error.message,true));
})();