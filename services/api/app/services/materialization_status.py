"""Progress parsing for the resumable NSE semantic-materialization process."""

import re
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path

from app.core.config import REPO_ROOT

LOG_PATH = REPO_ROOT / "data" / "logs" / "nse-mainboard-materialization.log"
MAX_LOG_BYTES = 2 * 1024 * 1024
ACTIVE_HEARTBEAT = timedelta(minutes=30)

PROGRESS_RE = re.compile(
    r"^\[(?P<timestamp>[^\]]+)\] "
    r"\[(?P<stage>metadata|cards)\] "
    r"(?P<completed>\d+)/(?P<total>\d+) "
    r"(?P<ticker>\S+) "
    r"(?P<outcome>ok|failed): .* "
    r"\((?P<rate>[0-9.]+) companies/hour\)$"
)


@dataclass
class LogProgress:
    state: str = "unknown"
    stage: str | None = None
    run_completed: int = 0
    run_total: int = 0
    run_percent: float = 0.0
    rate_per_hour: float | None = None
    eta_seconds: int | None = None
    eta_at: str | None = None
    last_ticker: str | None = None
    last_outcome: str | None = None
    updated_at: str | None = None


def _read_log_tail(path: Path) -> str:
    if not path.exists():
        return ""
    with path.open("rb") as handle:
        size = handle.seek(0, 2)
        handle.seek(max(0, size - MAX_LOG_BYTES))
        payload = handle.read()
    return payload.decode("utf-8", errors="replace")


def parse_materialization_log(
    path: Path = LOG_PATH, *, now: datetime | None = None
) -> dict:
    """Return the latest run's progress and ETA from the persistent runner log."""

    text = _read_log_tail(path)
    if not text:
        return asdict(LogProgress())

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    setup_indexes = [index for index, line in enumerate(lines) if "[setup]" in line]
    if setup_indexes:
        lines = lines[setup_indexes[-1] :]

    latest: re.Match[str] | None = None
    for line in reversed(lines):
        match = PROGRESS_RE.match(line)
        if match:
            latest = match
            break

    if latest is None:
        return asdict(LogProgress())

    timestamp = datetime.strptime(latest.group("timestamp"), "%Y-%m-%d %H:%M:%S").astimezone()
    current_time = now or datetime.now().astimezone()
    completed = int(latest.group("completed"))
    total = int(latest.group("total"))
    rate = float(latest.group("rate"))
    remaining = max(0, total - completed)
    eta_seconds = round(remaining / rate * 3600) if rate > 0 else None
    eta_at = (
        (current_time + timedelta(seconds=eta_seconds)).isoformat()
        if eta_seconds is not None
        else None
    )
    cards_finished = any("[cards] stage complete:" in line for line in lines)
    recently_active = current_time - timestamp <= ACTIVE_HEARTBEAT
    state = "completed" if cards_finished else ("running" if recently_active else "idle")

    return asdict(
        LogProgress(
            state=state,
            stage=latest.group("stage"),
            run_completed=completed,
            run_total=total,
            run_percent=round((completed / total * 100) if total else 0.0, 1),
            rate_per_hour=round(rate, 1),
            eta_seconds=eta_seconds,
            eta_at=eta_at,
            last_ticker=latest.group("ticker"),
            last_outcome=latest.group("outcome"),
            updated_at=timestamp.isoformat(),
        )
    )
