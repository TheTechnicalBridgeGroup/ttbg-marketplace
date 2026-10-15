# TTBG v0.6.0 — confirmed appointments and synchronization

This release implements the six requested pieces: backend Acuity API access, credential configuration, mentor calendar mapping, appointment type mapping, confirmed appointment creation, and saved/synchronized appointments. No live API key is included. The local simulator accepts a dummy key and exercises the same TTBG booking and persistence workflow.

For v0.6.7 service import and FREE consultations, also read **ACUITY_IMPORT_V067.md**. Mock type **202** is a free 30-minute consultation on calendar **101**.

## Local practice — Windows Command Prompt

Use the extracted **v0.6.7** folder. Keep your production database and credentials separate.

If `.venv` already exists, use it. Otherwise:

```bat
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe setup_local.py
```

In this folder's `.env`, **keep your existing SECRET_KEY** and set:

```dotenv
APP_ENV=local
ACUITY_MODE=mock
ACUITY_USER_ID=1
ACUITY_API_KEY=local-dummy-key
DATABASE_URL=sqlite:///marketplace-mock.db
PUBLIC_BASE_URL=http://127.0.0.1:5000
COOKIE_SECURE=false
```

Keep any existing SMTP/Turnstile values if you also want to test registration. The three practice accounts below do not need SMTP or verification. Environment variables already set in your terminal override `.env`; clear conflicting values or open a fresh terminal if settings appear unchanged.

Run:

```bat
.venv\Scripts\python.exe -m flask --app run setup-acuity-local
.venv\Scripts\python.exe run.py
```

The setup command asks you to choose a password (12–128 characters). It creates these accounts with that password:

| Role | Sign-in email |
| --- | --- |
| Admin | local.admin@example.com |
| Mentor | local.mentor@example.com |
| Student | local.student@example.com |

Open **http://127.0.0.1:5000**. The banner must say **Local practice mode**. Sign in as the student, open the practice mentor, select the mentoring service, choose a future weekday and time, complete the intake question, and confirm.

The seeded calendar is **101**, appointment type **201**, price **$100**, duration **60 minutes**, and allocation **$80 mentor / $20 TTBG**. Simulated availability is weekdays at 10:00, 13:00, and 15:00 America/New_York, at least two hours ahead. Client timezone selection still applies. The simulator uses these fixed fixtures; it is not an Acuity sandbox or proof that arbitrary live mappings work.

You should see:

1. A confirmed appointment with an Acuity reference.
2. The appointment on the student's and mentor's dashboards.
3. A saved record under **Support → Appointment sync** when signed in as Admin.
4. A successful connection check and mapping verification under Support.

Practice setup never overwrites existing practice accounts or their passwords. It refuses to run in live mode. The mock database is isolated from the normal local `marketplace.db`. Mock mode is forbidden on Render, with a public origin, or with a non-SQLite database; it also rejects non-loopback web requests. Never upload a local database to production. No mock call reaches Acuity or sends an Acuity confirmation email.

## Exercise synchronization and failures

Keep the local server running. Open a second Command Prompt in the same folder. Replace `1` below with the Acuity reference shown on your appointment.

### Change an appointment in the simulated provider

```bat
.venv\Scripts\python.exe -m flask --app run acuity-mock-change --id 1 --action cancel
```

This changes the simulated Acuity record and delivers a correctly signed webhook through TTBG's real webhook endpoint. Refresh the dashboard; the appointment should show cancelled. To simulate a provider-reported payment label without charging money:

```bat
.venv\Scripts\python.exe -m flask --app run acuity-mock-change --id 1 --action paid
```

For rescheduling, choose a free future weekday slot from the local calendar and provide its exact offset-bearing timestamp:

```bat
.venv\Scripts\python.exe -m flask --app run acuity-mock-change --id 1 --action reschedule --time "2026-11-02T13:00:00-05:00"
```

The example is illustrative; use a future date when testing. The command validates availability and sends the signed change notification.

### Simulate an unavailable slot

```bat
.venv\Scripts\python.exe -m flask --app run acuity-mock-scenario unavailable
```

Submit a booking. It should be rejected with no provider appointment or confirmed TTBG booking. Return to normal with:

```bat
.venv\Scripts\python.exe -m flask --app run acuity-mock-scenario normal
```

### Simulate a timeout after creation

```bat
.venv\Scripts\python.exe -m flask --app run acuity-mock-scenario timeout_after_create
```

Submit a new booking. The provider creates it, but TTBG shows **Checking your confirmation**. Reposting that same form must not create another appointment.

As Admin or Account Manager, open **Support → Appointment sync → request to review**. Choose **Find matching Acuity appointments**, verify the match, then enter its ID and your staff password to link it. The student now sees the confirmed appointment. Restore the `normal` scenario afterward.

The release action is only for a staff member who has independently checked Acuity and verified that no appointment exists. An empty search result or timeout alone is not proof of failure. Never release the timeout-after-create example: that scenario intentionally creates an appointment.

### Simulate a sync outage and recovery

```bat
.venv\Scripts\python.exe -m flask --app run acuity-mock-scenario sync_failure
.venv\Scripts\python.exe -m flask --app run acuity-mock-change --id 1 --action cancel
```

The command reports the sync failure; a retry remains saved. Recover with:

