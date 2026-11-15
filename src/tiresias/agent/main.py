from __future__ import annotations

import asyncio
import logging
import os
import time
from uuid import uuid4

from dotenv import load_dotenv
from livekit import rtc
from livekit.agents import AgentServer, AutoSubscribe, JobContext, StopResponse, cli
from livekit.agents.voice import Agent, AgentSession, room_io
from livekit.plugins import elevenlabs, silero
from livekit.plugins.elevenlabs import VoiceSettings
from PIL import Image, ImageDraw

from tiresias.agent.controller import TaskController
from tiresias.agent.intent import IntentClassifier
from tiresias.agent.media import CALLER_AUDIO_TRACK, CALLER_VIDEO_TRACK, FrameBuffer, IncomingFrame
from tiresias.agent.speech import CallLifecycle, SpeechScheduler
from tiresias.agent.vision import VisionClient
from tiresias.config import Settings
from tiresias.contracts import IntentKind

load_dotenv(".env.local")
load_dotenv(".env")

logger = logging.getLogger("tiresias.agent")
settings = Settings()
AGENT_NAME = os.environ.get("AGENT_NAME", settings.agent_name)
server = AgentServer()
_VAD = silero.VAD.load()
_STATUS_IMAGE = Image.new("RGB", (320, 240), color=(16, 24, 40))
_draw = ImageDraw.Draw(_STATUS_IMAGE)
_draw.rectangle((20, 20, 300, 220), outline=(120, 180, 255), width=3)
_draw.text((70, 110), "Tiresias", fill=(220, 230, 255))
_STATUS_FRAME = rtc.VideoFrame(320, 240, rtc.VideoBufferType.RGB24, _STATUS_IMAGE.tobytes())


