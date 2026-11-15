# Tiresias R0 — agent handoff

> **Current bridge recovery:** 192 tests pass. Chert must stay running for calls.
> A failed handset attempt had `remote_audio_timeout` and a greeting at the old
> 30-second fallback. The restarted bridge is connected. Greeting now requires
> an explicit true ready flag, with a bounded server-metadata lookup after caller
> audio arrives; no greeting is inferred from a join or an elapsed timer. Bridge
> disconnect cancels pending work and shuts down SDK audio without draining.
> Actual delayed-ready integration: no early speech, first audio **0.623 s** after
> readiness, stop cue, two label reads and animated video all passed. Active logs:
> `data/worker-bridge-readiness-v2.stdout.log` / `.stderr.log`.

> **Current accessible states/avatar:** 187 tests pass. Sparse spoken cues,
> acknowledged Stop/Wait/Hold on, generation-owned listening/thinking/speaking
> states, and a Higgsfield-generated character are active on the normal worker.
> The SDK's initial three-second STT mute was disabled after reproducing clipped
> early controls. Actual normal-worker stop cue, two label reads and changing
> 480×640 video passed; final preview counting/backchannel checks passed twice.
> Website artwork is live at https://tiresias.ink. Four generated assets used
> exactly 2 approved existing credits. See [CALL-STATES.md](CALL-STATES.md) for
> evidence and remaining handset/echo check. Active logs:
> `data/worker-accessible-states.stdout.log` / `.stderr.log`.

> **Current fast-vision worker:** 173 tests pass. Speech-first Gemini answers,
> scene/OCR resolution routing, real sharpness scoring, timestamped bounded video
> ingress and metadata-only authentication warm-up are active. Newest frames are
> retained for explicit label rechecks. Real counting/backchannel questions passed
> twice on the final worker, then label reads passed twice. SDK answer audio began
> 1.06/1.26 seconds after completed turns (not total phone latency). See
> [VISION-PERFORMANCE.md](VISION-PERFORMANCE.md) for measurements/limits. Logs:
> `data/worker-fast-vision-v2.stdout.log` / `.stderr.log`. Caller linking was
> confirmed by the owner; actual logs showed two automatic saved-voice loads.

> **Automatic caller settings:** 140 tests pass. One-time caller linking is
> implemented with the live Chert authenticated call API, separate voice-only
> bindings in Tiger Data, and a four-digit code spoken by the worker and entered
> on the signed-in website. Future calls from a verified identity auto-load
> preferences. No raw caller number is persisted, and the Chert credential stays
> local. Fresh review found/fixed concurrent unlink, late-refresh and code-history
> issues. Website controls are under “Remember me next time”; real handset setup
> and second-call verification remain pending. The current worker logs are
> `data/worker-caller-links.stdout.log` / `.stderr.log`.

> **Profile hotfix:** 119 tests pass. “Use profile” can now be said first, then
> digits across separate turns. A public LiveKit completed-message event recovers
> commands previously skipped during uninterruptible playback, with message-ID
> deduplication. A real-provider paused/overlapping profile test loaded saved
> settings, and both counting/backchannel follow-ups passed. Local worker was
> restarted; current logs are `data/worker-profile-fix.stdout.log` / `.stderr.log`.
> Owner confirmed the public website works on mobile data (public Wi-Fi failed).

> **Latest deployment/voice update:** 113 tests pass. The owner confirmed the
> improved conversation works on a real FaceTime call. Persistent voice, tone
> and speed settings are live at **https://tiresias.ink**, hosted on the owner's
> Vultr VM with verified HTTPS. Both web and local worker use hosted Tiger Data;
> account preferences, a real ElevenLabs preview and real pipeline stage records
> were verified. Say “Use profile” followed by the eight digits shown in your
> account to select its voice during a call. This code is not authentication.
> Keep the local Chert bridge and voice worker running. Human review, real Solana
> transfers and Grok Bot remain unfinished. See [deploy/README.md](../deploy/README.md)
> and [IMPLEMENTATION-LEDGER.md](IMPLEMENTATION-LEDGER.md) for current evidence.
> Older updates below describe earlier stages of the rescue.

> **Latest conversational fix:** 94 tests pass. The owner's real FaceTime call
> delivered 1280×720 frames and read Pepsi, but a counting question misrouted to
> ASK_PERSON. Raw STT dispatch/forced interruption caused turn collisions. Main
> now uses completed turns, server VAD + STT endpointing, a quiet gate, backchannel
> protection and direct image-question answers with short context. Automatic VAD
> interruption is disabled; completed meaningful utterances explicitly interrupt
> while input stays open during playback. Counting two Pepsi cans with a person
> in view passed real-provider tests, including a continuous-mic overlap test
> with “yes” during playback and a successful repeated follow-up question.
> Retest actual handset conversation. Human review/sponsor integrations remain missing.

