"""R-02: consent tied to the tracker list, focus management (real consent.js in a DOM stub)."""
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import compliance_store

ROOT = Path(__file__).resolve().parent
HARNESS = r"""const fs=require('fs'),vm=require('vm');
async function scenario(src,{cookie,version,actions}){
 const doc={cookie:cookie||'',readyState:'complete',activeElement:null};
 const byId={};
 function el(tag){const e={tagName:tag.toUpperCase(),children:[],parent:null,attrs:{},dataset:{},style:{},handlers:{},textContent:'',innerHTML:'',
  setAttribute(k,v){this.attrs[k]=v},getAttribute(k){return this.attrs[k]},
  append(...c){c.forEach(x=>this.appendChild(x))},appendChild(c){c.parent=this;this.children.push(c);if(c.id)byId[c.id]=c;return c},
  remove(){if(this.parent){this.parent.children=this.parent.children.filter(x=>x!==this);this.parent=null}if(this.id&&byId[this.id]===this)delete byId[this.id]},
  addEventListener(t,f){(this.handlers[t]=this.handlers[t]||[]).push(f)},
  focus(){doc.activeElement=this},click(){(this.handlers.click||[]).forEach(f=>f({}))},
  querySelectorAll(sel){const out=[];const m=n=>{if(sel==='button,input,a[href]'&&['BUTTON','INPUT'].includes(n.tagName))return true;if(sel==='input[data-category]'&&n.tagName==='INPUT'&&n.dataset.category)return true;return false};(function w(n){n.children.forEach(c=>{if(m(c))out.push(c);w(c)})})(this);return out}};
  Object.defineProperty(e,'id',{get(){return this._id},set(v){this._id=v;byId[v]=this}});return e}
 const body=el('body');
 const opener=el('button');body.appendChild(opener);opener.focus();
 Object.assign(doc,{body,createElement:el,getElementById:id=>{let n=byId[id];while(n&&n!==body){n=n.parent}return n===body?byId[id]:null},addEventListener(){},contains:n=>{while(n){if(n===body)return true;n=n.parent}return false}});
 const sandbox={document:doc,window:null,fetch:async()=>({ok:true,json:async()=>({consentRequired:true,policyVersion:version})}),CustomEvent:function(t,o){this.type=t;this.detail=o&&o.detail},console,JSON,Object,Array,String,Date,encodeURIComponent,decodeURIComponent};
 sandbox.window=sandbox;sandbox.dispatchEvent=()=>{};
 vm.createContext(sandbox);vm.runInContext(src,sandbox);
 await new Promise(r=>setImmediate(r));await new Promise(r=>setImmediate(r));
 const panel=()=>doc.getElementById('cc-consent-panel');
 const key=(k,shift)=>{let ev={key:k,shiftKey:!!shift,preventDefault(){}};(panel().handlers.keydown||[]).forEach(f=>f(ev))};
 const res={bannerShown:!!panel()};
 if(panel()){const items=panel().querySelectorAll('button,input,a[href]');res.focusInPanel=items.includes(doc.activeElement);}
 for(const a of actions||[]){
  if(a==='escape'){key('Escape');res.afterEscape=!!panel()}
  if(a==='open'){sandbox.CyberCheckConsent.open();res.prefsShown=!!panel();res.prefsFocus=panel().querySelectorAll('button,input,a[href]').includes(doc.activeElement)}
  if(a==='tabwrap'){const items=panel().querySelectorAll('button,input,a[href]');items[items.length-1].focus();key('Tab');res.wrapped=doc.activeElement===items[0]}
  if(a==='refuse'){panel().querySelectorAll('button,input,a[href]')[0].click();res.cookieVersion=JSON.parse(decodeURIComponent(doc.cookie.split('=')[1].split(';')[0])).policyVersion;res.focusRestored=doc.activeElement===opener}
 }
 return res;
}
(async()=>{
 const src=fs.readFileSync(process.argv[2],'utf8');
 const stored=v=>'cc_cookie_consent_v1='+encodeURIComponent(JSON.stringify({version:1,policyVersion:v,categories:{necessary:true}}));
 const out={
  fresh:await scenario(src,{version:'v2',actions:['tabwrap','escape','refuse']}),
  outdated:await scenario(src,{cookie:stored('v1'),version:'v2'}),
  current:await scenario(src,{cookie:stored('v2'),version:'v2',actions:['open','escape']}),
 };
 process.stdout.write(JSON.stringify(out));
})();
"""


class CookiePolicyVersionTest(unittest.TestCase):
    def test_version_changes_when_consent_trackers_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "compliance.sqlite3"
            base = compliance_store.cookie_policy(db)["policyVersion"]
            compliance_store.upsert_cookie({"key": "_audience", "provider": "Exemple", "purpose": "Mesure d'audience",
                                            "category": "analytics", "legalBasis": "consent", "durationDays": 180,
                                            "storageKind": "cookie"}, db)
            first = compliance_store.cookie_policy(db)["policyVersion"]
            self.assertNotEqual(base, first)
            self.assertEqual(compliance_store.cookie_policy(db)["policyVersion"], first)
            compliance_store.upsert_cookie({"key": "_audience", "provider": "Exemple", "purpose": "Mesure d'audience",
                                            "category": "analytics", "legalBasis": "consent", "durationDays": 390,
                                            "storageKind": "cookie"}, db)
            self.assertNotEqual(compliance_store.cookie_policy(db)["policyVersion"], first)


@unittest.skipUnless(shutil.which("node"), "node requis")
class ConsentBannerBehaviourTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "harness.js"
            script.write_text(HARNESS, encoding="utf-8")
            result = subprocess.run(["node", str(script), str(ROOT / "consent.js")], capture_output=True, text=True, timeout=30, check=True)
        cls.results = json.loads(result.stdout)

    def test_first_banner_takes_focus_traps_tab_and_cannot_be_escaped(self):
        fresh = self.results["fresh"]
        self.assertTrue(fresh["bannerShown"])
        self.assertTrue(fresh["focusInPanel"])
        self.assertTrue(fresh["wrapped"])
        self.assertTrue(fresh["afterEscape"], "Escape must not count as a decision on the first banner")

    def test_choice_records_policy_version_and_restores_focus(self):
        self.assertEqual(self.results["fresh"]["cookieVersion"], "v2")
        self.assertTrue(self.results["fresh"]["focusRestored"])

    def test_choice_made_for_another_tracker_list_is_asked_again(self):
        self.assertTrue(self.results["outdated"]["bannerShown"])

    def test_current_choice_is_kept_and_preferences_close_with_escape(self):
        current = self.results["current"]
        self.assertFalse(current["bannerShown"])
        self.assertTrue(current["prefsShown"])
        self.assertTrue(current["prefsFocus"])
        self.assertFalse(current["afterEscape"])


if __name__ == "__main__":
    unittest.main()
