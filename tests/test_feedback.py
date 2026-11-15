import asyncio

import pytest

from tiresias.agent.feedback import CallFeedback
from tiresias.agent.turns import QuietGate


@pytest.mark.asyncio
async def test_visible_states_follow_work_user_and_sdk_audio():
    async def say(text): pass
    status=CallFeedback(QuietGate(0),say)
    assert status.state=='connecting'
    status.connect()
    assert status.state=='listening'
    token=status.begin_work()
    assert status.state=='thinking'
    status.agent_speaking=True
    assert status.state=='speaking'
    status.user_speaking=True
    assert status.state=='listening'
    status.user_speaking=False
    status.agent_speaking=False
    newer=status.begin_work()
    status.finish_work(token)
    assert status.state=='thinking'
    status.finish_work(newer)
    assert status.state=='listening'
    status.close()
    assert status.state=='ended'


@pytest.mark.asyncio
async def test_status_cue_waits_for_silence_and_fast_answer_cancels_it():
    spoken=[]
    async def say(text): spoken.append(text)
    quiet=QuietGate(0)
    status=CallFeedback(quiet,say,cue_interval=0)
    status.connect()
    token=status.begin_work()
    quiet.set_speaking(True)
    status.queue_cue('Taking a look.',token=token,delay=0)
    await asyncio.sleep(0.02)
    assert spoken==[]
    await status.before_answer()
    quiet.set_speaking(False)
    await asyncio.sleep(0.02)
    assert spoken==[]
    status.close()


@pytest.mark.asyncio
async def test_started_short_cue_finishes_before_answer_and_old_work_cannot_speak():
    started,finish=asyncio.Event(),asyncio.Event()
    spoken=[]
    async def say(text):
        started.set()
        await finish.wait()
        spoken.append(text)
    status=CallFeedback(QuietGate(0),say,cue_interval=0)
    status.connect()
    token=status.begin_work()
    status.queue_cue('Got it.',token=token,delay=0)
    await started.wait()
    answer=asyncio.create_task(status.before_answer())
    await asyncio.sleep(0)
    assert not answer.done()
    finish.set()
    await answer
    assert spoken==['Got it.']
    status.queue_cue('Old cue.',token=token,delay=0.01)
    status.begin_work()
    await asyncio.sleep(0.03)
    assert spoken==['Got it.']
    status.close()


@pytest.mark.asyncio
async def test_cue_cooldown_and_disconnect_prevent_chatter():
    spoken=[]
    async def say(text): spoken.append(text)
    status=CallFeedback(QuietGate(0),say,cue_interval=4)
    status.connect()
    token=status.begin_work()
    await status.queue_cue("I'm listening.",token=token,delay=0)
    await status.queue_cue('Again.',token=token,delay=0)
    assert spoken==["I'm listening."]
    status.queue_cue('Too late.',token=token,delay=0.01)
    status.close()
    await asyncio.sleep(0.02)
    assert spoken==["I'm listening."]