> **Latest audit:** [PROGRESS-AUDIT.md](PROGRESS-AUDIT.md) compares the Downloads
> blueprint/slides with the code and all eight selected tracks. All 77 tests pass.
> Real isolated LiveKit/STT/vision/TTS tests returned correct label audio on two
> repeated checks in each of two runs. Actual Chert handset verification remains
> pending. Whole-word product matching was corrected; small-label input resolution
> remains unresolved. See the linked deadline implementation plan in the audit.

> **November 15 rescue update:** Read [RESCUE.md](RESCUE.md) first. Vertex AI
> with existing local ADC now works: real generated-label probe returned a correct
> MATCH in 2.26s. `.env.local` selects Vertex/global instead of depleted AI Studio
> prepay. Repeated-command, cancellation, image freshness and latency fixes are
> implemented. All 75 tests passed. A real FaceTime call is still required.
> Historical status below predates these fixes.

Dense continuation doc for a **new agent** with no prior chat context.  
Repo: `C:\Users\samat\Documents\Cursor\tiresias` · Windows · Python 3.13 · PowerShell · venv `.venv`.

**Secrets:** never paste API keys, LiveKit secrets, or full `.env.local` into docs/chat. Use presence checks only.

---

## 1. What it is

**Tiresias** is the HackUTA R0 FaceTime **label assistant**: find an everyday item on camera, read its label, then recheck a fresh view of the selected item.

| Stack piece | Role |
| --- | --- |
| **Chert** (`@trychert/facetime`) | Trial FaceTime line + bridge into LiveKit (`chert dev`) |
| **LiveKit Agents** | Named worker `tiresias-agent`; room jobs from Chert |
| **ElevenLabs** | Realtime STT (`scribe_v2_realtime`) + Flash TTS |
| **Gemini** | Vision JSON observations + optional text intent (heuristic fallback) |

**Out of scope for this hackathon build (Tasks 15–18):** signed production BYOR gateway, pilot recovery/invitations/callback alternative, production security/accessibility/recovery gate, hosted subscriptions/entitlement lifecycle. Do not implement those under R0 pressure.

**Event timing (owner-clarified):** initial Devpost entry by midnight end of Sat Nov 14, 2026 CST; **final deadline noon (12 p.m.) Sun Nov 15, 2026 CST**.

---

## 2. Current demo status

| ID | Value |
| --- | --- |
| Chert project | `8fdd4e9f-a087-4269-89d1-8ee7fbfe6ba2` |
| Trial line | Noah Wilson **+1 702 510 9706** (`+17025109706`) |
| Agent name | `tiresias-agent` |
| LiveKit | Own LiveKit Cloud project (Chert-managed keys still `livekit_not_provisioned`) |

### Works live on FaceTime today

- Chert accepts FaceTime **Video** while `chert dev` is connected and the agent is warm.
- Caller video track `facetime-remote-video` subscribed; frames JPEG-encoded into `FrameBuffer`.
- Caller audio → ElevenLabs STT → `user transcript` logs (hearing path works).
- Heuristic intent routes `find …` / `check this` / stop/repeat/slower/faster.
- Status video track `tiresias-status` published.
- Bridge-ready greeting path (`chert_bridge_ready` → lifecycle greeting) is implemented.

### Broken / partial (verify before judging “demo ready”)

| Area | Status | Evidence |
| --- | --- | --- |
| Live Gemini `analyze_frame` | **BROKEN/PARTIAL** | Recent agent logs: `400 INVALID_ARGUMENT` on vision during “Find me a Pepsi can” / “Find a pen”. Offline probe previously OK with `gemini-3.5-flash-lite`. |
| Gemini text intent | **PARTIAL** | Same `400` class; falls back to `route_utterance`. |
| TTS audio to caller | **PARTIAL** | Greeting/`session.say` wired; Chert has logged `no_audio` on some calls. |
| Ask-a-person → consent → snapshot review | **NOT LIVE** | Library + tests exist; agent does not persist reviews / no portal. |
| Sponsor proofs (Solana/Vultr/Grok/Atlas UI) | **PENDING** | See §8. |

**Truthful demo script (once Gemini live 400 is fixed):** FaceTime Video the line → hear greeting → `find lemon sparkling water` → show label → `check this`.

