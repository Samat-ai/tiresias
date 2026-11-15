"""Exercise STT -> controller -> vision -> spoken output without provider sockets."""
import asyncio
import time
import threading
from types import SimpleNamespace

import pytest

from tiresias.agent import main as runtime
from tiresias.agent.intent import IntentClassifier
from tiresias.agent.media import FrameBuffer
from tiresias.contracts import Observation, Quality
from tests.test_frames import incoming


class FakeRoom:
    metadata = 'chert_bridge_ready'
    name = 'test-room'
    remote_participants = {}

    def __init__(self):
        self.handlers={}

    def on(self, event, handler):
        self.handlers[event]=handler


class FakeSession:
    def __init__(self, **kwargs):
        self.handlers = {}
        self.messages = asyncio.Queue()
        self.tts = kwargs['tts']
        self.interruptions = 0

    def on(self, name):
        def register(handler):
            self.handlers[name] = handler
        return register

    async def start(self, **kwargs):
        self.agent = kwargs['agent']
        self.room = kwargs['room']

    async def say(self, text, **kwargs):
        self.messages.put_nowait(text)

    async def interrupt(self, **kwargs):
        self.interruptions += 1

    async def transcript(self, text):
        self.handlers['user_input_transcribed'](SimpleNamespace(transcript=text, is_final=True))
        with pytest.raises(runtime.StopResponse):
            await self.agent.on_user_turn_completed(None, SimpleNamespace(text_content=text))


async def setup_call(monkeypatch, vision, *, caller_links=False):
    session = FakeSession(tts=SimpleNamespace(update_options=lambda **kwargs: None))
    frames = FrameBuffer('test')
    monkeypatch.setattr(runtime, 'AgentSession', lambda **kwargs: session)
    monkeypatch.setattr(runtime, 'FrameBuffer', lambda **kwargs: frames)
    monkeypatch.setattr(runtime, '_get_intent_classifier', lambda: IntentClassifier(api_key=''))
    monkeypatch.setattr(runtime, '_get_vision', lambda: vision)
    monkeypatch.setattr(runtime.settings, 'elevenlabs_api_key', 'test')
    monkeypatch.setattr(runtime.settings, 'database_url', 'configured' if caller_links else '')
    monkeypatch.setattr(runtime.settings, 'caller_link_secret', 'test-only-caller-link-secret-at-least-32-characters' if caller_links else '')

    async def nothing(*args, **kwargs):
        pass

    if caller_links:
        monkeypatch.setattr(runtime,'TelemetrySink',lambda url:SimpleNamespace(start=lambda:None,emit=lambda **kw:None,close=nothing))
        monkeypatch.setattr(runtime,'_read_voice_profile',lambda uid: runtime.VoicePreferences())

    monkeypatch.setattr(runtime, '_publish_status_video', nothing)
    await runtime.entrypoint(SimpleNamespace(room=FakeRoom(), connect=nothing))
    # Allow the bridge-ready greeting task to finish.
    assert 'Tiresias' in await asyncio.wait_for(session.messages.get(), 1)
    return session, frames


def push(frames):
    frames.push(incoming(frames, received_monotonic=time.monotonic()))


@pytest.mark.asyncio
async def test_same_spoken_check_works_twice_through_stt(monkeypatch):
    def analyze(frame, target):
        return Observation(frame_id=frame.frame_id, visible_text=['LEMON'], quality=Quality.READABLE)

    session, frames = await setup_call(monkeypatch, SimpleNamespace(analyze_frame=analyze))
    for _ in range(2):
        push(frames)
        await session.transcript('check this')
        await asyncio.wait_for(session.messages.get(), 1)  # acknowledgement
        result = await asyncio.wait_for(session.messages.get(), 1)
        assert result == 'The label says LEMON.'
    assert session.interruptions == 2


@pytest.mark.asyncio
async def test_api_failure_does_not_blame_the_camera(monkeypatch):
    def analyze(frame, target):
        raise RuntimeError('provider unavailable')

    session, frames = await setup_call(monkeypatch, SimpleNamespace(analyze_frame=analyze))
    push(frames)
    await session.transcript('check this')
    await asyncio.wait_for(session.messages.get(), 1)
    result = await asyncio.wait_for(session.messages.get(), 1)
    assert 'service' in result
    assert 'steady' not in result and 'blurry' not in result


@pytest.mark.asyncio
async def test_completed_user_turn_is_the_single_command_source():
    called = []
    agent = runtime.TiresiasAgent(called.append)
    with pytest.raises(runtime.StopResponse):
        await agent.on_user_turn_completed(None, SimpleNamespace(content=['check this']))
    assert called == ['check this']


@pytest.mark.asyncio
async def test_raw_final_transcript_does_not_start_response(monkeypatch):
    session, frames = await setup_call(monkeypatch, None)
    session.handlers['user_input_transcribed'](SimpleNamespace(transcript='check this', is_final=True))
    await asyncio.sleep(0)
    assert session.messages.empty()
    assert session.interruptions == 0


