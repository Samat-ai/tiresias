# Deadline Completion Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan
> inline, task by task. Do not delegate without applicable authorization. Steps
> use checkbox syntax for tracking. Read the audit before starting.

**Goal:** Deliver a working FaceTime product assistant with genuine, demonstrable
use of the eight selected tracks and a complete submission before noon CST.

**Architecture:** Retain the Python LiveKit worker and verified Vertex ADC path.
Add a small FastAPI operator interface and asynchronous Tiger Data telemetry;
connect existing consent/review/outbox logic to a real devnet payout. Host the
operator service on Vultr while preserving the working local caller bridge.

**Tech Stack:** Python, LiveKit, Chert, Google Gen AI SDK/Vertex, ElevenLabs,
FastAPI/Jinja, PostgreSQL/Timescale, solders/solana, Vultr, Grok Bot.

**Spec:** `docs/PROGRESS-AUDIT.md`; original blueprint in Downloads is background,
with narrower R0 exclusions from `docs/HANDOFF.md` retained.

## Global Constraints

- Final live Devpost deadline: November 15, 2026 noon CST; plan to finish edits by 11 a.m.
- Feature freeze: 10 a.m.; preserve at least two hours for release/demo recovery.
- Required video length: 30 seconds to 2 minutes. In-person pitch: 3 minutes plus 2-minute Q&A.
- Eight target tracks only: General, Chert, Gemini, ElevenLabs, Tiger Data, Solana, Vultr, SpaceXSI.
- iMessage is optional for Chert. MongoDB/GoDaddy are not required for this selection.
- Ordinary product labels; no dosing/crossing advice. Human answers are literal snapshot readings.
- No provider/chain mocks presented as real integrations; rewards remain devnet only.
- Never commit secrets, ADC files, wallet keys, call logs or private images.
- Database/payment work must not block the media event loop.

## Review Focus

- Repeated identical speech, interrupted analysis and stale image results must not produce wrong or late replies.
- Missing words and substrings must not establish a product match; unreadable input must yield a useful limited answer.
- Missing/slow telemetry or RPC must leave speech usable and payment status truthful.
- Consent decline/revocation and disconnected calls must not leak snapshots or replay old answers.
- Double-clicks, worker retries and ambiguous transaction sends must not issue duplicate bounties.

## Task 1: Final caller gate and release baseline

**Files:** `scripts/smoke_live_media.py`, `tests/test_runtime.py`,
`src/tiresias/agent/main.py`, `docs/provider-capabilities.md`.

**Interfaces:** Existing `entrypoint(ctx)` and `VisionClient.analyze_frame(frame, target)`;
produces a recorded readiness check and preserves the current working pipeline.

- [x] Run complete suite: 77 passed after whole-word matching regression fix.
- [x] Run real isolated media smoke; two repeated commands return label audio.
- [ ] On an iPhone call the Chert line; read two actual products, repeat the same
  command, change the target, interrupt and stop. Record camera dimensions,
  provider duration and time from end of speech to useful returned audio.
- [ ] Inspect small-print failure against actual incoming dimensions before
  changing JPEG settings. High simulcast selection alone did not raise the
  isolated 320×180 input; keep this unresolved until measured.
- [ ] Add runtime regression tests only for any newly reproduced failures.
- [ ] Commit tested rescue source and docs, excluding unrelated/local files.

## Task 2: Bounded conversational visual responses

**Files:** Modify `src/tiresias/contracts.py`, `agent/intent.py`, `agent/main.py`,
`agent/vision.py`, `agent/policy.py`; create `agent/conversation.py`;
test `tests/test_conversation.py` and existing runtime/turn suites.

**Interfaces:** Add `GroundedReply` with `text: str`, `frame_id: str`, and
`needs_view: bool`. Add
`respond(frame: FrameRef, question: str, context: list[dict]) -> GroundedReply`.
Keep deterministic stop/repeat and the existing explicit product-match policy.

- [ ] First test: a question about a current label quotes available words; a
  follow-up uses recent conversational context but never claims to see an old
  frame. Assert no response from a canceled turn reaches `speak`.
