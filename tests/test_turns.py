import asyncio

import pytest

from tiresias.agent.turns import LatestTurn, acknowledge_and_analyze


@pytest.mark.asyncio
async def test_new_turn_cancels_old_result_and_repeated_commands_are_allowed():
    turns = LatestTurn()
    started = asyncio.Event()
    spoken = []

    async def slow():
        started.set()
        await asyncio.Event().wait()
        spoken.append('old result')

    old = turns.submit(slow())
    await started.wait()

    async def check():
        spoken.append('check this')

    await turns.submit(check())
    await turns.submit(check())
    assert old.cancelled()
    assert spoken == ['check this', 'check this']


@pytest.mark.asyncio
async def test_vision_starts_while_acknowledgement_is_playing():
    analysis_started = asyncio.Event()
    order = []

    async def acknowledge():
        await asyncio.wait_for(analysis_started.wait(), timeout=0.5)
        order.append('ack finished')

    async def analyze():
        analysis_started.set()
        order.append('vision started')
        return ['label result']

    result = await acknowledge_and_analyze(acknowledge(), analyze())
    assert order == ['vision started', 'ack finished']
    assert result == ['label result']


@pytest.mark.asyncio
async def test_stop_cancels_pending_analysis():
    turns = LatestTurn()
    started = asyncio.Event()

    async def analysis():
        started.set()
        await asyncio.Event().wait()

    task = turns.submit(analysis())
    await started.wait()
    turns.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert task.cancelled()
