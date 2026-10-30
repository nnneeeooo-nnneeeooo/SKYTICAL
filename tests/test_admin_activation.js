'use strict';
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../static/admin-activate.js'),'utf8');
async function main(){
  for(const route of [null,'https://attacker.example/admin/','/admin/short/']){
    let fetched=false;
    await vm.runInNewContext(source,{
      document:{currentScript:{dataset:{base:'/SKYTICAL'}}},
      sessionStorage:{getItem:()=>route},location:{pathname:'/SKYTICAL/news/a-test/'},
      fetch:()=>{fetched=true;throw new Error('must remain inactive');},
    });
    assert.equal(fetched,false,'ordinary visitors must not load admin components');
  }
  const route='/SKYTICAL/admin/'+'a'.repeat(64)+'/';
  let stored=null,destination=null;
  await vm.runInNewContext(source,{
    document:{currentScript:{dataset:{base:'/SKYTICAL'}}},
    sessionStorage:{setItem:(name,value)=>{stored=value;},removeItem(){}},
    location:{pathname:route,replace:value=>{destination=value;}},
  });
  assert.equal(stored,route);
  assert.equal(destination,'/SKYTICAL/','activation returns to the native site');
  for(const failure of ['http','content','network']){
    const banners=[];
    const element=()=>({style:{},setAttribute(){},append(child){this.link=child;}});
    await vm.runInNewContext(source,{
      document:{currentScript:{dataset:{base:'/SKYTICAL'}},getElementById:()=>null,createElement:element,body:{prepend:value=>banners.push(value)}},
      sessionStorage:{getItem:name=>name==='skytical-admin-route-v1'?route:null,setItem(){}},location:{pathname:'/SKYTICAL/'},
      fetch:async()=>{if(failure==='network')throw new Error('offline');return{ok:failure!=='http',text:async()=>''};},
      DOMParser:class{parseFromString(){return{body:{dataset:{}}};}},
    });
    assert.equal(banners.length,1,'activation failures must be visible rather than silently showing the public site');
    assert.equal(banners[0].link.href,'/SKYTICAL/admin/');
  }
  console.log('PASS admin activation: no public UI mutation, validated private entry and native URLs');
}
main().catch(error=>{console.error(error);process.exitCode=1;});