**Processes observed at handoff write time (do not invent PIDs):** agent `python -m tiresias.agent.main start` and `chert … dev --agent tiresias-agent` were **running**. Confirm with terminal status / `chert doctor` after any restart.

Provider ledger: [`docs/provider-capabilities.md`](provider-capabilities.md).

---

## 3. How to run locally

### One-time / env

```powershell
cd C:\Users\samat\Documents\Cursor\tiresias
.\.venv\Scripts\Activate.ps1
# If packages missing:
.\.venv\Scripts\python.exe -m pip install -e ".[media]"
# Optional chain extras: -e ".[media,chain]"
```

Secrets live only in **`.env.local`** (gitignored). Template: `.env.example`.  
Required for the call path (values present, not logged here): `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`, `ELEVENLABS_API_KEY` (or `ELEVEN_API_KEY`), `GEMINI_API_KEY`, `AGENT_NAME=tiresias-agent`, `CHERT_PROJECT_ID`.

Optional: `GEMINI_MODEL` — if empty, code defaults to **`gemini-3.5-flash-lite`**.

Sanity without printing secrets:

```powershell
.\.venv\Scripts\python.exe scripts\check_livekit_env.py
```

### Terminal A — agent worker

```powershell
cd C:\Users\samat\Documents\Cursor\tiresias
.\.venv\Scripts\Activate.ps1
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m tiresias.agent.main start
```

Wait for log: `registered worker` / `agent_name": "tiresias-agent"`.

(`dev` mode also exists via LiveKit CLI; production-style demo has been using `start`.)

### Terminal B — Chert line bridge

Pinned CLI used in this repo:

```powershell
npx --yes --prefer-online @trychert/facetime@0.1.0-beta.21 whoami --json
npx --yes --prefer-online @trychert/facetime@0.1.0-beta.21 doctor --json
npx --yes --prefer-online @trychert/facetime@0.1.0-beta.21 dev --agent tiresias-agent --json
```

If not signed in:

```powershell
npx --yes --prefer-online @trychert/facetime@0.1.0-beta.21 login --device --json
```

Then FaceTime Video **+1 702 510 9706**.  
Chert skills reference: https://app.trychert.com/skills.md

### Tests DB (auth/outbox)

```powershell
docker start tiresias-test-pg   # or recreate Timescale on 54329 — see §7
```

---

## 4. Architecture

### Packages under `src/tiresias/`

| Package / module | Purpose |
| --- | --- |
| `agent/main.py` | LiveKit `AgentServer` entrypoint; STT/TTS session; video ingest; vision/intent orchestration |
| `agent/media.py` | Caller track names, JPEG limits, `FrameBuffer` (`best` / pending) |
| `agent/vision.py` | Lazy-capable Gemini vision client + schema observation |
| `agent/intent.py` | Gemini text classifier + heuristic fallback |
| `agent/policy.py` | `route_utterance`, `decide`, speech templates, exclusions |
| `agent/controller.py` | Task state machine; inflight revision; pinned-frame complete |
| `agent/speech.py` | `SpeechScheduler`, `CallLifecycle` (bridge-ready greeting) |
| `auth.py` | Users, sessions, CSRF, phone bind, service consent, caller resolve |
| `reviews.py` | Consent + snapshot + review create/complete/delivery text |
| `outbox.py` | Idempotent jobs, scene upsert guards, claim/lease |
| `rewards.py` | Solana **devnet** payout prepare/reconcile (library) |
| `config.py` | `Settings` from `.env.local` / `.env` |
| `contracts.py` | Shared pydantic enums/models |
| `db.py` | Test Postgres connect/migrate/reset |
| `security.py` | Argon2id, tokens, CSRF |

**Not present yet (pyproject entry points reference them):** `app.py`, `jobs.py`, `migrate.py`, `portal.py` — no FastAPI website in tree.

### Data flow

```
FaceTime Video (+1 702 510 9706)
  → Chert bridge participant (chert-bridge-*)
  → LiveKit room (Chert warm room)
  → tiresias-agent
       ├─ facetime-remote-audio → ElevenLabs STT → IntentClassifier / route_utterance
       ├─ facetime-remote-video → FrameBuffer → VisionClient (Gemini) → policy.decide
       └─ TaskController → SpeechEvent → session.say() → ElevenLabs TTS → caller
```

Policy owns spoken lines; the LiveKit `Agent` raises `StopResponse` so the LLM does not freestyle.

---

## 5. Recent fixes (important)

