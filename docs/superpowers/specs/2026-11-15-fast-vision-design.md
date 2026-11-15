# Faster, clearer FaceTime vision

The owner confirmed caller-linked settings work and requested better/faster vision
using Downloads/fast_vision_architecture_gemini_3_implementation_guide.md.

## Evidence and approach

Existing implementation already continuously captures JPEG video, uses minimal
thinking with Gemini 3.5 Flash-Lite and ElevenLabs Flash, and avoids database writes
on the answer path. Real recent FaceTime model stages average 1412 ms for
conversation and 1571 ms for label vision; TTS first audio averages 190 ms.

A synthetic benchmark compared current JSON, tuned JSON and speech-first streaming
on counting two Pepsi cans among distractors and reading a small batch/date label.
Two repetitions per case: Flash-Lite current JSON median speech-ready 1272 ms;
tuned JSON 1079 ms; speech-first 674 ms, all 4/4 correct. Gemini 3.8 low-thinking
was slower (speech-first median 2086 ms) with no accuracy improvement on these
cases. These are small synthetic model-readiness measurements, not handset audio
latency or a general accuracy guarantee.

Implement the measured fast path in Python. Keep Flash-Lite as default; adapt
thinking level correctly for an explicitly selected 3.7/3.8 or Pro model. Use low
media resolution / 768-pixel JPEG for scene questions and high resolution with
the original detailed image for text questions and all label checks. Stream one
bounded, complete spoken answer before its trailing `|||` metadata; never speak
JSON or partial fragments. Label match policy continues to wait for validated
structured observations. Cancelled turns cannot publish late speech. API failures
remain service failures, not blurry-camera observations.

Continuously sample at approximately 3 fps in a bounded RTC queue. Compute an
image-gradient sharpness score and small scene signature off the media event loop;
select only a recent sharper frame from the same view. Remove JPEG-byte-count as
a sharpness proxy. Explicit rechecks use the newest frame so an old readable label
cannot confirm a changed selection. Retain capture arrival time before processing.

## Alternatives and boundaries

Directly copying the JS guide would replace a working Python/Vertex stack and add
unsupported assumptions. Its entropy score does not guarantee focus; its memory
query is not scoped by call/user; its image storage would change privacy behavior;
its firstAudioLatencyMs measures text readiness. Its monocular distance estimates
and always-on hazard speech are not justified by this change. No new camera-image
storage, cross-call spatial memory, second-frame payloads or background warnings.
Those add cost/latency or require separate evidence. Keep current call-local text
context and precise left/right wording without invented physical distances.

## Acceptance

Pin stream chunk boundaries, missing/malformed delimiters, cancellation, tail
failure after speech and frame freshness with tests. Verify blur scoring using
sharp/blurred generated images. Measure real provider image sizes/readiness and
actual completed-turn-to-audio separately. Run the full suite and counting/read
smokes after restarting the worker; preserve the caller-link feature. The owner
performs the final handset comparison. A 650 ms end-to-end result is not promised.
