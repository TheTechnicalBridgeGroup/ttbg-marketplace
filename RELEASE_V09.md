# TTBG Marketplace v0.9.0

**Stability, Accessibility & Administrative Diagnostics**  
Controlled production pre-release, based on v0.8.0. No deployment or live financial action was performed while preparing this package.

## What changed

- Availability hides booked times across all services sharing the Acuity calendar, including overlaps partway through a session and appointment-type padding. Acuity's available-time response remains required; TTBG does not generate extra availability or bypass provider scheduling restrictions.
- In-progress TTBG bookings and payment checkouts block the full occupied interval. New requests serialize the availability check and durable request creation with a database write lock. This covers different start times, different services, and different mentees.
- Cancelled/rescheduled times use current Acuity occupancy reads, so a stale TTBG snapshot does not keep an old time blocked. The time returns only if Acuity also offers it under current scheduling rules. A cancelled 30-minute consultation does not guarantee that a 60-minute service fits.
- Availability time links refresh every 30 seconds while visible and on returning to an open tab. Failed refreshes remove the links. A stale link or open confirmation form is checked again on the server before checkout/creation.
- Signed request retries must match the original user, service, appointment type, calendar, duration, price and time. A different service never redirects to an earlier service's confirmation. New request IDs distinguish new attempts; existing accepted IDs remain idempotent.
- Paid direct bookings are blocked when checkout is disabled outside isolated Acuity mock mode. Free consultations continue without Stripe. Existing test-reservation code remains gated by Flask testing configuration; `DEMO_BOOKING_ENABLED` is unused and cannot enable live reservations.
- Post-payment Acuity confirmation is rechecked, with existing recoverable holds/refunds retained for conflicts and unknown outcomes. The 80/20 allocation, TTBG-paid processing fees, original Stripe idempotency namespace, v0.7.1 Checkout and CSP fixes, and exact staff cancellation attribution remain unchanged.
- Every password input receives an independent Show/Hide eye control, including dynamically inserted fields and reauthentication dialogs. Native buttons, accessible names, pressed state, and 44px minimum touch height; hidden by default and hidden again on submit, dialog close, form reset or page departure. Password values and autofill settings are not read/copied/logged by this code.
- Booking/payment and Connect account-setup messages now describe the relevant workflow. Missing meeting instructions are explicitly identified instead of implying a joining link exists.

## Admin → Operations & Diagnostics

Only **Admins** can access these pages or their endpoints. Account Managers retain their existing support/financial-investigation permissions but cannot use the new diagnostic workspace or record explorer.

1. **Overview:** application/environment/deployment label, an actual database SELECT, migration status, last worker completion, separately recorded API-read checks and signed webhook delivery, pending sync work/notices, and Turnstile configuration readiness. Timestamps are observations, not permanent health guarantees. A saved credential is not labelled a successful connection. SMTP acceptance is not mailbox delivery.
2. **Investigation:** search a payment reference, request ID, numeric TTBG booking ID, or error reference. See original service/price/time/duration/mappings, saved Acuity state, payment operations, and the latest 50 financial events. Booking conflicts are recorded before any checkout exists with a safe reference and selected-service metadata. No invented event chains or guessed external actors.
3. **Render logs:** server-side GET integration with web/worker selection, time/severity/status filters, newest 50 entries, maximum five pages, 24-hour maximum window, bounded bytes/timeout and a shared six-requests-per-minute limit. Search filters the **safe summaries on the current page**. Arbitrary provider log text is withheld; only recognized activity categories, normalized timestamp/severity/status and strict support-reference IDs reach HTML. This deliberately prevents leaks that regex-only redaction would miss. Open Render for complete technical messages. API failures are nonfatal.
4. **Safe record explorer:** the existing `/admin/data` route now uses explicit backend table/column allowlists. Exact IDs/references and creation dates, 25 rows per page, maximum 20 pages, two-second query budget, no unrestricted counts, SQL input, editing, or exports. Passwords, hashes, tokens, emails, free-text intake/support notes, customer payloads and credentials are not selected. Existing financial CSV exports retain their separate permissions and safeguards.
5. **PlanetScale:** actual app database reachability, migration revision, optional configured database/branch labels and a validated direct Insights link. Query error/slow-query/resource metrics remain in PlanetScale. No PlanetScale monitoring API is connected in this release; this is the explicitly permitted provider-dashboard fallback.

Diagnostic views do not run financial reconciliation, refresh/create connected accounts, mutate infrastructure, or issue refunds. Only access audits, rate counters, and diagnostic observations are persisted. For actions, use the existing authorized workflow. Prefer these UI tools and provider dashboards over direct production SQL.

## Upgrade from v0.8.0

1. Back up the database and keep the previous release and environment settings. Restore and rehearse on a separate staging database first. Never point local mock mode at production.
2. Pause new booking submissions and drain active web requests during the deployment. **Do not run old and new booking code concurrently:** the old code does not enforce the new interval guard. Keep financial reconciliation available, or restart it promptly after upgrading.
3. Install the existing dependencies and run `flask --app run.py init-db` using the target environment. This adds two tables (`market_diagnostic_probe`, `market_diagnostic_event`), the `ix_acuity_calendar_start_v09` index, and revision `v0.9-stability-diagnostics`. Existing table columns, accounts, appointments, payment allocations and provider IDs are preserved. The migration does not call providers.
4. Start the web process and the existing payment worker using the same release, database, provider account and mode. Run the staging checks below before opening new bookings.
5. In Admin → Operations & Diagnostics, verify migration status, run connection reads, and inspect actual signed deliveries and worker timestamps. Configure the optional diagnostic settings below only if needed.
6. Restore booking access after validating availability and a cancellation/rebooking cycle. Keep `PAYMENTS_ENABLED=false` until the controlled payment activation is approved; paid sessions are then unavailable, not silently free. Existing paid orders still need the worker.