| Fix | Why |
| --- | --- |
| Speech / STT hearing | Room IO linked to `chert-bridge*`; open listening on caller audio before bridge metadata; `user_input_transcribed` + turn handler; VAD + ElevenLabs STT |
| Gemini model | AI Studio UI dropped 2.x for new use → default **`gemini-3.5-flash-lite`** in `vision.py` / `intent.py` |
| False-blurry + slow thinking | Prompt prefers quoting text; `_soften_quality`; `thinking_budget=0`; `buffer.best` sharpness heuristic; `complete_inflight(..., analyzed_frame=frame)` pins the frame Gemini saw |
| Intent + natural TTS | `IntentClassifier` + conversational `speech_for` / clarification templates; TTS `VoiceSettings` (lower stability, light style, normalization on) |
| Lazy `VisionClient` | `_get_vision()` / executor — avoid constructing Gemini client at import/startup (SSL stalls) |

**Open bug to fix next:** live Gemini generate_content returning **`400 INVALID_ARGUMENT`** for both vision schema calls and text intent (heuristic still saves find/check routing). Offline probe had worked; re-probe and adjust config (`thinking_config`, schema, timeouts, model id) before recording the demo video.

---

## 6. File map

| Path | One-line purpose |
| --- | --- |
| `src/tiresias/agent/main.py` | LiveKit agent worker + media/vision loop |
| `src/tiresias/agent/media.py` | Frame buffer + track constants |
| `src/tiresias/agent/vision.py` | Gemini frame → `Observation` |
| `src/tiresias/agent/intent.py` | Utterance → `UserIntent` |
| `src/tiresias/agent/policy.py` | Heuristics + evidence decisions + speech text |
| `src/tiresias/agent/controller.py` | Task generations / find / check / stop |
| `src/tiresias/agent/speech.py` | Queue + call lifecycle greeting |
| `src/tiresias/config.py` | Env settings |
| `src/tiresias/contracts.py` | Shared types |
| `src/tiresias/auth.py` | Auth/consent/phone helpers |
| `src/tiresias/reviews.py` | Snapshot review domain |
| `src/tiresias/outbox.py` | Job outbox + scene rules |
| `src/tiresias/rewards.py` | Devnet payout service |
| `src/tiresias/db.py` | Test DB harness |
| `src/tiresias/security.py` | Password/session crypto |
| `migrations/001_core.sql` | Core schema |
| `migrations/002_events.sql` | Events / outbox extensions |
| `scripts/check_livekit_env.py` | LiveKit env presence/length checks (no secrets printed) |
| `docs/provider-capabilities.md` | WORKING/BLOCKED/PARTIAL ledger |
| `.env.example` | Non-secret env template |
| `.gitignore` | Ignores `.env.local`, `.chert/`, snapshots, etc. |
| `pyproject.toml` | Package + optional `media` / `chain` / pytest |
| `tests/test_*.py` | Policy, frames, speech, auth, outbox |

---

## 7. Tests

```powershell
cd C:\Users\samat\Documents\Cursor\tiresias
.\.venv\Scripts\Activate.ps1
# pythonpath set in pyproject; explicit is fine:
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m pytest -q
```

| Suite | Focus | DB? |
| --- | --- | --- |
| `tests/test_policy.py` | decide / blurry soften / intent heuristics / speech templates | No |
| `tests/test_frames.py` | Frame freshness, clear on disconnect, pending | No |
| `tests/test_speech.py` | Lifecycle greeting, scheduler dedupe, wrong-can mismatch races | No |
| `tests/test_auth.py` | Users, CSRF, consent, reviews, rewards (mocked RPC) | Yes — skips if Postgres down |
| `tests/test_outbox.py` | Dedupe, leases, expiry, scene resurrection guards | Yes |
| `tests/test_tasks.py` | Placeholder note only | — |

Default test URL: `postgresql://postgres:postgres@localhost:54329/tiresias_test`  
Container used earlier: `tiresias-test-pg` (Timescale `latest-pg16`).

**Verified at handoff write:** `test_policy` + `test_frames` + `test_speech` → 35 passed; `test_auth` + `test_outbox` → 22 passed with Docker PG up. Collect-only: 57 tests.

---

## 8. Todo / remaining R0 work

