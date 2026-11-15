from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tiresias.outbox import enqueue_job


class ReviewError(Exception):
    def __init__(self, code: str, status: int) -> None:
        super().__init__(code)
        self.code = code
        self.status = status


def create_review(
    conn,
    *,
    owner_id: str,
    helper_id: str,
    session_id: str,
    task_id: str,
    generation: int,
    frame_id: str,
    image_bytes: bytes,
    snapshot_dir: Path,
    now: datetime | None = None,
) -> dict:
    now = now or datetime.now(timezone.utc)
    grant = conn.execute(
        """
        SELECT * FROM helper_grants
        WHERE owner_id = %s AND helper_id = %s AND state = 'ACCEPTED'
        """,
        (owner_id, helper_id),
    ).fetchone()
    if grant is None:
        raise ReviewError("helper_not_granted", 403)
    expires = now + timedelta(minutes=30)
    consent_id = str(uuid.uuid4())
    snapshot_id = str(uuid.uuid4())
    review_id = str(uuid.uuid4())
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    storage_key = f"{owner_id}/{snapshot_id}.jpg"
    path = snapshot_dir / storage_key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(image_bytes)
    try:
        conn.execute(
            """
            INSERT INTO snapshot_consents
                (id, owner_id, task_id, generation, frame_id, helper_id, accepted_at, expires_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (consent_id, owner_id, task_id, generation, frame_id, helper_id, now, expires),
        )
        conn.execute(
            """
            INSERT INTO snapshots (id, owner_id, task_id, frame_id, storage_key, expires_at)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (snapshot_id, owner_id, task_id, frame_id, storage_key, expires),
        )
        conn.execute(
            """
            INSERT INTO reviews
                (id, owner_id, task_id, generation, session_id, consent_id, snapshot_id, assigned_helper_id, state, expires_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'OPEN', %s)
            """,
            (review_id, owner_id, task_id, generation, session_id, consent_id, snapshot_id, helper_id, expires),
        )
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return {"review_id": review_id, "snapshot_id": snapshot_id, "consent_id": consent_id}


def read_snapshot(conn, *, actor_id: str, snapshot_id: str, snapshot_dir: Path, now: datetime | None = None) -> bytes:
    now = now or datetime.now(timezone.utc)
    row = conn.execute(
        """
        SELECT s.*, c.revoked_at, c.helper_id, c.expires_at AS consent_expires
        FROM snapshots s
        JOIN snapshot_consents c ON c.frame_id = s.frame_id AND c.owner_id = s.owner_id AND c.task_id = s.task_id
        WHERE s.id = %s
        """,
        (snapshot_id,),
    ).fetchone()
    if row is None or row["deleted_at"] is not None:
        raise ReviewError("not_found", 404)
    if row["expires_at"] <= now or row["consent_expires"] <= now:
        raise ReviewError("expired", 410)
    if row["revoked_at"] is not None:
        raise ReviewError("not_found", 404)
    allowed = str(row["owner_id"]) == actor_id
    if not allowed:
        grant = conn.execute(
            """
            SELECT 1 FROM helper_grants
            WHERE owner_id = %s AND helper_id = %s AND state = 'ACCEPTED'
            """,
            (row["owner_id"], actor_id),
        ).fetchone()
        allowed = grant is not None and str(row["helper_id"]) == actor_id
    if not allowed:
        raise ReviewError("not_found", 404)
    return (snapshot_dir / row["storage_key"]).read_bytes()


