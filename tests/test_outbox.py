import uuid
from datetime import datetime, timedelta, timezone

import pytest

from tiresias.db import connect, migrate, reset_test_data
from tiresias.outbox import IdempotencyConflict, begin_idempotency, claim_jobs, complete_idempotency, enqueue_job, upsert_scene


@pytest.fixture()
def db():
    try:
        conn = connect()
        conn.execute("SELECT 1")
    except Exception as exc:
        pytest.skip(f"test postgres is unavailable: {exc}")
    migrate()
    reset_test_data(conn)
    yield conn
    conn.close()


def test_one_job_per_dedupe_key(db):
    first = enqueue_job(db, job_id=str(uuid.uuid4()), kind="REVIEW_DELIVER", dedupe_key="review-1", payload={"review_id": "1"})
    second = enqueue_job(db, job_id=str(uuid.uuid4()), kind="REVIEW_DELIVER", dedupe_key="review-1", payload={"review_id": "1"})
    db.commit()
    assert first["id"] == second["id"]


def test_expired_lease_can_be_reclaimed(db):
    job_id = str(uuid.uuid4())
    enqueue_job(db, job_id=job_id, kind="REVIEW_DELIVER", dedupe_key="lease", payload={})
    db.commit()
    first = claim_jobs(db, "worker-a", ["REVIEW_DELIVER"], 10)
    db.execute("UPDATE outbox_jobs SET lease_until = now() - interval '1 second' WHERE id = %s", (first[0]["id"],))
    db.commit()
    second = claim_jobs(db, "worker-b", ["REVIEW_DELIVER"], 10)
    db.commit()
    assert second[0]["lease_owner"] == "worker-b"


def test_expired_scene_payload_never_runs(db):
    enqueue_job(
        db,
        job_id=str(uuid.uuid4()),
        kind="SCENE_UPSERT",
        dedupe_key="old-scene",
        payload={"scene_id": "s"},
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=5),
    )
    db.commit()
    assert claim_jobs(db, "worker", ["SCENE_UPSERT"], 10) == []


def test_two_claimants_do_not_own_same_active_lease(db):
    enqueue_job(db, job_id=str(uuid.uuid4()), kind="PAYOUT_PROCESS", dedupe_key="pay", payload={})
    db.commit()
    first = claim_jobs(db, "worker-a", ["PAYOUT_PROCESS"], 10)
    second = claim_jobs(db, "worker-b", ["PAYOUT_PROCESS"], 10)
    db.commit()
    assert len(first) == 1
    assert second == []
    assert first[0]["lease_owner"] == "worker-a"


def test_cleanup_still_runs_after_evidence_expiry(db):
    enqueue_job(
        db,
        job_id=str(uuid.uuid4()),
        kind="DELETE_EVIDENCE",
        dedupe_key="delete-1",
        payload={},
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=5),
    )
    db.commit()
    claimed = claim_jobs(db, "janitor", ["DELETE_EVIDENCE"], 10)
    assert len(claimed) == 1


def test_reward_reconciliation_outlives_image_ttl(db):
    enqueue_job(
        db,
        job_id=str(uuid.uuid4()),
        kind="PAYOUT_PROCESS",
        dedupe_key="payout-1",
        payload={"payout_id": "p"},
        expires_at=datetime.now(timezone.utc) - timedelta(minutes=40),
    )
    db.commit()
    assert len(claim_jobs(db, "payer", ["PAYOUT_PROCESS"], 10)) == 1


def test_late_scene_upsert_cannot_extend_expiry_or_resurrect_deleted_user(db):
    user_id = str(uuid.uuid4())
    db.execute(
        "INSERT INTO users (id, email_normalized, password_hash, role) VALUES (%s, %s, 'x', 'USER')",
        (user_id, f"{user_id}@example.com"),
    )
    original = datetime.now(timezone.utc) + timedelta(minutes=30)
    created = upsert_scene(db, scene_id="scene-1", user_id=user_id, expires_at=original, payload={"text": "lemon"})
    later = original + timedelta(hours=5)
    updated = upsert_scene(db, scene_id="scene-1", user_id=user_id, expires_at=later, payload={"text": "changed"})
    assert updated["expires_at"] == created["expires_at"]
    db.execute("INSERT INTO deleted_users (user_id) VALUES (%s)", (user_id,))
    assert upsert_scene(db, scene_id="scene-2", user_id=user_id, expires_at=later, payload={"text": "no"}) is None


def test_identical_idempotency_body_replays_and_changed_body_conflicts(db):
    actor = str(uuid.uuid4())
    body = {"result": "READABLE"}
    first = begin_idempotency(db, actor_id=actor, route_key="complete", idempotency_key="k", body=body)
    complete_idempotency(db, actor_id=actor, route_key="complete", idempotency_key="k", status=200, result={"answer_status": "QUEUED"})
    replay = begin_idempotency(db, actor_id=actor, route_key="complete", idempotency_key="k", body=body)
    assert first["replay"] is False
    assert replay["replay"] is True
    assert replay["record"]["result_status"] == 200
    with pytest.raises(IdempotencyConflict):
        begin_idempotency(db, actor_id=actor, route_key="complete", idempotency_key="k", body={"result": "UNRESOLVED"})