class TiresiasAgent(Agent):
    def __init__(self, on_user_text) -> None:
        super().__init__(
            instructions=(
                "You are Tiresias, a controlled FaceTime label assistant. "
                "Do not invent free-form answers. Application policy owns every spoken line."
            )
        )
        self._on_user_text = on_user_text
        self._last_handled = ""

    async def on_user_turn_completed(self, turn_ctx, new_message) -> None:
        text = ""
        content = getattr(new_message, "content", None)
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            text = " ".join(str(part) for part in content if part)
        text = (text or getattr(new_message, "text_content", "") or "").strip()
        if text and text != self._last_handled:
            self._last_handled = text
            self._on_user_text(text)
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
    if not settings.gemini_api_key:
        return None
    _VISION = VisionClient(
        settings.gemini_api_key,
        model=settings.gemini_model,
        timeout_seconds=settings.vision_timeout_seconds,
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
    )
    return _INTENT


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
        frame_max_age_ms=max(settings.frame_max_local_age_ms, settings.visual_evidence_max_age_ms),
    )
    pending_prompt_id: str | None = None
    sample_state = {"last": 0.0}
    vision_budget = {"left": settings.max_vision_requests_per_call}
    handled_texts: set[str] = set()

    session = AgentSession(
        stt=elevenlabs.STT(
            model=settings.elevenlabs_stt_model,
            api_key=key,
            language_code="en",
        ),
        tts=elevenlabs.TTS(
            model=settings.elevenlabs_tts_model,
            voice_id=settings.elevenlabs_voice_id,
            api_key=key,
            voice_settings=_TTS_VOICE_SETTINGS,
            apply_text_normalization="on",
        ),
        vad=_VAD,
    )

    async def speak(text: str, *, interruptible: bool = True) -> None:
        try:
            await session.say(text, allow_interruptions=interruptible)
        except Exception:
            logger.exception("speak failed: %s", text[:80])

    async def run_vision(stage: str, revision: int) -> None:
        loop = asyncio.get_running_loop()
        vision = await loop.run_in_executor(None, _get_vision)
        if vision is None:
            await speak("Vision isn't set up yet.")
            return
        if vision_budget["left"] <= 0:
            await speak("I've used my vision budget for this call. Ask a person to look.")
            return
        frame = buffer.best(settings.visual_evidence_max_age_ms, time.monotonic())
        if frame is None:
            await speak("That view's gone. Hold it still and try again.")
            return
        vision_budget["left"] -= 1
        try:
            observation = await loop.run_in_executor(
                None,
                lambda: vision.analyze_frame(frame, controller.task.target),
            )
        except Exception:
            logger.exception("vision analysis failed")
            await speak("Not sure on this one. Hold it steady, or ask a person.")
            return
        controller.set_time(time.monotonic())
        events = controller.complete_inflight(
            revision,
            observation,
            stage,
            analyzed_frame=frame,
        )
        for event in events:
            await speak(event.text)

    def handle_user_text(text: str) -> None:
        cleaned = text.strip()
        if not cleaned:
            return
        key_text = cleaned.lower()
        if key_text in handled_texts:
            return
        # Open listening as soon as audio exists so commands are not dropped
        # while waiting for chert_bridge_ready metadata.
        lifecycle.on_caller_audio(epoch)
        if lifecycle.accept_audio("caller", cleaned) is None:
            return
        handled_texts.add(key_text)
        logger.info("user transcript: %s", cleaned[:120])
        classifier = _get_intent_classifier()

        def classify():
            return classifier.route(cleaned, controller.task, pending_prompt_id)

        async def route_and_act() -> None:
            loop = asyncio.get_running_loop()
            intent = await loop.run_in_executor(None, classify)
            logger.info("routed intent: %s", intent.kind.value)
            controller.set_time(time.monotonic())
            events = controller.handle(intent)
            for event in events:
                await speak(event.text)
            if intent.kind in {IntentKind.FIND_TARGET, IntentKind.CHANGE_TARGET, IntentKind.CHECK}:
                revision = controller.inflight_revision
                if revision is not None:
                    stage = "recheck" if intent.kind == IntentKind.CHECK else "candidate"
                    await run_vision(stage, revision)

        asyncio.create_task(route_and_act())

    @session.on("user_input_transcribed")
    def _on_transcript(ev) -> None:
        text = getattr(ev, "transcript", None) or getattr(ev, "text", "") or ""
        is_final = getattr(ev, "is_final", True)
        if not text:
            return
        if not is_final:
            logger.info("interim transcript: %s", text[:80])
            return
        handle_user_text(text)

    def _link_bridge(participant: rtc.RemoteParticipant) -> None:
        identity = participant.identity or ""
        if not identity.startswith("chert-bridge"):
            return
        room_io_obj = getattr(session, "_room_io", None)
        if room_io_obj is not None:
            room_io_obj.set_participant(identity)
            logger.info("linked room io to %s", identity)

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
            asyncio.create_task(_consume_video(track, buffer, epoch, sample_state))
        if name == CALLER_AUDIO_TRACK or track.kind == rtc.TrackKind.KIND_AUDIO:
            lifecycle.on_caller_audio(epoch)
            logger.info("caller audio track ready")

    ctx.room.on("track_subscribed", _on_track)
    ctx.room.on("participant_connected", _on_participant)

    async def wait_bridge_ready() -> None:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            meta = ctx.room.metadata or ""
            if "chert_bridge_ready" in meta:
                greeting = lifecycle.on_bridge_ready(epoch)
                if greeting:
                    await speak(greeting, interruptible=False)
                return
            await asyncio.sleep(0.1)
        greeting = lifecycle.on_bridge_ready(epoch)
        if greeting:
            await speak(greeting, interruptible=False)

    await session.start(
        agent=TiresiasAgent(handle_user_text),
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
    for participant in ctx.room.remote_participants.values():
        _link_bridge(participant)
    asyncio.create_task(wait_bridge_ready())
    await _publish_status_video(ctx)


async def _consume_video(track: rtc.RemoteVideoTrack, buffer: FrameBuffer, session_id: str, sample_state: dict) -> None:
    stream = rtc.VideoStream(track)
    loop = asyncio.get_running_loop()
    async for event in stream:
        now = time.monotonic()
        if now - sample_state["last"] < 0.5:
            continue
        sample_state["last"] = now
        frame = event.frame
        try:
            argb = frame.convert(rtc.VideoBufferType.RGBA)

            def encode() -> tuple[bytes, int, int]:
                from tiresias.agent.media import JPEG_QUALITY, MAX_EDGE

                image = Image.frombytes("RGBA", (argb.width, argb.height), bytes(argb.data)).convert("RGB")
                image.thumbnail((MAX_EDGE, MAX_EDGE))
                import io

                out = io.BytesIO()
                image.save(out, format="JPEG", quality=JPEG_QUALITY, optimize=True)
                return out.getvalue(), image.width, image.height

            jpeg, width, height = await loop.run_in_executor(None, encode)
            buffer.push(
                IncomingFrame(
                    session_id=session_id,
                    track_name=CALLER_VIDEO_TRACK,
                    participant_kind="caller",
                    jpeg_bytes=jpeg,
                    width=width,
                    height=height,
                    received_monotonic=time.monotonic(),
                    received_at=time.time(),
                    camera_region=(0, 0, width, height),
                    scene_epoch=int(time.time()) // 30,
                )
            )
        except Exception:
            logger.exception("failed to ingest caller frame")


async def _publish_status_video(ctx: JobContext) -> None:
    source = rtc.VideoSource(320, 240)
    track = rtc.LocalVideoTrack.create_video_track("tiresias-status", source)
    options = rtc.TrackPublishOptions()
    options.source = rtc.TrackSource.SOURCE_CAMERA
    await ctx.room.local_participant.publish_track(track, options)

    async def pump() -> None:
        while True:
            source.capture_frame(_STATUS_FRAME)
            await asyncio.sleep(1.0)

    asyncio.create_task(pump())


def main() -> None:
    cli.run_app(server)


if __name__ == "__main__":
    main()
