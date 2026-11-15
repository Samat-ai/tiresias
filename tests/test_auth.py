import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from tiresias.auth import (
    AuthError,
    accept_service_consent,
    ai_allowed,
    confirm_phone_binding,
    create_user,
    login,
    logout,
    request_phone_link,
    resolve_caller,
    session_user,
)
from tiresias.db import connect, migrate, reset_test_data
from tiresias.security import hash_token, password_hasher
from tiresias.reviews import ReviewError, complete_review, create_review, delivery_text, read_snapshot
from tiresias.rewards import DeterministicSigner, DevnetRewardService, RpcTimeout, UnknownSend


HASHER = password_hasher(memory_kib=8192, time_cost=1, parallelism=1)
CONSENT = "2026-11-14.v1"


@pytest.fixture()
def db():
    directory = Path("data/pytest-snapshots")
    directory.mkdir(parents=True, exist_ok=True)
    try:
        conn = connect()
        conn.execute("SELECT 1")
    except Exception as exc:
        pytest.skip(f"test postgres is unavailable: {exc}")
    migrate()
    reset_test_data(conn)
    yield conn, directory
    conn.close()


def test_production_argon2_defaults():
    from tiresias.config import Settings

    settings = Settings()
    assert (settings.argon2_memory_kib, settings.argon2_time_cost, settings.argon2_parallelism) == (65536, 3, 1)


def test_user_cannot_assign_role(db):
    conn, _path = db
    with pytest.raises(AuthError) as caught:
        create_user(conn, email="a@example.com", password="a-long-passphrase", role="USER", hasher=HASHER, requested_role="OPERATOR")
    assert caught.value.status == 403


def test_login_rotates_token_and_logout_revokes_it(db):
    conn, _path = db
    create_user(conn, email="a@example.com", password="a-long-passphrase", role="USER", hasher=HASHER)
    first = login(conn, email="a@example.com", password="a-long-passphrase", hasher=HASHER, csrf=None, expected_csrf=None)
    second = login(conn, email="a@example.com", password="a-long-passphrase", hasher=HASHER, csrf=None, expected_csrf=None)
    assert first["token"] != second["token"]
    assert session_user(conn, first["token"]) is None
    assert session_user(conn, second["token"])["user_id"] == second["user_id"]
    logout(conn, second["token"])
    assert session_user(conn, second["token"]) is None


def test_mutation_requires_csrf(db):
    conn, _path = db
    create_user(conn, email="a@example.com", password="a-long-passphrase", role="USER", hasher=HASHER)
    with pytest.raises(AuthError) as caught:
        login(conn, email="a@example.com", password="a-long-passphrase", hasher=HASHER, csrf="nope", expected_csrf=hash_token("expected"))
    assert caught.value.status == 403


def test_phone_entry_stays_pending_until_operator_confirms(db):
    conn, _path = db
    user = create_user(conn, email="a@example.com", password="a-long-passphrase", role="USER", hasher=HASHER)
    operator = create_user(conn, email="op@example.com", password="a-long-passphrase", role="OPERATOR", hasher=HASHER)
    pending = request_phone_link(conn, user_id=user["id"], phone="+12145550100", key="test-key")
    assert pending["state"] == "PENDING"
    with pytest.raises(AuthError):
        confirm_phone_binding(conn, binding_id=pending["binding_id"], actor_role="USER", provider_identity="caller-1")
    verified = confirm_phone_binding(conn, binding_id=pending["binding_id"], actor_role=operator["role"], provider_identity="caller-1")
    assert verified["state"] == "VERIFIED"
    assert operator["role"] == "OPERATOR"


def test_forged_participant_metadata_cannot_select_user(db):
    conn, _path = db
    assert resolve_caller(conn, {"participant_name": "user-a", "room": "demo", "from_handle_hash": None}) is None


def test_unknown_caller_no_profile(db):
    conn, _path = db
    assert resolve_caller(conn, {"trusted_provider_identity": "missing", "connection_epoch": "epoch-1"}) is None