@pytest.mark.asyncio
async def test_yes_during_analysis_does_not_cancel_the_pending_answer(monkeypatch):
    release = threading.Event()

    def analyze(frame, target):
        assert release.wait(2)
        return Observation(frame_id=frame.frame_id, visible_text=['PEPSI'], quality=Quality.READABLE)

    session, frames = await setup_call(monkeypatch, SimpleNamespace(analyze_frame=analyze))
    push(frames)
    await session.transcript('check this')
    await asyncio.wait_for(session.messages.get(), 1)
    try:
        await session.transcript('Yes.')
        assert session.interruptions == 1
    finally:
        release.set()
    assert 'PEPSI' in await asyncio.wait_for(session.messages.get(), 1)


@pytest.mark.asyncio
async def test_conversational_answer_waits_for_caller_silence(monkeypatch):
    from tiresias.contracts import GroundedReply
    called = threading.Event()

    def answer(frame, question, history):
        assert question == 'How many Pepsi cans can you see?'
        called.set()
        return GroundedReply(text='I see two Pepsi cans.', frame_id=frame.frame_id)

    session, frames = await setup_call(monkeypatch, SimpleNamespace(answer_question=answer))
    push(frames)
    session.handlers['user_state_changed'](SimpleNamespace(new_state='speaking'))
    await session.transcript('How many Pepsi cans can you see?')
    assert await asyncio.to_thread(called.wait, 1)
    assert session.messages.empty()
    session.handlers['user_state_changed'](SimpleNamespace(new_state='listening'))
    assert await asyncio.wait_for(session.messages.get(), 1) == 'I see two Pepsi cans.'


@pytest.mark.asyncio
async def test_voice_change_applies_without_calling_vision(monkeypatch):
    session, frames=await setup_call(monkeypatch,None)
    updates=[]
    session.tts.update_options=lambda **kwargs: updates.append(kwargs)
    await session.transcript('Use a female voice.')
    result=await asyncio.wait_for(session.messages.get(),1)
    assert 'Sarah' in result
    assert updates[-1]['voice_id']=='EXAVITQu4vr4xnSDxMaL'


@pytest.mark.asyncio
async def test_profile_code_loads_saved_voice_preferences(monkeypatch):
    from tiresias.preferences import VoicePreferences
    session, frames=await setup_call(monkeypatch,None)
    monkeypatch.setattr(runtime,'_load_voice_profile',lambda code:{
        'user_id':'profile-owner','preferences':VoicePreferences(voice_id='EXAVITQu4vr4xnSDxMaL',tone='friendly',speed=0.8)})
    updates=[]
    session.tts.update_options=lambda **kwargs: updates.append(kwargs)
    await session.transcript('Use profile 1234 5678.')
    result=await asyncio.wait_for(session.messages.get(),1)
    assert 'loaded' in result.lower()
    assert updates[-1]['voice_settings'].speed==0.8


@pytest.mark.asyncio
async def test_profile_entry_across_turns_does_not_search_the_camera(monkeypatch):
    from tiresias.preferences import VoicePreferences
    session, frames=await setup_call(monkeypatch,None)
    loaded=[]
    def load(code):
        loaded.append(code)
        return {'user_id':'profile-owner','preferences':VoicePreferences()}
    monkeypatch.setattr(runtime,'_load_voice_profile',load)
    for text in ['Use profile.','Uh, 354...','zero two three seven four']:
        await session.transcript(text)
        response=await asyncio.wait_for(session.messages.get(),1)
        assert 'looking for' not in response.lower()
    assert loaded == ['35402374']
    assert 'loaded' in response.lower()


@pytest.mark.asyncio
async def test_completed_message_retained_during_speech_is_dispatched_once(monkeypatch):
    session, frames=await setup_call(monkeypatch,None)
    message=SimpleNamespace(id='completed-profile-turn',role='user',text_content='Use a female voice.')
    session.handlers['conversation_item_added'](SimpleNamespace(item=message))
    assert 'Sarah' in await asyncio.wait_for(session.messages.get(),1)
    with pytest.raises(runtime.StopResponse):
        await session.agent.on_user_turn_completed(None,message)
    await asyncio.sleep(0.05)
    assert session.messages.empty()
    assert session.interruptions == 1


@pytest.mark.asyncio
async def test_verified_caller_settings_load_on_two_calls_without_spoken_code(monkeypatch):
    from tiresias.preferences import VoicePreferences
    caller=SimpleNamespace(call_id='80498626-b341-469d-9375-8b941a92663d',handle='+12145550100')
    resolutions=[]
    def resolve(call_id):
        resolutions.append(call_id)
        return caller
    monkeypatch.setattr(runtime,'_resolve_chert_caller',resolve)
    monkeypatch.setattr(runtime,'_sync_caller_voice',lambda caller,**kw: {
        'linked':{'user_id':'profile-owner','preferences':VoicePreferences(voice_id='EXAVITQu4vr4xnSDxMaL',tone='friendly',speed=0.8)},
        'challenge':None})
    for _ in range(2):
        session,frames=await setup_call(monkeypatch,None,caller_links=True)
        applied=asyncio.Event()
        updates=[]
        def update(**kw):
            updates.append(kw)
            applied.set()
        session.tts.update_options=update
        session.room.handlers['participant_connected'](SimpleNamespace(identity='chert-bridge-'+caller.call_id))
        await asyncio.wait_for(applied.wait(),1)
        assert updates[0]['voice_id']=='EXAVITQu4vr4xnSDxMaL'
        assert session.messages.empty()
        session.room.handlers['disconnected']()
    assert resolutions == [caller.call_id,caller.call_id]


