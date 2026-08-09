"""Natural-language algorithmic scanner endpoints."""

import asyncio

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_db
from app.schemas.technical import TechnicalScanRequest, TechnicalScanResponse
from app.services.technical_scanner import run_technical_scan
from app.services.yahoo_live import get_yahoo_live_stream

router = APIRouter()


@router.get("/status")
async def technical_status() -> dict:
    settings = get_settings()
    live_status = get_yahoo_live_stream().status()
    return {
        "market": "IN",
        "universe": "NSE_MAINBOARD",
        "preferred_source": "Yahoo Finance live stream",
        "active_source": (
            "Upstox V3"
            if settings.upstox_access_token.strip()
            else (
                "Yahoo history + live WebSocket"
                if settings.yahoo_live_stream_enabled
                else "Yahoo Finance history"
            )
        ),
        "upstox_configured": bool(settings.upstox_access_token.strip()),
        "yahoo_stream": live_status,
        "default_interval": "1m",
        "supported_intervals": ["1m", "5m", "15m", "30m", "1h", "1d"],
        "minimum_candles": 35,
        "maximum_candles": 70,
        "concurrency": min(max(settings.technical_scan_concurrency, 1), 20),
    }


@router.websocket("/stream")
async def technical_quote_stream(websocket: WebSocket) -> None:
    """Relay already-ingested Yahoo quotes to displayed scanner results."""
    raw_tickers = websocket.query_params.get("tickers", "")
    tickers = list(
        dict.fromkeys(ticker.strip().upper() for ticker in raw_tickers.split(",") if ticker.strip())
    )[:50]
    if not tickers:
        await websocket.close(code=1008, reason="At least one ticker is required")
        return

    await websocket.accept()
    stream = get_yahoo_live_stream()
    try:
        while True:
            await websocket.send_json({"type": "quotes", "quotes": stream.public_quotes(tickers)})
            await asyncio.sleep(0.5)
    except (WebSocketDisconnect, RuntimeError):
        return


@router.post("/scan", response_model=TechnicalScanResponse)
async def technical_scan(
    request: TechnicalScanRequest,
    db: AsyncSession = Depends(get_db),
):
    return await run_technical_scan(db, request)
