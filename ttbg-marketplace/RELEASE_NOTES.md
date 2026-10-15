# v0.8.0 — Financial Operations & Payment Reliability

- Based on the supplied working v0.7.1 source; preserves supported Checkout parameters, narrow Stripe CSP, and original durable idempotency keys.
- Friendly environment-marked payment references, combined search/filters, date/timezone ranges, sorting, pagination, review queues, full-filter summaries, and staff CSV export.
- Exact staff cancellation identity snapshots, distinct requester/performer/approver, reasons, timestamps, confirmed provider results, and unverified external attribution.
- Guided Admin cancellation and optional approved full remaining refund; owner unpaid Checkout cancellation; mentor/manager review requests; no invented automatic refund policy.
- Append-only financial timeline, failed/uncertain operation evidence, full refund history, external refund detection, and transfer-recovery visibility.
- Mentee status/receipt page without internal bookkeeping cards; mentor earnings and authenticated Stripe Express account management.
- Worker heartbeat, canonical Stripe/Acuity reconciliation, cancellation read recovery, durable financial notices, and Admin review of ambiguous delivery.
- Six additive tables, financial indexes, friendly-ID backfill, and an editable in-app operations guide. Existing accounts, secrets, and amounts are preserved.
- Partial-refund creation and a new allocation policy are deferred pending leadership approval. Accounts v2 migration and daily scheduled financial reports remain future work.
- No deployment, live payment, production database migration, or real-provider email was performed during the build.

# v0.7.0 — Stripe Connect and completion-based mentor transfers

- Separate charges and transfers with Stripe-hosted Checkout and US/USD connected-account onboarding.
- TTBG absorbs processing fees; each order preserves its original allocation and separately records Stripe's reported processing fee.
- Verified payments precede Acuity creation. Failed appointments refund; uncertain creation is reconciled without duplicate provider requests.
- Durable signed webhook inbox, payment worker, stable operation keys, conservative retry window, and verified object recovery.
- TTBG payment center for staff, personal payment/earnings history, mentor readiness, completion reporting, and password-confirmed Admin money actions.
- Full remaining refunds, transfer reversals, dispute holds, cancellation review, and reschedule approval reset. Partial external refunds require staff settlement review.
- Local Stripe dummy-key simulation alongside local Acuity, including a command to end a simulated session for transfer testing.
- Seven additive tables, editable payment documentation, and payment-safe account deletion. Existing identities, passwords, settings, and historic allocations remain intact.
- New payments disabled by default; no deployment or live money movement performed. Real Stripe/Acuity staging and live activation remain operator steps in STRIPE_V07_SETUP.md.

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
