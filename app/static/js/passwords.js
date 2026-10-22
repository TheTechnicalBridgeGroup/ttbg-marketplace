/* No input values are read, copied, logged, or transmitted by this control. */
(() => {
  function attach(root) {
    root.querySelectorAll('input[type="password"]').forEach(input => {
      if (input.dataset.visibilityReady) return;
      input.dataset.visibilityReady = 'true';
      const wrapper = document.createElement('span');
      wrapper.className = 'password-control';
      input.before(wrapper); wrapper.append(input);
      const button = document.createElement('button');
      if (input.id) button.setAttribute('aria-controls', input.id);
      button.type = 'button'; button.className = 'password-toggle';
      const label = input.labels?.[0]?.textContent.trim() || 'password';
      button.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/></svg><span>Show</span>';
      const update = () => {
        const visible = input.type === 'text';
        button.setAttribute('aria-label', `${visible ? 'Hide' : 'Show'} ${label}`);
        button.setAttribute('aria-pressed', String(visible));
        button.querySelector('span').textContent = visible ? 'Hide' : 'Show';
      };
      button.addEventListener('click', () => {input.type = input.type === 'password' ? 'text' : 'password'; update();});
      window.addEventListener('pagehide', () => {input.type = 'password'; update();});
      input.form?.addEventListener('submit', () => {input.type = 'password'; update();});
      input.form?.addEventListener('reset', () => {input.type = 'password'; update();});
      input.closest('dialog')?.addEventListener('close', () => {input.type = 'password'; update();});
      wrapper.append(button); update();
    });
  }
  attach(document);
  new MutationObserver(() => attach(document)).observe(document.body, {childList:true,subtree:true});
})();
