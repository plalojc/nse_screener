from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi import Query
from pydantic import BaseModel, Field

from ..auth import CurrentUser, current_user
from ..store import (
    add_holding,
    add_watchlist,
    clear_watchlist,
    delete_holding,
    delete_profit_loss_sale,
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
def watchlist(user: CurrentUser = Depends(current_user)) -> list[dict[str, Any]]:
    return list_watchlist(user.email)


@router.post("/watchlist")
def create_watchlist(payload: WatchlistRequest, user: CurrentUser = Depends(current_user)) -> dict[str, Any]:
    if not payload.symbol.strip():
        raise HTTPException(status_code=400, detail="Symbol is required")
    return add_watchlist(user.email, payload.symbol, payload.notes, payload.target_price)


@router.put("/watchlist/{item_id}")
def edit_watchlist(item_id: int, payload: WatchlistRequest, user: CurrentUser = Depends(current_user)) -> dict[str, Any]:
    updated = update_watchlist(user.email, item_id, _payload_dict(payload))
    if not updated:
        raise HTTPException(status_code=404, detail="Watchlist item not found")
    return updated


@router.delete("/watchlist/{item_id}")
def remove_watchlist(item_id: int, user: CurrentUser = Depends(current_user)) -> dict[str, str]:
    delete_watchlist(user.email, item_id)
    return {"status": "deleted"}


@router.delete("/watchlist")
def remove_all_watchlist(user: CurrentUser = Depends(current_user)) -> dict[str, Any]:
    deleted = clear_watchlist(user.email)
    return {"status": "cleared", "deleted": deleted}


@router.get("/holdings")
def holdings(user: CurrentUser = Depends(current_user)) -> list[dict[str, Any]]:
    return list_holdings(user.email)


@router.get("/profit-loss")
def profit_loss(
    from_date: str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$"),
    to_date: str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$"),
    user: CurrentUser = Depends(current_user),
) -> dict[str, Any]:
    if from_date > to_date:
        raise HTTPException(status_code=400, detail="From date must be before To date")
    return profit_loss_report(user.email, from_date, to_date)


@router.delete("/profit-loss/{sale_id}")
def remove_profit_loss_sale(sale_id: int, user: CurrentUser = Depends(current_user)) -> dict[str, str]:
    deleted = delete_profit_loss_sale(user.email, sale_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="P/L row not found")
    return {"status": "deleted"}


@router.post("/holdings")
def create_holding(payload: HoldingRequest, user: CurrentUser = Depends(current_user)) -> dict[str, Any]:
    return add_holding(
        user.email,
        payload.symbol,
        payload.buy_date,
        payload.quantity,
        payload.buy_price,
        payload.notes,
    )


@router.put("/holdings/{item_id}")
def edit_holding(item_id: int, payload: HoldingRequest, user: CurrentUser = Depends(current_user)) -> dict[str, Any]:
    updated = update_holding(user.email, item_id, _payload_dict(payload))
    if not updated:
        raise HTTPException(status_code=404, detail="Holding not found")
    return updated


@router.delete("/holdings/{item_id}")
def remove_holding(item_id: int, user: CurrentUser = Depends(current_user)) -> dict[str, str]:
    delete_holding(user.email, item_id)
    return {"status": "deleted"}


@router.post("/holdings/{item_id}/sell")
def sell(item_id: int, payload: SellHoldingRequest, user: CurrentUser = Depends(current_user)) -> dict[str, Any]:
    try:
        result = sell_holding(
            user.email,
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
