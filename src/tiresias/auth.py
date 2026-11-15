from __future__ import annotations

import base64
import hashlib
import uuid
from datetime import datetime, timedelta, timezone

from tiresias.contracts import VerifiedCaller
from tiresias.security import csrf_token, hash_password, hash_token, new_token, verify_password


class AuthError(Exception):
    def __init__(self, code: str, status: int = 401) -> None:
        super().__init__(code)
        self.code = code
        self.status = status


def normalize_email(email: str) -> str:
    return email.strip().lower()


def fingerprint_phone(phone: str, key: str) -> str:
    return hashlib.sha256(f"{key}:{phone}".encode()).hexdigest()


def encrypt_phone(phone: str, key: str) -> str:
    raw = bytes(a ^ b for a, b in zip(phone.encode(), (key.encode() * 8)[: len(phone.encode())]))
    return base64.b64encode(raw).decode()


def create_user(conn, *, email: str, password: str, role: str, hasher, requested_role: str | None = None) -> dict:
    if requested_role is not None:
        raise AuthError("role_not_assignable", 403)
    if role not in {"USER", "HELPER", "OPERATOR"}:
        raise AuthError("role_not_assignable", 403)
    user_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO users (id, email_normalized, password_hash, role) VALUES (%s, %s, %s, %s)",
        (user_id, normalize_email(email), hash_password(password, hasher), role),
    )
    conn.execute("INSERT INTO profiles (user_id) VALUES (%s)", (user_id,))
    return {"id": user_id, "email": normalize_email(email), "role": role}


def login(conn, *, email: str, password: str, hasher, csrf: str | None, expected_csrf: str | None) -> dict:
    from tiresias.security import csrf_matches

    if expected_csrf is not None and not csrf_matches(csrf, expected_csrf):
        raise AuthError("csrf", 403)
    user = conn.execute("SELECT * FROM users WHERE email_normalized = %s", (normalize_email(email),)).fetchone()
    if user is None or user["disabled_at"] is not None or not verify_password(password, user["password_hash"], hasher):
        raise AuthError("invalid_login", 401)
    conn.execute(
        "UPDATE web_sessions SET revoked_at = now() WHERE user_id = %s AND revoked_at IS NULL",
        (user["id"],),
    )
    return _issue_session(conn, user["id"])


def _issue_session(conn, user_id: str) -> dict:
    token = new_token()
    csrf = csrf_token()
    session_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    conn.execute(
        """
        INSERT INTO web_sessions (id, token_hash, user_id, csrf_hash, expires_at, idle_expires_at)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (session_id, hash_token(token), user_id, hash_token(csrf), now + timedelta(hours=24), now + timedelta(minutes=30)),
    )
    return {"token": token, "csrf": csrf, "user_id": user_id, "session_id": session_id}


def logout(conn, token: str) -> None:
    conn.execute(
        "UPDATE web_sessions SET revoked_at = now() WHERE token_hash = %s AND revoked_at IS NULL",
        (hash_token(token),),
    )


def session_user(conn, token: str) -> dict | None:
    row = conn.execute(
        """
        SELECT s.*, u.role, u.disabled_at
        FROM web_sessions s JOIN users u ON u.id = s.user_id
        WHERE s.token_hash = %s AND s.revoked_at IS NULL AND s.expires_at > now() AND s.idle_expires_at > now()
        """,
        (hash_token(token),),
    ).fetchone()
    if row is None or row["disabled_at"] is not None:
        return None
    return row


def request_phone_link(conn, *, user_id: str, phone: str, key: str) -> dict:
    binding_id = str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO phone_bindings (id, user_id, phone_ciphertext, phone_fingerprint, state)
        VALUES (%s, %s, %s, %s, 'PENDING')
        """,
        (binding_id, user_id, encrypt_phone(phone, key), fingerprint_phone(phone, key)),
    )
    return {"binding_id": binding_id, "state": "PENDING"}


def confirm_phone_binding(conn, *, binding_id: str, actor_role: str, provider_identity: str) -> dict:
    if actor_role != "OPERATOR":
        raise AuthError("operator_only", 403)
    if not provider_identity:
        raise AuthError("missing_provider_evidence", 422)
    row = conn.execute(
        """
        UPDATE phone_bindings
        SET state = 'VERIFIED', provider_identity = %s, verification_source = 'operator', verified_at = now()
        WHERE id = %s AND state = 'PENDING'
        RETURNING *
        """,
        (provider_identity, binding_id),
    ).fetchone()
    if row is None:
        raise AuthError("binding_not_pending", 409)
    return row


def resolve_caller(conn, provider_context: dict) -> VerifiedCaller | None:
    identity = provider_context.get("trusted_provider_identity")
    epoch = provider_context.get("connection_epoch")
    if not identity or not epoch:
        return None
    binding = conn.execute(
        """
        SELECT * FROM phone_bindings
        WHERE provider_identity = %s AND state = 'VERIFIED'
        """,
        (identity,),
    ).fetchone()
    if binding is None:
        return None
    authorization = conn.execute(
        """
        SELECT * FROM call_sessions
        WHERE connection_epoch = %s AND user_id = %s AND state IN ('INITIALIZING', 'ACTIVE')
        """,
        (epoch, binding["user_id"]),
    ).fetchone()
    if authorization is None:
        return None
    return VerifiedCaller(
        user_id=str(binding["user_id"]),
        provider_identity=identity,
        binding_id=str(binding["id"]),
        verification_source=binding["verification_source"] or "operator",
        verified_at=authorization["started_at"].isoformat(),
    )


def accept_service_consent(conn, *, user_id: str, accepted: bool, version: str, current_version: str) -> dict:
    if accepted and version != current_version:
        raise AuthError("stale_consent", 409)
    if accepted:
        conn.execute(
            "UPDATE profiles SET service_consent_version = %s, service_consent_at = now() WHERE user_id = %s",
            (version, user_id),
        )
    else:
        conn.execute(
            "UPDATE profiles SET service_consent_version = NULL, service_consent_at = NULL WHERE user_id = %s",
            (user_id,),
        )
        conn.execute(
            """
            UPDATE call_sessions SET state = 'PROCESSING_REVOKED'
            WHERE user_id = %s AND state IN ('INITIALIZING', 'ACTIVE')
            """,
            (user_id,),
        )
    profile = conn.execute("SELECT * FROM profiles WHERE user_id = %s", (user_id,)).fetchone()
    return profile


def ai_allowed(conn, user_id: str, current_version: str) -> bool:
    profile = conn.execute("SELECT * FROM profiles WHERE user_id = %s", (user_id,)).fetchone()
    return bool(profile and profile["service_consent_version"] == current_version and profile["service_consent_at"])
