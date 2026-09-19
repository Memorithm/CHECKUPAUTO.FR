const rr=id=>document.getElementById(id);

async function rrApi(path,options={}){
  const response=await fetch(path,{cache:'no-store',...options});
  let data={};
  try{data=await response.json()}catch{}
  if(!response.ok||data.ok===false)throw new Error(data.error||`HTTP ${response.status}`);
  return data;
}

function rrEuro(cents){
  return (Number(cents||0)/100).toLocaleString('fr-FR',{style:'currency',currency:'EUR'});
}

function rrShareUrl(code){
  let origin=location.origin;
  try{
    const canonical=window.cyberCheckAdminConfig?.seo?.canonicalUrl;
    if(canonical)origin=new URL(canonical).origin;
  }catch{}
  return origin+'/p/'+encodeURIComponent(code);
}
function rrText(id,value){
  const el=rr(id);if(el)el.textContent=value;
}

function rrRender(data){
  const rows=data.accounts||[];
  rrText('referralAccountCount',String(rows.length));
  rrText('referralWalletTotal',rrEuro(rows.reduce((n,x)=>n+Number(x.balanceCents||0),0)));
  rrText('referralPendingTotal',rrEuro(rows.reduce((n,x)=>n+Number(x.pendingCents||0),0)));
  rrText('referralEarnedTotal',String(rows.reduce((n,x)=>n+Number(x.earnedReferrals||0),0)));
  rrText('referralRewardValue',rrEuro(data.rewardCents||500));

  const body=rr('referralAccounts');
  body.replaceChildren();
  if(!rows.length){
    const tr=document.createElement('tr'),td=document.createElement('td');
    td.colSpan=6;td.textContent='Aucun code de parrainage créé.';
    tr.appendChild(td);body.appendChild(tr);return;
  }
  for(const account of rows){
    const tr=document.createElement('tr');
    const values=[
      account.code,
      String(account.earnedReferrals||0),
      String(account.pendingReferrals||0),
      rrEuro(account.pendingCents),
      rrEuro(account.balanceCents)
    ];
    for(const value of values){
      const td=document.createElement('td');td.textContent=value;tr.appendChild(td);
    }
    const action=document.createElement('td');
    const button=document.createElement('button');
    button.type='button';button.className='secondary compact-action';button.textContent='Copier le lien';
    button.addEventListener('click',async()=>{
      const url=rrShareUrl(account.code);
      try{
        await navigator.clipboard.writeText(url);
        button.textContent='Copié';
        setTimeout(()=>button.textContent='Copier le lien',1200);
      }catch{
        rrText('referralMessage',url);
      }
    });
    action.appendChild(button);tr.appendChild(action);body.appendChild(tr);
  }
}
async function rrLoad(){
  const badge=rr('referralState');
  if(badge){badge.textContent='Chargement…';badge.className='gsc-status warning'}
  try{
    const data=await rrApi('/api/admin/referrals/accounts?limit=100');
    rrRender(data);
    if(badge){badge.textContent='ReferralWallet actif';badge.className='gsc-status online'}
    return data;
  }catch(error){
    if(badge){badge.textContent='Indisponible';badge.className='gsc-status offline'}
    rrText('referralMessage',error.message);
    throw error;
  }
}

async function rrCreate(){
  const code=rr('referralCustomCode')?.value.trim()||'';
  const data=await rrApi('/api/admin/referrals/account',{
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({code})
  });
  if(rr('referralCustomCode'))rr('referralCustomCode').value='';
  rrText('referralMessage',`Code créé : ${data.account.code} · ${rrShareUrl(data.account.code)}`);
  await rrLoad();
}

async function rrRedeem(){
  const code=rr('referralRedeemCode')?.value.trim()||'';
  const euros=Number(rr('referralRedeemAmount')?.value||0);
  const reference=rr('referralRedeemReference')?.value.trim()||'';
  const amountCents=Math.round(euros*100);
  if(!code||!Number.isFinite(euros)||amountCents<=0||!reference)throw new Error('Code, montant et référence sont requis.');
  const data=await rrApi('/api/admin/referrals/redeem',{
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({code,amountCents,reference})
  });
  rrText('referralMessage',`Crédit utilisé. Nouveau solde : ${rrEuro(data.account.balanceCents)}`);
  await rrLoad();
}
function rrBind(id,handler){
  rr(id)?.addEventListener('click',async()=>{
    const button=rr(id),old=button.textContent;
    button.disabled=true;
    try{await handler()}
    catch(error){rrText('referralMessage',error.message);alert(error.message)}
    finally{button.disabled=false;button.textContent=old}
  });
}

rrBind('referralCreate',rrCreate);
rrBind('referralRedeem',rrRedeem);
rrBind('referralRefresh',rrLoad);
rrLoad().catch(()=>{});
