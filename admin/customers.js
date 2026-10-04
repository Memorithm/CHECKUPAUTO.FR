'use strict';
(() => {
 const $=s=>document.querySelector(s),route='/api/admin/customers/oidc';
 let snapshot=null,busy=false;
 const message=(text,error=false)=>{$('#oidcMessage').textContent=text;$('#oidcMessage').classList.toggle('error',error);};
 const setBusy=value=>{busy=value;document.querySelectorAll('#oidcProviders input,#oidcProviders button,#oidcReload').forEach(el=>{el.disabled=value;});};
 const managedProviders=new Set(['google','apple']);
 function help(provider){
  if(provider==='apple')return 'Apple : utilisez le Services ID comme Client ID. Le Client Secret est le JWT signé généré avec votre clé Sign in with Apple.';
  return 'Google : application OAuth Web avec le callback ci-dessus autorisé.';
 }
 function render(data){
  snapshot=data;const root=$('#oidcProviders');root.replaceChildren();
  for(const row of data.providers){
   if(!managedProviders.has(row.id))continue;
   const card=document.createElement('article');card.className='oidc-card';card.dataset.provider=row.id;
   const title=document.createElement('h3');title.textContent=row.label;
   const state=document.createElement('span');state.className='oidc-state '+(row.configured?'ready':'missing');state.textContent=row.configured?'CONFIGURÉ':'À CONFIGURER';
   const callback=document.createElement('div');callback.className='oidc-callback';callback.textContent='Callback : '+row.callbackUrl;
   const clientLabel=document.createElement('label');clientLabel.textContent='Client ID';
   const client=document.createElement('input');client.id='oidc-client-'+row.id;client.autocomplete='off';client.maxLength=512;client.spellcheck=false;clientLabel.append(client);
   const secretLabel=document.createElement('label');secretLabel.textContent='Client Secret';
   const secret=document.createElement('input');secret.id='oidc-secret-'+row.id;secret.type='password';secret.autocomplete='new-password';secret.maxLength=4096;secretLabel.append(secret);
   const hint=document.createElement('p');hint.className='oidc-help';hint.textContent=help(row.id);
   const actions=document.createElement('div');actions.className='oidc-actions';
   const save=document.createElement('button');save.type='button';save.textContent=row.configured?'Remplacer la configuration':'Installer la configuration';
   save.addEventListener('click',()=>saveProvider(row.id));
   const remove=document.createElement('button');remove.type='button';remove.className='secondary';remove.textContent='Désactiver';remove.disabled=!row.configured;
   remove.addEventListener('click',()=>removeProvider(row.id));
   actions.append(save,remove);card.append(title,state,callback,clientLabel,secretLabel,hint,actions);root.append(card);
  }
 }
 async function request(payload){
  const options={cache:'no-store',credentials:'same-origin',headers:{}};
  if(payload){options.method='POST';options.headers={'Content-Type':'application/json','X-CheckupAuto-Customer-OIDC-CSRF':snapshot.csrfToken};options.body=JSON.stringify(payload);}
  const response=await fetch(route,options);
  if(response.status===401||response.status===403){$('#oidcAuth').hidden=false;throw new Error('Authentification ou double authentification à renouveler.');}
  const data=await response.json().catch(()=>({}));
  if(!response.ok||!data.ok)throw new Error(response.status===400?'Configuration refusée. Vérifiez les champs et le callback déclaré chez le fournisseur.':'Configuration des connecteurs indisponible.');
  return data;
 }
 async function load(force=false){
  if(busy&&!force)return;if(!force)setBusy(true);
  try{const data=await request();render(data);$('#oidcAuth').hidden=true;message('État des connecteurs chargé. Les secrets ne sont jamais relus.');}
  catch(e){message(e.message||'Connecteurs indisponibles.',true);}
  finally{if(!force)setBusy(false);}
 }
 async function saveProvider(provider){
  if(busy||!snapshot)return;
  const clientId=$('#oidc-client-'+provider).value.trim(),clientSecret=$('#oidc-secret-'+provider).value;
  if(!clientId||!clientSecret){message('Client ID et Client Secret sont obligatoires.',true);return;}
  setBusy(true);
  try{
   const data=await request({action:'save',provider,clientId,clientSecret});
   $('#oidc-client-'+provider).value='';$('#oidc-secret-'+provider).value='';
   await load(true);message('Connecteur '+provider+' enregistré. Le secret a été effacé du formulaire et n’est pas relu.');
  }catch(e){$('#oidc-secret-'+provider).value='';message(e.message||'Enregistrement impossible.',true);}
  finally{setBusy(false);}
 }
 async function removeProvider(provider){
  if(busy||!snapshot)return;
  if(!confirm('Désactiver ce connecteur pour les nouvelles connexions ? Les comptes existants sont conservés.'))return;
  setBusy(true);
  try{await request({action:'remove',provider});await load(true);message('Connecteur '+provider+' désactivé.');}
  catch(e){message(e.message||'Suppression impossible.',true);}
  finally{setBusy(false);}
 }
 $('#oidcReload').addEventListener('click',load);load();
})();