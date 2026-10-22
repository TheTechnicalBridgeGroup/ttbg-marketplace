# v0.9.0 validation

Baseline: the completed v0.8.0 release, including the supplied v0.7.1 Stripe Checkout and CSP fixes.

- Full Python regression run: **213 passed** (168.77 seconds).
- After final provider-response and error-classification hardening: **47 passed** covering v0.7 financial workflows and the 22 initial v0.9 tests.
- Final PlanetScale/Vitess query-timeout guard: **2 passed**, including one additional test and a repeated record-explorer security test. **214 unique Python tests validated overall.**
- Password DOM checks passed: independent Show/Hide buttons, accessible labels and pressed state, value/autofill preservation, dynamic fields, submit/dialog-close reset, and no logging/network access. `tests/password_visibility.cjs` can be run with Node after installing the development-only `jsdom` package. It is not a runtime dependency.
- All Jinja templates compile; approved diagnostic table/column names exist; Python sources compile.
- All 44 pre-existing model class declarations are unchanged. Two new diagnostic models and one booking lookup index are additive. Upgrade tests preserve accounts, password hashes, booking/payment snapshots, and repeated migration safety. PostgreSQL and MySQL table/index DDL compile in the regression suite.

The v0.9 tests cover:

- Free-to-paid same-time conflict with no substitution and no checkout creation.
- Paid checkout blocking a free service before payment; timer alone does not release it; verified expiry does.
- Cancellation/rebooking despite a stale local appointment snapshot; changed provider times after rescheduling.
- Full-duration conflicts, different starts, cross-service padding, independent available times, saturated/incomplete occupancy responses and API failures.
- Real simultaneous HTTP submissions using separate SQLite connections: one durable appointment, one conflict response.
- Signed retry safety and one checkout per accepted request; paid services cannot use the live direct-booking path with checkout disabled.
- Actual clickable availability links omit active checkout holds.
- Admin-only direct-route/POST access, CSRF, diagnostic allowlists, bounds, no private fields or exports, and audited access.
- Read-only health probes, no fabricated webhook delivery, original service and saved payment history, safe Render log summaries and nonfatal provider failure.
- Connect-specific error references and unchanged historical financial values.

Retained financial tests cover verified payment outcomes, Acuity creation uncertainty, post-payment recovery/refunds, duplicate operations, cancellation attribution, refund history, transfer approvals, webhook signatures, mode isolation and account deletion safeguards.

## Not claimed as tested

No live credentials, Render workspace API permissions, PlanetScale production migration, provider calendar settings, real email delivery, Google Meet joining details, real-money payments/refunds/transfers, or production deployment were exercised. No real-browser visual/keyboard/device QA was completed: the Chromium test binary could not be downloaded in this environment. DOM tests are not a substitute for that acceptance gate. Database concurrency was exercised with SQLite; run the staging race tests on the target PlanetScale engine before live activation.

Follow RELEASE_V09.md for staging, controlled production acceptance, migration and rollback instructions. v0.9.0 remains a controlled production pre-release; this validation does not certify v1.0.0 readiness.
