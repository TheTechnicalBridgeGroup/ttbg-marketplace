# Marketplace V1 model and integration plan

## Implemented relationships

`User → Mentor → Service` represents the approved supply side. `User (student) → Booking → Mentor + Service` represents a demo session. Each mentor currently belongs to one lane and can have many services. All account and business state lives server-side.

| Object | Main fields | Purpose |
| --- | --- | --- |
| User | name, unique email, password hash, role | Sign-in and authorization |
| Mentor | user, lane, title, bio, experience, review state/note, Acuity calendar ID | Onboarding and public profile |
| Service | mentor, name, price cents, duration, fee basis points, Acuity type ID, active | Mentor-specific offerings |
| Booking | student, mentor, service, UTC start, price/fee/earnings snapshots, state, unique slot/request keys | Demo reservation and dashboard source |
| LoginAttempt | normalized email, timestamp | Shared database-backed sign-in throttling |

The public path is: choose lane → browse mentor → select service → authenticate as a student → choose sample time → acknowledge demo mode → save reservation → view dashboards.

Mentor states: submitted → reviewing → approved, changes requested, or declined. Resubmission always returns to submitted. Only approved profiles appear publicly. Admins prepare services independently; an approved profile without services displays a coming-soon state.

All amounts are stored as integer USD cents; the fee is stored as basis points (1500 = 15%). A $100 demo session snapshots $15 estimated TTBG share and $85 estimated mentor share. These values are not collected, earned, or payable. Fee calculation rounds half up to the nearest cent. Cancellation removes the slot lock and excludes the reservation from active demo totals.

Demo time choices are three fixed starts per day, four hours apart, in America/New_York for the next seven days. Allowed service durations do not overlap adjacent generated slots. UTC is stored; availability labels include the Eastern timezone and reservation dashboards explicitly display UTC.

## Connect live scheduling and payments next

The live path is intentionally absent from beta, not a switch waiting to be flipped. Add these in a separate tested change:

1. Server-side Acuity client with credentials stored in environment variables; fetch availability for the mentor's calendar ID and the selected service's appointment type ID. Revalidate at booking time. Do not expose Acuity keys to the browser.
2. Transaction table with unique provider checkout/payment IDs, amount/currency, status, booking reference, and a separate immutable event log. Signed payment webhooks must determine payment success, not a redirect from a checkout page.
3. Pending booking before checkout and idempotent payment-event processing. Acuity scheduling can fail after payment succeeds: record a recoverable state, retry safely, and provide a refund/reconciliation path. Do not report a confirmed session until the appointment exists.
4. Persist Acuity appointment IDs. Verify supported webhook authenticity and reconcile cancellations/reschedules across systems. Do not use Acuity's admin booking override to bypass availability checks.
5. Real earnings ledger, refund adjustments, and payout-provider onboarding. Gross mentor allocation is not the same as a completed payout; processing fees and business commission policy need explicit treatment.
6. Email verification, password reset, operational email, abuse controls beyond per-email login throttling, migrations, backups, and monitoring before a public launch.

Official scheduling references:
- https://developers.acuityscheduling.com/page/how-to-schedule-an-appointment-with-the-acuity-scheduling-api
- https://developers.acuityscheduling.com/reference/post-appointments

## Existing TTBG apps

The two supplied projects were inspected for branding and stack compatibility. Their source, credentials, routes, and databases were not changed or merged into this app. The exact logo and favicon were copied as assets. Application import and help desk onboarding tickets remain manual; add an authenticated integration later rather than coupling tables across applications.

## v0.2 changes (supersede v0.1 self-application flow)

Public application CTAs and new-applicant visits to `/onboarding` go to the existing mentor application portal. Only mentors with an existing profile can use `/onboarding` to propose profile edits. The team creates marketplace profiles from approved applications.

Three new tables are additive, so upgrading v0.1 requires `init-db` but no column rewriting:

| Table | Purpose |
| --- | --- |
| market_mentor_details | Public qualifications and specialties; private contact/application/owner/notes; five readiness attestations and account activation time |
| market_mentor_invitation | One current hashed token per mentor, expiry and atomic one-time consumption |
| market_mentor_audit | Actor, action, summary, UTC timestamp for profile, state, service, activation, and price changes |

States add draft, suspended, and deleted. Delete is soft deletion: hidden by default, blocks sign-in, excludes public/booking access, retains history. Restore goes to draft. Suspension/delete revoke pending activation links and block sessions at the next request. Existing reservations are preserved, with manual cancellation available in the team workspace.

Publication requires the five recorded attestations, minimum biography/experience text, and at least one active service. Pre-v0.2 approved profiles stay published until edited or reviewed; newly publishing them requires completing the checklist. Mentor changes to credential text invalidate the credential-review check.

The onboarding role shares profile/service/booking workspace access with administrators. It cannot create other staff through a web route. Owner assignment is not row-level authorization. Private profile fields and audit information are never rendered on public mentor pages.

Mentors can change only their own service prices; server-side authorization rejects other users' service IDs. Commission and service setup remain staff-managed. Prices use Decimal input converted to integer cents. Existing booking snapshots do not change, and a server-side quote check detects prices changed between opening and submitting a reservation.

Setup tokens are random, stored only as SHA-256 hashes, expire after seven days, and are consumed transactionally. They are rendered once to staff for manual handoff; they are not stored in session cookies. New links replace old links. Existing linked student accounts retain their passwords. Activation URLs are sensitive: share only with the intended mentor. No outbound email action is performed.
