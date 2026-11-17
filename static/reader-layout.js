/* Expanded mobile controls and a portrait fitted within the original note footprint. */
(() => {
  const root = document.documentElement;
  const header = document.querySelector('.header-search-row');
  if (!header) return;
  const menu = header.querySelector('.mobile-more');
  if (!menu) return;
  const panel = menu.querySelector('.mobile-more-panel');
  const nav = document.querySelector('.site-nav');
  const media = matchMedia('(max-width:720px)');
  const labels = new Map();
  function update() {
    root.classList.toggle('expanded-mobile-header', media.matches);
    if (!media.matches) {
      menu.append(panel);
      for (const [link, text] of labels) link.textContent = text;
      return;
    }
    menu.open = false;
    header.append(panel);
    const socials = document.querySelector('.header-social-links');
    header.append(socials);
    panel.querySelectorAll('.seg').forEach(seg => {
      seg.classList.toggle('inline-theme-controls', !!seg.querySelector('[data-set-theme]'));
    });
    for (const link of panel.querySelectorAll(':scope > a')) {
      if (!labels.has(link)) labels.set(link, link.textContent);
      if (root.lang.startsWith('en')) {
        if (/\/about\/$/.test(link.pathname)) link.textContent = 'About';
        if (/\/team\/$/.test(link.pathname)) link.textContent = 'Team';
      }
      nav.append(link);
    }
    const zones = panel.querySelector('.mobile-timezones');
    if (zones) document.querySelector('.utility-row').append(zones);
  }
  media.addEventListener('change', update);
  update();

  const dialog = document.querySelector('#site-update-notice');
  if (!dialog) return;
  const note = dialog.querySelector('.station-note');
  if (!note) return;
  const originalPhoto = note.querySelector('.station-portrait img');
  const photoWindow = document.createElement('span');
  photoWindow.className = 'station-photo-window';
  originalPhoto.before(photoWindow);
  photoWindow.append(originalPhoto);
  let lastFit = '';
  function fitPortrait() {
    if (!dialog.open || note.hidden) return;
    const fitKey = [note.clientWidth, root.dataset.theme, document.fonts.status].join(':');
    if (lastFit === fitKey) return;
    note.classList.remove('station-photo-fit');
    const rect = note.getBoundingClientRect();
    const figure = note.querySelector('.station-portrait');
    const photo = figure.querySelector('img');
    const text = note.querySelector('[data-station-message]');
    const heading = note.querySelector('h3');
    const oldWidth = figure.getBoundingClientRect().width;
    const oldHeight = photo.getBoundingClientRect().height;
    const limit = rect.bottom - parseFloat(getComputedStyle(note).paddingBottom);
    note.style.setProperty('--note-height', rect.height + 'px');
    note.dataset.originalHeight = String(rect.height);
    note.classList.add('station-photo-fit');
    let best = {width:oldWidth,height:oldHeight,area:0};
    const maxWidth = Math.min(rect.width*.42, oldWidth*1.8);
    const maxHeight = Math.min(rect.height-50, oldHeight*1.8);
    for (let width=Math.floor(maxWidth); width>=oldWidth; width-=2) {
      for (let height=Math.floor(Math.min(maxHeight,width*1.3)); height>=Math.max(oldHeight,width*.87); height-=3) {
        if (width*height<=best.area) continue;
        note.style.setProperty('--photo-width',width+'px');
        note.style.setProperty('--photo-height',height+'px');
        note.style.setProperty('--photo-lift',-(heading.getBoundingClientRect().height+parseFloat(getComputedStyle(heading).marginBottom))+'px');
        if (Math.max(text.getBoundingClientRect().bottom,figure.getBoundingClientRect().bottom)<=limit+.5) best={width,height,area:width*height};
      }
    }
    note.style.setProperty('--photo-width',best.width+'px');
    note.style.setProperty('--photo-height',best.height+'px');
    note.style.setProperty('--photo-lift',-(heading.getBoundingClientRect().height+parseFloat(getComputedStyle(heading).marginBottom))+'px');
    lastFit = fitKey;
  }
  let frame;
  function queueFit(){cancelAnimationFrame(frame);frame=requestAnimationFrame(fitPortrait);}
  new MutationObserver(queueFit).observe(dialog,{attributes:true,attributeFilter:['open']});
  window.addEventListener('resize',queueFit);
  document.fonts.ready.then(queueFit);
  document.fonts.addEventListener('loadingdone',()=>{lastFit='';queueFit();});
})();
