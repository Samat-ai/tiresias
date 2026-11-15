import asyncio
import threading
from types import SimpleNamespace

import pytest

from tests.test_policy import frame
from tests.test_vision import client
from tiresias.agent.vision_stream import SpeechFirstParser


def test_delimiter_split_across_chunks_never_speaks_metadata():
    parser=SpeechFirstParser(frame_id='frame-1')
    assert parser.feed('I see two Pepsi cans. |') is None
    assert parser.feed('|') is None
    reply=parser.feed('| {"needs_view":')
    assert reply.text=='I see two Pepsi cans.'
    assert reply.frame_id=='frame-1'
    assert parser.feed('false}') is None
    assert parser.finish().text==reply.text


@pytest.mark.parametrize('text',['{"text":"metadata only"}','```json\n{}','x'*401,'||| {}',
    'I see two cans. {"needs_view":false}', 'I see two cans. | {"needs_view":false}',
    'I see two cans. |', 'There are'])
def test_invalid_or_unbounded_speech_is_rejected(text):
    parser=SpeechFirstParser(frame_id=None)
    with pytest.raises(ValueError):
        parser.feed(text)
        parser.finish()


def test_plain_bounded_answer_without_delimiter_can_finish():
    parser=SpeechFirstParser(frame_id=None)
    assert parser.feed('Please point your camera at the label.') is None
    assert parser.finish().text=='Please point your camera at the label.'


@pytest.mark.asyncio
async def test_speech_is_yielded_before_metadata_finishes_and_tail_failure_is_not_repeated():
    vision=client()
    finish=threading.Event()
    def chunks(**kwargs):
        yield SimpleNamespace(text='I see two cans. |||')
        assert finish.wait(2)
        raise RuntimeError('metadata transport failed')
    vision._client.models.generate_content_stream=chunks
    stream=vision.stream_answer_question(frame(),'How many cans?',[])
    try:
        reply=await asyncio.wait_for(anext(stream),1)
        assert reply.text=='I see two cans.'
        finish.set()
        assert [reply async for reply in stream]==[]
    finally:
        finish.set()
        await stream.aclose()


@pytest.mark.asyncio
async def test_cancelled_stream_cannot_deliver_late_speech():
    vision=client()
    started,release,closed=threading.Event(),threading.Event(),threading.Event()
    def chunks(**kwargs):
        try:
            started.set()
            assert release.wait(2)
            yield SimpleNamespace(text='Late answer. |||{}')
        finally:
            closed.set()
    vision._client.models.generate_content_stream=chunks
    stream=vision.stream_answer_question(frame(),'How many cans?',[])
    waiting=asyncio.create_task(anext(stream))
    try:
        assert await asyncio.to_thread(started.wait,1)
        waiting.cancel()
        with pytest.raises(asyncio.CancelledError): await waiting
        release.set()
        assert await asyncio.to_thread(closed.wait,1)
    finally:
        release.set()
        await stream.aclose()


@pytest.mark.asyncio
async def test_truncated_provider_output_without_delimiter_is_not_spoken():
    vision=client()
    vision._client.models.generate_content_stream=lambda **kw:iter([
        SimpleNamespace(text='There are two cans.',candidates=[SimpleNamespace(finish_reason='MAX_TOKENS')])])
    with pytest.raises(ValueError):
        assert [reply async for reply in vision.stream_answer_question(frame(),'How many cans?',[])]==[]
