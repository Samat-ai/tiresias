# Tiresias progress and track audit — November 15, 2026

## Latest call-driven update

The owner subsequently made a real FaceTime call: close-up Pepsi recognition
worked, but conversation and interruption behavior failed. The call logs showed
**1280×720** incoming frames, so the earlier isolated 320×180 observation does
not describe the actual handset feed. The question “How many Pepsi cans can you
see?” was incorrectly classified as ASK_PERSON; “yes” was then incorrectly
classified as UNSUPPORTED. This was a text-routing defect, not a person-in-view
consent requirement.

The runtime now dispatches only completed voice turns, uses ElevenLabs server VAD
with STT endpointing, and waits for caller silence before speaking. Automatic
audio-triggered interruption is disabled while input audio remains enabled during
playback; a completed meaningful new utterance explicitly interrupts playback.
Punctuated stop/repeat controls remain deterministic. Short acknowledgements do
not cancel pending work.
English/Russian code switching is supported by STT hints and direct question routing.

Unclassified questions now use one current-image Gemini request with recent text
context. A real-provider generated scene with two Pepsi cans and a person produced
correct counted answers twice, without sharing prompts. A real helper is still
not integrated; explicit helper requests now receive an honest unavailable reply.
The complete test suite is **94 passed**. The corrected continuous-microphone
smoke test injected “yes” during audible returned speech, verified complete
counted answers and then a repeated question: both passed. Output artifacts are
local/ignored (`data/conversation-smoke-results.json`,
`data/backchannel-smoke-results.json`). A real handset conversation retest is
still required; sponsor integrations remain as described below.

The rest of this audit records the earlier baseline and discovery sequence.

Audited at approximately 00:48 CST. User confirmed the initial Devpost entry was
submitted. Targets: General, Chert, Gemini, ElevenLabs, Tiger Data, Solana, Vultr,
and SpaceXSI. This is an evidence assessment, not an organizer eligibility ruling.

## Sources and deadline

- Original concept: `C:/Users/samat/Downloads/tiresias_hackuta_2026_master_blueprint.md`.
- Opening slides: `C:/Users/samat/Downloads/HackUTA 2026_compressed.pdf`, 80 pages.
  Read embedded text and visually inspected sponsor slides 44–70. Pages 40 and 42
  describe robustness, Odyssey theme, creativity, and a 3-minute presentation plus
  2-minute Q&A at 1 p.m. in UH.
