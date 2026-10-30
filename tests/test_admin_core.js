"use strict";
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const path = require('node:path');
vm.runInThisContext(fs.readFileSync(path.join(__dirname, '../static/admin-core.js'), 'utf8'));
const core = globalThis.SkyticalAdmin;
const original = {
  id:'a-test', publishedUtc:'2026-10-29T01:00Z', writer:'provider:actual-model', revision:4,
  zh:{title:'原標題', summary:'原摘要', body:['原內文']}, en:{title:'',summary:'',body:[]},
  sources:[{url:'https://example.com/story'}], opaque:{preserve:true},
  image:{url:'https://example.com/old.jpg', subject:'原圖', sourceCaption:'原圖證據'},
};
const fields = {
  'zh-title':'新標題', 'zh-summary':'新摘要', 'zh-body':'第一段\n\n第二段',
  'en-title':'', 'en-summary':'', 'en-body':'', published:'2026-10-29T09:00', sort:'2026-10-29T10:00',
  models:'Model A、Model B', 'image-url':'https://example.com/new.jpg', 'image-subject':'新圖',
  'image-link':'https://example.com/source', 'image-credit':'攝影者', 'image-license':'授權',
  'image-kind':'file_photo', 'remove-image':false,
};
const edited = core.editArticle(original, fields, '2026-10-30T00:00:00.000Z');
assert.equal(edited.publishedUtc, '2026-10-29T01:00:00.000Z');
assert.equal(edited.sortUtc, '2026-10-29T02:00:00.000Z');
assert.equal(edited.writer, original.writer);
assert.deepEqual(edited.writerModels, ['Model A','Model B']);
assert.equal(edited.editorialLocked, true);
assert.equal(edited.editorialImageLocked, true);
assert.equal(edited.revision, 5);
assert.deepEqual(edited.opaque, {preserve:true});
assert.equal(edited.image.sourceCaption, undefined);
assert.equal(original.zh.title, '原標題');
assert.equal(core.editArticle(original, {...fields,'remove-image':true}, edited.updatedUtc).image, null);
assert.throws(() => core.toUtc('2026-02-30T09:00'));
assert.throws(() => core.editArticle(original, {...fields,'image-url':'javascript:alert(1)'}, edited.updatedUtc));
assert.throws(() => core.editArticle(original, {...fields,'zh-body':''}, edited.updatedUtc));
const sourced = core.editArticle({...original,sources:[{name:'來源',url:'https://example.com/story',factIds:['F1']}]}, {...fields,'primary-source':'新來源',sources:'來源 | https://example.com/story'}, edited.updatedUtc);
assert.equal(sourced.primarySource,'新來源');
assert.deepEqual(sourced.sources[0].factIds,['F1']);
assert.throws(() => core.editArticle(original,{...fields,sources:'錯誤格式'},edited.updatedUtc));
const sibling = {id:'a-other', untouched:true};
const payload = {articles:[original, sibling], batchMetadata:'keep'};
const result = core.replaceArticle(payload, original, edited);
assert.deepEqual(result.articles[1], sibling);
assert.equal(result.batchMetadata, 'keep');
assert.throws(() => core.replaceArticle({articles:[{...original,revision:6}]}, original, edited), /已被其他程序更新/);
assert.throws(() => core.replaceArticle({articles:[]}, original, edited));
console.log('PASS admin edit contract: Taipei time, metadata, image, lock and conflict protection');
