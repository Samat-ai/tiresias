from __future__ import annotations

import hashlib
import hmac
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError


COMMON_PASSWORDS = {"passwordpassword", "correcthorsebatterystaple"}


def password_hasher(*, memory_kib: int = 65536, time_cost: int = 3, parallelism: int = 1) -> PasswordHasher:
    return PasswordHasher(memory_cost=memory_kib, time_cost=time_cost, parallelism=parallelism)


def validate_password(password: str) -> None:
    if not isinstance(password, str) or not 15 <= len(password) <= 128:
        raise ValueError("password must be 15 to 128 characters")
    if password.lower() in COMMON_PASSWORDS:
        raise ValueError("password is too common")


def hash_password(password: str, hasher: PasswordHasher) -> str:
    validate_password(password)
    return hasher.hash(password)


def verify_password(password: str, password_hash: str, hasher: PasswordHasher) -> bool:
    try:
        return hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False


def new_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def csrf_token() -> str:
    return secrets.token_urlsafe(32)


def csrf_matches(header: str | None, expected_hash: str) -> bool:
    if not header:
        return False
    return hmac.compare_digest(hash_token(header), expected_hash)
