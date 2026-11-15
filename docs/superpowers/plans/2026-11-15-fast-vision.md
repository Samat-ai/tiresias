# Fast vision implementation plan

> **For agentic workers:** Use superpowers:executing-plans inline; one fresh final
> review of this feature. Implement the owner's requested optimization and guide
> within the existing working Python/Vertex pipeline.

**Goal:** Faster answer audio and better frame choice without stale label matches.
**Spec:** docs/superpowers/specs/2026-11-15-fast-vision-design.md

## Task 1: Frame quality and request tuning

- [x] Write failing tests for sharpness/scene scoring, bounded recent selection,
  unscored newest fallback, resolution routing and 3.8 low thinking.
- [x] Add measured frame features and scene JPEG preparation in media.py; carry
  quality/signature in frame contracts; update capture sampling/queue/timestamps.
- [x] Apply high-resolution label/low-resolution scene configuration; verify tests.

## Task 2: Speech-first conversation

- [x] Write failing parser/provider/runtime tests for split delimiters, metadata
  exclusion, invalid speech, cancellation and no duplicate error after speaking.
- [x] Add a bounded streaming parser and cancellable async bridge over the
  existing synchronous provider client; stream one complete grounded answer.
- [x] Wire runtime while preserving strict label policy and explicit recheck;
  measure completed-turn-to-audio separately from model speech readiness.

## Task 3: Review and measure

- [x] Run all tests, review feature, fix Important/Critical findings with regressions.
- [x] Restart worker; real generated-scene conversation/backchannel and label
  smokes pass. Rerun benchmark and record accuracy/latency limits honestly.
- [x] Update ledger/docs, save a local commit, ask for handset comparison.

## Review focus

Old sharp frames after an object changes; capture timestamp correctness;
chunk/thread completion racing cancellation; model tail failure after speech;
scene low-resolution routing accidentally degrading small print.
