const cc=id=>document.getElementById(id);
async function ccApi(url){
 const r=await fetch(url,{cache:'no-store'});let data={};
 try{data=await r.json()}catch{}
 if(!r.ok||data.ok===false)throw new Error(data.error||`HTTP ${r.status}`);
 return data;
}
function ccText(id,value){const e=cc(id);if(e)e.textContent=value}
function ccNum(v,d=0){return Number(v||0).toLocaleString('fr-FR',{maximumFractionDigits:d})}
function metricDelta(id,value,unit='%'){
 const e=cc(id);if(!e)return;e.className='metric-delta';
 if(value===null){e.textContent='Nouveau vs période précédente';e.classList.add('up');return}
 const n=Number(value||0),sign=n>0?'+':'';e.textContent=`${sign}${ccNum(n,1)} ${unit} vs période précédente`;
 e.classList.add(n>0?'up':n<0?'down':'flat');
}
function renderSimpleTable(id,rows,labelKey,valueKey){
 const body=cc(id);if(!body)return;body.replaceChildren();
 if(!rows?.length){const tr=document.createElement('tr'),td=document.createElement('td');td.colSpan=2;td.textContent='Aucune donnée sur la période';tr.appendChild(td);body.appendChild(tr);return}
 for(const row of rows){const tr=document.createElement('tr'),a=document.createElement('td'),b=document.createElement('td');a.textContent=row[labelKey]||'—';b.textContent=ccNum(row[valueKey]);tr.append(a,b);body.appendChild(tr)}
}
function renderSourceFunnels(rows){
 const body=cc('analyticsSourceFunnels');if(!body)return;body.replaceChildren();
 if(!rows?.length){const tr=document.createElement('tr'),td=document.createElement('td');td.colSpan=8;td.textContent='Aucune donnée sur la période';tr.appendChild(td);body.appendChild(tr);return}
 for(const row of rows){
  const tr=document.createElement('tr');
  for(const v of [row.source||'—',ccNum(row.views),ccNum(row.bookings),ccNum(row.confirmedBookings),ccNum(row.confirmationRate,1)+' %',(Number(row.revenueCents||0)/100).toLocaleString('fr-FR',{style:'currency',currency:'EUR'}),ccNum(row.phoneClicks),ccNum(row.directionsClicks)]){const td=document.createElement('td');td.textContent=v;tr.appendChild(td)}
  body.appendChild(tr);
 }
}
function renderCampaigns(rows){
 const body=cc('analyticsCampaigns');if(!body)return;body.replaceChildren();
 if(!rows?.length){const tr=document.createElement('tr'),td=document.createElement('td');td.colSpan=4;td.textContent='Aucune campagne UTM sur la période';tr.appendChild(td);body.appendChild(tr);return}
 for(const row of rows){const tr=document.createElement('tr');for(const v of [row.campaign||'—',ccNum(row.views),ccNum(row.bookings),ccNum(row.bookingRate,1)+' %']){const td=document.createElement('td');td.textContent=v;tr.appendChild(td)}body.appendChild(tr)}
}
function renderHistory(rows){
 const svg=cc('analyticsHistoryChart');if(!svg)return;svg.replaceChildren();
 const ns='http://www.w3.org/2000/svg',w=760,h=220,pad={l:38,r:12,t:16,b:30},plotW=w-pad.l-pad.r,plotH=h-pad.t-pad.b;
 const max=Math.max(1,...(rows||[]).flatMap(r=>[Number(r.views||0),Number(r.bookings||0),Number(r.confirmedBookings||0)]));
 const x=i=>pad.l+(rows.length<=1?0:(i/(rows.length-1))*plotW),y=v=>pad.t+plotH-(Number(v||0)/max)*plotH;
 for(let i=0;i<=4;i++){const yy=pad.t+(plotH*i/4),line=document.createElementNS(ns,'line');line.setAttribute('x1',pad.l);line.setAttribute('x2',w-pad.r);line.setAttribute('y1',yy);line.setAttribute('y2',yy);line.setAttribute('class','chart-grid');svg.appendChild(line)}
 const makePath=(key,cls)=>{const path=document.createElementNS(ns,'path'),d=(rows||[]).map((r,i)=>(i?'L':'M')+x(i).toFixed(1)+' '+y(r[key]).toFixed(1)).join(' ');path.setAttribute('d',d||`M${pad.l} ${pad.t+plotH}`);path.setAttribute('class','chart-line '+cls);path.setAttribute('fill','none');svg.appendChild(path)};
 makePath('views','views');makePath('bookings','bookings');makePath('confirmedBookings','confirmed');
 const maxLabel=document.createElementNS(ns,'text');maxLabel.setAttribute('x','4');maxLabel.setAttribute('y',String(pad.t+4));maxLabel.setAttribute('class','chart-label');maxLabel.textContent=String(max);svg.appendChild(maxLabel);
 const zero=document.createElementNS(ns,'text');zero.setAttribute('x','20');zero.setAttribute('y',String(pad.t+plotH+4));zero.setAttribute('class','chart-label');zero.textContent='0';svg.appendChild(zero);
 if(rows?.length){for(const i of [...new Set([0,Math.floor((rows.length-1)/2),rows.length-1])]){const t=document.createElementNS(ns,'text');t.setAttribute('x',String(x(i)));t.setAttribute('y',String(h-8));t.setAttribute('text-anchor',i===0?'start':i===rows.length-1?'end':'middle');t.setAttribute('class','chart-label');t.textContent=new Date(rows[i].day+'T00:00:00').toLocaleDateString('fr-FR',{day:'2-digit',month:'2-digit'});svg.appendChild(t)}}
}
async function loadAnalytics(){
 const days=Number(cc('analyticsPeriod')?.value||30),d=await ccApi(`/api/admin/analytics?days=${days}`);
 ccText('metricViews',ccNum(d.pageViews));ccText('metricBookings',ccNum(d.bookingClicks));ccText('metricBookingRate',ccNum(d.bookingRate,1)+' %');
 ccText('metricHero',ccNum(d.heroCtaClicks));ccText('metricPhone',ccNum(d.phoneClicks));ccText('metricDirections',ccNum(d.directionsClicks));
 ccText('metricConfirmed',ccNum(d.confirmedBookings));ccText('metricConfirmationRate',ccNum(d.confirmationRate,1)+' %');
 ccText('metricRevenue',(Number(d.revenueCents||0)/100).toLocaleString('fr-FR',{style:'currency',currency:'EUR'}));ccText('metricAttribution',ccNum(d.attributionRate,1)+' %');
 metricDelta('metricConfirmedDelta',d.delta?.confirmedBookingsPct);metricDelta('metricConfirmationDelta',d.delta?.confirmationRatePoints,'pt');metricDelta('metricRevenueDelta',d.delta?.revenuePct);
 renderMercureStatus(d.bookingIntegration||{});
 metricDelta('metricViewsDelta',d.delta?.pageViewsPct);metricDelta('metricBookingsDelta',d.delta?.bookingClicksPct);metricDelta('metricRateDelta',d.delta?.bookingRatePoints,'pt');
 metricDelta('metricHeroDelta',d.delta?.heroCtaClicksPct);metricDelta('metricPhoneDelta',d.delta?.phoneClicksPct);metricDelta('metricDirectionsDelta',d.delta?.directionsClicksPct);
 ccText('analyticsPeriodLabel',`${d.period?.start||''} → ${d.period?.end||''} · comparaison ${d.period?.previousStart||''} → ${d.period?.previousEnd||''}`);
 renderHistory(d.daily||[]);renderSourceFunnels(d.sourceFunnels||[]);renderCampaigns(d.campaignFunnels||[]);renderSimpleTable('analyticsDevices',d.devices,'device','views');
}
function renderMercureStatus(s){
 ccText('mercurePending',ccNum(s.pendingIntents));ccText('mercureConfirmed',ccNum(s.confirmedBookings));
 ccText('mercureAttribution',ccNum(s.attributionRate,1)+' %');
 const e=cc('mercureStatus');if(e){const active=Number(s.confirmedBookings||0)>0;e.textContent=active?'Flux de confirmations actif':'En attente du flux fournisseur';e.className='gsc-status '+(active?'online':'warning')}
 const body=cc('mercureRecent');if(body){body.replaceChildren();const rows=s.recent||[];if(!rows.length){const tr=document.createElement('tr'),td=document.createElement('td');td.colSpan=6;td.textContent='Aucun événement Mercure reçu';tr.appendChild(td);body.appendChild(tr)}else for(const row of rows){const tr=document.createElement('tr');for(const v of [row.externalId||'—',row.status||'—',row.service||'—',row.source||'Non attribué',(Number(row.amountCents||0)/100).toLocaleString('fr-FR',{style:'currency',currency:'EUR'}),row.updatedAt?new Date(row.updatedAt).toLocaleString('fr-FR'):'—']){const td=document.createElement('td');td.textContent=v;tr.appendChild(td)}body.appendChild(tr)}}
}
function renderMercureLivePartners(rows){
 const body=cc('mercureLivePartners');if(!body)return;body.replaceChildren();
 if(!rows?.length){body.innerHTML='<tr><td colspan="2">Aucune donnée</td></tr>';return}
 for(const row of rows){const tr=document.createElement('tr');for(const v of [row.partner||'—',ccNum(row.count)]){const td=document.createElement('td');td.textContent=v;tr.appendChild(td)}body.appendChild(tr)}
}
function renderMercureLiveServices(rows){
 const body=cc('mercureLiveServices');if(!body)return;body.replaceChildren();
 if(!rows?.length){body.innerHTML='<tr><td colspan="3">Aucune donnée</td></tr>';return}
 for(const row of rows){const tr=document.createElement('tr');for(const v of [row.service||'—',ccNum(row.count),Number(row.value||0).toLocaleString('fr-FR',{style:'currency',currency:'EUR'})]){const td=document.createElement('td');td.textContent=v;tr.appendChild(td)}body.appendChild(tr)}
}
async function loadMercureLive(){
 const days=Number(cc('analyticsPeriod')?.value||30),badge=cc('mercureAdminStatus');
 if(badge){badge.textContent='Synchronisation…';badge.className='gsc-status warning'}
 try{
  const d=await ccApi(`/api/admin/mercure/live-summary?days=${days}`),by=Object.fromEntries((d.partners||[]).map(x=>[x.partner,x.count]));
  ccText('mercureLiveTotal',ccNum(d.appointments));ccText('mercureLiveWeb',ccNum(by['MERCURE WEB']||0));ccText('mercureLiveCteasy',ccNum(by.CTEASY||0));ccText('mercureLiveDirect',ccNum(by['Direct / interne']||0));
  ccText('mercureLivePaid',ccNum(d.paid));ccText('mercureLiveValue',Number(d.scheduledValue||0).toLocaleString('fr-FR',{style:'currency',currency:'EUR'}));ccText('mercureLiveHonored',ccNum(d.honored));ccText('mercureLiveNoShow',ccNum(d.notHonored));
  ccText('mercureLivePeriod',`${days} derniers jours`);const dash=d.dashboard30d||{};ccText('mercureLiveOnlinePaid',ccNum(dash.nbr_rendezvous_paiement_ligne));ccText('mercureLiveOnlineSum',dash.somme_rendezvous_paiement_ligne?`${dash.somme_rendezvous_paiement_ligne} €`:'—');
  renderMercureLivePartners(d.partners||[]);renderMercureLiveServices(d.services||[]);
  if(badge){badge.textContent='Session Mercure connectée';badge.className='gsc-status online'}const loginBadge=cc('mercureLoginState');if(loginBadge){loginBadge.textContent='Session connectée';loginBadge.className='gsc-status online'}
  return d;
 }catch(e){if(badge){badge.textContent='Session Mercure expirée';badge.className='gsc-status offline'}const loginBadge=cc('mercureLoginState');if(loginBadge){loginBadge.textContent='Session expirée';loginBadge.className='gsc-status offline'}throw e}
}

