/* Apply the saved theme before styles paint. Light is always the initial default. */
(function () {
  'use strict';
  const key = 'ttbg-theme';
  const normalize = value => value === 'dark' ? 'dark' : 'light';
  let initial = 'light';
  try { initial = normalize(window.localStorage.getItem(key)); } catch (_) {}
  function apply(value) {
    const theme = normalize(value);
    document.documentElement.dataset.theme = theme;
    const control = document.getElementById('theme-choice');
    if (control) control.value = theme;
  }
  apply(initial);
  document.addEventListener('DOMContentLoaded', function () {
    const control = document.getElementById('theme-choice');
    if (!control) return;
    control.hidden = false;
    apply(document.documentElement.dataset.theme);
    control.addEventListener('change', function () {
      apply(control.value);
      try { window.localStorage.setItem(key, control.value); } catch (_) {}
    });
  });
  window.addEventListener('storage', function (event) {
    if (event.key === key || event.key === null) apply(event.newValue);
  });
}());
