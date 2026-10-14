# v0.4.1 targeted validation

Confirmed the ticket button renders on Support pages for Admin and Account Manager roles, uses the help desk’s /tickets/new route with a safe new-tab link, and is absent from student/mentor pages. The help desk attachment confirms unauthenticated users sign in before reaching the form. This change adds a link; it does not submit tickets automatically. Prior 50-test results below apply to v0.4.0.

# TTBG Marketplace v0.4.0 validation

Validated locally on October 14, 2026 (UTC). **All 50 automated tests passed.** JavaScript syntax checks also passed.

## Automated coverage

The full suite contains 50 tests: 34 existing workflow regressions and 16 new support/availability checks, including parametrized cases.

- Exact Support Center role boundaries on both GET and POST endpoints, and no staff navigation for students/mentors.
- Account lookup by name/email/ID, literal search matching, role filtering, escaped internal notes, and note audit attribution.
- Account Manager recovery limited to students/mentors; reset token single use, old-session invalidation, and session revocation.
- Credentials absent from initial HTML and database exports; per-reveal password confirmation, Admin-only access, allowlist restrictions, non-cacheable secret responses, audit without key values, and rate limiting across sessions.
- CSRF rejection and successful HTTPS same-origin support form/reveal submissions.
- Safe error-reference capture, omission of raw exception text/URLs/query parameters, resolution notes, and a 500 fallback that does not invoke database-backed context processors.
- Booking lookup and private support notes absent from student-facing pages.
- Acuity date/time mapping, mentor/service IDs, timezone parameters, future/duplicate slot handling, invalid timezone/month rejection, missing configuration, sanitized provider failures, and no appointment/booking creation.
- Fixed Acuity origin, Basic-auth construction, restricted endpoint names, redirect refusal, response-size boundary, and transport timeout configuration.
- Native availability sign-in return and public-mode gating; additive upgrade preserves users/passwords and configured fee/mode settings.

All previous onboarding, role, photo moderation, redacted reporting, password reset, commission, legacy upgrade, and test-only reservation regressions remain. Test-only booking behavior does not imply live payment processing.

## Additional checks

- JavaScript syntax checks for `ui.js` and `theme.js`.
- All 21 SQLAlchemy table definitions compile for PostgreSQL and MySQL, including photo binary storage. Workflow tests use SQLite; live database migrations were not executed.
- Templates render through Flask test-client coverage. No new runtime dependency was added.

## Limits

A Chromium headless-shell installation was attempted, but the supplied archive was unusable. Browser-level visual checks, keyboard/focus behavior, and the timed reveal dialog were not exercised in a real browser. Review the refreshed screens on desktop/mobile and light/dark themes before deployment. The server-side reveal permissions, CSRF, password verification, and throttling were tested independently of the UI.

Acuity calls were tested with controlled responses. TTBG's real API credentials, calendar/type mappings, account entitlement, and live availability still require a connection check and a one-mentor trial. No actual Acuity appointment was created or changed.

Stripe Connect onboarding, checkout, payment webhooks, refund/reconciliation handling, Acuity webhook sync, and automatic payouts are not implemented in this release. Availability uses a contact-to-confirm handoff, not an automatic reservation. No live hosting service, database, account, DNS, email, payment, or payout was modified.
