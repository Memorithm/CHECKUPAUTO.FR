const service=document.querySelector('#service');const price=document.querySelector('#price');service?.addEventListener('change',()=>{price.textContent=service.value});
const video=document.querySelector('#vehicleVideo');const stage=document.querySelector('.stage');let px=0,py=0,tx=0,ty=0;
if(stage&&video&&!matchMedia('(prefers-reduced-motion: reduce)').matches){stage.addEventListener('pointermove',e=>{const r=stage.getBoundingClientRect();tx=((e.clientX-r.left)/r.width-.5)*2;ty=((e.clientY-r.top)/r.height-.5)*2});stage.addEventListener('pointerleave',()=>{tx=0;ty=0});const tick=()=>{px+=(tx-px)*.045;py+=(ty-py)*.045;video.style.transform=`perspective(1200px) rotateY(${px*1.8}deg) rotateX(${-py*.8}deg) translate3d(${px*5}px,${py*3}px,35px)`;requestAnimationFrame(tick)};requestAnimationFrame(tick)}
const observer=new IntersectionObserver(entries=>entries.forEach(e=>{if(e.isIntersecting)e.target.classList.add('visible')}),{threshold:.12});document.querySelectorAll('.section article,.section h2,.section .kicker,.reservation,.trust').forEach(el=>{el.style.opacity='0';el.style.transform='translateY(18px)';el.style.transition='opacity .7s ease,transform .7s ease';observer.observe(el)});new MutationObserver(()=>{});document.addEventListener('scroll',()=>document.querySelectorAll('.section .visible,.reservation.visible,.trust.visible').forEach(el=>{}),{passive:true});observer.takeRecords();
const style=document.createElement('style');style.textContent='.visible{opacity:1!important;transform:none!important}';document.head.appendChild(style);


async function loadSiteConfig(){
 try{
  const r=await fetch('/api/site-config',{cache:'no-store'});if(!r.ok)return;
  const c=await r.json();window.cyberCheckConfig=c;
  const text=(sel,value)=>{const e=document.querySelector(sel);if(e)e.textContent=value};
  const toggle=(sel,show)=>document.querySelectorAll(sel).forEach(e=>e.classList.toggle('offer-hidden',!show));
  const top=document.querySelectorAll('.topline span'),phoneLink=document.querySelector('#phoneLink');if(phoneLink){phoneLink.textContent=c.business.phone;phoneLink.href='tel:'+c.business.phone.replace(/[^+\d]/g,'')}else if(top[1])top[1].textContent=c.business.phone;
  window.cyberCheckAnalyticsEnabled=c.analytics?.enabled!==false;
  text('.hero .kicker',c.hero.kicker);text('.lead-offer',c.offer.heroLine);text('.location','⌖ '+c.business.address);
  text('.offer-banner strong',c.offer.title);text('.offer-banner p span',c.offer.subtitle);
  text('.offer-seal strong','CONTRE-VISITE');text('.offer-seal b',c.offer.enabled?'OFFERTE':'');
  text('.reservation-offer','✓ '+c.offer.title.charAt(0)+c.offer.title.slice(1).toLowerCase());
  const trust=document.querySelector('.trust span:first-child');if(trust)trust.textContent='✓ '+c.offer.title;
  text('.card-offer',c.offer.title);text('.included-offer',c.offer.subtitle);
  const final=document.querySelector('.final h2');if(final)final.textContent=c.offer.finalTitle;
  const booking=document.querySelector('.reservation>a.primary');if(booking)booking.href=c.business.bookingUrl;
  const keys=['technical','fitted','pollution'],select=document.querySelector('#service');
  if(select){[...select.options].forEach(o=>{const k=o.dataset.service||o.value,s=c.services[k];if(s)o.textContent=s.label});select.dispatchEvent(new Event('change'))}
  const bookingPhone=document.querySelector('#bookingPhone');if(bookingPhone){bookingPhone.textContent='Appeler le centre · '+c.business.phone;bookingPhone.href='tel:'+c.business.phone.replace(/[^+\d]/g,'')}
  document.querySelectorAll('a.call-centre').forEach(a=>a.href='tel:'+c.business.phone.replace(/[^+\d]/g,''));
  const cards=document.querySelectorAll('.cards article');keys.forEach((k,i)=>{const card=cards[i],s=c.services[k];if(!card||!s)return;const h=card.querySelector('h3'),v=card.querySelector('strong');if(h)h.textContent=s.label+'.';if(v)v.textContent=String(s.price).replace('.',',')+'€'});
  toggle('.offer-banner,.offer-seal,.lead-offer,.reservation-offer,.trust span:first-child,.card-offer,.included-offer',c.offer.enabled);
 }catch(e){console.warn('CyberCheck config fallback:',e)}
}
loadSiteConfig().finally(()=>{initPlanner();initTracking()});



