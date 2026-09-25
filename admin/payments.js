'use strict';
(() => {
 const $=s=>document.querySelector(s),route='/api/admin/payments/contract',activityRoute='/api/admin/payments/activity',refundRoute='/api/admin/payments/refunds';
 let snapshot=null,activitySnapshot=null,refundSnapshot=null,dirty=false,busy=false,refundAttempt=null;
 const message=(text,error=false)=>{$('#paymentsMessage').textContent=text;$('#paymentsMessage').classList.toggle('error',error);};
 const refundMessage=(text,error=false)=>{$('#refundMessage').textContent=text;$('#refundMessage').classList.toggle('error',error);};
 const setBusy=value=>{busy=value;$('#paymentsEditor').disabled=value||!snapshot;};
 const money=(cents,currency='EUR')=>(Number(cents)/100).toFixed(2)+' '+currency;
 function runtime(data){
  const root=$('#paymentsRuntime');root.replaceChildren();
  const state=data.runtime||{},refund=state.refundBasis||{};
  const rows=[
   ['Transport Payline sandbox',state.transportImplemented===true?'Prêt':'Indisponible'],
   ['Configuration API privée',state.configured===true&&state.configurationValid===true?'Présente':'À configurer'],
   ['Identifiants vérifiés chez Monext',state.credentialsVerified===true?'Oui':'Non'],
   ['Contrat Payline vérifié',state.contractBindingVerified===true?'Oui':'Non'],
   ['Devis issu d’une réservation Mercure confirmée',state.checkoutBasis?.authoritativeBookingBound===true?'Oui':'Non'],
   ['Prix issu du serveur',state.checkoutBasis?.serverAuthoritativePrice===true?'Oui':'Non'],
   ['CGV liées à la réservation',state.checkoutBasis?.contractAcceptanceBound===true?'Oui':'Non'],
   ['Checkout raccordé',state.checkoutBound===true?'Oui':'Non'],
   ['Callbacks raccordés',state.callbacksBound===true?'Oui':'Non'],
   ['Ledger remboursement sandbox',refund.operatorRefundLedger===true?'Raccordé':'Indisponible'],
   ['Relance remboursement ambiguë',refund.ambiguousRefundRetryBlocked===true?'Bloquée':'À sécuriser'],
   ['Paiements réels',state.livePaymentsEnabled===true?'ACTIFS':'Désactivés'],
  ];
  for(const [label,value] of rows){
   const row=document.createElement('p'),strong=document.createElement('strong');
   strong.textContent=label+' : ';row.append(strong,document.createTextNode(value));root.append(row);
  }
 }
 function show(data){
  snapshot=data;dirty=false;runtime(data);const root=$('#paymentsFields');root.replaceChildren();
  const groups=new Map();
  for(const spec of data.schema){
   if(!groups.has(spec.group)){
    const section=document.createElement('section');section.className='panel';
    const title=document.createElement('h2');title.textContent=spec.group;
    const grid=document.createElement('div');grid.className='payment-fields';section.append(title,grid);root.append(section);groups.set(spec.group,grid);
   }
   const label=document.createElement('label');label.textContent=spec.label;
   const input=document.createElement('input');input.type='text';input.name=spec.name;input.maxLength=spec.maxLength;
   input.value=data.fields[spec.name]||'';input.autocomplete='off';input.spellcheck=false;
   if(!['brand','platform','allowedErt','currency'].includes(spec.name))input.inputMode='numeric';
   input.addEventListener('input',()=>{dirty=true;});label.append(input);groups.get(spec.group).append(label);
  }
  const body=$('#paymentsAudit');body.replaceChildren();
  for(const row of data.audit){const tr=document.createElement('tr');
   for(const value of [String(row.revision),row.at,row.source==='manual'?'Modification manuelle':'Import des champs vides',row.changedFields.map(k=>data.schema.find(s=>s.name===k)?.label||k).join(', ')]){
    const td=document.createElement('td');td.textContent=value;tr.append(td);
   }body.append(tr);
  }
  if(!data.audit.length){const tr=document.createElement('tr'),td=document.createElement('td');td.colSpan=4;td.textContent='Aucune modification enregistrée.';tr.append(td);body.append(tr);}
 }
 async function request(payload){
  const options={cache:'no-store',credentials:'same-origin',headers:{}};
  if(payload){options.method='POST';options.headers={'Content-Type':'application/json','X-CheckupAuto-Payments-CSRF':snapshot.csrfToken};options.body=JSON.stringify(payload);}
  const response=await fetch(route,options);
  if(response.status===401||response.status===403){$('#paymentsAuth').hidden=false;throw new Error('Connexion, double authentification ou session à renouveler. Revenir au back-office puis recharger cette page.');}
  if(response.status===409)throw new Error('La fiche a été modifiée ailleurs. Vos saisies sont conservées à l’écran. Rechargez la fiche avant de réappliquer vos modifications.');
  if(!response.ok)throw new Error(response.status===400?'Fiche refusée : vérifier les champs et leurs formats. Aucun changement enregistré.':'Configuration indisponible. Aucun succès d’enregistrement confirmé.');
  const data=await response.json();if(!data.ok||data.provider!=='payline_monext'||!Array.isArray(data.schema)||!data.runtime)throw new Error('Réponse de configuration invalide.');return data;
 }
 function syncRefundMax(){
  const option=$('#refundPayment').selectedOptions[0],input=$('#refundAmount');
  if(!option||!option.value){input.removeAttribute('max');return;}
  input.max=(Number(option.dataset.remaining||0)/100).toFixed(2);
  if(Number.isFinite(input.valueAsNumber)&&input.valueAsNumber>Number(input.max))input.value=input.max;
 }
 function renderRefundPaymentOptions(){
  const select=$('#refundPayment'),editor=$('#refundEditor'),current=select.value;
  select.replaceChildren();
  const holds=new Map(),blocked=new Set();
  for(const row of refundSnapshot?.refunds||[]){
   if(['completed','attempting','indeterminate'].includes(row.state))holds.set(row.paymentId,(holds.get(row.paymentId)||0)+Number(row.amountCents||0));
   if(['attempting','indeterminate'].includes(row.state))blocked.add(row.paymentId);
  }
  const captured=(activitySnapshot?.transactions||[]).filter(row=>row.provider==='payline'&&row.environment==='sandbox'&&row.state==='captured');
  let available=0;
  for(const row of captured){
   const remaining=Math.max(0,Number(row.amountCents)-Number(holds.get(row.paymentId)||0));
   const option=document.createElement('option');option.value=row.paymentId;option.dataset.remaining=String(remaining);
   option.textContent=row.paymentId.slice(0,12)+'… · '+money(row.amountCents,row.currency)+' · restant '+money(remaining,row.currency);
   option.disabled=remaining<1||blocked.has(row.paymentId);
   if(option.disabled&&blocked.has(row.paymentId))option.textContent+=' · RÉCONCILIATION REQUISE';
   if(!option.disabled)available++;
   select.append(option);
  }
  if(!captured.length){const option=document.createElement('option');option.value='';option.textContent='Aucun paiement Payline capturé';select.append(option);}
  else if(!available){const option=document.createElement('option');option.value='';option.textContent='Aucun montant actuellement remboursable';option.disabled=false;select.prepend(option);}
  if([...select.options].some(option=>option.value===current&&!option.disabled))select.value=current;
  else {const first=[...select.options].find(option=>option.value&&!option.disabled);select.value=first?.value||'';}
  editor.disabled=!activitySnapshot||!refundSnapshot||available===0;
  syncRefundMax();
 }
 async function loadActivity(){
  const response=await fetch(activityRoute,{cache:'no-store',credentials:'same-origin'});
  if(response.status===401||response.status===403)throw new Error('Authentification requise pour l’activité des paiements.');
  if(!response.ok)throw new Error('Activité des paiements indisponible.');
  const data=await response.json();
  if(!data.ok||!data.summary||!Array.isArray(data.transactions))throw new Error('Réponse activité paiements invalide.');
  activitySnapshot=data;
  const summary=data.summary,root=$('#paymentsActivitySummary');root.replaceChildren();
  const values=[['Intentions',summary.total],['Capturés',summary.captured],['En attente',summary.pending],['Refusés',summary.declined],['Annulés',summary.cancelled||0],['Erreurs techniques',summary.error||0],['Démarrages à réconcilier',summary.indeterminateStarts]];
  for(const [label,value] of values){const p=document.createElement('p'),strong=document.createElement('strong');strong.textContent=label+' : ';p.append(strong,document.createTextNode(String(value)));root.append(p);}
  const body=$('#paymentsActivity');body.replaceChildren();
  for(const row of data.transactions){
   const tr=document.createElement('tr');
   const stateLabels={created:'Créé',pending:'En attente',declined:'Refusé',cancelled:'Annulé',error:'Erreur technique',authorized:'Autorisé',captured:'Capturé'};
   const startLabels={ready:'Prêt',attempting:'Démarrage',indeterminate:'À réconcilier','':'—'};
   const values=[row.createdAt,row.paymentId.slice(0,12)+'…',money(row.amountCents,row.currency),stateLabels[row.state]||row.state,startLabels[row.startState]||row.startState];
   for(const value of values){const td=document.createElement('td');td.textContent=value;tr.append(td);}body.append(tr);
  }
  if(!data.transactions.length){const tr=document.createElement('tr'),td=document.createElement('td');td.colSpan=5;td.textContent='Aucune intention de paiement enregistrée.';tr.append(td);body.append(tr);}
  renderRefundPaymentOptions();
 }
 function renderRefunds(data){
  refundSnapshot=data;
  const summary=data.summary,root=$('#refundSummary');root.replaceChildren();
  const values=[['Demandes',summary.total],['Terminées',summary.completed],['En cours',summary.attempting],['À réconcilier',summary.indeterminate],['Refusées',summary.refused]];
  for(const [label,value] of values){const p=document.createElement('p'),strong=document.createElement('strong');strong.textContent=label+' : ';p.append(strong,document.createTextNode(String(value)));root.append(p);}
  const body=$('#refundActivity');body.replaceChildren();
  const stateLabels={attempting:'En cours',completed:'Remboursé',indeterminate:'À réconcilier',refused:'Refusé'};
  const reasonLabels={customer_request:'Demande client',booking_cancelled:'Réservation annulée',duplicate:'Paiement en double',operator_correction:'Correction opérateur'};
  for(const row of data.refunds){
   const tr=document.createElement('tr');
   const cells=[row.createdAt,row.paymentId.slice(0,12)+'…',money(row.amountCents,row.currency),reasonLabels[row.reason]||row.reason];
   for(const value of cells){const td=document.createElement('td');td.textContent=value;tr.append(td);}
   const state=document.createElement('td'),badge=document.createElement('span');badge.className='refund-state '+row.state;badge.textContent=stateLabels[row.state]||row.state;state.append(badge);tr.append(state);
   const proof=document.createElement('td');proof.textContent=row.evidenceHash?row.evidenceHash.slice(0,12)+'…':'—';tr.append(proof);body.append(tr);
  }
  if(!data.refunds.length){const tr=document.createElement('tr'),td=document.createElement('td');td.colSpan=6;td.textContent='Aucun remboursement sandbox enregistré.';tr.append(td);body.append(tr);}
  renderRefundPaymentOptions();
 }
 async function loadRefunds(){
  const response=await fetch(refundRoute,{cache:'no-store',credentials:'same-origin'});
  if(response.status===401||response.status===403)throw new Error('Authentification requise pour les remboursements.');
  if(!response.ok)throw new Error('État des remboursements indisponible.');
  const data=await response.json();
  if(!data.ok||!data.summary||!Array.isArray(data.refunds)||data.capability?.liveRefundsEnabled!==false||typeof data.csrfToken!=='string')throw new Error('Réponse remboursements invalide.');
  renderRefunds(data);
 }
 function randomRequestId(){
  const bytes=new Uint8Array(16);crypto.getRandomValues(bytes);return [...bytes].map(value=>value.toString(16).padStart(2,'0')).join('');
 }
 async function submitRefund(event){
  event.preventDefault();
  if(!refundSnapshot||$('#refundEditor').disabled)return;
  const paymentId=$('#refundPayment').value,amountValue=$('#refundAmount').valueAsNumber,reason=$('#refundReason').value;
  if(!paymentId||!Number.isFinite(amountValue)){refundMessage('Sélectionnez un paiement et un montant valide.',true);return;}
  const amountCents=Math.round(amountValue*100),maxCents=Math.round(Number($('#refundPayment').selectedOptions[0]?.dataset.remaining||0));
  if(amountCents<1||amountCents>maxCents){refundMessage('Le montant dépasse le solde remboursable vérifié.',true);return;}
  const fingerprint=[paymentId,amountCents,reason].join('|');
  if(!refundAttempt||refundAttempt.fingerprint!==fingerprint)refundAttempt={fingerprint,requestId:randomRequestId()};
  if(!confirm('Confirmer le remboursement Payline HOMOLOGATION de '+money(amountCents)+' ? Aucun remboursement de production ne sera déclenché.'))return;
  const button=$('#refundSubmit');button.disabled=true;refundMessage('Envoi de la demande de remboursement homologation…');
  try{
   const response=await fetch(refundRoute,{method:'POST',cache:'no-store',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CheckupAuto-Payments-CSRF':refundSnapshot.csrfToken},body:JSON.stringify({requestId:refundAttempt.requestId,paymentId,amountCents,reason})});
   const data=await response.json().catch(()=>({}));
   if(response.status===401||response.status===403)throw new Error('Connexion ou double authentification à renouveler.');
   if(!response.ok){
    if(data.error==='refund_reconciliation_required')throw new Error('Résultat fournisseur incertain : la tentative est verrouillée et doit être réconciliée avant toute nouvelle opération sur ce paiement.');
    if(data.error==='refund_amount_exceeds_remaining_capture')throw new Error('Le montant dépasse désormais le solde remboursable vérifié.');
    if(data.error==='payline_refund_refused'){refundAttempt=null;throw new Error('Payline a refusé ce remboursement homologation. Aucun remboursement n’a été confirmé.');}
    throw new Error('Remboursement non confirmé. La même clé de demande sera conservée pour éviter un doublon.');
   }
   if(!data.ok||data.environment!=='sandbox'||data.state!=='completed'||data.capability?.liveRefundsEnabled!==false)throw new Error('Réponse remboursement non vérifiable. La demande reste à contrôler.');
   refundAttempt=null;$('#refundAmount').value='';
   await loadActivity();await loadRefunds();
   refundMessage('Remboursement homologation confirmé et enregistré.');
  }catch(error){refundMessage(error.message||'Remboursement indisponible.',true);}
  finally{button.disabled=false;}
 }
 async function reload(){
  if(busy)return;if(dirty&&!confirm('Abandonner les modifications non enregistrées et recharger ?'))return;
  setBusy(true);try{show(await request());await loadActivity();await loadRefunds();$('#paymentsAuth').hidden=true;message('Fiche chargée — version '+snapshot.revision+'. Paiements réels désactivés.');}catch(e){message(e.message,true);}finally{setBusy(false);}
 }
 $('#paymentsForm').addEventListener('submit',async event=>{
  event.preventDefault();if(busy||!snapshot)return;
  const fields={};$('#paymentsFields').querySelectorAll('input[name]').forEach(input=>{fields[input.name]=input.value;});
  setBusy(true);try{show(await request({revision:snapshot.revision,mode:'manual',fields}));message('Modifications enregistrées — version '+snapshot.revision+'. Aucun paiement déclenché.');}catch(e){message(e.message,true);}finally{setBusy(false);}
 });
 $('#paymentsReload').addEventListener('click',reload);
 $('#paymentsImport').addEventListener('click',async()=>{
  if(busy||!snapshot)return;if(dirty){message('Enregistrez ou rechargez vos modifications avant un import.',true);return;}
  const file=$('#paymentsImportFile').files[0];if(!file){message('Sélectionnez le fichier de fiche bancaire.',true);return;}
  if(file.size>32768){message('Fichier trop volumineux : 32 Kio maximum.',true);return;}
  setBusy(true);try{
   let doc;try{doc=JSON.parse(await file.text());}catch{throw new Error('Le fichier doit être un document JSON valide.');}
   if(!doc||doc.schemaVersion!==1||doc.provider!=='payline_monext'||!doc.fields||Array.isArray(doc.fields)||Object.keys(doc).some(k=>!['schemaVersion','provider','fields'].includes(k)))throw new Error('Format de fiche non reconnu. Aucun import effectué.');
   const names=new Set(snapshot.schema.map(s=>s.name));if(Object.entries(doc.fields).some(([k,v])=>!names.has(k)||typeof v!=='string'))throw new Error('Champs inconnus ou identifiants non textuels. Aucune clé API ne doit être importée ici.');
   if(!confirm('Importer uniquement les champs actuellement vides, sans remplacer les valeurs enregistrées ?'))return;
   show(await request({revision:snapshot.revision,mode:'import_missing',fields:doc.fields}));$('#paymentsImportFile').value='';message('Import terminé — version '+snapshot.revision+'. Les valeurs déjà enregistrées ont été conservées.');
  }catch(e){message(e.message,true);}finally{setBusy(false);}
 });
 $('#refundPayment').addEventListener('change',syncRefundMax);
 $('#refundForm').addEventListener('submit',submitRefund);
 window.addEventListener('beforeunload',event=>{if(dirty){event.preventDefault();event.returnValue='';}});
 reload();
})();
