from datetime import datetime, timedelta, timezone
from uuid import UUID
import jwt
from fastapi import HTTPException, Request, status
from pwdlib import PasswordHash
from .config import get_settings

password_hash = PasswordHash.recommended()
COOKIE_NAME = "access_token"


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    return password_hash.verify(password, hashed_password)


def create_access_token(user_id: UUID) -> str:
    settings = get_settings()
    expires = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
    return jwt.encode({"sub": str(user_id), "exp": expires}, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def get_user_id_from_request(request: Request) -> UUID:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    try:
        payload = jwt.decode(token, get_settings().jwt_secret_key, algorithms=[get_settings().jwt_algorithm])
        return UUID(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired session") from exc


def set_auth_cookie(response, user_id: UUID) -> None:
    settings = get_settings()
    response.set_cookie(
        key=COOKIE_NAME,
        value=create_access_token(user_id),
        max_age=settings.access_token_expire_minutes * 60,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


def clear_auth_cookie(response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")
