(function () {
  'use strict';
  const announce = text => { document.getElementById('ui-status').textContent = text; };
  document.querySelectorAll('[data-dismiss]').forEach(button => {
    button.hidden = false; button.addEventListener('click', () => button.closest('.notice').remove());
  });
  document.querySelectorAll('[data-copy-target]').forEach(button => button.addEventListener('click', async () => {
    const target = document.getElementById(button.dataset.copyTarget), original = button.textContent;
    try {
      await navigator.clipboard.writeText(target.value || target.textContent.trim());
      button.textContent = 'Copied ✓'; announce('Copied to clipboard.');
      setTimeout(() => { button.textContent = original; }, 2000);
    } catch (_) {
      if (target.select) { target.focus(); target.select(); }
      announce('Copy is unavailable in this browser. Select the text and copy it manually.');
      button.textContent = 'Select text to copy';
      setTimeout(() => { button.textContent = original; }, 3000);
    }
  }));
  document.querySelectorAll('form[data-confirm]').forEach(form => form.addEventListener('submit', event => {
    if (!window.confirm(form.dataset.confirm)) event.preventDefault();
  }));
  const pathname = location.pathname;
  document.querySelectorAll('.support-nav a,.control-nav a,header nav > a').forEach(link => {
    const url = new URL(link.href);
    if (url.origin === location.origin && (url.pathname === pathname || (url.pathname === '/support' && pathname.startsWith('/support/accounts/')))) {
      link.setAttribute('aria-current', 'page');
    }
  });
  const quick = document.getElementById('quick-dialog'), filter = document.getElementById('quick-filter');
  const quickLinks = Array.from(quick.querySelectorAll('.quick-links a'));
  function filterPages() {
    const term = filter.value.trim().toLowerCase(); let count = 0;
    quickLinks.forEach(link => { link.hidden = !link.textContent.toLowerCase().includes(term); if (!link.hidden) count++; });
    document.getElementById('quick-empty').hidden = count !== 0;
  }
  function openQuick() {
    if (document.querySelector('dialog[open]')) return;
    filter.value = ''; filterPages(); quick.showModal(); filter.focus();
  }
  if (typeof quick.showModal === 'function') {
    document.querySelectorAll('[data-open-quick]').forEach(b => { b.hidden = false; b.addEventListener('click', openQuick); });
    document.querySelector('[data-close-quick]').addEventListener('click', () => quick.close());
    filter.addEventListener('input', filterPages);
    document.addEventListener('keydown', e => { if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); openQuick(); } });
  }
  const dialog = document.getElementById('credential-dialog');
  if (!dialog || typeof dialog.showModal !== 'function') return;
  const form = document.getElementById('credential-form'), password = document.getElementById('reveal-password');
  const error = document.getElementById('credential-error'), result = document.getElementById('credential-result'), value = document.getElementById('credential-value');
  const submit = form.querySelector('[type="submit"]');
  let revealUrl = '', timer, controller, generation = 0;
  function erase() {
    generation++; clearTimeout(timer); if (controller) controller.abort();
    password.value = ''; value.value = ''; result.hidden = true; form.hidden = false;
    error.textContent = ''; submit.disabled = false; submit.textContent = 'Verify & reveal';
  }
  document.querySelectorAll('[data-reveal-url]').forEach(button => {
    button.hidden = false;
    button.addEventListener('click', () => {
      erase(); revealUrl = button.dataset.revealUrl;
      document.getElementById('credential-title').textContent = button.dataset.keyLabel;
      dialog.showModal(); password.focus();
    });
  });
  dialog.querySelector('[data-close-dialog]').addEventListener('click', () => dialog.close());
  dialog.addEventListener('close', erase);
  dialog.addEventListener('cancel', erase);
  document.addEventListener('visibilitychange', () => { if (document.hidden && dialog.open) dialog.close(); });
  window.addEventListener('blur', () => { if (dialog.open) { erase(); dialog.close(); } });
  window.addEventListener('pagehide', erase);
  form.addEventListener('submit', async event => {
    event.preventDefault(); error.textContent = ''; submit.disabled = true; submit.textContent = 'Verifying…';
    const body = new FormData(form), attempt = ++generation;
    password.value = ''; controller = new AbortController();
    try {
      const response = await fetch(revealUrl, { method:'POST', body, credentials:'same-origin', cache:'no-store', redirect:'error', signal:controller.signal });
      const data = response.headers.get('content-type')?.includes('application/json') ? await response.json() : {};
      if (attempt !== generation || !dialog.open) return;
      if (!response.ok) { error.textContent = data.error || (response.status === 429 ? 'Too many attempts. Wait 15 minutes before trying again.' : 'Your session or form expired. Reload this page and try again.'); return; }
      value.value = data.value; delete data.value; form.hidden = true; result.hidden = false; value.focus();
      timer = setTimeout(() => { erase(); dialog.close(); announce('Credential hidden.'); }, 30000);
    } catch (e) {
      if (e.name !== 'AbortError' && attempt === generation) error.textContent = 'Unable to verify. Reload the page or try again.';
    } finally {
      body.delete('password');
      if (attempt === generation) { submit.disabled = false; submit.textContent = 'Verify & reveal'; }
    }
  });
}());
