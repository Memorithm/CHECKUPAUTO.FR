# Notification delivery policy

## Rule

Mercure is a data source only. CyberCheck must not call Mercure endpoints that send customer reminders or review-request emails.

The delivery path is intentionally separated:

`Mercure data -> CyberCheck decision engine -> Checkup Auto mail relay -> customer`

The former Mercure Google-review sender is explicitly disabled in `mercure_admin_client.py`.

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

`CYBERCHECK_GOOGLE_REVIEW_URL` must be a validated HTTPS Google review URL. The follow-up engine sends the request through `email_gateway.py` only. It stores the Mercure appointment identifier and delivery state, but not the customer's e-mail address.

## Current host state

At implementation time Thor had no local Postfix/sendmail service listening on ports 25, 465 or 587. Therefore this change cannot send real mail until a local MTA or another explicitly configured relay is deployed.
