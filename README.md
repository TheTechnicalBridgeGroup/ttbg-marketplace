# TTBG Marketplace — v0.7.0

TTBG v0.7.0 adds **Stripe Connect, hosted Checkout, verified payment webhooks, Acuity booking recovery, refunds, mentor earnings, and Admin-approved transfers**. **TTBG absorbs Stripe processing fees** out of its gross allocation; the default mentor share remains 80% of the session price. Start with **STRIPE_V07_SETUP.md** for upgrade steps, local dummy-key practice, real Stripe test mode, and controlled live activation. New paid checkout is disabled by default. No existing accounts are disabled or reset.

The Acuity appointment-type import from v0.6.7, FREE consultations, confirmed appointment synchronization, four-role access model, account deletion, verification, Turnstile, support, documentation, and TTBG navy/gold design are retained.

## Role hierarchy

| Capability | Admin | Account Manager | Mentor | Mentee / Student |
| --- | --- | --- | --- | --- |
| Create staff/student accounts; manage roles and account access | Yes | No | No | No |
| Permanently delete any non-admin account | Yes, with confirmation | No | No | No |
| Create and manage mentor profiles and services | Yes | Yes | Own profile and prices | No |
| Issue password resets and revoke sessions | All accounts | Students and mentors only | No | No |
| Support account search, internal notes, activity, booking lookup, error triage | Yes | Yes | No | No |
| Reveal an allowlisted API credential after password confirmation | Yes | No | No | No |
| Submit mentor profile pictures | Any mentor | Any mentor | Own picture | No |
| Approve/reject/remove published mentor pictures | Yes | Yes | No | No |
| Platform settings, commission, maintenance, metadata | Yes | No | No | No |
| Database explorer, CSV pages, statistics, audit, diagnostics | Yes | No | No | No |
| Import and update services from an Acuity Appointment Type ID | Yes | Yes | No | No |
| Scheduling URL/event references | Yes | Yes | View own service prices | No |
| Investigate payment status and recovery | Yes | Yes | Own earnings only | Own payments only |
| Approve completion, transfer, refund, recover money | Yes, password + reason | No | No | No |
| Hosted Stripe onboarding | Link verified existing accounts | No | Own connected account | No |
| Browse public mentors and provider booking links | Yes | Yes | Yes | Yes |

Existing `admin` accounts stay Admins. Existing `onboarding` accounts become Account Managers during `init-db`. This avoids silently removing anyone’s administrative access; an Admin can reassign other staff after deployment. Mentor accounts remain tied to mentor profiles, so staff roles cannot be attached to an existing mentor identity through the role editor.

## Admin workspace

Sign in and choose **Admin** in the main navigation.

- **Platform overview:** account totals, signups in the last 30 days, accounts by role, mentor publication states, services, pending pictures, and table record counts.
- **Accounts:** find accounts, create Account Managers, Admins, and students; create mentors through the existing mentor-profile workflow; change identity details and roles; enable/disable access; revoke sessions; issue password-reset links.
- **Settings & booking:** site title and description, support address, student registration, maintenance mode, scheduler choice, hosted booking links, and company share.
- **Database:** paginated access to every application table and CSV exports of the displayed 50-record page. Password hashes, reset-token hashes, and photo bytes are excluded. Use task-specific forms to make changes.
- **Audit history:** identity changes, profile actions, commission/settings changes, exports, and photo decisions. Existing older mentor-only events remain visible in mentor history and the database explorer.
- **Resources:** application/runtime information, database connectivity, disk capacity, and hosting-console links. Actual server restarts, scaling, deployments, secrets, backups, and billing remain in Render/PlanetScale. This release does not connect to their infrastructure management APIs or provide a web shell.

Sensitive account/configuration actions require the acting Admin’s password and a reason. Admins cannot disable/demote themselves or remove the last enabled Admin. Account changes and resets invalidate previous sessions and unused links. Staff/mentor identity linking remains explicitly confirmed and cannot take over an existing staff account.

## Account creation and password resets

1. Open **Admin → Accounts → Create staff or student**. For mentors, choose **Create mentor** instead.
2. Enter the person’s name, email, role, reason, and your own Admin password.
3. Copy the one-time setup link shown after saving and privately give it to that person.
4. The person verifies their email using the emailed link and chooses a password of at least 12 characters. The private setup link remains available but grants only restricted access until email verification is complete.

