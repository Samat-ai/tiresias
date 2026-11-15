# Completion ledger — plan: docs/superpowers/plans/2026-11-15-deadline-completion.md

## Baseline

- Owner confirmed the initial Devpost entry was submitted.
- Owner confirmed the new conversation flow works much better on FaceTime.
- 94 tests passed; real pipeline counting/backchannel/follow-up tests passed.
- Remaining account resources not configured: Grok Bot destination, Solana
  treasury/recipient. Tiger Data is connected and the Vultr VM is accessible.
  Continue local implementation
  while these are provisioned; do not claim external integration without evidence.

## Rulings

- Ruling: Keep the existing working directory and move edits to a development
  branch rather than copying into another worktree — the live worker and virtual
  environment are anchored here and contain the verified rescue. No source or
  user edits are discarded; changing this assumption would complicate restart.
- Ruling: Add voice settings as a complete dashboard slice before the remaining
  sponsor tasks — the user explicitly requested persistent voice/tone selection.
- Ruling: A spoken profile code links voice preferences only. It is not caller
  authentication and must never authorize private review access or payments.
- Ruling: Use a separate local application DB for durable development settings;
  retain the isolated test DB. A local Timescale instance is not proof of a
  hosted Tiger Data integration. DATABASE_URL can later target Tiger Data.
- Ruling: Retain the Python/FastAPI architecture and Vultr hosting plan; do not
  create an unrelated Sites/Cloudflare deployment.

## Active work

- Voice preferences: validated models, durable storage, web account UI,
  voice preview, call profile selection and live voice/tone commands.
- Telemetry: bounded asynchronous stage writes and dashboard latency queries.

## Verified on November 15, approximately 02:28 CST

- Full suite: `python -m pytest -q` -> **113 passed**, 17.70 seconds.
- Hosted Tiger Data: migrations applied, Timescale extension/hypertable present;
  real pipeline telemetry includes two conversation requests at 2221/1116 ms
  and speech generation first audio at approximately 145–178 ms. Playback
  duration includes the spoken answer and must not be called response latency.
- Saved Sarah/friendly/0.85 settings through the local web UI; actual preview
  returned MP3. A real-provider LiveKit smoke call loaded the saved profile by
  spoken digits and correctly counted two Pepsi cans in both follow-up tests.
- Vultr VM `45.76.239.245`: pinned-key SSH works, Ubuntu 24.04, one CPU,
  approximately 2 GB RAM, fresh host, UFW initially permits SSH only.
- Prepared source-allowlist deployment, unprivileged systemd web service, Caddy
  HTTPS and operation/rollback instructions. No credentials are embedded in
  these source files or the release archive.
- The user explicitly approved copying the Tiger Data credential and ElevenLabs
  key to this VM after the automatic review asked for that authorization.
  Deployment then completed; the environment file is mode 0640, root:tiresias.
- Human helper flow, real Solana transaction and Grok Bot are still unproven.

## Vultr deployment and domain, approximately 02:38 CST

- Public web service deployed and independently browser-tested: registration,
  account-scoped preferences saved/reloaded, real ElevenLabs MP3 preview
  (HTTP 200, 12033 bytes, 576 ms), live Tiger Data performance dashboard,
  and mobile layout with six available voices. QA used a separate test account.
- Current release: `20261115t083404z`; source archive SHA256
  `bf6f62c08212d2dca2327421e846a86db9f75911c55abd864003d8c032d30208`.
- Main URL: **https://tiresias.ink**. Also configured `www.tiresias.ink` and
  `45.76.239.245.sslip.io` as HTTPS aliases. Caddy and tiresias-web are active.
- User configured Porkbun: root A -> `45.76.239.245`, www CNAME -> `tiresias.ink`,
  TTL 600. Verified both against authoritative Porkbun and public resolvers.
  After server DNS cache refresh, both root/www HTTPS health endpoints returned
  HTTP 200 with certificate validation enabled (no insecure TLS bypass).
  Some client DNS caches still hold the deleted parking/NODATA records, so
  browser access to the new domain may lag public DNS until those expire.
- First redeploy encountered Ubuntu unattended-upgrade's package lock. The
  provisioner now skips installed dependencies and waits for the lock when
  installation is actually required. A subsequent deployment passed.
- FaceTime bridge and Gemini/voice worker remain local; keep them running for
  calls. Web deployment alone does not make calls independent of this computer.

## Profile command repair, approximately 02:51 CST

- Actual handset logs showed “Use profile.” routed as FIND_TARGET because no
  digits followed it in the same completed turn. A later complete code was
  retained by LiveKit during uninterruptible playback but never delivered to
  `on_user_turn_completed`.
