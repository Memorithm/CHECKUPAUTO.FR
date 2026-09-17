const $=s=>document.querySelector(s);
let config=null;
function state(msg,error=false){const e=$('#saveState');e.textContent=msg;e.classList.toggle('error',error)}
function checked(id,v){const e=$(id);if(e)e.checked=!!v}
function value(id,v=''){const e=$(id);if(e)e.value=v??''}
function fill(c){
 config=c;
 checked('#offerEnabled',c.offer.enabled);value('#offerTitle',c.offer.title);value('#offerSubtitle',c.offer.subtitle);value('#offerHeroLine',c.offer.heroLine);value('#offerFinalTitle',c.offer.finalTitle);
 value('#heroKicker',c.hero.kicker);value('#priceTechnical',c.services.technical.price);value('#priceFitted',c.services.fitted.price);value('#pricePollution',c.services.pollution.price);
 value('#phone',c.business.phone);value('#address',c.business.address);value('#bookingUrl',c.business.bookingUrl);
 const a=c.analytics||{};checked('#analyticsEnabled',a.enabled!==false);value('#analyticsRetention',a.retentionDays||180);
 const i=c.incentives||{},ie=i.eligibleServices||{};checked('#incentiveEnabled',i.enabled!==false);value('#incentiveLabel',i.label||'PRIX AVANTAGE');value('#incentiveDefaultDiscount',i.defaultDiscountPercent??0);value('#incentiveMaxDiscount',i.maxDiscountPercent??0);value('#incentiveHorizonDays',i.horizonDays||30);value('#incentiveTimeStart',i.timeStart||'09:00');value('#incentiveTimeEnd',i.timeEnd||'19:00');checked('#incentiveTechnical',ie.technical!==false);checked('#incentiveFitted',ie.fitted!==false);checked('#incentiveShowOriginal',i.showOriginalPrice!==false);checked('#incentiveShowPercent',i.showDiscountPercent!==false);
 const allowed=new Set((i.allowedWeekdays||[1,2,3,4,5,6]).map(Number));document.querySelectorAll('#incentiveWeekdays input').forEach(x=>x.checked=allowed.has(Number(x.value)));
 window.cyberCheckAdminConfig=c;window.dispatchEvent(new CustomEvent('cybercheck-config-loaded',{detail:c}));
 const s=c.seo||{},cr=s.crawlers||{},sd=s.structuredData||{};
 checked('#indexingEnabled',s.indexingEnabled);value('#seoTitle',s.title);value('#seoSiteName',s.siteName);value('#seoDescription',s.description);value('#canonicalUrl',s.canonicalUrl);value('#ogImage',s.ogImage);
 value('#googleVerification',s.googleVerification);value('#searchConsoleProperty',s.searchConsoleProperty);value('#aiSummary',s.aiSummary);
 checked('#crawlerGooglebot',cr.googlebot);checked('#crawlerBingbot',cr.bingbot);checked('#crawlerOaiSearchBot',cr.oaiSearchBot);checked('#crawlerChatgptUser',cr.chatgptUser);checked('#crawlerGptBot',cr.gptBot);
 checked('#crawlerClaudeSearchBot',cr.claudeSearchBot);checked('#crawlerClaudeUser',cr.claudeUser);checked('#crawlerClaudeBot',cr.claudeBot);checked('#crawlerPerplexityBot',cr.perplexityBot);checked('#crawlerPerplexityUser',cr.perplexityUser);checked('#crawlerGoogleExtended',cr.googleExtended);
 value('#structuredBusinessName',sd.businessName);value('#structuredStreet',sd.streetAddress);value('#structuredPostal',sd.postalCode);value('#structuredLocality',sd.locality);value('#structuredCountry',sd.country);value('#structuredPriceRange',sd.priceRange);
 $('#updatedAt').textContent=new Date(c.updatedAt).toLocaleString('fr-FR');
}
async function load(){state('Chargement…');const r=await fetch('/api/admin/config',{cache:'no-store'});if(!r.ok)throw new Error('Impossible de charger la configuration');fill(await r.json());state('Configuration chargée')}
function collect(){
 return{version:4,
  offer:{enabled:$('#offerEnabled').checked,title:$('#offerTitle').value,subtitle:$('#offerSubtitle').value,heroLine:$('#offerHeroLine').value,finalTitle:$('#offerFinalTitle').value},
  business:{phone:$('#phone').value,address:$('#address').value,bookingUrl:$('#bookingUrl').value},
  hero:{kicker:$('#heroKicker').value},
  analytics:{enabled:$('#analyticsEnabled')?.checked!==false,retentionDays:Number($('#analyticsRetention')?.value||180),privacyMode:'cookieless'},
  incentives:{enabled:$('#incentiveEnabled')?.checked!==false,label:$('#incentiveLabel')?.value||'PRIX AVANTAGE',eligibleServices:{technical:$('#incentiveTechnical')?.checked!==false,fitted:$('#incentiveFitted')?.checked!==false},defaultDiscountPercent:Number($('#incentiveDefaultDiscount')?.value||0),maxDiscountPercent:Number($('#incentiveMaxDiscount')?.value||0),horizonDays:Number($('#incentiveHorizonDays')?.value||30),allowedWeekdays:[...document.querySelectorAll('#incentiveWeekdays input:checked')].map(x=>Number(x.value)),timeStart:$('#incentiveTimeStart')?.value||'09:00',timeEnd:$('#incentiveTimeEnd')?.value||'19:00',showOriginalPrice:$('#incentiveShowOriginal')?.checked!==false,showDiscountPercent:$('#incentiveShowPercent')?.checked!==false},
  services:{technical:{label:'Contrôle technique',price:Number($('#priceTechnical').value)},fitted:{label:'Véhicule aménagé',price:Number($('#priceFitted').value)},pollution:{label:'Visite pollution',price:Number($('#pricePollution').value)}},
  seo:{indexingEnabled:$('#indexingEnabled').checked,siteName:$('#seoSiteName').value,title:$('#seoTitle').value,description:$('#seoDescription').value,canonicalUrl:$('#canonicalUrl').value,ogImage:$('#ogImage').value,googleVerification:$('#googleVerification').value,searchConsoleProperty:$('#searchConsoleProperty').value,aiSummary:$('#aiSummary').value,
   structuredData:{businessName:$('#structuredBusinessName').value,streetAddress:$('#structuredStreet').value,postalCode:$('#structuredPostal').value,locality:$('#structuredLocality').value,country:$('#structuredCountry').value,priceRange:$('#structuredPriceRange').value},
   crawlers:{googlebot:$('#crawlerGooglebot').checked,bingbot:$('#crawlerBingbot').checked,oaiSearchBot:$('#crawlerOaiSearchBot').checked,chatgptUser:$('#crawlerChatgptUser').checked,gptBot:$('#crawlerGptBot').checked,claudeSearchBot:$('#crawlerClaudeSearchBot').checked,claudeUser:$('#crawlerClaudeUser').checked,claudeBot:$('#crawlerClaudeBot').checked,perplexityBot:$('#crawlerPerplexityBot').checked,perplexityUser:$('#crawlerPerplexityUser').checked,googleExtended:$('#crawlerGoogleExtended').checked}
  }
 }
}
$('#adminForm').addEventListener('submit',async e=>{e.preventDefault();const b=e.submitter;b.disabled=true;state('Enregistrement…');try{const r=await fetch('/api/admin/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(collect())});const data=await r.json();if(!r.ok||!data.ok)throw new Error(data.error||'Échec de sauvegarde');fill(data.config);state('Sauvegardé — SEO, IA et site public sont à jour')}catch(err){state(err.message,true)}finally{b.disabled=false}});
load().catch(e=>state(e.message,true));
