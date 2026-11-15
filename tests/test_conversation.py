import asyncio
from types import SimpleNamespace

import pytest

from tiresias.agent.intent import IntentClassifier
from tiresias.agent.turns import QuietGate
from tiresias.agent.vision import VisionClient
from tests.test_policy import frame


def test_count_question_cannot_trigger_human_sharing(monkeypatch):
    classifier = IntentClassifier(api_key='configured')
    monkeypatch.setattr(classifier, '_classify_gemini', lambda *args: pytest.fail('unneeded intent request'))
    intent = classifier.route('How many Pepsi cans can you see?', None)
    assert intent.kind.value == 'CONVERSATION'


@pytest.mark.parametrize('text', ['yes', 'okay', 'hello', 'thanks', 'да', 'привет'])
def test_social_acknowledgement_never_becomes_unsupported(text):
    assert IntentClassifier(api_key='').route(text, None).kind.value == 'SOCIAL'


@pytest.mark.parametrize('text,kind', [('Stop.', 'STOP'), ('Repeat!', 'REPEAT'), ('Slow down.', 'SLOWER')])
def test_spoken_controls_accept_stt_punctuation(text, kind):
    assert IntentClassifier(api_key='').route(text, None).kind.value == kind


def test_russian_question_is_not_a_product_name():
    from tests.test_policy import waiting_task
    assert IntentClassifier(api_key='').route('Что это?', waiting_task()).kind.value == 'CONVERSATION'


def test_location_follow_up_is_not_a_new_product_name():
    from tests.test_policy import waiting_task
    assert IntentClassifier(api_key='').route('Where are they?', waiting_task()).kind.value == 'CONVERSATION'


@pytest.mark.asyncio
async def test_response_waits_until_caller_stops_speaking():
    gate = QuietGate(quiet_period=0)
    gate.set_speaking(True)
    waiting = asyncio.create_task(gate.wait())
    await asyncio.sleep(0)
    assert not waiting.done()
    gate.set_speaking(False)
    await asyncio.wait_for(waiting, 0.5)


@pytest.mark.asyncio
async def test_stuck_speech_detector_cannot_hold_an_answer_indefinitely():
    gate = QuietGate(quiet_period=0)
    gate.set_speaking(True)
    assert await asyncio.wait_for(gate.wait(max_wait=0.03), 0.2) is False
    # Releasing one answer must not manufacture silence for status cues.
    waiting = asyncio.create_task(gate.wait())
    await asyncio.sleep(0)
    assert not waiting.done()
    gate.set_speaking(False)
    assert await asyncio.wait_for(waiting, 0.2) is True


@pytest.mark.asyncio
async def test_bounded_speech_gate_still_honors_real_silence():
    gate = QuietGate(quiet_period=0)
    gate.set_speaking(True)
    waiting = asyncio.create_task(gate.wait(max_wait=0.2))
    await asyncio.sleep(0.01)
    assert not waiting.done()
    gate.set_speaking(False)
    assert await waiting is True


def test_visual_question_uses_current_image_and_recent_question_in_one_request():
    calls = []
    vision = VisionClient.__new__(VisionClient)
    vision.model = 'gemini-3.5-flash-lite'
    vision.timeout_seconds = 12

    def generate(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(text='{"text":"I can see one Pepsi can.","needs_view":false}')

    vision._client = SimpleNamespace(models=SimpleNamespace(generate_content=generate))
    reply = vision.answer_question(frame(), 'How many Pepsi cans can you see?', [])
    assert reply.text == 'I can see one Pepsi can.'
    assert reply.frame_id == frame().frame_id
    assert len(calls) == 1
    assert 'How many Pepsi cans' in calls[0]['contents'][1]
