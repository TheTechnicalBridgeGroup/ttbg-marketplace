# TTBG Marketplace v0.8.0 — Financial Operations & Payment Reliability

This release builds on the supplied working v0.7.1 source. It preserves the narrow Stripe Connect/Checkout redirect CSP and the removal of the unsupported Checkout `payment_method_types` request parameter. Original payment operation IDs and the `ttbg-v07-` Stripe idempotency prefix are retained so upgrading never turns an old recovery attempt into a new financial write.

TTBG continues to absorb processing fees. The original price, commission basis points, mentor allocation, TTBG gross allocation, Stripe references, destination account, and Acuity reference remain on each existing order. A default $100 session still allocates $80 to the mentor; actual processing fees reduce TTBG's share.

## What is included

- Stable friendly payment references: `PAY-2026-000041`, `TEST-PAY-2026-000041`, or `SIM-PAY-2026-000041`. Technical IDs are preserved. The numeric sequence is global, may have gaps, and does not reset annually.
- Session payment search across friendly/internal IDs, customer name/email, mentor name, service, Stripe references, and Acuity appointment ID.
- Combined payment, appointment, earnings, action-required, and date filters; explicit date timezone; sorting; filter-preserving pagination; review presets; CSV export of the full filtered result, bounded to 10,000 records.
- Filtered collected/refunded amounts and untransferred contractual mentor allocations. These are not company profit. Test/mock scopes never enter live reporting. Fee totals include only values Stripe has reported.
- Exact cancellation attribution for staff, including immutable actor name, role, account ID, request, approval, reason, and timestamps. Unknown external initiators are explicitly unverified. Natural expiry is not attributed as a cancellation.
- Independent payment, appointment, cancellation, refund, and mentor-earnings states. Cancellation does not imply a refund; a Stripe transfer does not imply a bank payout.
- Guided cancellation review, safe unpaid Checkout expiration, full remaining refunds, provider-result reconciliation, refund history, transfer holds, and recovery of refunded transfers.
- Append-only financial events, including failed/uncertain attempts, provider references, safe errors, before/after status snapshots, and approved amounts. Operator corrections produce additional events.
- A simpler mentee page with session/payment/refund status, original and refunded amounts, Stripe receipt access, and support. Internal allocation cards, operation IDs, and staff financial controls are restricted.
- Clear mentor earnings stages, completion submission, an oldest-session-first approval queue, and authenticated access to the mentor's Stripe Express dashboard.
- Payment-worker heartbeat, pending webhook/recovery visibility, fresh provider rechecks, financial notice outbox, and Admin review of ambiguous notice delivery.

## Upgrade safely

1. Use a nonproduction copy of your database first. Take a provider-supported backup of the production database and **test that it restores** before deploying. Verify user/account counts, booking counts, payment amounts, and provider references on that restored copy. No live provider database backup or restore was performed during this release build.
2. Preserve your current `.env`/hosting environment, `SECRET_KEY`, `DATABASE_URL`, Stripe account/mode/secrets, Acuity configuration, and SMTP credentials. The delivered archive includes example environment files only. It excludes local runtime data, virtual environments, and git metadata.
3. Disable new paid Checkout during the upgrade window with `PAYMENTS_ENABLED=false`. Keep payment recovery available. Pause worker processes while running the schema upgrade; avoid simultaneous first-time `init-db` commands.
4. Install the source and existing requirements. Run once:

```text
python -m flask --app run init-db
```

5. Start the v0.8 web service and its dedicated payment worker with the **same database and provider scope**. Verify `/health` reports `0.8.0`, sign in, and open Support → Payments.
6. Recheck representative existing orders. Verify original allocations/references, friendly references, historical import events, and current Stripe/Acuity state. Test a new sandbox booking and all critical cancellation/refund/transfer paths before live reactivation.

Six additive tables are created: `market_payment_identity`, `market_financial_event`, `market_payment_cancellation`, `market_payment_refund`, `market_payment_worker_health`, and `market_payment_notice`. There are 44 application tables in total. Existing table columns are not changed. Additive indexes cover scope/date/status and common new financial relationships/references. The upgrade backfills identities and a recorded import event without changing existing payment amounts, account access, or provider objects. One editable financial operations guide is added to Documentation.

Friendly identity names are snapshots of the participants known at creation/import. Actor identity snapshots preserve the name and role at the time of an action. Deleting or renaming a login does not erase those snapshots. Prior actor identities are not guessed from current roles. Successful Stripe/Acuity verification times are stored separately from refresh-attempt and cached-state timestamps; a failed request does not advance the successful verification time. Historical saved Acuity cancellations are marked initiator unverified; their original cancellation timestamp remains unknown rather than being fabricated as the migration time.

The financial audit table is append-only through application ORM writes; its web interface has no edit/delete action. Restrict direct database credentials appropriately. A database owner with arbitrary SQL privileges remains outside these application controls. No claim of tamper-proof external/WORM storage is made.

## Permissions