- [ ] Run tests and confirm failures before implementing the interface.
- [ ] Use one multimodal model request per visual question, including the current
  question and at most six recent text turns. Limit response to two short
  sentences; ask one specific camera adjustment when needed. Preserve literal
  evidence for product confirmations. Do not add a separate rewrite-model call.
- [ ] Test ordinary noun descriptions, a readable label, an unreadable label,
  a question without a current frame, and interruption. Keep requests within the
  call budget and timeout.
- [ ] Repeat isolated smoke and one real FaceTime test; commit only when both
  the label path and new conversational questions pass.

## Task 3: Tiger Data telemetry and operator dashboard

**Prerequisite:** A real application `DATABASE_URL`; use a separate `_test` DB
for tests. Prefer a Tiger Data managed service for clear sponsor evidence.

**Files:** Create `src/tiresias/telemetry.py`, `app.py`, `migrate.py`,
`templates/operator.html`; modify `agent/main.py`, `config.py`, `pyproject.toml`;
test `tests/test_telemetry.py`, `tests/test_app.py`.

**Interfaces:** `record_stage_event(conn, **event)` already exists.
Add `emit_stage(event: dict) -> None` as a bounded nonblocking enqueue operation;
add `GET /healthz` and authenticated `GET /operator` with latency/outcome queries.

- [ ] Test bounded telemetry delivery, DB timeout recovery, and that speech
  continues when the telemetry sink fails. Use the real test hypertable.
- [ ] Implement worker-side queued inserts with stage events tied to a DB call
  UUID; do not insert the current non-UUID room epoch into UUID columns.
- [ ] Implement the missing migration entry point with explicit application URL;
  retain the test harness's protection against resetting an application DB.
- [ ] Add dashboard counts, recent outcomes and actual latency queries. Use
  existing Timescale continuous aggregate where it helps; do not invent metrics.
- [ ] Verify the dashboard requires an operator session; public health returns
  only a health status. Never expose raw caller media in a public metrics route.
- [ ] Make a real call and show newly persisted events and a dashboard update;
  record Tiger Data service/extension evidence and commit.

## Task 4: Complete consented human review

**Files:** Modify `agent/main.py`, `agent/controller.py`, `reviews.py`, `app.py`;
create `jobs.py`, `templates/review.html`; test `tests/test_review_runtime.py`.

**Interfaces:** Consume existing `create_review`, `read_snapshot`,
`complete_review`, `enqueue_job`, `claim_jobs`. Add authenticated
`POST /reviews/{review_id}/complete`. Deliver the existing outbox result only to
the matching live call generation.

- [ ] Test pending prompt propagation: “ask a person” then “yes” creates one
  consented review; “no” creates none. Test revocation, stale generations and
  disconnect during completion.
- [ ] Create DB records for an enrolled demo caller/helper, persist only the
  pinned consented snapshot, and connect the helper UI to existing review logic.
  Do not expose unfinished phone-enrollment/XOR protection in the public demo.
- [ ] Implement an outbox runner with bounded leases and generation-aware
  delivery; speak the literal reviewed text rather than a generic “readable”.
- [ ] If this slice cannot finish, remove the misleading help offer and mark the
  feature unavailable; do not claim a live helper or review-based bounty.
- [ ] Demo caller consent -> helper review -> same caller receives result; commit.

## Task 5: Real Solana devnet reward

**Prerequisite:** Funded devnet treasury key file and helper public wallet;
store the private key outside version control. No mainnet funds.

**Files:** Create `src/tiresias/solana_rpc.py`, `scripts/probe_solana.py`;
modify `rewards.py`, `jobs.py`, review template; test `tests/test_solana_rpc.py`.

**Interfaces:** Preserve `DevnetRewardService`'s injected signer/RPC contract.
Implement `sign(payout_id, recipient, lamports) -> dict` returning actual signed
bytes, base58 signature and validity height; RPC provides `send(bytes)` and
`status(signature)` with known-vs-ambiguous failure distinctions.

