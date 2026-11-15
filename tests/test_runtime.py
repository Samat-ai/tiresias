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
        self.shutdown_calls=[]

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

    def shutdown(self, *, drain=True):
        self.shutdown_calls.append(drain)

    async def transcript(self, text):
        self.handlers['user_input_transcribed'](SimpleNamespace(transcript=text, is_final=True))
        with pytest.raises(runtime.StopResponse):
            await self.agent.on_user_turn_completed(None, SimpleNamespace(text_content=text))


async def setup_call(monkeypatch, vision, *, caller_links=False, bridge_ready=True, room_service=None):
    session = FakeSession(tts=SimpleNamespace(update_options=lambda **kwargs: None))
    frames = FrameBuffer('test')
    def make_session(**kwargs):
        session.runtime_options=kwargs
        return session
    monkeypatch.setattr(runtime, 'AgentSession', make_session)
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
    room=FakeRoom()
    if not bridge_ready:
        room.metadata=''
    await runtime.entrypoint(SimpleNamespace(room=room, connect=nothing,
        api=SimpleNamespace(room=room_service) if room_service else None))
    # Allow the bridge-ready greeting task to finish.
    if bridge_ready:
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

    def answer(frame, question, history, **kwargs):
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
    def answer(frame,question,recent,**kwargs):
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


@pytest.mark.asyncio
async def test_video_processing_does_not_block_loop_or_refresh_capture_timestamp(monkeypatch):
    image=SimpleNamespace(width=64,height=64,data=bytes([120,120,120,255])*64*64)
    times={}
    class CameraFrame:
        def convert(self,format):
            time.sleep(0.05)
            times['converted']=time.monotonic()
            return image
    class Stream:
        def __init__(self,*args,**kw):
            times['capacity']=kw.get('capacity')
        async def __aiter__(self):
            times['arrived']=time.monotonic()
            yield SimpleNamespace(frame=CameraFrame())
    monkeypatch.setattr(runtime.rtc,'VideoStream',Stream)
    frames=FrameBuffer('test')
    async def heartbeat():
        await asyncio.sleep(0.01)
        times['heartbeat']=time.monotonic()
    await asyncio.gather(runtime._consume_video(object(),frames,'test',{'last':0}),heartbeat())
    selected=frames.latest(2000,time.monotonic())
    assert selected is not None
    assert times['heartbeat']<times['converted']
    assert selected.received_monotonic-times['arrived']<0.02
    assert times['capacity']==1


@pytest.mark.asyncio
async def test_streamed_conversation_starts_before_trailing_metadata(monkeypatch):
    from tiresias.contracts import GroundedReply
    finish=asyncio.Event()
    async def stream(frame,question,history,**kwargs):
        yield GroundedReply(text='Two Pepsi cans.',frame_id=frame.frame_id)
        await finish.wait()
    session,frames=await setup_call(monkeypatch,SimpleNamespace(stream_answer_question=stream))
    push(frames)
    await session.transcript('How many Pepsi cans can you see?')
    try:
        assert await asyncio.wait_for(session.messages.get(),1)=='Two Pepsi cans.'
    finally:
        finish.set()


@pytest.mark.asyncio
async def test_turn_to_audio_metric_waits_for_actual_speaking_state(monkeypatch):
    from tiresias.contracts import GroundedReply
    metrics=[]
    async def nothing(): pass
    monkeypatch.setattr(runtime,'TelemetrySink',lambda url:SimpleNamespace(start=lambda:None,emit=lambda **event:metrics.append(event),close=nothing))
    session,frames=await setup_call(monkeypatch,SimpleNamespace(answer_question=lambda *args,**kwargs:GroundedReply(text='Two cans.')))
    push(frames)
    await session.transcript('How many Pepsi cans can you see?')
    await asyncio.wait_for(session.messages.get(),1)
    assert not any(row['stage']=='turn_to_first_audio' for row in metrics)
    session.handlers['agent_state_changed'](SimpleNamespace(new_state='speaking'))
    session.handlers['agent_state_changed'](SimpleNamespace(new_state='speaking'))
    assert len([row for row in metrics if row['stage']=='turn_to_first_audio'])==1


