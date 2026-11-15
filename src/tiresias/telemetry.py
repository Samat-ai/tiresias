from __future__ import annotations

import asyncio
import logging
from uuid import uuid4

from tiresias.db import connect
from tiresias.outbox import record_stage_event

logger=logging.getLogger(__name__)


class TelemetrySink:
    def __init__(self, database_url: str, max_queue: int=128):
        self.database_url=database_url
        self.queue=asyncio.Queue(maxsize=max_queue)
        self.task=None
        self.dropped=0
        self.failed=0
        self.closed=False

    def start(self):
        if self.database_url and self.task is None:
            self.task=asyncio.create_task(self._run())

    def emit(self, **event):
        if not self.database_url or self.closed:
            return
        try:
            self.queue.put_nowait({'event_id':str(uuid4()),**event})
        except asyncio.QueueFull:
            self.dropped+=1

    def _write(self,event):
        with connect(self.database_url,connect_timeout=2) as conn:
            conn.execute("SET LOCAL statement_timeout='2000ms'")
            record_stage_event(conn,**event)

    async def _run(self):
        while True:
            event=await self.queue.get()
            try:
                await asyncio.to_thread(self._write,event)
            except Exception as error:
                self.failed+=1
                logger.warning('Telemetry write failed: %s',type(error).__name__)
            finally:
                self.queue.task_done()

    async def flush(self):
        await self.queue.join()

    async def close(self):
        self.closed=True
        if self.task:
            try:
                await asyncio.wait_for(self.flush(),2.5)
            except TimeoutError:
                logger.warning('Telemetry shutdown exceeded drain budget')
            self.task.cancel()
            await asyncio.gather(self.task,return_exceptions=True)