| Item | Status | Reality check |
| --- | --- | --- |
| Phase 0 probes (Chert/LiveKit/ElevenLabs/Gemini probe) | **DONE** | See provider-capabilities |
| Voice loop on FaceTime (STT + TTS + video ingest) | **DONE / PARTIAL** | Works; occasional `no_audio` |
| Find/check controller + unit tests | **DONE** | Strong pytest coverage |
| Live Gemini vision on call | **PENDING FIX** | Wired; live 400s — unblock for demo |
| Intent classifier | **DONE / PARTIAL** | Code + tests; live Gemini 400 → heuristics |
| Review path (portal / consent / snapshots / Atlas) | **PARTIAL → PENDING** | `auth`/`reviews`/`outbox` + migrations + tests; **no** FastAPI portal, templates, Atlas client, agent→DB wiring |
| Sponsor proofs — Solana devnet | **PARTIAL** | `rewards.py` + tests; no live treasury/key demo script committed |
| Sponsor proofs — Vultr / HTTPS / domain | **PENDING** | No deploy artifacts in repo |
| Sponsor proofs — Grok Bot webhook | **PENDING** | Config keys exist; no `scripts/notify_grok.py` |
| Tiger Data / Timescale | **PARTIAL** | Test container + SQL migrations; not production-hosted |
| MongoDB Atlas scenes | **PENDING** | `upsert_scene` SQL-shaped helpers; no Atlas usage in agent |
| Devpost entry + demo video | **PENDING** | Repo has **no commits / no remote** yet (`git status` showed untracked tree on `main`) |
| Submit / evidence ledger | **PENDING** | Deadline noon Sun Nov 15 CST |
| Tasks 15–18 | **OUT OF SCOPE** | Do not build for R0 |

---

## 9. Operational pitfalls

1. **Chert shared-line capacity** — trial lines fill up; onboarding can sit on waitlists. Keep the assigned Noah Wilson line; don’t thrash re-onboard.
2. **LiveKit secret length / whitespace** — doctor fails on short or quoted secrets. Use `scripts/check_livekit_env.py` (length/whitespace/quote checks only).
3. **Agent must register before calls** — if Chert logs `agent_not_warm`, calls are declined. Start agent, wait for `registered worker`, then ensure `dev` shows `agent_warm`.
4. **Restart agent after code changes** — worker loads code at process start.
5. **`chert_bridge_ready` greeting window** — greeting waits up to ~30s for room metadata; audio listening opens earlier so commands aren’t dropped forever.
6. **Never commit `.env.local`** — gitignored; also ignore `.chert/`, `private/`, snapshot dirs.
7. **Windows has no `head`** — use `Get-Content … -TotalCount` / `-Tail`.
8. **Own LiveKit, not Chert-provisioned** — `chert livekit` stayed blocked; keep using the Cloud project already in `.env.local`.
9. **Gemini timeouts** — API rejects HTTP deadlines under 10s; code clamps to ≥10s.
10. **Consent intents** — `ASK_PERSON` sets controller consent id, but `main.py` keeps `pending_prompt_id=None` and controller does not handle `CONSENT_ACCEPT`/`DECLINE` → review voice path incomplete.

---

## 10. Handoff checklist for next agent

Do these **first five** actions before feature work:

1. **Confirm env (no secret dump):** `python scripts/check_livekit_env.py` and verify `GEMINI_API_KEY` / ElevenLabs / `AGENT_NAME` present via length/presence only.
2. **Run unit suites:** `python -m pytest tests/test_policy.py tests/test_frames.py tests/test_speech.py -q` (then auth/outbox if Docker PG is up).
3. **Start / verify agent warm:** `$env:PYTHONPATH='src'; python -m tiresias.agent.main start` → log shows `tiresias-agent` registered.
4. **Start / verify Chert:** `npx … @trychert/facetime@0.1.0-beta.21 doctor --json` then `dev --agent tiresias-agent --json` → `agent_warm`.
5. **Smoke FaceTime:** call **+1 702 510 9706**, confirm greeting + STT transcript in agent logs, then **reproduce and fix** live Gemini `400 INVALID_ARGUMENT` on `find …` before filming.

After that: stabilize vision → record demo → Devpost/submit → only then remaining review/sponsor slices that fit the noon deadline.

---

## Quick reference commands

```powershell
# Agent
$env:PYTHONPATH='src'; .\.venv\Scripts\python.exe -m tiresias.agent.main start

# Chert
npx --yes --prefer-online @trychert/facetime@0.1.0-beta.21 doctor --json
npx --yes --prefer-online @trychert/facetime@0.1.0-beta.21 dev --agent tiresias-agent --json

# Tests
.\.venv\Scripts\python.exe -m pytest -q
```

Call: FaceTime Video **+1 702 510 9706**.
