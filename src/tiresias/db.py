from __future__ import annotations

import os
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = ROOT / "migrations"
SURVIVING_KINDS = ("DELETE_EVIDENCE", "PAYOUT_PROCESS", "SESSION_REVOKE")
APP_DATABASE_NAMES = {"tiresias", "postgres"}


def test_database_url() -> str:
    url = os.environ.get(
        "TEST_DATABASE_URL",
        "postgresql://postgres:postgres@localhost:54329/tiresias_test",
    )
    app_url = os.environ.get("DATABASE_URL", "")
    if app_url and url == app_url:
        raise RuntimeError("the test harness refuses the normal application database")
    database_name = url.rstrip("/").rsplit("/", 1)[-1]
    if database_name in APP_DATABASE_NAMES or not database_name.endswith("_test"):
        raise RuntimeError(f"refusing non-test database {database_name}")
    return url


def connect(url: str | None = None):
    return psycopg.connect(url or test_database_url(), row_factory=dict_row)


def migrate(url: str | None = None) -> None:
    with connect(url) as conn:
        for path in sorted(MIGRATIONS.glob("*.sql")):
            conn.execute(path.read_text(encoding="utf-8"))
        conn.commit()


def reset_test_data(conn) -> None:
    conn.execute(
        """
        TRUNCATE
            idempotency_records, outbox_jobs, stage_events, scene_reports, deleted_users,
            payouts, call_reward_reservations, reviews, snapshots, snapshot_consents,
            call_tasks, call_sessions, helper_grants, phone_bindings, profiles,
            web_sessions, users
        RESTART IDENTITY CASCADE
        """
    )
    conn.commit()