def test_old_call_authorization_not_reused(db):
    conn, _path = db
    user = create_user(conn, email="a@example.com", password="a-long-passphrase", role="USER", hasher=HASHER)
    binding = request_phone_link(conn, user_id=user["id"], phone="+12145550100", key="test-key")
    confirm_phone_binding(conn, binding_id=binding["binding_id"], actor_role="OPERATOR", provider_identity="caller-1")
    _session(conn, user["id"], "epoch-1", "ENDED")
    assert resolve_caller(conn, {"trusted_provider_identity": "caller-1", "connection_epoch": "epoch-1"}) is None
    _session(conn, user["id"], "epoch-2", "ACTIVE")
    caller = resolve_caller(conn, {"trusted_provider_identity": "caller-1", "connection_epoch": "epoch-2"})
    assert caller.user_id == user["id"]


def test_missing_or_old_service_consent_blocks_ai_and_revocation_stops_processing(db):
    conn, _path = db
    user = create_user(conn, email="a@example.com", password="a-long-passphrase", role="USER", hasher=HASHER)
    assert ai_allowed(conn, user["id"], CONSENT) is False
    with pytest.raises(AuthError):
        accept_service_consent(conn, user_id=user["id"], accepted=True, version="old", current_version=CONSENT)
    assert ai_allowed(conn, user["id"], CONSENT) is False
    accept_service_consent(conn, user_id=user["id"], accepted=True, version=CONSENT, current_version=CONSENT)
    session_id = _session(conn, user["id"], "epoch-3", "ACTIVE")
    assert ai_allowed(conn, user["id"], CONSENT) is True
    accept_service_consent(conn, user_id=user["id"], accepted=False, version=CONSENT, current_version=CONSENT)
    state = conn.execute("SELECT state FROM call_sessions WHERE id = %s", (session_id,)).fetchone()
    assert state["state"] == "PROCESSING_REVOKED"
    assert ai_allowed(conn, user["id"], CONSENT) is False


def test_snapshot_consent_isolation_and_review_reward_cap(db):
    conn, directory = db
    owner = create_user(conn, email="owner@example.com", password="a-long-passphrase", role="USER", hasher=HASHER)
    helper = create_user(conn, email="helper@example.com", password="a-long-passphrase", role="HELPER", hasher=HASHER)
    other = create_user(conn, email="other@example.com", password="a-long-passphrase", role="USER", hasher=HASHER)
    session_id = _session(conn, owner["id"], "epoch-4", "ACTIVE")
    task_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO helper_grants (id, owner_id, helper_id, state) VALUES (%s, %s, %s, 'ACCEPTED')",
        (str(uuid.uuid4()), owner["id"], helper["id"]),
    )
    created = create_review(
        conn,
        owner_id=owner["id"],
        helper_id=helper["id"],
        session_id=session_id,
        task_id=task_id,
        generation=1,
        frame_id="frame-1",
        image_bytes=b"jpeg-bytes",
        snapshot_dir=directory,
    )
    assert read_snapshot(conn, actor_id=helper["id"], snapshot_id=created["snapshot_id"], snapshot_dir=directory) == b"jpeg-bytes"
    with pytest.raises(ReviewError) as missing:
        read_snapshot(conn, actor_id=other["id"], snapshot_id=created["snapshot_id"], snapshot_dir=directory)
    assert missing.value.status == 404
    conn.execute("UPDATE helper_grants SET state = 'REVOKED' WHERE helper_id = %s", (helper["id"],))
    with pytest.raises(ReviewError):
        read_snapshot(conn, actor_id=helper["id"], snapshot_id=created["snapshot_id"], snapshot_dir=directory)
    conn.execute("UPDATE helper_grants SET state = 'ACCEPTED' WHERE helper_id = %s", (helper["id"],))
    conn.execute("UPDATE snapshots SET expires_at = now() - interval '1 second' WHERE id = %s", (created["snapshot_id"],))
    with pytest.raises(ReviewError) as expired:
        read_snapshot(conn, actor_id=owner["id"], snapshot_id=created["snapshot_id"], snapshot_dir=directory)
    assert expired.value.status == 410


