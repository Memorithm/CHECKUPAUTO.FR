# Notification delivery policy

## Rule

Mercure is a data source only. CyberCheck must not call Mercure endpoints that send customer reminders or review-request emails.

The delivery path is intentionally separated:

`Mercure data -> CyberCheck decision engine -> NotificationBroker -> Checkup Auto mail relay -> customer`

The former Mercure Google-review sender is explicitly disabled in `mercure_admin_client.py`.

## NotificationBroker

`notification_broker.py` is the delivery boundary. It creates a deterministic idempotency key from channel, category, business reference and recipient, records delivery state without persisting the raw recipient or message body, leases in-flight deliveries to prevent concurrent duplicate sends, and permits retries after failures. The administration API exposes read-only status at `/api/admin/notifications/status`.

The broker currently has one active transport: e-mail. APNs is declared as not configured until Apple credentials and the production app identity are available.

## Email transport

`email_gateway.py` submits messages to an SMTP relay controlled by Checkup Auto. By default it targets `127.0.0.1:25` in plain local-relay mode. The application does not contain relay credentials.

Runtime variables:

- `CYBERCHECK_SMTP_FROM`: required sender address;
- `CYBERCHECK_SMTP_HOST`: optional, defaults to `127.0.0.1`;
- `CYBERCHECK_SMTP_PORT`: optional, defaults to 25 for local plain relay;
- `CYBERCHECK_SMTP_MODE`: `plain`, `starttls` or `ssl`.

## Mercure customer fields

The customer e-mail field is not guessed. `CYBERCHECK_MERCURE_CUSTOMER_EMAIL_FIELD` must contain the exact field name verified against a live Mercure appointment response. Until this value is configured, review follow-up remains in `waiting_mercure_email_field` state.

This deliberately prevents accidental delivery to the wrong address.

## Google review follow-up

`CYBERCHECK_GOOGLE_REVIEW_URL` must be a validated HTTPS Google review URL. The follow-up engine sends the request through `notification_broker.py`, which delegates to `email_gateway.py`. It stores the Mercure appointment identifier and delivery state, but not the customer's e-mail address or message body.

## Current host state

At implementation time Thor had no local Postfix/sendmail service listening on ports 25, 465 or 587. Therefore this change cannot send real mail until a local MTA or another explicitly configured relay is deployed.
