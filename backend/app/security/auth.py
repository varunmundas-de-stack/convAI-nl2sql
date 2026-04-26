import os
from datetime import datetime, timedelta, timezone
from typing import Annotated

import jwt 
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.security.context import UserContext
from app.security.metadata_store import get_user_by_id, get_user_by_username, update_last_login

try:
    import bcrypt
except Exception:  # pragma: no cover - dependency is present in Docker after requirements install
    bcrypt = None


bearer = HTTPBearer(auto_error=False)


def _secret() -> str:
    return os.getenv("APP_JWT_SECRET") or os.getenv("CUBEJS_API_SECRET") or "dev-secret-change-me"


def verify_password(password: str, stored_hash: str) -> bool:
    if stored_hash.startswith("plain:"):
        return password == stored_hash.removeprefix("plain:")
    if not bcrypt:
        return False
    return bcrypt.checkpw(password.encode("utf-8"), stored_hash.encode("utf-8"))


def authenticate_user(username: str, password: str) -> UserContext | None:
    result = get_user_by_username(username)
    if not result:
        return None
    user, stored_hash = result
    if not verify_password(password, stored_hash):
        return None
    update_last_login(user.user_id)
    return user


def create_access_token(user: UserContext) -> str:
    now = datetime.now(tz=timezone.utc)
    payload = {
        **user.profile(),
        "sub": str(user.user_id),
        "iat": now,
        "exp": now + timedelta(hours=int(os.getenv("APP_JWT_HOURS", "8"))),
    }
    return jwt.encode(payload, _secret(), algorithm="HS256")


def create_cube_token(user: UserContext) -> str:
    secret = os.getenv("CUBEJS_API_SECRET", "mysecretkey123")
    now = datetime.now(tz=timezone.utc)
    payload = {
        "clientId": user.client_id,
        "schemaName": user.schema_name,
        "userId": user.user_id,
        "username": user.username,
        "role": user.role,
        "hierarchy_code": user.hierarchy_code,
        "salesrep_code": user.salesrep_code,
        "so_code": user.so_code,
        "asm_code": user.asm_code,
        "zsm_code": user.zsm_code,
        "nsm_code": user.nsm_code,
        "iat": now,
        "exp": now + timedelta(hours=8),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def decode_access_token(token: str) -> dict:
    try:
        return jwt.decode(token, _secret(), algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        ) from exc


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]
) -> UserContext:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    payload = decode_access_token(credentials.credentials)
    user = get_user_by_id(int(payload["sub"]))
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User no longer active")
    return user


def require_admin(user: Annotated[UserContext, Depends(get_current_user)]) -> UserContext:
    if (user.role or "").lower() != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required")
    return user