def test_duplicate_completion_is_one_payout_and_cap_still_queues_answer(db):
    conn, directory = db
    owner = create_user(conn, email="owner@example.com", password="a-long-passphrase", role="USER", hasher=HASHER)
    helper = create_user(conn, email="helper@example.com", password="a-long-passphrase", role="HELPER", hasher=HASHER)
    session_id = _session(conn, owner["id"], "epoch-5", "ACTIVE")
    conn.execute(
        "INSERT INTO helper_grants (id, owner_id, helper_id, state) VALUES (%s, %s, %s, 'ACCEPTED')",
        (str(uuid.uuid4()), owner["id"], helper["id"]),
    )
    reviews = [
        create_review(
            conn,
            owner_id=owner["id"],
            helper_id=helper["id"],
            session_id=session_id,
            task_id=str(uuid.uuid4()),
            generation=index,
            frame_id=f"frame-{index}",
            image_bytes=b"jpeg",
            snapshot_dir=directory,
        )
        for index in range(1, 5)
    ]
    first = complete_review(conn, actor_id=helper["id"], review_id=reviews[0]["review_id"], result="READABLE", literal_text="LEMON", notes=None, expected_version=1, helper_wallet="HelperWallet", rewards_enabled=True, lamports=50_000_000)
    replay = complete_review(conn, actor_id=helper["id"], review_id=reviews[0]["review_id"], result="READABLE", literal_text="LEMON", notes=None, expected_version=2, helper_wallet="HelperWallet", rewards_enabled=True, lamports=50_000_000)
    assert first["reward_status"] == "QUEUED"
    assert replay["answer_status"] == "QUEUED"
    assert conn.execute("SELECT count(*) AS n FROM payouts").fetchone()["n"] == 1
    with pytest.raises(ReviewError):
        complete_review(conn, actor_id=helper["id"], review_id=reviews[0]["review_id"], result="UNRESOLVED", literal_text=None, notes=None, expected_version=2, helper_wallet="HelperWallet", rewards_enabled=True, lamports=50_000_000)
    for review in reviews[1:3]:
        done = complete_review(conn, actor_id=helper["id"], review_id=review["review_id"], result="READABLE", literal_text="LEMON", notes=None, expected_version=1, helper_wallet="HelperWallet", rewards_enabled=True, lamports=50_000_000)
        assert done["answer_status"] == "QUEUED"
    capped = complete_review(conn, actor_id=helper["id"], review_id=reviews[3]["review_id"], result="READABLE", literal_text="LEMON", notes=None, expected_version=1, helper_wallet=None, rewards_enabled=True, lamports=50_000_000)
    assert capped["reward_status"] == "NOT_ENROLLED"
    assert capped["answer_status"] == "QUEUED"
    conn.execute("UPDATE call_reward_reservations SET reserved_count = 3 WHERE call_session_id = %s", (session_id,))
    extra = create_review(conn, owner_id=owner["id"], helper_id=helper["id"], session_id=session_id, task_id=str(uuid.uuid4()), generation=9, frame_id="frame-9", image_bytes=b"jpeg", snapshot_dir=directory)
    reached = complete_review(conn, actor_id=helper["id"], review_id=extra["review_id"], result="UNRESOLVED", literal_text=None, notes=None, expected_version=1, helper_wallet="HelperWallet", rewards_enabled=True, lamports=50_000_000)
    assert reached["reward_status"] == "CAP_REACHED"
    assert reached["answer_status"] == "QUEUED"


def test_review_delivery_stays_on_the_original_call(db):
    conn, _path = db
    owner = create_user(conn, email="owner@example.com", password="a-long-passphrase", role="USER", hasher=HASHER)
    active = _session(conn, owner["id"], "epoch-live", "ACTIVE")
    ended = _session(conn, owner["id"], "epoch-next", "ENDED")
    conn.execute(
        "INSERT INTO call_tasks (id, session_id, generation, analysis_revision, state, version, expires_at) VALUES (%s, %s, 2, 1, 'FINDING', 1, now() + interval '30 minutes')",
        (str(uuid.uuid4()), active),
    )
    stale = delivery_text(conn, session_id=active, generation=1, consent_revoked=False, publish_started=False)
    assert "earlier view" in stale["text"]
    blocked = delivery_text(conn, session_id=active, generation=2, consent_revoked=True, publish_started=False)
    assert blocked["text"] is None
    crashed = delivery_text(conn, session_id=active, generation=2, consent_revoked=False, publish_started=True)
    assert crashed["replayed"] is False
    assert crashed["text"] is None
    missed = delivery_text(conn, session_id=ended, generation=1, consent_revoked=False, publish_started=False)
    assert missed["state"] == "UNAVAILABLE"


