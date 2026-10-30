/* A new tab can inherit mode from an open admin tab without changing its URL. */
(async () => {
  'use strict';
  const base = document.currentScript.dataset.base || '';
  const storage = 'skytical-admin-route-v1';
  const disabled = storage + '-disabled';
  const pattern = new RegExp(`^${base.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')}/admin/[a-f0-9]{64}/$`);
  let channel = null;
  function openChannel() {
    try {return typeof BroadcastChannel === 'function' ? new BroadcastChannel('skytical-admin-tabs-v1:' + base) : null;}
    catch (_) {return null;}
  }
  function discoverRoute() {
    if (!channel) return Promise.resolve(null);
    const id = crypto.randomUUID();
    return new Promise(resolve => {
      const finish = route => {clearTimeout(timer);channel.onmessage=null;resolve(route);};
      const timer = setTimeout(() => finish(null), 1000);
      channel.onmessage = event => {
        const message = event.data;
        if (message?.type === 'offer' && message.id === id
            && typeof message.route === 'string' && pattern.test(message.route)) finish(message.route);
      };
      channel.postMessage({type:'request',id});
    });
  }
  function shareRoute(route) {
    if (!channel) return;
    channel.onmessage = event => {
      const message = event.data;
      if (message?.type !== 'request' || typeof message.id !== 'string') return;
      if (sessionStorage.getItem(disabled) === '1' || sessionStorage.getItem(storage) !== route) return;
      channel.postMessage({type:'offer',id:message.id,route});
    };
  }
  function showFailure(message) {
    const status = document.getElementById('status');
    if (status) {status.textContent=message;return;}
    const banner=document.createElement('aside');banner.id='skytical-admin-activation-error';banner.setAttribute('role','alert');
    banner.style.cssText='position:relative;z-index:10000;padding:14px;background:#fff2cf;color:#382800;font:14px/1.6 system-ui';
    banner.textContent=message+' ';
    const retry=document.createElement('a');retry.href=`${base}/admin/`;retry.textContent='重新開啟管理入口';banner.append(retry);document.body.prepend(banner);
  }
  try {
    if (pattern.test(location.pathname)) {
      sessionStorage.removeItem(disabled);
      sessionStorage.setItem(storage,location.pathname);
      location.replace(`${base}/`);
      return;
    }
    if (sessionStorage.getItem(disabled) === '1') return;
    channel = openChannel();
    let route = sessionStorage.getItem(storage);
    if (!route || !pattern.test(route)) route = await discoverRoute();
    if (!route) {channel?.close();return;}
    sessionStorage.setItem(storage,route);
    shareRoute(route);
    const response = await fetch(route, {cache:'no-store',referrerPolicy:'no-referrer'});
    if (!response.ok) {channel?.close();showFailure('管理模式尚未啟用：私人入口不存在或已更換，請重新使用完整私人連結。');return;}
    const source = new DOMParser().parseFromString(await response.text(),'text/html');
    if (source.body.dataset.skyticalAdmin !== 'true') {channel?.close();showFailure('管理模式尚未啟用：入口內容不完整，請重新開啟私人連結。');return;}
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
      const script = document.createElement('script');script.src=`${base}/assets/${name}?v=admin-tabs1`;script.onload=resolve;script.onerror=reject;document.body.append(script);
    });
  } catch (_) {
    channel?.close();
    showFailure('管理模式載入失敗，請檢查瀏覽器儲存權限或網路，再重新開啟私人入口。');
  }
})();
