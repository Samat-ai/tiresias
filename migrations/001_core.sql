CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS users (
    id uuid PRIMARY KEY,
    email_normalized text UNIQUE NOT NULL,
    password_hash text NOT NULL,
    role text NOT NULL CHECK (role IN ('USER', 'HELPER', 'OPERATOR')),
    created_at timestamptz NOT NULL DEFAULT now(),
    disabled_at timestamptz
);

CREATE TABLE IF NOT EXISTS web_sessions (
    id uuid PRIMARY KEY,
    token_hash text UNIQUE NOT NULL,
    user_id uuid REFERENCES users (id),
    csrf_hash text NOT NULL,
    expires_at timestamptz NOT NULL,
    revoked_at timestamptz,
    idle_expires_at timestamptz NOT NULL
);

CREATE TABLE IF NOT EXISTS profiles (
    user_id uuid PRIMARY KEY REFERENCES users (id),
    preferred_name text,
    language text NOT NULL DEFAULT 'en',
    speech_speed double precision NOT NULL DEFAULT 1.0,
    save_summaries boolean NOT NULL DEFAULT false,
    service_consent_version text,
    service_consent_at timestamptz
);

CREATE TABLE IF NOT EXISTS phone_bindings (
    id uuid PRIMARY KEY,
    user_id uuid NOT NULL REFERENCES users (id),
    phone_ciphertext text NOT NULL,
    phone_fingerprint text NOT NULL,
    provider_identity text,
    state text NOT NULL CHECK (state IN ('PENDING', 'OPERATOR_ASSISTED', 'VERIFIED', 'BLOCKED')),
    verification_source text,
    verified_at timestamptz
);

CREATE UNIQUE INDEX IF NOT EXISTS phone_bindings_one_verified_owner
    ON phone_bindings (provider_identity)
    WHERE state = 'VERIFIED' AND provider_identity IS NOT NULL;

CREATE TABLE IF NOT EXISTS helper_grants (
    id uuid PRIMARY KEY,
    owner_id uuid NOT NULL REFERENCES users (id),
    helper_id uuid NOT NULL REFERENCES users (id),
    state text NOT NULL CHECK (state IN ('PENDING', 'ACCEPTED', 'REVOKED')),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS helper_grants_active_pair
    ON helper_grants (owner_id, helper_id)
    WHERE state = 'ACCEPTED';

CREATE TABLE IF NOT EXISTS call_sessions (
    id uuid PRIMARY KEY,
    connection_epoch text UNIQUE NOT NULL,
    user_id uuid REFERENCES users (id),
    binding_id uuid,
    provider_line_id text,
    room_name text NOT NULL,
    provider_call_id text,
    authorization_source text NOT NULL,
    authorized_by uuid,
    source text NOT NULL CHECK (source IN ('FACETIME', 'BROWSER', 'REPLAY')),
    state text NOT NULL CHECK (state IN ('INITIALIZING', 'ACTIVE', 'PROCESSING_REVOKED', 'ENDED', 'FAILED')),
    started_at timestamptz NOT NULL DEFAULT now(),
    ended_at timestamptz
);

CREATE UNIQUE INDEX IF NOT EXISTS one_active_facetime_line
    ON call_sessions (provider_line_id)
    WHERE source = 'FACETIME' AND state IN ('INITIALIZING', 'ACTIVE', 'PROCESSING_REVOKED');

CREATE TABLE IF NOT EXISTS call_tasks (
    id uuid PRIMARY KEY,
    session_id uuid NOT NULL REFERENCES call_sessions (id),
    generation integer NOT NULL,
    analysis_revision integer NOT NULL,
    state text NOT NULL,
    target_json jsonb,
    last_frame_id text,
    version integer NOT NULL DEFAULT 1,
    expires_at timestamptz NOT NULL
);

CREATE TABLE IF NOT EXISTS snapshot_consents (
    id uuid PRIMARY KEY,
    owner_id uuid NOT NULL REFERENCES users (id),
    task_id uuid NOT NULL,
    generation integer NOT NULL,
    frame_id text NOT NULL,
    helper_id uuid NOT NULL,
    accepted_at timestamptz,
    revoked_at timestamptz,
    expires_at timestamptz NOT NULL
);

CREATE TABLE IF NOT EXISTS snapshots (
    id uuid PRIMARY KEY,
    owner_id uuid NOT NULL REFERENCES users (id),
    task_id uuid NOT NULL,
    frame_id text NOT NULL,
    storage_key text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    deleted_at timestamptz
);

CREATE TABLE IF NOT EXISTS reviews (
    id uuid PRIMARY KEY,
    owner_id uuid NOT NULL REFERENCES users (id),
    task_id uuid NOT NULL,
    generation integer NOT NULL,
    session_id uuid NOT NULL,
    consent_id uuid NOT NULL REFERENCES snapshot_consents (id),
    snapshot_id uuid NOT NULL REFERENCES snapshots (id),
    assigned_helper_id uuid NOT NULL,
    claimed_by uuid,
    state text NOT NULL,
    result text,
    literal_text text,
    notes text,
    version integer NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL
);

CREATE TABLE IF NOT EXISTS payouts (
    id uuid PRIMARY KEY,
    review_id uuid UNIQUE NOT NULL REFERENCES reviews (id),
    call_session_id uuid NOT NULL,
    network text NOT NULL DEFAULT 'devnet' CHECK (network = 'devnet'),
    recipient text NOT NULL,
    lamports bigint NOT NULL,
    state text NOT NULL,
    signed_transaction bytea,
    signature text UNIQUE,
    last_valid_block_height bigint,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS call_reward_reservations (
    call_session_id uuid PRIMARY KEY,
    reserved_count integer NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS deleted_users (
    user_id uuid PRIMARY KEY,
    deleted_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS scene_reports (
    scene_id text PRIMARY KEY,
    user_id uuid NOT NULL,
    expires_at timestamptz NOT NULL,
    payload_json jsonb NOT NULL,
    deleted_at timestamptz
);
