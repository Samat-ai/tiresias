from __future__ import annotations

import io
from dataclasses import dataclass

from PIL import Image

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
        # Prefer larger JPEG payload among the newest few samples: motion-blur /
        # near-empty frames compress smaller than sharp label text.
        window = fresh[-min(4, len(fresh)) :]
        return max(window, key=lambda frame: (len(frame.jpeg_bytes), frame.received_monotonic))

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
