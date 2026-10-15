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

test('seven-day window shows only genuinely open Mercure days, never Sunday',()=>{
 const {sandbox,root,caption}=fixture();
 const slot={time:'09:00',price:80,basePrice:80};
 const mk=(date,available=true,slots=[slot],weekday='weekday')=>({date,weekday,day:date.slice(-2),month:'octobre',available,slots});
 sandbox.renderPlanner({startDate:'2026-10-15',days:[
   mk('2026-10-15',false),mk('2026-10-16',true,[]),
   mk('2026-10-17'),mk('2026-10-18',true,[slot],'lundi'),
   mk('2026-10-19'),mk('2026-10-20'),mk('2026-10-21'),mk('2026-10-22'),
 ]});
 assert.equal(root.children.length,4);
 assert.match(caption.textContent,/15 octobre.*21 octobre/);
 assert.deepEqual(root.children.map(d=>d.children[1].children[0].dataset.date),
   ['2026-10-17','2026-10-19','2026-10-20','2026-10-21']);
 assert.equal(root.children.some(d=>d.className.includes('unavailable')),false);
});

test('one available date is one card rather than seven empty placeholders',()=>{
 const {sandbox,root}=fixture();
 sandbox.renderPlanner({startDate:'2026-10-15',days:[{
  date:'2026-10-17',weekday:'samedi',day:'17',month:'octobre',available:true,
  slots:[{time:'10:20',price:80,basePrice:80}]}]});
 assert.equal(root.children.length,1);
 assert.equal(root.children[0].children[1].children[0].dataset.time,'10:20');
});

test('Sunday, closed Mercure days, and dates without slots render none',()=>{
 const {sandbox,root}=fixture(),slot={time:'09:00',price:80,basePrice:80};
 sandbox.renderPlanner({startDate:'2026-10-18',days:[
  {date:'2026-10-18',weekday:'lundi',day:'18',month:'octobre',available:true,slots:[slot]},
  {date:'2026-10-19',weekday:'lundi',day:'19',month:'octobre',available:false,slots:[slot]},
  {date:'2026-10-20',weekday:'mardi',day:'20',month:'octobre',available:true,slots:[]}
 ]});
 assert.equal(root.children.length,0);
 assert.match(root.innerHTML,/Aucun créneau disponible/);
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

test('responsive CSS keeps adaptive booking columns and native iOS date taps',()=>{
  assert.match(html,/id="bookingDateTrigger"[^>]*type="button"|type="button" id="bookingDateTrigger"/);
  assert.match(html,/<\/button><input id="bookingStartDate" type="date"/);
  assert.match(html,/id="bookingWeekCaption"/);
  assert.match(html,/booking-week-desktop\.css\?v=/);
  assert.ok(css.includes('grid-template-columns:repeat(var(--booking-visible-days,6),minmax(204px,1fr))!important'));
  assert.match(css,/@media\(min-width:761px\)/);
  assert.match(css, /@media\(max-width:760px\) and \(pointer:coarse\)/);
  assert.match(css,/pointer-events:auto!important/);
  assert.match(css,/pointer-events:none!important/);
});
