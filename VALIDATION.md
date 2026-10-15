# TTBG Marketplace v0.6.0 validation

Validated locally on October 14, 2026. **All 109 automated tests passed (70.33 seconds).**

## Coverage

### v0.6 Acuity booking and synchronization

- Confirmed appointment creation, persisted provider snapshots, student/mentor dashboard access, required intake, CSRF, role restrictions, signed quote validation, stale pricing, and client-field tampering.
- Repeat form submission and distinct duplicate requests do not create a second appointment. A provider timeout after creation remains uncertain and requires staff reconciliation. A database failure after provider acceptance leaves the durable request for recovery.
- Signed webhooks, invalid signatures, duplicate/out-of-order delivery, rescheduling, cancellation, provider payment labels, durable sync failures, and CLI recovery. Provider email, price, or duration changes trigger review without rewriting agreed financial amounts.
- Staff-only mapping checks, explicit linking of external appointments, password-protected reconciliation/release, and idempotent webhook registration.
- Account deletion with foreign keys enforced; later synchronization does not restore removed identity on linked records.
- Isolated mock configuration, local-only requests, dummy credentials rejected in live mode, seeded practice accounts, and CLI-delivered signed change events.
- Live transport shape checked using a mocked HTTP transport: fixed HTTPS origin, backend authentication, client-validated creation without the admin bypass, and conservative HTTP error classification. No live Acuity request was made.
- Timezone offsets across daylight-saving changes and a webhook arriving before the creation response is persisted.

### Retained platform regression coverage

- Existing onboarding, role management, password reset, commission settings, photo moderation, Support Center, redacted data views, API-key reveal, and read-only Acuity availability regressions.
- Admin-only hard deletion from Support account details; both self and every other Admin are protected. Original user records, logins, profiles, photos, and dependent private data are removed. Old sessions cannot revive through reused SQLite IDs.
- Deleting students, mentors, and account managers with foreign keys enforced. Paid/non-test booking amounts/status/dates survive under non-login archive references; other participants retain their records. Shared support/audit/documentation attribution remains readable.
- New registration remains restricted until verification. Token hashing, one-hour expiry, single use, replacement on resend, email-change invalidation, CSRF, disabled-account rejection, configured-origin links, mailbox-owner password choice, and old-session revocation.
- Verification email send failure, missing SMTP configuration, and certificate-verified STARTTLS transport behavior. SMTP calls are mocked; no real email was sent.
- Turnstile server verification, expected hostname/action, replay rejection, missing keys/network failure, and scoped CSP. Cloudflare responses are mocked; live widgets were not exercised.
- Database-backed registration/verification rate limits, trusted proxy hop selection, and additive upgrade preserving access/passwords/disabled states.
- Documentation read/write/image permissions across all four roles, escaped text, search, parent/child organization, cycle and cross-space rejection, page/image deletion, and stale version conflict checks. Two concurrent real database workers were not exercised.
- Documentation image metadata removal, WebP encoding, preserved aspect ratio, 1600-pixel resize, 500 KB output cap, input-size/type restrictions, required descriptions, 10-image limit, CSRF, and private image responses.
- Public help-guide phone link and ticket link, Admin-only phone configuration, invalid phone rejection, widget enable/disable, and role-appropriate navigation.
- Starter documentation seeds once and subsequent upgrades preserve team edits.

## Additional checks

- Python compilation and JavaScript syntax checks for booking.js, help.js, verification.js, ui.js, and theme.js.
- All 31 table definitions compile for PostgreSQL and MySQL. Workflow tests use SQLite with foreign keys enabled; no live PostgreSQL/MySQL migration was performed.
- Templates rendered through Flask test clients. No new runtime dependencies were added.

## Practical limits

The browser installation available in this environment was unusable, so desktop/mobile visual checks, keyboard focus, the help widget’s interactive conversation, and live Cloudflare rendering require a real-browser review before deployment. The phone link is a device handoff, not an embedded call or live-agent transfer. Documentation is a lightweight text-and-image knowledge base, with optimistic version checking but no revision restoration or simultaneous collaborative editor.

SMTP configuration and real inbox delivery must be checked with the production mail provider. Turnstile must be configured and tested on the actual marketplace hostname. No live account, database, hosting service, mail delivery, phone call, DNS setting, appointment, or payment was modified.

Confirmed appointment creation and synchronization are implemented. Production Acuity API entitlement, real calendar/type mappings, email delivery, and public webhook reachability require a controlled live test with your account. Stripe Connect onboarding/checkout/webhooks and automated payouts remain outside this release; appointment confirmation does not collect payment. The existing availability/contact mode remains selectable, and an upgrade does not silently enable provider writes. Account deletion does not cancel or refund external-provider transactions, remove backups, or erase all free-text references from retained shared records.
