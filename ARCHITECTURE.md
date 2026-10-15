# Marketplace v0.6 architecture

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

Every request checks disabled-account state and the session revision. Disabling, changing identity/role, or resetting/revoking access invalidates older sessions. Password links use random tokens stored as SHA-256 hashes, expire after one hour, and use a conditional database update to prevent reuse. They are rendered once for private handoff; these private setup/reset links are not emailed automatically. v0.5 sends separate mailbox-verification messages through SMTP. Mentor invitation behavior remains available, with account-disable checks and revocation on access changes.

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

## Acuity transport and availability

The backend transport uses a fixed HTTPS Acuity origin, HTTP Basic authentication, an endpoint/method allowlist, redirect refusal, a 10-second socket timeout, and a bounded JSON response. The API key stays server-side. Live requests never use admin=true to bypass availability or intake validation. Availability supports mapped calendar/type IDs and explicit IANA timezone handling; times require UTC offsets.

v0.6 retains the original read-only availability/contact mode and adds the explicit acuity_confirmed booking mode. Neither mode collects payment. Mock mode dispatches to a local simulator before any network operation and is guarded by local environment, loopback origin, SQLite database name, and remote address checks.

## v0.5 identity lifecycle

`market_email_identity` holds an email snapshot, verification time, explicit legacy/bootstrap exemption, hashed single-use token and expiry, and last-send time. A SQLAlchemy before_flush listener attaches pending identities to new users and clears verification whenever an ORM-managed email changes. The one-time upgrade exempts existing rows without claiming mailbox verification. The request guard restricts pending accounts to verification, logout, health/static assets, and existing account-setup/reset routes. Profile publication and public image/availability access require verified/exempt identity.

Verification links carry the random token in the URL fragment, which is not sent in HTTP URLs/referrers. A local script moves it to a CSRF-protected POST. GET does not consume it. Confirmation atomically consumes the email-bound, unexpired token, lets the recipient choose their own password, and invalidates earlier sessions/reset/invitation links. It does not automatically authenticate the bearer. Raw tokens are never stored in the database, sessions, audit records, or exposed on support screens.

SMTP uses certificate-verified STARTTLS/SSL with authentication and a timeout. Public registration is closed if configuration is incomplete; sending failures preserve a pending account for retry. Mail URLs use only validated PUBLIC_BASE_URL, never request Host. Delivery is synchronous with a 10-second socket timeout, not a durable queue; monitor delivery and add a worker/outbox when actual volume requires one.

`market_security_rate` contains atomic counters with expiries and HMAC keys. It supports registration/verification limits, resend cooldown/daily cap, and local Turnstile replay protection. The pruning CLI removes expired entries. Turnstile validation uses a fixed HTTPS endpoint, refuses redirects, limits response size, and checks an explicit hostname/action allowlist. CSP changes are limited to the two protected pages.

Deletion rechecks permissions, password, confirmation email, the prohibition on deleting any Admin account in the transaction. Paid/non-test booking snapshots retain their identifiers, amounts, status, and dates; deleted participant references move to non-login archives and goals are cleared. For a deleted mentor with retained bookings, a hidden archive mentor/service supplies non-personal foreign-key targets. It deletes dependent records in FK order. Shared author/reviewer attribution moves to a new disabled archive principal and onboarding ownership becomes unassigned. The original account row is physically deleted; archive principals cannot authenticate or be edited/deleted in the account UI. Allocating the archive principal before deletion prevents old SQLite account IDs from being reused. No external provider deletion is performed.

## v0.5 shared documentation and guided help

`market_knowledge_page` stores space/title/body, a self-referencing parent, last editor/time, and an optimistic version counter. `market_knowledge_image` stores compressed WebP pixels and accessibility captions. The role decorator restricts all page/image reads to admin/account_manager/mentor and mutations to admin/account_manager. Text rendering escapes every input before constructing supported heading/list/paragraph markup. Image validation bounds upload bytes, megapixels, animations, final dimensions/bytes and per-page image count. Original metadata is not retained.

Mutations serialize on the existing platform-settings row in databases supporting row locks, then use a conditional version increment to reject stale requests. Parent changes reject cycles and cross-space parenting; deleting a parent reparents its children. SQLite uses its normal write locking and is for local use. Audit records track page edits/deletes and image removals. Only the current document version is stored; there is no rollback/revision-content archive.

`market_help_settings` is additive, with a public phone number and enabled flag. Admin settings changes require the existing password/reason confirmation. The help widget uses local JavaScript topic matching and textContent, without a chat API, remote data transmission, or browser persistence. Server-rendered links respect roles. Calling is an explicit tel: handoff; live-agent transfer/presence is not implemented.

## v0.6 create and synchronize

A signed 30-minute quote binds the logged-in student, service, start time, timezone, mapping, current account scope, price, duration, commission and request nonce. POST validates the quote and required intake answers, rechecks availability, revalidates publication/access/price under a platform row lock, and commits an AcuityRequest before making one provider POST. A unique request key and per-user/calendar/time deduplication key prevent repeated submissions from creating multiple requests. Provider-side client validation remains the final availability authority.

AcuityAppointment stores a unique (mode/account, provider ID) snapshot and optional links to a TTBG Booking/request. Successful creation commits these together. Definitive validation errors release the local deduplication key. Timeouts, malformed success, provider 5xx/429 responses and local persistence failures remain uncertain/creating; automatic retries never repeat a create POST. Staff can match exact email/calendar/type/original time to an existing appointment, or deliberately release a request after checking Acuity directly. The provider does not supply an idempotency contract used by this implementation, so exactly-once delivery across a network failure is not claimed.

Signed callbacks use constant-time base64 HMAC-SHA256 verification of raw bytes, with the API key (or optional static-webhook secret). Only this endpoint is CSRF-exempt; it works during maintenance. A durable per-provider sync job is recorded before fetching current provider state. Duplicate/out-of-order events fetch the current source rather than applying an old event action. Per-job database row locks serialize refreshes on production databases; the existing platform-settings lock serializes snapshot linking and account deletion. All foreign keys/unique constraints remain enforced.

Webhook failures return HTTP 500 and retain a pending job. The sync-acuity CLI retries jobs and refreshes the oldest saved records, without create retries. No separate queue worker is required; webhooks process synchronously with bounded provider calls. Configure periodic invocation with the host scheduler for recovery beyond Acuity's retry window. SQLite is supported for local practice, not a multiworker production locking guarantee.

Unknown external appointments stay unlinked and staff-only. No email-based automatic account creation or reassignment occurs. Staff must authenticate and explicitly link a verified student and matched service. Reschedules/cancellations update schedule state. Client/mapping/price/duration changes require review. Original financial allocation snapshots stay intact. Already-linked account deletion sets an identity_removed flag so subsequent fetches do not restore names/emails/locations. The app does not cancel external appointments when deleting accounts.

AcuityMockAppointment and AcuityMockConfig provide fixed local calendar 101/type 201, persistent simulated provider state, scenario switches, and correctly signed local webhook delivery. Dummy mode requires a separate marketplace-mock.db and cannot start on Render or with a public origin. Live mode refuses that database filename. Simulator behavior cannot validate live account settings or plan entitlement.
