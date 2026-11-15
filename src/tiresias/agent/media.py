from __future__ import annotations

import io
from dataclasses import dataclass

from PIL import Image,ImageChops,ImageStat

from tiresias.contracts import FrameRef, new_id

CALLER_VIDEO_TRACK = "facetime-remote-video"
CALLER_AUDIO_TRACK = "facetime-remote-audio"
MAX_EDGE = 1280
JPEG_QUALITY = 90
MAX_BYTES = 1_000_000
DEFAULT_MAX_FRAMES = 8


@dataclass
class IncomingFrame:
    session_id: str
    track_name: str
    participant_kind: str
    jpeg_bytes: bytes
    width: int
    height: int
    received_monotonic: float
    received_at: float
    source_timestamp: float | None = None
    scene_epoch: int = 0
    muted: bool = False
    frozen_camera: bool = False
    ui_only_change: bool = False
    camera_region: tuple[int, int, int, int] | None = None
    sharpness: float | None = None
    scene_signature: tuple[int,...] = ()


class FrameBuffer:
    def __init__(self, session_id: str, max_frames: int = DEFAULT_MAX_FRAMES) -> None:
        self.session_id = session_id
        self.max_frames = max_frames
        self._frames: list[FrameRef] = []
        self._pending: FrameRef | None = None
        self._pending_expires_at: float | None = None

    def push(self, incoming: IncomingFrame) -> FrameRef | None:
        if incoming.participant_kind == "agent":
            return None
        if incoming.track_name != CALLER_VIDEO_TRACK:
            return None
        if incoming.muted or incoming.ui_only_change or incoming.frozen_camera:
            return None
        if incoming.camera_region is None:
            return None
        encoded, width, height = _limit_jpeg(incoming.jpeg_bytes, incoming.width, incoming.height)
        frame = FrameRef(
            frame_id=new_id(),
            session_id=self.session_id,
            received_at=incoming.received_at,
            received_monotonic=incoming.received_monotonic,
            source_timestamp=incoming.source_timestamp,
            jpeg_bytes=encoded,
            width=width,
            height=height,
            scene_epoch=incoming.scene_epoch,
            track_name=incoming.track_name,
            sharpness=incoming.sharpness,
            scene_signature=incoming.scene_signature,
        )
        self._frames.append(frame)
        if len(self._frames) > self.max_frames:
            self._frames = self._frames[-self.max_frames :]
        return frame

    def get(self, frame_id: str) -> FrameRef | None:
        for frame in reversed(self._frames):
            if frame.frame_id == frame_id:
                return frame
        return None

    def latest(self, max_age_ms: int, now_monotonic: float) -> FrameRef | None:
        return self.best(max_age_ms, now_monotonic, prefer_sharp=False)

    def best(self, max_age_ms: int, now_monotonic: float, *, prefer_sharp: bool = True) -> FrameRef | None:
        fresh = [
            frame
            for frame in self._frames
            if (now_monotonic - frame.received_monotonic) * 1000 <= max_age_ms
        ]
        if not fresh:
            return None
        if not prefer_sharp:
            return fresh[-1]
        latest=fresh[-1]
        if latest.sharpness is None or not latest.scene_signature:
            return latest
        window=[frame for frame in fresh[-4:] if frame.sharpness is not None
                and latest.received_monotonic-frame.received_monotonic<=0.7
                and frame.scene_epoch==latest.scene_epoch
                and same_view(frame.scene_signature,latest.scene_signature)]
        chosen=max(window,key=lambda frame:(frame.sharpness,frame.received_monotonic),default=latest)
        return chosen if chosen.sharpness>latest.sharpness*1.15 else latest

    def hold_pending(self, frame: FrameRef, expires_at: float) -> None:
        self._pending = frame
        self._pending_expires_at = expires_at

    def pending(self, now_monotonic: float) -> FrameRef | None:
        if self._pending is None or self._pending_expires_at is None:
            return None
        if now_monotonic > self._pending_expires_at:
            self._pending = None
            self._pending_expires_at = None
            return None
        return self._pending

    def clear_pending(self) -> None:
        self._pending = None
        self._pending_expires_at = None

    def clear(self) -> None:
        self._frames.clear()
        self.clear_pending()


def _limit_jpeg(raw: bytes, width: int, height: int) -> tuple[bytes, int, int]:
    if width <= MAX_EDGE and height <= MAX_EDGE and len(raw) <= MAX_BYTES:
        return raw, width, height
    image = Image.open(io.BytesIO(raw))
    image = image.convert("RGB")
    image.thumbnail((MAX_EDGE, MAX_EDGE))
    out = io.BytesIO()
    image.save(out, format="JPEG", quality=JPEG_QUALITY)
    data = out.getvalue()
    if len(data) > MAX_BYTES:
        raise ValueError("frame exceeds 1 MB after encoding")
    return data, image.width, image.height


def frame_features(image: Image.Image) -> tuple[float,tuple[int,...]]:
    """Cheap gradient energy and scene signature; run outside the media loop.

    A focus heuristic, not a guarantee of readable text. Compression size and
    image entropy are not used as substitutes for actual pixel gradients.
    """
    gray=image.convert('L')
    signature=tuple(gray.resize((16,9),Image.Resampling.BILINEAR).tobytes())
    gray.thumbnail((256,144))
    width,height=gray.size
    if width<2 or height<2:
        return 0.0,signature
    dx=ImageChops.difference(gray.crop((1,0,width,height)),gray.crop((0,0,width-1,height)))
    dy=ImageChops.difference(gray.crop((0,1,width,height)),gray.crop((0,0,width,height-1)))
    score=ImageStat.Stat(dx).rms[0]**2+ImageStat.Stat(dy).rms[0]**2
    return score,signature


def same_view(first: tuple[int,...],second: tuple[int,...]) -> bool:
    return bool(first and len(first)==len(second) and
                sum(abs(a-b) for a,b in zip(first,second))/len(first)<=14)


def vision_image_bytes(frame: FrameRef,*,reading: bool) -> bytes:
    if reading or max(frame.width,frame.height)<=768:
        return frame.jpeg_bytes
    image=Image.open(io.BytesIO(frame.jpeg_bytes)).convert('RGB')
    image.thumbnail((768,768))
    output=io.BytesIO()
    image.save(output,'JPEG',quality=82)
    return output.getvalue()
