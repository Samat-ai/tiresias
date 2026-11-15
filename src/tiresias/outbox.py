from __future__ import annotations

import hashlib
import json
from typing import Any

from tiresias.db import SURVIVING_KINDS


class IdempotencyConflict(Exception):
    status = 409


def enqueue_job(conn, *, job_id: str, kind: str, dedupe_key: str, payload: dict, expires_at=None) -> dict:
    row = conn.execute(
        """
        INSERT INTO outbox_jobs (id, kind, dedupe_key, payload_json, state, expires_at)
        VALUES (%s, %s, %s, %s::jsonb, 'PENDING', %s)
        ON CONFLICT (dedupe_key) DO NOTHING
        RETURNING *
        """,
        (job_id, kind, dedupe_key, json.dumps(payload), expires_at),
    ).fetchone()
    if row:
        return row
    return conn.execute("SELECT * FROM outbox_jobs WHERE dedupe_key = %s", (dedupe_key,)).fetchone()


def claim_jobs(conn, worker_id: str, kinds: list[str], limit: int) -> list[dict]:
    rows = conn.execute(
        """
        WITH picked AS (
            SELECT id
            FROM outbox_jobs
            WHERE kind = ANY(%s)
              AND state IN ('PENDING', 'LEASED')
              AND (lease_until IS NULL OR lease_until <= now())
              AND available_at <= now()
              AND (
                    expires_at IS NULL
                    OR expires_at > now()
                    OR kind = ANY(%s)
                  )
            ORDER BY available_at, id
            FOR UPDATE SKIP LOCKED
            LIMIT %s
        )
        UPDATE outbox_jobs AS job
        SET state = 'LEASED',
            lease_owner = %s,
            lease_until = now() + interval '30 seconds',
            attempts = job.attempts + 1
        FROM picked
        WHERE job.id = picked.id
        RETURNING job.*
        """,
        (kinds, list(SURVIVING_KINDS), limit, worker_id),
    ).fetchall()
    return list(rows)


def upsert_scene(conn, *, scene_id: str, user_id: str, expires_at, payload: dict) -> dict | None:
    deleted = conn.execute("SELECT 1 FROM deleted_users WHERE user_id = %s", (user_id,)).fetchone()
    if deleted:
        return None
    existing = conn.execute("SELECT expires_at, deleted_at FROM scene_reports WHERE scene_id = %s", (scene_id,)).fetchone()
    if existing and existing["deleted_at"] is not None:
        return None
    if existing:
        return conn.execute(
            """
            UPDATE scene_reports
            SET payload_json = %s::jsonb
            WHERE scene_id = %s
            RETURNING *
            """,
            (json.dumps(payload), scene_id),
        ).fetchone()
    return conn.execute(
        """
        INSERT INTO scene_reports (scene_id, user_id, expires_at, payload_json)
        VALUES (%s, %s, %s, %s::jsonb)
        RETURNING *
        """,
        (scene_id, user_id, expires_at, json.dumps(payload)),
    ).fetchone()


def begin_idempotency(conn, *, actor_id: str, route_key: str, idempotency_key: str, body: dict) -> dict:
    request_hash = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
    existing = conn.execute(
        """
        SELECT * FROM idempotency_records
        WHERE actor_id = %s AND route_key = %s AND idempotency_key = %s
        """,
        (actor_id, route_key, idempotency_key),
    ).fetchone()
    if existing:
        if existing["request_hash"] != request_hash:
            raise IdempotencyConflict("idempotency key was reused with a different body")
        return {"replay": True, "record": existing}
    conn.execute(
        """
        INSERT INTO idempotency_records
            (actor_id, route_key, idempotency_key, request_hash, state, expires_at)
        VALUES (%s, %s, %s, %s, 'IN_PROGRESS', now() + interval '24 hours')
        """,
        (actor_id, route_key, idempotency_key, request_hash),
    )
    return {"replay": False, "record": None}


def complete_idempotency(conn, *, actor_id: str, route_key: str, idempotency_key: str, status: int, result: dict) -> None:
    conn.execute(
        """
        UPDATE idempotency_records
        SET state = 'COMPLETED', result_status = %s, result_json = %s::jsonb
        WHERE actor_id = %s AND route_key = %s AND idempotency_key = %s
        """,
        (status, json.dumps(result), actor_id, route_key, idempotency_key),
    )


def record_stage_event(conn, **event: Any) -> None:
    conn.execute(
        """
        INSERT INTO stage_events
            (event_ts, event_id, session_id, task_id, stage, duration_ms, outcome, source, model_id, error_code)
        VALUES (now(), %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            event["event_id"],
            event.get("session_id"),
            event.get("task_id"),
            event["stage"],
            event["duration_ms"],
            event["outcome"],
            event["source"],
            event.get("model_id"),
            event.get("error_code"),
        ),
    )
