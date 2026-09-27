"""Thread-safe coordination primitives for queued REPL follow-ups."""

from __future__ import annotations

import asyncio
from concurrent.futures import Future
from dataclasses import dataclass
from queue import Empty, Queue
from threading import Lock
from typing import Any


class FollowUpQueue:
    """FIFO queue for user messages entered while an agent turn is running."""

    def __init__(self) -> None:
        self._items: Queue[str] = Queue()

    def put(self, message: str) -> None:
        self._items.put(message)

    def pop(self) -> str | None:
        try:
            return self._items.get_nowait()
        except Empty:
            return None

    def size(self) -> int:
        return self._items.qsize()


@dataclass
class PromptRequest:
    """A worker-thread request for exclusive terminal input."""

    message: Any
    result: Future[str]


class PromptBroker:
    """Bridge synchronous tool callbacks to the REPL's asyncio input loop."""

    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        self._requests: asyncio.Queue[PromptRequest] = asyncio.Queue()
        self._pending: set[Future[str]] = set()
        self._pending_lock = Lock()

    def ask_from_worker(self, message: Any) -> str:
        """Block a worker callback until the main REPL supplies an answer."""
        result: Future[str] = Future()
        with self._pending_lock:
            self._pending.add(result)
        request = PromptRequest(message=message, result=result)
        self._loop.call_soon_threadsafe(self._requests.put_nowait, request)
        try:
            return result.result()
        finally:
            with self._pending_lock:
                self._pending.discard(result)

    async def next_request(self) -> PromptRequest:
        return await self._requests.get()

    def close(self) -> None:
        """Release worker callbacks if the REPL input loop exits unexpectedly."""
        with self._pending_lock:
            pending = list(self._pending)
        for result in pending:
            if not result.done():
                result.set_result("")
