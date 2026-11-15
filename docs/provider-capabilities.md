# Provider capabilities

**Current deployment/voice status:** 113 tests pass; the owner confirmed improved
handset conversation. Hosted Tiger Data stores saved voice preferences and real
call-stage telemetry. A real ElevenLabs web preview and spoken-profile load were
verified. Vultr hosts **https://tiresias.ink** with valid HTTPS (root and www);
registration, persistence, preview and performance pages were browser-tested.
The Chert/LiveKit worker still runs locally. Human review, actual Solana devnet
transfers and Grok Bot remain unverified/unfinished. Earlier status below is
historical; consult [IMPLEMENTATION-LEDGER.md](IMPLEMENTATION-LEDGER.md).

**Latest call-driven update:** Real handset input was 1280×720 and close-up Pepsi
reading worked. Count-question intent misrouting and voice turn collisions were
corrected. Direct multimodal conversation now answers the two-can/person test;
94 tests pass; the corrected continuous-mic overlap/retry test passed twice.
A handset conversation retest remains pending. Human sharing is
unavailable and no longer offered as a working feature.

**Latest audit:** [PROGRESS-AUDIT.md](PROGRESS-AUDIT.md): 77 tests pass; real
LiveKit + ElevenLabs STT + Vertex vision + ElevenLabs returned audio verified
with repeated commands. Chert/handset delivery still needs a real iPhone test.
Sponsor readiness and the confirmed Devpost requirements are in the audit.

**November 15 update:** See [RESCUE.md](RESCUE.md). Vertex AI with local ADC
successfully read and matched the generated label in 2.26s. Local configuration
selects Vertex/global, avoiding the depleted AI Studio prepay backend. All 75
tests pass. Real FaceTime camera and audio verification remains pending.
The historical ledger below predates the rescue fixes.

Reviewed during R0 setup. Do not paste secrets here.

| Capability | Status | Notes |
| --- | --- | --- |
| Chert account / project | WORKING | Project `8fdd4e9f-a087-4269-89d1-8ee7fbfe6ba2` signed in on this computer. |
| Phone verification / trial line | WORKING | Trial line Noah Wilson `+17025109706` answering via `chert dev`. |
| Shared line worker readiness | WORKING | Live FaceTime Video calls accepted while `chert dev` is connected. |
| Own LiveKit Cloud credentials | WORKING | Doctor accepted URL/key/secret after correction. Values stay in `.env.local` only. |
| Chert-managed LiveKit keys | BLOCKED | Still `livekit_not_provisioned`; using own LiveKit project instead. |
| ElevenLabs key in `.env.local` | WORKING | Onboarded; key present; not logged here. |
| Agent worker `tiresias-agent` | WORKING | Registered and handling FaceTime jobs when process is up. |
| Gemini image/schema probe | WORKING | Offline probe succeeded with `gemini-3.5-flash-lite` (2.5 removed from AI Studio UI). Default in code when `GEMINI_MODEL` empty. |
| Gemini live vision analyze | BROKEN/PARTIAL | FaceTime path recently logged `400 INVALID_ARGUMENT` on `analyze_frame` (same class of error as intent). Fix before demo. |
| Gemini text intent classify | PARTIAL | Live calls get `400 INVALID_ARGUMENT`; heuristic `route_utterance` fallback still routes find/check. |
| Caller video track `facetime-remote-video` | WORKING | Frames ingested during FaceTime Video; status video published. |
| Bridge-ready greeting / TTS | PARTIAL | Greets after `chert_bridge_ready`; Chert has also logged `no_audio` on some calls — confirm TTS track after restart. |
| Find → vision → check loop | PARTIAL | Wired end-to-end; blocked on live Gemini 400 until fixed (see `docs/HANDOFF.md`). |
| Review portal / Atlas / Vultr / Grok | PENDING | Library/tests exist for auth/reviews/outbox/rewards; no FastAPI portal, Atlas wiring, Vultr deploy, or Grok webhook script yet. |

## Next human actions

1. Keep the agent process and `chert dev` running (or restart both — see `docs/HANDOFF.md`)
2. FaceTime Video `+1 702 510 9706`
3. Say `find lemon sparkling water` (or another labeled item), show the can, then say `check this`