const plannerState={service:'technical',selected:null,data:null};
function localISODate(d=new Date()){const y=d.getFullYear(),m=String(d.getMonth()+1).padStart(2,'0'),day=String(d.getDate()).padStart(2,'0');return `${y}-${m}-${day}`}
function euro(v){return Number(v||0).toLocaleString('fr-FR',{minimumFractionDigits:Number(v)%1?2:0,maximumFractionDigits:2})+'€'}
function escapeHTML(v){return String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
function plannerServiceLabel(){const s=document.querySelector('#service');return s?.options[s.selectedIndex]?.textContent||''}
function setPlannerStatus(text,ok=true){const el=document.querySelector('#bookingLiveStatus');if(el){el.textContent=text;el.classList.toggle('error',!ok)}}
function clearPlannerSelection(){plannerState.selected=null;const box=document.querySelector('#bookingSelection');if(box)box.hidden=true;document.querySelectorAll('.slot-button.selected').forEach(b=>b.classList.remove('selected'))}
function renderPlanner(data){
 plannerState.data=data;clearPlannerSelection();const root=document.querySelector('#bookingDays');if(!root)return;root.replaceChildren();
 const days=(data.days||[]).filter(d=>d.available).slice(0,6);if(!days.length){root.innerHTML='<p class="booking-empty">Aucun créneau disponible sur cette période.</p>';return}
 const ip=data.incentives||window.cyberCheckConfig?.incentives||{},promoLabel=escapeHTML(ip.enabled===false?'TARIF RÉDUIT':(ip.label||'PRIX AVANTAGE'));
 for(const day of days){const article=document.createElement('article');article.className='booking-day';const head=document.createElement('div');head.className='booking-day-head';head.innerHTML=`<small>${day.weekday}</small><strong>${day.day} ${day.month}</strong>`;article.appendChild(head);const slots=document.createElement('div');slots.className='booking-slots';
  for(const slot of day.slots){const b=document.createElement('button');b.type='button';b.className='slot-button'+(slot.promotion?' promo':'');b.dataset.date=day.date;b.dataset.time=slot.time;b.dataset.price=slot.price;b.dataset.base=slot.basePrice;b.dataset.saving=slot.saving;b.dataset.discount=slot.discountPercent;if(slot.promotion){const original=ip.showOriginalPrice===false?'':`<s>${euro(slot.basePrice)}</s> `,pct=ip.showDiscountPercent===false?'':` · -${Math.round(slot.discountPercent)}%`;b.innerHTML=`<span>${slot.time}</span><small>${original}<b>${euro(slot.price)}</b></small><em>${promoLabel}${pct}</em>`}else b.innerHTML=`<span>${slot.time}</span><small>${euro(slot.price)}</small>`;b.addEventListener('click',()=>selectPlannerSlot(b,day,slot));slots.appendChild(b)}
  article.appendChild(slots);root.appendChild(article)}
}
function selectPlannerSlot(button,day,slot){document.querySelectorAll('.slot-button.selected').forEach(b=>b.classList.remove('selected'));button.classList.add('selected');plannerState.selected={day,slot};const box=document.querySelector('#bookingSelection'),label=document.querySelector('#bookingSelectionLabel'),price=document.querySelector('#bookingSelectionPrice'),cta=document.querySelector('#bookingContinue');if(!box||!label||!price||!cta)return;label.textContent=`${day.weekday} ${day.day} ${day.month} · ${slot.time}`;price.textContent=slot.promotion?`${euro(slot.price)} · économie ${euro(slot.saving)}`:`${euro(slot.price)} TTC`;const q=new URLSearchParams(location.search),p=new URLSearchParams();p.set('referrer',trackingReferrer());p.set('utmSource',q.get('utm_source')||'');p.set('utmCampaign',q.get('utm_campaign')||'');p.set('device',trackingDevice());p.set('path',location.pathname);p.set('service',plannerServiceLabel());p.set('preferredDate',day.date);p.set('preferredTime',slot.time);cta.href='/go/booking?'+p.toString();box.hidden=false;box.scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth',block:'nearest'})}
async function loadPlanner(){const service=document.querySelector('#service'),date=document.querySelector('#bookingStartDate'),root=document.querySelector('#bookingDays');if(!service||!date||!root)return;plannerState.service=service.value;clearPlannerSelection();root.innerHTML='<p class="booking-loading">Chargement des créneaux…</p>';setPlannerStatus('Connexion à Mercure…');try{const r=await fetch(`/api/booking/availability?service=${encodeURIComponent(service.value)}&date=${encodeURIComponent(date.value)}`,{cache:'no-store'}),d=await r.json();if(!r.ok)throw new Error(d.error||`HTTP ${r.status}`);document.querySelector('#price').textContent=String(Math.round(d.service.basePrice));renderPlanner(d);setPlannerStatus('Disponibilités Mercure · mises à jour à l’instant')}catch(e){root.innerHTML='<p class="booking-empty">Les disponibilités sont momentanément indisponibles. Vous pouvez appeler le centre.</p>';setPlannerStatus(e.message||'Indisponible',false)}}
function initPlanner(){const service=document.querySelector('#service'),date=document.querySelector('#bookingStartDate'),refresh=document.querySelector('#bookingRefresh');if(!service||!date)return;const today=localISODate();date.min=today;const horizon=Math.max(1,Math.min(180,Number(window.cyberCheckConfig?.incentives?.horizonDays||30)));const max=new Date();max.setDate(max.getDate()+horizon);date.max=localISODate(max);if(!date.value)date.value=today;service.addEventListener('change',()=>{const cfg=window.cyberCheckConfig?.services?.[service.value];if(cfg)document.querySelector('#price').textContent=String(cfg.price);loadPlanner()});date.addEventListener('change',loadPlanner);refresh?.addEventListener('click',loadPlanner);loadPlanner()}

function trackingDevice(){const w=window.innerWidth;return w<700?'mobile':w<1100?'tablet':'desktop'}
function trackingReferrer(){try{return document.referrer?new URL(document.referrer).origin:''}catch{return ''}}
function trackEvent(event,extra={}){
 if(window.cyberCheckAnalyticsEnabled===false)return;
 const q=new URLSearchParams(location.search);
 const payload={event,path:location.pathname,device:trackingDevice(),referrer:trackingReferrer(),utmSource:q.get('utm_source')||'',utmCampaign:q.get('utm_campaign')||'',...extra};
 fetch('/api/events',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload),keepalive:true}).catch(()=>{});
}
function initTracking(){
 if(window.cyberCheckAnalyticsEnabled===false)return;
 trackEvent('page_view');
 document.addEventListener('click',e=>{
  const a=e.target.closest('a');if(!a)return;
  if(a.matches('.hero .primary,.book'))trackEvent('hero_cta_click');
  if(a.matches('.reservation>a.primary')){
   e.preventDefault();
   const q=new URLSearchParams(location.search),p=new URLSearchParams();
   p.set('referrer',trackingReferrer());p.set('utmSource',q.get('utm_source')||'');p.set('utmCampaign',q.get('utm_campaign')||'');
   p.set('device',trackingDevice());p.set('path',location.pathname);p.set('service',service?.options[service.selectedIndex]?.textContent||'');
   location.href='/go/booking?'+p.toString();return;
  }
  if(a.matches('#phoneLink')||a.href?.startsWith('tel:'))trackEvent('phone_click');
  if(a.href?.includes('google.com/maps'))trackEvent('directions_click');
 });
 service?.addEventListener('change',e=>{if(e.isTrusted)trackEvent('service_selected',{service:service.options[service.selectedIndex]?.textContent||''})});
 const offer=document.querySelector('.offer-banner');if(offer){let sent=false;const io=new IntersectionObserver(es=>{if(!sent&&es.some(x=>x.isIntersecting)){sent=true;trackEvent('offer_viewed');io.disconnect()}},{threshold:.5});io.observe(offer)}
}