For an existing account, choose **Manage → Reset password**. Links expire after one hour, work once, and replace earlier links. They are hashed in storage; passwords and plaintext tokens are not logged. Password-reset links for existing verified accounts still use private handoff. New web-created accounts receive a verification email when SMTP is configured; setup links do not bypass verification. Existing mentor onboarding links still work and expire after seven days.

Disabled accounts and suspended/deleted mentor profiles cannot sign in or complete password setup. Re-enabling an account does not republish a suspended mentor profile.

## Mentor profile pictures

Mentors choose **My dashboard → Manage my profile picture**. Staff choose **Mentor overview → Profile picture** to submit on behalf of a mentor.

- JPEG, PNG, and WebP still images; maximum upload 5 MB and 16 megapixels.
- The server verifies and decodes the file, crops to 512 × 512, and re-encodes JPEG pixels without original filenames or EXIF metadata.
- Photos are stored in the database, not Render’s ephemeral filesystem.
- A new submission enters **Photo approvals**. The previous approved image stays public until its replacement is approved.
- Admins and Account Managers can approve, request a replacement with feedback, or remove the published picture. A staff upload also enters the queue rather than publishing automatically.
- Pending/rejected pictures are not public. Private images are restricted to the owner and staff. Hidden/disabled mentors’ photos are not publicly served.
- Superseded/rejected image bytes are discarded; review metadata is retained. At most the current approved and current pending picture are retained per mentor.

## Scheduling and the 80/20 split

The first v0.3 upgrade sets the future session allocation to **80% mentor / 20% TTBG** for existing services. Existing booking snapshots are preserved. Admins can subsequently change the platform share; Account Managers and mentors cannot override it. Calculations use integer cents and preserve the full session total after rounding.

The chosen direction is **Acuity for scheduling, Stripe Connect for payments**, with TTBG retaining the student-facing interface and mentors completing their own Stripe-hosted financial onboarding.

This release implements native Acuity appointment creation and synchronization:

1. Configure your Acuity User ID and API key, then verify mentor calendar/service type mappings in Support.
2. Enable automatic synchronization from Support → Appointment sync. This registers a signed Acuity change webhook.
3. Select Acuity confirmed appointments in Admin settings. Students choose a time, provide their details/intake answers, and confirm in the TTBG interface.
4. The server rechecks availability, creates the appointment using Acuity's normal client validations, then saves its provider ID, date/time/status, local booking, and allocation snapshot.
5. Acuity changes update saved appointments through signed webhooks and a retryable synchronization command. Student and mentor dashboards show the appointment.
6. Timeouts after creation become explicit uncertain requests; the app does not blindly retry. Staff reconcile the existing appointment from Support.

The existing availability + contact and hosted-link modes remain optional. Upgrading does not silently enable provider writes. For a complete walkthrough, including `.env` dummy credentials, test accounts, failure scenarios, and live activation, read **ACUITY_V06_SETUP.md**. Dummy mode uses a separate SQLite database and never calls Acuity. Live mode uses a fixed Acuity HTTPS origin with backend-only credentials.

External appointments are saved by webhook/ID fetch and remain staff-only until explicitly linked to an existing student. When v0.7 Stripe payments are enabled, payment is verified before a paid appointment is created. Transfers remain separately approved after completion. See STRIPE_V07_SETUP.md.

## Support Center

Choose **Submit a ticket** in the Support Center header to open the existing TTBG help desk new-ticket form in a separate tab. Sign in with your help desk account if prompted; marketplace sign-in is not shared with the help desk. The button is available only within the staff-only Support Center.

Only the exact `admin` and `account_manager` roles can access `/support`, including its POST actions. The legacy `onboarding` role must be migrated through `init-db`; it does not grant Support Center access on its own.