- Live [Devpost overview](https://hackuta-8.devpost.com/) and
  [rules](https://hackuta-8.devpost.com/rules), read in browser November 15.
- [Chert challenge](https://www.trychert.com/uta) and
  [MLH event categories](https://www.mlh.com/events/hackuta-53).

**Deadline conflict:** PDF page 32 and the blueprint say midnight Sunday for
hacking end. Live Devpost explicitly says noon November 15, with edits until
11:59 a.m. Use the live rules as the working source and confirm any contrary
announcement with organizers. The initial Saturday 11:59 p.m. submission gate is
separate; the owner confirmed it was met.

Devpost requires title, description, a **30-second to 2-minute video**, and a
GitHub URL. Code must be uploaded before the deadline. Judging is in person.
Rules state a maximum of four hackers, one project per hacker, submission only
to this hackathon, and at least 70% of submitted code written by the team during
the hacking period. The repo cannot establish participant/history compliance;
the team must accurately attest to it.

## What the main feature actually proves

**77 tests passed**, with no skipped database tests, in a fresh complete run.
The tests cover policy, frames, speech, turn cancellation, ADC backend selection,
runtime routing, auth, reviews, and outbox behavior.

An isolated real LiveKit room was created, joined by a test caller publishing a
generated label image and synthesized speech, and dispatched to the running
`tiresias-agent`. This used real ElevenLabs STT, Vertex Gemini vision, and
ElevenLabs TTS. Returned audio was transcribed through ElevenLabs to check that
the caller actually received the label. Both identical “Check this” commands
passed. A second run after the audit fixes also passed both commands.

Example received speech: “Checking that. The label says lemon sparkling water,
330 milliliters.” Repeated command: “The label says lemon, sparkling water,
330 milliliters.”

Worker vision stage measurements were **1.44–2.69 seconds**, with fresh sampled
frames. The smoke script's 17.3-second observation windows include deliberate
silence, a fixed 12-second wait and output transcription; they are **not**
measured response latency. Evidence is in ignored local
`data/live-smoke-results.json` and worker logs. The reproducible tool is
`scripts/smoke_live_media.py`; it uses provider credits and deletes its own room.

**This does not test the actual Chert FaceTime bridge, handset camera, Siri,
speaker acoustics, noisy surroundings, or arbitrary small-print labels.** A real
iPhone call remains the final gate for the main product and the Chert demo.

## Findings in priority order

1. **Critical matching defect found and fixed:** “GOAT MILK” matched a request
   for “oat milk” because terms were matched as substrings. Required/excluded
   terms now use whole words; punctuation and case still work. Regression tests
   reproduced the failure before the change and pass after it. See
   `src/tiresias/agent/policy.py` and `tests/test_policy.py`.
2. **Image quality remains unresolved:** a 1280×720 generated source reached the
   worker as 320×180. Explicit high simulcast quality was requested and the live
   test repeated, but those samples stayed at 320×180. Do not claim this fixes
   camera resolution. Inspect actual FaceTime publication/source dimensions and
   sender encoding before changing JPEG size or blaming the model. Large test
   text was readable; small text at this resolution is not proven.
3. **Human-help path is a dead end:** `TaskController.handle(ASK_PERSON)` offers
   sharing, but main keeps `pending_prompt_id=None`, no caller/review DB records
   are written, and consent results are not delivered. Finish the loop before
   demonstrating it; otherwise change the offer to an honest unavailable message.
4. **Product is narrower than the blueprint:** current runtime is a commanded
   label reader, not a continuous visual guide. It ignores object/position fields
   for guidance, has no conversational response model or contextual history, no
   background search and no visual avatar beyond a static status card. Do not
   promise autonomous navigation or general hazard understanding.
5. **Sponsor libraries are disconnected:** main has no database/event calls;
   `record_stage_event` is unused by the live pipeline. There is no job runner,
   web app, portal or migration CLI despite package entry points advertising them.
6. **Solana proof is currently simulated:** `DeterministicSigner` produces a
   SHA-256 digest, not a signed Solana transaction. No concrete network signer/RPC
   adapter, treasury file or recipient is configured. Reward unit tests establish
   orchestration semantics only, not an on-chain payment.
7. **Deployment and workflow evidence are absent:** no Vultr deployment artifacts
   or running web dashboard; no Grok Bot call or workflow. Dependencies and empty
   environment fields are not usage evidence.
8. **Release state needs attention:** origin points to
   `https://github.com/Samat-ai/tiresias.git`, but rescue changes are uncommitted.
   Commit and upload the tested source before the cutoff. Do not stage `.env.local`,
   ADC files, runtime logs, snapshots, or unrelated `.idea` files.
9. **Existing phone-data protection is not ready for real deployment:**
   `auth.encrypt_phone` uses repeating XOR rather than authenticated encryption.
   Keep phone enrollment out of the public demo path; replace it before storing
   real phone data. This does not require reworking the tested FaceTime label path.

## Plan comparison

| Blueprint deliverable | Current implementation | Readiness |
| --- | --- | --- |
| Native FaceTime visual assistant | Chert line, LiveKit worker, caller track ingest and returned voice | Wired; actual handset test still required |
| Gemini visual understanding | Real Vertex ADC vision observations and policy decisions | Live generated-image proof; broader visual guidance missing |
| Natural low-latency voice | Real ElevenLabs streaming STT and Flash TTS; fixed response templates | Transport proven; conversation quality incomplete |
| Guardian dashboard | Auth/review libraries and SQL; no web app | Not implemented |
| Tiger Data metrics | Local Timescale extension, stage_events hypertable and aggregate migration | DB tested; runtime producer and dashboard missing |
| Human-in-the-loop review | Consent/snapshot/review domain tests | Not connected to callers or helper UI |
| Volunteer Solana bounty | Idempotent payout state machine with test doubles | No real transaction proof |
| Vultr hosting | Local Windows processes | Not implemented |
| Cursor + Grok workflow | Owner reports prior Cursor development; no Grok automation code/config | Incomplete |
| Post-call iMessage | Config flag only | Not implemented; optional for Chert |

The blueprint's JavaScript filenames/model choices are historical; the current
Python implementation need not be rewritten. The later R0 handoff intentionally
excluded dosing and street-crossing advice. Use ordinary product labels and
human-confirmed literal text for this demo. MongoDB and GoDaddy are not among the
owner's eight selected tracks, so they are not additional deadline tasks.

## Track evidence matrix

| Track | Published requirement or judging focus | Current evidence | Remaining gate |
| --- | --- | --- | --- |
| General | Robustness, Homer's Odyssey theme, creativity; submission artifacts and in-person judging | Tiresias story; functional voice/vision pipeline | Real demo, accurate pitch, uploaded code, video, attendance |
| Chert | Chert FaceTime API; bring an iPhone; make/take a real FaceTime call during demo; select Chert category | Existing Chert bridge/line and matching media tracks | Actual handset proof; demo on FaceTime rather than only a browser/test room |
| Gemini | Build using Gemini API | Live Gemini image analysis via Vertex using Google Gen AI SDK | Explain ADC/Vertex route accurately; confirm with MLH rep if the sponsor interprets its API requirement narrowly |
| ElevenLabs | Innovative interactive API use; Devpost section titled **How We Used ElevenLabs** | Real STT and TTS together in multimodal assistant | Add exact-titled section and features/models used; show live interactive audio |
| Tiger Data | Meaningful project use of Tiger Data | Test DB has timescaledb installed and stage_events hypertable; zero runtime events | Runtime inserts, real dashboard queries, preferably hosted Tiger Data service with demonstrable data |
| Solana | Meaningful use of Solana | Library plus mocked payout tests | Real devnet transaction tied to a completed human review, signature and explorer link; confirm devnet acceptance with rep |
| Vultr | Build/deploy using Vultr cloud infrastructure | None in running app | Deploy a real project service, health check and URL; record deployment evidence |
| SpaceXSI | Cursor as core coding agent; Grok Bot automation; explain both; opt into raffle | Owner's Cursor work; no Grok automation | Genuine Grok Bot workflow and execution evidence; truthful agent/tool history; select raffle opt-in |

The user does not need to abandon a working Vertex setup based on an unverified
interpretation of the Gemini track. Obtain clarification rather than inventing
an API-key-only rule. Likewise, no source establishes that additional Codex help
automatically disqualifies the Cursor workflow; describe actual usage truthfully.

## Recommended next work

Keep the current Python worker. Add a bounded conversational product helper,
then a thin operator dashboard backed by Tiger Data. Connect consented review
completion to one idempotent devnet reward, and host the dashboard on Vultr.
The working worker can stay local while the web service is deployed; moving
everything at once is unnecessary for a truthful Vultr hosting proof.

Use the implementation plan in
`docs/superpowers/plans/2026-11-15-deadline-completion.md`. Stop feature work by
10:00 a.m.; reserve time for the live demo, 30s–2min video, tested-code upload,
and Devpost edits. If a service cannot be shown working, do not list it as built.
