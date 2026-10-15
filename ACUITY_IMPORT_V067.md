# TTBG v0.6.7 — Import services from Acuity

## Where to find it

Sign in as **Admin** or **Account Manager**. Open **Team workspace → mentor → Services & pricing → Import from Acuity**. **Add manually** remains beside it. Import controls and endpoints are restricted to those two roles.

1. Save the mentor’s **Acuity Calendar ID** under **Review & publish** if it is not already set.
2. Click **Import from Acuity** and enter the **Appointment Type ID** (a different ID from the calendar).
3. Click **Fetch appointment type**. TTBG reads the connected Acuity account and verifies that the type is active, one-to-one, and offered on that mentor’s saved calendar.
4. Review the name, description, price, and duration. Name and description are editable before saving. Missing descriptions can be filled in. Price and duration remain matched to Acuity; change them in Acuity and fetch again if needed.
5. Choose whether the service should be active. New public types default to active; new private types default to hidden. Existing services keep their current visibility checkbox setting. A mentor must still be approved before an active service appears publicly.
6. Confirm the reviewed values and that the Acuity account uses **USD**, then select **Confirm import** or **Confirm service update**.

The price returned by Acuity is in its account currency. This release does not convert currencies or automatically detect currency from appointment-type data. Use a USD Acuity account.

## Existing services

Duplicate detection is scoped to the mentor and checks both the older Acuity type field and the Scheduling-page mapping. Another mentor may use the same type. An existing match shows a current-versus-Acuity comparison and requires explicit confirmation to update it. If multiple services for one mentor already map to that ID, the import stops so staff can correct the conflicting mappings.

The import saves both Acuity type fields consistently. If an existing service uses a different scheduling provider, the preview explains that confirmation replaces it with Acuity and clears that provider’s hosted link. Existing Acuity hosted links are retained.

Existing booking prices, allocations, and appointment records are not changed. Existing service commission settings are preserved; newly imported services receive the platform commission. An audit event records each successful import/update.

This is a one-time import, not automatic catalog synchronization. Import the same ID again to review later Acuity changes. Previews expire after 15 minutes and are bound to the staff account, mentor, provider account/mode, source values, and current service state. Changes after preview require fetching again. Replaying a creation preview cannot silently update the newly created service.

## FREE consultations

Services priced at **0** display **FREE** on mentor listings, profiles, availability, confirmation, and service screens. Both imports and manual/mentor price forms accept zero. Paid services retain their normal currency display. Financial amounts such as zero earnings or commission remain **$0.00**.

Confirmed zero-priced Acuity bookings use **No payment required** rather than **Payment due**. This does not turn a previously paid booking into a free booking when a service is later edited; booking snapshots retain their agreed price.

## Supported fields and limits

- One-to-one Acuity `service` types only; classes and series are not imported.
- Prices from $0.00 to $1,000.00, at most two decimal places.
- Whole-minute durations from 1 to 1,440. Manual service editing supports the same durations, including 15- and 45-minute offerings.
- Names up to 120 characters and descriptions up to 1,000. Longer source text is visibly flagged as shortened for review.
- Descriptions are converted to plain text. Images, attachments, rich formatting, categories, padding, and intake forms are not copied into the service. Acuity continues managing availability and booking intake.
- Acuity private/public configuration is not changed by import. The TTBG active checkbox controls TTBG visibility independently.
- No new API key, environment variable, package, or database table is needed for this feature. It uses existing server-side Acuity credentials. Importing performs provider reads only; it never creates an appointment or modifies Acuity.

## Local dummy-key check

Use **ACUITY_V06_SETUP.md** to configure the isolated local mock database and practice accounts. No live Acuity calls are made in mock mode.

With calendar **101** saved on the local mentor:

- Import **201**: Local mentoring session, $100.00, 60 minutes. The seeded mentor already has this type, so this exercises the update preview.
- Import **202**: Free introductory consultation, **FREE**, 30 minutes. This exercises new service creation and free booking.
- Re-fetch either ID: TTBG offers an update, not a duplicate.
- Try **999**: it is not found and no service is saved.

Sign in as the local student to book the new free consultation. Check that the confirmation shows FREE and the saved appointment says No payment required. The $100 service and free service share the simulated mentor’s availability.

## Updating a deployed installation

Deploy the v0.6.7 code using your existing process and environment settings. Keep `SECRET_KEY`, `DATABASE_URL`, SMTP, Turnstile, and Acuity credentials. The normal `init-db` startup remains compatible; no new tables or account changes are introduced by v0.6.7. `/health` reports version `0.6.7`.

After deployment, import one known type into a draft mentor first. Confirm the preview against Acuity before saving. Credentials, account API access, and live webhook behavior still depend on your deployment; local tests do not validate your live account.

Official field reference: https://developers.acuityscheduling.com/reference/appointment-types