- [ ] Test real serialized transaction structure using a generated local key,
  configured recipient/amount/network, and duplicate outbox retries. Test an
  ambiguous send does not create a second transaction.
- [ ] Implement with solders/solana and retain the existing DB idempotency guards.
  Keep `DeterministicSigner` limited to tests.
- [ ] Complete one real helper review and confirm exactly one devnet transfer;
  show the signature/explorer link and make network/status explicit in the UI.
- [ ] Verify one repeat click creates no second payment; commit proof tooling.

## Task 6: Vultr deployment

**Prerequisite:** User's Vultr VM/SSH access and desired hostname or HTTPS route.

**Files:** Create `deploy/tiresias-web.service`, `deploy/Caddyfile`,
`deploy/README.md` and a bounded deployment script/configuration.

**Interfaces:** Host the FastAPI app from Tasks 3–4; connect to the same Tiger
Data database. The existing local FaceTime worker can remain local for judging.

- [ ] Prepare a concrete deployable revision and service definitions; health
  check and verify dashboard login locally before external deployment.
- [ ] Deploy the web service to the user's Vultr instance, supplying secrets
  through server environment configuration. Use HTTPS for authenticated pages.
- [ ] Verify from outside the VM: health, login, real recent call telemetry and
  authorized review. Record VM/provider evidence and the working URL.
- [ ] Preserve the working local bridge; document restart/rollback and commit.

## Task 7: SpaceXSI Grok Bot workflow

**Prerequisite:** Actual Grok Bot automation destination/credentials. A generic
Grok text-completion API alone must not be mislabeled as Grok Bot automation.

**Files:** Create `scripts/notify_grok.py`, `docs/WORKFLOW-EVIDENCE.md`.

**Interfaces:** `notify_grok(report: dict, *, dry_run: bool = True) -> dict`;
report includes only test/readiness counts and project links, never caller data.

- [ ] Test report redaction and failure handling; prepare a dry-run report from
  the actual verification output.
- [ ] Connect a genuine Grok Bot automation in the team's workflow. Sending a
  message requires explicit user authorization for that destination.
- [ ] Record the real execution and useful outcome; document Cursor's actual
  role and additional tools truthfully. Do not manufacture a prior workflow.
- [ ] Add both workflow descriptions to Devpost and select the SpaceXSI raffle
  opt-in during submission editing; commit evidence docs.

## Task 8: Freeze, upload and submission

**Files:** Create/update `README.md`, `docs/SUBMISSION.md`,
`docs/DEMO-CHECKLIST.md`, provider ledger and final plan checkboxes.

- [ ] Reserve the final two hours. Re-run full tests and the live handset gate
  after the last source change; freeze features by 10 a.m.
- [ ] Upload the exact tested code to the linked GitHub repository before the
  deadline. Verify remote head and judge access; keep credentials/images local.
- [ ] Record a 30s–2min video of working features. Rehearse a 3min live pitch and
  2min Q&A. Bring an iPhone and demonstrate an actual Chert FaceTime call.
- [ ] Include exact Devpost heading **How We Used ElevenLabs**, models/features,
  genuine sponsor usage, the Tiresias/Odyssey story, and accurate limitations.
- [ ] Show a real transaction and real data/hosting/workflow only where proven.
  Confirm track selections and raffle opt-in in the existing initial submission.
- [ ] Aim to finish final Devpost edits by 11 a.m.; verify saved artifacts and
  leave the remaining time for network/judging recovery.

## Scheduling and resource gates

Budget roughly 45 minutes for Task 1, 60–90 minutes for Task 2, 90 minutes for
Task 3, 60–90 minutes for Task 4, 60 minutes for Task 5, 60 minutes for Task 6,
30 minutes for Task 7, with final release time protected. These are planning
estimates and depend on services/credentials already being available. Request
resource status early; build/test adapters locally while account setup proceeds.
If the budget slips, protect core reliability and truthful evidence; do not
claim eight completed integrations merely because eight tracks were selected.
