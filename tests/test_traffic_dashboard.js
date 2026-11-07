/* Offline regression checks: no Google account, browser package or credentials. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
class Element {
  constructor() { this.value=''; this.textContent=''; this.children=[]; this.attrs={}; this.style={}; this.events={}; this.hidden=false; this.classList={toggle(){}}; }
  setAttribute(k,v) { this.attrs[k]=String(v); }
  appendChild(el) { this.children.push(el); return el; }
  append(...els) { this.children.push(...els); }
  replaceChildren(...els) { this.children=els; }
  querySelectorAll() { return []; }
  getBoundingClientRect() { return {width:760,left:0}; }
  addEventListener(name,fn) { this.events[name]=fn; }
  focus() { this.focused=true; }
}
const elements=new Map();
const element=id=>{if(!elements.has(id)) elements.set(id,new Element());return elements.get(id);};
element('trend-metric').value='sessions';
class FixedDate extends Date {
  constructor(...args) { super(...(args.length?args:['2026-11-07T18:30:00Z'])); }
  static now() { return new FixedDate().getTime(); }
}
const context=vm.createContext({
  Date:FixedDate,Intl,URL,URLSearchParams,AbortController,console,setTimeout,clearTimeout,setInterval(){},
  location:{href:'https://example.test/?v=existing',search:''},history:{replaceState(){}},
  localStorage:{getItem(){return '';},setItem(){}},window:{addEventListener(){}},
  document:{getElementById:element,createElement:()=>new Element(),createElementNS:()=>new Element(),querySelectorAll:()=>[]}
});
let code=fs.readFileSync(path.join(__dirname,'../static/traffic-dashboard.js'),'utf8');
// Expose the closure only in this isolated context; deployed code has no test API.
code=code.replace(/\}\)\(\);\s*$/,`globalThis.qa={today,rangeError,normalizeTrend,safePath,refresh,
  configure(value){days=value;revision++;accessToken='offline-fixture';tokenExpires=Date.now()+60000;},
  expire(){tokenExpires=0;},getSnapshot(){return snapshot;}};})();`);
vm.runInContext(code,context);
const {qa}=context;
assert.equal(qa.today(),'2026-11-08','Taiwan calendar must be independent of host timezone');
assert.equal(qa.rangeError('2024-02-29','2025-02-28'),'');
assert.match(qa.rangeError('2024-02-29','2025-03-01'),/366/);
assert.match(qa.rangeError('2025-02-29','2025-03-01'),/完整/);
assert.match(qa.rangeError('2026-11-09','2026-11-09'),/今天/);
assert.match(qa.rangeError('2026-11-08','2026-11-07'),/晚於/);
const rows=qa.normalizeTrend({rows:[{dimensionValues:[{value:'20260228'}],metricValues:[{value:'5'},{value:'12'},{value:'4'}]},
  {dimensionValues:[{value:'20260302'}],metricValues:[{value:'2'},{value:'3'},{value:'2'}]}]},{start:'2026-02-28',end:'2026-03-02'});
assert.equal(rows.length,3);assert.equal(rows[1].date,'2026-03-01');assert.equal(rows[1].sessions,0);
assert.equal(rows.reduce((sum,r)=>sum+r.sessions,0),7);
for(const unsafe of ['https://evil.test/','//evil.test/','/m/private/','/%6d/private/','/en/u/private/','/%zz']) assert.equal(qa.safePath(unsafe),null,unsafe);
assert.equal(qa.safePath('/news/example/?secret=omitted#fragment'),'/news/example/');
function report(values,dimensions){return {rows:[{metricValues:values.map(value=>({value:String(value)})),dimensionValues:(dimensions||[]).map(value=>({value}))}]};}
let calls=[],release,blocked=true,fail=false;
const waitForOld=new Promise(resolve=>{release=resolve;});
context.fetch=async function(url,opts){
  const body=JSON.parse(opts.body);calls.push(body);
  if(blocked) await waitForOld;
  if(fail) return {ok:false,status:503,json:async()=>({})};
  const name=body.dimensions&&body.dimensions[0].name;
  const response=name==='date'?{rows:[]}:name==='sessionSourceMedium'?report([3],['google / organic']):name==='pagePath'?report([8],['/']):body.dimensionFilter?report([1]):report([2,3,8,0.5]);
  return {ok:true,json:async()=>response};
};
(async function(){
  element('property-id').value='123456789';qa.configure(7);
  const first=qa.refresh();qa.configure(90);await qa.refresh();
  blocked=false;release();await first;
  for(let i=0;i<20&&!qa.getSnapshot();i++) await new Promise(resolve=>setTimeout(resolve,0));
  const snapshot=qa.getSnapshot();
  assert.equal(calls.length,10,'new range queues one fresh request set');
  assert.equal(snapshot.range.start,'2026-08-11','stale response cannot overwrite new range');
  assert.equal(snapshot.range.end,'2026-11-08');assert.equal(calls[1].limit,366);
  assert.equal(calls[6].metrics.length,3);
  assert.equal(element('kpi-views').textContent,'8');assert.equal(element('kpi-engagement').textContent,'50.0%');
  assert.equal(element('daily-rows').children.length,90);
  assert.equal(element('trend-plot').attrs['aria-label'].includes('最高 0'),true);
  fail=true;await qa.refresh();assert.equal(qa.getSnapshot(),snapshot);
  assert.match(element('error').textContent,/保留上次/);
  const before=calls.length;qa.expire();await qa.refresh();assert.equal(calls.length,before);
  assert.match(element('error').textContent,/授權已過期/);assert.equal(element('refresh').disabled,true);
  // Google-managed sessions restore without browser OAuth, including after the
  // legacy token expiry boundary and when no client/property is saved locally.
  elements.clear(); element('trend-metric').value='sessions';
  let rpcCalls=0;
  const scriptRun={withSuccessHandler(resolve){return {withFailureHandler(){return {runTrafficReport(body){
    rpcCalls++;
    const name=body.dimensions&&body.dimensions[0].name;
    resolve(name==='date'?{rows:[]}:name==='sessionSourceMedium'?report([3],['google / organic']):name==='pagePath'?report([8],['/']):body.dimensionFilter?report([1]):report([2,3,8,0.5]));
  }}}};}};
  const serverContext=vm.createContext({...context,
    document:{...context.document,documentElement:{dataset:{trafficTransport:'apps-script'}}},
    window:{addEventListener(){},google:{script:{run:scriptRun,url:{getLocation(callback){callback({parameter:{days:'28'}});}}}}},
    fetch(){throw Error('server sessions must not request browser access tokens');}
  });
  vm.runInContext(code,serverContext);
  for(let i=0;i<20&&!serverContext.qa.getSnapshot();i++) await new Promise(resolve=>setTimeout(resolve,0));
  assert.equal(element('setup').hidden,true);assert.equal(element('auth-action').hidden,true);
  assert.equal(element('kpi-views').textContent,'8');assert.equal(element('daily-rows').children.length,28);
  assert.equal(element('error').textContent,'');assert.equal(rpcCalls,5);
  serverContext.qa.expire();await serverContext.qa.refresh();assert.equal(rpcCalls,10);
  assert.equal(element('refresh').disabled,false);
  console.log('test_traffic_dashboard.js: dates, gaps, privacy, metrics, request races, errors and expiry OK');
})().catch(error=>{console.error(error);process.exitCode=1;});