function promoISO(d=new Date()){const y=d.getFullYear(),m=String(d.getMonth()+1).padStart(2,'0'),day=String(d.getDate()).padStart(2,'0');return `${y}-${m}-${day}`}
function promoEventId(row){return row?.id??row?.creneauId??row?.promotion_creneau_id??row?.extendedProps?.creneauId??row?.extendedProps?.promotionCreneauId??''}
function promoEventLabel(row){return row?.title??row?.promotionName??row?.name??row?.extendedProps?.promotionName??'Promotion Mercure'}
async function loadPromoPlanner(){
 const start=cc('promoDateStart')?.value||promoISO(),end=cc('promoDateEnd')?.value||start,body=cc('promoEvents');if(!body)return;
 body.innerHTML='<tr><td colspan="4">Chargement…</td></tr>';
 try{const d=await ccApi(`/api/admin/mercure/promotions?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`),rows=d.events||[];body.replaceChildren();
  if(!rows.length){body.innerHTML='<tr><td colspan="4">Aucun créneau remisé sur cette période.</td></tr>';ccText('promoPlannerStatus','Aucun créneau remisé sur la période');return}
  for(const row of rows){const tr=document.createElement('tr'),id=promoEventId(row),vals=[promoEventLabel(row),row.start||row.dateStart||'—',row.end||row.dateEnd||'—'];for(const v of vals){const td=document.createElement('td');td.textContent=String(v);tr.appendChild(td)}const td=document.createElement('td');if(id){const b=document.createElement('button');b.type='button';b.className='danger compact-action';b.textContent='Supprimer';b.addEventListener('click',()=>deletePromoSlot(id));td.appendChild(b)}else td.textContent='—';tr.appendChild(td);body.appendChild(tr)}ccText('promoPlannerStatus',`${rows.length} créneau(x) promotionnel(s) Mercure`)
 }catch(e){body.innerHTML='<tr><td colspan="4">Lecture impossible.</td></tr>';ccText('promoPlannerStatus',e.message)}
}
async function createPromoSlot(){
 const service=cc('promoService')?.value,finalPrice=Number(cc('promoFinalPrice')?.value),dateStart=cc('promoDateStart')?.value,dateEnd=cc('promoDateEnd')?.value,timeStart=cc('promoTimeStart')?.value,timeEnd=cc('promoTimeEnd')?.value,weekdays=[...document.querySelectorAll('#promoWeekdays input:checked')].map(x=>x.value);
 const r=await fetch('/api/admin/mercure/promo-slot',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({service,finalPrice,dateStart,dateEnd,timeStart,timeEnd,weekdays})}),d=await r.json();if(!r.ok||d.ok===false)throw new Error(d.error||`HTTP ${r.status}`);ccText('promoPlannerStatus',`Remise enregistrée dans Mercure · ${Number(d.finalPrice).toLocaleString('fr-FR',{style:'currency',currency:'EUR'})}`);await loadPromoPlanner()
}
async function deletePromoSlot(id){if(!confirm('Supprimer ce créneau promotionnel Mercure ?'))return;const r=await fetch('/api/admin/mercure/promo-slot?id='+encodeURIComponent(id),{method:'DELETE'}),d=await r.json();if(!r.ok||d.ok===false)throw new Error(d.error||`HTTP ${r.status}`);await loadPromoPlanner()}
let promoPolicy=null;
function applyPromoPolicy(c){
 const p=c?.incentives||{},svc=c?.services||{};promoPolicy=p;const select=cc('promoService'),price=cc('promoFinalPrice'),start=cc('promoDateStart'),end=cc('promoDateEnd');
 if(select){[...select.options].forEach(o=>o.disabled=p.eligibleServices?.[o.value]===false);if(select.selectedOptions[0]?.disabled){const first=[...select.options].find(o=>!o.disabled);if(first)select.value=first.value}}
 if(start){const today=promoISO();start.min=today;const max=new Date();max.setDate(max.getDate()+Number(p.horizonDays||30));start.max=promoISO(max)}
 if(end){end.min=start?.value||promoISO();const max=new Date();max.setDate(max.getDate()+Number(p.horizonDays||30));end.max=promoISO(max)}
 if(cc('promoTimeStart'))cc('promoTimeStart').value=p.timeStart||'09:00';if(cc('promoTimeEnd'))cc('promoTimeEnd').value=p.timeEnd||'19:00';
 const allowed=new Set((p.allowedWeekdays||[1,2,3,4,5,6]).map(Number));document.querySelectorAll('#promoWeekdays input').forEach(x=>{x.disabled=!allowed.has(Number(x.value));x.checked=allowed.has(Number(x.value))});
 const key=select?.value||'technical',base=Number(svc[key]?.price|| (key==='technical'?80:90)),def=Number(p.defaultDiscountPercent||0),cap=Number(p.maxDiscountPercent||0);if(price){price.max=String(Math.max(0.01,base-0.01));price.min=cap>0?String(Math.max(0.01,Math.ceil(base*(1-cap/100)*100)/100)):'0.01';if(def>0)price.value=(base*(1-def/100)).toFixed(2)}
 const b=cc('promoCreate');if(b)b.disabled=p.enabled===false;ccText('promoPlannerStatus',p.enabled===false?'Système d’incitation désactivé':`Politique active · horizon ${p.horizonDays||30} j · ${p.label||'PRIX AVANTAGE'}`);
}
function initPromoPlanner(){const start=cc('promoDateStart'),end=cc('promoDateEnd');if(start&&!start.value)start.value=promoISO();if(end&&!end.value){const d=new Date();d.setDate(d.getDate()+30);end.value=promoISO(d)}
 const refreshPrice=()=>{if(window.cyberCheckAdminConfig)applyPromoPolicy(window.cyberCheckAdminConfig)};cc('promoService')?.addEventListener('change',refreshPrice);cc('promoDateStart')?.addEventListener('change',()=>{if(end)end.min=start.value});
 window.addEventListener('cybercheck-config-loaded',e=>applyPromoPolicy(e.detail));if(window.cyberCheckAdminConfig)applyPromoPolicy(window.cyberCheckAdminConfig);
 cc('promoReload')?.addEventListener('click',()=>loadPromoPlanner().catch(e=>alert(e.message)));cc('promoCreate')?.addEventListener('click',async()=>{const b=cc('promoCreate'),old=b.textContent;b.disabled=true;b.textContent='Enregistrement Mercure…';try{await createPromoSlot()}catch(e){alert(e.message)}finally{b.disabled=promoPolicy?.enabled===false;b.textContent=old}});loadPromoPlanner().catch(()=>{})}