```bat
.venv\Scripts\python.exe -m flask --app run acuity-mock-scenario normal
.venv\Scripts\python.exe -m flask --app run sync-acuity
```

No server restart is required for these scenario commands. Restart after changing `.env`.

## Live deployment

Preserve the production `DATABASE_URL`, `SECRET_KEY`, SMTP, and Turnstile settings. Use:

```dotenv
APP_ENV=production
ACUITY_MODE=live
ACUITY_USER_ID=YOUR_NUMERIC_ACUITY_USER_ID
ACUITY_API_KEY=YOUR_REAL_ACUITY_API_KEY
PUBLIC_BASE_URL=https://YOUR-MARKETPLACE-HOST
COOKIE_SECURE=true
```

Do not copy the mock database URL into Render. Use TTBG's persistent production database. Live mode rejects the documented dummy key and the mock database filename.

1. Deploy the code, install `requirements.txt`, and run `flask --app run init-db` before workers start. The existing Procfile/Render command already performs this additive upgrade. It preserves accounts and existing booking settings.
2. Use an Acuity plan/account with API access. Enter the **numeric User ID as well as the API key**.
3. Set each mentor's calendar ID and each service's appointment type ID. Use **Support → Acuity mappings** to load actual IDs and verify each service. A Scheduling-page Acuity event/type reference takes precedence over the older service field.
4. Match the TTBG service price and duration to its Acuity appointment type. This version is for one-to-one services and TTBG's existing USD pricing. Configure the Acuity account in USD. Shared appointment types need the same price/duration across their mapped services; use distinct types where mentor prices differ. Changing a mentor's TTBG price does not silently change Acuity—update both, then verify.
5. In **Support → Appointment sync**, click **Enable automatic sync** as Admin. It registers an `appointment.changed` webhook for `PUBLIC_BASE_URL/webhooks/acuity`. Repeating this for the same active endpoint does not create duplicate subscriptions. If you change your domain, register the new endpoint and remove the obsolete subscription in Acuity.
6. In **Admin → Settings**, choose **Acuity Scheduling → Acuity confirmed appointments**. The previous availability/contact mode is still available and is not silently upgraded to provider writes.
7. Book one controlled real session. Verify the actual appointment in Acuity, TTBG dashboard record, confirmation email, and subsequent reschedule/cancellation updates before inviting students broadly.

Dynamic webhooks use the same API key for signature validation. If you instead configure a **static** webhook signed by a different main-admin key, set `ACUITY_WEBHOOK_SECRET` to that signing key. Leave it blank for the normal dynamic setup. Never place keys in templates, forms, URLs, or source control.

Acuity sends its configured appointment emails/reminders. The marketplace's registration-verification SMTP remains separate. Mock testing does not verify production API entitlement, real calendars, inbox delivery, or webhook reachability.

## Operational recovery

Webhook updates fetch the current appointment from Acuity instead of trusting the notification's status. Duplicate/out-of-order notifications therefore do not duplicate bookings or roll a cancellation back. Failed reads leave a durable pending retry and return HTTP 500 so Acuity can retry.

Use **Sync from Acuity** by ID for a targeted refresh. Also schedule this command on your hosting environment periodically (for example every five minutes):

```bash
flask --app run sync-acuity --limit 500
```

This retries pending sync jobs, then refreshes the least-recently-synced records for the currently configured account. It never retries appointment-creation POSTs. At higher volume, tune the limit/frequency to provider rate limits and the number of records. Your hosting scheduler is configured separately.

Appointments created outside TTBG are saved when a signed webhook arrives or staff fetches them by ID. They remain **staff-only and unlinked** until staff explicitly verifies and links an existing verified student and matching service. There is no automatic account creation or bulk historical import. Use request reconciliation for a TTBG request with an uncertain result.

If the provider's client email, calendar/type, price, or duration changes, TTBG marks the linked booking for review rather than silently transferring access or changing agreed financial totals. Staff should correct/verify the source in Acuity, then refresh. Ordinary time changes and cancellations sync automatically.

## Scope

- Confirmation creates an appointment; it does **not** collect a card payment, verify a settlement, or send an automatic payout. TTBG retains the configured allocation snapshot. Stripe Connect remains separate.
- Required text, textarea, dropdown, checkbox, checkbox-list, yes/no, and address intake answers are supported. Internal Acuity forms are never shown. Required file-upload intake is blocked with a clear setup error because Acuity's API requires externally hosted files; optional file fields are omitted. Configure supported intake fields for this native flow.
- Rescheduling and cancellation are performed in Acuity or through its confirmation emails; TTBG synchronizes them back. No separate native rescheduling/cancellation interface is introduced.
- Account deletion retains appointment/financial history through the existing non-login archive references. It does not cancel an external appointment or refund money. Already-linked records with removed identity stay redacted on later synchronization.

## Official references used

- https://developers.acuityscheduling.com/reference/post-appointments
- https://developers.acuityscheduling.com/reference/get-appointments-id
- https://developers.acuityscheduling.com/reference/get-appointments
- https://developers.acuityscheduling.com/reference/forms
- https://developers.acuityscheduling.com/reference/appointment-types
- https://developers.acuityscheduling.com/docs/webhooks
- https://developers.acuityscheduling.com/page/webhooks-webhooks-webhooks