- Added bounded profile entry across turns: bare command prompts for eight
  digits; partial groups/fillers are parsed; complete code repeats replace the
  partial entry. Cancel, topic change and a 45-second expiry clear entry state.
  Only a complete eight-digit code reaches the database lookup.
- Recover completed user messages from LiveKit's public
  `conversation_item_added` event. Deduplicate by message ID across that event
  and the normal completed-turn hook; raw STT remains diagnostic only. This
  preserves backchannel protection and legitimate identical-command retries.
- Six regression tests failed before the change and passed afterward. Full
  suite: **119 passed**, 30.56 seconds. Restarted the local worker with the fix;
  current logs: `data/worker-profile-fix.stdout.log` / `.stderr.log`.
- Real-provider smoke (`--conversation --backchannel --profile-paused
  --profile-code <QA-code>`) passed: output transcribed as “Say the eight digits
  ... I have four digits ... Your saved voice preferences are loaded.” Both
  subsequent counting questions returned two Pepsi cans despite “yes” during
  output. Test excludes Chert/handset; owner should retry their actual call.
  Artifact: `data/profile-paused-smoke-results.json` (ignored).
- Owner confirmed `https://tiresias.ink` works on the phone's mobile data;
  their public Wi-Fi could not open it. DNS, TLS and service were independently
  checked. Do not treat that network failure as a local-only deployment.

## Caller-linked preferences — implementation in progress

- Owner requested one-time setup and automatic settings by phone number,
  avoiding a long spoken profile code on every call.
- Verified authenticated Chert GET call API returns `from: {type, value}` for
  this project's real calls. Only field names/types were logged; credentials
  and caller values were omitted. Chert's bridge participant ID identifies the
  exact call UUID; provider response must match project, inbound/live state and
  a recent creation time before its caller handle is used.
- Ruling: link voice preferences with an inbound spoken four-digit challenge
  entered on the signed-in website once — this proves control without SMS or
  reading a code aloud. Caller binding selects preferences only, never private
  review/payment access. Store keyed handle fingerprints and masked displays;
  do not reuse legacy XOR phone storage. Cost: setup still needs one brief call
  and entering four heard digits on the site.
- Separate additive migration 004 has been applied to hosted Tiger Data. A new
  random `CALLER_LINK_SECRET` was generated in local ignored configuration;
  it must also be deployed in the restricted web-service environment. Chert
  credentials remain only on this computer.
- Tests watched fail then pass for DB linking, authenticated provider lookup,
  CSRF/account isolation, persistent failed-code attempts, unlink, runtime
  setup speech and automatic loading on two separate fake calls without STT.
  Full suite: **136 passed**, 47.22 seconds. Fresh code review is in progress.
- Real handset link/second-call verification is still outstanding. Do not claim
  the real caller auto-load path is proven by fake/runtime tests.

### Fresh caller-link review and fix pass

- Reviewer found three Important issues. All were reproduced by failing tests:
  confirmation racing unlink could preserve a link; delayed profile refresh
  could restore settings after unlink; setup speech included digits in logs and
  Gemini history. Fixed with consistent per-user DB locking, revision checks
  after asynchronous reads, and private setup speech excluded from logs and both
  application/SDK chat histories. Full suite after fixes: 139 passed.
- Minor deferred: explicitly asking to repeat a setup code can repeat an already
  expired/confirmed code. Verification still rejects it; starting setup again
  is the recovery. No authentication or preference selection is authorized by
  that stale code.
- Browser verification caught cached old JavaScript after deployment. Added
  content-derived asset URLs; regression changes a script and confirms a new
  URL is rendered for an existing signed-in session. Caller forms now use POST
  even when script loading fails, keeping caller handles out of query strings.
- Worker restarted with caller linking enabled. The actual-provider normal
  conversation/backchannel smoke passed both checks after this restart.
- Final suite: **140 passed**, 57.23 seconds. JavaScript syntax and tracked diff
  whitespace checks pass. Final public release `20261115t093820z`, archive SHA256
  `33e3006141eb2091e87dca88b5ac5c4add1ccd20598dbd41b424a58d8979dbb4`.
  Browser verified the new content-derived script URL, phone-sized layout,
  authenticated setup request, masked response, and cancellation through the
  actual public app. QA used a fictional 555 number; no phone call/SMS was sent.
  Normal HTTPS health returns 200. Owner was given the one-time setup steps;
  real setup and second-call auto-loading remain the explicit final handset gate.

