from datetime import date

from app.services import block_deals


class FakeNseClient:
    def __init__(self, historical: list[dict] | None = None, *, fail_history: bool = False):
        self.historical = historical or []
        self.fail_history = fail_history
        self.requested_ranges = []

    async def get_historical_deals(self, option_type, from_date, to_date):
        self.requested_ranges.append((option_type, from_date, to_date))
        if self.fail_history:
            raise RuntimeError("history unavailable")
        return self.historical

    async def get_large_deals_snapshot(self):
        return {
            "BLOCK_DEALS_DATA": [
                {
                    "date": "21-Jul-2026",
                    "symbol": "WIPRO",
                    "name": "Wipro Limited",
                    "clientName": "EXAMPLE FUND LIMITED",
                    "buySell": "BUY",
                    "qty": "1000000",
                    "watp": "250.50",
                }
            ]
        }


async def test_block_deals_are_normalized_valued_and_sorted(monkeypatch):
    client = FakeNseClient(
        [
            {
                "BD_DT_DATE": "20-JUL-2026",
                "BD_SYMBOL": "AAA",
                "BD_SCRIP_NAME": "Alpha Ltd",
                "BD_CLIENT_NAME": "SELLER FUND",
                "BD_BUY_SELL": "SELL",
                "BD_QTY_TRD": 100,
                "BD_TP_WATP": 200,
            },
            {
                "BD_DT_DATE": "21-JUL-2026",
                "BD_SYMBOL": "BBB",
                "BD_SCRIP_NAME": "Beta Ltd",
                "BD_CLIENT_NAME": "BUYER FUND",
                "BD_BUY_SELL": "BUY",
                "BD_QTY_TRD": 250,
                "BD_TP_WATP": 400,
            },
        ]
    )
    monkeypatch.setattr(block_deals, "get_nse_client", lambda: client)

    result = await block_deals.get_block_deals(30, today=date(2026, 7, 22))

    assert client.requested_ranges[0] == (
        "block_deals",
        date(2026, 6, 23),
        date(2026, 6, 29),
    )
    assert client.requested_ranges[-1] == (
        "block_deals",
        date(2026, 7, 21),
        date(2026, 7, 22),
    )
    assert [deal["symbol"] for deal in result["deals"]] == ["BBB", "AAA"]
    assert result["deals"][0]["trade_value_inr"] == 100_000
    assert result["used_latest_snapshot"] is False


async def test_block_deals_fall_back_to_latest_snapshot(monkeypatch):
    client = FakeNseClient(fail_history=True)
    monkeypatch.setattr(block_deals, "get_nse_client", lambda: client)

    result = await block_deals.get_block_deals(7, today=date(2026, 7, 22))

    assert result["used_latest_snapshot"] is True
    assert result["deals"][0]["symbol"] == "WIPRO"
    assert result["deals"][0]["trade_value_inr"] == 250_500_000
    assert "only the latest snapshot" in result["limitation"]
