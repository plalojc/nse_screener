from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..store import (
    add_holding,
    add_watchlist,
    delete_holding,
    delete_watchlist,
    list_holdings,
    list_watchlist,
    update_holding,
)


router = APIRouter()


class WatchlistRequest(BaseModel):
    symbol: str
    notes: str = ""
    target_price: float | None = None


class HoldingRequest(BaseModel):
    symbol: str
    buy_date: str
    quantity: float = Field(gt=0)
    buy_price: float = Field(gt=0)
    notes: str = ""


def _payload_dict(payload: BaseModel) -> dict[str, Any]:
    if hasattr(payload, "model_dump"):
        return payload.model_dump()
    return payload.dict()


@router.get("/watchlist")
def watchlist() -> list[dict[str, Any]]:
    return list_watchlist()


@router.post("/watchlist")
def create_watchlist(payload: WatchlistRequest) -> dict[str, Any]:
    if not payload.symbol.strip():
        raise HTTPException(status_code=400, detail="Symbol is required")
    return add_watchlist(payload.symbol, payload.notes, payload.target_price)


@router.delete("/watchlist/{item_id}")
def remove_watchlist(item_id: int) -> dict[str, str]:
    delete_watchlist(item_id)
    return {"status": "deleted"}


@router.get("/holdings")
def holdings() -> list[dict[str, Any]]:
    return list_holdings()


@router.post("/holdings")
def create_holding(payload: HoldingRequest) -> dict[str, Any]:
    return add_holding(
        payload.symbol,
        payload.buy_date,
        payload.quantity,
        payload.buy_price,
        payload.notes,
    )


@router.put("/holdings/{item_id}")
def edit_holding(item_id: int, payload: HoldingRequest) -> dict[str, Any]:
    updated = update_holding(item_id, _payload_dict(payload))
    if not updated:
        raise HTTPException(status_code=404, detail="Holding not found")
    return updated


@router.delete("/holdings/{item_id}")
def remove_holding(item_id: int) -> dict[str, str]:
    delete_holding(item_id)
    return {"status": "deleted"}
