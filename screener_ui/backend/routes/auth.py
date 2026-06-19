from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..auth import authenticate, current_user, token_pair, verify_token
from ..auth import add_user, change_own_password, change_user_password, public_users, remove_user, require_admin


router = APIRouter(prefix="/auth")


class LoginRequest(BaseModel):
    username: str
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class UserRequest(BaseModel):
    email: str
    password: str


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str


class AdminPasswordRequest(BaseModel):
    password: str


@router.post("/login")
def login(payload: LoginRequest) -> dict[str, Any]:
    user = authenticate(payload.username, payload.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    return token_pair(user.email)


@router.post("/refresh")
def refresh(payload: RefreshRequest) -> dict[str, Any]:
    user = verify_token(payload.refresh_token, "refresh")
    return token_pair(user.email)


@router.get("/me")
def me(user=Depends(current_user)) -> dict[str, Any]:
    return {"email": user.email, "is_admin": user.is_admin}


@router.get("/users")
def users(admin=Depends(require_admin)) -> list[dict[str, Any]]:
    return public_users()


@router.post("/users")
def create_user(payload: UserRequest, admin=Depends(require_admin)) -> dict[str, Any]:
    return add_user(payload.email, payload.password)


@router.delete("/users/{email}")
def delete_user(email: str, admin=Depends(require_admin)) -> dict[str, str]:
    remove_user(email)
    return {"status": "deleted"}


@router.put("/users/{email}/password")
def admin_change_password(email: str, payload: AdminPasswordRequest, admin=Depends(require_admin)) -> dict[str, str]:
    change_user_password(email, payload.password)
    return {"status": "updated"}


@router.put("/password")
def change_password(payload: PasswordChangeRequest, user=Depends(current_user)) -> dict[str, str]:
    change_own_password(user.email, payload.current_password, payload.new_password)
    return {"status": "updated"}
