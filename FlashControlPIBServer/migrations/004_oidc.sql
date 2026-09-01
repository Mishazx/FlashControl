CREATE TABLE IF NOT EXISTS oidc_identities (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL UNIQUE REFERENCES auth_users(id),
    issuer VARCHAR(1024) NOT NULL,
    subject VARCHAR(512) NOT NULL,
    groups JSONB NOT NULL,
    created_at_utc TIMESTAMPTZ NOT NULL,
    last_seen_at_utc TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_oidc_identity_subject UNIQUE (issuer, subject)
);

CREATE TABLE IF NOT EXISTS oidc_transactions (
    id UUID PRIMARY KEY,
    state_hash VARCHAR(64) NOT NULL UNIQUE,
    browser_hash VARCHAR(64) NOT NULL,
    nonce VARCHAR(128) NOT NULL,
    code_verifier VARCHAR(128) NOT NULL,
    created_at_utc TIMESTAMPTZ NOT NULL,
    expires_at_utc TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_oidc_transactions_expires_at_utc
    ON oidc_transactions (expires_at_utc);
