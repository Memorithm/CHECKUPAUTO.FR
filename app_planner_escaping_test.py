"""F-01: planner data from Mercure is escaped before reaching innerHTML (real app.js in a DOM stub)."""
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
HARNESS = r"""const fs=require('fs'),vm=require('vm');
function el(tag){const e={tagName:tag,children:[],dataset:{},classList:{add(){},remove(){},toggle(){}},style:{},attrs:{},
 appendChild(c){this.children.push(c);return c},replaceChildren(){this.children=[]},setAttribute(k,v){this.attrs[k]=v},removeAttribute(){},
 addEventListener(){},querySelector(){return null},querySelectorAll(){return []},after(){},innerHTML:'',textContent:''};return e}
const root=el('div');
const any=new Proxy(function(){},{get:(t,k)=>k===Symbol.toPrimitive?()=>'' :any,apply:()=>any,construct:()=>any});
const document={querySelector:s=>s==='#bookingDays'?root:null,querySelectorAll:()=>[],createElement:el,addEventListener(){},getElementById:()=>null,body:el('body'),documentElement:el('html'),cookie:''};
const sandbox={document,window:{},location:{search:'',pathname:'/',href:'https://x/'},navigator:{userAgent:''},localStorage:{getItem:()=>null,setItem(){}},sessionStorage:{getItem:()=>null,setItem(){}},
 matchMedia:()=>({matches:false,addEventListener(){}}),fetch:()=>new Promise(()=>{}),setTimeout:()=>0,clearTimeout(){},setInterval:()=>0,requestAnimationFrame:()=>0,IntersectionObserver:function(){return {observe(){},disconnect(){}}},
 URLSearchParams,console,Intl,Date,Math,JSON,Number,String,Object,Array,Promise,encodeURIComponent,history:{replaceState(){}},addEventListener(){},CSS:{supports:()=>false}};
sandbox.window=sandbox;sandbox.self=sandbox;sandbox.globalThis=sandbox;
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(process.argv[2],'utf8'),sandbox);
const evil='<img src=x onerror=alert(1)>';
sandbox.renderPlanner({days:[{available:true,date:'2026-10-12',weekday:evil,day:evil,month:evil,slots:[{time:evil,price:70,basePrice:70}]}]});
const out=[];(function walk(n){if(n.innerHTML)out.push(n.innerHTML);(n.children||[]).forEach(walk)})(root);
process.stdout.write(JSON.stringify(out));
"""


@unittest.skipUnless(shutil.which("node"), "node requis")
class AppPlannerEscapingTest(unittest.TestCase):
    def test_availability_fields_are_escaped(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "harness.js"
            script.write_text(HARNESS, encoding="utf-8")
            result = subprocess.run(["node", str(script), str(ROOT / "app.js")], capture_output=True, text=True, timeout=30, check=True)
        fragments = json.loads(result.stdout)
        self.assertGreaterEqual(len(fragments), 2)
        for fragment in fragments:
            self.assertNotIn("<img", fragment)
        self.assertTrue(any("&lt;img src=x onerror=alert(1)&gt;" in fragment for fragment in fragments))


if __name__ == "__main__":
    unittest.main()
