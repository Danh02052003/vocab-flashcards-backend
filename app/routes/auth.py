from fastapi import APIRouter, Header, HTTPException, status
from pymongo.errors import DuplicateKeyError

from app.db import get_db
from app.models.auth import (
    AuthTokenResponse,
    ForgotPasswordRequest,
    ForgotPasswordResponse,
    ResetPasswordRequest,
    UserLoginRequest,
    UserOut,
    UserRegisterRequest,
)
from app.services.auth import (
    CurrentUser,
    _bearer_token,
    create_session_token,
    generate_reset_code,
    hash_token,
    hash_password,
    migrate_legacy_data_to_user,
    normalize_email,
    reset_code_expiry,
    verify_password,
)
from app.utils.time import now_local

router = APIRouter(prefix="/auth", tags=["auth"])


def _to_user_out(doc: dict) -> UserOut:
    return UserOut(
        id=str(doc["_id"]),
        name=str(doc.get("name") or ""),
        email=str(doc.get("email") or ""),
        createdAt=doc["createdAt"],
    )


@router.post("/register", response_model=AuthTokenResponse)
async def register(payload: UserRegisterRequest):
    db = get_db()
    now = now_local()
    email_normalized = normalize_email(payload.email)
    salt, password_hash = hash_password(payload.password)

    existing_users = await db.users.count_documents({})
    try:
        result = await db.users.insert_one(
            {
                "name": payload.name.strip(),
                "email": str(payload.email),
                "emailNormalized": email_normalized,
                "passwordSalt": salt,
                "passwordHash": password_hash,
                "createdAt": now,
                "updatedAt": now,
            }
        )
    except DuplicateKeyError:
        raise HTTPException(status_code=409, detail="Email already exists")

    user = await db.users.find_one({"_id": result.inserted_id})
    if existing_users == 0:
        await migrate_legacy_data_to_user(user["_id"])

    token = await create_session_token(user["_id"])
    return AuthTokenResponse(token=token, user=_to_user_out(user))


@router.post("/login", response_model=AuthTokenResponse)
async def login(payload: UserLoginRequest):
    db = get_db()
    user = await db.users.find_one({"emailNormalized": normalize_email(payload.email)})
    if not user or not verify_password(payload.password, user["passwordSalt"], user["passwordHash"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

    token = await create_session_token(user["_id"])
    return AuthTokenResponse(token=token, user=_to_user_out(user))


@router.post("/forgot-password", response_model=ForgotPasswordResponse)
async def forgot_password(payload: ForgotPasswordRequest):
    db = get_db()
    user = await db.users.find_one({"emailNormalized": normalize_email(payload.email)})
    if not user:
        return ForgotPasswordResponse(message="If the email exists, a reset code has been generated.", resetCode=None)

    reset_code = generate_reset_code()
    await db.users.update_one(
        {"_id": user["_id"]},
        {
            "$set": {
                "passwordResetCodeHash": hash_token(reset_code),
                "passwordResetExpiresAt": reset_code_expiry(),
                "updatedAt": now_local(),
            }
        },
    )
    return ForgotPasswordResponse(
        message="Reset code created. Use it below to set a new password.",
        resetCode=reset_code,
    )


@router.post("/reset-password")
async def reset_password(payload: ResetPasswordRequest):
    db = get_db()
    user = await db.users.find_one({"emailNormalized": normalize_email(payload.email)})
    if not user:
        raise HTTPException(status_code=404, detail="Account not found")

    code_hash = str(user.get("passwordResetCodeHash") or "")
    expires_at = user.get("passwordResetExpiresAt")
    if not code_hash or not expires_at or now_local() > expires_at:
        raise HTTPException(status_code=400, detail="Reset code expired. Request a new one.")

    if hash_token(payload.resetCode.strip().upper()) != code_hash:
        raise HTTPException(status_code=400, detail="Reset code is invalid")

    salt, password_hash = hash_password(payload.newPassword)
    await db.users.update_one(
        {"_id": user["_id"]},
        {
            "$set": {
                "passwordSalt": salt,
                "passwordHash": password_hash,
                "updatedAt": now_local(),
            },
            "$unset": {
                "passwordResetCodeHash": "",
                "passwordResetExpiresAt": "",
            },
        },
    )
    await db.user_sessions.delete_many({"userId": user["_id"]})
    return {"reset": True}


@router.post("/logout")
async def logout(current_user=CurrentUser, authorization: str | None = Header(default=None)):
    del current_user

    db = get_db()
    token = _bearer_token(authorization)
    await db.user_sessions.delete_one({"tokenHash": hash_token(token)})
    return {"loggedOut": True}


@router.get("/me", response_model=UserOut)
async def me(current_user=CurrentUser):
    return _to_user_out(current_user)
