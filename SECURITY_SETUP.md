# v0.5 setup — email verification and bot protection

## Account impact

There is no command that disables all current accounts. `init-db` adds tables and grants existing accounts a one-time verification exemption. Previously disabled/suspended accounts stay restricted. New accounts and changed email addresses require verification. The hosting `create-admin` command is a trusted bootstrap exception so missing SMTP cannot lock the platform owner out.

## 1. Configure verification email in Render

Open the marketplace service's Environment settings. Preserve existing SECRET_KEY and DATABASE_URL. Add:

| Variable | Value |
| --- | --- |
| PUBLIC_BASE_URL | Your exact HTTPS marketplace origin, e.g. https://ttbg-marketplace.onrender.com (no path) |
| SMTP_HOST | Your mail provider's SMTP host |
| SMTP_PORT | 587 for STARTTLS, or 465 for implicit TLS if your provider specifies it |
| SMTP_SECURITY | starttls or ssl; plaintext mail transport is not supported |
| SMTP_USERNAME | Authorized sending account |
| SMTP_PASSWORD | Provider-approved SMTP credential/app password |
| SMTP_FROM | Authorized sender email address |

Use the values required by your mail provider and verify sender-domain authorization there. SMTP settings are not exposed through the app's key-reveal screen. No mail credentials are included in this ZIP.

Public registration requires this mail configuration. It fails closed if settings are incomplete. Existing account sign-in, including existing Admins, remains available. The Support → Integrations screen shows configuration readiness, not proof of successful inbox delivery.

For local testing, use a real SMTP test inbox/service and PUBLIC_BASE_URL=http://127.0.0.1:5000 (or http://localhost:5000). Verification links containing localhost work only on the computer running the app. There is no development bypass or console mode that leaks live verification tokens. The bootstrap admin CLI works without SMTP.

A web-created account receives a verification email automatically if SMTP is configured. Staff-created accounts can also use the existing private setup link, but it cannot bypass verification. Verification resends are limited to once per minute and eight per account per day. SMTP errors are recorded without credentials or link values; the new account stays pending. The app's email wording means a message was accepted by SMTP, not that it was delivered to an inbox.

## 2. Enable Cloudflare Turnstile

Create a Turnstile widget for the marketplace in your Cloudflare account. Add the exact marketplace hostnames used for registration (without scheme/path). Use a separate widget for local testing if needed.

Add these Render environment values:

| Variable | Value |
| --- | --- |
| TURNSTILE_ENABLED | true |
| TURNSTILE_SITE_KEY | Public widget site key |
| TURNSTILE_SECRET_KEY | Private verification key |
| TURNSTILE_HOSTNAMES | Exact allowed hostnames, comma-separated; e.g. ttbg-marketplace.onrender.com |

The browser receives only the public site key. The private key can be revealed only through the Admin password-confirmation dialog already in Support Center. Registration uses action `register`; verification resend uses `verify_email`. The backend calls Cloudflare Siteverify and checks success, hostname, action, and replay protection. A successful-looking client widget alone is never sufficient.

If enabled, missing credentials, missing tokens, provider failures, or validation failures block the protected form. Setting either key also enables enforcement so partially configured protection does not silently disappear. To intentionally disable Turnstile, set TURNSTILE_ENABLED=false and clear both keys. Basic application rate limits and email verification still apply. Turnstile is not deployed automatically; you must create/configure the widget.

Turnstile scripts/iframes are allowed only on registration and verification-resend pages. Login and staff/admin pages keep the stricter existing CSP. A CAPTCHA alone is not a guarantee against bots.

## 3. Test before enabling public registration

- Register an address you control. Before verification, dashboard, booking, profile editing, and staff tools must redirect to verification.
- Open the email link and choose a password. Then sign in again. The password chosen on confirmation replaces any initial password and invalidates earlier sessions.
- Request a second email: the first link must stop working. Test an expired and already-used link.
- Confirm changing an email requires fresh verification and removes public visibility from an unverified mentor.
- Test a valid and invalid Turnstile response on the real deployed hostname and check mobile layout.
- Delete a disposable account as Admin. Account Managers cannot access permanent deletion. Try a wrong confirmation email/password, verify that no Admin account can be deleted, and verify that deleting a non-admin with booking history retains financial snapshots.

## 4. Rate limiting and maintenance

Registration is limited to 10 POST requests per IP per 15 minutes. Verification confirmation is limited to 30 attempts per IP per 15 minutes. Resend limits are per account. Counters are database-backed and shared across workers; identifiers are HMAC-hashed. Users behind one shared IP may share limits.

On Render, TRUSTED_PROXY_HOPS defaults to 1 and selects the rightmost trusted forwarded-IP hop. Confirm the proxy chain for your deployment; too few hops can group users behind one proxy, while trusting too many permits spoofing. Non-Render local runs ignore forwarded-IP headers. Do not copy arbitrary X-Forwarded-For or CF-Connecting-IP headers directly into rate-limit keys.

Run `flask --app run prune-security-records` periodically to delete expired rate counters and clear expired token hashes. It never disables accounts. Keep external uptime/error monitoring and database backups configured separately.

## Scope of permanent deletion

The original user record and its eligible profile/login data are physically removed. Shared records use a disabled non-login archive principal; this is audit attribution, not a recoverable user account. Only Admins can delete accounts, and all Admin accounts are protected. Booking history does not block deletion: real/non-test booking snapshots remain under archive references, with amounts/status/dates intact and session goals cleared. Deletion does not cancel an external appointment or refund a charge. Notes on other users, prior audit text, backups, and external-provider records are not globally scrubbed; this feature is not a complete cross-provider data-erasure workflow.

## Documentation and help settings

The Documentation tab is readable by Admins, Account Managers, and Mentors. Only Admins and Account Managers can write/delete pages or upload/delete images. Access checks also cover direct image URLs. Shared guides should not contain staff-only support notes. Text is escaped, uploaded images are re-encoded with metadata removed, and limits cap image dimensions, bytes, and count. Concurrent stale edits return a conflict instead of overwriting someone else's changes.

Set the public team contact number under Admin → Settings → Help guide & team contact. International format is required. Leave it blank for tickets/email only. The bot is a built-in navigation guide, not a live-chat service; it offers a phone-app handoff and help-desk link. Messages are not submitted or retained. No API key is needed for this widget.

## Implementation references

- https://developers.cloudflare.com/turnstile/get-started/server-side-validation/
- https://developers.cloudflare.com/turnstile/reference/content-security-policy/
- https://developers.cloudflare.com/turnstile/get-started/client-side-rendering/
- https://render.com/articles/how-render-handles-ddos-attacks
