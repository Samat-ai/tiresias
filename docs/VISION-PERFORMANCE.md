# Vision optimization evidence — November 15, 2026

Implementation follows the useful latency patterns in the owner's Downloads
`fast_vision_architecture_gemini_3_implementation_guide.md`, adapted to the
existing Python/Vertex worker. Caller-linked preferences remain intact.

## Changes

- One complete spoken answer can start before Gemini's trailing metadata ends.
  Only validated, bounded speech crosses to TTS; split/malformed delimiters,
  JSON metadata and truncated fragments are tested. Cancelled requests cannot
  deliver late speech. Structured label matches still pass the policy gate.
- Clear scene/counting questions use LOW media resolution and a 768-pixel JPEG;
  text reading and ambiguous follow-ups retain the original detailed image and
  HIGH resolution. This uses Google's documented
  [media-resolution controls](https://ai.google.dev/gemini-api/docs/generate-content/media-resolution).
- Frames receive gradient-based sharpness scores in a background thread.
  Recent selection is limited to 700 ms behind the newest frame, a similar
  view and the same scene epoch. Explicit label rechecks always use the newest
  frame. JPEG byte count is no longer treated as focus quality.
- A continuously draining ingress task timestamps incoming frames before a
  capacity-one processing queue. Conversion and scoring do not block audio;
  disconnect cancels capture and closes the RTC stream. Sampling is about 3 fps.
- A metadata GET warms authentication while waiting for a call, without vision
  inference or sending an image. Gemini 3.5 Flash-Lite remains default; 3.8
  was slower in these tests. Explicitly configured 3.8 uses supported LOW thinking.
- Smaller label JSON avoids unused model-generated fields and frame-ID echo;
  the application pins the response to the frame it actually supplied.
- The performance dashboard distinguishes model/text readiness, SDK answer audio
  start and speech duration. A short grace period suppresses an acknowledgment
  that STT finalizes just after a faster answer finishes.

## Measurements

Generated images only: two Pepsi cans among a distractor can, and a small-print
batch/date label. These are narrow correctness checks, not general OCR scores.
Sequential requests used the existing Vertex project and global endpoint.

| Test | Samples correct | Median text-ready time |
| --- | --- | --- |
| Original conversation JSON, before edits | 4/4 | 1272 ms |
| Finished production conversation stream, with warm-up | 6/6 | 729 ms |
| Finished compact structured label read | 3/3 | 962 ms |

The measured conversation median fell by about 43%. Sample count is small;
network conditions, answer length and changed request format also contribute.
The initial series contains a cold first request. Warm-up itself took
1197–1680 ms and happens before the user's visual question in the waiting room.

On the counting image, submitted scene JPEG size fell from 46959 to 18947 bytes.
The detailed label image remains 50112 bytes. Frame-feature calculation took
about 4.2 ms on this computer (eight local samples); it is not on the audio loop.

These numbers measure model text readiness, **not total microphone-to-speaker
latency**. STT endpointing, quiet gating, ElevenLabs, WebRTC and phone networking
add time. The guide's 650 ms end-to-end target has not been established.

Artifacts remain ignored/local: `data/vision-benchmark-before.json` and
`data/vision-benchmark-after.json`. `scripts/benchmark_vision.py --production`
measures the current implementation; its `current_json` mode now calls the tuned
JSON method and must not be mistaken for regenerating the original baseline.
Production row `image_bytes` describes the source frame; actual submitted sizes
above were measured separately through `vision_image_bytes`.

## Validation and remaining limits

Fresh review identified malformed speech fallback, missed OCR wording and falsely
fresh queued frames. Regression tests reproduced all three before their fixes.
The latest full suite passes 173 tests. The earlier live overlap run produced a
correct first answer but timed out on the repeated turn; its timeout cause was
not established. On the final worker, both repeated counting/backchannel turns
passed without the extra social prompt, followed by two successful label reads.
Model speech readiness for that final conversation was 683 and 886 ms. SDK answer
audio started 1059 and 1263 ms after the completed caller turn; this excludes STT
endpointing and transport to the phone. These real media tests use isolated
LiveKit rooms and generated input; they do not replace handset verification.

No cross-call spatial memory, raw camera storage, inferred physical distances or
periodic hazard speech was added. The synchronous provider thread may remain in
a network read until its transport timeout after cancellation, but its result
cannot publish to the cancelled turn. A real handset comparison remains the
final usability check for focus, lighting, latency and conversational flow.