## Fast vision work — November 15

- Owner subsequently reported caller linking works. Local worker logs contain
  one private setup-code announcement and **two verified-caller automatic voice
  loads**, supporting the reported setup/repeat-call success.
- Read the entire Downloads fast-vision Gemini 3 guide. Existing continuous JPEG
  capture, minimal thinking and Flash TTS were already present. Guide claims of
  fixed 650 ms end-to-end audio, guaranteed sharpness from entropy, arbitrary
  distance estimates and an unscoped memory SQL query were not adopted.
- Ruling: implement measured stream-first speech, low-detail scene/high-detail
  OCR routing, gradient scoring and bounded fresh frames in existing Python,
  with no raw image persistence, new background speech or database lookup on
  the visual answer path. Keep strict JSON/policy validation for label matches.
  Cost: no new persistent spatial memory or automatic hazard warnings in this
  change; explicit rechecks favor newest evidence over an old sharper label.
- Consulted current Google primary docs for media resolution, thinking levels
  and Gemini 3.8. Actual Vertex requests verified LOW/HIGH resolution and 3.8 LOW
  thinking. 3.8 was slower on the tested cases, so Flash-Lite remains default.
- Initial synthetic 2x2 benchmark: existing JSON median speech-ready 1272 ms,
  candidate speech-first 674 ms, both 4/4 correct. Implemented pipeline with
  warm-up: six conversation samples median **729 ms**, 6/6 correct; three compact
  label samples median **962 ms**, 3/3 exact code/date checks. These are model text
  readiness, not total FaceTime audio latency; sample size is small. Artifacts
  `data/vision-benchmark-before.json` / `vision-benchmark-after.json` stay local.
- A free model metadata GET primes OAuth/connection in the waiting room without
  inference or camera data; real cold warm-up took 1197–1680 ms.
- Fresh review found three Important issues, reproduced RED: malformed stream
  delimiters could speak metadata, ambiguous OCR wording lost detail, processing
  queue waits could make old frames appear fresh. Fixes reject metadata/fragments
  and truncated output, default ambiguous questions to high detail, and stamp
  frames in a continuously draining ingress task before a one-frame processing
  queue. Video conversion/scoring is off-loop; streams/tasks close on disconnect.
- Full suite before final truncated-output check: **171 passed**. Final run and
  new real-provider smoke are pending. Existing worker has not been restarted
  with the new vision code yet, preserving working calls during implementation.
- Minor deferred benchmark limitations: original before data was captured before
  code edits and is preserved separately; later `current_json` runs call the now
  tuned JSON method. `image_bytes` in production benchmark rows is the source
  frame size, not necessarily the submitted resized scene payload. Neither field
  is used to claim unchanged-baseline reproduction or payload savings.
- Final code suite: **173 passed**, 29.40 seconds. New review regressions and
  delayed acknowledgment test all pass. One early overlap run returned a correct
  first answer but timed out before a second transcript; cause not established.
  Independent label checks passed. Faster speech exposed a separate late-final
  “yes” producing an unnecessary prompt; added a two-second positive backchannel
  grace period, with a regression watched RED->GREEN.
- Restarted final worker (`data/worker-fast-vision-v2.*.log`). Final real-provider
  overlap/repeat run passed both counted answers without extra social speech;
  subsequent label run passed both reads. Tiger Data for that final conversation:
  model speech readiness **683/886 ms**, SDK answer audio **1059/1263 ms** after
  completed turn, TTS first audio **170/172 ms**. These omit STT/phone transport.
- Measured scene submission separately: **46959 -> 18947 bytes**, while detailed
  label input stays **50112 bytes**; pixel features cost approximately **4.2 ms**
  off-loop on this computer. Public performance template now defines timings.
- Web release `20261115t115130z`, source archive SHA256
  `739e17a5cdb86044f47279ef8fae18b6ab0f4981577ecbff4d2e61d0929d4302`.
  Public health passed after deployment; caller-link secret preserved. An expired
  QA browser session correctly received 401 on the performance page.

## Accessible call states and character — November 15

- Requested: spoken feedback after interruption, animated FaceTime character,
  then Higgsfield-generated art shared with the website.
- Implemented per-call generation-owned feedback, SDK speech-driven states,
  quiet-gated/cancellable status cues and stop/wait/hold-on acknowledgments.
  Cues stay out of conversation history; cue audio does not satisfy answer
  latency metrics. Explicit pause acknowledgments bypass reminder cooldown.
