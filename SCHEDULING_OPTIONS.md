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

A confirmed appointment alone is not proof of payment. In v0.7.0, enabling Stripe payments routes paid native bookings through hosted Checkout, verifies the payment on the backend, then creates the Acuity appointment. Free consultations bypass Stripe. With payments disabled, the existing Acuity-only workflow remains available and labels payment as separately arranged.

Acuity remains authoritative for availability; local Checkout coordination cannot reserve a slot against external bookings. Definitive booking failure requests a full refund. Uncertain creation is reconciled before further action. Mentor transfers require ended-session approval and current Stripe eligibility. TTBG absorbs processing fees from its gross allocation. Do not enable another collection path for the same session.

See STRIPE_V07_SETUP.md for implemented payment architecture, setup, cancellation/refund behavior, recovery, and limitations.
