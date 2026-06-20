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

from data.db_backend import connect, ensure_schemas, execute, integrity_error_types, is_postgres, system_schema, table_name

from .settings import UI_ROOT


ACCESS_TOKEN_MINUTES = 60
REFRESH_TOKEN_DAYS = 2
ADMIN_EMAIL = "plal.besu@gmail.com"
AUTH_SECRET = os.environ.get("SCREENER_JWT_SECRET", "change-this-secret-before-deploying")
USERS_FILE = Path(os.environ.get("SCREENER_USERS_FILE", UI_ROOT / "backend" / "users.json"))
T_AUTH_USERS = table_name("auth_users", system_schema())
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


def _load_file_users() -> list[dict[str, str]]:
    if not USERS_FILE.exists():
        return []
    data = json.loads(USERS_FILE.read_text(encoding="utf-8"))
    users = data.get("users", data if isinstance(data, list) else [])
    return [
        {
            "email": str(item.get("email") or item.get("username") or "").strip().lower(),
            "password": str(item.get("password_hash") or item.get("password") or ""),
            "disabled": bool(item.get("disabled", False)),
        }
        for item in users
        if str(item.get("email") or item.get("username") or "").strip()
    ]


def _bool_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on", "disabled"}


def _normalized_users(users: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized = []
    seen: set[str] = set()
    for item in users:
        email = str(item.get("email") or "").strip().lower()
        password = str(item.get("password") or item.get("password_hash") or "")
        if not email or email in seen:
            continue
        seen.add(email)
        normalized.append({"email": email, "password": password, "disabled": _bool_value(item.get("disabled", False))})
    return normalized


def _save_file_users(users: list[dict[str, Any]]) -> None:
    USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    normalized = [
        {"email": item["email"], "password_hash": item["password"], "disabled": bool(item.get("disabled", False))}
        for item in _normalized_users(users)
    ]
    USERS_FILE.write_text(json.dumps({"users": normalized}, indent=2), encoding="utf-8")


def _init_auth_table(conn) -> None:
    ensure_schemas(conn)
    execute(conn, f"""
        CREATE TABLE IF NOT EXISTS {T_AUTH_USERS} (
            email TEXT PRIMARY KEY,
            password_hash TEXT NOT NULL,
            disabled BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        )
    """)
    if is_postgres():
        execute(conn, f"ALTER TABLE {T_AUTH_USERS} ADD COLUMN IF NOT EXISTS disabled BOOLEAN NOT NULL DEFAULT FALSE")


def _import_file_users_to_db(conn) -> None:
    for user in _normalized_users(_load_file_users()):
        if not user["password"]:
            continue
        execute(conn, f"""
            INSERT INTO {T_AUTH_USERS} (email, password_hash, disabled)
            VALUES (?, ?, ?)
            ON CONFLICT (email) DO NOTHING
        """, (user["email"], user["password"], bool(user.get("disabled", False))))


def _remove_file_user(email: str) -> None:
    if not USERS_FILE.exists():
        return
    next_users = [user for user in _load_file_users() if user["email"] != email]
    _save_file_users(next_users)


def _set_file_user_disabled(email: str, disabled: bool) -> None:
    if not USERS_FILE.exists():
        return
    users = _load_file_users()
    changed = False
    for user in users:
        if user["email"] == email:
            user["disabled"] = disabled
            changed = True
    if changed:
        _save_file_users(users)


def load_users() -> list[dict[str, str]]:
    if is_postgres():
        with connect() as conn:
            _init_auth_table(conn)
            rows = execute(conn, f"""
                SELECT email, password_hash, disabled
                FROM {T_AUTH_USERS}
                ORDER BY created_at, email
            """).fetchall()
        return [
            {
                "email": str(row["email"]).lower(),
                "password": str(row["password_hash"]),
                "disabled": bool(row.get("disabled", False)),
            }
            for row in rows
        ]
    return _load_file_users()


def save_users(users: list[dict[str, str]]) -> None:
    normalized = _normalized_users(users)
    if is_postgres():
        with connect() as conn:
            _init_auth_table(conn)
            execute(conn, f"DELETE FROM {T_AUTH_USERS}")
            for user in normalized:
                execute(conn, f"""
                    INSERT INTO {T_AUTH_USERS} (email, password_hash, disabled)
                    VALUES (?, ?, ?)
                """, (user["email"], user["password"], bool(user.get("disabled", False))))
        return
    _save_file_users(normalized)


def public_users() -> list[dict[str, Any]]:
    return [
        {"email": user["email"], "is_admin": user["email"] == ADMIN_EMAIL, "disabled": bool(user.get("disabled", False))}
        for user in load_users()
    ]


def default_user_email() -> str:
    users = load_users()
    return users[0]["email"] if users else "local@example.com"


def authenticate(email: str, password: str) -> CurrentUser | None:
    email = email.strip().lower()
    for user in load_users():
        if user["email"] == email and not user.get("disabled", False) and verify_password(password, user["password"]):
            return CurrentUser(email=email)
    return None


def ensure_admin_user() -> None:
    if is_postgres():
        with connect() as conn:
            _init_auth_table(conn)
            _import_file_users_to_db(conn)
            row = execute(conn, f"SELECT email FROM {T_AUTH_USERS} WHERE email=?", (ADMIN_EMAIL,)).fetchone()
            if not row:
                execute(conn, f"""
                    INSERT INTO {T_AUTH_USERS} (email, password_hash, disabled)
                    VALUES (?, ?, FALSE)
                """, (ADMIN_EMAIL, _pbkdf2_hash("admin123")))
        return

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
    if is_postgres():
        try:
            with connect() as conn:
                _init_auth_table(conn)
                execute(conn, f"""
                    INSERT INTO {T_AUTH_USERS} (email, password_hash, disabled)
                    VALUES (?, ?, FALSE)
                """, (email, _pbkdf2_hash(password)))
        except integrity_error_types() as exc:
            raise HTTPException(status_code=409, detail="User already exists") from exc
        return {"email": email, "is_admin": email == ADMIN_EMAIL}

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
    from .store import delete_user_data

    if is_postgres():
        with connect() as conn:
            _init_auth_table(conn)
            row = execute(conn, f"SELECT email FROM {T_AUTH_USERS} WHERE email=?", (email,)).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="User not found")
        delete_user_data(email)
        with connect() as conn:
            _init_auth_table(conn)
            execute(conn, f"DELETE FROM {T_AUTH_USERS} WHERE email=?", (email,))
        _remove_file_user(email)
        return

    users = load_users()
    next_users = [user for user in users if user["email"] != email]
    if len(next_users) == len(users):
        raise HTTPException(status_code=404, detail="User not found")
    delete_user_data(email)
    save_users(next_users)