- Tests watched RED for silent/misrouted pause controls, cooldown suppressing
  a second explicit pause and failed video publication source cleanup. Fixed
  controls/cooldown and SDK protobuf CopyFrom for video encoding. Full suite
  at this point: **183 passed**, 32.99 seconds. Final feature review pending.
- Procedural fallback preview visually inspected; 480x640 at 10fps, approximately
  1 ms render time. Preview GIF/contact sheet in ignored data directory.
- Ruling: owner specifically requested Higgsfield, replacing the procedural art
  as the main asset. Preserve local rendering/state control, add offline playback
  of generated loops, and share master still with the existing website. This
  adds bundled public artwork, but no model/API calls on the call path.
- Higgsfield plugin initially installed but tools absent from the running task;
  an unauthenticated endpoint probe returned 401, which did not establish a
  failure of the owner's sign-in. Tools later appeared and authenticated balance
  succeeded. Account has 10 credits and an available unlimited allowance through
  November 18. All character generations explicitly use_unlim=true; never charge
  credits on failure. Master pending: 13a6a539-3a81-4242-bfed-da668865db50.
- Existing fast-vision worker remains active; these changes are not activated yet.
- Final review found/fixed feedback being disconnected before bridge metadata;
  regression watched RED->GREEN. Website missing GIF restores the still.
- Real early controls were clipped or absent: actual SDK default AEC warmup
  zeroes caller PCM for three seconds of initial agent output. Added a test using
  real SDK push_audio and runtime configuration, watched silence fail, then set
  public aec_warmup_duration=0. Follow-up review accepted fix and flagged handset
  echo as a remaining verification gate. No noise/barge-in policy expansion.
- The free Higgsfield job stayed queued. Owner approved up to **2 existing
  credits**; each master/GIF quote was 0.5. Four assets completed, balance **8**.
  Native outputs: 16-frame, 512px GIFs; optimized web still: **22,976 bytes**.
- Final full suite **187 passed**, 33.61 seconds. Preview call passed early-stop
  acknowledgment and two counted answers; independent overlap/backchannel test
  passed both answers. Normal worker then passed early stop + two label reads,
  with 449 video frames / 111 distinct samples at 480x640. Earlier transient
  timeouts remain recorded; their cause was not conclusively established.
- Website deployed release **20261115t130709z**, source archive SHA256
  **c6f4d42fd28adc7a376392f1e43cfbc889e88530ded7b63687d3ba63d214abac**.
  Desktop/mobile artwork inspected; actual preview switched to speaking GIF
  and restored still. Reduced motion kept still through audio playback.
- Activated normal worker, logs `data/worker-accessible-states.*.log`. Full
  behavior/provenance/evidence in docs/CALL-STATES.md. Owner handset echo/animation
  check remains pending; no new Chert settings are needed.

## No-answer / bridge recovery

- Owner reported no answer, then observed Chert dev had gone down. The local
  bridge processes subsequently changed to a new running connection; doctor
  confirmed this account's existing line lease, service session and remote Mac
  were available. Did not take over or replace the restored bridge.
- Chert call diagnostics confirmed a failed attempt with
  `terminal_detail=remote_audio_timeout`. Worker greeting was logged at its
  30-second fallback after caller audio arrived much earlier. Server room metadata
  was later observed ready; exact cause/timing of the missed local flag was not
  conclusively isolated. Added a bounded server-read backup, not a claim that an
  SDK cache bug was proven.
- Ruling: preserve the pinned Chert CLI contract: only the explicit true
  `chert_bridge_ready` flag authorizes greeting. A prototype using caller-track
  readiness directly was rejected after reading that contract and was never
  activated. Tests now assert no speech on joined audio or a false readiness
  flag. After caller audio, bounded ListRooms queries can recover server readiness
  when the RTC view is stale. The old timed fallback is removed.
- Bridge participant disconnect immediately cancels greeting/warmup work and
  invokes public SDK shutdown(drain=False). Review caught that cancelling a say
  awaiter alone does not stop SDK-owned audio on transport failures; a new failing
  regression was fixed. All new recovery regressions were watched RED->GREEN.
- Full suite **192 passed**, 36.72 s. Actual normal-worker delayed-ready test:
  no speech before ready; first audio **0.623 s** after the signal; early stop cue
  and both LEMON label reads passed. Video: 472 frames / 116 distinct samples at
  480x640. Evidence: `data/warm-room-smoke-results.json` (synthetic LiveKit media,
  excludes handset/FaceTime). Active worker logs `data/worker-bridge-readiness-v2.*.log`.
- Final handset redial remains the owner check. The website is unaffected; both
  the local agent worker and Chert dev are needed for FaceTime calls.
