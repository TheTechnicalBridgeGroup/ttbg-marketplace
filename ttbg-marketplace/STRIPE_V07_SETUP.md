# TTBG Marketplace v0.7.0 — Stripe Connect

**TTBG absorbs payment-processing fees.** With the default 80/20 policy, a $100 booking allocates $80 to the mentor and $20 gross to TTBG. Stripe's actual charge balance-transaction fee is recorded separately; it does not reduce the mentor's $80. Connect fees, refunds, disputes, taxes, and other expenses can further reduce TTBG's revenue. The allocation is captured in integer cents when checkout starts. Later commission changes do not rewrite it.

This release implements separate charges and transfers using Stripe-hosted Checkout and hosted connected-account onboarding. It supports US platform/mentor accounts and USD, with card payments only. It does not collect card, bank, identity-document, or tax-identification values inside TTBG. No production configuration, deployment, or money movement is included in the release process.

## Upgrade an existing installation

1. Back up the existing database. Preserve `.env`, `SECRET_KEY`, `DATABASE_URL`, and all existing accounts.
2. Replace application source with this release. Install `requirements.txt` in your virtual environment.
3. Keep `PAYMENTS_ENABLED=false`. Run `python -m flask --app run init-db` once before starting multiple web/worker processes. This creates seven additive payment tables and one editable documentation page; it does not rebuild old tables, disable accounts, or reset the commission.
4. Start the app normally. Existing Acuity scheduling continues with its prior booking mode while payments are disabled. Free consultations remain FREE and bypass Stripe in either mode.
5. Configure Stripe in a separate test environment, verify the complete flow, then activate live payments deliberately.

Payment enablement applies only to the native **Acuity confirmed appointments** booking mode. Select that mode in Admin → Settings before activation. Contact and external-link modes are separate experiences. Do not collect a second payment for the same session in Acuity, another checkout, or a manual invoice.

## Credentials and environment

| Variable | Purpose |
| --- | --- |
| `STRIPE_MODE` | `mock`, `test`, or `live`; defaults to `test` |
| `STRIPE_ACCOUNT_ID` | TTBG platform account ID (`acct_…`), not a mentor ID; verified against the API key on real requests |
| `STRIPE_SECRET_KEY` | Platform key matching the selected mode: `sk_test_…` or `sk_live_…` |
| `STRIPE_WEBHOOK_SECRET` | Signing secret for the platform snapshot webhook destination |
| `STRIPE_CONNECT_WEBHOOK_SECRET` | Signing secret for the connected-account snapshot destination, if separately configured |
| `PAYMENTS_ENABLED` | `false` by default; set `true` only to activate new paid checkouts |
| `STRIPE_LIVE_CONFIRMED` | Must be `true` for any live Stripe write; keep false until controlled activation |
| `APP_ENV` | `staging` for real Stripe test mode, `production` for live, `local` for the isolated simulator |
| `PUBLIC_BASE_URL` | Exact trusted origin; HTTPS required for live Stripe, e.g. `https://marketplace.example.com` |
| `PAYMENT_MAX_ADVANCE_DAYS` | Integer 1–60; default 60; application limit, not a statement of Stripe's legal holding allowance |
| `PAYMENT_POLICY_TEXT` | Customer-facing cancellation/refund policy shown before payment; set the approved TTBG policy before activation |
| `ACUITY_USER_ID`, `ACUITY_API_KEY` | Existing Acuity backend credentials |
| `ACUITY_WEBHOOK_SECRET` | Only for a separately configured static Acuity signing key; dynamic Acuity webhooks use the API key |

No publishable key is needed for this redirect-based hosted Checkout flow. One platform API key serves all mentors; mentors receive connected-account IDs, not platform API keys. Admins can reveal allowlisted secrets only after password verification in Support → Integrations. Webhook secrets are distinct from API keys.

The API is pinned to **2026-09-30.endive**. This is a v1 REST integration using explicit controller properties (`fees.payer=application`, `losses.payments=application`, `requirement_collection=stripe`, `stripe_dashboard.type=express`), with the transfers capability requested. No new Stripe SDK dependency is required. API traffic is HTTPS to `api.stripe.com` only, with bounded responses, timeouts, no redirects, and durable idempotency keys on writes.

## Mentor onboarding

