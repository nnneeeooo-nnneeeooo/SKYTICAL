/* Capability URL opens the editor; GitHub still enforces repository writes. */
(async () => {
  "use strict";
  const $ = id => document.getElementById(id);
  const core = globalThis.SkyticalAdmin;
  const base = document.body.dataset.adminBase;
  const repository = 'nnneeeooo-nnneeeooo/SKYTICAL';
  const branch = 'main';
  const frame = {contentDocument:document,contentWindow:window};
  Object.defineProperty(frame,'src',{set:value=>location.assign(value)});
  const slug = document.body.dataset.adminRoute.match(/\/admin\/([a-f0-9]{64})\//)?.[1];
  if (!slug) return;
  const vaultDigest = await crypto.subtle.digest('SHA-256',new TextEncoder().encode(slug));
  const vaultId = [...new Uint8Array(vaultDigest)].map(value=>value.toString(16).padStart(2,'0')).join('');
  const vault = `skytical-admin-pat-v1:${vaultId}`;
  let token = '', original = null, record = null, uploaded = null, dirty = false, busy = false;
  let manifest = {};
  let draftTimer = null, draftRevision = 0, savedRevision = 0, pending = null, imageBusy = false;
  const say = message => { $('status').textContent = message; };
  const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
  const bytesToBase64 = bytes => {
    let binary = '';
    for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
    return btoa(binary);
  };
  const decode = text => new TextDecoder().decode(Uint8Array.from(atob(text.replace(/\s/g, '')), c => c.charCodeAt(0)));
  async function vaultKey() {
    const material = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(`skytical-admin-encryption-v1:${slug}`));
    return crypto.subtle.importKey('raw', material, 'AES-GCM', false, ['encrypt', 'decrypt']);
  }
  async function remember() {
    const iv = crypto.getRandomValues(new Uint8Array(12));
    const cipher = await crypto.subtle.encrypt({name:'AES-GCM', iv}, await vaultKey(), new TextEncoder().encode(token));
    localStorage.setItem(vault, JSON.stringify({iv:[...iv], cipher:[...new Uint8Array(cipher)]}));
  }
  const draftKey = id => `${vault}:draft:${id}`;
  async function saveDraft() {
    if (!original || !record || !dirty) return;
    const revision = ++draftRevision;
    const id = record.id;
    const value = {original, record, fields:getFields(), uploaded:uploaded ? {path:uploaded.path,data:uploaded.data} : null, savedAt:new Date().toISOString()};
    try {
      const iv = crypto.getRandomValues(new Uint8Array(12));
      const cipher = await crypto.subtle.encrypt({name:'AES-GCM',iv}, await vaultKey(), new TextEncoder().encode(JSON.stringify(value)));
      if (revision !== draftRevision || id !== record.id) return;
      localStorage.setItem(draftKey(id), JSON.stringify({iv:[...iv],cipher:bytesToBase64(new Uint8Array(cipher))}));
      savedRevision = revision;
      $('draft-state').textContent = `草稿已自動儲存於此瀏覽器（${new Date().toLocaleTimeString('zh-TW')}），尚未發布。`;
    } catch (_) {
      $('draft-state').textContent = '草稿無法儲存：瀏覽器空間不足或禁止儲存。請勿關閉頁面。';
    }
  }
  function queueDraft() {
    dirty = true;
    draftRevision++;
    $('draft-state').textContent = '正在儲存草稿…';
    clearTimeout(draftTimer);
    draftTimer = setTimeout(saveDraft, 400);
  }
  async function restoreDraft() {
    const stored = localStorage.getItem(draftKey(record.id));
    if (!stored) return;
    const envelope = JSON.parse(stored);
    const ciphertext = Array.isArray(envelope.cipher) ? new Uint8Array(envelope.cipher) : Uint8Array.from(atob(envelope.cipher), c => c.charCodeAt(0));
    const clear = await crypto.subtle.decrypt({name:'AES-GCM',iv:new Uint8Array(envelope.iv)}, await vaultKey(), ciphertext);
    const draft = JSON.parse(new TextDecoder().decode(clear));
    if (draft.original?.id !== record.id || draft.record?.path !== record.path) throw new Error('草稿與文章不符。');
    const stale = JSON.stringify(draft.original) !== JSON.stringify(original);
    original = draft.original;
    for (const [id,value] of Object.entries(draft.fields)) {
      if (!$(id) || !Object.hasOwn(getFields(), id)) continue;
      if (id === 'remove-image') $(id).checked = value; else $(id).value = value;
    }
    uploaded = draft.uploaded;
    if (uploaded) uploaded.preview = `data:image/jpeg;base64,${uploaded.data}`;
    dirty = true; draftRevision++; savedRevision = draftRevision;
    $('draft-state').textContent = stale
      ? '已還原私人草稿，但正式文章已變更。發布將阻擋覆寫；可先複製文字，再捨棄草稿重新編輯。'
      : '已還原此瀏覽器的私人草稿，尚未發布。';
  }
  // Replace this adapter with authenticated server calls when account login is added.
  const transport = {
    async request(path, options = {}) {
      const headers = {Accept:'application/vnd.github+json', 'X-GitHub-Api-Version':'2022-11-28'};
      if (token) headers.Authorization = `Bearer ${token}`;
      if (options.body) headers['Content-Type'] = 'application/json';
      const response = await fetch(`https://api.github.com/repos/${repository}${path}`, {...options, headers, cache:'no-store'});
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        const error = new Error(`GitHub 操作失敗（${response.status}）：${data.message || '請檢查連線與權限'}`);
        error.status = response.status;
        throw error;
      }
      return data;
    },
    async read(path, ref = branch) {
      const value = await this.request(`/contents/${path}?ref=${encodeURIComponent(ref)}`);
      if (!value.content) throw new Error('文章檔案無法讀取，請確認 Contents 權限與檔案大小。');
      return JSON.parse(decode(value.content));
    },
    async readArticle(ref = branch) {
      const payload = await this.read(record.path, ref);
      let override;
      try {override = await this.read(record.overridePath, ref);}
      catch (error) {if (error.status !== 404) throw error;}
      if (override) {
        if (override.id !== record.id) throw new Error('人工修訂資料不符，已停止讀取。');
        payload.articles = payload.articles.map(article => article.id === record.id ? override : article);
      }
      return payload;
    },
    async publish(edited) {
      let imageSha = null;
      if (uploaded && !getFields()['remove-image']) {
        const blob = await this.request('/git/blobs', {method:'POST', body:JSON.stringify({content:uploaded.data, encoding:'base64'})});
        imageSha = blob.sha;
      }
      for (let attempt = 0; attempt < 3; attempt++) {
        const ref = await this.request(`/git/ref/heads/${branch}`);
        const head = await this.request(`/git/commits/${ref.object.sha}`);
        const payload = await this.readArticle(ref.object.sha);
        const updated = core.replaceArticle(payload, original, edited);
        const tree = [
          {path:record.path, mode:'100644', type:'blob', content:JSON.stringify(updated, null, 2) + '\n'},
          {path:record.overridePath, mode:'100644', type:'blob', content:JSON.stringify(edited, null, 2) + '\n'},
          {path:'.github/deploy-trigger', mode:'100644', type:'blob', content:`Article content update\n${edited.id}\n${edited.updatedUtc}\n`},
        ];
        if (imageSha) tree.push({path:uploaded.path, mode:'100644', type:'blob', sha:imageSha});
        const built = await this.request('/git/trees', {method:'POST', body:JSON.stringify({base_tree:head.tree.sha, tree})});
        const commit = await this.request('/git/commits', {method:'POST', body:JSON.stringify({message:`Update article ${edited.id}`, tree:built.sha, parents:[ref.object.sha]})});
        try {
          await this.request(`/git/refs/heads/${branch}`, {method:'PATCH', body:JSON.stringify({sha:commit.sha, force:false})});
          return commit.sha;
        } catch (error) {
          if (![409, 422].includes(error.status) || attempt === 2) throw error;
        }
      }
    },
  };
  async function verify() {
    const repo = await transport.request('');
    if (!repo.permissions?.admin) throw new Error('請使用此 repository 管理員的 fine-grained PAT。');
  }
  function currentId() {
    try {
      const path = frame.contentWindow.location.pathname;
      if (!path.startsWith(`${base}/`)) return '';
      const match = path.slice(base.length).match(/^\/(?:en\/)?news\/([^/]+)\/(?:index\.html)?$/);
      return match ? decodeURIComponent(match[1]) : '';
    } catch (_) { return ''; }
  }
  function refreshLocation() { for(const id of ['edit','image-mode','publish','discard']) $(id).disabled=busy||!original||!manifest[currentId()]; }
  function getFields() {
    const ids = ['zh-title','zh-summary','zh-body','en-title','en-summary','en-body','published','sort','models','primary-source','sources','image-url','image-subject','image-link','image-credit','image-license','image-kind'];
    const fields = Object.fromEntries(ids.map(id => [id, $(id).value]));
    fields['remove-image'] = $('remove-image').checked;
    return fields;
  }
  function buildEdit() { return core.editArticle(original, getFields(), new Date().toISOString()); }
  function populate(article) {
    for (const lang of ['zh','en']) {
      $(lang+'-title').value = article[lang]?.title || '';
      $(lang+'-summary').value = article[lang]?.summary || '';
      $(lang+'-body').value = (article[lang]?.body || []).join('\n\n');
    }
    $('published').value = core.toTaipei(article.publishedUtc);
    $('sort').value = core.toTaipei(article.sortUtc || article.publishedUtc);
    $('models').value = article.writerModels ? article.writerModels.join('、') : String(article.writer || '').replace(/^[^:]+:/, '');
    $('primary-source').value = article.primarySource || '';
    $('sources').value = (article.sources || []).map(s => `${s.name || s.url} | ${s.url}`).join('\n');
    const image = typeof article.image === 'string' ? {url:article.image} : article.image || {};
    for (const name of ['url','subject','link','credit','license']) $('image-'+name).value = image[name] || '';
    $('image-kind').value = image.kind || 'file_photo';
    $('remove-image').checked = false;
    $('upload').value = '';
    uploaded = null;
    dirty = false;
  }
  async function waitForDeployment(edited, sha, publicId) {
    const url = `${base}/${edited.availableLanguages.includes('zh') ? '' : 'en/'}news/${encodeURIComponent(publicId)}/`;
    const deadline = Date.now() + 10 * 60000;
    while (Date.now() < deadline) {
      await sleep(10000);
      try {
        const response = await fetch(`${url}?admin-revision=${encodeURIComponent(edited.updatedUtc)}`, {cache:'no-store'});
        if (!response.ok) continue;
        const doc = new DOMParser().parseFromString(await response.text(), 'text/html');
        const stamp = doc.querySelector('meta[property="article:modified_time"]')?.content;
        if (Math.floor(new Date(stamp).getTime()/1000) === Math.floor(new Date(edited.updatedUtc).getTime()/1000)) {
          say(`已確認正式網站上線。Commit：${sha.slice(0,7)}`);
          frame.src = `${url}?v=${sha}`;
          return;
        }
      } catch (_) { /* A transient network error is not a confirmed deployment. */ }
    }
    say(`修改已提交（${sha.slice(0,7)}），尚未確認上線。請到 GitHub Actions 檢查本次部署。`);
  }
  $('connection').onclick = () => $('connection-dialog').showModal();
  document.querySelectorAll('[data-close]').forEach(button => button.onclick = () => button.closest('dialog').close());
  $('connection-form').onsubmit = async event => {
    event.preventDefault();
    const previous = token;
    token = $('pat').value.trim();
    try {
      if (!/^github_pat_[A-Za-z0-9_]+$/.test(token)) throw new Error('請輸入 fine-grained GitHub PAT。');
      await verify();
      try { await remember(); say('GitHub 已連線，憑證已加密記住。'); }
      catch (_) { say('GitHub 已連線；瀏覽器拒絕保存憑證，關閉頁面後需要重新設定。'); }
      $('pat').value = '';
      $('connection-dialog').close();
    } catch (error) {token = previous; say(error.message);}
  };
  $('forget').onclick = () => {
    token = ''; $('pat').value = '';
    try { localStorage.removeItem(vault); } catch (_) { /* Nothing persisted. */ }
    say('發布連線已清除。');
  };
  let editMode = 'text', loadingArticle = false;
  function inlineField(element, field, label, kind = 'text', update = null) {
    if (!element) return;
    element.dataset.adminInline = field;
    element.dataset.adminKind = kind;
    element.setAttribute('aria-label', label);
    element.title = `${label}：點擊編輯，Enter 儲存草稿`;
    element.spellcheck = false;
    element.addEventListener('input', () => {
      if (update) update(element.innerText); else $(field).value = element.innerText.trim();
      queueDraft();
    });
    element.addEventListener('paste', event => {
      event.preventDefault();
      const selection = window.getSelection();
      if (!selection.rangeCount) return;
      const range = selection.getRangeAt(0);range.deleteContents();
      const node = document.createTextNode(event.clipboardData.getData('text/plain'));
      range.insertNode(node);range.setStartAfter(node);range.collapse(true);selection.removeAllRanges();selection.addRange(range);
      element.dispatchEvent(new Event('input',{bubbles:true}));
    });
    element.addEventListener('keydown', event => {
      if(event.isComposing || event.keyCode === 229) return;
      if(event.key === 'Enter' && !event.shiftKey && !event.ctrlKey && !event.metaKey) {
        event.preventDefault();element.blur();clearTimeout(draftTimer);saveDraft();
      }
    });
    element.addEventListener('click', event => {if(element.isContentEditable)event.preventDefault();});
  }
  function setEditMode(mode) {
    editMode = mode;document.body.dataset.adminEditMode = mode;
    for (const element of document.querySelectorAll('[data-admin-inline]')) element.contentEditable = element.dataset.adminKind === mode && !busy ? 'plaintext-only' : 'false';
    for (const input of document.querySelectorAll('[data-admin-input]')) input.disabled = busy || input.dataset.adminKind !== mode;
    $('edit').setAttribute('aria-pressed',String(mode === 'text'));
    $('image-mode').setAttribute('aria-pressed',String(mode === 'image'));
  }
  function extraField(container, field, label, kind='text') {
    const line=document.createElement('div');line.className='admin-inline-extra';line.dataset.adminKind=kind;
    const name=document.createElement('small');name.textContent=label+'：';
    const value=document.createElement('span');value.textContent=$(field).value;
    line.append(name,value);container.append(line);inlineField(value,field,label,kind);return value;
  }
  function mountInline() {
    const article = document.querySelector('.article-page');
    if (!article || !original) return;
    article.querySelectorAll('.admin-inline-extra,.admin-picture-tools').forEach(element=>element.remove());
    const lang=document.documentElement.lang.startsWith('en')?'en':'zh';
    const title=article.querySelector('.article-title');title.textContent=$(lang+'-title').value;
    inlineField(title,lang+'-title','文章標題');
    const summary=document.createElement('div');summary.className='admin-inline-extra';title.after(summary);extraField(summary,lang+'-summary','文章摘要');
    const body=article.querySelector('[data-article-body]');
    const paragraphs=$(lang+'-body').value.split(/\n\s*\n/).filter(Boolean).map(text=>{const p=document.createElement('p');p.textContent=text;return p;});
    body.replaceChildren(...paragraphs);
    for(const p of paragraphs) inlineField(p,lang+'-body','文章內文','text',()=>{$(lang+'-body').value=[...body.querySelectorAll('p')].map(row=>row.innerText.trim()).join('\n\n');});
    const meta=article.querySelector('.article-meta');
    const published=meta.querySelector('time');
    if(published) {
      published.replaceChildren();const label=document.createElement('span');label.textContent='刊登（臺北）：';published.append(label);
      const input=document.createElement('input');input.type='datetime-local';input.value=$('published').value;input.dataset.adminInput='published';input.dataset.adminKind='text';input.setAttribute('aria-label','文章刊登時間（臺北）');published.append(input);
      input.oninput=()=>{$('published').value=input.value;queueDraft();};input.onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();input.blur();saveDraft();}};
    }
    const sort=document.createElement('span');sort.className='admin-inline-extra';sort.textContent='排序（臺北）：';meta.append(sort);
    const sortInput=document.createElement('input');sortInput.type='datetime-local';sortInput.value=$('sort').value;sortInput.dataset.adminInput='sort';sortInput.dataset.adminKind='text';sortInput.setAttribute('aria-label','文章排序時間（臺北）');sort.append(sortInput);sortInput.oninput=()=>{$('sort').value=sortInput.value;queueDraft();};sortInput.onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();sortInput.blur();saveDraft();}};
    const primaryLine=[...meta.children].find(element=>/主要來源|Main source/i.test(element.textContent) && !element.classList.contains('admin-inline-extra'));
    if(primaryLine){primaryLine.replaceChildren();const label=document.createElement('span');label.textContent='主要來源：';const value=document.createElement('span');value.textContent=$('primary-source').value;primaryLine.append(label,value);inlineField(value,'primary-source','主要來源');}
    else extraField(meta,'primary-source','主要來源');
    const sources=article.querySelector('.article-sources');
    sources.querySelectorAll('.article-source-row').forEach(row=>row.remove());
    const sourceLines=$('sources').value.split('\n').filter(Boolean);
    const syncSources=()=>{$('sources').value=[...sources.querySelectorAll('[data-admin-source]')].map(row=>`${row.querySelector('[data-source-name]').innerText.trim()} | ${row.querySelector('[data-source-url]').innerText.trim()}`).join('\n');};
    for(const [i,line] of sourceLines.entries()) {
      const sep=line.indexOf('|');const row=document.createElement('div');row.className='article-source-row';row.dataset.adminSource=String(i);
      const name=document.createElement('span');name.dataset.sourceName='true';name.textContent=line.slice(0,sep).trim();
      const url=document.createElement('span');url.dataset.sourceUrl='true';url.textContent=line.slice(sep+1).trim();
      row.append(name,url);sources.append(row);inlineField(name,'sources','文章來源名稱','text',syncSources);inlineField(url,'sources','文章來源網址','text',syncSources);
    }
    const modelNote=sources.querySelector(':scope > div:not(.article-source-row):not(.admin-inline-extra) > span');
    if(modelNote){modelNote.textContent=$('models').value;inlineField(modelNote,'models','模型署名');}
    else extraField(sources,'models','模型署名');
    const figure=article.querySelector('figure');figure.classList.add('admin-picture');
    const img=figure.querySelector('img');img.src=$('remove-image').checked?`${base}/assets/skytical-social.png`:uploaded?.preview||$('image-url').value||`${base}/assets/skytical-social.png`;
    const tools=document.createElement('div');tools.className='admin-picture-tools';tools.dataset.adminKind='image';
    const upload=document.createElement('button');upload.type='button';upload.textContent='上傳配圖';upload.onclick=()=>$('upload').click();
    const remove=document.createElement('button');remove.type='button';remove.textContent='移除圖片';remove.onclick=()=>{$('remove-image').checked=true;queueDraft();mountInline();};tools.append(upload,remove);figure.append(tools);
    let caption=figure.querySelector('figcaption');if(!caption){caption=document.createElement('figcaption');figure.append(caption);}caption.replaceChildren();
    for(const [field,label] of [['image-subject','圖片說明'],['image-credit','攝影／來源署名'],['image-link','圖片來源網址'],['image-license','授權說明']])extraField(caption,field,label,'image');
    const typeLine=document.createElement('label');typeLine.className='admin-inline-extra';typeLine.dataset.adminKind='image';typeLine.textContent='圖片性質：';
    const select=$('image-kind').cloneNode(true);select.removeAttribute('id');select.dataset.adminInput='image-kind';select.dataset.adminKind='image';select.value=$('image-kind').value;select.onchange=()=>{$('image-kind').value=select.value;queueDraft();};typeLine.append(select);caption.append(typeLine);
    setEditMode(editMode);
  }
  async function loadArticle() {
    if(loadingArticle || !manifest[currentId()]) return;
    loadingArticle=true;
    try {
      record=manifest[currentId()];
      const payload=await transport.readArticle();
      const rows=payload.articles.filter(a=>a.id===record.id);
      if(rows.length!==1)throw new Error('文章資料已變更，請重新整理。');
      original=rows[0];populate(original);
      try{await restoreDraft();}catch(_){$('draft-state').textContent='草稿無法還原，請檢查瀏覽器儲存設定。';}
      mountInline();refreshLocation();say('直接點擊文章上的半透明框編輯；Enter 儲存草稿，Ctrl+S／⌘S 確認送出。');
    }catch(error){say(error.message);}finally{loadingArticle=false;}
  }
  $('edit').onclick=()=>setEditMode('text');
  $('image-mode').onclick=()=>setEditMode('image');
  $('publish').onclick=requestSubmit;
  $('discard').onclick=()=>{
    if(!record||!window.confirm('確定捨棄這篇尚未發布的草稿？'))return;
    clearTimeout(draftTimer);draftRevision++;
    try{localStorage.removeItem(draftKey(record.id));}catch(_){say('無法清除草稿。');return;}
    dirty=false;location.reload();
  };
  $('exit-admin').onclick=async()=>{await saveDraft();sessionStorage.setItem('skytical-admin-route-v1-disabled','1');sessionStorage.removeItem('skytical-admin-route-v1');location.reload();};
  $('upload').onchange = async () => {
    imageBusy = true;
    $('publish').disabled = true;
    $('preview').disabled = true;
    try {
      const file = $('upload').files[0];
      if (!file) return;
      if (!['image/jpeg','image/png','image/webp'].includes(file.type) || file.size > 8*1024*1024) throw new Error('圖片須為 JPG、PNG 或 WebP，且不超過 8 MB。');
      const bitmap = await createImageBitmap(file);
      const scale = Math.min(1, 2400 / Math.max(bitmap.width, bitmap.height));
      const canvas = document.createElement('canvas');
      canvas.width = Math.max(1, Math.round(bitmap.width*scale)); canvas.height = Math.max(1, Math.round(bitmap.height*scale));
      const context = canvas.getContext('2d');
      context.fillStyle = '#fff'; context.fillRect(0,0,canvas.width,canvas.height); context.drawImage(bitmap,0,0,canvas.width,canvas.height); bitmap.close();
      const preview = canvas.toDataURL('image/jpeg', .88);
      const filename = `editorial-${crypto.randomUUID()}.jpg`;
      uploaded = {path:`static/${filename}`, data:preview.split(',')[1], preview};
      $('image-url').value = `${location.origin}${base}/assets/${filename}`;
      $('remove-image').checked = false;
      $('editor-state').textContent = '圖片已準備，發布時才會上傳。';
      queueDraft();mountInline();say('配圖已加入草稿，請直接在圖片下方編寫來源。');
    } catch (error) { say(error.message); }
    finally { imageBusy = false; $('publish').disabled = busy; $('preview').disabled = busy; }
  };
  async function requestSubmit() {
    if (busy || imageBusy || !original) return;
    clearTimeout(draftTimer);
    await saveDraft();
    try {
      pending = buildEdit();
      const items = [];
      const add = (label,before,after) => {
        if ((before == null && after == null) || JSON.stringify(before) === JSON.stringify(after)) return;
        const section = document.createElement('section');
        const heading = document.createElement('h3'); heading.textContent = label;
        const detail = document.createElement('pre');
        const format = value => Array.isArray(value) ? value.join('\n\n') : typeof value === 'object' ? JSON.stringify(value,null,2) : String(value || '（無）');
        detail.textContent = `修改前\n${format(before)}\n\n修改後\n${format(after)}`;
        section.append(heading,detail); items.push(section);
      };
      for (const lang of ['zh','en']) for (const [field,label] of [['title','標題'],['summary','摘要'],['body','內文']]) add(`${lang === 'zh' ? '中文' : '英文'}${label}`,original[lang]?.[field],pending[lang][field]);
      add('刊登時間（臺北）', core.toTaipei(original.publishedUtc), core.toTaipei(pending.publishedUtc));
      add('排序時間（臺北）', core.toTaipei(original.sortUtc || original.publishedUtc), core.toTaipei(pending.sortUtc));
      add('模型署名', original.writerModels || original.writer, pending.writerModels);
      add('主要來源',original.primarySource,pending.primarySource); add('文章來源',original.sources,pending.sources);
      add('圖片與來源',original.image,pending.image);
      $('changes').replaceChildren(...items);
      if (uploaded && !getFields()['remove-image']) {const img=document.createElement('img');img.src=uploaded.preview;img.alt=pending.image.subject;img.className='confirm-image';$('changes').append(img);}
      $('confirm-state').textContent = '請確認上述變更；送出後將開始部署。';
      $('confirm-dialog').showModal();
    } catch(error) {say(error.message);}
  }
  $('editor-form').onsubmit = event => {event.preventDefault(); requestSubmit();};
  $('cancel-submit').onclick = () => {$('confirm-dialog').close();};
  $('confirm-dialog').addEventListener('cancel', event => {event.preventDefault(); $('cancel-submit').click();});
  $('confirm-submit').onclick = async () => {
    if (busy || !pending) return;
    if (!token) {$('confirm-state').textContent='尚未設定發布連線。請返回文章，再設定一次發布連線；草稿會保留。';return;}
    const edited = pending;
    busy = true;setEditMode(editMode); $('fields').disabled = true; $('publish').disabled = true; $('preview').disabled = true; refreshLocation();
    $('confirm-submit').disabled=true; $('cancel-submit').disabled=true;
    try {
      await verify();
      $('confirm-state').textContent = '正在提交修改…';
      const publicId = currentId();
      const sha = await transport.publish(edited);
      clearTimeout(draftTimer); draftRevision++;
      try {localStorage.removeItem(draftKey(record.id));} catch (_) { /* Published data is authoritative. */ }
      original = edited; uploaded = null; dirty = false;
      $('confirm-dialog').close();
      say(`已提交 ${sha.slice(0,7)}，等待正式網站部署…`);
      await waitForDeployment(edited, sha, publicId);
    } catch(error) {$('confirm-state').textContent = error.message; say(error.message);}
    finally {busy = false; $('fields').disabled = false; $('publish').disabled = false; $('preview').disabled = false; $('confirm-submit').disabled=false; $('cancel-submit').disabled=false; setEditMode(editMode);refreshLocation();}
  };
  function shortcut(event) {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {
      event.preventDefault();
      if ($('confirm-dialog').open || busy) return;
      if (original && original.id === manifest[currentId()]?.id) requestSubmit();
      else {say('請先開啟文章並編輯，再按 Ctrl+S／⌘S 確認送出。');}
    }
  }
  document.addEventListener('keydown', shortcut);
  document.addEventListener('click', async event => {
    const link=event.target.closest('a[href]');
    if(!link || link.isContentEditable || !dirty || event.ctrlKey || event.metaKey || link.target==='_blank' || link.origin!==location.origin || link.hash && link.pathname===location.pathname)return;
    event.preventDefault();clearTimeout(draftTimer);await saveDraft();location.assign(link.href);
  });
  window.addEventListener('beforeunload', event => {if((dirty && savedRevision !== draftRevision) || busy) {event.preventDefault(); event.returnValue = '';}});
  try {
    const stored = localStorage.getItem(vault);
    if (stored) {
      const envelope = JSON.parse(stored);
      token = new TextDecoder().decode(await crypto.subtle.decrypt({name:'AES-GCM',iv:new Uint8Array(envelope.iv)}, await vaultKey(), new Uint8Array(envelope.cipher)));
      await verify(); say('GitHub 已自動連線。');
    }
  } catch (_) {token = ''; say('已保存的發布連線無法使用，請重新設定。');}
  try {manifest = await (await fetch(document.body.dataset.adminRoute+'articles.json', {cache:'no-store'})).json(); refreshLocation();await loadArticle();if(!original)say('管理模式已啟用，開啟任一篇新聞即可直接編輯。');}
  catch (_) {say('無法載入文章索引，請重新整理。');}
})();
