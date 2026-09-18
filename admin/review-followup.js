const rf=(id)=>document.getElementById(id);
async function rfApi(path,options){const r=await fetch(path,options);const d=await r.json().catch(()=>({}));if(!r.ok)throw new Error(d.error||('HTTP '+r.status));return d}
function rfNum(v){return Number(v||0).toLocaleString('fr-FR')}
async function loadReviewFollowup(){
 const badge=rf('reviewFollowupState');if(badge){badge.textContent='Analyse…';badge.className='gsc-status warning'}
 try{
  const d=await rfApi('/api/admin/reviews/status');
  rf('reviewSent24h').textContent=rfNum(d.sent24h);rf('reviewSentTotal').textContent=rfNum(d.sentTotal);rf('reviewFailures').textContent=rfNum(d.permanentFailures);rf('reviewDelay').textContent=rfNum(d.delayMinutes)+' min';
  let detail='Mode : tous les contrôles honorés · aucune sélection selon le résultat.';
  if(!d.sessionConnected)detail+=' Session Mercure expirée : envoi suspendu.';
  else if(d.nativeFavorableOnlyEmailEnabled===true)detail+=' Ancien automatisme Mercure « favorable uniquement » détecté : CyberCheck le désactivera avant tout envoi.';
  else detail+=' Session Mercure opérationnelle.';
  detail+=' '+(d.privacy||'');rf('reviewFollowupDetail').textContent=detail;
  const ok=d.sessionConnected&&d.nativeFavorableOnlyEmailEnabled!==true;
  if(badge){badge.textContent=ok?'Actif':'En attente';badge.className='gsc-status '+(ok?'online':'warning')}
 }catch(e){if(badge){badge.textContent='Indisponible';badge.className='gsc-status offline'}rf('reviewFollowupDetail').textContent=String(e.message||e)}
}
async function processReviewFollowup(){const b=rf('reviewFollowupProcess');if(b)b.disabled=true;try{const d=await rfApi('/api/admin/reviews/process',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});await loadReviewFollowup();alert(d.ok?`Contrôle terminé · ${d.sent||0} envoi(s)`:(d.error||d.state||'En attente'))}finally{if(b)b.disabled=false}}
rf('reviewFollowupRefresh')?.addEventListener('click',loadReviewFollowup);rf('reviewFollowupProcess')?.addEventListener('click',()=>processReviewFollowup().catch(e=>alert(e.message)));loadReviewFollowup();
