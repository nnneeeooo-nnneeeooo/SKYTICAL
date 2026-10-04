(() => {
  const picker = document.querySelector('[data-briefing-picker]');
  if (!picker) return;

  const range = picker.querySelector('[data-briefing-range]');
  const status = picker.querySelector('[data-briefing-status]');
  const periodButtons = [...picker.querySelectorAll('[data-period]')];
  const selected = Number(range.value);
  const editionNames = periodButtons.map((button) => button.textContent.trim());
  const dateParts = (picker.dataset.date || '').split('-').map(Number);
  const date = new Date(Date.UTC(dateParts[0], dateParts[1] - 1, dateParts[2], 12));
  const dateLabel = new Intl.DateTimeFormat(
    picker.dataset.language === 'zh' ? 'zh-TW' : 'en-US',
    { year: 'numeric', month: 'long', day: 'numeric', timeZone: 'UTC' },
  ).format(date);
  const dateOutput = picker.querySelector('[data-briefing-date]');
  if (dateOutput && dateParts.length === 3 && dateParts.every(Number.isFinite)) {
    dateOutput.textContent = dateLabel;
  }

  function go(url) {
    if (url) window.location.assign(url);
  }

  function setPreview(index) {
    const button = periodButtons[index];
    if (!button) return;
    const periodName = editionNames[index];
    range.setAttribute('aria-valuetext', `${periodName}，${dateLabel}`);
    picker.style.setProperty(
      '--briefing-sky',
      ['#192941', '#318fce', '#192941'][index],
    );
  }

  range.addEventListener('input', () => {
    const index = Number(range.value);
    if (periodButtons[index]) setPreview(index);
  });

  range.addEventListener('change', () => {
    const index = Number(range.value);
    const button = periodButtons[index];
    if (index === selected) {
      status.textContent = '';
      setPreview(selected);
      return;
    }
    if (!button || button.disabled || !button.dataset.url) {
      range.value = String(selected);
      setPreview(selected);
      status.textContent = picker.dataset.unavailable || '';
      return;
    }
    go(button.dataset.url);
  });

  periodButtons.forEach((button) => {
    button.addEventListener('click', () => {
      if (Number(button.dataset.period) !== selected) go(button.dataset.url);
    });
  });

  picker.querySelectorAll('[data-day]').forEach((button) => {
    button.addEventListener('click', () => go(button.dataset.url));
  });

  document.querySelectorAll('.briefing-page img[data-fallback]').forEach((image) => {
    const useFallback = () => {
      if (image.dataset.fallbackTried === 'true') return;
      image.dataset.fallbackTried = 'true';
      image.alt = 'SKYTICAL';
      const credit = image.closest('.briefing-story')?.querySelector('.briefing-image-credit');
      if (credit) credit.hidden = true;
      const fallback = new URL(image.dataset.fallback, document.baseURI).href;
      if (image.src !== fallback) image.src = fallback;
    };
    image.addEventListener('error', useFallback);
    if (image.complete && image.naturalWidth === 0) useFallback();
  });
})();
