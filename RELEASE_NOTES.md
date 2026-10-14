# v0.4.1 — Help desk shortcut

- Added a Submit a ticket button throughout the staff-only Support Center.
- Opens https://help.thetechnicalbridgegroup.com/tickets/new in a new tab. The help desk handles sign-in and returns users to the new-ticket form.
- Existing help desk code and ticket records are unchanged.

# v0.4.0 — Support and interface update

- Staff-only Support Center: account lookup, activity timeline, internal notes, booking lookup, and error triage.
- Account Manager password-reset/session-revocation tools restricted to students and mentors; Admins retain staff recovery.
- Masked environment-backed API keys. Admin password popup for every reveal, with audit and throttling; user passwords remain unreadable.
- Navy/gold visual refresh, quick navigation, device theme, dismissible notices, useful copy buttons, and square mentor profile photos.
- Native Acuity availability aligned with TTBG's chosen Acuity/Stripe Connect architecture. Contact-to-confirm remains the only action after viewing a slot.
- Additive upgrade preserves existing users, passwords, mentor profiles, booking snapshots, configured booking mode, and customized commission settings.

Not included: live deployment, Stripe Connect onboarding/checkout/webhooks/refunds, appointment creation, automatic payouts, email delivery, or support impersonation.

Run the updated `start-windows.bat` locally. For an existing installation, retain its `.env` and database. For Render, follow DEPLOYMENT.md and run init-db before serving the new release.