| Action | Mentee | Mentor | Account Manager | Admin |
| --- | --- | --- | --- | --- |
| View payments | Own | Own earnings | Existing authorized staff scope | All current-scope records |
| Request cancellation | Own | Own sessions | Yes | Yes |
| Close verified unpaid Checkout | Own | No | No | Yes |
| Cancel paid/confirmed session | Request review | Request review | Recommend/request | Verify and execute |
| Request refund review | Own | No | Recommend/request | Yes |
| Approve full refund / transfer / recovery | No | No | No | Password + reason + confirmation |
| Report completion | No | Own session | No | No |
| Approve completion | No | No | No | After verifying the ended session |
| View financial audit/export | Own relevant updates | Own relevant updates | Authorized staff | Full |
| Manage Stripe Express account | No | Own connected account | No | Existing staff verification tools |

Account managers do not gain payment-cancellation, refund-approval, or money-transfer privileges in this release. Their cancellation request names remain visible. If an Admin processes their request, **Requested by** identifies the Account Manager and **Cancelled by / Processed by** identifies the actual Admin. Every endpoint enforces role/ownership; hiding a button is not authorization.

## Cancellation and refund workflow

### Mentee / mentor / Account Manager

Open the session's payment details and choose Request session cancellation. Supply a standard reason and details. This immediately holds earnings. Paid sessions require Admin review; no refund is claimed merely because a request exists. An owner can close their unpaid Checkout only after current Stripe state confirms it is still unpaid. A payment that completes during that race moves to staff review instead of being incorrectly called cancelled without charge.

### Admin

1. Support → Payments → Review → Review / process cancellation.
2. Inspect the original session amount, verified payment/refund amounts, appointment state, and whether the mentor transfer was released.
3. Select a standard reason, enter details, confirm your password, and acknowledge the financial impact.
4. If policy permits, explicitly select **Approve a full remaining refund after cancellation is confirmed**. Otherwise cancellation leaves the payment/refund decision separate.
5. Confirm. TTBG persists the actor/approval before a provider write. Unpaid sessions use Stripe Checkout expiration. Confirmed appointments use Acuity's Admin cancellation endpoint. An uncreated paid booking request can be closed without claiming an Acuity appointment existed.
6. Read the verified results. An Acuity cancellation may be confirmed while a refund is pending or failed. A refund may succeed while recovery of a mentor transfer still needs attention.

The system checks provider state again on submission. A completed/ended booking is routed to post-session refund review, not ordinary cancellation. A creating/uncertain Acuity appointment must be reconciled first. An ambiguous cancellation response is rechecked by reading the provider; the worker never blindly resubmits an Acuity cancellation write.

**Cancellation policy remains an Admin decision.** No automatic 24-hour rule, no-show forfeiture, mentor penalty, or partial-refund split was invented. Set TTBG's approved customer-facing `PAYMENT_POLICY_TEXT` in the existing environment. Partial-refund creation through TTBG is deliberately deferred until the mentor allocation rule is agreed. External partial refunds are detected and held for settlement review; they are not silently expanded to full refunds.

Cancelled by always appears on staff payment records:

- `Admin · Account name` for a verified Admin action.
- `Mentee` for a verified owner cancellation of unpaid Checkout.
- `External / Acuity · Initiator unverified` when cancellation is observed externally.
- `—` when no cancellation is confirmed, including natural Checkout expiry.

Requested, performed, and approved actors are distinct. A mentor or Account Manager request does not falsely identify that person as the confirmed cancellation actor. No-show status is accepted from Acuity's verified `noShow` field and holds earnings for review; it does not trigger an invented refund rule.

## Refund and earnings review

Full remaining refunds preserve the original charge and append refund evidence/history. Standard reasons are required; customer recommendations and Admin approval are recorded separately. Statuses distinguish requested, pending, succeeded, failed, and uncertain outcomes. Failed refunds are retried explicitly only after canonical verification; an uncertain result is reconciled first.

A financial action's authorization succeeding does not mean every provider operation completed. Use the actual refund state, transferred/reversed amounts, and provider references in the timeline. Known full external refunds trigger recovery of a TTBG mentor transfer. Partial external refunds and unexpected external transfers hold further transfers for manual investigation. Full reversal can fail after a bank payout or due to insufficient balance; it does not undo an already confirmed customer refund.

Mentor completion reports never approve their own earnings. Admins must verify attendance, then approve completion and explicitly release the saved mentor allocation. Release refreshes the appointment, payment/refund/dispute state, account readiness, and available funds. A committed operation lease and Stripe's durable idempotency key guard duplicate/concurrent submissions. Only a successful Stripe transfer is described as Transferred to Stripe. No new bank-payout assertion is made.

The Awaiting payout approval preset includes ended sessions awaiting a completion report or Admin approval, sorted oldest session first. Ready for transfer means saved approval exists; funds/account/provider eligibility are still rechecked on submission.

## Worker, provider synchronization, and monitoring

Keep the required worker from v0.7 running:

```text
python -m flask --app run payments-worker
```

Or schedule one-shot batches every minute:

```text
python -m flask --app run payments-worker --once --limit 100
```

Use one dedicated worker initially. The supplied `render-worker.yaml` is a separate deployment template, not an activated service. It needs the same database, secret, and provider environment as the web service. Existing `render.yaml` remains the web service blueprint.

