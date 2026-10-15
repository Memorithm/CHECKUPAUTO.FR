import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createContext,runInContext} from 'node:vm';

const source=readFileSync(new URL('../app.js',import.meta.url),'utf8');
const html=readFileSync(new URL('../index.html',import.meta.url),'utf8');
const css=readFileSync(new URL('./booking-week-desktop.css',import.meta.url),'utf8');

function fixture() {
  const nodes=new Map();
  function element(tag='div') {
    return {
      tagName:tag,children:[],dataset:{},attrs:{},listeners:{},disabled:false,innerHTML:'',
      textContent:'',value:'',className:'',
      classList:{add(){},remove(){},toggle(){},contains(){return false}},
      appendChild(child){this.children.push(child);return child},
      replaceChildren(){this.children=[]},
      setAttribute(key,value){this.attrs[key]=value},
      removeAttribute(key){delete this.attrs[key]},
      addEventListener(name,cb){this.listeners[name]=cb},
      querySelector(){return null},after(){},focus(){},
    };
  }
  for(const id of ['bookingDays','bookingStartDate','bookingDateTrigger','bookingWeekCaption',
      'bookingSelection','bookingSelectionKicker','bookingSelectionLabel','bookingSelectionPrice',
      'bookingContinue','service','bookingRefresh','bookingLiveStatus','price',
      'promoPreviewBanner'])nodes.set('#'+id,element());
  const date=nodes.get('#bookingStartDate');date.value='2026-10-15';
  const service=nodes.get('#service');service.value='technical';
  const caption=nodes.get('#bookingWeekCaption');
  const root=nodes.get('#bookingDays');
  const document={
    querySelector(selector){return nodes.get(selector)||null},
    querySelectorAll(){return []},createElement:element,
    addEventListener(){},getElementById(){return null},body:element('body'),
    documentElement:element('html'),cookie:'',
  };
  const window={cyberCheckConfig:{}};
  const sandbox={
    document,window,location:{search:'',pathname:'/',href:'https://test.checkupauto.fr/'},
    navigator:{userAgent:''},localStorage:{getItem(){return null},setItem(){}},
    sessionStorage:{getItem(){return null},setItem(){}},matchMedia(){return {matches:false,addEventListener(){}}},
    fetch:()=>new Promise(()=>{}),setTimeout:()=>0,clearTimeout(){},setInterval:()=>0,
    requestAnimationFrame:()=>0,IntersectionObserver:function(){return {observe(){},disconnect(){}}},
    URLSearchParams,console,Intl,Date,Math,JSON,Number,String,Object,Array,Promise,
    encodeURIComponent,history:{replaceState(){}},addEventListener(){},
    CSS:{supports:()=>false},
  };
  sandbox.self=sandbox;sandbox.globalThis=sandbox;
  Object.assign(window,sandbox);
  const context=createContext(sandbox);
  runInContext(source,context);
  return {sandbox,nodes,root,date,caption,context};
}

test('seven actual calendar dates render in one contiguous week with no fabricated slots',()=>{
  const {sandbox,root,caption}=fixture();
  const mk=(date,weekday,day,month)=>({date,weekday,day:String(day),month,available:true,
     slots:[{time:'09:00',price:80,basePrice:80}]});
  sandbox.renderPlanner({startDate:'2026-10-15',days:[
    mk('2026-10-17','samedi',17,'octobre'),
    mk('2026-10-19','lundi',19,'octobre'),
    mk('2026-10-20','mardi',20,'octobre'),
    mk('2026-10-21','mercredi',21,'octobre'),
  ]});
  assert.equal(root.children.length,7);
  assert.match(caption.textContent,/15 octobre.*21 octobre/);
  const d=root.children;
  for(let i=0;i<7;i++)assert.equal(d[i].children[1].tagName,'div');
  assert.equal(d[0].className.includes('unavailable'),true);
  assert.equal(d[1].className.includes('unavailable'),true);
  assert.equal(d[3].className.includes('unavailable'),true);
  assert.equal(d[2].children[1].children.length,1);
  assert.equal(d[2].children[1].children[0].dataset.date,'2026-10-17');
  for(const i of [0,1,3]) {
    assert.equal(d[i].children[1].children.length,1);
    assert.equal(d[i].children[1].children[0].tagName,'p');
    assert.equal(d[i].children[1].children[0].textContent,'Aucun créneau disponible');
  }
});

test('provider day with nonpadded ISO still maps to the correct full week',()=>{
  const {sandbox,root}=fixture();
  sandbox.renderPlanner({startDate:'2026-10-15',days:[{
     date:'2026-10-17',weekday:'samedi',day:'17',month:'octobre',
     available:true,slots:[{time:'10:20',price:80,basePrice:80}]
  }]});
  assert.equal(root.children.length,7);
  assert.equal(root.children[2].children[1].children[0].dataset.time,'10:20');
});

test('a clickable calendar trigger calls showPicker in the user gesture on desktop',()=>{
  const {sandbox,nodes,date,context}=fixture();
  let calls=0;date.showPicker=()=>calls++;
  runInContext("plannerState.bounds={businessDate:'2026-10-15',horizonEnd:'2026-11-20'}",context);
  sandbox.initPlanner();
  const trigger=nodes.get('#bookingDateTrigger');
  assert.equal(typeof trigger.listeners.click,'function');
  trigger.listeners.click();
  assert.equal(calls,1);
  assert.equal(date.min,'2026-10-15');
  assert.equal(date.max,'2026-11-20');
});

test('calendar fallback remains actionable without showPicker or when showPicker throws',()=>{
  const {sandbox,date}=fixture();
  let focus=0,clicks=0;
  date.focus=()=>focus++;
  date.click=()=>clicks++;
  sandbox.openBookingDatePicker(date);
  assert.equal(focus,1);assert.equal(clicks,1);
  date.showPicker=()=>{throw new Error('not supported')};
  sandbox.openBookingDatePicker(date);
  assert.equal(focus,2);assert.equal(clicks,2);
  date.disabled=true;
  sandbox.openBookingDatePicker(date);
  assert.equal(clicks,2);
});

test('markup and responsive CSS guarantee one seven-day desktop row and native iOS date taps',()=>{
  assert.match(html,/id="bookingDateTrigger"[^>]*type="button"|type="button" id="bookingDateTrigger"/);
  assert.match(html,/<\/button><input id="bookingStartDate" type="date"/);
  assert.match(html,/id="bookingWeekCaption"/);
  assert.match(html,/booking-week-desktop\.css\?v=/);
  assert.match(css,/grid-template-columns:repeat\(7,minmax\(204px,1fr\)\)!important/);
  assert.match(css,/@media\(min-width:761px\)/);
  assert.match(css, /@media\(max-width:760px\) and \(pointer:coarse\)/);
  assert.match(css,/pointer-events:auto!important/);
  assert.match(css,/pointer-events:none!important/);
});
