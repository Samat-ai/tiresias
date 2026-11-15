import asyncio
from types import SimpleNamespace

import pytest
from PIL import Image

from tiresias.agent import avatar, main as runtime
from tiresias.agent.feedback import CallFeedback
from tiresias.agent.turns import QuietGate


def test_downloaded_loop_follows_state_and_frame_durations(tmp_path,monkeypatch):
    Image.new('RGB',(64,64),'white').save(tmp_path/'tiresias.png')
    red,blue=Image.new('RGB',(64,64),'red'),Image.new('RGB',(64,64),'blue')
    red.save(tmp_path/'speaking.gif',save_all=True,append_images=[blue],duration=[100,200],loop=0)
    monkeypatch.setattr(avatar,'ASSET_DIR',tmp_path)
    renderer=avatar.AvatarRenderer()
    assert renderer.render('speaking',0.05).getpixel((240,300))==(255,0,0)
    assert renderer.render('speaking',0.15).getpixel((240,300))==(0,0,255)
    assert renderer.render('speaking',0.35).getpixel((240,300))==(255,0,0)
    assert renderer.render('listening',0.15).getpixel((240,300))==(255,255,255)


@pytest.mark.asyncio
async def test_published_animation_stops_and_closes_video_source(monkeypatch):
    frames,closed=[],[]
    class Source:
        def __init__(self,*args): pass
        def capture_frame(self,frame): frames.append((frame.width,frame.height))
        async def aclose(self): closed.append(True)
    async def publish(*args): pass
    async def say(text): pass
    monkeypatch.setattr(runtime.rtc,'VideoSource',Source)
    monkeypatch.setattr(runtime.rtc.LocalVideoTrack,'create_video_track',lambda *args:object())
    feedback=CallFeedback(QuietGate(0),say)
    ctx=SimpleNamespace(room=SimpleNamespace(local_participant=SimpleNamespace(publish_track=publish)))
    task=await runtime._publish_status_video(ctx,feedback)
    await asyncio.sleep(0.25)
    feedback.close()
    task.cancel()
    await asyncio.gather(task,return_exceptions=True)
    count=len(frames)
    await asyncio.sleep(0.15)
    assert len(frames)==count and count>=2
    assert all(size==(480,640) for size in frames)
    assert closed==[True]
