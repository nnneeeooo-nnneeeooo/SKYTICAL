/* Public pages stay unchanged unless this tab has opened the private entry. */
(async () => {
  'use strict';
  const base = document.currentScript.dataset.base || '';
  const storage = 'skytical-admin-route-v1';
  const pattern = new RegExp(`^${base.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')}/admin/[a-f0-9]{64}/$`);
  try {
    if (pattern.test(location.pathname)) {
      sessionStorage.setItem(storage,location.pathname);
      location.replace(`${base}/`);
      return;
    }
    const route = sessionStorage.getItem(storage);
    if (!route || !pattern.test(route)) return;
    const response = await fetch(route, {cache:'no-store',referrerPolicy:'no-referrer'});
    if (!response.ok) return;
    const source = new DOMParser().parseFromString(await response.text(),'text/html');
    if (source.body.dataset.skyticalAdmin !== 'true') return;
    document.body.dataset.adminBase = base;
    document.body.dataset.adminRoute = route;
    document.body.classList.add('skytical-admin-active');
    const meta = document.createElement('meta');meta.name='referrer';meta.content='no-referrer';document.head.append(meta);
    const css = document.createElement('link');css.rel='stylesheet';css.href=`${base}/assets/admin.css`;document.head.append(css);
    for (const id of ['admin-controls','connection-dialog','editor','confirm-dialog']) {
      const element = source.getElementById(id);
      if (!element) throw new Error('管理元件缺失');
      if (id === 'admin-controls') document.body.prepend(element);else document.body.append(element);
    }
    for (const name of ['admin-core.js','admin.js']) await new Promise((resolve,reject) => {
      const script = document.createElement('script');script.src=`${base}/assets/${name}`;script.onload=resolve;script.onerror=reject;document.body.append(script);
    });
  } catch (_) {
    const status = document.getElementById('status');
    if (status) status.textContent='管理模式載入失敗，請重新開啟私人入口。';
  }
})();
