const service=document.querySelector('#service');const price=document.querySelector('#price');service?.addEventListener('change',()=>{const cfg=window.cyberCheckConfig?.services?.[service.value];if(cfg&&price)price.textContent=String(cfg.price)});
// Essential booking controls must never depend on intersection ratios.
// A tall mobile planner may never reach a fractional visibility threshold.
const revealTargets=document.querySelectorAll('.section article,.section h2,.section .kicker');
if ('IntersectionObserver' in window && !matchMedia('(prefers-reduced-motion: reduce)').matches) {
 const revealObserver=new IntersectionObserver(entries=>entries.forEach(entry=>{
  if(entry.isIntersecting){entry.target.classList.add('visible');revealObserver.unobserve(entry.target)}
 }),{threshold:0});
 revealTargets.forEach(el=>{el.classList.add('reveal-pending');revealObserver.observe(el)});
}
const mobileNavigation=document.querySelector('.mobile-navigation');
mobileNavigation?.addEventListener('click',event=>{
 if(event.target.closest('a'))mobileNavigation.removeAttribute('open');
});
mobileNavigation?.addEventListener('keydown',event=>{
 if(event.key==='Escape'){mobileNavigation.removeAttribute('open');mobileNavigation.querySelector('summary').focus()}
});



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
loadSiteConfig().finally(()=>{initControlTypeSelector();initBookingTest();loadPlannerBounds().finally(()=>initPlanner());initTracking()});



function initControlTypeSelector(){
 const select=document.querySelector('#service'),buttons=[...document.querySelectorAll('.control-type-option')],services=window.cyberCheckConfig?.services||{};if(!select||!buttons.length)return;
 const sync=()=>{for(const b of buttons){const active=b.dataset.service===select.value;b.classList.toggle('selected',active);b.setAttribute('aria-pressed',String(active));const strong=b.querySelector('strong'),svc=services[b.dataset.service]||{};if(strong&&svc.price!=null){const label=b.dataset.service==='technical'?'Contrôle technique':'Véhicule aménagé';strong.replaceChildren(document.createTextNode(label+' '));const price=document.createElement('b');price.textContent=Number(svc.price).toLocaleString('fr-FR')+' €';strong.appendChild(price)}}};
 for(const b of buttons)b.addEventListener('click',()=>{select.value=b.dataset.service;select.dispatchEvent(new Event('change',{bubbles:true}));trackEvent('service_selected',{service:select.options[select.selectedIndex]?.textContent||''});sync()});
 select.addEventListener('change',sync);sync();
}

const bookingTestToken=new URLSearchParams(location.search).get('bookingTest')||'';
let bookingTestState=null;
async function initBookingTest(){
 if(!bookingTestToken)return;
 try{
  const r=await fetch('/api/booking-test/status?token='+encodeURIComponent(bookingTestToken),{cache:'no-store'}),d=await r.json();if(!r.ok)throw new Error(d.error||`HTTP ${r.status}`);bookingTestState=d;
  const host=document.querySelector('#reservation .booking-intro');if(host&&!document.querySelector('#bookingTestBanner')){const b=document.createElement('div');b.id='bookingTestBanner';b.className='booking-test-banner';b.innerHTML='<strong>MODE TEST MERCURE</strong><span>Parcours synthétique sécurisé · aucun email ni SMS · le rendez-vous test pourra être supprimé à la fin.</span>';host.after(b)}
  if(d.status==='created')showBookingTestResult(d); else if(d.status==='removed')showBookingTestRemoved(d);
 }catch(e){const host=document.querySelector('#reservation .booking-intro');if(host){const b=document.createElement('div');b.id='bookingTestBanner';b.className='booking-test-banner error';b.textContent='Mode test indisponible : '+e.message;host.after(b)}}
 const cta=document.querySelector('#bookingContinue');if(cta&&!cta.dataset.testBound){cta.dataset.testBound='1';cta.addEventListener('click',e=>{if(!bookingTestToken)return;e.preventDefault();createBookingTestAppointment().catch(err=>alert(err.message))})}
}

