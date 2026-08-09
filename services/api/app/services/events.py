"""In-memory search progress bus for Server-Sent Events (single-process prototype)."""

import asyncio
from collections import defaultdict
from collections.abc import AsyncIterator
from uuid import UUID

_TERMINAL_STAGES = {"completed", "failed"}


class SearchEventBus:
    def __init__(self):
        self._history: dict[UUID, list[dict]] = defaultdict(list)
        self._queues: dict[UUID, list[asyncio.Queue]] = defaultdict(list)

    def publish(self, search_id: UUID, stage: str, **payload) -> None:
        event = {"stage": stage, **payload}
        self._history[search_id].append(event)
        for queue in list(self._queues.get(search_id, [])):
            queue.put_nowait(event)

    def is_finished(self, search_id: UUID) -> bool:
        return any(e["stage"] in _TERMINAL_STAGES for e in self._history.get(search_id, []))

    async def subscribe(self, search_id: UUID) -> AsyncIterator[dict]:
        """Replay history, then stream live events until a terminal stage."""
        for event in list(self._history.get(search_id, [])):
            yield event
            if event["stage"] in _TERMINAL_STAGES:
                return
        queue: asyncio.Queue = asyncio.Queue()
        self._queues[search_id].append(queue)
        try:
            while True:
                event = await queue.get()
                yield event
                if event["stage"] in _TERMINAL_STAGES:
                    return
        finally:
            self._queues[search_id].remove(queue)

    def clear(self, search_id: UUID) -> None:
        self._history.pop(search_id, None)


event_bus = SearchEventBus()
