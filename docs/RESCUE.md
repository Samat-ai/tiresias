# Demo rescue assessment — November 15, 2026

**Latest update — ADC unblocked vision:** Vertex AI using the existing local ADC
login successfully read the generated label on `gemini-3.5-flash-lite` in
**2.26 seconds**, with `READABLE` quality and a correct `MATCH`. The local
configuration now selects Vertex AI in the global location. No new API key or
credentials file was needed. All **75 tests pass**. The AI Studio prepaid balance
is still separate; its earlier 402 no longer blocks the selected backend.
Real FaceTime camera quality and audio delivery still require a handset test.

## Current evidence

The core FaceTime label-reading path is salvageable. It had several independently
verifiable defects; changing TTS styling alone cannot solve them.

- The real Gemini request returned `400 INVALID_ARGUMENT` with `thinking_budget=0`.
  Changing only this field to `thinking_level="minimal"` returned valid JSON in
  **0.74 seconds** on `gemini-3.5-flash-lite`.
- A subsequent real image request returned **402 RESOURCE_EXHAUSTED** with the
  explicit message that prepaid credits are depleted. Restore billing or replace
  the local key with one from a funded project before claiming vision works.
  Do not put keys in chat or commit them.
- All **71 tests passed**, including database tests and new runtime tests that
  exercise STT event routing through controller/vision to spoken output with fake
  providers. Those tests do not prove FaceTime audio delivery or real camera OCR.
- The previous handoff's statement that there are no commits is stale: the repo
  already has an initial commit and a handoff commit.
- The Devpost page could not be fetched by the research tool. The working deadline
  is the owner's stated noon November 15 CST, not a newly verified event deadline.

## Root causes and changes

| Problem | Cause | Change |
| --- | --- | --- |
| Vision and some intent calls fail | Unsupported numeric thinking setting for Gemini 3 | Minimal thinking level for Gemini 3; retain budget setting for older models |
| API failures sound like bad camera quality | Vision client swallowed every exception and manufactured an unknown observation | Propagate errors to the runtime and speak a service error |
| Repeating “check this” stops working | Call-long set blacklists every previously heard phrase | Final STT events are the sole command source; remove both text blacklists |
| Delay before analysis | Acknowledgement playback finishes before vision begins | Run acknowledgement and vision concurrently, then speak the result |
| Old replies can continue after stop/new commands | Controller invalidation never canceled application tasks or TTS playback | Latest-turn cancellation plus LiveKit playback interruption |
| Wrong old item is checked | Largest JPEG from recent frames can beat the current frame | Analyze the latest frame with a two-second local freshness limit |
| “Read this” reports a mismatch | Matching policy expects a search target even when none exists | Read the visible label directly when no target was requested |
| Partial name called wrong product | Any missing required word is treated as contradictory evidence | Shared but incomplete target words yield uncertainty, with quoted text |
| “Pepsi can” fails on a readable PEPSI label | Packaging words are required as literal label text; “find me” leaves “me” in the target | Remove request filler and omit container words when a product name is available |
| Some camera tracks can be missed | Room subscriptions can arrive before handlers are installed | Also inspect existing track publications, with duplicate stream protection |
| “Slower” only changes acknowledgement | Controller speed never reaches ElevenLabs | Update the actual TTS voice speed |

The worker now logs image dimensions, payload size, capture age, analysis duration,
quality and text-span count. It does not save camera frames. These measurements
will distinguish weak FaceTime input from weak model output during the live test.
The restarted worker registered successfully with LiveKit and received a Chert
warm-room job. Actual handset audio and image recognition remain unverified.

## What remains unproven or incomplete

- Real camera image recognition after the billing change.
- FaceTime greeting and label speech reaching the handset consistently.
- Live interruption timing and handling of STT segmentation.
- Human conversation: the runtime still intentionally prevents free-form LLM
  responses. Intent classification plus fixed speech templates is not a
  conversational assistant. There is no conversation history or continuous
  visual understanding. Vision is requested by commands, not a background stream.
- Non-label object finding, including an unlabeled pen, remains outside the
  implemented product-label path. Do not present it as a general visual assistant.
- Ask-a-person is not connected to a live helper. The current consent prompt is
  an unfinished path, not a demo feature.

## Deadline order

1. Vertex ADC is now verified; no AI Studio top-up is needed for this backend.
   Run the generated-label probe below, then make a real
   FaceTime Video call. Verify one label, repeat the identical command, switch
   products, and stop a response. Keep the actual worker logs.
2. Fix any remaining camera/bridge defects using those measurements. Aim for a
   prompt acknowledgement and useful label speech without repeated camera advice.
3. Only after that gate, improve conversation in a bounded slice: one multimodal
   request per visual question, short answers grounded in the current image,
   recent conversation context, and deterministic stop/repeat controls. Compare
   against the working label path before replacing it. Avoid stacking another
   model round trip in front of vision.
4. Record the working demonstration and prepare the submission with several hours
   left. Include a correct-label read, a different product, and recovery from a
   difficult view. Describe limitations accurately.
5. Spend spare time on presentation or an already-working sponsor integration.
   Defer the portal, payments, subscription system and new deployment platforms.

## Commands

```powershell
# Complete local suite
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider

# Real Gemini request with a generated label; no private camera image is sent
.\.venv\Scripts\python.exe scripts\probe_vision.py

# Worker logs after the rescue restart
Get-Content data\worker.stderr.log -Tail 60
Get-Content data\worker.stdout.log -Tail 60
```

FaceTime Video line: **+1 702 510 9706**. Try “check this”, “check this” again
after changing the view, “find lemon sparkling water”, “try again”, and “stop”.
The synthetic probe verifies request compatibility and basic label extraction;
it is not a substitute for a real FaceTime call.

Provider thinking documentation: https://ai.google.dev/gemini-api/docs/thinking

## Vertex AI / ADC setup

The application supports both AI Studio keys and Vertex ADC. Select Vertex in
`.env.local`:

```dotenv
GOOGLE_GENAI_USE_VERTEXAI=true
GOOGLE_CLOUD_PROJECT=your-project-id
GOOGLE_CLOUD_LOCATION=global
```

ADC credentials already exist locally for this machine. On another machine,
install the Google Cloud CLI and run `gcloud auth application-default login`.
The selected project needs Cloud billing, the Vertex AI API, and permission to
call the model. A new AI Studio key is unnecessary. If using an existing
credentials JSON instead, set `GOOGLE_APPLICATION_CREDENTIALS` to its local path;
never paste or commit its contents. The backend deliberately ignores the Studio
key when Vertex is selected and does not silently fall back to Studio billing.
