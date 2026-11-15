CREATE TABLE IF NOT EXISTS outbox_jobs (
    id uuid PRIMARY KEY,
    kind text NOT NULL,
    dedupe_key text UNIQUE NOT NULL,
    payload_json jsonb NOT NULL,
    state text NOT NULL,
    attempts integer NOT NULL DEFAULT 0,
    available_at timestamptz NOT NULL DEFAULT now(),
    lease_owner text,
    lease_until timestamptz,
    expires_at timestamptz,
    last_error text NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS idempotency_records (
    actor_id uuid NOT NULL,
    route_key text NOT NULL,
    idempotency_key text NOT NULL,
    request_hash text NOT NULL,
    state text NOT NULL CHECK (state IN ('IN_PROGRESS', 'COMPLETED')),
    result_status integer,
    result_json jsonb,
    expires_at timestamptz NOT NULL,
    PRIMARY KEY (actor_id, route_key, idempotency_key)
);

CREATE TABLE IF NOT EXISTS stage_events (
    event_ts timestamptz NOT NULL,
    event_id uuid NOT NULL,
    session_id uuid,
    task_id uuid,
    stage text NOT NULL,
    duration_ms integer NOT NULL,
    outcome text NOT NULL,
    source text NOT NULL,
    model_id text,
    error_code text,
    PRIMARY KEY (event_ts, event_id)
);

CREATE INDEX IF NOT EXISTS stage_events_session_time ON stage_events (session_id, event_ts DESC);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_available_extensions WHERE name = 'timescaledb') THEN
        CREATE EXTENSION IF NOT EXISTS timescaledb;
        PERFORM create_hypertable('stage_events', 'event_ts', if_not_exists => TRUE);
        CREATE MATERIALIZED VIEW IF NOT EXISTS stage_events_one_minute
        WITH (timescaledb.continuous) AS
        SELECT time_bucket('1 minute', event_ts) AS bucket,
               stage,
               count(*) AS event_count,
               avg(duration_ms) AS avg_duration_ms
        FROM stage_events
        GROUP BY 1, 2
        WITH NO DATA;
    END IF;
END $$;
