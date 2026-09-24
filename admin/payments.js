'use strict';
(() => {
 const $=s=>document.querySelector(s), route='/api/admin/payments/contract', activityRoute='/api/admin/payments/activity';
 let snapshot=null, dirty=false, busy=false;
 const message=(text,error=false)=>{$('#paymentsMessage').textContent=text;$('#paymentsMessage').classList.toggle('error',error);};
 const setBusy=value=>{busy=value;$('#paymentsEditor').disabled=value||!snapshot;};
 function runtime(data){
  const root=$('#paymentsRuntime');root.replaceChildren();
  const state=data.runtime||{};
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
 async function loadActivity(){
  const response=await fetch(activityRoute,{cache:'no-store',credentials:'same-origin'});
  if(response.status===401||response.status===403)throw new Error('Authentification requise pour l’activité des paiements.');
  if(!response.ok)throw new Error('Activité des paiements indisponible.');
  const data=await response.json();
  if(!data.ok||!data.summary||!Array.isArray(data.transactions))throw new Error('Réponse activité paiements invalide.');
  const summary=data.summary,root=$('#paymentsActivitySummary');root.replaceChildren();
  const values=[['Intentions',summary.total],['Capturés',summary.captured],['En attente',summary.pending],['Refusés',summary.declined],['Annulés',summary.cancelled||0],['Erreurs techniques',summary.error||0],['Démarrages à réconcilier',summary.indeterminateStarts]];
  for(const [label,value] of values){const p=document.createElement('p'),strong=document.createElement('strong');strong.textContent=label+' : ';p.append(strong,document.createTextNode(String(value)));root.append(p);}
  const body=$('#paymentsActivity');body.replaceChildren();
  for(const row of data.transactions){
   const tr=document.createElement('tr');
   const stateLabels={created:'Créé',pending:'En attente',declined:'Refusé',cancelled:'Annulé',error:'Erreur technique',authorized:'Autorisé',captured:'Capturé'};
   const startLabels={ready:'Prêt',attempting:'Démarrage',indeterminate:'À réconcilier','':'—'};
   const values=[row.createdAt,row.paymentId.slice(0,12)+'…',(row.amountCents/100).toFixed(2)+' '+row.currency,stateLabels[row.state]||row.state,startLabels[row.startState]||row.startState];
   for(const value of values){const td=document.createElement('td');td.textContent=value;tr.append(td);}body.append(tr);
  }
  if(!data.transactions.length){const tr=document.createElement('tr'),td=document.createElement('td');td.colSpan=5;td.textContent='Aucune intention de paiement enregistrée.';tr.append(td);body.append(tr);}
 }
 async function reload(){
  if(busy)return;if(dirty&&!confirm('Abandonner les modifications non enregistrées et recharger ?'))return;
  setBusy(true);try{show(await request());await loadActivity();$('#paymentsAuth').hidden=true;message('Fiche chargée — version '+snapshot.revision+'. Paiements réels désactivés.');}catch(e){message(e.message,true);}finally{setBusy(false);}
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
 window.addEventListener('beforeunload',event=>{if(dirty){event.preventDefault();event.returnValue='';}});
 reload();
})();
