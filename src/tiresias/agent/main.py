from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections import deque
from uuid import uuid4, UUID

from dotenv import load_dotenv
from livekit import api, rtc
from livekit.agents import AgentServer, AutoSubscribe, JobContext, StopResponse, cli
from livekit.agents.voice import Agent, AgentSession, room_io
from livekit.plugins import elevenlabs, silero
from livekit.plugins.elevenlabs import VoiceSettings
from PIL import Image

from tiresias.agent.controller import TaskController
from tiresias.agent.feedback import CallFeedback
from tiresias.agent.intent import IntentClassifier
from tiresias.agent.media import CALLER_AUDIO_TRACK, CALLER_VIDEO_TRACK, FrameBuffer, IncomingFrame
from tiresias.agent.speech import CallLifecycle, SpeechScheduler
from tiresias.agent.turns import LatestTurn, QuietGate, acknowledge_and_analyze
from tiresias.agent.vision import VisionClient,reading_task
from tiresias.config import Settings
from tiresias.contracts import IntentKind
from tiresias.db import connect
from tiresias.preferences import VoicePreferences, VOICE_BY_ID, ProfileCodeEntry, resolve_profile_code, save_preferences, get_preferences
from tiresias.telemetry import TelemetrySink
from tiresias.chert_identity import ChertCallerResolver
from tiresias.caller_links import linked_preferences, issue_challenge

load_dotenv(".env.local")
load_dotenv(".env")

logger = logging.getLogger("tiresias.agent")
settings = Settings()
AGENT_NAME = os.environ.get("AGENT_NAME", settings.agent_name)
server = AgentServer()
_VAD = silero.VAD.load()


def _bridge_metadata_ready(metadata: str) -> bool:
    try:
        value=json.loads(metadata or '{}')
    except (TypeError,ValueError):
        return metadata=='chert_bridge_ready'  # Legacy marker.
    return isinstance(value,dict) and value.get('chert_bridge_ready') is True


class TiresiasAgent(Agent):
    def __init__(self, on_user_text) -> None:
        super().__init__(
            instructions=(
                "You are Tiresias, a controlled FaceTime label assistant. "
                "Do not invent free-form answers. Application policy owns every spoken line."
            )
        )
        self._on_user_text = on_user_text
        self._completed_messages = deque(maxlen=128)

    def accept_user_message(self,new_message) -> None:
        if getattr(new_message,'role','user')!='user':
            return
        message_id=getattr(new_message,'id',None)
        if message_id and message_id in self._completed_messages:
            return
        text = getattr(new_message, "text_content", "") or ""
        if not text:
            content = getattr(new_message, "content", [])
            text = content if isinstance(content, str) else " ".join(p for p in content if isinstance(p, str))
        if text.strip():
            if message_id:
                self._completed_messages.append(message_id)
            self._on_user_text(text.strip())

    async def on_user_turn_completed(self, turn_ctx, new_message) -> None:
        self.accept_user_message(new_message)
        # Turn detection owns dispatch; raw STT segments are only diagnostics.
        raise StopResponse()


_VISION: VisionClient | None = None
_INTENT: IntentClassifier | None = None

# Slightly lower stability + light style keeps flash TTS less monotone.
_TTS_VOICE_SETTINGS = VoiceSettings(
    stability=0.35,
    similarity_boost=0.8,
    style=0.2,
    speed=0.95,
)


def _get_vision() -> VisionClient | None:
    global _VISION
    if _VISION is not None:
        return _VISION
    if not settings.gemini_api_key and not settings.google_genai_use_vertexai:
        return None
    _VISION = VisionClient(
        settings.gemini_api_key,
        model=settings.gemini_model,
        timeout_seconds=settings.vision_timeout_seconds,
        **settings.gemini_backend_options(),
    )
    return _VISION


def _get_intent_classifier() -> IntentClassifier:
    global _INTENT
    if _INTENT is not None:
        return _INTENT
    _INTENT = IntentClassifier(
        api_key=settings.gemini_api_key,
        model=settings.gemini_model,
        timeout_seconds=min(8.0, float(settings.vision_timeout_seconds)),
        **settings.gemini_backend_options(),
    )
    return _INTENT


