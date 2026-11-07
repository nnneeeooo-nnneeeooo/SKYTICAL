const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
let property = '123456789', lastCall, fetched;
const ctx = vm.createContext({Date,JSON,Set,Number,Error,
  PropertiesService:{getScriptProperties:()=>({getProperty:()=>property})},
  AnalyticsData:{Properties:{runReport:(body,name)=>{lastCall={body,name};return {rows:[{metricValues:[{value:'12'}]}]};}}},
  UrlFetchApp:{fetch:(url,options)=>{fetched={url,options};return {getResponseCode:()=>200,getContentText:()=>'<html data-traffic-transport="apps-script"></html>'};}},
  HtmlService:{createHtmlOutput:html=>({html,setTitle(){return this;},addMetaTag(){return this;}})}
});
vm.runInContext(fs.readFileSync(path.join(__dirname,'../apps/traffic-session/Code.gs'),'utf8'),ctx);
const body={dateRanges:[{startDate:'2026-01-01',endDate:'2026-01-07'}],metrics:[{name:'sessions'}],dimensions:[{name:'date'}],orderBys:[{dimension:{dimensionName:'date'}}],limit:366};
assert.equal(ctx.runTrafficReport(body).rows[0].metricValues[0].value,'12');
assert.equal(lastCall.name,'properties/123456789');
for(const bad of [
  {...body,property:'properties/999999999'}, {...body,metrics:[{name:'totalRevenue'}]},
  {...body,dateRanges:[{startDate:'2026-02-29',endDate:'2026-03-01'}]},
  {...body,dateRanges:[{startDate:'2025-01-01',endDate:'2026-01-02'}]},
  {...body,limit:100000}, {...body,dimensionFilter:{filter:{fieldName:'other'}}}
]) assert.throws(()=>ctx.runTrafficReport(bad));
property='';assert.throws(()=>ctx.runTrafficReport(body),/GA4_PROPERTY_ID/);
assert.match(ctx.doGet().html,/apps-script/);
assert.equal(fetched.url,'https://skytical.tech/assets/traffic-dashboard-app.html');
assert.equal(fetched.options.followRedirects,false);
assert.equal(fetched.options.headers.Authorization,undefined,'no Google credential may be sent to the static site');
const manifest=JSON.parse(fs.readFileSync(path.join(__dirname,'../apps/traffic-session/appsscript.json'),'utf8'));
assert.deepEqual(manifest.webapp,{executeAs:'USER_DEPLOYING',access:'MYSELF'});
assert.equal(manifest.oauthScopes.length,2);
assert.equal(manifest.oauthScopes.includes('https://www.googleapis.com/auth/analytics.readonly'),true);
console.log('test_traffic_session: owner-only deployment, fixed property, bounded readonly reports, token-free UI fetch OK');