- Search all accounts by name, email, numeric ID, and role.
- See enabled/restricted status, recent sign-in attempts, mentor links, the latest account/mentor activity, and recent stored bookings.
- Write internal, append-only notes. They are never shown on student/mentor dashboards and record the author and time.
- Generate one-time reset links or revoke sessions with your own password and an audit reason. Account Managers can perform these actions only for students and mentors. Admins can also help staff accounts. No automatic email is sent.
- Find stored bookings and inspect their recorded allocation and status. Stripe payment details fetch verified provider state; historical non-Stripe booking records retain their original labels.
- Triage unhandled application errors and Acuity request failures using a reference ID. Errors record only the route template, method, type, affected account if signed in, and time. They exclude raw exception messages, URL parameters, request bodies, and credentials. Both staff roles can add resolution notes and close an issue.
- Check Acuity connectivity without receiving credential values. If the database is unavailable, an error reference is written to hosting logs where possible; no database incident can be guaranteed during that outage.

The account timeline shows up to 50 recent events; notes and search results paginate. Tracking begins with events the application actually records; it cannot reconstruct missing historical activity. Maintenance mode retains the existing admin-only access rule, including Support Center.

## Protected API-key reveal

**Support → Integrations** reports whether credentials are configured. Admins see masked values and a **Reveal key** button. Every reveal opens a dialog and requires the current admin password. The value is sent only after verification, never embedded in the original HTML. Account Managers see readiness only.

The allowlist is `ACUITY_API_KEY`, `ACUITY_WEBHOOK_SECRET`, `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, and `TURNSTILE_SECRET_KEY`. Values remain in hosting environment settings; no new secret database or key-editing UI is added. `SECRET_KEY`, database URLs/passwords, user password hashes, and arbitrary environment variables cannot be revealed through this endpoint. User passwords remain one-way hashes and are never recoverable or displayed.

Reveal responses are non-cacheable. The value is removed from the dialog after 30 seconds, on close, tab hiding, or window blur. No key is saved to browser storage or written to audit records. A successful reveal records actor, credential name, and timestamp. Each reveal requires fresh password confirmation; five failed support-password confirmations within 15 minutes temporarily block additional confirmations for that staff account, across sessions. CSRF checks apply. Authorized admins can still inspect or copy a revealed response; automatic hiding is a display safeguard, not revocation of access to a secret already revealed.

## Interface updates

The existing navigation and booking flow remain. Navy/gold styling now includes softer cards, clear active-page navigation, responsive layouts, dismissible notices, copy buttons for account/reset/error references, **Ctrl/Cmd+K quick navigation**, and an optional device-based color theme. Existing light/dark preferences continue working. Mentor profile photos now use a square frame; small navigation avatars remain round. Dialogs support keyboard navigation and Escape, and animation respects reduced-motion settings.

## Documentation and help guide

**Documentation** appears in navigation for Admins, Account Managers, and Mentors only. Admins and Account Managers can add, edit, and delete pages; Mentors can read/search pages and view images. Every page is shared with all three roles—do not put staff-only case notes or secrets here.

The Confluence-inspired layout has named spaces, a nested page sidebar, parent/child pages, search, last-editor/date labels, and version numbers. The text editor supports `#` headings, `##` subheadings, `###` smaller headings, `-` lists, and paragraphs. HTML is escaped. This is a lightweight shared knowledge base, not a full Confluence integration or collaborative rich-text editor. Version checks reject stale edits; version numbers do not provide revision restoration. Page deletion requires a confirmation page, removes its images, and keeps child pages. Three starter guides are created once during upgrade and can be edited or deleted.

Upload one image per save, with an accessibility description. Images appear after the text. Supported input is still JPEG/PNG/WebP, at most 5 MB / 16 megapixels. Files are decoded and re-encoded as WebP, preserving proportions, at most 1600 × 1600 pixels and 500 KB, with a maximum of 10 images per page. Originals and metadata are discarded. Images are stored in the persistent database and served only to documentation readers. Backups must cover these tables. There is no remote image embedding or public attachment URL.

**Admin → Settings → Help guide & team contact** controls whether the automated guide appears and its public team phone number. Enter international format, such as `+12125550123`, or leave blank for email/tickets only. Changes are applied on the next page load. Only Admins can change these settings. The existing support email is also used.

The help widget answers common navigation questions with built-in guidance and offers your help-desk ticket link, email, and a `tel:` link. It opens the device's phone app; it does not start a call automatically, bridge a call, offer live-agent presence, or transmit the chat to the team. There is no AI provider, subscription, or per-message API call. Conversation text is held only in the page and disappears on reload. The widget is available to visitors and signed-in users; internal Support tools remain restricted to Admins and Account Managers.

