BEGIN;
CREATE SCHEMA IF NOT EXISTS checkupauto_customer;
CREATE TABLE IF NOT EXISTS checkupauto_customer.customer_account(
 account_id TEXT PRIMARY KEY,kind TEXT NOT NULL CHECK(kind IN ('individual','professional')),
 email_hash TEXT NOT NULL UNIQUE,profile_blob BYTEA NOT NULL,wallet_code TEXT NOT NULL DEFAULT '',
 created_at TEXT NOT NULL,updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS checkupauto_customer.customer_identity(
 provider TEXT NOT NULL CHECK(provider IN ('google','apple','microsoft')),subject_hash TEXT NOT NULL,
 account_id TEXT NOT NULL REFERENCES checkupauto_customer.customer_account(account_id) ON DELETE CASCADE,
 created_at TEXT NOT NULL,last_login_at TEXT NOT NULL,PRIMARY KEY(provider,subject_hash)
);
CREATE INDEX IF NOT EXISTS idx_customer_identity_account ON checkupauto_customer.customer_identity(account_id,provider);
CREATE TABLE IF NOT EXISTS checkupauto_customer.customer_session(
 session_hash TEXT PRIMARY KEY,
 account_id TEXT NOT NULL REFERENCES checkupauto_customer.customer_account(account_id) ON DELETE CASCADE,
 created_at TEXT NOT NULL,expires_at TEXT NOT NULL,last_seen_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_customer_session_account ON checkupauto_customer.customer_session(account_id,expires_at);
CREATE TABLE IF NOT EXISTS checkupauto_customer.customer_password_credential(
 account_id TEXT PRIMARY KEY REFERENCES checkupauto_customer.customer_account(account_id) ON DELETE CASCADE,
 password_hash TEXT NOT NULL,verified_at TEXT NOT NULL DEFAULT '',
 failed_attempts INTEGER NOT NULL DEFAULT 0,locked_until TEXT NOT NULL DEFAULT '',
 created_at TEXT NOT NULL,updated_at TEXT NOT NULL,last_login_at TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS checkupauto_customer.customer_password_token(
 token_hash TEXT PRIMARY KEY,
 account_id TEXT NOT NULL REFERENCES checkupauto_customer.customer_account(account_id) ON DELETE CASCADE,
 purpose TEXT NOT NULL CHECK(purpose IN ('verify','reset')),
 created_at TEXT NOT NULL,expires_at TEXT NOT NULL,consumed_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_customer_password_token_account ON checkupauto_customer.customer_password_token(account_id,purpose,expires_at);
CREATE TABLE IF NOT EXISTS checkupauto_customer.customer_password_throttle(
 account_id TEXT NOT NULL REFERENCES checkupauto_customer.customer_account(account_id) ON DELETE CASCADE,
 client_key TEXT NOT NULL,failed_attempts INTEGER NOT NULL DEFAULT 0,
 locked_until TEXT NOT NULL DEFAULT '',updated_at TEXT NOT NULL,
 PRIMARY KEY(account_id,client_key)
);
CREATE TABLE IF NOT EXISTS checkupauto_customer.customer_passage_confirmation(
 passage_hash TEXT PRIMARY KEY,
 account_id TEXT NOT NULL REFERENCES checkupauto_customer.customer_account(account_id) ON DELETE CASCADE,
 state TEXT NOT NULL CHECK(state IN ('pending','confirmed')),
 action TEXT NOT NULL DEFAULT '' CHECK(action IN ('','validated','modified')),
 contact_hash TEXT NOT NULL DEFAULT '',created_at TEXT NOT NULL,
 expires_at TEXT NOT NULL,confirmed_at TEXT NOT NULL DEFAULT '',
 vehicle_id TEXT NOT NULL DEFAULT '',booking_hash TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_customer_passage_account ON checkupauto_customer.customer_passage_confirmation(account_id,state,expires_at);
CREATE INDEX IF NOT EXISTS idx_customer_passage_booking ON checkupauto_customer.customer_passage_confirmation(account_id,booking_hash,state,expires_at);
CREATE TABLE IF NOT EXISTS checkupauto_customer.customer_oidc_flow(
 state_hash TEXT PRIMARY KEY,provider TEXT NOT NULL,nonce TEXT NOT NULL,
 verifier TEXT NOT NULL,redirect_uri TEXT NOT NULL,
 created_at TEXT NOT NULL,expires_at TEXT NOT NULL,browser_hash TEXT NOT NULL DEFAULT '',
 mobile INTEGER NOT NULL DEFAULT 0,return_to TEXT NOT NULL DEFAULT '',mobile_challenge TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_customer_oidc_expiry ON checkupauto_customer.customer_oidc_flow(expires_at);
CREATE TABLE IF NOT EXISTS checkupauto_customer.customer_native_nonce(
 nonce_hash TEXT PRIMARY KEY,server_issued INTEGER NOT NULL DEFAULT 0,
 used_at TEXT NOT NULL DEFAULT '',expires_at TEXT NOT NULL
);
COMMIT;
