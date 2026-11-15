"""Opt-in real-provider smoke test in an isolated LiveKit room.

Publishes a generated label and synthesized command to the running worker.
Verifies returned audio by transcribing it. This does not test Chert/FaceTime.
Creates and deletes only its own uniquely named room. Uses provider credits.
"""
from __future__ import annotations

import asyncio
import argparse
import io
import hashlib
import json
import time
import wave
from pathlib import Path
from uuid import uuid4

import httpx
from livekit import api, rtc
from PIL import Image, ImageDraw, ImageFont

from tiresias.config import Settings


async def main(*, conversation: bool = False, backchannel: bool = False, profile_code: str = '', profile_paused: bool = False, states: bool = False, warm_room: bool = False) -> None:
    settings = Settings()
    room_name = f"tiresias-smoke-{uuid4().hex[:10]}"
    service = api.LiveKitAPI(settings.livekit_url, settings.livekit_api_key, settings.livekit_api_secret)
    room = rtc.Room()
    tasks = []
    received = bytearray()
    audio_ready = asyncio.Event()
    result = {"room": room_name, "scope": "LiveKit + ElevenLabs STT/TTS + Vertex vision; excludes FaceTime", "warm_room_without_ready_metadata":warm_room}
    video_state={'frames':0,'digests':set(),'image':None,'last_sample':0}
    video_ready=asyncio.Event()

    async def consume_video(track):
        stream=rtc.VideoStream(track,format=rtc.VideoBufferType.RGB24,capacity=1)
        try:
            async for event in stream:
                video_ready.set()
                video_state['frames']+=1
                now=time.monotonic()
                if now-video_state['last_sample']<0.4:
                    continue
                video_state['last_sample']=now
                frame=event.frame
                image=Image.frombytes('RGB',(frame.width,frame.height),bytes(frame.data))
                video_state['image']=image
                video_state['dimensions']=[frame.width,frame.height]
                video_state['digests'].add(hashlib.sha256(image.tobytes()).hexdigest())
        finally:
            await stream.aclose()

    def save_video_sample(name):
        if video_state['image'] is not None:
            video_state['image'].save(Path('data')/f'call-state-{name}.png')

    async def consume(track):
        stream = rtc.AudioStream(track, sample_rate=16000, num_channels=1)
        try:
            async for event in stream:
                raw = bytes(event.frame.data)
                received.extend(raw)
                # Opus comfort noise is nonzero even when the agent is silent.
                samples = memoryview(raw).cast('h')
                if sum(abs(sample) for sample in samples) / max(1, len(samples)) > 200:
                    audio_ready.set()
        finally:
            await stream.aclose()

    @room.on("track_subscribed")
    def subscribed(track, publication, participant):
        if track.kind == rtc.TrackKind.KIND_AUDIO:
            tasks.append(asyncio.create_task(consume(track)))
        if track.kind == rtc.TrackKind.KIND_VIDEO and publication.name=='tiresias-status':
            tasks.append(asyncio.create_task(consume_video(track)))

    async def transcribe(client, raw):
        output = io.BytesIO()
        with wave.open(output, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)
            wav.writeframes(raw)
        response = await client.post(
            "https://api.elevenlabs.io/v1/speech-to-text",
            headers={"xi-api-key": settings.elevenlabs_key()},
            data={"model_id": "scribe_v2", "language_code": "en"},
            files={"file": ("synthetic-call-output.wav", output.getvalue(), "audio/wav")},
        )
        response.raise_for_status()
        return response.json().get("text", "")

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{settings.elevenlabs_voice_id}",
                params={"output_format": "pcm_16000"},
                headers={"xi-api-key": settings.elevenlabs_key()},
                json={"text": "How many Pepsi cans can you see?" if conversation else "Check this.",
                      "model_id": settings.elevenlabs_tts_model},
            )
            response.raise_for_status()
            command_audio = response.content
            pause_audio=b''
            if states:
                pause=await client.post(
                    f"https://api.elevenlabs.io/v1/text-to-speech/{settings.elevenlabs_voice_id}",
                    params={'output_format':'pcm_16000'},headers={'xi-api-key':settings.elevenlabs_key()},
                    json={'text':'Stop talking.','model_id':settings.elevenlabs_tts_model})
                pause.raise_for_status()
                pause_audio=pause.content
                result['pause_input_transcript']=await transcribe(client,pause_audio)
                if 'stop' not in result['pause_input_transcript'].lower():
                    raise RuntimeError('Synthetic pause command was not intelligible in offline STT')
            profile_audio = b''
            profile_parts = []
            if profile_code:
                profile_response = await client.post(
                    f"https://api.elevenlabs.io/v1/text-to-speech/{settings.elevenlabs_voice_id}",
                    params={"output_format": "pcm_16000"},headers={"xi-api-key": settings.elevenlabs_key()},
                    json={"text":"Use profile "+' '.join(profile_code),"model_id":settings.elevenlabs_tts_model},
                )
                profile_response.raise_for_status()
                profile_audio=profile_response.content
                if profile_paused:
                    digit_words=dict(zip('0123456789','zero one two three four five six seven eight nine'.split()))
                    for text in ['Use profile.',
                                 ' '.join(digit_words[d] for d in profile_code[:4]),
                                 ' '.join(digit_words[d] for d in profile_code[4:])]:
                        segment=await client.post(
                            f"https://api.elevenlabs.io/v1/text-to-speech/{settings.elevenlabs_voice_id}",
                            params={'output_format':'pcm_16000'},headers={'xi-api-key':settings.elevenlabs_key()},
                            json={'text':text,'model_id':settings.elevenlabs_tts_model})
                        segment.raise_for_status()
                        profile_parts.append(segment.content)
            backchannel_audio = b''
            if backchannel:
                yes = await client.post(
                    f"https://api.elevenlabs.io/v1/text-to-speech/{settings.elevenlabs_voice_id}",
                    params={"output_format": "pcm_16000"},
                    headers={"xi-api-key": settings.elevenlabs_key()},
                    json={"text": "Yes.", "model_id": settings.elevenlabs_tts_model},
                )
                yes.raise_for_status()
                backchannel_audio = yes.content
            await service.room.create_room(api.CreateRoomRequest(
                name=room_name, metadata=json.dumps({'chert_warm':True} if warm_room else {"chert_bridge_ready": True}),
                empty_timeout=60,
            ))
            token = api.AccessToken(settings.livekit_api_key, settings.livekit_api_secret).with_identity(
                f"chert-bridge-smoke-{uuid4().hex[:6]}"
            ).with_grants(api.VideoGrants(room_join=True, room=room_name)).to_jwt()
            await room.connect(settings.livekit_url, token)

            image = Image.new("RGB", (1280, 720), "white")
            draw = ImageDraw.Draw(image)
            font = ImageFont.truetype("arial.ttf", 76)
            if conversation:
                for left in [100, 450]:
                    draw.rounded_rectangle((left, 130, left+240, 610), radius=35, fill='#004b99')
                    draw.ellipse((left, 120, left+240, 180), fill='silver')
                    draw.text((left+12, 330), 'PEPSI', fill='white', font=ImageFont.truetype('arial.ttf', 65))
                # An unrelated person in view must not trigger sharing consent.
                draw.ellipse((960, 110, 1080, 230), fill='#555555')
                draw.rounded_rectangle((930, 240, 1110, 570), radius=40, fill='#555555')
            else:
                draw.multiline_text((80, 170), "LEMON\nSPARKLING WATER\n330 ml", font=font, fill="black", spacing=24)
            video_source = rtc.VideoSource(1280, 720)
            video = rtc.LocalVideoTrack.create_video_track("facetime-remote-video", video_source)
            video_options = rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_CAMERA)
            await room.local_participant.publish_track(video, video_options)
            audio_source = rtc.AudioSource(16000, 1)
            audio = rtc.LocalAudioTrack.create_audio_track("facetime-remote-audio", audio_source)
            await room.local_participant.publish_track(audio, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE))

            # Real microphones supply continuous audio, including silence. Gaps
            # in synthetic source timestamps can invalidate overlap/STT tests.
            input_frames = asyncio.Queue()

            async def pump_audio():
                while True:
                    queued = not input_frames.empty()
                    chunk = input_frames.get_nowait() if queued else bytes(640)
                    await audio_source.capture_frame(rtc.AudioFrame(chunk, 16000, 1, 320))
                    if queued:
                        input_frames.task_done()
                    await asyncio.sleep(0.02)

            async def play_input(pcm):
                for offset in range(0, len(pcm), 640):
                    input_frames.put_nowait(pcm[offset:offset + 640].ljust(640, b'\0'))
                await input_frames.join()
                await audio_source.wait_for_playout()

            tasks.append(asyncio.create_task(pump_audio()))

            async def pump():
                frame = rtc.VideoFrame(1280, 720, rtc.VideoBufferType.RGB24, image.tobytes())
                while True:
                    video_source.capture_frame(frame)
                    await asyncio.sleep(0.2)

            tasks.append(asyncio.create_task(pump()))
            await service.agent_dispatch.create_dispatch(api.CreateAgentDispatchRequest(
                room=room_name, agent_name=settings.agent_name,
            ))
            print("isolated room dispatched:", room_name, flush=True)
            if warm_room:
                await asyncio.wait_for(video_ready.wait(),20)
                await asyncio.sleep(2)
                result['greeting_before_ready']=audio_ready.is_set()
                if audio_ready.is_set():
                    raise RuntimeError('Agent spoke before the explicit Chert ready signal')
                ready_sent=time.monotonic()
                await service.room.update_room_metadata(api.UpdateRoomMetadataRequest(
                    room=room_name,metadata=json.dumps({'chert_bridge_ready':True})))
            await asyncio.wait_for(audio_ready.wait(), 10 if warm_room else 30)
            if warm_room:
                result['first_audio_after_ready_seconds']=round(time.monotonic()-ready_sent,3)
            if states:
                await asyncio.sleep(2)
                save_video_sample('greeting')
                await play_input(pause_audio+bytes(32000))
                await asyncio.sleep(5)
                pause_transcript=await transcribe(client,bytes(received))
                result['pause']={'command':'Stop talking.','transcript':pause_transcript,'passed':"listening" in pause_transcript.lower()}
                save_video_sample('listening')
                print(json.dumps({'pause':result['pause']}),flush=True)
            else:
                await asyncio.sleep(8)  # Let the greeting finish before the command.
            result["greeting_audio_bytes"] = len(received)
            received.clear()
            if profile_code:
                if profile_paused:
                    audio_ready.clear()
                    await play_input(profile_parts[0]+bytes(32000))
                    await asyncio.wait_for(audio_ready.wait(),10)
                    # Send the first digits during the spoken entry instructions.
                    await play_input(profile_parts[1]+bytes(32000))
                    await asyncio.sleep(3)
                    await play_input(profile_parts[2]+bytes(32000))
                else:
                    await play_input(bytes(32000)+profile_audio+bytes(96000))
                await asyncio.sleep(6)
                profile_transcript=await transcribe(client,bytes(received))
                result['profile_loaded']='loaded' in profile_transcript.lower()
                print(json.dumps({'profile_loaded':result['profile_loaded'],'transcript':profile_transcript}),flush=True)
                if not result['profile_loaded']:
                    raise RuntimeError('saved voice profile was not loaded')
                received.clear()

            # Two identical commands prove the running worker accepts retries.
            result["checks"] = []
            for number in range(2):
                received.clear()
                audio_ready.clear()
                started = time.monotonic()
                pcm = bytes(16000 * 2) + command_audio + bytes(16000 * 2 * (1 if backchannel else 3))
                await play_input(pcm)
                if states:
                    save_video_sample(f'answer-{number+1}')
                if backchannel:
                    # Say a one-word acknowledgement during returned speech.
                    await asyncio.wait_for(audio_ready.wait(), 10)
                    pcm_yes = backchannel_audio + bytes(16000 * 2)
                    await play_input(pcm_yes)
                await asyncio.sleep(12)
                transcript = await transcribe(client, bytes(received))
                if conversation:
                    lowered = transcript.lower()
                    passed = 'pepsi' in lowered and ('two' in lowered or '2' in lowered) and not any(
                        term in lowered for term in ['say yes', 'share this', 'helper']
                    )
                else:
                    passed = "lemon" in transcript.lower() and "sparkling" in transcript.lower()
                check = {"number": number + 1, "returned_audio_bytes": len(received),
                         "backchannel_injected": backchannel,
                         "transcript": transcript, "passed": passed,
                         "test_window_seconds": round(time.monotonic() - started, 2)}
                result["checks"].append(check)
                print(json.dumps(check), flush=True)
            result['video']={'frames':video_state['frames'],'different_samples':len(video_state['digests']),
                             'dimensions':video_state.get('dimensions')}
            result["passed"] = all(check["passed"] for check in result["checks"])
            if states:
                result['passed']=result['passed'] and result['pause']['passed'] and video_state['frames']>=10 and len(video_state['digests'])>=3
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await room.disconnect()
        try:
            await service.room.delete_room(api.DeleteRoomRequest(room=room_name))
        finally:
            await service.aclose()
            name = 'warm-room-smoke-results.json' if warm_room else ('call-states-smoke-results.json' if states else ('profile-paused-smoke-results.json' if profile_paused else ('backchannel-smoke-results.json' if backchannel else ('conversation-smoke-results.json' if conversation else 'live-smoke-results.json'))))
            path = Path('data') / name
            path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    if not result.get("passed"):
        raise SystemExit("FAIL: one or more live media checks failed; inspect the saved result.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--conversation', action='store_true', help='Test counting Pepsi cans with a person in view')
    parser.add_argument('--backchannel', action='store_true', help='Say yes during the returned answer')
    parser.add_argument('--profile-code',default='',help='Load an existing saved voice profile before checking the image')
    parser.add_argument('--profile-paused',action='store_true',help='Enter the profile code across pauses and during spoken instructions')
    parser.add_argument('--states',action='store_true',help='Interrupt the greeting with Stop talking and verify audible feedback and animated video')
    parser.add_argument('--warm-room',action='store_true',help='Warm silently, then publish the explicit Chert readiness signal')
    args = parser.parse_args()
    if args.profile_code and (not args.profile_code.isdigit() or len(args.profile_code)!=8):
        parser.error('profile code must contain eight digits')
    if args.profile_paused and not args.profile_code:
        parser.error('--profile-paused requires --profile-code')
    asyncio.run(main(conversation=args.conversation, backchannel=args.backchannel,profile_code=args.profile_code,profile_paused=args.profile_paused,states=args.states,warm_room=args.warm_room))
