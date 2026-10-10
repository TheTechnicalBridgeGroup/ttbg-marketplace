# Marketplace v0.2.2 validation

Validated locally on October 10, 2026 (UTC): **23 automated tests passed**.

## Covered behavior

- Registration, sign-in, authorization, login throttling, and CSRF rejection.
- Mentor creation, editing, publication readiness, and public/private field separation.
- Activation links, expiry, revocation, and mentor-owned price changes.
- Suspension, recoverable deletion, retained history, and restoration.
- Additive initialization against an existing SQLite schema.
- Public directory and direct profile URLs exclude flagged fictional mentors without deleting them.
- Published mentor counts exclude fictional records.
- Normal runtime blocks simulated reservation creation even when an old environment setting or an explicit simulation flag is present.
- Existing historical records render without prerelease labels and are excluded from financial dashboard totals.
- Public pages, staff pages, account pages, and health responses use the updated presentation.
- Existing reservation simulation regression checks run only under explicit automated-test configuration.

The existing test helper was corrected to select the reservation-time field rather than the first select element, which is the light/dark theme selector.

## Release scope

No database columns, stored status values, passwords, or branding assets were changed. The fictional-profile seeder and obsolete screenshots were removed. Legacy storage identifiers remain for database compatibility and do not appear as interface labels.

This validation used a local SQLite database and Flask's test client. No live GitHub repository, Render deployment, hosted database, DNS, Acuity connection, or payment provider was changed or verified. No browser screenshot review was performed for this release. Live in-app scheduling, checkout, and payouts are not implemented.