Support → Payments displays last completed reconciliation batch, recent heartbeat, failures, pending webhook jobs, financial notice delivery, and action-required records. Healthy requires a completed error-free batch within five minutes. A long-running batch or quiet webhook destination may still need investigation; an empty inbox alone does not prove Stripe delivery is configured.

Active payment recovery is prioritized over settled history. Reconciliation refreshes linked Acuity appointments as well as Stripe records, so cancellations made directly in Acuity can be detected even if a webhook was missed. Existing Acuity automatic webhooks remain important for timely reschedules/cancellations. Finance holds and completion approval resets apply to those changes. Use Recheck with Stripe and Acuity to inspect the original transaction; it never creates a replacement charge.

Current scope (mode plus TTBG platform account ID) controls all staff reports and exports. Restoring an older scope is required to investigate its records. CSV exports exclude credentials, intake answers, card/bank/identity data, raw provider payloads, and password hashes. Spreadsheet formula prefixes in text are escaped. Large exports require narrowing the filters rather than silently truncating.

## Financial email notices and receipts

Acuity continues to own appointment confirmations/reminders. TTBG does not send a duplicate booking-confirmation email. Its financial outbox sends cancellation/refund updates that distinguish appointment state from money state. When SMTP is configured, the Admin Acuity cancellation requests no provider cancellation email and TTBG queues the combined status notice. Without SMTP readiness, Acuity's normal cancellation email remains enabled.

The payment worker delivers queued notices with existing verified SMTP settings. Mock mode suppresses actual delivery. A process interruption or SMTP error during send is marked ambiguous and is not blindly resent. Staff can inspect Support → Payments → Review financial email notices. Only an Admin, after checking mail-provider logs and confirming a password/reason, can record a verified send or authorize another attempt. In-flight notices must be at least ten minutes old. Another delivery attempt can produce a duplicate if prior delivery was actually successful.

The Stripe receipt link is fetched from the original verified charge and redirects only to the permitted Stripe receipt host. No receipt URL or private Express login link is exposed through a generic database export. Manage Stripe account is restricted to the authenticated mentor and a platform-owned connected account; returning from Stripe is still not proof of readiness.

## Local practice and acceptance

Use `.env.mock.example`, the separate `marketplace-mock.db`, and the existing setup command in STRIPE_V07_SETUP.md. Upgrade existing local practice accounts with `init-db`; do not reset your production credentials or database to practice.

Test these in local simulation, then Stripe Sandbox with a controlled Acuity calendar:

1. Successful paid booking, free consultation, abandoned/expired Checkout, definite Checkout rejection, duplicate/out-of-order signed events, and post-payment slot conflicts.
2. Owner cancels unpaid Checkout; Admin cancels paid session with and without a refund; mentor/manager requests cancellation; external Acuity cancellation; payment completes during an unpaid-cancellation race.
3. Refund succeeds, remains pending, fails, or has an unknown response; full refund after a mentor transfer; reversal failure/recovery; external partial refunds remain held without an invented allocation adjustment.
4. Mentor reports completion; Admin verifies/approves; one exact saved allocation is transferred despite repeated attempts; refunds/cancellations/disputes stop further transfers.
5. Friendly and provider ID search, combined filters, date/timezone boundaries, pagination, full-filter aggregates, scope separation, formula-safe export, and exact staff cancellation attribution.
6. Unauthorized money endpoints, CSRF, wrong password, audit immutability, actor snapshots after rename/deletion, worker interruption/read-only cancellation recovery, and notice delivery review.
7. Migration on a restored database preserves all prior accounts, payment amounts, scope, and technical/provider IDs. New references are additive. Test real provider webhook delivery and SMTP acceptance/inbox outcomes separately.

The automated suite exercises local provider simulations, transport constraints, database behavior, and server-rendered pages. It does not substitute for TTBG's real Stripe Sandbox/Connect eligibility, Acuity plan/calendar, staging SMTP, and final controlled live verification.

## Compatibility and rollback

The real v1 Stripe account integration and pinned API version are retained, including v0.7.1's successful fixes. Stripe's live Connect account-creation eligibility must still be confirmed for TTBG; Accounts v2 migration is a separate integration project requiring live configuration review, not something inferred from sandbox acceptance.

Do not delete financial history to roll back a page change. Keep provider recovery running, disable new checkout, and prefer a forward fix. A source rollback to v0.7.1 would omit v0.8 cancellation, audit, monitoring, and notice processing; retain/export the v0.8 records and reconcile every outstanding operation before considering it. A database restore must not erase real payments made after the backup. Preserve the new tables even if a temporary web rollback is necessary.

## Primary provider references

- https://developers.acuityscheduling.com/reference/put-appointments-id-cancel
- https://docs.stripe.com/api/checkout/sessions/expire
- https://docs.stripe.com/api/accounts/login_link/create
- https://docs.stripe.com/connect/separate-charges-and-transfers
- https://docs.stripe.com/api/idempotent_requests
- https://docs.stripe.com/webhooks