@pytest.mark.asyncio
async def test_setup_code_is_spoken_only_for_a_trusted_inbound_caller(monkeypatch):
    caller=SimpleNamespace(call_id='80498626-b341-469d-9375-8b941a92663d',handle='+12145550100')
    monkeypatch.setattr(runtime,'_resolve_chert_caller',lambda call_id:caller)
    monkeypatch.setattr(runtime,'_sync_caller_voice',lambda caller,**kw:{'linked':None,'challenge':{'code':'2468'}})
    session,frames=await setup_call(monkeypatch,None,caller_links=True)
    session.room.handlers['participant_connected'](SimpleNamespace(identity='chert-bridge-smoke-forged'))
    await asyncio.sleep(0.05)
    assert session.messages.empty()
    session.room.handlers['participant_connected'](SimpleNamespace(identity='chert-bridge-'+caller.call_id))
    message=await asyncio.wait_for(session.messages.get(),1)
    assert '2, 4, 6, 8' in message and 'website' in message
    session.room.handlers['disconnected']()


@pytest.mark.asyncio
async def test_setup_digits_are_excluded_from_logs_and_vision_history(monkeypatch,caplog):
    from tiresias.contracts import GroundedReply
    import logging
    caplog.set_level(logging.INFO,logger='tiresias.agent')
    history=[]
    def answer(frame,question,recent):
        history.extend(recent)
        return GroundedReply(text='I see a label.',frame_id=frame.frame_id)
    caller=SimpleNamespace(call_id='80498626-b341-469d-9375-8b941a92663d',handle='+12145550100')
    monkeypatch.setattr(runtime,'_resolve_chert_caller',lambda call_id:caller)
    monkeypatch.setattr(runtime,'_sync_caller_voice',lambda caller,**kw:{'linked':None,'challenge':{'code':'2468'}})
    session,frames=await setup_call(monkeypatch,SimpleNamespace(answer_question=answer),caller_links=True)
    session.room.handlers['participant_connected'](SimpleNamespace(identity='chert-bridge-'+caller.call_id))
    assert '2, 4, 6, 8' in await asyncio.wait_for(session.messages.get(),1)
    push(frames)
    await session.transcript('How many Pepsi cans can you see?')
    await asyncio.wait_for(session.messages.get(),1)
    session.room.handlers['disconnected']()
    leaks=[]
    if '2, 4, 6, 8' in caplog.text: leaks.append('logs')
    if '2, 4, 6, 8' in str(history): leaks.append('vision history')
    assert leaks == []


@pytest.mark.asyncio
async def test_inflight_refresh_cannot_restore_preferences_after_unlink(monkeypatch):
    from tiresias.preferences import VoicePreferences
    caller=SimpleNamespace(call_id='80498626-b341-469d-9375-8b941a92663d',handle='+12145550100')
    preferences=VoicePreferences(voice_id='EXAVITQu4vr4xnSDxMaL',tone='friendly')
    state={'linked':True}
    monkeypatch.setattr(runtime,'_resolve_chert_caller',lambda call_id:caller)
    monkeypatch.setattr(runtime,'_sync_caller_voice',lambda caller,**kw:{'linked':{'user_id':'profile-owner','preferences':preferences} if state['linked'] else None,'challenge':None})
    session,frames=await setup_call(monkeypatch,None,caller_links=True)
    started,release=threading.Event(),threading.Event()
    def delayed(user_id):
        started.set()
        assert release.wait(6)
        return preferences
    monkeypatch.setattr(runtime,'_read_voice_profile',delayed)
    applied,unlinked=asyncio.Event(),asyncio.Event()
    voices=[]
    def update(**kw):
        voices.append(kw['voice_id'])
        (applied if kw['voice_id']==preferences.voice_id else unlinked).set()
    session.tts.update_options=update
    session.room.handlers['participant_connected'](SimpleNamespace(identity='chert-bridge-'+caller.call_id))
    try:
        await asyncio.wait_for(applied.wait(),1)
        assert await asyncio.to_thread(started.wait,4)
        state['linked']=False
        await asyncio.wait_for(unlinked.wait(),3)
        release.set()
        await asyncio.sleep(0.1)
        assert voices[-1]==VoicePreferences().voice_id
    finally:
        release.set()
        session.room.handlers['disconnected']()
