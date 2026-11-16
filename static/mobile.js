/* Reuse the native controls and URLs; restore their positions on wider screens. */
(function () {
  'use strict';
  var root = document.documentElement;
  var media = window.matchMedia('(max-width: 720px)');
  var header = document.querySelector('.header-search-row');
  var toggle = document.querySelector('.mobile-search-toggle');
  var menu = document.querySelector('.mobile-more');
  var panel = menu && menu.querySelector('.mobile-more-panel');
  if (!header || !toggle || !panel) return;
  var relocations = [];
  var home = document.querySelector('[data-mobile-label]');
  var homeLabel = home && home.textContent;
  var active = false;
  var timezone = document.createElement('div');
  timezone.className = 'mobile-timezones';
  var help = document.querySelector('.search-help');
  var helpPanel = document.createElement('details');
  helpPanel.className = 'mobile-search-help';
  var helpSummary = document.createElement('summary');
  helpSummary.textContent = root.lang.indexOf('zh') === 0 ? '搜尋方式與範例' : 'Search tips and examples';
  helpPanel.appendChild(helpSummary);

  function move(node, destination) {
    if (!node) return;
    var marker = document.createComment('mobile-control-position');
    node.parentNode.insertBefore(marker, node);
    relocations.push({node: node, marker: marker});
    destination.appendChild(node);
  }
  function searchState(open) {
    header.classList.toggle('is-search-open', open);
    toggle.setAttribute('aria-expanded', String(open));
    toggle.setAttribute('aria-label', open ? toggle.dataset.closeLabel : toggle.dataset.openLabel);
  }
  function updateLayout() {
    var next = media.matches && root.dataset.theme !== '8bit';
    if (next === active) return;
    active = next;
    root.classList.toggle('mobile-refresh', active);
    if (active) {
      document.querySelectorAll('.utility-row .seg').forEach(function (el) { move(el, panel); });
      document.querySelectorAll('.site-nav a').forEach(function (link) {
        if (/\/(about|team|sources)\/$/.test(link.pathname)) move(link, panel);
      });
      move(header.querySelector('.header-social-links'), panel);
      document.querySelectorAll('.utility-row .utility-clock').forEach(function (el) { move(el, timezone); });
      panel.appendChild(timezone);
      if (home) home.textContent = home.dataset.mobileLabel;
      if (help) {
        help.parentNode.insertBefore(helpPanel, help);
        move(help, helpPanel);
        move(document.querySelector('.search-help-note'), helpPanel);
      }
      searchState(!!document.getElementById('news-search-app'));
    } else {
      menu.open = false;
      searchState(false);
      relocations.forEach(function (entry) { entry.marker.replaceWith(entry.node); });
      relocations = [];
      timezone.remove();
      helpPanel.remove();
      if (home) home.textContent = homeLabel;
    }
  }
  toggle.addEventListener('click', function () {
    var open = !header.classList.contains('is-search-open');
    searchState(open);
    menu.open = false;
    var input = document.getElementById('news-search-input');
    if (open && input) input.focus();
  });
  menu.addEventListener('toggle', function () { if (menu.open && active) searchState(false); });
  document.addEventListener('click', function (event) {
    if (menu.open && !menu.contains(event.target)) menu.open = false;
  });
  document.addEventListener('keydown', function (event) {
    if (event.key !== 'Escape' || !active) return;
    if (menu.open) { menu.open = false; menu.querySelector('summary').focus(); }
    else if (header.classList.contains('is-search-open')) { searchState(false); toggle.focus(); }
  });
  media.addEventListener('change', updateLayout);
  new MutationObserver(updateLayout).observe(root, {attributes: true, attributeFilter: ['data-theme']});
  updateLayout();

  var buttons = Array.prototype.slice.call(document.querySelectorAll('[data-filter-cat]'));
  var headings = Array.prototype.slice.call(document.querySelectorAll('.feed-day-heading'));
  var rows = Array.prototype.slice.call(document.querySelectorAll('.home-feed-row'));
  function updateGroups() {
    buttons.forEach(function (button) { button.setAttribute('aria-pressed', String(button.classList.contains('active'))); });
    headings.forEach(function (heading) {
      heading.hidden = !rows.some(function (row) {
        return row.dataset.feedDay === heading.dataset.feedDay && !row.classList.contains('is-hidden');
      });
    });
  }
  buttons.forEach(function (button) { button.addEventListener('click', updateGroups); });
  updateGroups();
})();
