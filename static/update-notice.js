/* One reminder per origin every three hours; shared by both site languages. */
(function () {
  'use strict';
  const INTERVAL = 3 * 60 * 60 * 1000;
  const KEY = 'skytical:update-notice:last-shown:v1';
  function isDue(last, now) {
    return last === null || !Number.isFinite(last) || last <= 0 || last > now || now - last >= INTERVAL;
  }
  if (typeof module !== 'undefined' && module.exports) module.exports = {isDue, INTERVAL, KEY};
  if (typeof document === 'undefined') return;
  const dialog = document.getElementById('site-update-notice');
  const source = document.getElementById('site-update-data');
  if (!dialog || !source || typeof dialog.showModal !== 'function') return;
  let data;
  try { data = JSON.parse(source.textContent); } catch (_) { return; }
  if (!Array.isArray(data.items) || !data.ui) return;
  let memory = null;
  let opener = null;
  let wingTimer;
  const wing = dialog.querySelector('[data-notice-wing]');
  function playWing() {
    if (!wing || window.matchMedia('(prefers-reduced-motion: reduce)').matches || document.documentElement.dataset.theme === '8bit') return;
    wing.classList.remove('is-playing');
    void wing.offsetWidth;
    wing.classList.add('is-playing');
    clearTimeout(wingTimer);
    wingTimer = setTimeout(() => wing.classList.remove('is-playing'), 2400);
  }
  wing?.addEventListener('click', playWing);
  wing?.addEventListener('pointerenter', event => {if (event.pointerType === 'mouse' && !wing.classList.contains('is-playing')) playWing();});
  function readLast() {
    try {const raw = localStorage.getItem(KEY); if (raw !== null) return Number(raw);} catch (_) {}
    return memory;
  }
  function showIfDue() {
    if (dialog.open || document.querySelector('dialog[open]') || !isDue(readLast(), Date.now())) return false;
    opener = document.activeElement;
    try {dialog.showModal();} catch (_) {return false;}
    memory = Date.now();
    try {localStorage.setItem(KEY, String(memory));} catch (_) {}
    requestAnimationFrame(playWing);
    return true;
  }
  function checkEntry() {
    // The origin-wide lock prevents simultaneous tabs from both showing it.
    if (navigator.locks?.request) navigator.locks.request('skytical-update-notice', showIfDue).catch(showIfDue);
    else showIfDue();
  }
  for (const item of data.items) {
    if (!item || typeof item.title !== 'string' || typeof item.copy !== 'string') continue;
    const article = document.createElement('article'); article.className = 'update';
    const heading = document.createElement('div'); heading.className = 'update-heading';
    if (/^\d{4}-\d{2}-\d{2}$/.test(item.date)) {
      const date = document.createElement('time'); date.className = 'update-date'; date.dateTime = item.date; date.textContent = item.date.slice(5).replace('-', '/'); heading.append(date);
    }
    const title = document.createElement('h3'); title.textContent = item.title; heading.append(title);
    const copy = document.createElement('p'); copy.textContent = item.copy.startsWith(item.title + '，') ? item.copy.slice(item.title.length + 1) : item.copy;
    article.append(heading, copy); dialog.querySelector('[data-notice-items]').append(article);
  }
  if (data.station && typeof data.station.message === 'string' && data.station.message.trim()) {
    const message = data.station.message;
    const target = dialog.querySelector('[data-station-message]');
    const parts = [];
    const tokens = [
      {at: message.indexOf('neo'), text: 'neo', kind: 'name'},
      {at: message.indexOf(data.ui.emailLabel), text: data.ui.emailLabel, kind: 'email'}
    ].filter(token => token.at >= 0).sort((a, b) => a.at - b.at);
    let position = 0;
    for (const token of tokens) {
      if (token.at < position) continue;
      parts.push(document.createTextNode(message.slice(position, token.at)));
      if (token.kind === 'name') {
        const name = document.createElement('span'); name.className = 'neo-signature';
        for (const letter of 'neo') {const glyph = document.createElement('span'); glyph.textContent = letter; name.append(glyph);}
        parts.push(name);
      } else if (/^[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}$/i.test(data.station.email || '')) {
        const link = document.createElement('a'); link.href = 'mailto:' + data.station.email; link.textContent = token.text; parts.push(link);
      } else parts.push(document.createTextNode(token.text));
      position = token.at + token.text.length;
    }
    parts.push(document.createTextNode(message.slice(position)));
    target.replaceChildren(...parts);
    dialog.querySelector('.station-note').hidden = false;
  }
  if (!dialog.querySelector('.update') && dialog.querySelector('.station-note').hidden) return;
  dialog.querySelectorAll('[data-notice-close]').forEach(button => button.addEventListener('click', () => dialog.close()));
  dialog.addEventListener('close', () => {
    clearTimeout(wingTimer);
    wing?.classList.remove('is-playing');
    if (opener instanceof HTMLElement && opener !== document.body && opener.isConnected) opener.focus({preventScroll: true});
    else document.querySelector('.brand-link')?.focus({preventScroll: true});
  });
  document.addEventListener('close', event => {if (event.target !== dialog) checkEntry();}, true);
  window.addEventListener('pageshow', event => {if (event.persisted) checkEntry();});
  checkEntry();
}());
