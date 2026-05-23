from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi import Query
from pydantic import BaseModel, Field

from ..store import (
    add_holding,
    add_watchlist,
    clear_watchlist,
    delete_holding,
    delete_watchlist,
    list_holdings,
    list_watchlist,
    profit_loss_report,
    sell_holding,
    update_holding,
    update_watchlist,
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


class SellHoldingRequest(BaseModel):
    sell_date: str
    quantity: float = Field(gt=0)
    sell_price: float = Field(gt=0)
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


@router.put("/watchlist/{item_id}")
def edit_watchlist(item_id: int, payload: WatchlistRequest) -> dict[str, Any]:
    updated = update_watchlist(item_id, _payload_dict(payload))
    if not updated:
        raise HTTPException(status_code=404, detail="Watchlist item not found")
    return updated


@router.delete("/watchlist/{item_id}")
def remove_watchlist(item_id: int) -> dict[str, str]:
    delete_watchlist(item_id)
    return {"status": "deleted"}


@router.delete("/watchlist")
def remove_all_watchlist() -> dict[str, Any]:
    deleted = clear_watchlist()
    return {"status": "cleared", "deleted": deleted}


@router.get("/holdings")
def holdings() -> list[dict[str, Any]]:
    return list_holdings()


@router.get("/profit-loss")
def profit_loss(
    from_date: str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$"),
    to_date: str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$"),
) -> dict[str, Any]:
    if from_date > to_date:
        raise HTTPException(status_code=400, detail="From date must be before To date")
    return profit_loss_report(from_date, to_date)


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


@router.post("/holdings/{item_id}/sell")
def sell(item_id: int, payload: SellHoldingRequest) -> dict[str, Any]:
    try:
        result = sell_holding(
            item_id,
            payload.sell_date,
            payload.quantity,
            payload.sell_price,
            payload.notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not result:
        raise HTTPException(status_code=404, detail="Holding not found")
    return result
