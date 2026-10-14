# Marketplace v0.4 architecture

The Flask application retains the existing user, mentor, service, booking, onboarding-detail, invitation, and mentor-audit models. New functions are split into `security.py`, `control.py`, `photos.py`, `booking_config.py`, and `upgrade.py`, `support.py`, and `acuity.py`.

## Additional tables

| Table | Purpose |
| --- | --- |
| `market_account_access` | Enabled state, session revision, and last sign-in time |
| `market_password_link` | One hashed, expiring password/setup token per account |
| `market_platform_settings` | Singleton application metadata, registration/maintenance controls, provider choice, booking mode, company share |
| `market_platform_audit` | Actor, action, target, reason/detail, and timestamp |
| `market_photo_submission` | Moderation metadata and normalized JPEG bytes for current images |
| `market_mentor_photo` | Current approved and pending submission pointers |
| `market_service_scheduling` | Provider, event reference, hosted URL per service |
| `market_mentor_integration` | Scheduling-user and future Stripe account references |
| `market_schema_revision` | Idempotent upgrade markers |
| `market_support_note` | Append-only staff notes attached to an account |
| `market_support_incident` | Safe exception/provider metadata and resolution records |
| `market_sensitive_attempt` | Staff password-confirmation failure throttling across sessions |
| `market_availability_request` | Per-account availability/readiness request throttling |

The migration is additive and runs before serving requests. It converts the legacy staff role and initializes future commissions once. Production passwords and booking snapshots are unchanged.

## Authorization and account lifecycle

`admin` is the highest application role. `account_manager` is the delegated mentor-management role; the former `onboarding` value is accepted for compatibility and migrated. All protected routes perform server-side role or ownership checks. User-submitted role and commission parameters cannot override those checks.

Every request checks disabled-account state and the session revision. Disabling, changing identity/role, or resetting/revoking access invalidates older sessions. Password links use random tokens stored as SHA-256 hashes, expire after one hour, and use a conditional database update to prevent reuse. They are rendered once for private handoff; the app does not send mail. Mentor invitation behavior remains available, with account-disable checks and revocation on access changes.

Self-demotion/disable is rejected. Identity mutation serializes through the settings row on databases supporting row locks and checks that an active Admin remains. Role changes are constrained to keep mentor/profile relationships consistent.

## Photo lifecycle

Upload → pending review → approved or rejected. A replacement never becomes public before review. Submission/review uses the mentor row as the lock on databases supporting row locks and verifies that the pending submission still matches the review request. Pending-image access is owner/staff only; public-image access additionally requires a published, enabled, non-fictional mentor.

Only JPEG/PNG/WebP still images are accepted. File size, dimensions, decoding, and normalized output size are checked. Original metadata and filenames are discarded. At most an approved image and a pending image retain bytes; historical decisions remain. SQLAlchemy uses binary storage with a MySQL MEDIUMBLOB variant. No local upload directory is required.

## Reporting and resources

The Admin database explorer enumerates application metadata tables, paginates rows, and excludes sensitive hash/blob columns at the SQL selection layer. CSV exports escape spreadsheet formula prefixes. It offers no arbitrary SQL execution. Audit writes occur with the business transaction; histories are retained.

Resources report application/runtime/database/disk state and link to hosting consoles. Host infrastructure permissions, secret rotation, server lifecycle, backups, and billing remain outside the Flask app; no cloud-provider management API credentials are present. An explicit environment allowlist supplies Acuity and future Stripe credentials; only Admins can reveal them after fresh password verification.

## Booking and allocation

Scheduling references and commission configuration are independent of the public profile model. Only validated HTTPS URLs for the selected provider can appear as hosted booking links. There are no server-side fetches to user-entered URLs. Contacts remain the default booking experience.

Allocation uses integer cents, half-up rounding, and a 2000-basis-point company default. Current service rates are updated when an Admin changes the platform share; previous booking snapshots remain untouched. Test reservations remain explicitly gated by testing mode and cannot be enabled through hosting environment variables.

See `SCHEDULING_OPTIONS.md` for the chosen Acuity/Stripe Connect architecture and remaining appointment/payment work. Saved external account references are not proof of authorization or payout readiness.

## Support security and error capture

Support routes use exact `admin`/`account_manager` checks in addition to the existing enabled-account and session-revision checks. Manager recovery targets are limited to `student`/`mentor`. Notes use escaped Jinja output and are absent from public and owner dashboards. Sensitive recovery and API reveals require current-password confirmation and CSRF. Failed confirmations share a per-staff-account 5-failure/15-minute limit persisted in the database; no password value is retained.

API credentials are retrieved by fixed identifier from an allowlist of three environment-backed settings. No arbitrary name, file, SQL query, or environment enumeration is accepted. Secret JSON uses no-store headers; masked markup contains no key suffix or full value. Browser code clears password fields after submission and clears displayed keys on close, timeout, page hiding or blur. Abort handling prevents a late response from redisplaying a key after the dialog is closed. Confirmation is per request, with no reusable unlock flag.

Flask's `got_request_exception` signal captures safe metadata and adds a random reference to the 500 response. Handled Acuity failures create equivalent incidents. A static fallback 500 page does not require database context. Support records never include raw URLs, posted form bodies, request headers, provider response bodies, or raw exceptions. Hosting logs remain the admin's deeper technical source. Audit notes entered by staff are text, so staff must avoid entering secrets manually.

## Acuity read-only adapter

The server uses HTTPS Basic authentication at fixed Acuity endpoints for `/me`, `/availability/dates`, and `/availability/times`. It never sends credentials to the browser for normal availability requests. Redirects are rejected, network calls have a 10-second timeout, and responses are limited to 1 MiB. The authenticated request rate is limited to 20 page/check requests per minute per account; a calendar page makes at most two provider calls. This is a basic application throttle, not a distributed edge rate limiter.

Every availability page rechecks service activity, mentor publication/account access, and the platform provider/mode. Staff can inspect a publicly eligible mentor/service before activating native availability for students. Dates are validated against the selected month, a six-month horizon, and the selected IANA timezone. Returned times must have a UTC offset and fall on the requested date; past/duplicate slots are discarded. No synthetic fallback slots, appointment writes, payment transactions, or reservation locks are created. Selecting a slot creates only a local mailto draft, with explicit instructions that TTBG must confirm it.
