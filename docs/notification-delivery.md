# Notification delivery policy

## Rule

Mercure is a data source only. CyberCheck must not call Mercure endpoints that send customer reminders or review-request emails.

The delivery path is intentionally separated:

`Mercure data -> CyberCheck decision engine -> NotificationBroker -> Checkup Auto transport -> customer`

The former Mercure Google-review sender is explicitly disabled in `mercure_admin_client.py`.

## NotificationBroker

`notification_broker.py` is the delivery boundary. It creates a deterministic idempotency key from channel, category, business reference and recipient, records delivery state without persisting the raw recipient or message body, leases in-flight deliveries to prevent concurrent duplicate sends, and permits retries after failures. The administration API exposes read-only status at `/api/admin/notifications/status`.

The broker supports e-mail and APNs. APNs remains non-delivering until Apple credentials are present and `CYBERCHECK_MOBILE_PUSH_ENABLED` is explicitly enabled; this activation gate prevents central push delivery from duplicating the application's local fallback reminders during rollout.

## Email transports

`email_gateway.py` supports two Checkup Auto-owned transports. `auto` mode preserves the SMTP relay when configured and otherwise uses the Gmail API when the Google IntegrationHub has the `gmail.send` scope and a validated sender address.

Runtime selector:

- `CYBERCHECK_EMAIL_TRANSPORT`: `auto` (default), `smtp` or `gmail`.

SMTP variables:

- `CYBERCHECK_SMTP_FROM`: sender address; enables SMTP;
- `CYBERCHECK_SMTP_HOST`: optional, defaults to `127.0.0.1`;
- `CYBERCHECK_SMTP_PORT`: optional, defaults to 25 for local plain relay;
- `CYBERCHECK_SMTP_MODE`: `plain`, `starttls` or `ssl`.

Gmail variables/settings:

- connect the Gmail service from IntegrationHub with `https://www.googleapis.com/auth/gmail.send`;
- configure `Gmail · Adresse d’envoi` in the private Google settings;
- `CYBERCHECK_GMAIL_FROM` is an optional runtime fallback for that sender setting.

OAuth client secrets and refresh tokens remain under `/root/CyberCheckPrivate/integrations` with private filesystem permissions. No OAuth token is written into the notification ledger.

## Mercure customer fields

The e-mail address used for reminders and review follow-up comes from the verified Mercure calendar `extendedProps.email` field. It is read only at delivery time and is not copied into the durable reminder inventory or NotificationBroker ledger.

## Google review follow-up

`CYBERCHECK_GOOGLE_REVIEW_URL` must be a validated HTTPS Google review URL. The follow-up engine sends the request through `notification_broker.py`, which delegates to `email_gateway.py`. It stores the Mercure appointment identifier and delivery state, but not the customer's e-mail address or message body.

## CT due-date reminder pipeline

CyberCheck reads the verified Mercure calendar schema and resolves `vehiculeId` to `/admin/get-vehicule/<id>`, where `date_echeance` is the control due-date source. The local reminder inventory stores only provider technical identifiers, due date and last source appointment. Customer e-mail addresses are resolved from Mercure only at delivery time and are never persisted in the reminder inventory.

The dispatch policy is shared with the iOS core: J-60, J-30, J-15, J-7 and J-1 at 09:00 Europe/Paris. Delivery is routed exclusively through NotificationBroker. Its idempotency reference hashes the provider vehicle identifier before persistence.

A recent Mercure window is refreshed on every cycle. Historical coverage is progressively backfilled in bounded 31-day chunks up to 730 days so the integration does not issue an unbounded burst of provider requests. Missing e-mail transport configuration prevents delivery but does not prevent due-date synchronization.

## Mobile bootstrap policy

The public endpoint `/api/mobile/bootstrap` exposes only non-secret mobile policy: reminder lead days, delivery hour and timezone, the public booking URL, the configured referral reward amount, application landing/download state, and whether central push is actually active. It does not expose Mercure identifiers, customer data, OAuth material, APNs credentials or administration configuration.

The iOS application validates schema version 1 and the reminder policy before applying it. If the endpoint is unavailable or invalid, the app keeps the baked-in safe defaults (J-60/J-30/J-15/J-7/J-1 at 09:00 Europe/Paris and the public Mercure booking URL). Local notifications remain enabled unless the server explicitly declares central push active.

## Mobile due-date push pipeline

The authenticated endpoint `/api/mobile/reminders/sync` receives a full snapshot of at most 24 mobile deadlines for an installation. Each entry contains only an opaque UUID and an ISO due date; registration plates, vehicle labels, Mercure identifiers and customer data never enter this registry. Device unregister and APNs-token reassignment purge stale mobile deadlines.

`mobile_reminder_dispatch.py` evaluates those dates with the same J-60/J-30/J-15/J-7/J-1 policy and routes eligible notifications through `NotificationBroker`. The APNs environment is selected per registered device (`sandbox` or `production`) rather than globally, so Debug and Release installations can coexist safely.
