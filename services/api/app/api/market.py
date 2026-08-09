from fastapi import APIRouter, Query

from app.schemas.market import BlockDealsOut, MarketPulseOut
from app.services.block_deals import get_block_deals
from app.services.market_pulse import get_market_pulse

router = APIRouter()


@router.get("/pulse", response_model=MarketPulseOut)
async def market_pulse():
    return await get_market_pulse()


@router.get("/block-deals", response_model=BlockDealsOut)
async def block_deals(days: int = Query(default=30, ge=1, le=365)):
    return await get_block_deals(days)