def _load_voice_profile(code):
    if not settings.database_url:
        return None
    with connect(settings.database_url,connect_timeout=2) as conn:
        return resolve_profile_code(conn,code)


def _save_voice_profile(user_id, preferences):
    with connect(settings.database_url,connect_timeout=2) as conn:
        save_preferences(conn,user_id,preferences)


def _read_voice_profile(user_id):
    with connect(settings.database_url,connect_timeout=2) as conn:
        return get_preferences(conn,user_id)['preferences']


def _resolve_chert_caller(call_id):
    return ChertCallerResolver(settings.chert_project_id,
        credentials_file=settings.chert_credentials_file or None).resolve(call_id)


def _sync_caller_voice(caller,*,allow_challenge=True):
    with connect(settings.database_url,connect_timeout=2) as conn:
        conn.execute("SET LOCAL statement_timeout='2000ms'")
        linked=linked_preferences(conn,handle=caller.handle,key=settings.caller_link_secret)
        challenge=issue_challenge(conn,handle=caller.handle,key=settings.caller_link_secret,
                                  call_id=caller.call_id) if allow_challenge else None
        return {'linked':linked,'challenge':challenge}


@server.rtc_session(agent_name=AGENT_NAME)
async def entrypoint(ctx: JobContext) -> None:
    settings.assert_runtime_safe()
    key = settings.elevenlabs_key()
    if not key:
        raise RuntimeError("ELEVENLABS_API_KEY is required")
    os.environ.setdefault("ELEVEN_API_KEY", key)

    await ctx.connect(auto_subscribe=AutoSubscribe.SUBSCRIBE_ALL)
    epoch = f"{ctx.room.name}:{uuid4()}"
    lifecycle = CallLifecycle()
    buffer = FrameBuffer(session_id=epoch)
    scheduler = SpeechScheduler()
    controller = TaskController(
        epoch,
        buffer,
        scheduler,
        evidence_max_age_ms=settings.visual_evidence_max_age_ms,
        frame_max_age_ms=settings.frame_max_local_age_ms,
    )
    pending_prompt_id: str | None = None
    sample_state = {"last": 0.0}
    vision_budget = {"left": settings.max_vision_requests_per_call}
    turns = LatestTurn()
    quiet = QuietGate()
    conversation_history: list[dict] = []
    response_audio_clock={'started':None,'ready':False}
    recent_speech={'finished_at':0.0}
    subscribed_video: set[str] = set()
    video_tasks: set[asyncio.Task] = set()
    voice_state={'preferences':VoicePreferences(), 'user_id':None, 'attempts':0, 'closed':False}
    voice_state.update(manual_profile=False,auto_user_id=None,setup_code=None,selection_revision=0)
    profile_entry=ProfileCodeEntry()
    caller_task=None
    avatar_task=None
    greeting_task=None
    warm_task=None
    caller_audio_ready=asyncio.Event()
    caller_resolved=asyncio.Event()
    controller.speed=voice_state['preferences'].speed
    call_id=str(uuid4())
    source='REPLAY' if ctx.room.name.startswith('tiresias-smoke-') else 'FACETIME'
    telemetry=TelemetrySink(settings.database_url)
    telemetry.start()

    def measure(stage, started, outcome='ok'):
        telemetry.emit(stage=stage,duration_ms=max(0,int((time.monotonic()-started)*1000)),
                       outcome=outcome,session_id=call_id,source=source,model_id=settings.gemini_model or 'gemini-3.5-flash-lite')

    session = AgentSession(
        # Preserve early controls on the Chert caller track. SDK default AEC
        # warmup replaces its first 3s of speech with silence during greeting.
        # Echo suppression remains a FaceTime/bridge handset verification gate.
        aec_warmup_duration=0,
        stt=elevenlabs.STT(
            model=settings.elevenlabs_stt_model,
            api_key=key,
            language_code="en",
            secondary_languages=["ru"],
            include_language_detection=True,
            server_vad={"vad_silence_threshold_secs": 0.6, "vad_threshold": 0.5},
        ),
        tts=elevenlabs.TTS(
            model=settings.elevenlabs_tts_model,
            voice_id=voice_state['preferences'].voice_id,
            api_key=key,
            voice_settings=VoiceSettings(**voice_state['preferences'].tts_options()),
            apply_text_normalization="on",
        ),
        vad=_VAD,
        turn_handling={
            "turn_detection": "stt",
            "endpointing": {"min_delay": 0.2, "max_delay": 2.0},
            "interruption": {
                # Final meaningful utterances interrupt explicitly below. Keep
                # listening during playback without noise/backchannel VAD cuts.
                "enabled": False, "discard_audio_if_uninterruptible": False,
            },
        },
    )

    async def speak(text: str, *, interruptible: bool = False, private: bool = False,
                    status_cue: bool = False, answer: bool = False) -> None:
        started=None
        try:
            if not status_cue:
                await feedback.before_answer()
                await quiet.wait()
            started=time.monotonic()
            if answer:
                response_audio_clock['ready']=True
            logger.info("speaking response: %s", '[private setup instructions]' if private else text[:160])
            await session.say(text, allow_interruptions=interruptible,add_to_chat_ctx=not (private or status_cue))
            if not (private or status_cue):
                conversation_history.append({"role": "assistant", "text": text})
                del conversation_history[:-6]
        except Exception:
            logger.exception("speak failed: %s", '[private setup instructions]' if private else text[:80])
        finally:
            if started is not None:
                recent_speech['finished_at']=time.monotonic()
                measure('speech_playout',started)

    async def say_status(text):
        await speak(text,status_cue=True)

    feedback=CallFeedback(quiet,say_status)

    def submit_turn(work, *, cue=None, delay=1.5):
        token=feedback.begin_work()
        if cue:
            feedback.queue_cue(cue,token=token,delay=delay)

        async def run():
            try:
                await work
            finally:
                feedback.finish_work(token)
        turns.submit(run())
        return token

    def apply_voice(preferences):
        voice_state['selection_revision']+=1
        voice_state['preferences']=preferences
        controller.speed=preferences.speed
        session.tts.update_options(voice_id=preferences.voice_id,voice_settings=VoiceSettings(**preferences.tts_options()))
        logger.info('voice preferences applied voice=%s tone=%s speed=%s',preferences.voice_id,preferences.tone,preferences.speed)

    async def save_voice():
        if voice_state['user_id'] and settings.database_url:
            try:
                await asyncio.to_thread(_save_voice_profile,voice_state['user_id'],voice_state['preferences'])
            except Exception as error:
                logger.warning('Could not save voice preferences: %s',type(error).__name__)
                return False
        return True

    async def voice_command(command):
        if command.cancel_profile:
            await speak('Profile entry cancelled.')
            return
        if command.profile_code is not None:
            if len(command.profile_code)!=8:
                remaining=8-len(command.profile_code)
                await speak('Say the eight digits of your profile code, one at a time.' if remaining==8
                            else f'I have {len(command.profile_code)} digits. Say the remaining {remaining}.')
                return
            voice_state['attempts']+=1
            if voice_state['attempts']>5:
                await speak('Please call again to try another profile code.')
                return
            try:
                linked=await asyncio.to_thread(_load_voice_profile,command.profile_code)
            except Exception as error:
                logger.warning('Profile lookup failed: %s',type(error).__name__)
                await speak('I could not load that profile just now. Your current voice still works.')
                return
            if not linked:
                await speak('That profile code was not recognized. Say the eight digits one at a time.')
                return
            voice_state['user_id']=linked['user_id']
            voice_state['manual_profile']=True
            apply_voice(linked['preferences'])
            await speak('Your saved voice preferences are loaded.')
            return
        preferences=VoicePreferences.model_validate({**voice_state['preferences'].model_dump(),**command.updates})
        apply_voice(preferences)
        saved=await save_voice()
        description=VOICE_BY_ID[preferences.voice_id]['name'] if 'voice_id' in command.updates else preferences.tone+' tone'
        await speak(f'Using {description}.' if saved else f'Using {description} for this call. I could not save the change just now.')

    async def refresh_voice():
        while not voice_state['closed']:
            await asyncio.sleep(3)
            if voice_state['user_id'] and settings.database_url:
                try:
                    user_id=voice_state['user_id']
                    revision=voice_state['selection_revision']
                    preferences=await asyncio.to_thread(_read_voice_profile,user_id)
                    if (voice_state['closed'] or voice_state['user_id']!=user_id
                            or voice_state['selection_revision']!=revision):
                        continue
                    if preferences!=voice_state['preferences']:
                        apply_voice(preferences)
                except Exception as error:
                    logger.warning('Profile refresh unavailable: %s',type(error).__name__)

    refresh_task=asyncio.create_task(refresh_voice()) if settings.database_url else None

    async def announce_setup_code(code):
        await session.interrupt(force=True)
        await speak('To remember your voice settings, enter these four digits on the website: '
                    +', '.join(code)+'. You only need to do this once.',private=True)

    async def follow_caller(call_id):
        try:
            caller=None
            for _ in range(3):
                caller=await asyncio.to_thread(_resolve_chert_caller,call_id)
                if voice_state['closed']:
                    return
                if caller:
                    break
                await asyncio.sleep(1)
            if not caller:
                logger.info('Caller auto-selection unavailable; keeping normal call controls.')
                return
            while not voice_state['closed']:
                try:
                    result=await asyncio.to_thread(_sync_caller_voice,caller,allow_challenge=lifecycle.bridge_ready)
                    if voice_state['closed']:
                        return
                    linked=result['linked']
                    if not voice_state['manual_profile']:
                        if linked and voice_state['auto_user_id']!=linked['user_id']:
                            voice_state['user_id']=linked['user_id']
                            voice_state['auto_user_id']=linked['user_id']
                            apply_voice(linked['preferences'])
                            logger.info('Saved voice preferences loaded for verified caller.')
                        elif not linked and voice_state['auto_user_id']:
                            voice_state['user_id']=None
                            voice_state['auto_user_id']=None
                            apply_voice(VoicePreferences())
                    caller_resolved.set()
                    if result['challenge']:
                        voice_state['setup_code']=result['challenge']['code']
                        submit_turn(announce_setup_code(voice_state['setup_code']))
                except Exception as error:
                    logger.warning('Caller settings sync unavailable: %s',type(error).__name__)
                    caller_resolved.set()
                await asyncio.sleep(2.5)
        finally:
            caller_resolved.set()

    @session.on('metrics_collected')
    def _on_metrics(ev):
        ttfb=getattr(getattr(ev,'metrics',None),'ttfb',None)
        if ttfb is not None:
            telemetry.emit(stage='tts_first_audio',duration_ms=max(0,int(ttfb*1000)),outcome='ok',session_id=call_id,source=source)

    @session.on("user_state_changed")
    def _on_user_state(ev) -> None:
        quiet.set_speaking(ev.new_state == "speaking")
        feedback.user_speaking=ev.new_state == 'speaking'

    @session.on('agent_state_changed')
    def _on_agent_state(ev):
        feedback.agent_speaking=ev.new_state == 'speaking'
        if ev.new_state=='speaking' and response_audio_clock['ready'] and response_audio_clock['started'] is not None:
            measure('turn_to_first_audio',response_audio_clock['started'])
            response_audio_clock['started']=None

    async def run_conversation(question: str) -> None:
        if vision_budget["left"] <= 0:
            await speak("I've reached the image limit for this call. Call again to keep going.")
            return
        frame = (buffer.latest if reading_task(question) else buffer.best)(settings.frame_max_local_age_ms, time.monotonic())
        history = list(conversation_history[-6:])
        vision_budget["left"] -= 1
        started = time.monotonic()
        stream=None
        delivered=False
        try:
            vision=await asyncio.to_thread(_get_vision)
            if vision is None:
                raise RuntimeError('vision is not configured')
            if hasattr(vision,'stream_answer_question'):
                stream=vision.stream_answer_question(frame,question,history)
                reply=await asyncio.wait_for(anext(stream),settings.vision_timeout_seconds)
            else:
                reply=await asyncio.wait_for(asyncio.to_thread(vision.answer_question,frame,question,history),settings.vision_timeout_seconds)
            logger.info('conversational speech ready elapsed_ms=%d frame=%s',(time.monotonic()-started)*1000,
                        f'{frame.width}x{frame.height}' if frame else 'none')
            measure('conversation',started)
            controller.set_time(time.monotonic())
            for event in controller.conversational_reply(reply,frame):
                delivered=True
                await speak(event.text,answer=True)
        except Exception:
            logger.exception("conversational vision failed")
            if not delivered:
                measure('conversation',started,'error')
                await speak("I couldn't finish that look. Could you try again?")
        finally:
            if stream is not None:
                await stream.aclose()

    async def run_vision(stage: str, revision: int) -> list[str]:
        loop = asyncio.get_running_loop()
        if vision_budget["left"] <= 0:
            return ["I've reached the image limit for this call. Call again to keep going."]
        # A recheck must see the current selection, not the largest old JPEG.
        frame = (buffer.latest if stage=='recheck' else buffer.best)(settings.frame_max_local_age_ms, time.monotonic())
        if frame is None:
            return ["I'm not getting a current camera view. Check that your video is on."]
        target = controller.task.target
        started = time.monotonic()
        vision_budget["left"] -= 1
        try:
            async def analyze():
                vision = await loop.run_in_executor(None, _get_vision)
                if vision is None:
                    raise RuntimeError("GEMINI_API_KEY is not configured")
                return await loop.run_in_executor(None, lambda: vision.analyze_frame(frame, target))

            observation = await asyncio.wait_for(
                analyze(), timeout=settings.vision_timeout_seconds,
            )
        except Exception:
            logger.exception("vision analysis failed")
            measure('vision',started,'error')
            if controller.inflight_revision == revision:
                controller.inflight_revision = None
            return ["The image service didn't respond. Say try again and I'll take another look."]
        logger.info(
            "vision result elapsed_ms=%d frame_age_ms=%d dimensions=%sx%s bytes=%d quality=%s text_spans=%d",
            (time.monotonic() - started) * 1000,
            (started - frame.received_monotonic) * 1000,
            frame.width, frame.height, len(frame.jpeg_bytes), observation.quality.value,
            len(observation.visible_text),
        )
        measure('vision',started)
        controller.set_time(time.monotonic())
        events = controller.complete_inflight(
            revision,
            observation,
            stage,
            analyzed_frame=frame,
        )
        return [event.text for event in events]

    def handle_user_text(text: str) -> None:
        cleaned = text.strip()
        if not cleaned or voice_state['closed']:
            return
        # Open listening as soon as audio exists so commands are not dropped
        # while waiting for chert_bridge_ready metadata.
        lifecycle.on_caller_audio(epoch)
        if lifecycle.accept_audio("caller", cleaned) is None:
            return
        feedback.connect()
        logger.info("user transcript: %s", cleaned[:120])
        if cleaned.lower().strip(' .!?') in {'repeat setup code','repeat the setup code'} and voice_state['setup_code']:
            submit_turn(announce_setup_code(voice_state['setup_code']))
            return
        classifier = _get_intent_classifier()
        command=profile_entry.consume(cleaned)
        if command is not None:
            response_audio_clock['started']=None
            async def change_voice():
                await session.interrupt(force=True)
                await voice_command(command)
            submit_turn(change_voice())
            return

        # Backchannels must not replace an answer already being generated/spoken.
        immediate = classifier.route(cleaned, controller.task, pending_prompt_id)
        if immediate.kind == IntentKind.SOCIAL:
            if turns.task is not None and not turns.task.done():
                return
            if cleaned.lower().strip(' .!?') in {
                'yes','yeah','yep','okay','ok','sure','thanks','thank you','да','спасибо','хорошо',
            } and time.monotonic()-recent_speech['finished_at']<2:
                # Faster answers can finish before STT finalizes a backchannel
                # spoken during playback. Do not add a second prompt afterward.
                return
        response_audio_clock['started']=time.monotonic() if immediate.kind in {
            IntentKind.CONVERSATION,IntentKind.CHECK,IntentKind.FIND_TARGET,IntentKind.CHANGE_TARGET} else None
        response_audio_clock['ready']=False
        conversation_history.append({"role": "user", "text": cleaned})
        del conversation_history[:-6]
        was_active=feedback.busy or feedback.agent_speaking

        async def route_and_act() -> None:
            intent = immediate
            logger.info("routed intent: %s", intent.kind.value)
            if intent.kind != IntentKind.SOCIAL:
                await session.interrupt(force=True)
            if intent.kind == IntentKind.CONVERSATION:
                feedback.queue_cue('Got it.' if was_active else 'Taking a look.',
                                   token=work_token,delay=0 if was_active else 1.5)
            if intent.kind == IntentKind.SOCIAL:
                greeting = cleaned.lower().strip(' .!?') in {"hello", "hi", "hey", "привет"}
                await speak("I'm here. What would you like me to look at?" if greeting else "Okay. What would you like to know?")
                return
            if intent.kind == IntentKind.CONVERSATION:
                controller.task.analysis_revision += 1
                controller.inflight_revision = None
                await run_conversation(cleaned)
                return
            controller.set_time(time.monotonic())
            events = controller.handle(intent)
            if intent.kind == IntentKind.STOP:
                feedback.busy=False
                await feedback.queue_cue("I'm listening.",token=work_token,delay=0,force=True)
                return
            if intent.kind in {IntentKind.SLOWER, IntentKind.FASTER}:
                apply_voice(voice_state['preferences'].model_copy(update={'speed':controller.speed}))
                await save_voice()

            async def acknowledge():
                for event in events:
                    await speak(event.text)
                feedback.queue_cue('Still checking.',token=work_token,delay=3.5)

            if intent.kind in {IntentKind.FIND_TARGET, IntentKind.CHANGE_TARGET, IntentKind.CHECK}:
                revision = controller.inflight_revision
                if revision is not None:
                    stage = "recheck" if intent.kind == IntentKind.CHECK else "candidate"
                    results = await acknowledge_and_analyze(acknowledge(), run_vision(stage, revision))
                    for result in results:
                        await speak(result,answer=True)
                    return
            await acknowledge()

        work_token=submit_turn(route_and_act())

    @session.on("user_input_transcribed")
    def _on_transcript(ev) -> None:
        text = getattr(ev, "transcript", None) or getattr(ev, "text", "") or ""
        is_final = getattr(ev, "is_final", True)
        if not text:
            return
        if not is_final:
            logger.info("interim transcript: %s", text[:80])
            return
        logger.info("final STT segment: %s", text[:120])

    def _link_bridge(participant: rtc.RemoteParticipant) -> None:
        nonlocal caller_task
        identity = participant.identity or ""
        if not identity.startswith("chert-bridge"):
            return
        room_io_obj = getattr(session, "_room_io", None)
        if room_io_obj is not None:
            room_io_obj.set_participant(identity)
            logger.info("linked room io to %s", identity)
        if caller_task is None and settings.database_url and len(settings.caller_link_secret)>=32:
            call_id=identity.removeprefix('chert-bridge-')
            try:
                valid=str(UUID(call_id))==call_id
            except ValueError:
                valid=False
            if valid:
                caller_task=asyncio.create_task(follow_caller(call_id))

    def _on_participant(participant: rtc.RemoteParticipant) -> None:
        _link_bridge(participant)

    def _on_track(track: rtc.Track, publication: rtc.RemoteTrackPublication, participant: rtc.RemoteParticipant) -> None:
        name = publication.name or getattr(track, "name", "") or ""
        logger.info(
            "track subscribed name=%s kind=%s participant=%s",
            name,
            getattr(track, "kind", None),
            participant.identity,
        )
        _link_bridge(participant)
        if name == CALLER_VIDEO_TRACK and isinstance(track, rtc.RemoteVideoTrack):
            if publication.sid not in subscribed_video:
                if publication.simulcasted:
                    publication.set_video_quality(rtc.VideoQuality.VIDEO_QUALITY_HIGH)
                    logger.info("requested highest caller video quality for label reading")
                subscribed_video.add(publication.sid)
                video_task=asyncio.create_task(_consume_video(track, buffer, epoch, sample_state))
                video_tasks.add(video_task)
                video_task.add_done_callback(video_tasks.discard)
        if name == CALLER_AUDIO_TRACK or track.kind == rtc.TrackKind.KIND_AUDIO:
            lifecycle.on_caller_audio(epoch)
            feedback.connect()
            if name == CALLER_AUDIO_TRACK and participant.identity.startswith('chert-bridge'):
                caller_audio_ready.set()
            logger.info("caller audio track ready")

    ctx.room.on("track_subscribed", _on_track)
    ctx.room.on("participant_connected", _on_participant)

    def _on_disconnect(*args) -> None:
        if voice_state['closed']:
            return
        turns.cancel()
        feedback.close()
        if avatar_task:
            avatar_task.cancel()
        if greeting_task:
            greeting_task.cancel()
        if warm_task:
            warm_task.cancel()
        for video_task in tuple(video_tasks):
            video_task.cancel()
        buffer.clear()
        lifecycle.disconnect()
        voice_state['closed']=True
        if refresh_task:
            refresh_task.cancel()
        if caller_task:
            caller_task.cancel()
        asyncio.create_task(telemetry.close())

    ctx.room.on("disconnected", _on_disconnect)

    def _on_bridge_disconnect(participant):
        if (participant.identity or '').startswith('chert-bridge') and not voice_state['closed']:
            _on_disconnect()
            # Cancelling say() awaiters does not stop SDK-owned playback.
            # Transport failures are not all covered by RoomIO's auto-close.
            session.shutdown(drain=False)

    ctx.room.on('participant_disconnected',_on_bridge_disconnect)

    @session.on('close')
    def _on_session_close(ev):
        _on_disconnect()

    # Prime OAuth/HTTPS while the bridge is warming. This metadata GET does
    # not run inference or send a caller image.
    async def warm_vision():
        try:
            def warm():
                vision=_get_vision()
                if vision is not None and hasattr(vision,'prewarm'):
                    vision.prewarm()
            await asyncio.to_thread(warm)
        except Exception as error:
            logger.warning('Vision client warmup failed: %s',type(error).__name__)
    warm_task=asyncio.create_task(warm_vision())

    async def wait_bridge_ready() -> None:
        next_probe=0.0
        probe_warning=False
        while not voice_state['closed']:
            ready=_bridge_metadata_ready(ctx.room.metadata)
            # Chert requires its explicit media-ready flag. Read the server's
            # metadata as a backup when RTC's local room state has not updated.
            # Caller track arrival enables probing, but never authorizes speech.
            if not ready and caller_audio_ready.is_set() and time.monotonic()>=next_probe:
                next_probe=time.monotonic()+0.75
                try:
                    client=getattr(ctx,'api',None)
                    if client is not None:
                        rooms=await asyncio.wait_for(client.room.list_rooms(
                            api.ListRoomsRequest(names=[ctx.room.name])),2)
                        ready=any(room.name==ctx.room.name and _bridge_metadata_ready(room.metadata)
                                  for room in rooms.rooms)
                        if ready:
                            logger.info('Bridge readiness confirmed through room service')
                except Exception as error:
                    if not probe_warning:
                        logger.warning('Bridge readiness lookup unavailable: %s',type(error).__name__)
                        probe_warning=True
            if ready:
                if voice_state['closed']:
                    return
                feedback.connect()
                if caller_task is not None and not caller_resolved.is_set():
                    try:
                        await asyncio.wait_for(caller_resolved.wait(),1.5)
                    except TimeoutError:
                        pass
                greeting = lifecycle.on_bridge_ready(epoch)
                if greeting and not lifecycle.transcripts:
                    await speak(greeting, interruptible=False)
                return
            await asyncio.sleep(0.1)

    agent=TiresiasAgent(handle_user_text)

    @session.on('conversation_item_added')
    def _on_completed_item(ev):
        # LiveKit retains completed user messages here when uninterruptible
        # playback bypasses on_user_turn_completed. Recover that completed turn;
        # message IDs prevent duplicate dispatch without suppressing retries.
        if not voice_state['closed']:
            agent.accept_user_message(ev.item)

    logger.info('Starting call audio session')
    await session.start(
        agent=agent,
        room=ctx.room,
        room_input_options=room_io.RoomInputOptions(
            audio_enabled=True,
            text_enabled=False,
            close_on_disconnect=True,
            participant_kinds=[
                rtc.ParticipantKind.PARTICIPANT_KIND_STANDARD,
                rtc.ParticipantKind.PARTICIPANT_KIND_SIP,
                rtc.ParticipantKind.PARTICIPANT_KIND_CONNECTOR,
            ],
        ),
    )
    logger.info('Call audio session ready')
    for participant in ctx.room.remote_participants.values():
        _link_bridge(participant)
        # connect() may subscribe before the event handlers were installed.
        for publication in participant.track_publications.values():
            if publication.track is not None:
                _on_track(publication.track, publication, participant)
    greeting_task=asyncio.create_task(wait_bridge_ready())
    try:
        avatar_task=await _publish_status_video(ctx,feedback)
        if voice_state['closed'] and avatar_task:
            avatar_task.cancel()
    except Exception:
        logger.exception('Status video unavailable; voice remains active')


