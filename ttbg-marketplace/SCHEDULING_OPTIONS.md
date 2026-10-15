# TTBG booking — Acuity scheduling, separate payment integration

Squarespace remains the marketing site. The Flask marketplace owns TTBG's student/mentor experience. Acuity supplies availability and confirmed appointments. The configured mentor/TTBG allocation defaults to 80/20.

## Implemented in v0.6.0

- Server-side API credentials and fixed-origin authenticated requests.
- Mentor calendar and service appointment-type mappings, with live verification of type/calendar assignment, price, duration, and supported intake requirements.
- Native TTBG availability, confirmation, provider appointment creation, and saved booking/reference/status records.
- Durable create-request tracking, duplicate-submission protection, explicit uncertain outcomes and staff reconciliation.
- Signed Acuity change webhooks, saved sync retries, manual/periodic refresh, and dashboard updates.
- External appointment storage with staff-controlled linking to existing students.
- Local dummy-key practice using isolated provider simulation, including signed changes and failures.

Read ACUITY_V06_SETUP.md for exact settings and commands. The default upgrade preserves the previous booking mode. Enable confirmed appointments only after configuring the provider and verifying a controlled real booking.

## Payment scope remains separate

A confirmed appointment is not proof of payment. This release does not charge a card, create Stripe Connect accounts, verify checkout/webhook settlement, issue refunds, or send automatic payouts. It stores the agreed financial allocation for future reconciliation and displays any Acuity payment label as provider-reported.

A future payment release still needs hosted mentor onboarding, account-readiness checks, coordinated payment/appointment states, conflict compensation, signed Stripe webhooks, refunds and reconciliation. Acuity remains the authority on slot availability; a local lock cannot reserve a time against an external Acuity booking.

Do not enable two independent collection paths for the same session. Until a payment workflow is deliberately integrated, arrange payment separately and explain that at confirmation, as the current UI does.
