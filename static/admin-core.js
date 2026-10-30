/* Pure edit contract. A future authenticated API can reuse the same payload. */
globalThis.SkyticalAdmin = (() => {
  "use strict";
  const clone = value => JSON.parse(JSON.stringify(value));
  const toTaipei = value => new Date(new Date(value).getTime() + 8 * 3600000).toISOString().slice(0, 16);
  function toUtc(value) {
    if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(value)) throw new Error("請填寫有效的臺北日期與時間。");
    const date = new Date(`${value}:00+08:00`);
    if (!Number.isFinite(date.getTime()) || toTaipei(date) !== value) throw new Error("日期或時間不存在。");
    return date.toISOString();
  }
  function webUrl(value) {
    if (!value) return "";
    const url = new URL(value);
    if (!['http:', 'https:'].includes(url.protocol)) throw new Error("圖片與來源網址只接受 HTTP／HTTPS。");
    return url.href;
  }
  function editArticle(original, fields, now) {
    const article = clone(original);
    for (const lang of ['zh', 'en']) {
      const before = original[lang] || {};
      const title = fields[`${lang}-title`].trim();
      const body = fields[`${lang}-body`].trim().split(/\n\s*\n/).map(s => s.trim()).filter(Boolean);
      if ((before.title || title || body.length) && (!title || !body.length)) throw new Error(`${lang === 'zh' ? '中文' : '英文'}標題與內文不可留白。`);
      article[lang] = {...before, title, summary: fields[`${lang}-summary`].trim(), body};
    }
    if (!article.zh.title && !article.en.title) throw new Error("至少保留一種語言的文章。");
    article.publishedUtc = toUtc(fields.published);
    article.sortUtc = toUtc(fields.sort);
    const models = [...new Set(fields.models.split(/[、,\n]/).map(s => s.trim()).filter(Boolean))];
    if (models.length > 5 || models.some(s => s.length > 100)) throw new Error("模型署名最多五個，每個最多 100 字。");
    article.writerModels = models;
    if (typeof fields['primary-source'] === 'string') article.primarySource = fields['primary-source'].trim();
    if (typeof fields.sources === 'string') {
      const sources = fields.sources.split('\n').map(s => s.trim()).filter(Boolean).map(line => {
        const separator = line.indexOf('|');
        if (separator < 1) throw new Error('文章來源格式須為「名稱 | 網址」。');
        const name = line.slice(0,separator).trim(), url = webUrl(line.slice(separator+1).trim());
        if (!name || !url) throw new Error('文章來源名稱與網址不可留白。');
        const previous = (original.sources || []).find(source => source.url === url);
        return {...previous, name,url};
      });
      if (!sources.length) throw new Error('請至少保留一個文章來源。');
      article.sources = sources;
    }
    if (fields['remove-image']) article.image = null;
    else {
      const url = webUrl(fields['image-url'].trim());
      if (url && !fields['image-subject'].trim()) throw new Error("請填寫圖片說明。");
      const old = typeof original.image === 'object' && original.image ? original.image : {};
      const same = old.url === url;
      article.image = url ? {
        ...(same ? old : {}), url, subject: fields['image-subject'].trim(),
        description: fields['image-subject'].trim(),
        link: webUrl(fields['image-link'].trim()), credit: fields['image-credit'].trim(),
        license: fields['image-license'].trim(), kind: fields['image-kind'],
        provider: 'manual', curated: true,
      } : null;
    }
    article.editorialLocked = true;
    article.editorialImageLocked = true;
    article.updatedUtc = now;
    article.revision = (Number(original.revision) || 1) + 1;
    article.availableLanguages = ['zh', 'en'].filter(lang => article[lang].title);
    return article;
  }
  function replaceArticle(payload, original, edited) {
    const result = clone(payload);
    const rows = result.articles;
    const matches = Array.isArray(rows) ? rows.filter(a => a.id === original.id) : [];
    if (matches.length !== 1) throw new Error("找不到唯一文章，請重新整理後再編輯。");
    if (JSON.stringify(matches[0]) !== JSON.stringify(original)) throw new Error("文章已被其他程序更新，請重新載入後再編輯；本次尚未覆寫。");
    result.articles = rows.map(a => a.id === original.id ? edited : a);
    return result;
  }
  return {toTaipei, toUtc, webUrl, editArticle, replaceArticle};
})();
