import asyncio
import uuid

import pytest

from tiresias.telemetry import TelemetrySink
from tiresias.db import connect, migrate, reset_test_data, test_database_url as database_url


@pytest.mark.asyncio
async def test_real_stage_events_are_persisted_and_queryable():
    migrate()
    with connect() as conn:
        reset_test_data(conn)
    sink=TelemetrySink(database_url())
    sink.start()
    sink.emit(stage='vision',duration_ms=123,outcome='ok',session_id=str(uuid.uuid4()),source='REPLAY')
    await asyncio.wait_for(sink.flush(),3)
    await sink.close()
    with connect() as conn:
        row=conn.execute("SELECT * FROM stage_events WHERE stage='vision'").fetchone()
        assert row['duration_ms']==123
        assert row['outcome']=='ok'


@pytest.mark.asyncio
async def test_slow_or_broken_telemetry_does_not_block_caller(monkeypatch):
    sink=TelemetrySink('unreachable',max_queue=2)
    def failed(event):
        raise OSError('database offline')
    monkeypatch.setattr(sink,'_write',failed)
    sink.start()
    sink.emit(stage='vision',duration_ms=1,outcome='ok',source='REPLAY')
    await asyncio.wait_for(sink.flush(),0.5)
    assert sink.failed==1
    await sink.close()


def test_telemetry_queue_is_bounded():
    sink=TelemetrySink('unused',max_queue=2)
    for _ in range(5):
        sink.emit(stage='vision',duration_ms=1,outcome='ok',source='REPLAY')
    assert sink.dropped==3
