(() => {
  document.querySelectorAll('form[data-booking-submit]').forEach(form => {
    form.addEventListener('submit', () => {
      const button = form.querySelector('button[type="submit"]');
      button.dataset.originalLabel = button.textContent;
      button.disabled = true; button.textContent = 'Confirming your appointment…';
    });
  });
  window.addEventListener('pageshow', () => {
    document.querySelectorAll('form[data-booking-submit] button[type="submit"]').forEach(button => {
      button.disabled = false; button.textContent = button.dataset.originalLabel || button.textContent;
    });
  });
})();