def test_reward_timeout_reuses_signed_bytes_and_unknown_does_not_resign(db):
    conn, directory = db
    payout_id = _payout(conn, directory)
    signer = DeterministicSigner()
    rpc = FlakyRpc(fail_with=RpcTimeout)
    service = DevnetRewardService(signer, rpc, lamports=50_000_000, recipient="HelperWallet")
    prepared = service.prepare_payout(conn, payout_id)
    again = service.prepare_payout(conn, payout_id)
    assert signer.calls == 1
    assert again.signature == prepared.signature
    submitted = service.reconcile_payout(conn, payout_id)
    assert submitted.state.value == "SUBMITTED"
    assert signer.calls == 1
    rpc.fail_with = UnknownSend
    unknown = service.reconcile_payout(conn, payout_id)
    assert unknown.state.value == "UNKNOWN"
    still = service.reconcile_payout(conn, payout_id)
    assert still.signature == prepared.signature
    assert signer.calls == 1


def test_client_cannot_choose_amount_or_recipient(db):
    conn, directory = db
    payout_id = _payout(conn, directory)
    service = DevnetRewardService(DeterministicSigner(), FlakyRpc(), lamports=1, recipient="OtherWallet")
    with pytest.raises(PermissionError):
        service.prepare_payout(conn, payout_id)


class FlakyRpc:
    def __init__(self, fail_with: type[Exception] | None = None) -> None:
        self.fail_with = fail_with
        self.sent: list[bytes] = []

    def send(self, payload: bytes) -> None:
        self.sent.append(payload)
        if self.fail_with:
            error = self.fail_with
            self.fail_with = None
            raise error()

    def status(self, signature: str) -> str:
        return "confirmed" if signature else "unknown"


def _session(conn, user_id: str, epoch: str, state: str) -> str:
    session_id = str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO call_sessions
            (id, connection_epoch, user_id, room_name, authorization_source, source, state)
        VALUES (%s, %s, %s, 'room', 'operator', 'FACETIME', %s)
        """,
        (session_id, epoch, user_id, state),
    )
    return session_id


def _payout(conn, directory: Path) -> str:
    owner = create_user(conn, email=f"{uuid.uuid4()}@example.com", password="a-long-passphrase", role="USER", hasher=HASHER)
    helper = create_user(conn, email=f"{uuid.uuid4()}@example.com", password="a-long-passphrase", role="HELPER", hasher=HASHER)
    session_id = _session(conn, owner["id"], str(uuid.uuid4()), "ACTIVE")
    conn.execute(
        "INSERT INTO helper_grants (id, owner_id, helper_id, state) VALUES (%s, %s, %s, 'ACCEPTED')",
        (str(uuid.uuid4()), owner["id"], helper["id"]),
    )
    review = create_review(
        conn,
        owner_id=owner["id"],
        helper_id=helper["id"],
        session_id=session_id,
        task_id=str(uuid.uuid4()),
        generation=1,
        frame_id="frame",
        image_bytes=b"jpeg",
        snapshot_dir=directory,
    )
    done = complete_review(
        conn,
        actor_id=helper["id"],
        review_id=review["review_id"],
        result="READABLE",
        literal_text="LEMON",
        notes=None,
        expected_version=1,
        helper_wallet="HelperWallet",
        rewards_enabled=True,
        lamports=50_000_000,
    )
    assert done["reward_status"] == "QUEUED"
    return str(conn.execute("SELECT id FROM payouts WHERE review_id = %s", (review["review_id"],)).fetchone()["id"])
