(() => {
  const panel = document.getElementById('help-guide');
  if (!panel) return;
  const log = document.getElementById('help-transcript');
  const input = document.getElementById('help-text');
  const close = document.getElementById('help-close');
  const responses = {
    booking: 'Open Find a mentor, select a profile and service, and check availability. In confirmed booking mode, choose a time, enter your details, and submit confirmation. Check your dashboard for the appointment. If confirmation is uncertain, contact TTBG before trying again. An available time is not reserved. When payments are enabled, paid sessions use Stripe Checkout before Acuity confirms the appointment; FREE consultations skip payment. Open Payments to review status or contact TTBG for refund help.',
    account: 'For a new account, open the verification email and choose your password. Check spam or sign in to resend the email. For a forgotten password or account restriction, submit a ticket so the team can help you recover access. Never send your password in a ticket.',
    profile: 'Mentors can upload a profile picture from their dashboard. An admin or account manager reviews it before publication. The current approved photo stays visible until the replacement is approved.',
    documentation: 'Admins, account managers, and mentors can open Documentation from the main navigation. Admins and account managers can add, edit, and delete pages and upload images.',
    team: document.getElementById('help-phone') ? 'Use Call the team below to open your phone app, or submit a ticket. I cannot connect a live agent inside this chat; the team will respond through your chosen contact method.' : 'Submit a help-desk ticket or email the team below. A team phone number has not been configured yet. I cannot connect a live agent inside this chat.',
    fallback: 'I can help with booking, account access, profile pictures, documentation, or contacting the team. Choose a topic below, or submit a ticket for something specific.'
  };
  function reply(question, topic) {
    const user = document.createElement('p'); user.className = 'help-question'; user.textContent = question;
    const answer = document.createElement('p'); answer.className = 'help-answer'; answer.textContent = responses[topic] || responses.fallback;
    log.append(user, answer);
    while (log.children.length > 15) log.firstElementChild.remove();
    log.scrollTop = log.scrollHeight;
  }
  function classify(text) {
    if (/human|person|team|agent|call|phone|contact|ticket|help desk/i.test(text)) return 'team';
    if (/doc|guide|article|confluence/i.test(text)) return 'documentation';
    if (/password|sign.?in|log.?in|account|verif|email/i.test(text)) return 'account';
    if (/photo|picture|profile|avatar/i.test(text)) return 'profile';
    if (/book|schedul|session|payment|refund|availab/i.test(text)) return 'booking';
    return 'fallback';
  }
  panel.querySelectorAll('[data-help-topic]').forEach(button => button.addEventListener('click', () => reply(button.textContent, button.dataset.helpTopic)));
  document.getElementById('help-question').addEventListener('submit', event => {
    event.preventDefault(); const question = input.value.trim(); if (!question) return;
    reply(question, classify(question)); input.value = ''; input.focus();
  });
  close.hidden = false;
  function dismiss() { panel.open = false; panel.querySelector('summary').focus(); }
  close.addEventListener('click', dismiss);
  panel.addEventListener('keydown', event => { if (event.key === 'Escape') dismiss(); });
})();
