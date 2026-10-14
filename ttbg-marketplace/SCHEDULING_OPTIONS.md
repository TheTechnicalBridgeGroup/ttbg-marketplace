# TTBG booking direction — Acuity + Stripe Connect

The provided booking conversation establishes the direction: keep Squarespace for marketing, keep the existing Flask marketplace as TTBG's user interface, use Acuity's API for scheduling, and use Stripe Connect for mentor onboarding and an 80% mentor / 20% TTBG allocation. Do not replace the marketplace or treat a visual calendar as live availability.

## Delivered in v0.4

- Native TTBG availability page, populated only by Acuity API responses for a mentor calendar and service appointment type.
- Available dates/times, timezone selection, empty/error states, and a read-only connection check.
- Existing mentor calendar, service appointment type, and Stripe connected-account reference fields retained.
- Backend environment configuration and protected admin credential reveal.
- Contact-to-confirm handoff while payment/appointment creation is incomplete. An email draft is not a reservation.
- 80/20 allocation configuration, preserved historical snapshots, support incident references, and booking lookup.

## Next integration stage — not delivered as functioning checkout

1. Platform-initiated Stripe Connect accounts and short-lived Stripe-hosted onboarding links. Mentors supply their own identity and banking details to Stripe. TTBG staff should not create shared mentor financial identities or collect Stripe passwords.
2. Verified account readiness and mapping to the correct mentor; a stored `acct_...` reference alone is insufficient.
3. Server-authoritative pricing and a coordinated appointment/payment state machine. A TTBG-only temporary lock cannot guarantee an Acuity slot is held against external bookings. Verify the selected reservation strategy with Acuity, recheck availability, and define conflict compensation before collecting money.
4. Stripe Checkout with the destination account and the application fee calculated explicitly from the agreed session allocation. The 20% share is before processing fees unless TTBG establishes another policy.
5. Signed, idempotent Stripe webhooks as payment authority; a browser success redirect must never confirm payment on its own.
6. Appointment creation and reconciliation, including retries, duplicate/out-of-order callbacks, abandoned/expired checkout, conflicts, refunds, and failed transfers. A successful charge with no confirmed appointment must enter a recoverable support state, not disappear.
7. Authenticated Acuity webhook processing for appointment changes and dashboard updates.
8. Test one mentor and one service end-to-end with Stripe test mode, including refunds and failures, before enabling live checkout. Confirm cancellation, refund, processing-fee, and notification policies with TTBG leadership.

Existing hosted links are retained as a manual fallback. They do not implement the native Connect allocation. Do not enable two independent payment collection paths for the same session.

## Configure availability

Read README's Scheduling section. Use an API-enabled Acuity account, `ACUITY_USER_ID`, `ACUITY_API_KEY`, mentor calendar IDs, and service appointment-type IDs. Support → Integrations checks authentication. Staff can inspect availability from a mentor's Support account page. Admin settings control public activation. No credentials are included in this ZIP, and no private API access was tested against TTBG's live account.

## Primary API references consulted

- https://developers.acuityscheduling.com/reference/quick-start — backend HTTPS Basic authentication using user ID and API key.
- https://developers.acuityscheduling.com/reference/get-availability-dates — month, appointment type, calendar, and timezone inputs.
- https://developers.acuityscheduling.com/reference/get-availability-times — date-specific slots for the mapped type/calendar.
- https://developers.acuityscheduling.com/reference/post-appointments — appointment creation, to implement in the next stage.
- https://docs.stripe.com/connect/destination-charges — payment allocation architecture for the next stage; verify the final account configuration before implementation.