@pytest.mark.asyncio
async def test_recheck_uses_new_item_even_when_old_label_is_sharper(monkeypatch):
    def analyze(frame,target):
        return Observation(frame_id=frame.frame_id,visible_text=['OLD' if frame.jpeg_bytes==b'old' else 'NEW'],quality=Quality.READABLE)
    session,frames=await setup_call(monkeypatch,SimpleNamespace(analyze_frame=analyze))
    now=time.monotonic()
    frames.push(incoming(frames,received_monotonic=now-0.3,jpeg_bytes=b'old',sharpness=100,scene_signature=(100,)*144))
    frames.push(incoming(frames,received_monotonic=now,jpeg_bytes=b'new',sharpness=1,scene_signature=(100,)*144))
    await session.transcript('Check this.')
    await asyncio.wait_for(session.messages.get(),1)
    assert 'NEW' in await asyncio.wait_for(session.messages.get(),1)


@pytest.mark.asyncio
async def test_video_queue_wait_does_not_make_an_old_frame_fresh(monkeypatch):
    image=SimpleNamespace(width=64,height=64,data=bytes([120,120,120,255])*64*64)
    events=asyncio.Queue()
    times={}
    class CameraFrame:
        def __init__(self,slow): self.slow=slow
        def convert(self,format):
            if self.slow: time.sleep(0.45)
            return image
    class Stream:
        def __init__(self,*args,**kw):
            async def publish():
                await events.put(SimpleNamespace(frame=CameraFrame(True)))
                await asyncio.sleep(0.02)
                times['second_arrival']=time.monotonic()
                await events.put(SimpleNamespace(frame=CameraFrame(False)))
                await events.put(None)
            self.publisher=asyncio.create_task(publish())
        async def __aiter__(self):
            while (event:=await events.get()) is not None:
                yield event
        async def aclose(self):
            times['closed']=True
            await self.publisher
    monkeypatch.setattr(runtime.rtc,'VideoStream',Stream)
    frames=FrameBuffer('test')
    await runtime._consume_video(object(),frames,'test',{'last':0})
    assert time.monotonic()-times['second_arrival']>0.1
    assert frames.latest(100,time.monotonic()) is None
    assert times['closed']


@pytest.mark.asyncio
async def test_backchannel_finalized_just_after_fast_answer_does_not_prompt_again(monkeypatch):
    from tiresias.contracts import GroundedReply
    session,frames=await setup_call(monkeypatch,SimpleNamespace(answer_question=lambda *args,**kwargs:GroundedReply(text='Two Pepsi cans.')))
    push(frames)
    await session.transcript('How many Pepsi cans can you see?')
    assert await asyncio.wait_for(session.messages.get(),1)=='Two Pepsi cans.'
    await asyncio.sleep(0)
    await session.transcript('Yes.')
    await asyncio.sleep(0.25)
    assert session.messages.empty()


@pytest.mark.asyncio
@pytest.mark.parametrize('text',['Stop.','Wait.','Hold on.','Стоп.','Подожди.'])
async def test_pause_controls_confirm_listening_without_a_vision_request(monkeypatch,text):
    session,frames=await setup_call(monkeypatch,None)
    await session.transcript(text)
    assert await asyncio.wait_for(session.messages.get(),1)=="I'm listening."


@pytest.mark.asyncio
async def test_interrupting_a_pending_visual_question_gets_one_brief_ack(monkeypatch):
    from tiresias.contracts import GroundedReply
    started,release=threading.Event(),threading.Event()
    def answer(frame,question,history,**kwargs):
        if 'Pepsi' in question:
            started.set()
            assert release.wait(3)
            return GroundedReply(text='Old answer.')
        return GroundedReply(text='The can is on the left.')
    session,frames=await setup_call(monkeypatch,SimpleNamespace(answer_question=answer))
    push(frames)
    await session.transcript('How many Pepsi cans can you see?')
    assert await asyncio.to_thread(started.wait,1)
    await session.transcript('Where are they?')
    try:
        messages=[await asyncio.wait_for(session.messages.get(),1.5)]
        if messages[0]=='Got it.':
            messages.append(await asyncio.wait_for(session.messages.get(),1.5))
        assert messages[-1]=='The can is on the left.'
        assert 'Old answer.' not in messages
    finally:
        release.set()


