import hashlib
import secrets
from datetime import timedelta
from typing import Any

from bson import ObjectId
from fastapi import Depends, Header, HTTPException, status

from app.db import get_db
from app.utils.time import now_local

PBKDF2_ITERATIONS = 200_000
SESSION_TOKEN_BYTES = 32
RESET_CODE_BYTES = 3
RESET_CODE_TTL_MINUTES = 15


def normalize_email(email: str) -> str:
    return str(email or "").strip().lower()


def hash_password(password: str, *, salt: str | None = None) -> tuple[str, str]:
    salt_value = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt_value.encode("utf-8"),
        PBKDF2_ITERATIONS,
    )
    return salt_value, digest.hex()


def verify_password(password: str, salt: str, password_hash: str) -> bool:
    _, computed = hash_password(password, salt=salt)
    return secrets.compare_digest(computed, password_hash)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_reset_code() -> str:
    return secrets.token_hex(RESET_CODE_BYTES).upper()


async def create_session_token(user_id: ObjectId) -> str:
    db = get_db()
    raw_token = secrets.token_urlsafe(SESSION_TOKEN_BYTES)
    await db.user_sessions.insert_one(
        {
            "userId": user_id,
            "tokenHash": hash_token(raw_token),
            "createdAt": now_local(),
        }
    )
    return raw_token


def reset_code_expiry():
    return now_local() + timedelta(minutes=RESET_CODE_TTL_MINUTES)


def _bearer_token(authorization: str | None) -> str:
    raw = str(authorization or "").strip()
    if not raw.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    token = raw[7:].strip()
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    return token


async def get_current_user(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    token = _bearer_token(authorization)
    db = get_db()
    session = await db.user_sessions.find_one({"tokenHash": hash_token(token)})
    if not session:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session")

    user = await db.users.find_one({"_id": session["userId"]})
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


CurrentUser = Depends(get_current_user)


def user_id_filter(user: dict[str, Any]) -> dict[str, Any]:
    return {"userId": user["_id"]}


def user_id_str(user: dict[str, Any]) -> str:
    return str(user["_id"])


async def migrate_legacy_data_to_user(user_id: ObjectId) -> None:
    db = get_db()
    legacy_filter = {"userId": {"$exists": False}}
    await db.vocabs.update_many(legacy_filter, {"$set": {"userId": user_id}})
    await db.review_logs.update_many(legacy_filter, {"$set": {"userId": user_id}})
    await db.practice_logs.update_many(legacy_filter, {"$set": {"userId": user_id}})
    await db.topic_packs.update_many(legacy_filter, {"$set": {"userId": user_id}})
    await db.writing_errors.update_many(legacy_filter, {"$set": {"userId": user_id}})
    await db.events.update_many(legacy_filter, {"$set": {"userId": user_id}})