There are no new Python runtime dependencies. Diagnostic tables contain sanitized references/classifications and selected service/time/price metadata, not request bodies or credentials. Shared documentation content is not overwritten during upgrade.

Rollback: pause new booking submissions, stop the new web process, restore the prior code/environment, and keep additive tables unless a separately rehearsed restore is required. Do not restore an old database over financial events created since its backup. The previous release retains the known overlap defect: leave new bookings paused until the correction is restored. Never change the `ttbg-v07-` Stripe idempotency prefix to match the release number.

## Optional environment settings

All credentials stay in hosting environment settings. They are not editable or revealed through diagnostics.

| Setting | Purpose |
| --- | --- |
| `RENDER_API_KEY` | Server-side Render API token authorized for the relevant workspace/services. |
| `RENDER_OWNER_ID` | Render workspace owner ID. |
| `RENDER_WEB_SERVICE_ID` | Web service ID (`srv-…`). |
| `RENDER_WORKER_SERVICE_ID` | Payment worker service ID (`srv-…`). |
| `DEPLOYMENT_LABEL` | Operator-supplied deployment timestamp/revision label; not automatically verified. |
| `PLANETSCALE_DATABASE_LABEL` / `PLANETSCALE_BRANCH_LABEL` | Nonsecret labels for the diagnostic summary; not auto-discovered. |
| `PLANETSCALE_INSIGHTS_URL` | HTTPS link on `app.planetscale.com`, without credentials/query/fragment. |
| `DIAGNOSTICS_DATABASE_URL` | Optional SQLAlchemy URL with **SELECT-only** access to the approved tables, preferably a read replica. Use the same driver syntax as the app's normalized URL. |

Use a separately provisioned least-privilege database credential where available. When absent, the explorer uses the application connection with allowlisted SELECT statements and transaction-level read-only mode for PostgreSQL/MySQL, plus statement limits (including the Vitess `QUERY_TIMEOUT_MS` directive, since MySQL session timeout settings can be ignored by Vitess). SQLite uses a two-second progress interrupt. Diagnostic audit/rate records still use the main write connection. A replica can lag; use the primary operational workflow for action decisions. A database-side credential is stronger isolation than application code alone.

Render account capabilities and logs retention must be checked in your workspace. Missing permissions/configuration show an explanation and dashboard link instead of breaking the diagnostic page. No infrastructure changes can be made through this integration.

## Availability boundaries and recovery

- Acuity is authoritative for available times, limits, groups, buffers, existing external appointments and cancellations. TTBG additionally enforces one-at-a-time calendar occupancy regardless of provider overlap settings.
- A TTBG checkout hold is **not a provider reservation**. An external Acuity administrator/client can still occupy a time during Checkout. Final Acuity validation and existing refund/manual-reconciliation safeguards remain essential; no app can guarantee a previously displayed time stays available indefinitely.
- Checkout timers alone never release holds. Canonical provider expiry/cancellation or a definitive rejected booking is required. Unknown appointment/payment outcomes remain held for staff reconciliation. Do not clear holds through direct SQL to make a slot appear available.
- Appointment-type buffers up to 24 hours and sessions up to 24 hours are supported. Missing/malformed types, buffer data or occupancy responses block booking safely. The bounded occupancy query includes date margins and all appointment types on the calendar. A saturated 100-appointment response is treated as incomplete; availability is withheld for review rather than assuming omitted appointments are free.
- A cancellation restores only genuinely open future time. Other appointments, an active checkout, scheduling limits, minimum advance notice or a longer service's duration may still block it. Rescheduling frees the old interval and occupies the new one according to fresh provider reads.
- Existing confirmed historical paid bookings are not retroactively changed by the new paid-checkout requirement.

## Required real-provider release gates (not completed by local tests)

- Check each mentor's Acuity calendar and availability groups; appointments per time slot must be one. Verify pre/post padding, resources and advance-notice restrictions. The diagnostic UI links/instructions do not remotely verify these settings.
- In staging, exercise free → paid and paid → free at the same time, partial-duration overlaps, two mentees competing, open-page stale availability, abandoned Checkout, expiry, confirmed cancellation/rebooking, rescheduling, missing-webhook recovery and provider timeouts.
- Check Google Meet or the chosen Acuity video integration: both mentor and mentee must receive usable joining instructions. When details are absent the app says so; generating a joining URL is delegated to Acuity's configured integration.
- Validate desktop/mobile keyboard and screen-reader behavior in real browsers. DOM checks were run; real-browser visual/keyboard testing remains necessary.
- Verify live platform readiness, authorized mentor Connect onboarding, actual Stripe/Acuity webhook deliveries, worker reconciliation, email receipts/notices and sandbox mentor transfer.
- With explicit approval, conduct one controlled low-value real payment, appointment, cancellation/refund and completed-session mentor transfer. Record the provider IDs/results; a Stripe transfer is not proof of a bank payout. This package has not made these transactions.
- Resolve all P0 failures before approving v0.9.0 for controlled production or packaging v1.0.0. Continue the feature freeze: defects, clarity and validation only.

## Provider references checked for implementation

- Acuity appointments: https://developers.acuityscheduling.com/reference/get-appointments
- Acuity appointment types and padding: https://developers.acuityscheduling.com/reference/appointment-types
- Acuity available times: https://developers.acuityscheduling.com/reference/get-availability-times
- Render logs and timestamp pagination: https://api-docs.render.com/reference/list-logs

- PlanetScale query timeout directive: https://planetscale.com/docs/vitess/scaling/planetscale-system-limits
