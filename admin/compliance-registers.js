(()=>{
'use strict';
const $=selector=>document.querySelector(selector);
const text=value=>String(value??'');
const list=value=>Array.isArray(value)?value.map(item=>text(item)).filter(Boolean):[];

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

function reviewLabel(row){
 const due=text(row?.reviewDueAt);
 if(!due)return '—';
 return due+(row?.reviewOverdue?' · EN RETARD':'');
}

function statusLabel(value){
 const labels={
  controller:'Responsable',processor:'Sous-traitant',joint_controller:'Responsables conjoints',
  standard:'Standard',high:'Élevé',not_screened:'Non évaluée',not_required:'Non requise',
  required_pending:'Requise · en attente',in_progress:'En cours',approved:'Approuvée',
  signed:'Signé',pending:'En attente',inactive:'Inactif',active:'Actif',not_required_dpa:'Non requis'
 };
 return labels[text(value)]||text(value)||'—';
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
  const td=cell('Aucune activité de traitement enregistrée.');td.colSpan=8;tr.append(td);body.append(tr);return;
 }
 for(const row of activities){
  const tr=document.createElement('tr');
  tr.append(
   cell(row?.name),
   cell(statusLabel(row?.role)),
   listCell(row?.purposes),
   listCell(row?.legalBases),
   listCell(row?.systems),
   cell(row?.owner),
   cell(statusLabel(row?.riskLevel)+' · '+statusLabel(row?.dpiaStatus)),
   cell(reviewLabel(row))
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
  const td=cell('Aucun sous-traitant enregistré.');td.colSpan=7;tr.append(td);body.append(tr);return;
 }
 for(const row of processors){
  const transfer=row?.transferRequired
   ? ('Requis · '+(text(row?.transferMechanism)||'MÉCANISME MANQUANT'))
   : 'Non requis';
  const tr=document.createElement('tr');
  tr.append(
   cell(row?.name),
   cell(row?.service),
   cell(statusLabel(row?.dpaStatus)),
   cell(row?.hostingLocation),
   cell(transfer),
   listCell(row?.subprocessors),
   cell(reviewLabel(row))
  );
  body.append(tr);
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
 renderBlockers(summary.blockers);
 renderActivities(operations.processingActivities);
 renderProcessors(operations.processors);
}

async function load(){
 setMessage('Chargement des registres…');
 const response=await fetch('/api/admin/compliance',{cache:'no-store',headers:{Accept:'application/json'}});
 let payload={};
 try{payload=await response.json();}catch(_){payload={};}
 if(!response.ok||payload.ok===false)throw new Error(payload.error||('HTTP '+response.status));
 render(payload);
 setMessage('Registres opérationnels chargés depuis le snapshot de conformité.');
}

$('#operationsRefresh')?.addEventListener('click',()=>load().catch(error=>setMessage(error.message,true)));
load().catch(error=>setMessage(error.message,true));
})();