1. Mentor signs in → Payments → Stripe payment setup → Set up Stripe account.
2. TTBG creates an account for the current platform/mode and redirects the mentor to Stripe-hosted onboarding.
3. Mentor completes Stripe's identity, tax, and bank requirements. Return to TTBG and check readiness.
4. Readiness requires US/USD, submitted details, active transfers, enabled payouts, and no currently-due or disabled requirements. Returning to TTBG alone is never approval.

Legacy manually entered Stripe account references are not trusted as payment-ready. An Admin can use Support → Payments → Link an existing connected account, supplying the TTBG mentor ID and correct connected-account ID, password, and reason. Verify the mentor's identity in Stripe first. TTBG verifies platform control and US/USD and prevents replacing an association or linking one account to two mentors in the same mode. Uncertain account creation must be reconciled using the original operation instead of creating another account.

Mode/platform associations are separate. Existing orders retain their original destination. Changing environment credentials does not remap historical orders; restore the original scope to investigate those records.

## Signed webhooks and the required worker

Configure **snapshot** event destinations, not thin events, with the same pinned API version. Public URL:

```text
https://YOUR-MARKETPLACE-ORIGIN/webhooks/stripe
```

Platform destination events:

- `checkout.session.completed`, `checkout.session.expired`, `checkout.session.async_payment_succeeded`, `checkout.session.async_payment_failed`.
- `payment_intent.succeeded`, `payment_intent.payment_failed`, `payment_intent.canceled`.
- `charge.refunded`, `charge.dispute.created`, `charge.dispute.updated`, `charge.dispute.closed`, `charge.dispute.funds_withdrawn`, `charge.dispute.funds_reinstated`.
- `refund.created`, `refund.updated`, `refund.failed`.
- `transfer.created`, `transfer.updated`, `transfer.reversed`.

Connected accounts destination: `account.updated`. Set its distinct secret in `STRIPE_CONNECT_WEBHOOK_SECRET`. The receiver accepts either configured secret, validates raw-body HMAC with a five-minute timestamp tolerance, and checks test/live mode. Connected-account charge events are ignored; marketplace payments are platform charges.

The receiver commits a small durable inbox record before returning HTTP 200. **A 200 response means queued, not fully processed.** It never trusts the event payload as the current financial state. The worker fetches canonical Stripe objects; duplicate or out-of-order deliveries do not create duplicate charges, bookings, or transfers.

Run a dedicated process with the same database and environment as the web service:

```text
python -m flask --app run payments-worker
```

Or schedule the following every minute, with monitoring and no overlapping scheduled runs:

```text
python -m flask --app run payments-worker --once --limit 100
```

The long-running worker checks batches and waits ten seconds between batches; provider requests may make a batch longer. Active recoveries are polled at least 30 seconds apart and take priority. Settled history is checked hourly or immediately when a webhook is processed. A one-shot invocation exits nonzero if jobs need retry/review. Monitor worker health, pending inbox count, oldest unprocessed records, and failed operations in Support → Payments. Recovery reads can have API costs/rate limits as history grows; size worker capacity to the marketplace. Do not start a worker thread inside each Gunicorn worker. Keep the existing Acuity webhook/retry/sync process from ACUITY_V06_SETUP.md.

Switching `PAYMENTS_ENABLED=false` stops new paid checkout requests. It does **not** cancel open Stripe sessions or stop recovery of existing payments. Keep webhooks and the worker running until all outstanding orders are settled. This avoids abandoning customers who already opened Checkout.

## Booking, completion, and transfers

1. Student chooses a service and time. Backend validates Acuity mappings, catalog, current availability, intake answers, service amount, and mentor readiness. Paid sessions must start at least one hour ahead and cost at least $0.50.
2. TTBG saves the request, exact financial allocation, and one Checkout operation before contacting Stripe. Checkout expires after roughly 31 minutes. A local slot key limits simultaneous TTBG checkouts but does not reserve availability in Acuity or prevent overlapping external bookings.
3. Stripe collects payment. Webhook/worker or the customer's return page fetches and verifies the Checkout Session, PaymentIntent, charge, amount, currency, and order references. A browser redirect is not proof of payment.
4. TTBG rechecks eligibility/availability and attempts Acuity creation once. A confirmed provider response is saved with the booking. Definitive failure requests a full refund. An ambiguous timeout/database failure enters reconciliation; there is no blind second Acuity POST or premature refund.
5. Mentor reports completion after the scheduled end. An Admin independently verifies completion, enters a reason and password, and approves it. Time passing alone is not proof of attendance.
6. Admin selects Transfer. The backend refreshes Acuity, Stripe payment/dispute/refund status, mentor readiness, and charge-fund availability. The stored mentor allocation is transferred with `source_transaction` and a booking transfer group. Duplicate action submissions reuse the original durable operation.

