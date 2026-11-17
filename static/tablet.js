/* Portrait tablets reuse the phone content with their approved full header. */
(() => {
  const tablet = matchMedia('(min-width: 721px) and (max-width: 1100px) and (orientation: portrait)');
  const root = document.documentElement;
  const header = document.querySelector('.header-search-row');
  const toggle = document.querySelector('.nav-toggle');
  const nav = document.querySelector('.site-nav');
  const utility = document.querySelector('.utility-bar');
  if (!header || !toggle || !nav || !utility) return;
  const marker = document.createComment('tablet-original-menu-position');
  const navMarker = document.createComment('tablet-original-navigation-position');
  toggle.before(marker);
  nav.before(navMarker);
  let active = false;
  let previousNav;
  function update() {
    const next = tablet.matches;
    if (next === active) return;
    active = next;
    root.classList.toggle('tablet-portrait', active);
    if (active) {
      previousNav = { open: nav.classList.contains('is-open'), expanded: toggle.getAttribute('aria-expanded'), icon: toggle.querySelector('.nav-toggle-icon').textContent };
      root.classList.add('mobile-refresh');
      header.append(toggle);
      utility.after(nav);
      nav.classList.add('is-open');
      toggle.setAttribute('aria-expanded', 'true');
    } else {
      marker.after(toggle);
      navMarker.after(nav);
      nav.classList.toggle('is-open', previousNav.open);
      toggle.setAttribute('aria-expanded', previousNav.expanded);
      toggle.querySelector('.nav-toggle-icon').textContent = previousNav.icon;
      if (!matchMedia('(max-width: 720px)').matches) root.classList.remove('mobile-refresh');
    }
  }
  tablet.addEventListener('change', update);
  new MutationObserver(update).observe(root, { attributes: true, attributeFilter: ['data-theme'] });
  update();
})();
