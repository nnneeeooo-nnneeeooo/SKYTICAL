'use strict';
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../static/admin-activate.js'),'utf8');
const storage='skytical-admin-route-v1',route='/SKYTICAL/admin/'+'a'.repeat(64)+'/';
const channels=new Set();let sequence=0;
class Channel{
  constructor(name){this.name=name;this.closed=false;channels.add(this);}
  postMessage(data){for(const peer of channels)if(peer!==this&&!peer.closed&&peer.name===this.name)queueMicrotask(()=>{if(!peer.closed)peer.onmessage?.({data:structuredClone(data)});});}
  close(){this.closed=true;channels.delete(this);}
}
function page(initial={},base='/SKYTICAL'){
  const saved=new Map(Object.entries(initial)),requests=[],banners=[];
  let active=false,destination=null;
  const element=()=>({style:{},setAttribute(){},append(child){this.child=child;}});
  const body={dataset:{},classList:{add:()=>{active=true;}},prepend:value=>banners.push(value),append:value=>{if(value.onload)queueMicrotask(value.onload);}};
  const context={
    document:{currentScript:{dataset:{base}},body,head:{append(){}},getElementById:()=>null,createElement:element},
    sessionStorage:{getItem:name=>saved.get(name)||null,setItem:(name,value)=>saved.set(name,value),removeItem:name=>saved.delete(name)},
    location:{pathname:base+'/news/a-child/',replace:value=>{destination=value;}},BroadcastChannel:Channel,
    crypto:{randomUUID:()=>String(++sequence)},setTimeout:(fn,ms)=>setTimeout(fn,Math.min(ms,30)),clearTimeout,
    fetch:async url=>{requests.push(url);return{ok:true,text:async()=>''};},
    DOMParser:class{parseFromString(){return{body:{dataset:{skyticalAdmin:'true'}},getElementById:()=>element()};}},
  };
  return{context,saved,requests,banners,get active(){return active;},get destination(){return destination;},run(){return vm.runInNewContext(source,context);}};
}
function closeAll(){for(const channel of [...channels])channel.close();}
async function main(){
  const leader=page({[storage]:route});await leader.run();assert.equal(leader.active,true);
  // No opener or inherited sessionStorage: the same case as a right-click/noopener tab.
  const child=page();await child.run();
  assert.equal(child.active,true);
  assert.equal(child.saved.get(storage),route);
  assert.deepEqual(child.requests,[route]);
  assert.equal(child.destination,null,'new article tab must keep its native URL');
  const optedOut=page({[storage+'-disabled']:'1'});await optedOut.run();
  assert.equal(optedOut.active,false,'ending mode in a tab must prevent automatic reactivation');
  assert.equal(optedOut.requests.length,0);
  const anotherBase=page({},'/another-site');await anotherBase.run();
  assert.equal(anotherBase.active,false,'do not share mode across site base paths');
  closeAll();
  const ordinary=page();await ordinary.run();
  assert.equal(ordinary.active,false);
  assert.equal(ordinary.requests.length,0,'without an open admin tab, ordinary pages remain unchanged');
  const invalid=page({[storage]:'https://attacker.example/admin/'});await invalid.run();
  assert.equal(invalid.active,false);
  assert.equal(invalid.requests.length,0);
  const exitedLeader=page({[storage]:route});await exitedLeader.run();
  exitedLeader.saved.delete(storage);exitedLeader.saved.set(storage+'-disabled','1');
  const afterExit=page();await afterExit.run();assert.equal(afterExit.active,false,'an exited tab must stop sharing');
  closeAll();
  console.log('PASS admin new tabs: openerless inheritance, native URLs, opt-out, channel scope and no-active-admin fallback');
}
main().catch(error=>{closeAll();console.error(error);process.exitCode=1;});
