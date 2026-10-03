# Customer federated authentication runbook

Supported customer providers: Apple and Google.

Web uses the CheckupAuto HTTPS OIDC callbacks. iOS Apple uses AuthenticationServices
and server-side token verification. iOS Google uses ASWebAuthenticationSession,
the registered HTTPS Google callback, then a 90-second single-use CheckupAuto
handoff ticket into the app.

Customer sessions are opaque and stored in the iOS Keychain with a device-only
accessibility class. Provider passwords and Apple/Google private credentials are
never stored in the app.

Release gates:
1. Federated Auth Fast Gate green.
2. Security CI green.
3. Native Mac iOS Core CI green.
4. Staging web redirects reach the official provider.
5. A real provider login is required before claiming end-to-end production
   authentication success.
