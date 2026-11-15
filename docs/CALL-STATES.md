# Accessible call states and Tiresias artwork

The worker now shows listening, thinking and speaking states and gives brief
spoken feedback when a caller interrupts. The existing website uses the same
Higgsfield-generated character. No avatar-generation API runs during a call.

## Behavior

- Stop, wait, hold on, pause and listen cancel current work/output, then confirm
  “I'm listening” after caller silence. Explicit pause confirmations bypass the
  four-second reminder cooldown.
- A meaningful replacement question can receive “Got it.” A slower new visual
  answer gets “Taking a look” after 1.5 seconds; acknowledged label work can get
  “Still checking” after another 3.5 seconds. Fast answers cancel pending cues.
- Started short cues finish before an answer. New turns/disconnect cancel them.
  Cues enter neither application conversation history nor SDK chat context.
  Cue audio does not count as first answer audio in latency telemetry.
- Positive backchannels keep the answer running. Raw STT still has no command
  side effects; completed user turns own dispatch.
- Avatar speaking follows SDK audio state, thinking follows owned application
  work, and detected caller speech displays listening immediately. Stale task
  completion cannot reset the current request's state. Caller audio/commands
  connect feedback before delayed bridge-ready metadata; greeting remains gated.

LiveKit 1.8 defaults to a three-second AEC warmup that replaces caller PCM with
silence during initial output. Real early-interruption tests exposed clipped or
missing “Wait” / “Stop talking” inputs. `aec_warmup_duration=0` preserves those
words. The regression invokes the installed SDK's actual `push_audio`, verifying
nonzero caller audio reaches STT during initial agent speech. This preserves the
existing deterministic interruption policy. FaceTime/Chert speakerphone echo
suppression still needs the owner's handset check.

## Character files

Higgsfield GPT Image 2.6 generated an original ceramic oracle character and three
reference-based native GIF loops. Each completed generation cost 0.5 existing
credit, within the owner's approved **2-credit total**; balance afterward: **8**.
No purchase, trial activation or subscription change was performed.

| Asset in static/avatar | Generation job | Actual output |
| --- | --- | --- |
| tiresias.png | baea7b7f-6208-48e3-8e7f-f66c360a94f3 | 1024×1024, 1,203,783 bytes |
| listening.gif | e784f641-539d-425b-aff8-f82ccfd966c8 | 512×512, 16 frames, 1.6 seconds |
| thinking.gif | 9997f033-35ff-4519-b500-c5a5893260d5 | 512×512, 16 frames, 1.6 seconds |
| speaking.gif | d982200b-9678-42d0-a40a-f50b3fe5bbc4 | 512×512, 16 frames, 1.6 seconds |
| tiresias.webp | Optimized locally from the master PNG | 640×640, 22,976 bytes |

The initial free-allowance master job
`13a6a539-3a81-4242-bfed-da668865db50` remained waiting when the owner approved
the credit queue. It is unused and incurred no credit spend; it was not resubmitted
as an unknown-outcome request or automatically cancelled.

The call renderer decodes/caches bounded loops off-loop and publishes 480×640
at approximately 10 fps. Rendering measured about 1.06 ms per frame locally;
this is not network video latency. Missing loops use the master still; absent
artwork uses the procedural fallback. Video errors never disable voice. Tasks
and video source close on disconnect. Speaking motion is a state animation,
not phoneme-level lip synchronization.

The sign-in/register pages and signed-in FaceTime card show the optimized still.
Voice preview switches to the speaking GIF, then restores the still on pause,
end or error. Reduced motion keeps the still throughout. Asset-derived versions
include artwork, and both package/deployment allowlists include these files.

## Verification and activation — November 15, 2026

- Full test suite: **187 passed**, 33.61 seconds. New behavior regressions were
  watched fail before fixes. Fresh review's early-metadata issue and optional
  website image fallback are fixed; follow-up review accepted the AEC fix.
- Actual preview worker: early “Stop talking” returned “I'm listening,” then two
  normal visual questions returned correct counts. A separate final overlap
  test returned both correct counts with “yes” spoken during playback.
- Actual normal worker: early stop acknowledgment and two strict LEMON label
  reads passed. Returned video: **449 frames**, **111 different samples**,
  **480×640**. Captured video and state contact sheet were visually inspected.
- Earlier attempts included a greeting timeout, short control clipping and
  intermittent later-answer timeouts. Clipping was traced to SDK warmup and
  fixed. The other transient failures were not conclusively attributed; do not
  claim the final runs prove all transport/provider failures are eliminated.
- Browser: desktop/mobile layout inspected; public 390px view loads the artwork
  with no horizontal overflow. Local real voice preview recorded speaking GIF
  then still; reduced-motion playback recorded only the still.
- Web release: `20261115t130709z`; archive SHA256
  `c6f4d42fd28adc7a376392f1e43cfbc889e88530ded7b63687d3ba63d214abac`.
  Public URL: https://tiresias.ink. Current worker logs:
  `data/worker-accessible-states.stdout.log` / `.stderr.log`.

Local evidence stays ignored: `data/call-states-final-preview.json`,
`data/backchannel-smoke-results.json`, `data/call-states-smoke-results.json`,
`data/tiresias-higgsfield-preview.{gif,png}` and browser screenshots. These tests
use synthetic media in isolated LiveKit rooms; they exclude the actual handset
and FaceTime transport. Final owner check: speakerphone greeting interruption,
no self-transcription of greeting echo, and correct animation on the handset.
