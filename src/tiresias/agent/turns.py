"""Keep a single active caller turn; start vision without waiting for speech."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine
from typing import Any

logger = logging.getLogger(__name__)


class QuietGate:
    """Do not start a new spoken sentence while the caller is speaking."""

    def __init__(self, quiet_period: float = 0.2) -> None:
        self.quiet_period = quiet_period
        self._quiet = asyncio.Event()
        self._quiet.set()

    def set_speaking(self, speaking: bool) -> None:
        if speaking:
            self._quiet.clear()
        else:
            self._quiet.set()

    async def wait(self) -> None:
        while True:
            await self._quiet.wait()
            await asyncio.sleep(self.quiet_period)
            if self._quiet.is_set():
                return


class LatestTurn:
    def __init__(self) -> None:
        self.task: asyncio.Task | None = None

    def cancel(self) -> None:
        if self.task is not None and not self.task.done():
            self.task.cancel()

    def submit(self, work: Coroutine[Any, Any, Any]) -> asyncio.Task:
        self.cancel()
        self.task = asyncio.create_task(work)
        self.task.add_done_callback(self._finished)
        return self.task

    @staticmethod
    def _finished(task: asyncio.Task) -> None:
        if not task.cancelled() and (error := task.exception()) is not None:
            logger.error("caller turn failed", exc_info=(type(error), error, error.__traceback__))


async def acknowledge_and_analyze(acknowledgement, analysis):
    _, result = await asyncio.gather(acknowledgement, analysis)
    return result
