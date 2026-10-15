# TTBG Marketplace v0.7.0 validation

Validated locally on October 15, 2026. **163 automated tests covered: 138 retained regression tests and 25 new v0.7 payment tests.** The full regression run passed all 161 tests present at that point. After adding two recovery regression cases and correcting their explicit-retry paths, all 25 payment tests passed together. Focused webhook/worker and won-dispute tests passed after the final recovery-polling and simulator refinements. Test outcomes are local simulation/transport checks, not evidence of live provider activation.

## Payment checks

- No appointment exists before verified payment. $100 checkout stores $80 mentor/$20 TTBG allocations, with a separately recorded simulated processing fee absorbed by TTBG.
- Canonical Checkout, PaymentIntent, charge, amount/currency/order verification; tampered amount fails closed. Transport uses the pinned API version, fixed Stripe origin, Basic authorization, nested form encoding, and persistent idempotency headers.
- Signed raw-body webhook rejection for bad signatures, stale timestamps, and wrong mode; durable inbox, duplicate event IDs, worker processing, and stale event delivery.
- Local slot conflicts after payment produce one full refund and no booking. Uncertain Acuity creation never retries and reconciles to the original appointment.
- Expired Checkout releases local coordination state; repeated submissions and uncertain Checkout response recovery do not create a second session or appointment.
- Transfer requires completion approval after the scheduled end, available funds, current mentor readiness, no refund/dispute hold, and a known transfer history. Repeated transfers produce one mentor transfer.
- Full refunds after transfer recover the mentor allocation separately. Definitive rejected refunds and failed reversals can be explicitly retried by an Admin. Unknown refund outcomes reconcile without a second refund.
- External partial refunds are not silently expanded. External full refunds recover known mentor transfers. Unknown external transfer groups hold new transfer actions.
- Disputes block transfers; a canonically won dispute can be released, completion reapproved, and the original allocation transferred. Cancellation holds and rescheduling approval resets are exercised.
- Account managers and mentors cannot call Admin money endpoints. Other students cannot view payments. Wrong-password and CSRF submissions cannot perform money actions. Readiness is not granted just by returning from onboarding.
- New-payment feature flag does not abandon existing paid sessions. Free consultation creation bypasses Stripe even without credentials.
- Mentor deletion detaches the payment association and preserves financial records; a deleted student's late payment refunds without recreating the identity.
- Manual linking of an existing Stripe operation validates its original metadata. Retry-window expiry moves the write to manual reconciliation.

## Retained behavior

Existing tests cover mentor profile workflows, service import/update from Acuity, FREE presentation, Acuity creation/synchronization, account access/reset/deletion, verification emails, Turnstile, photo review/compression, knowledge-page editing, support tooling, commission snapshots, and protected credential reveal. No existing accounts/passwords are reset during upgrade.

## Schema and presentation

- All 38 table definitions and indexes compile for PostgreSQL and MySQL. SQLite workflow tests enable foreign keys. This is not a live PlanetScale/PostgreSQL migration test.
- Repeated additive upgrade preserves existing users, roles, password hashes, and edited documentation. Seven payment tables and one seeded editable payment guide are new.
- Payment history/details, mentor onboarding, and staff payment center render through Flask test clients. They reuse the existing responsive TTBG navy/gold styles and theme controls. No visual browser/screenshot QA was performed in this environment.
- Python source compiles. Release archive excludes `.env`, local databases, virtual environments, runtime instances, credentials, and caches; only example environment files are included.

## Remaining operator verification

Real Stripe Connect onboarding, Checkout, webhook reachability, payment settlement, account restrictions, refund/reversal behavior with real balances, and bank payouts must be tested with TTBG's actual test/live credentials. Live Acuity calendar entitlement/mappings, reminders, provider email, SMTP, and Turnstile require their own end-to-end checks. No production service, account, database, payment, appointment, or deployment was changed by this release build.

Read STRIPE_V07_SETUP.md before activation. New payments are disabled by default; a persistent worker is required. Initial scope is US/USD, cards, full remaining refunds, and Admin-approved transfers. Partial-refund settlement, disputed money already reversed, tax/reporting, permitted fund-holding timing, and platform bank-payout/balance policy require the documented operator decisions. Transfer status does not claim a completed bank payout.
