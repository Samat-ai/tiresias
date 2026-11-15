# Provider capabilities

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
