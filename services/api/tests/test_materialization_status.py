from datetime import datetime
from pathlib import Path

from app.services.materialization_status import parse_materialization_log


def test_parse_materialization_log_uses_latest_run(tmp_path: Path):
    log = tmp_path / "materialization.log"
    log.write_text(
        "\n".join(
            [
                "[2026-07-23 10:00:00] [setup] NSE main-board universe contains 2386 companies",
                "[2026-07-23 10:00:01] [metadata] 100/2186 OLD ok: reports_added=8, "
                "reports_available=8 (7000.0 companies/hour)",
                "[2026-07-23 11:00:00] [setup] NSE main-board universe contains 2386 companies",
                "[2026-07-23 11:01:00] [cards] 50/2000 NEWCO ok: cards=22 "
                "(30.0 companies/hour)",
            ]
        )
    )

    result = parse_materialization_log(
        log, now=datetime.fromisoformat("2026-07-23T11:01:30+05:30")
    )

    assert result["state"] == "running"
    assert result["stage"] == "cards"
    assert result["run_completed"] == 50
    assert result["run_total"] == 2000
    assert result["run_percent"] == 2.5
    assert result["last_ticker"] == "NEWCO"
    assert result["eta_seconds"] == 234000


def test_parse_materialization_log_marks_completed_cards(tmp_path: Path):
    log = tmp_path / "materialization.log"
    log.write_text(
        "\n".join(
            [
                "[2026-07-23 11:00:00] [setup] NSE main-board universe contains 2386 companies",
                "[2026-07-23 11:01:00] [cards] 2/2 DONE ok: cards=20 "
                "(30.0 companies/hour)",
                "[2026-07-23 11:01:01] [cards] stage complete: 2 succeeded, 0 failed",
            ]
        )
    )

    result = parse_materialization_log(
        log, now=datetime.fromisoformat("2026-07-23T11:01:30+05:30")
    )

    assert result["state"] == "completed"
    assert result["run_percent"] == 100.0