function testResultBox(){let box=document.querySelector('#bookingTestResult');if(box)return box;box=document.createElement('div');box.id='bookingTestResult';box.className='booking-test-result';const anchor=document.querySelector('#bookingSelection');anchor?.after(box);return box}
function showBookingTestResult(d){bookingTestState=d;const box=testResultBox();box.innerHTML=`<small>RENDEZ-VOUS TEST CRÉÉ DANS MERCURE</small><strong>ID ${escapeHTML(d.appointmentId||'—')}</strong><span>${escapeHTML(d.appointmentAt||'')} · ${escapeHTML(d.service||'')}</span><em>Vérifié dans le calendrier Mercure · aucune notification envoyée.</em><button type="button" id="bookingTestRemove">Supprimer ce rendez-vous test</button>`;box.classList.add('created');box.querySelector('#bookingTestRemove')?.addEventListener('click',()=>removeBookingTestAppointment().catch(err=>alert(err.message)))}
function showBookingTestRemoved(d){bookingTestState=d;const box=testResultBox();box.className='booking-test-result removed';box.innerHTML='<small>TEST TERMINÉ</small><strong>Rendez-vous test supprimé</strong><span>Mercure ne contient plus ce rendez-vous synthétique.</span>'}
async function createBookingTestAppointment(){if(!plannerState.selected)throw new Error('Sélectionnez d’abord un créneau');const cta=document.querySelector('#bookingContinue'),sel=plannerState.selected;if(cta){cta.classList.add('disabled');cta.textContent='Création dans Mercure…'}try{const r=await fetch('/api/booking-test/create',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token:bookingTestToken,service:plannerState.service,date:sel.day.date,time:sel.slot.time})}),d=await r.json();if(!r.ok)throw new Error(d.error||`HTTP ${r.status}`);showBookingTestResult(d);setPlannerStatus('Rendez-vous test créé et vérifié dans Mercure');return d}finally{if(cta){cta.classList.remove('disabled');cta.textContent='Créer le rendez-vous test →'}}}
async function removeBookingTestAppointment(){const b=document.querySelector('#bookingTestRemove');if(b){b.disabled=true;b.textContent='Suppression…'}const r=await fetch('/api/booking-test/remove',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token:bookingTestToken})}),d=await r.json();if(!r.ok)throw new Error(d.error||`HTTP ${r.status}`);showBookingTestRemoved(d);setPlannerStatus('Test terminé · rendez-vous supprimé de Mercure');setTimeout(()=>loadPlanner(),350);return d}
const plannerState={service:'technical',selected:null,data:null,bounds:null};
const promoPreviewRequested=new URLSearchParams(location.search).get('promoPreview')==='1';
function promoPreviewActive(){return promoPreviewRequested&&plannerState.bounds?.promoPreviewAllowed===true}
function parisISODate(d=new Date()){const parts=new Intl.DateTimeFormat('en-US',{timeZone:'Europe/Paris',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(d),values={};for(const part of parts)if(part.type!=='literal')values[part.type]=part.value;return `${values.year}-${values.month}-${values.day}`}
function addISODays(iso,days){const [y,m,d]=String(iso).split('-').map(Number);if(!y||!m||!d)return '';return new Date(Date.UTC(y,m-1,d+days)).toISOString().slice(0,10)}
function plannerFallbackBounds(){const businessDate=parisISODate(),horizon=Math.max(1,Math.min(180,Number(window.cyberCheckConfig?.incentives?.horizonDays||30)));return {businessDate,horizonEnd:addISODays(businessDate,horizon)}}
async function loadPlannerBounds(){try{const r=await fetch('/api/booking/services',{cache:'no-store'}),d=await r.json();if(!r.ok)throw new Error(`HTTP ${r.status}`);const businessDate=String(d.businessDate||''),horizonEnd=String(d.horizonEnd||''),valid=/^\d{4}-\d{2}-\d{2}$/;if(!valid.test(businessDate)||!valid.test(horizonEnd)||horizonEnd<businessDate)throw new Error('invalid booking bounds');plannerState.bounds={businessDate,horizonEnd,source:'server',promoPreviewAllowed:d.promoPreviewAllowed===true}}catch{plannerState.bounds={...plannerFallbackBounds(),source:'paris-fallback'}}}
function euro(v){return Number(v||0).toLocaleString('fr-FR',{minimumFractionDigits:Number(v)%1?2:0,maximumFractionDigits:2})+'€'}
function escapeHTML(v){return String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
function plannerServiceLabel(){const s=document.querySelector('#service');return s?.options[s.selectedIndex]?.textContent||''}
function setPlannerStatus(text,ok=true){const el=document.querySelector('#bookingLiveStatus');if(el){el.textContent=text;el.classList.toggle('error',!ok)}}
function clearPlannerSelection(){plannerState.selected=null;document.querySelectorAll('.slot-button.selected').forEach(b=>b.classList.remove('selected'));const box=document.querySelector('#bookingSelection'),kicker=document.querySelector('#bookingSelectionKicker'),label=document.querySelector('#bookingSelectionLabel'),price=document.querySelector('#bookingSelectionPrice'),cta=document.querySelector('#bookingContinue');if(!box||!label||!price||!cta)return;box.hidden=false;box.classList.add('booking-awaiting');if(kicker)kicker.textContent='RÉSERVATION EN LIGNE';label.textContent='Sélectionnez un créneau ci-dessus';price.textContent='Le bouton s’active automatiquement après votre choix.';cta.href='#bookingDays';cta.textContent='Choisissez un créneau pour réserver';cta.classList.add('disabled');cta.setAttribute('aria-disabled','true')}
function renderPlanner(data){
 plannerState.data=data;clearPlannerSelection();const root=document.querySelector('#bookingDays');if(!root)return;root.replaceChildren();
 const days=(data.days||[]).filter(d=>d.available).slice(0,6);if(!days.length){root.innerHTML='<p class="booking-empty">Aucun créneau disponible sur cette période.</p>';return}
 const ip=data.incentives||window.cyberCheckConfig?.incentives||{},promoLabel=escapeHTML(ip.enabled===false?'TARIF RÉDUIT':(ip.label||'PRIX AVANTAGE'));
 for(const day of days){const article=document.createElement('article');article.className='booking-day';const head=document.createElement('div');head.className='booking-day-head';head.innerHTML=`<small>${escapeHTML(day.weekday)}</small><strong>${escapeHTML(day.day)} ${escapeHTML(day.month)}</strong>`;article.appendChild(head);const slots=document.createElement('div');slots.className='booking-slots';
  for(const slot of day.slots){const b=document.createElement('button');b.type='button';b.className='slot-button'+(slot.promotion?' promo':'')+(slot.lowDemandOffer?' low-demand':'');b.dataset.date=day.date;b.dataset.time=slot.time;b.dataset.price=slot.price;b.dataset.base=slot.basePrice;b.dataset.saving=slot.saving;b.dataset.discount=slot.discountPercent;if(slot.promotion){const original=ip.showOriginalPrice===false?'':`<s>${euro(slot.basePrice)}</s> `,pct=ip.showDiscountPercent===false?'':` · -${Math.round(slot.discountPercent)}%`;b.innerHTML=`<span>${escapeHTML(slot.time)}</span><small>${original}<b>${euro(slot.price)}</b></small><em>${promoLabel}${pct}</em>`}else b.innerHTML=`<span>${escapeHTML(slot.time)}</span><small>${euro(slot.price)}</small>`;if(slot.lowDemandOffer){const flame=document.createElement('span');flame.className='slot-flame';flame.textContent='🔥';flame.setAttribute('aria-hidden','true');const clock=b.querySelector('span');if(clock){clock.classList.add('slot-time');clock.appendChild(flame)}const note=b.querySelector('em');if(note)note.textContent=(slot.previewOnly?'DÉMO · CRÉNEAU CALME · -':'CRÉNEAU CALME · -')+euro(slot.lowDemandOffer.savingEuro);if(slot.previewOnly)b.dataset.previewOnly='true';b.setAttribute('aria-label',(slot.previewOnly?'Simulation non réservable, ':'')+slot.time+', créneau plus calme : réduction de '+euro(slot.lowDemandOffer.savingEuro)+', prix '+euro(slot.price)+' TTC')}b.addEventListener('click',()=>selectPlannerSlot(b,day,slot));slots.appendChild(b)}
  article.appendChild(slots);root.appendChild(article)}
}
function selectPlannerSlot(button,day,slot){document.querySelectorAll('.slot-button.selected').forEach(b=>b.classList.remove('selected'));button.classList.add('selected');plannerState.selected={day,slot};const box=document.querySelector('#bookingSelection'),kicker=document.querySelector('#bookingSelectionKicker'),label=document.querySelector('#bookingSelectionLabel'),price=document.querySelector('#bookingSelectionPrice'),cta=document.querySelector('#bookingContinue');if(!box||!label||!price||!cta)return;box.classList.remove('booking-awaiting');if(kicker)kicker.textContent='CRÉNEAU SÉLECTIONNÉ';cta.classList.remove('disabled');cta.removeAttribute('aria-disabled');label.textContent=`${day.weekday} ${day.day} ${day.month} · ${slot.time}`;price.textContent=slot.lowDemandOffer?`${euro(slot.price)} TTC · économie ${euro(slot.lowDemandOffer.savingEuro)} (créneau calme, sous réserve de disponibilité chez Mercure)`:(slot.promotion?`${euro(slot.price)} · économie ${euro(slot.saving)}`:`${euro(slot.price)} TTC`);if(slot.previewOnly && promoPreviewActive()){price.textContent='SIMULATION : '+euro(slot.price)+' TTC · remise fictive '+euro(slot.lowDemandOffer.savingEuro)+' · aucun créneau Mercure réservé.';cta.href='#bookingDays';cta.textContent='Aperçu uniquement · réservation désactivée';cta.classList.add('disabled');cta.setAttribute('aria-disabled','true');box.scrollIntoView({behavior:'auto',block:'nearest'});return}const q=new URLSearchParams(location.search),p=new URLSearchParams();p.set('referrer',trackingReferrer());p.set('utmSource',q.get('utm_source')||'');p.set('utmCampaign',q.get('utm_campaign')||'');p.set('device',trackingDevice());p.set('path',location.pathname);p.set('service',plannerServiceLabel());const referral=q.get('ref')||'';if(referral)p.set('referralCode',referral);p.set('preferredDate',day.date);p.set('preferredTime',slot.time);if(bookingTestToken){cta.href='#';cta.textContent='Créer le rendez-vous test →'}else{cta.href='/go/booking?'+p.toString();cta.textContent='Réserver →'}box.scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth',block:'nearest'})}
async function loadPlanner(){const service=document.querySelector('#service'),date=document.querySelector('#bookingStartDate'),root=document.querySelector('#bookingDays');if(!service||!date||!root)return;plannerState.service=service.value;clearPlannerSelection();root.innerHTML='<p class="booking-loading">Chargement des créneaux…</p>';setPlannerStatus('Connexion à Mercure…');try{const endpoint=promoPreviewActive()?`/api/booking/promo-preview?service=${encodeURIComponent(service.value)}`:`/api/booking/availability?service=${encodeURIComponent(service.value)}&date=${encodeURIComponent(date.value)}`;const r=await fetch(endpoint,{cache:'no-store'}),d=await r.json();if(!r.ok)throw new Error(d.error||`HTTP ${r.status}`);document.querySelector('#price').textContent=String(Math.round(d.service.basePrice));renderPlanner(d);setPlannerStatus(promoPreviewActive()?'Quatre créneaux fictifs · -5 € · aucun tarif Mercure modifié':'Disponibilités Mercure · mises à jour à l’instant')}catch(e){root.innerHTML='<p class="booking-empty">Les disponibilités sont momentanément indisponibles. Vous pouvez appeler le centre.</p>';setPlannerStatus(e.message||'Indisponible',false)}}
function initPlanner(){const service=document.querySelector('#service'),date=document.querySelector('#bookingStartDate'),refresh=document.querySelector('#bookingRefresh');if(!service||!date)return;const bounds=plannerState.bounds||plannerFallbackBounds();date.min=bounds.businessDate;date.max=bounds.horizonEnd;if(!date.value||date.value<date.min||date.value>date.max)date.value=date.min;if(promoPreviewActive()){date.disabled=true;date.title='Dates figées pour la démonstration';const host=document.querySelector('.booking-live-head');if(host&&!document.querySelector('#promoPreviewBanner')){const banner=document.createElement('div');banner.id='promoPreviewBanner';banner.className='booking-promo-preview-banner';banner.setAttribute('role','status');banner.innerHTML='<strong>APERÇU DES FLAMMES · MODE TEST</strong><span>Quatre créneaux fictifs, les 9 et 10 octobre 2026, avec une réduction simulée de 5 €. Aucun créneau ni tarif Mercure modifié. Réservation désactivée.</span>';host.after(banner)}}service.addEventListener('change',()=>{const cfg=window.cyberCheckConfig?.services?.[service.value];if(cfg)document.querySelector('#price').textContent=String(cfg.price);loadPlanner()});date.addEventListener('change',()=>{const t=document.querySelector('.booking-date-text');if(t)t.textContent=date.value?new Date(date.value+'T12:00:00').toLocaleDateString('fr-FR',{day:'numeric',month:'long',year:'numeric'}):'Choisir une date';loadPlanner()});const dateText=document.querySelector('.booking-date-text');if(dateText&&date.value)dateText.textContent=new Date(date.value+'T12:00:00').toLocaleDateString('fr-FR',{day:'numeric',month:'long',year:'numeric'});refresh?.addEventListener('click',loadPlanner);loadPlanner()}

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
   p.set('device',trackingDevice());p.set('path',location.pathname);p.set('service',service?.options[service.selectedIndex]?.textContent||'');const referral=q.get('ref')||'';if(referral)p.set('referralCode',referral);
   location.href='/go/booking?'+p.toString();return;
  }
  if(a.matches('#phoneLink')||a.href?.startsWith('tel:'))trackEvent('phone_click');
  if(a.href?.includes('google.com/maps')&&!a.matches('[data-navigation-app]'))trackEvent('directions_click');
 });
 service?.addEventListener('change',e=>{if(e.isTrusted)trackEvent('service_selected',{service:service.options[service.selectedIndex]?.textContent||''})});
 const offer=document.querySelector('.offer-banner');if(offer){let sent=false;const io=new IntersectionObserver(es=>{if(!sent&&es.some(x=>x.isIntersecting)){sent=true;trackEvent('offer_viewed');io.disconnect()}},{threshold:.5});io.observe(offer)}
}