def complete_review(
    conn,
    *,
    actor_id: str,
    review_id: str,
    result: str,
    literal_text: str | None,
    notes: str | None,
    expected_version: int,
    helper_wallet: str | None,
    rewards_enabled: bool,
    lamports: int,
) -> dict:
    review = conn.execute("SELECT * FROM reviews WHERE id = %s FOR UPDATE", (review_id,)).fetchone()
    if review is None or str(review["assigned_helper_id"]) != actor_id:
        raise ReviewError("not_found", 404)
    if review["state"] == "COMPLETED":
        if review["result"] != result or (review["literal_text"] or None) != literal_text:
            raise ReviewError("conflict", 409)
        payout = conn.execute("SELECT id FROM payouts WHERE review_id = %s", (review_id,)).fetchone()
        return {
            "review_id": review_id,
            "state": "COMPLETED",
            "version": review["version"],
            "answer_status": "QUEUED",
            "reward_status": "QUEUED" if payout else "NOT_ENROLLED",
            "reward_network": "devnet",
        }
    if review["version"] != expected_version:
        raise ReviewError("conflict", 409)
    conn.execute(
        """
        UPDATE reviews
        SET state = 'COMPLETED', result = %s, literal_text = %s, notes = %s, version = version + 1, claimed_by = %s
        WHERE id = %s
        """,
        (result, literal_text, notes, actor_id, review_id),
    )
    enqueue_job(
        conn,
        job_id=str(uuid.uuid4()),
        kind="REVIEW_DELIVER",
        dedupe_key=f"deliver:{review_id}",
        payload={
            "review_id": review_id,
            "session_id": str(review["session_id"]),
            "generation": review["generation"],
            "literal_text": literal_text,
            "result": result,
        },
        expires_at=review["expires_at"],
    )
    reward_status = _reserve_reward(conn, review, helper_wallet, rewards_enabled, lamports)
    updated = conn.execute("SELECT version FROM reviews WHERE id = %s", (review_id,)).fetchone()
    return {
        "review_id": review_id,
        "state": "COMPLETED",
        "version": updated["version"],
        "answer_status": "QUEUED",
        "reward_status": reward_status,
        "reward_network": "devnet",
    }


def _reserve_reward(conn, review: dict, helper_wallet: str | None, rewards_enabled: bool, lamports: int) -> str:
    if not rewards_enabled:
        return "DISABLED"
    if not helper_wallet:
        return "NOT_ENROLLED"
    conn.execute(
        """
        INSERT INTO call_reward_reservations (call_session_id, reserved_count)
        VALUES (%s, 0)
        ON CONFLICT (call_session_id) DO NOTHING
        """,
        (review["session_id"],),
    )
    reservation = conn.execute(
        "SELECT reserved_count FROM call_reward_reservations WHERE call_session_id = %s FOR UPDATE",
        (review["session_id"],),
    ).fetchone()
    if reservation["reserved_count"] >= 3:
        return "CAP_REACHED"
    conn.execute(
        "UPDATE call_reward_reservations SET reserved_count = reserved_count + 1 WHERE call_session_id = %s",
        (review["session_id"],),
    )
    payout_id = str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO payouts (id, review_id, call_session_id, recipient, lamports, state)
        VALUES (%s, %s, %s, %s, %s, 'QUEUED')
        """,
        (payout_id, review["id"], review["session_id"], helper_wallet, lamports),
    )
    enqueue_job(
        conn,
        job_id=str(uuid.uuid4()),
        kind="PAYOUT_PROCESS",
        dedupe_key=f"payout:{review['id']}",
        payload={"payout_id": payout_id},
    )
    return "QUEUED"


def delivery_text(conn, *, session_id: str, generation: int, consent_revoked: bool, publish_started: bool) -> dict:
    session = conn.execute("SELECT * FROM call_sessions WHERE id = %s", (session_id,)).fetchone()
    if session is None or session["state"] == "ENDED":
        return {"state": "UNAVAILABLE", "text": None, "replayed": False}
    if publish_started:
        return {"state": "PUBLISH_STARTED", "text": None, "replayed": False}
    if consent_revoked:
        return {"state": "EXPIRED", "text": None, "replayed": False}
    task = conn.execute(
        "SELECT generation FROM call_tasks WHERE session_id = %s ORDER BY generation DESC LIMIT 1",
        (session_id,),
    ).fetchone()
    current = task["generation"] if task else generation
    if current != generation:
        return {
            "state": "QUEUED",
            "text": "The shared snapshot was from an earlier view. Check the item again.",
            "replayed": False,
        }
    return {"state": "PUBLISH_STARTED", "text": "The shared snapshot says the label was readable.", "replayed": False}