**Transferred to Stripe is not paid to a bank.** Stripe handles bank-payout schedules and restrictions. TTBG does not call a bank-payout endpoint. Keep enough platform balance for transfers, fees, refunds, and disputes. Confirm permitted holding times, appointment lead times, payout schedule, and marketplace liability with Stripe before live activation; this is not an escrow service. Test whether TTBG's automatic platform bank payouts leave adequate available balance for completion-based transfers.

## Cancellations, refunds, and disputes

- A cancellation or material Acuity change holds transfers for staff review. A reschedule clears prior completion approval. Full automatic refunds apply to definitively failed post-payment appointment creation; other cancellations use the approved TTBG policy and Admin review.
- Admins issue a **full remaining session refund**, with fresh password, reason, and acknowledgement. This release does not provide partial-refund entry in TTBG.
- A refund does not cancel a confirmed Acuity appointment. Cancel/reschedule separately through Acuity and verify synchronization.
- Refund statuses include pending and failed. A definitive failed/canceled refund can be retried explicitly by an Admin; an unknown outcome is reconciled first.
- After a verified full refund, the system separately reverses an existing TTBG mentor transfer. Reversal can fail if funds are unavailable. The payment remains refunded while Support flags mentor-funds recovery; an Admin can retry recovery after resolving Stripe's balance restriction. Do not promise that reversing a transfer retrieves money already paid into a bank.
- External full refunds are recognized and trigger recovery of a known TTBG transfer. External partial refunds hold further transfers for manual review; TTBG does not silently enlarge them to a full refund. Resolve partial settlement in Stripe and retain the evidence/reason in staff records.
- Disputes hold transfers. Admins manage evidence and deadlines in Stripe. An Admin can recover a transferred mentor allocation for a disputed payment. A won/closed warning dispute can be released through the review action after canonical verification, provided no funds were reversed/refunded. Completion must then be reapproved. Recovery/retransfer after reversed funds requires manual settlement in Stripe; this release never automatically pays a second mentor transfer.
- Unknown transfers discovered under an order's transfer group block further transfer until investigated. Avoid manual transfers for TTBG orders outside this workflow; metadata-less external transfers cannot be reliably attributed automatically.

## Recovery procedures

**Uncertain Acuity appointment:** Support → Payment details → Reconcile Acuity appointment. Search and verify the exact client, calendar, type, and original time. Link an existing appointment. Release only after independently confirming none exists; this queues the paid-request refund. If an account was deleted, verify/cancel any remaining appointment in Acuity before releasing; deleted identities are not recreated.

**Unknown Stripe write:** the original operation and parameters remain saved. Retrying uses the same idempotency key within a conservative 23-hour window from first attempt. Beyond that, the operation stops for manual reconciliation rather than risking Stripe treating a retry as a new write. Locate the original Stripe object by `metadata.ttbg_operation`, `metadata.ttbg_order`, and the operation ID in Support. Admin → Operation history → Reconcile an existing Stripe object validates metadata, amount, destination, and charge references before linking it. Never guess an object ID or create a replacement payment to clear an error. Account Links are short-lived; mentors can request a fresh link.

**Rejected Checkout without a session:** after verifying the definite rejection, an Admin can close the rejected checkout and release its local slot. An uncertain Checkout must first be reconciled. Expired sessions are refreshed from Stripe before release.

Account deletion remains available for non-admin accounts. Financial snapshots survive, the connected-account association is detached when a mentor is deleted, and sensitive pending intake/email payloads are scrubbed. Existing bank/Stripe/Acuity records are not deleted. A late payment on a deleted student's unconfirmed request is refunded; uncertain appointment outcomes still require staff reconciliation. Existing confirmed bookings remain archived, with transfers held.

## Local dummy-key walkthrough (Windows Command Prompt)

Use an isolated local folder/database, never your production environment. Copy `.env.mock.example` to `.env` and add a random `SECRET_KEY` of at least 32 characters. It includes:

```dotenv
APP_ENV=local
ACUITY_MODE=mock
ACUITY_USER_ID=1
ACUITY_API_KEY=local-dummy-key
DATABASE_URL=sqlite:///marketplace-mock.db
PUBLIC_BASE_URL=http://127.0.0.1:5000
COOKIE_SECURE=false
STRIPE_MODE=mock
STRIPE_ACCOUNT_ID=acct_local
STRIPE_SECRET_KEY=local-stripe-dummy-key
STRIPE_WEBHOOK_SECRET=whsec_local_practice_only
PAYMENTS_ENABLED=true
STRIPE_LIVE_CONFIRMED=false
```

