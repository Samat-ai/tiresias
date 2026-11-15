"""Exercise the real vision/config/policy path with a generated test label.

Run with the media extra installed. Sends only a synthetic label to Gemini.
No camera images or credentials are printed or saved.
"""
from __future__ import annotations

import io
import time

from PIL import Image, ImageDraw, ImageFont

from tiresias.agent.media import CALLER_VIDEO_TRACK
from tiresias.agent.policy import decide, speech_for
from tiresias.agent.vision import VisionClient
from tiresias.config import Settings
from tiresias.contracts import FrameRef, TargetSpec, TaskContext


def main() -> None:
    settings = Settings()
    image = Image.new("RGB", (1280, 720), "white")
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("arial.ttf", 76)
    except OSError:
        font = ImageFont.load_default(size=76)
    draw.multiline_text((80, 170), "LEMON\nSPARKLING WATER\n330 ml", font=font, fill="black", spacing=24)
    output = io.BytesIO()
    image.save(output, "JPEG", quality=90)
    client = VisionClient(settings.gemini_api_key, settings.gemini_model, settings.vision_timeout_seconds,
                          **settings.gemini_backend_options())
    task = TaskContext(
        session_id="probe", task_id="probe", generation=0, analysis_revision=1,
        turn_id="probe", target=TargetSpec(requested_label="lemon sparkling water", required_terms=["lemon", "sparkling", "water"]),
    )
    frame = FrameRef(
        frame_id="synthetic-label", session_id="probe", received_at=time.time(),
        received_monotonic=time.monotonic(), jpeg_bytes=output.getvalue(), width=1280,
        height=720, scene_epoch=1, track_name=CALLER_VIDEO_TRACK,
    )
    started = time.monotonic()
    observation = client.analyze_frame(frame, task.target)
    elapsed = time.monotonic() - started
    decision = decide(task, frame, observation, stage="recheck", now_monotonic=time.monotonic(), max_age_ms=20_000)
    print(f"model={client.model} elapsed_seconds={elapsed:.2f} quality={observation.quality.value}")
    print("visible_text:", observation.visible_text)
    print("decision:", decision.kind.value)
    print("speech:", speech_for(decision, task))
    if decision.kind.value != "MATCH":
        raise SystemExit("FAIL: synthetic label was not matched")


if __name__ == "__main__":
    main()
