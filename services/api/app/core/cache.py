"""Disk-backed JSON cache for raw upstream responses (SEC JSON, market snapshots, query plans).

Every cached object is wrapped with provenance metadata per spec §16:
source, retrieved_at, data_version, and optionally model_name / prompt_version.
Structured facts extracted from these responses live in Postgres tables.
"""

import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DATA_VERSION = "1"


def cache_key(*parts: str) -> str:
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


class FileCache:
    def __init__(self, root: Path, namespace: str):
        self.dir = root / namespace
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        return self.dir / f"{key}.json"

    def get(self, key: str, ttl_seconds: float | None) -> Any | None:
        """Return the cached payload, or None if absent/expired. ttl_seconds=None means no expiry."""
        path = self._path(key)
        if not path.exists():
            return None
        try:
            wrapper = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return None
        if (
            ttl_seconds is not None
            and time.time() - wrapper.get("cached_at_epoch", 0) > ttl_seconds
        ):
            return None
        return wrapper.get("payload")

    def get_wrapper(self, key: str, ttl_seconds: float | None) -> dict | None:
        path = self._path(key)
        if not path.exists():
            return None
        try:
            wrapper = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return None
        if (
            ttl_seconds is not None
            and time.time() - wrapper.get("cached_at_epoch", 0) > ttl_seconds
        ):
            return None
        return wrapper

    def put(
        self,
        key: str,
        payload: Any,
        *,
        source: str,
        model_name: str | None = None,
        prompt_version: str | None = None,
    ) -> None:
        wrapper = {
            "source": source,
            "retrieved_at": datetime.now(UTC).isoformat(),
            "cached_at_epoch": time.time(),
            "data_version": DATA_VERSION,
            "payload": payload,
        }
        if model_name:
            wrapper["model_name"] = model_name
        if prompt_version:
            wrapper["prompt_version"] = prompt_version
        self._path(key).write_text(json.dumps(wrapper, default=str))

    def invalidate(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)