In Command Prompt, from the folder containing `run.py`:

```bat
py -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
python -m flask --app run setup-acuity-local
python -m flask --app run --host 127.0.0.1 --port 5000
```

The setup command asks for a 12–128 character password and creates `local.admin@example.com`, `local.mentor@example.com`, and `local.student@example.com`, all with that password in the isolated practice database. Existing practice accounts are not reset. If those accounts already exist, run `python -m flask --app run init-db` to add v0.7 tables instead.

1. Sign in as local mentor → Payments → Stripe payment setup → Set up account → Mark local account ready.
2. Sign in as local student. Select the $100 practice session (calendar 101, appointment type 201), choose a future slot, and continue to checkout.
3. Select **Simulate successful payment**. Verify payment paid, appointment confirmed, one saved Acuity appointment, $80 mentor allocation, and a separately displayed simulated processing fee. The local fee is illustrative, not a Stripe pricing quote.
4. Copy the TTBG payment reference from payment details. In another activated Command Prompt:

```bat
python -m flask --app run stripe-mock-session-ended --order PAYMENT_REFERENCE
```

5. Mentor reports completion. Admin opens Support → Payments, approves completion, then transfers. Confirm one $80 transfer. Submit the transfer action again; no second transfer should appear.
6. Admin refunds the session. Confirm $100 refunded and the $80 transfer reversed. Acuity remains scheduled until separately canceled.
7. For a free consultation, Admin/Account Manager imports appointment type **202** under the practice mentor's Services & pricing. It displays FREE and books without Stripe.
8. For a slot conflict, create a Checkout, then before simulating payment run `python -m flask --app run acuity-mock-scenario unavailable`. Payment should refund without a booking. Restore `normal` afterward.
9. For uncertain creation use `timeout_after_create`; confirm exactly one provider appointment, an uncertain status, no automatic rebooking/refund, and successful staff linking. Restore `normal` afterward.
10. Run `python -m flask --app run payments-worker --once` to exercise durable reconciliation. Signed webhook verification, replay, failed-response recovery, permission checks, and other edge cases are covered by `tests/test_v07.py`.

Local mock mode makes no Stripe or Acuity network calls, collects no real payment details, and is guarded by local environment, loopback origin/client, and the separate SQLite database. Dummy keys are accepted only in mock mode. Real Stripe test mode needs real Stripe **test** credentials and test connected accounts.

## Controlled test/live activation

- Complete the journey in local mock mode, then real Stripe test mode against a controlled Acuity test calendar. Verify US/USD accounts, onboarding, additional verification, card decline, abandoned Checkout, webhook signatures/replay, slot conflicts, refunds, and transfers.
- Validate SMTP, Acuity confirmations/reminders, public webhook delivery, and the long-running worker in staging. Ensure Acuity does not independently collect a second payment.
- Configure Stripe Connect branding with TTBG's logo, colors, business details, and support contact. Hosted pages take their branding from Stripe configuration; the API key alone cannot establish those settings.
- Approve TTBG's cancellation/no-show rules, tax/reporting responsibilities, payment terms, transfer timing, and dispute handling. This release does not calculate sales tax or implement tax-filing automation.
- Deploy code with `PAYMENTS_ENABLED=false`. Add live account credentials, webhook secrets, HTTPS origin, `APP_ENV=production`, `STRIPE_MODE=live`, `ACUITY_MODE=live`. Keep `STRIPE_LIVE_CONFIRMED=false` until approved for live onboarding/writes.
- After approval, enable live writes, onboard live mentors, check readiness, start the worker, select Acuity confirmed appointments, then enable new payments. Perform an authorized low-value live booking, refund, and transfer check before broad rollout.

## Primary technical references

- https://docs.stripe.com/connect/separate-charges-and-transfers
- https://docs.stripe.com/api/accounts/create
- https://docs.stripe.com/connect/hosted-onboarding
- https://docs.stripe.com/api/checkout/sessions/create
- https://docs.stripe.com/webhooks
- https://docs.stripe.com/api/idempotent_requests
- https://docs.stripe.com/api/transfers/create
- https://docs.stripe.com/api/transfer_reversals/create
- https://docs.stripe.com/api/refunds/create
- https://docs.stripe.com/api/versioning