async function loginMercure(){
 const username=cc('mercureLoginUser')?.value||'',password=cc('mercureLoginPassword')?.value||'',badge=cc('mercureLoginState');
 if(!username||!password)throw new Error('Identifiant et mot de passe Mercure requis');
 if(badge){badge.textContent='Connexion…';badge.className='gsc-status warning'}
 const r=await fetch('/api/admin/mercure/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username,password})}),d=await r.json();
 if(cc('mercureLoginPassword'))cc('mercureLoginPassword').value='';
 if(!r.ok||d.ok===false){if(badge){badge.textContent='Connexion refusée';badge.className='gsc-status offline'}throw new Error(d.error||`HTTP ${r.status}`)}
 if(badge){badge.textContent='Session connectée';badge.className='gsc-status online'}
 await loadMercureLive();return d;
}

async function launchBookingTest(){
 const popup=window.open('about:blank','cybercheck-booking-test');
 try{
  const r=await fetch('/api/admin/booking-test/session',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'}),d=await r.json();if(!r.ok||d.ok===false)throw new Error(d.error||`HTTP ${r.status}`);
  ccText('bookingTestStatus',`Lien valable jusqu’au ${new Date(d.expiresAt).toLocaleTimeString('fr-FR',{hour:'2-digit',minute:'2-digit'})}`);
  if(popup)popup.location=d.url;else window.location=d.url;
 }catch(e){if(popup)popup.close();throw e}
}

async function loadMercureIntegration(){
 const days=Number(cc('analyticsPeriod')?.value||30),d=await ccApi(`/api/admin/mercure/status?days=${days}`);
 ccText('mercureWebhookUrl',d.webhookUrl||'—');ccText('mercureBrowserCallbackUrl',d.browserCallbackUrl||'—');ccText('mercurePreviewWebhookUrl',location.origin+'/api/integrations/mercure/booking-confirmed');ccText('mercureSecretFingerprint',d.secret?.fingerprint||'—');renderMercureStatus(d.stats||{});
 ccText('mercureConfirmedPeriod',`${days} derniers jours`);
}
async function copyMercureSecret(){
 const d=await ccApi('/api/admin/mercure/secret'),secret=d.secret;if(!secret)throw new Error('Secret indisponible');
 try{await navigator.clipboard.writeText(secret);alert('Secret webhook copié dans le presse-papiers.')}catch{prompt('Secret webhook — copiez cette valeur :',secret)}
}
async function rotateMercureSecret(){
 if(!confirm('Régénérer le secret invalidera immédiatement toute configuration webhook existante chez AutoBilan-Systems. Continuer ?'))return;
 const r=await fetch('/api/admin/mercure/rotate-secret',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'}),d=await r.json();if(!r.ok||d.ok===false)throw new Error(d.error||`HTTP ${r.status}`);
 ccText('mercureSecretFingerprint',d.fingerprint||'—');try{await navigator.clipboard.writeText(d.secret);alert('Nouveau secret généré et copié.')}catch{prompt('Nouveau secret webhook :',d.secret)}
}
async function securityPost(url,payload={}){const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)}),d=await r.json();if(!r.ok||d.ok===false)throw new Error(d.error||`HTTP ${r.status}`);return d}
async function ackSecurityAlert(id){await securityPost('/api/admin/security/alerts/ack',{id});await loadSecurity()}
async function loadSecurity(){
 const badge=cc('securityStatus');if(badge){badge.textContent='Analyse…';badge.className='gsc-status warning'}
 try{
  const [d,posture,ai,alertData]=await Promise.all([ccApi('/api/admin/security/status?days=1'),ccApi('/api/admin/security/posture'),ccApi('/api/admin/security/ai'),ccApi('/api/admin/security/alerts')]);
  const profiles=d.behaviorProfiles||[],highProfiles=profiles.filter(x=>Number(x.max_risk||0)>=65);
  ccText('securityEvents',ccNum(d.events));ccText('securityBlocked',ccNum(d.blocked));ccText('securityQuarantines',ccNum(d.activeQuarantines));ccText('securityAlertsOpen',ccNum(alertData.open));ccText('securityHighRiskProfiles',ccNum(highProfiles.length));
  ccText('securityIntegrity',posture.integrity?.ok?'OK':'ALERTE');ccText('securityGit',posture.git?.dirty?'MODIFIÉ':'PROPRE');ccText('securityDependencies',posture.dependencies?.ok?'CONFORMES':'DÉRIVE');ccText('securitySbom',ccNum(posture.sbom?.componentCount));ccText('securityVulns',posture.vulnerabilities?.count===null?'—':ccNum(posture.vulnerabilities?.count));ccText('securityAiSeverity',String(ai.severity||'—').toUpperCase());
  const gitHead=(posture.git?.head||'').slice(0,12);ccText('securityIntegrityDetail',posture.integrity?.ok?`${posture.integrity.protectedFiles||0} fichiers conformes · Git ${gitHead||'indisponible'}`:`Altérations: ${(posture.integrity?.changed||[]).length}, manquants: ${(posture.integrity?.missing||[]).length}, Git dirty: ${posture.integrity?.gitDirty?'oui':'non'}.`);
  const deps=posture.dependencies||{};ccText('securityDependencyDetail',deps.ok?'requirements.txt et environnement Python concordent.':`Manquants ${deps.missing?.length||0} · divergents ${deps.mismatched?.length||0} · non figés ${deps.unpinned?.length||0}.`);
  const deterministic=`Moteur déterministe: ${ai.summary||'aucune anomalie synthétisée.'}`;
  ccText('securityAiSummary',ai.modelUsed&&ai.aiSummary?`${deterministic} · IA locale (${ai.model||'modèle'}): ${ai.aiSummary}`:deterministic);
  const delivery=alertData.webhookConfigured?`Relais webhook actif · ${ccNum(alertData.undeliveredHighOrCritical||0)} alerte(s) haute(s) en attente.`:'Alertes persistantes locales actives · aucun webhook externe configuré.';
  ccText('securityAlertDelivery',`${delivery} · Scores/quarantaines ${d.statePersistence==='sqlite'?'persistants SQLite':'mémoire'}.`);
  const reasons=cc('securityReasons');if(reasons){reasons.replaceChildren();const rows=d.topReasons||[];if(!rows.length)reasons.innerHTML='<tr><td colspan="2">Aucun incident</td></tr>';else for(const row of rows){const tr=document.createElement('tr');for(const v of [row.reason||'—',ccNum(row.count)]){const td=document.createElement('td');td.textContent=v;tr.appendChild(td)}reasons.appendChild(tr)}}
  const bp=cc('securityBehaviorProfiles');if(bp){bp.replaceChildren();if(!profiles.length)bp.innerHTML='<tr><td colspan="6">Aucun profil</td></tr>';else for(const row of profiles){const tr=document.createElement('tr');for(const v of [row.fingerprint||'—',row.classification||'normal',ccNum(row.requests),ccNum(row.errors),ccNum(row.unique_paths),ccNum(row.max_risk,1)]){const td=document.createElement('td');td.textContent=v;tr.appendChild(td)}bp.appendChild(tr)}}
  const ab=cc('securityAlerts');if(ab){ab.replaceChildren();const actionable=Array.isArray(alertData.actionable)?alertData.actionable:[],latest=Array.isArray(alertData.latest)?alertData.latest:[],seen=new Set(actionable.map(row=>Number(row.id))),rows=[...actionable,...latest.filter(row=>!seen.has(Number(row.id)))].slice(0,50);if(!rows.length)ab.innerHTML='<tr><td colspan="6">Aucune alerte</td></tr>';else for(const row of rows){const tr=document.createElement('tr');if(!row.acknowledged&&['high','critical'].includes(String(row.level||'').toLowerCase()))tr.className='security-alert-actionable';for(const v of [row.created_at?new Date(row.created_at).toLocaleString('fr-FR'):'—',String(row.level||'').toUpperCase(),row.kind||'—',row.title||'—',row.delivered?'relayée':'locale']){const td=document.createElement('td');td.textContent=v;tr.appendChild(td)}const td=document.createElement('td');if(!row.acknowledged){const b=document.createElement('button');b.type='button';b.className='secondary compact-action';b.textContent='Acquitter';b.addEventListener('click',()=>ackSecurityAlert(row.id).catch(e=>alert(e.message)));td.appendChild(b)}else td.textContent='Acquittée';tr.appendChild(td);ab.appendChild(tr)}}
  const vb=cc('securityVulnerabilities');if(vb){vb.replaceChildren();const rows=posture.vulnerabilities?.findings||[];if(!rows.length)vb.innerHTML='<tr><td colspan="3">Aucune vulnérabilité connue</td></tr>';else for(const row of rows){const tr=document.createElement('tr');for(const v of [`${row.component||'—'} ${row.version||''}`,row.id||'—',row.summary||'—']){const td=document.createElement('td');td.textContent=v;tr.appendChild(td)}vb.appendChild(tr)}}
  const files=cc('securityIntegrityFiles');if(files){files.replaceChildren();const changed=posture.integrity?.changed||[],missing=posture.integrity?.missing||[];const rows=[...changed.map(x=>({state:'MODIFIÉ',path:x.path})),...missing.map(path=>({state:'MANQUANT',path}))];if(posture.integrity?.gitHeadChanged)rows.push({state:'COMMIT',path:`HEAD ${posture.integrity.baselineGitHead?.slice(0,12)||'—'} → ${posture.git?.head?.slice(0,12)||'—'}`});if(!rows.length)files.innerHTML='<tr><td colspan="2">Aucune altération</td></tr>';else for(const row of rows){const tr=document.createElement('tr');for(const v of [row.state,row.path]){const td=document.createElement('td');td.textContent=v;tr.appendChild(td)}files.appendChild(tr)}}
  const recent=cc('securityRecent');if(recent){recent.replaceChildren();const rows=d.recent||[];if(!rows.length)recent.innerHTML='<tr><td colspan="6">Aucun incident récent</td></tr>';else for(const row of rows){const tr=document.createElement('tr');for(const v of [row.occurred_at?new Date(row.occurred_at).toLocaleString('fr-FR'):'—',row.client_hash||'—',row.method||'—',row.path||'—',row.action||'—',ccNum(row.risk)]){const td=document.createElement('td');td.textContent=v;tr.appendChild(td)}recent.appendChild(tr)}}
  if(badge){const bad=!posture.integrity?.ok||!posture.dependencies?.ok||Number(alertData.highOrCritical||0)>0||['critical','high'].includes(String(ai.severity||'').toLowerCase());badge.textContent=bad?'Sentinel · attention requise':'Sentinel actif';badge.className='gsc-status '+(bad?'warning':'online')}return {d,posture,ai,alertData}
 }catch(e){if(badge){badge.textContent='Sentinel indisponible';badge.className='gsc-status offline'}throw e}
}

