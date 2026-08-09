"""Bootstrap the database: run migrations and load the 300-company universe.

Usage:  services/api/.venv/bin/python scripts/bootstrap_db.py
"""

import asyncio
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
API_DIR = REPO_ROOT / "services" / "api"
sys.path.insert(0, str(API_DIR))


async def main() -> None:
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"], cwd=API_DIR, check=True
    )
    from app.core.db import get_session_factory
    from app.services.ingestion import ensure_universe

    async with get_session_factory()() as db:
        count = await ensure_universe(db)
    print(f"Universe loaded: {count} companies")


if __name__ == "__main__":
    asyncio.run(main())