async def _consume_video(track: rtc.RemoteVideoTrack, buffer: FrameBuffer, session_id: str, sample_state: dict) -> None:
    stream = rtc.VideoStream(track,capacity=1)
    loop = asyncio.get_running_loop()
    ingress=asyncio.Queue(maxsize=1)

    async def receive():
        try:
            async for event in stream:
                arrived=(event.frame,time.monotonic(),time.time())
                if ingress.full():
                    ingress.get_nowait()
                ingress.put_nowait(arrived)
            await ingress.put(None)
        except Exception:
            logger.exception('camera ingress failed')
            if ingress.full():
                ingress.get_nowait()
            ingress.put_nowait(None)

    receiver=asyncio.create_task(receive())
    try:
        while (arrived:=await ingress.get()) is not None:
            frame,now,captured_at=arrived
            if now-sample_state['last']<0.35:
                continue
            sample_state['last']=now
            try:
                def encode():
                    from tiresias.agent.media import JPEG_QUALITY,MAX_EDGE,frame_features
                    import io
                    argb=frame.convert(rtc.VideoBufferType.RGBA)
                    image=Image.frombytes('RGBA',(argb.width,argb.height),bytes(argb.data)).convert('RGB')
                    image.thumbnail((MAX_EDGE,MAX_EDGE))
                    sharpness,signature=frame_features(image)
                    out=io.BytesIO()
                    image.save(out,format='JPEG',quality=JPEG_QUALITY,optimize=True)
                    return out.getvalue(),image.width,image.height,sharpness,signature

                jpeg,width,height,sharpness,signature=await loop.run_in_executor(None,encode)
                from tiresias.agent.media import same_view
                previous=sample_state.get('signature')
                if previous and not same_view(previous,signature):
                    sample_state['scene_epoch']=sample_state.get('scene_epoch',0)+1
                sample_state['signature']=signature
                buffer.push(IncomingFrame(session_id=session_id,track_name=CALLER_VIDEO_TRACK,
                    participant_kind='caller',jpeg_bytes=jpeg,width=width,height=height,
                    received_monotonic=now,received_at=captured_at,camera_region=(0,0,width,height),
                    scene_epoch=sample_state.get('scene_epoch',0),sharpness=sharpness,scene_signature=signature))
            except Exception:
                logger.exception('failed to ingest caller frame')
    finally:
        receiver.cancel()
        await asyncio.gather(receiver,return_exceptions=True)
        if close:=getattr(stream,'aclose',None):
            await close()