def set_user_disabled(email: str, disabled: bool) -> None:
    email = email.strip().lower()
    if email == ADMIN_EMAIL:
        raise HTTPException(status_code=400, detail="Admin user cannot be disabled")
    if is_postgres():
        with connect() as conn:
            _init_auth_table(conn)
            cur = execute(conn, f"""
                UPDATE {T_AUTH_USERS}
                SET disabled=?, updated_at=CURRENT_TIMESTAMP
                WHERE email=?
            """, (disabled, email))
            if getattr(cur, "rowcount", 0) == 0:
                raise HTTPException(status_code=404, detail="User not found")
        _set_file_user_disabled(email, disabled)
        return

    users = load_users()
    changed = False
    for user in users:
        if user["email"] == email:
            user["disabled"] = disabled
            changed = True
    if not changed:
        raise HTTPException(status_code=404, detail="User not found")
    save_users(users)


def change_user_password(email: str, new_password: str) -> None:
    email = email.strip().lower()
    if len(new_password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
    if is_postgres():
        with connect() as conn:
            _init_auth_table(conn)
            cur = execute(conn, f"""
                UPDATE {T_AUTH_USERS}
                SET password_hash=?, updated_at=CURRENT_TIMESTAMP
                WHERE email=?
            """, (_pbkdf2_hash(new_password), email))
            if getattr(cur, "rowcount", 0) == 0:
                raise HTTPException(status_code=404, detail="User not found")
        return

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
