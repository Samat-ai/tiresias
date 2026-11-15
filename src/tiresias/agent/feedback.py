"""Per-call visible state and sparse, cancellable spoken status cues."""
from __future__ import annotations

import asyncio
import time

from tiresias.agent.turns import QuietGate


class CallFeedback:
    def __init__(self, quiet: QuietGate, say, *, cue_interval: float = 4) -> None:
        self.quiet, self.say = quiet, say
        self.cue_interval = cue_interval
        self.user_speaking = self.agent_speaking = False
        self.connected = self.closed = self.busy = False
        self.generation = 0
        self._cue: asyncio.Task | None = None
        self._cue_started = False
        self._last_cue = float('-inf')

    @property
    def state(self) -> str:
        if self.closed:
            return 'ended'
        if not self.connected:
            return 'connecting'
        if self.user_speaking:
            return 'listening'
        if self.agent_speaking:
            return 'speaking'
        return 'thinking' if self.busy else 'listening'

    def connect(self) -> None:
        self.connected = True

    def _cancel_cue(self) -> None:
        if self._cue and not self._cue.done():
            self._cue.cancel()
        self._cue = None
        self._cue_started = False

    def begin_work(self) -> int:
        self._cancel_cue()
        self.generation += 1
        self.busy = True
        return self.generation

    def finish_work(self, token: int) -> None:
        if token == self.generation:
            self.busy = False
            self._cancel_cue()

    def queue_cue(self, text: str, *, token: int, delay: float = 1.5, force: bool = False) -> asyncio.Task:
        self._cancel_cue()

        async def deliver():
            await asyncio.sleep(delay)
            await self.quiet.wait()
            if (self.closed or not self.connected or token != self.generation
                    or (not force and time.monotonic() - self._last_cue < self.cue_interval)):
                return
            self._last_cue = time.monotonic()
            self._cue_started = True
            await self.say(text)

        self._cue = asyncio.create_task(deliver())
        return self._cue

    async def before_answer(self) -> None:
        cue = self._cue
        if not cue or cue.done():
            return
        if self._cue_started:
            # A short cue already on the wire must finish before the answer.
            await cue
        else:
            self._cancel_cue()

    def close(self) -> None:
        self.closed = True
        self.busy = False
        self._cancel_cue()