async def _publish_status_video(ctx: JobContext, feedback: CallFeedback) -> asyncio.Task:
    from tiresias.agent.avatar import AvatarRenderer
    renderer=await asyncio.to_thread(AvatarRenderer)
    source = rtc.VideoSource(renderer.width, renderer.height)
    track = rtc.LocalVideoTrack.create_video_track("tiresias-status", source)
    options = rtc.TrackPublishOptions()
    options.source = rtc.TrackSource.SOURCE_CAMERA
    options.video_encoding.CopyFrom(rtc.VideoEncoding(max_framerate=10,max_bitrate=450_000))
    try:
        await ctx.room.local_participant.publish_track(track, options)
    except BaseException:
        await source.aclose()
        raise

    async def pump() -> None:
        try:
            while not feedback.closed:
                started=time.monotonic()
                pixels=await asyncio.to_thread(renderer.render_bytes,feedback.state,started)
                if feedback.closed:
                    break
                source.capture_frame(rtc.VideoFrame(renderer.width,renderer.height,rtc.VideoBufferType.RGB24,pixels))
                await asyncio.sleep(max(0.01,0.1-(time.monotonic()-started)))
        except Exception:
            logger.exception('Status animation stopped; voice remains active')
        finally:
            await source.aclose()

    task=asyncio.create_task(pump())
    # Enter the task's try/finally before exposing it to disconnect cancellation.
    await asyncio.sleep(0)
    return task


def main() -> None:
    cli.run_app(server)


if __name__ == "__main__":
    main()
