const ih=id=>document.getElementById(id);

async function ihApi(path,options={}){
  const r=await fetch(path,{cache:'no-store',...options});
  let data={};
  try{data=await r.json()}catch{}
  if(!r.ok||data.ok===false)throw new Error(data.error||`HTTP ${r.status}`);
  return data;
}

function ihStatusClass(state){
  return state==='connected'?'online':state==='attention'?'warning':'offline';
}

function ihOauthHealthText(health={}){
  const state=health.state||'awaiting_authorization';
  if(health.usable)return health.refreshable?'OAuth renouvelable':'OAuth actif';
  if(state==='token_expired')return 'jeton expiré';
  if(state==='reauthorization_required')return 'réautorisation requise';
  if(state==='oauth_client_missing')return 'client OAuth manquant';
  return 'autorisation requise';
}

function ihRender(data){
  const badge=ih('integrationGoogleStatus');
  const rows=data.connectors||[];
  const connected=rows.filter(x=>x.connected).length;
  badge.textContent=`${connected}/${rows.length} services prêts`;
  badge.className='gsc-status '+(connected?'online':'warning');

  const client=data.oauthClient||{};
  const oauthHealth=data.oauthHealth||{};
  ih('googleOAuthRedirectUri').textContent=data.redirectUri||'—';
  ih('googleOAuthIdentity').textContent=client.configured
    ? `Client OAuth installé · ${client.projectId||'projet Google'} · …${client.clientIdSuffix||''} · ${ihOauthHealthText(oauthHealth)}`
    : 'Aucun client OAuth Google installé.';
  if(!oauthHealth.usable&&['token_expired','reauthorization_required','oauth_client_missing'].includes(oauthHealth.state)){
    badge.className='gsc-status offline';
  }

  const grid=ih('googleConnectorGrid');
  grid.replaceChildren();
  for(const row of rows){
    const card=document.createElement('article');
    card.className='integration-card '+row.state;

    const head=document.createElement('div');
    const title=document.createElement('strong');
    title.textContent=row.label;
    const status=document.createElement('span');
    status.className='gsc-status '+ihStatusClass(row.state);
    status.textContent=row.connected?'Connecté':row.state==='attention'?'À compléter':'À connecter';
    head.append(title,status);

    const category=document.createElement('small');
    category.textContent=row.category;
    const desc=document.createElement('p');
    desc.textContent=row.description;
    const detail=document.createElement('em');
    detail.textContent=row.detail;

    card.append(head,category,desc,detail);

    if(!row.connected&&row.mode!=='api_key'){
      const label=document.createElement('label');
      label.className='integration-select';
      const input=document.createElement('input');
      input.type='checkbox';
      input.value=row.id;
      input.dataset.integrationConnector='google';
      const text=document.createElement('span');
      text.textContent='Autoriser ce service';
      label.append(input,text);
      card.append(label);
    }
    grid.append(card);
  }

  const s=data.settings||{};
  ih('googleAnalyticsPropertyId').value=s.analyticsPropertyId||'';
  ih('googleBusinessAccountId').value=s.businessAccountId||'';
  ih('googleTagManagerAccountId').value=s.tagManagerAccountId||'';
  ih('googleGmailSender').value=s.gmailSender||'';
  ih('googleMapsKey').value='';
  ih('googleAdsDeveloperToken').value='';
  ih('googleMapsKey').placeholder=s.mapsApiKeyConfigured?'Clé API déjà enregistrée · laisser vide pour conserver':'Clé API Google Maps / Places';
  ih('googleAdsDeveloperToken').placeholder=s.googleAdsDeveloperTokenConfigured?'Jeton déjà enregistré · laisser vide pour conserver':'Jeton développeur Google Ads';

  ih('integrationDisconnectGoogle').disabled=!data.oauthAuthorized;
  ih('integrationConnectSelected').disabled=!client.configured;
}

async function ihLoad(){
  const badge=ih('integrationGoogleStatus');
  badge.textContent='Diagnostic…';
  badge.className='gsc-status warning';
  try{ihRender(await ihApi('/api/admin/integrations/google/status'))}
  catch(e){
    badge.textContent='Diagnostic impossible';
    badge.className='gsc-status offline';
    ih('googleIntegrationMessage').textContent=e.message;
  }
}

async function ihInstallClient(){
  const file=ih('googleOAuthClientFile').files?.[0];
  if(!file)throw new Error('Sélectionnez le fichier JSON du client OAuth Google.');
  let payload;
  try{payload=JSON.parse(await file.text())}
  catch{throw new Error('Le fichier client OAuth Google n’est pas un JSON valide.')}
  await ihApi('/api/admin/integrations/google/oauth-client',{
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify(payload)
  });
  ih('googleOAuthClientFile').value='';
  await ihLoad();
}

async function ihConnectSelected(){
  const connectors=[...document.querySelectorAll('input[data-integration-connector="google"]:checked')].map(x=>x.value);
  if(!connectors.length)throw new Error('Sélectionnez au moins un service Google à autoriser.');
  const data=await ihApi('/api/admin/integrations/google/oauth/start',{
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({connectors})
  });
  if(!data.authorizationUrl)throw new Error('Google n’a pas fourni d’URL d’autorisation.');
  window.location.assign(data.authorizationUrl);
}

async function ihSaveSettings(){
  const payload={
    analyticsPropertyId:ih('googleAnalyticsPropertyId').value.trim(),
    businessAccountId:ih('googleBusinessAccountId').value.trim(),
    tagManagerAccountId:ih('googleTagManagerAccountId').value.trim(),
    gmailSender:ih('googleGmailSender').value.trim()
  };
  const maps=ih('googleMapsKey').value.trim();
  const ads=ih('googleAdsDeveloperToken').value.trim();
  if(maps)payload.mapsApiKey=maps;
  if(ads)payload.googleAdsDeveloperToken=ads;
  await ihApi('/api/admin/integrations/google/settings',{
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify(payload)
  });
  ih('googleIntegrationMessage').textContent='Paramètres privés enregistrés.';
  await ihLoad();
}

async function ihDisconnect(){
  if(!confirm('Révoquer la connexion OAuth Google de CheckupAuto ? Les clés Maps et le compte de service Search Console ne seront pas supprimés.'))return;
  await ihApi('/api/admin/integrations/google/oauth',{method:'DELETE'});
  await ihLoad();
}

function ihBind(id,fn){
  ih(id)?.addEventListener('click',async()=>{
    const b=ih(id),old=b.textContent;
    b.disabled=true;
    try{await fn()}
    catch(e){ih('googleIntegrationMessage').textContent=e.message;alert(e.message)}
    finally{b.disabled=false;b.textContent=old}
  });
}

ihBind('integrationInstallGoogleClient',ihInstallClient);
ihBind('integrationConnectSelected',ihConnectSelected);
ihBind('integrationSaveGoogleSettings',ihSaveSettings);
ihBind('integrationDisconnectGoogle',ihDisconnect);
ihBind('integrationRefreshGoogle',ihLoad);
ihLoad();
