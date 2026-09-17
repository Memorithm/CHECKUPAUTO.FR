const g=id=>document.getElementById(id);
async function gscApi(path,options={}){
 const r=await fetch(path,{cache:'no-store',...options});
 let data={};try{data=await r.json()}catch{}
 if(!r.ok||data.ok===false)throw new Error(data.error||`HTTP ${r.status}`);
 return data;
}
function gscBadge(text,ok=false,warn=false){
 const e=g('gscStatus');e.textContent=text;e.className='gsc-status '+(ok?'online':warn?'warning':'offline');
}
function fnum(v,d=0){return Number(v||0).toLocaleString('fr-FR',{maximumFractionDigits:d})}
function renderRows(id,rows){
 const body=g(id);body.innerHTML='';
 if(!rows?.length){body.innerHTML='<tr><td colspan="4">Aucune donnée sur la période</td></tr>';return}
 for(const row of rows){
  const tr=document.createElement('tr'),label=row.keys?.[0]||'—';
  tr.innerHTML=`<td title="${label.replaceAll('"','&quot;')}">${label}</td><td>${fnum(row.clicks)}</td><td>${fnum(row.impressions)}</td><td>${fnum(row.position,1)}</td>`;
  body.appendChild(tr);
 }
}
async function loadGSCStatus(){
 try{
  const s=await gscApi('/api/admin/google/status');g('gscProperty').textContent=s.property||'—';
  const info=s.credentials||{};g('gscIdentity').textContent=info.configured?`${info.clientEmail||'Compte de service'} · ${info.projectId||'projet inconnu'}`:'Aucun compte de service configuré.';
  g('gscPermission').textContent=s.permissionLevel||'Aucune permission détectée';
  if(s.connected)gscBadge('Connecté à Google',true);else if(info.configured)gscBadge('Autorisation Search Console requise',false,true);else gscBadge('Non connecté');
 }catch(e){gscBadge('Erreur de connexion');g('gscIdentity').textContent=e.message}
}
async function installGSCCredentials(){
 const file=g('gscCredentials').files?.[0];if(!file)throw new Error('Sélectionnez le fichier JSON du compte de service Google.');
 let payload;try{payload=JSON.parse(await file.text())}catch{throw new Error('Le fichier JSON est invalide.');}
 await gscApi('/api/admin/google/credentials',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
 g('gscCredentials').value='';await loadGSCStatus();
}
async function testGSC(){
 const r=await gscApi('/api/admin/google/test',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
 g('gscPermission').textContent=r.permissionLevel||'Propriété non accessible';
 if(!r.accessible)throw new Error('Le compte Google est valide mais n’a pas accès à la propriété configurée. Ajoutez son e-mail dans Search Console.');
 gscBadge('Connexion validée',true);
}
async function disconnectGSC(){
 if(!confirm('Supprimer les identifiants Google Search Console de ce serveur ?'))return;
 await gscApi('/api/admin/google/credentials',{method:'DELETE'});await loadGSCStatus();
}
async function refreshGSCPerformance(){
 const d=await gscApi('/api/admin/google/performance?days=28'),s=d.summary||{};
 g('gscClicks').textContent=fnum(s.clicks);g('gscImpressions').textContent=fnum(s.impressions);
 g('gscCtr').textContent=fnum((s.ctr||0)*100,1)+' %';g('gscPosition').textContent=fnum(s.position,1);
 g('gscPeriod').textContent=`${d.startDate} → ${d.endDate}`;
 renderRows('gscQueries',d.topQueries);renderRows('gscPages',d.topPages);
}
async function loadGSCSitemaps(){
 const d=await gscApi('/api/admin/google/sitemaps'),items=d.sitemaps||[];
 if(!items.length){g('gscSitemapState').textContent='Aucun sitemap déclaré pour cette propriété.';return}
 g('gscSitemapState').textContent=items.map(x=>`${x.path||'sitemap'} · ${x.isPending?'en attente':'traité'}${x.lastSubmitted?' · soumis '+new Date(x.lastSubmitted).toLocaleString('fr-FR'):''}`).join(' | ');
}
async function submitGSCSitemap(){
 const canonical=g('canonicalUrl').value.trim(),origin=new URL(canonical).origin;
 await gscApi('/api/admin/google/sitemap-submit',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({sitemapUrl:origin+'/sitemap.xml'})});
 g('gscSitemapState').textContent='Sitemap soumis à Google. Actualisation…';await loadGSCSitemaps();
}
async function inspectGSCUrl(){
 const url=g('gscInspectUrl').value.trim()||g('canonicalUrl').value.trim();
 const d=await gscApi('/api/admin/google/inspect',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({url})});
 const r=d.result?.inspectionResult||{},i=r.indexStatusResult||{};
 const lines=[`Verdict : ${i.verdict||'—'}`,`Couverture : ${i.coverageState||'—'}`,`Indexation : ${i.indexingState||'—'}`,`robots.txt : ${i.robotsTxtState||'—'}`,`Récupération : ${i.pageFetchState||'—'}`,`Dernier crawl : ${i.lastCrawlTime?new Date(i.lastCrawlTime).toLocaleString('fr-FR'):'—'}`,`Canonique Google : ${i.googleCanonical||'—'}`,`Canonique déclarée : ${i.userCanonical||'—'}`];
 g('gscInspectResult').textContent=lines.join('\n');
}
function bindGSCButton(id,fn){g(id)?.addEventListener('click',async()=>{const b=g(id),old=b.textContent;b.disabled=true;try{await fn()}catch(e){alert(e.message)}finally{b.disabled=false;b.textContent=old}})}
bindGSCButton('gscInstallCredentials',installGSCCredentials);bindGSCButton('gscTest',testGSC);bindGSCButton('gscDisconnect',disconnectGSC);
bindGSCButton('gscRefresh',refreshGSCPerformance);bindGSCButton('gscLoadSitemaps',loadGSCSitemaps);bindGSCButton('gscSubmitSitemap',submitGSCSitemap);bindGSCButton('gscInspect',inspectGSCUrl);
if(g('gscInspectUrl')&&!g('gscInspectUrl').value)g('gscInspectUrl').value=g('canonicalUrl')?.value||'https://www.checkupauto.fr/';
loadGSCStatus();