/* Accessible native navigation chooser: no unreliable installed-app detection. */
function initDirectionsPicker(){
 const opener=document.querySelector('#directionsOpen'),dialog=document.querySelector('#directionsDialog');
 if(!opener||!dialog||typeof dialog.showModal!=='function')return; // Keep Google Maps link as progressive fallback.
 const isAndroid=/Android/i.test(navigator.userAgent);
 const android=dialog.querySelector('[data-navigation-app="android"]'),apple=dialog.querySelector('[data-navigation-app="apple"]'),share=dialog.querySelector('[data-navigation-app="share"]');
 if(android)android.hidden=!isAndroid;
 if(apple)apple.hidden=isAndroid; // Apple Maps can still be used from other desktop platforms.
 if(share)share.hidden=isAndroid||typeof navigator.share!=='function';
 opener.addEventListener('click',event=>{
  event.preventDefault();
  if(!dialog.open){dialog.showModal();trackEvent('directions_picker_open')}
 });
 dialog.querySelector('.directions-dialog-close')?.addEventListener('click',()=>dialog.close());
 dialog.addEventListener('click',event=>{
  if(event.target!==dialog)return;
  const bounds=dialog.getBoundingClientRect();
  if(event.clientX<bounds.left||event.clientX>bounds.right||event.clientY<bounds.top||event.clientY>bounds.bottom)dialog.close();
 });
 dialog.addEventListener('close',()=>opener.focus({preventScroll:true}));
 dialog.querySelectorAll('a[data-navigation-app]').forEach(link=>link.addEventListener('click',()=>{
  trackEvent('directions_click',{application:link.dataset.navigationApp});
  dialog.close();
 }));
 share?.addEventListener('click',async()=>{
  if(typeof navigator.share!=='function')return;
  try{
   await navigator.share({title:'Checkup Auto · Les Mureaux',text:'1E rue Niépce, 78130 Les Mureaux',url:'https://www.google.com/maps/dir/?api=1&destination=48.980120%2C1.890251&travelmode=driving'});
   trackEvent('directions_click',{application:'share'});
   dialog.close();
  }catch(error){if(error?.name!=='AbortError')console.warn('Partage de l’itinéraire indisponible',error)}
 });
}
initDirectionsPicker();
