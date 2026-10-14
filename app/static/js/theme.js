/* Apply saved or device theme before styles paint. Light stays the default. */
(function () {
  'use strict';
  const key = 'ttbg-theme', media = window.matchMedia('(prefers-color-scheme: dark)');
  const normalize = v => ['light', 'dark', 'system'].includes(v) ? v : 'light';
  let preference = 'light';
  try { preference = normalize(localStorage.getItem(key)); } catch (_) {}
  function apply() {
    document.documentElement.dataset.theme = preference === 'system' ? (media.matches ? 'dark' : 'light') : preference;
    const control = document.getElementById('theme-choice');
    if (control) control.value = preference;
  }
  apply();
  document.addEventListener('DOMContentLoaded', () => {
    const control = document.getElementById('theme-choice');
    if (!control) return;
    control.hidden = false; apply();
    control.addEventListener('change', () => { preference = normalize(control.value); apply(); try { localStorage.setItem(key, preference); } catch (_) {} });
  });
  media.addEventListener('change', apply);
  window.addEventListener('storage', e => { if (e.key === key || e.key === null) { preference = normalize(e.newValue); apply(); } });
}());
