# v0.6.7 — Acuity service import and FREE consultations

- Admins and Account Managers can fetch an appointment type from Services & pricing, review and edit its name/description, and explicitly save the service and Acuity mapping.
- Validates the saved mentor calendar, active one-to-one type, supported price/duration, and current provider data. Existing mentor/type matches become explicit updates with side-by-side comparisons; conflicting mappings stop the import.
- Signed 15-minute previews reject stale service/source changes, cross-account reuse, and repeated creation submissions. Successful imports/updates are audited.
- Zero-priced consultations import and save correctly and show FREE. Zero-priced confirmed appointments are recorded as No payment required; monetary allocation fields remain numeric.
- Manual service duration accepts 1–1,440 whole minutes. Local mock type 202 provides a free 30-minute consultation alongside type 201.
- Existing bookings, accounts, credentials, and platform booking mode are preserved. No new dependency or schema migration is required. Health/version and asset references now identify v0.6.7.

See ACUITY_IMPORT_V067.md. Live Acuity account testing and deployment remain separate from the included local verification.

# v0.6.0 — Confirmed Acuity appointments

- Native TTBG confirmation form, server-owned quotes/mappings, normal Acuity availability and intake validation, and saved provider IDs/booking/allocation snapshots.
- Signed change webhooks, durable retries, periodic/targeted refresh, and updated student/mentor dashboards.
- Staff mapping verification, external-appointment linking, and reconciliation for uncertain creation outcomes; no blind duplicate create retries.
- Isolated local dummy-key simulator, practice account setup, unavailable-slot/timeout/sync-failure scenarios, and signed reschedule/cancellation simulation.
- Existing accounts and booking settings preserved; live confirmation is explicitly enabled after configuration.

Read ACUITY_V06_SETUP.md. Payment collection and automatic Stripe Connect payouts are not part of appointment confirmation. Live credentials/entitlement and a controlled real end-to-end test remain required.

# v0.5.0 — Accounts, documentation, and guided help

- Permanent deletion of any non-admin account from Support account details, with email/password/reason confirmation. Every Admin account is protected. Financial snapshots and shared history are retained through non-login archive references.
- Role-protected documentation with spaces, nested pages, search, staff Add/Edit/Delete, stale-edit checks, and compressed private image uploads.
- Lightweight automated help guide with configurable public team phone number, email, and help-desk handoff.
- New-account and changed-email verification, automatic SMTP verification email, single-use one-hour links, restricted pending access, resend limits and safe delivery failure handling.
- Cloudflare Turnstile registration/resend protection with server-side hostname/action checks, replay protection, and scoped CSP.
- Database-backed registration/verification limits and a cleanup CLI.
- Existing accounts retain access; disabled/suspended accounts remain restricted. No mass-disable command was added.

Read SECURITY_SETUP.md before deploying. New public registration requires SMTP configuration; Turnstile requires your widget keys and hostname configuration. Live email delivery and Cloudflare challenges still need deployment verification.

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