function healthLabel(status){return status==='pass'?'CONFORME':status==='fail'?'ERREUR':'À SURVEILLER'}
async function loadSeoHealth(){
 const d=await ccApi('/api/admin/seo-health'),grid=cc('seoHealthGrid');grid.replaceChildren();
 ccText('healthPass',d.totals?.pass||0);ccText('healthWarning',d.totals?.warning||0);ccText('healthFail',d.totals?.fail||0);
 for(const item of d.checks||[]){
  const article=document.createElement('article');article.className='health-item '+item.status;
  const top=document.createElement('div'),name=document.createElement('strong'),badge=document.createElement('span'),detail=document.createElement('p');
  name.textContent=item.label;badge.textContent=healthLabel(item.status);top.append(name,badge);detail.textContent=item.detail;article.append(top,detail);grid.appendChild(article);
 }
}
async function runButton(id,fn){const b=cc(id);if(!b)return;b.addEventListener('click',async()=>{const old=b.textContent;b.disabled=true;b.textContent='Actualisation…';try{await fn()}catch(e){alert(e.message)}finally{b.disabled=false;b.textContent=old}})}
runButton('analyticsRefresh',async()=>{await Promise.all([loadAnalytics(),loadMercureIntegration(),loadMercureLive()])});runButton('seoHealthRefresh',loadSeoHealth);
cc('mercureLoginButton')?.addEventListener('click',()=>loginMercure().catch(e=>alert(e.message)));
cc('bookingTestLaunch')?.addEventListener('click',()=>launchBookingTest().catch(e=>alert(e.message)));
runButton('mercureRevealSecret',copyMercureSecret);runButton('mercureRotateSecret',rotateMercureSecret);runButton('securityRefresh',loadSecurity);
runButton('securityAssess',async()=>{await securityPost('/api/admin/security/assess');await loadSecurity()});
runButton('securityVulnRefresh',async()=>{await securityPost('/api/admin/security/vulnerability-refresh');await loadSecurity()});
cc('analyticsPeriod')?.addEventListener('change',()=>Promise.all([loadAnalytics(),loadMercureIntegration(),loadMercureLive()]).catch(e=>alert(e.message)));
initPromoPlanner();Promise.allSettled([loadAnalytics(),loadMercureIntegration(),loadMercureLive(),loadSecurity(),loadSeoHealth()]);