@pytest.mark.asyncio
async def test_explicit_pause_is_acknowledged_even_just_after_another_status_cue(monkeypatch):
    session,frames=await setup_call(monkeypatch,None)
    for text in ('Wait.','Hold on.'):
        await session.transcript(text)
        assert await asyncio.wait_for(session.messages.get(),1)=="I'm listening."


@pytest.mark.asyncio
async def test_failed_status_video_publish_releases_source(monkeypatch):
    from tiresias.agent.feedback import CallFeedback
    from tiresias.agent.turns import QuietGate
    closed=[]
    class Source:
        def __init__(self,*args): pass
        async def aclose(self): closed.append(True)
    async def fail(*args): raise RuntimeError('publish failed')
    async def say(text): pass
    monkeypatch.setattr(runtime.rtc,'VideoSource',Source)
    monkeypatch.setattr(runtime.rtc.LocalVideoTrack,'create_video_track',lambda *args:object())
    ctx=SimpleNamespace(room=SimpleNamespace(local_participant=SimpleNamespace(publish_track=fail)))
    with pytest.raises(RuntimeError,match='publish failed'):
        await runtime._publish_status_video(ctx,CallFeedback(QuietGate(0),say))
    assert closed==[True]


@pytest.mark.asyncio
async def test_pause_is_acknowledged_before_bridge_ready_metadata(monkeypatch):
    session,frames=await setup_call(monkeypatch,None,bridge_ready=False)
    await session.transcript('Wait.')
    assert await asyncio.wait_for(session.messages.get(),1)=="I'm listening."
    session.room.handlers['disconnected']()


@pytest.mark.asyncio
async def test_caller_audio_reaches_stt_during_the_first_seconds_of_greeting(monkeypatch):
    import struct
    from livekit.agents.voice import AgentSession as SDKSession
    from livekit.agents.voice.agent_activity import AgentActivity
    session,_=await setup_call(monkeypatch,None)
    sdk=SDKSession(**session.runtime_options)
    sdk._agent_state='speaking'
    # Emulate the SDK's initial AEC timer, using the real session configuration
    # and push_audio implementation, rather than a fake transcript handler.
    sdk._aec_warmup_timer=asyncio.get_running_loop().call_later(10,lambda:None)
    pushed=[]
    recognition=SimpleNamespace(_push_audio=lambda frame,stt_frame=None:pushed.append(stt_frame or frame))
    activity=SimpleNamespace(_started=True,_session=sdk,_current_speech=None,
                             _rt_session=None,_audio_recognition=recognition)
    frame=runtime.rtc.AudioFrame(struct.pack('<320h',*([1000]*320)),16000,1,320)
    try:
        AgentActivity.push_audio(activity,frame)
        assert bytes(pushed[0].data)==bytes(frame.data)
    finally:
        sdk._aec_warmup_timer.cancel()


@pytest.mark.asyncio
@pytest.mark.parametrize('initial_metadata',['{}','{"chert_bridge_ready":false}'])
async def test_warm_room_waits_for_real_ready_signal_after_caller_audio(monkeypatch,initial_metadata):
    session,_=await setup_call(monkeypatch,None,bridge_ready=False)
    session.room.metadata=initial_metadata
    session.room.handlers['track_subscribed'](
        SimpleNamespace(kind=runtime.rtc.TrackKind.KIND_AUDIO),
        SimpleNamespace(name=runtime.CALLER_AUDIO_TRACK),
        SimpleNamespace(identity='chert-bridge-test'))
    await asyncio.sleep(0.3)
    assert session.messages.empty()
    session.room.metadata='{"chert_bridge_ready":true}'
    assert 'Tiresias' in await asyncio.wait_for(session.messages.get(),1)
    session.room.handlers['disconnected']()


