/* Refresh only time links; never automatically submit or create a reservation. */
(() => {
  const grid = document.querySelector('.slot-grid');
  if (!grid) return;
  grid.setAttribute('aria-live', 'polite');
  let loading = false;
  async function refresh() {
    if (loading || document.hidden) return;
    loading = true;
    try {
      const response = await fetch(location.href, {cache:'no-store', credentials:'same-origin', signal:AbortSignal.timeout(12000)});
      if (!response.ok) throw new Error('unavailable');
      const doc = new DOMParser().parseFromString(await response.text(), 'text/html');
      const next = doc.querySelector('.slot-grid');
      if (!next) throw new Error('unavailable');
      if (grid.innerHTML !== next.innerHTML) grid.replaceChildren(...Array.from(next.childNodes));
    } catch (_) {
      grid.replaceChildren();
      const note = document.createElement('p');
      note.textContent = 'Times could not be refreshed. Reload this page to see current availability.';
      grid.append(note);
    } finally {loading = false;}
  }
  setInterval(refresh, 30000);
  document.addEventListener('visibilitychange', () => {if (!document.hidden) refresh();});
  window.addEventListener('pageshow', event => {if (event.persisted) refresh();});
})();
