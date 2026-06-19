from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .settings import UI_ROOT


ACCESS_TOKEN_MINUTES = 60
REFRESH_TOKEN_DAYS = 2
ADMIN_EMAIL = "plal.besu@gmail.com"
AUTH_SECRET = os.environ.get("SCREENER_JWT_SECRET", "change-this-secret-before-deploying")
USERS_FILE = Path(os.environ.get("SCREENER_USERS_FILE", UI_ROOT / "backend" / "users.json"))
bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class CurrentUser:
    email: str

    @property
    def is_admin(self) -> bool:
        return self.email.lower() == ADMIN_EMAIL


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))


def _sign(message: str) -> str:
    return _b64url(hmac.new(AUTH_SECRET.encode("utf-8"), message.encode("ascii"), hashlib.sha256).digest())


def _json_part(data: dict[str, Any]) -> str:
    return _b64url(json.dumps(data, separators=(",", ":"), sort_keys=True).encode("utf-8"))


def create_token(email: str, token_type: str, expires_delta: timedelta) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": email.lower(),
        "typ": token_type,
        "iat": int(now.timestamp()),
        "exp": int((now + expires_delta).timestamp()),
    }
    header = {"alg": "HS256", "typ": "JWT"}
    message = f"{_json_part(header)}.{_json_part(payload)}"
    return f"{message}.{_sign(message)}"


def verify_token(token: str, expected_type: str = "access") -> CurrentUser:
    try:
        header_part, payload_part, signature = token.split(".", 2)
        message = f"{header_part}.{payload_part}"
        expected_signature = _sign(message)
        if not hmac.compare_digest(signature, expected_signature):
            raise ValueError("bad signature")
        payload = json.loads(_b64url_decode(payload_part))
        if payload.get("typ") != expected_type:
            raise ValueError("bad token type")
        if int(payload.get("exp", 0)) < int(datetime.now(timezone.utc).timestamp()):
            raise ValueError("expired")
        email = str(payload.get("sub") or "").strip().lower()
        if not email:
            raise ValueError("missing subject")
        return CurrentUser(email=email)
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired token") from exc


def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme)) -> CurrentUser:
    if not credentials:
        raise HTTPException(status_code=401, detail="Login required")
    return verify_token(credentials.credentials, "access")


def _pbkdf2_hash(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("ascii"), 210_000)
    return f"pbkdf2_sha256$210000${salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    stored = str(stored or "")
    if stored.startswith("pbkdf2_sha256$"):
        try:
            _, iterations, salt, digest = stored.split("$", 3)
            candidate = hashlib.pbkdf2_hmac(
                "sha256",
                password.encode("utf-8"),
                salt.encode("ascii"),
                int(iterations),
            ).hex()
            return hmac.compare_digest(candidate, digest)
        except Exception:
            return False
    return hmac.compare_digest(password, stored)


def load_users() -> list[dict[str, str]]:
    if not USERS_FILE.exists():
        return []
    data = json.loads(USERS_FILE.read_text(encoding="utf-8"))
    users = data.get("users", data if isinstance(data, list) else [])
    return [
        {
            "email": str(item.get("email") or item.get("username") or "").strip().lower(),
            "password": str(item.get("password_hash") or item.get("password") or ""),
        }
        for item in users
        if str(item.get("email") or item.get("username") or "").strip()
    ]


def save_users(users: list[dict[str, str]]) -> None:
    USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    normalized = []
    seen: set[str] = set()
    for item in users:
        email = str(item.get("email") or "").strip().lower()
        password = str(item.get("password") or "")
        if not email or email in seen:
            continue
        seen.add(email)
        normalized.append({"email": email, "password_hash": password})
    USERS_FILE.write_text(json.dumps({"users": normalized}, indent=2), encoding="utf-8")


def public_users() -> list[dict[str, Any]]:
    return [
        {"email": user["email"], "is_admin": user["email"] == ADMIN_EMAIL}
        for user in load_users()
    ]


def default_user_email() -> str:
    users = load_users()
    return users[0]["email"] if users else "local@example.com"


def authenticate(email: str, password: str) -> CurrentUser | None:
    email = email.strip().lower()
    for user in load_users():
        if user["email"] == email and verify_password(password, user["password"]):
            return CurrentUser(email=email)
    return None


def ensure_admin_user() -> None:
    users = load_users()
    if any(user["email"] == ADMIN_EMAIL for user in users):
        return
    users.insert(0, {"email": ADMIN_EMAIL, "password": _pbkdf2_hash("admin123")})
    save_users(users)


def require_admin(user: CurrentUser = Depends(current_user)) -> CurrentUser:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


def add_user(email: str, password: str) -> dict[str, Any]:
    email = email.strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Valid email is required")
    if len(password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
    users = load_users()
    if any(user["email"] == email for user in users):
        raise HTTPException(status_code=409, detail="User already exists")
    users.append({"email": email, "password": _pbkdf2_hash(password)})
    save_users(users)
    return {"email": email, "is_admin": email == ADMIN_EMAIL}


def remove_user(email: str) -> None:
    email = email.strip().lower()
    if email == ADMIN_EMAIL:
        raise HTTPException(status_code=400, detail="Admin user cannot be deleted")
    users = load_users()
    next_users = [user for user in users if user["email"] != email]
    if len(next_users) == len(users):
        raise HTTPException(status_code=404, detail="User not found")
    save_users(next_users)


def change_user_password(email: str, new_password: str) -> None:
    email = email.strip().lower()
    if len(new_password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
    users = load_users()
    for user in users:
        if user["email"] == email:
            user["password"] = _pbkdf2_hash(new_password)
            save_users(users)
            return
    raise HTTPException(status_code=404, detail="User not found")


def change_own_password(email: str, current_password: str, new_password: str) -> None:
    user = authenticate(email, current_password)
    if not user:
        raise HTTPException(status_code=401, detail="Current password is incorrect")
    change_user_password(email, new_password)


def token_pair(email: str) -> dict[str, Any]:
    return {
        "access_token": create_token(email, "access", timedelta(minutes=ACCESS_TOKEN_MINUTES)),
        "refresh_token": create_token(email, "refresh", timedelta(days=REFRESH_TOKEN_DAYS)),
        "token_type": "bearer",
        "expires_in": ACCESS_TOKEN_MINUTES * 60,
        "user": {"email": email.lower(), "is_admin": email.lower() == ADMIN_EMAIL},
    }
