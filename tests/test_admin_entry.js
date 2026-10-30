'use strict';
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
const {webcrypto,createHash}=require('node:crypto');
const source=fs.readFileSync(path.join(__dirname,'../static/admin-entry.js'),'utf8');
const testKey='test-only-key-not-a-real-secret-123456789';
function harness(hash='',{ok=true,marker=true,storageError=false}={}){
  const state={textContent:'等待私人連結。'},events={},stored={},requests=[];
  let destination=null;
  const location={hash,pathname:'/SKYTICAL/admin/',replace:value=>{destination=value;}};
  const context={
    document:{currentScript:{dataset:{base:'/SKYTICAL'}},getElementById:()=>state},
    window:{addEventListener:(name,handler)=>{events[name]=handler;}},location,
    history:{replaceState:()=>{location.hash='';}},crypto:webcrypto,TextEncoder,TypeError,
    fetch:async(route,options)=>{requests.push({route,options});return{ok,text:async()=>marker?'private':'public fallback'};},
    DOMParser:class{parseFromString(html){return{body:{dataset:{skyticalAdmin:html==='private'?'true':undefined}}};}},
    sessionStorage:{setItem:(name,value)=>{if(storageError)throw new Error('storage denied');stored[name]=value;}},
  };
  return{context,state,events,stored,requests,location,get destination(){return destination;}};
}
async function main(){
  const first=harness('#'+testKey);
  await vm.runInNewContext(source,first.context);
  assert.equal(first.destination,'/SKYTICAL/');
  assert.equal(first.stored['skytical-admin-route-v1'],'/SKYTICAL/admin/'+createHash('sha256').update(testKey).digest('hex')+'/');
  assert.equal(first.location.hash,'','raw key must be removed from the address');
  assert.ok(!JSON.stringify(first.requests).includes(testKey),'raw key must never be transmitted');
  const later=harness();await vm.runInNewContext(source,later.context);
  assert.equal(later.requests.length,0);
  later.location.hash='#'+testKey;
  await later.events.hashchange();
  assert.equal(later.destination,'/SKYTICAL/','adding a hash to the already-open page must activate');
  for(const options of [{ok:false},{marker:false},{storageError:true}]){
    const failed=harness('#'+testKey,options);await vm.runInNewContext(source,failed.context);
    assert.equal(failed.destination,null);
    assert.notEqual(failed.state.textContent,'等待私人連結。');
    assert.ok(!failed.state.textContent.includes(testKey));
  }
  console.log('PASS admin entry: initial/hashchange activation, validated route, visible failures and no key transmission');
}
main().catch(error=>{console.error(error);process.exitCode=1;});
