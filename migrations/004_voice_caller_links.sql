CREATE TABLE IF NOT EXISTS voice_caller_links (
    id uuid PRIMARY KEY,
    user_id uuid NOT NULL UNIQUE REFERENCES users(id),
    handle_fingerprint text NOT NULL UNIQUE,
    handle_type text NOT NULL CHECK (handle_type IN ('phone_number','email')),
    masked_handle text NOT NULL,
    verified_at timestamptz NOT NULL
);

CREATE TABLE IF NOT EXISTS voice_link_requests (
    id uuid PRIMARY KEY,
    user_id uuid NOT NULL REFERENCES users(id),
    handle_fingerprint text NOT NULL,
    handle_type text NOT NULL CHECK (handle_type IN ('phone_number','email')),
    masked_handle text NOT NULL,
    created_at timestamptz NOT NULL,
    expires_at timestamptz NOT NULL,
    challenge_hash text,
    provider_call_id uuid,
    attempts integer NOT NULL DEFAULT 0,
    completed_at timestamptz,
    cancelled_at timestamptz
);
CREATE UNIQUE INDEX IF NOT EXISTS one_pending_voice_link_per_user
    ON voice_link_requests(user_id) WHERE completed_at IS NULL AND cancelled_at IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS one_pending_voice_link_per_handle
    ON voice_link_requests(handle_fingerprint) WHERE completed_at IS NULL AND cancelled_at IS NULL;
CREATE INDEX IF NOT EXISTS voice_link_requests_created ON voice_link_requests(created_at);