@pytest.mark.asyncio
async def test_bridge_disconnect_cancels_pending_greeting(monkeypatch):
    session,_=await setup_call(monkeypatch,None,bridge_ready=False)
    handler=session.room.handlers.get('participant_disconnected')
    assert handler is not None
    handler(SimpleNamespace(identity='chert-bridge-test'))
    session.room.metadata='chert_bridge_ready'
    await asyncio.sleep(0.3)
    assert session.messages.empty()


@pytest.mark.asyncio
async def test_server_metadata_readiness_recovers_a_stale_rtc_room(monkeypatch):
    ready=False
    async def list_rooms(request):
        assert list(request.names)==['test-room']
        return SimpleNamespace(rooms=[SimpleNamespace(name='test-room',
            metadata='{"chert_bridge_ready":true}' if ready else '{"chert_warm":true}')])
    session,_=await setup_call(monkeypatch,None,bridge_ready=False,
                             room_service=SimpleNamespace(list_rooms=list_rooms))
    session.room.handlers['track_subscribed'](
        SimpleNamespace(kind=runtime.rtc.TrackKind.KIND_AUDIO),
        SimpleNamespace(name=runtime.CALLER_AUDIO_TRACK),
        SimpleNamespace(identity='chert-bridge-test'))
    await asyncio.sleep(0.3)
    assert session.messages.empty()
    ready=True
    assert 'Tiresias' in await asyncio.wait_for(session.messages.get(),2)
    session.room.handlers['disconnected']()


@pytest.mark.asyncio
async def test_bridge_transport_failure_shuts_down_sdk_without_draining_audio(monkeypatch):
    session,_=await setup_call(monkeypatch,None)
    session.room.handlers['participant_disconnected'](
        SimpleNamespace(identity='chert-bridge-test',disconnect_reason='CONNECTION_TIMEOUT'))
    assert session.shutdown_calls==[False]


@pytest.mark.asyncio
async def test_noise_does_not_interrupt_or_acknowledge_pending_answer(monkeypatch):
    from tiresias.contracts import GroundedReply
    started,release=threading.Event(),threading.Event()
    calls=[]
    def answer(frame,question,history,**kwargs):
        calls.append(question);started.set();release.wait(3)
        return GroundedReply(text='Two Pepsi cans.')
    session,frames=await setup_call(monkeypatch,SimpleNamespace(answer_question=answer))
    push(frames)
    await session.transcript('How many Pepsi cans can you see?')
    assert await asyncio.to_thread(started.wait,1)
    try:
        for noise in ['А-а-а...','Um, um-','Я га-','Ага.','Да, да, я вижу.']:
            await session.transcript(noise)
        await asyncio.sleep(0.25)
        assert session.interruptions==1
        assert session.messages.empty()
        assert len(calls)==1
    finally: release.set()
    assert await asyncio.wait_for(session.messages.get(),1)=='Two Pepsi cans.'


@pytest.mark.asyncio
async def test_response_language_changes_only_on_explicit_command(monkeypatch):
    from tiresias.contracts import GroundedReply
    languages=[]
    def answer(frame,question,history,*,language='English'):
        languages.append(language)
        return GroundedReply(text='Two cans.' if language=='English' else 'Две банки.')
    session,frames=await setup_call(monkeypatch,SimpleNamespace(answer_question=answer))
    for question,expected in [('Что ты видишь?','Two cans.'),('Speak Russian.',None),
                              ('How many Pepsi cans can you see?','Две банки.'),('Switch to English.',None),
                              ('Что ты видишь?','Two cans.')]:
        push(frames);await session.transcript(question)
        response=await asyncio.wait_for(session.messages.get(),1)
        if expected: assert response==expected
    assert languages==['English','Russian','English']
