(()=>{
const COOKIE='cc_cookie_consent_v1';
const CATEGORIES=['preferences','analytics','marketing','external_media'];
let policyVersion='';
let returnFocus=null;
function getCookie(){
 const raw=document.cookie.split('; ').find(x=>x.startsWith(COOKIE+'='));
 if(!raw)return null;
 try{const v=JSON.parse(decodeURIComponent(raw.slice(COOKIE.length+1)));return v&&v.version===1?v:null}catch(_){return null}
}
function setCookie(value){
 document.cookie=COOKIE+'='+encodeURIComponent(JSON.stringify(value))+'; Path=/; Max-Age=15552000; SameSite=Lax; Secure';
}
function stateFrom(choice){
 const categories={necessary:true};
 for(const key of CATEGORIES)categories[key]=!!choice[key];
 return {version:1,policyVersion:policyVersion,categories:categories,updatedAt:new Date().toISOString()};
}
function focusables(root){return Array.from(root.querySelectorAll('button,input,a[href]')).filter(e=>!e.disabled)}
function trapFocus(root,dismissible){
 root.addEventListener('keydown',event=>{
  if(event.key==='Escape'&&dismissible){event.preventDefault();closePanel();return}
  if(event.key!=='Tab')return;
  const items=focusables(root);if(!items.length)return;
  const first=items[0],last=items[items.length-1];
  if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus()}
  else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus()}
 });
}
function focusPanel(root){const first=focusables(root)[0];if(first)first.focus()}
function closePanel(){
 document.getElementById('cc-consent-panel')?.remove();
 const target=returnFocus;returnFocus=null;
 if(target&&typeof target.focus==='function'&&document.contains?.(target))target.focus();
}
function publish(state){
 window.CyberCheckConsent={
  state:state,
  allowed:category=>category==='necessary'||!!state?.categories?.[category],
  open:()=>openPreferences()
 };
 window.dispatchEvent(new CustomEvent('cybercheck:consent',{detail:state}));
}
function button(label,action,secondary){
 const b=document.createElement('button');b.type='button';b.textContent=label;
 b.style.cssText='border:1px solid #214f40;border-radius:999px;padding:10px 15px;font-weight:700;cursor:pointer;min-height:44px;font-size:14px;'+(secondary?'background:#fff;color:#214f40':'background:#214f40;color:#fff');
 b.addEventListener('click',action);return b;
}
function shell(dismissible){
 let root=document.getElementById('cc-consent-panel');
 if(root)root.remove();
 else returnFocus=document.activeElement||null;
 root=document.createElement('section');root.id='cc-consent-panel';root.setAttribute('role','dialog');root.setAttribute('aria-modal','true');root.setAttribute('aria-label','Préférences de confidentialité');
 root.style.cssText='position:fixed;z-index:2147483000;left:16px;right:16px;bottom:16px;max-width:760px;margin:auto;background:#fff;color:#17372b;border:1px solid #cfd8d2;border-radius:18px;box-shadow:0 18px 60px rgba(20,45,36,.18);padding:20px;font-family:system-ui,sans-serif;box-sizing:border-box;max-height:calc(100vh - 32px);max-height:calc(100dvh - 32px);overflow-y:auto;overscroll-behavior:contain';
 trapFocus(root,!!dismissible);
 document.body.appendChild(root);return root;
}
function saveAndClose(choice){
 const state=stateFrom(choice);setCookie(state);publish(state);
 ensureManageButton();closePanel();
}
function openPreferences(){
 const stored=getCookie();
 const existing=stored||stateFrom({});
 // Escape only dismisses when a choice already exists; the first decision stays explicit.
 const root=shell(!!stored);
 const title=document.createElement('h2');title.textContent='Vos préférences de confidentialité';title.style.cssText='margin:0 0 8px;font-size:22px';
 const intro=document.createElement('p');intro.textContent='Les traceurs strictement nécessaires restent actifs. Les autres catégories sont désactivées tant que vous ne les autorisez pas.';intro.style.cssText='line-height:1.55;color:#53675e;margin:0 0 16px';
 root.append(title,intro);
 const form=document.createElement('div');form.style.cssText='display:grid;gap:10px;margin:12px 0 18px';
 for(const category of CATEGORIES){
  const row=document.createElement('label');row.style.cssText='display:flex;gap:10px;align-items:center;padding:9px 0;border-bottom:1px solid #edf0ed';
  const input=document.createElement('input');input.type='checkbox';input.dataset.category=category;input.checked=!!existing.categories?.[category];
  const text=document.createElement('span');text.textContent=({preferences:'Préférences',analytics:'Mesure d’audience',marketing:'Marketing',external_media:'Médias externes'})[category];
  row.append(input,text);form.appendChild(row);
 }
 root.appendChild(form);
 const actions=document.createElement('div');actions.style.cssText='display:flex;gap:8px;flex-wrap:wrap';
 actions.append(
  button('Tout refuser',()=>saveAndClose({}),true),
  button('Enregistrer mes choix',()=>{
   const choice={};form.querySelectorAll('input[data-category]').forEach(i=>choice[i.dataset.category]=i.checked);saveAndClose(choice);
  },false),
  button('Tout accepter',()=>saveAndClose(Object.fromEntries(CATEGORIES.map(k=>[k,true]))),false)
 );
 const links=document.createElement('p');links.style.cssText='margin:14px 0 0;font-size:12px';
 links.innerHTML='<a href="/cookies" style="color:#214f40">Politique cookies</a> · <a href="/confidentialite" style="color:#214f40">Confidentialité</a>';
 root.append(actions,links);
 focusPanel(root);
}
function firstBanner(){
 const root=shell();
 const h=document.createElement('h2');h.textContent='Cookies et confidentialité';h.style.cssText='margin:0 0 8px;font-size:22px';
 const p=document.createElement('p');p.textContent='Checkup Auto utilise uniquement les traceurs nécessaires sans accord. Vous pouvez accepter, refuser ou personnaliser les autres traceurs.';p.style.cssText='line-height:1.55;color:#53675e;margin:0 0 16px';
 const actions=document.createElement('div');actions.style.cssText='display:flex;gap:8px;flex-wrap:wrap';
 actions.append(button('Tout refuser',()=>saveAndClose({}),true),button('Personnaliser',openPreferences,true),button('Tout accepter',()=>saveAndClose(Object.fromEntries(CATEGORIES.map(k=>[k,true]))),false));
 root.append(h,p,actions);
 focusPanel(root);
}
function ensureManageButton(){
 if(document.getElementById('cc-consent-manage'))return;
 const b=document.createElement('button');b.id='cc-consent-manage';b.type='button';b.textContent='Cookies';
 b.style.cssText='position:fixed;z-index:2147482999;left:14px;bottom:14px;border:1px solid #cad4ce;border-radius:999px;background:#fff;color:#214f40;padding:8px 11px;font:600 11px system-ui;cursor:pointer;box-shadow:0 5px 18px rgba(20,45,36,.12)';
 b.addEventListener('click',openPreferences);document.body.appendChild(b);
}
async function init(){
 let policy;
 try{const r=await fetch('/api/compliance/cookies',{cache:'no-store',headers:{Accept:'application/json'}});if(!r.ok)return;policy=await r.json()}catch(_){return}
 policyVersion=String(policy?.policyVersion||'');
 if(!policy?.consentRequired){
  publish(stateFrom({}));
  return;
 }
 const stored=getCookie();
 // A choice recorded for a different list of trackers must be asked again.
 if(stored&&stored.policyVersion===policyVersion){publish(stored);ensureManageButton()}else{publish(stateFrom({}));firstBanner()}
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();
})();