## Account deletion, verification, and bot protection

**Support → Account lookup → click an account → Delete account** lets an Admin delete any non-admin account's actual `market_user` row, password hash, verification/reset records, mentor profile, service mappings, photos, own support notes, and related unpaid test reservations. Confirmation requires the exact account email, your current admin password, and a reason. It is unavailable to Account Managers, mentors, and students. All Admin accounts are protected from deletion, including your own and every other Admin, even when disabled. There is no bulk-disable or bulk-delete startup command.

Having booking history does not block deletion. Actual booking/payment snapshots are retained with their recorded amounts, status, and dates, and reassigned to non-login archive references. Personal session goals are cleared. Other participants keep access to their booking records. Shared audit/support attribution remains under a disabled, non-login “Deleted account” principal; the original login row is gone. The archive principal is hidden from account lists and cannot sign in, be enabled through the editor, or be deleted through this action. This also prevents SQLite from reusing removed account IDs. Free text in other accounts' notes/audit records and backups is not automatically erased. External records remain; unconfirmed v0.7 payments are held/reconciled and may require refunds. See STRIPE_V07_SETUP.md for deletion during checkout.

New web-created accounts must prove email ownership before entering their dashboard, managing a profile, using staff tools, or booking. Email changes clear prior verification and invalidate outstanding verification links. A new mentor must verify before publication. Verification links expire after one hour, are hashed in the database, and are single-use. The owner explicitly chooses a password on confirmation, preventing a person who preregistered someone else's email from retaining a known password. Confirmation revokes earlier sessions and requires a new sign-in. Visiting the link alone does not consume it.

Existing accounts are grandfathered once during the additive upgrade, without falsely claiming their email was verified. Disabled accounts remain disabled; the upgrade does not disable, enable, or reset current accounts. The hosting CLI `create-admin` remains an explicitly trusted bootstrap/recovery path. Web-created Admins and both web/CLI-created Account Managers require verification.

Read **SECURITY_SETUP.md before deployment**. SMTP configuration and a trusted `PUBLIC_BASE_URL` are required for new public registration. Missing mail setup closes public registration with a clear message while existing users retain access. SMTP failure leaves a new account pending and offers resend; no verification link is exposed in the browser or logs.

Cloudflare Turnstile protects registration and verification-email resend when configured. Its tokens are checked server-side against the expected action and an explicit hostname allowlist. Invalid, expired, replayed, or failed checks block the submission. The app also rate-limits registration, verification attempts, and verification emails. Turnstile requires your site's public/secret keys and is not automatically active without configuration; it reduces automated abuse but does not guarantee every account belongs to a human.

## Deploy or upgrade

Read `DEPLOYMENT.md`. Back up the database, replace the **marketplace** repository files, preserve your private environment settings, install dependencies, and run:

```bash
flask --app run init-db
```

This creates new tables, migrates the legacy staff role once, and updates future service allocation once on the original v0.3 migration. The v0.4 migration adds support tables and selects Acuity only if no provider was previously selected; it preserves existing booking mode and fee settings. The v0.5 migration adds verification, help, and documentation tables and preserves access for pre-existing accounts. v0.6 adds request, provider appointment, sync-job, and isolated local-simulator tables. It also adds a booking/sync guide without overwriting edited documentation. It does not drop existing tables or rewrite passwords or booking snapshots. Both the Render configuration and Procfile run this before Gunicorn. Run migrations once per release when using multiple service instances.

## Local development

Windows: run `start-windows.bat`, then create an administrator in a second terminal:

```powershell
.venv\Scripts\python.exe -m flask --app run create-admin
```

macOS / Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python setup_local.py
flask --app run create-admin
python run.py
```

CLI account recovery remains available:

```bash
flask --app run reset-password
flask --app run create-account-manager
```

The older `create-onboarding-user` command remains as an alias that creates an Account Manager. Keep `.env`, credentials, database files, and virtual environments out of Git.

## Checks

```bash
pip install pytest
python -m pytest -q
```

Read `VALIDATION.md` for the checks performed and their limits. No live deployment is included in this source update.
