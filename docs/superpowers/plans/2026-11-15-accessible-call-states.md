# Accessible call states implementation plan

> **For agentic workers:** Use superpowers:executing-plans inline, with one
> fresh review of the final feature. The owner delegated these two improvements.

**Goal:** Understandable audible states and an animated FaceTime Tiresias.
**Spec:** docs/superpowers/specs/2026-11-15-accessible-call-states-design.md

## Task 1: Feedback state and cues

- [x] Write failing feedback/runtime tests for stop/wait acknowledgment,
  quiet-gated/cancelled cues, slow processing and generation ownership.
- [x] Implement per-call feedback controller; connect SDK state and latest-turn
  lifecycle while preserving noise/backchannel behavior and private setup speech.

## Task 2: Animated video

- [x] Implement procedural fallback and generated character playback with distinct readable states;
  generate and visually inspect a GIF/contact sheet.
- [x] Publish bounded-rate frames off-loop on the agent participant; own/cancel
  the animation task and tolerate video failures without losing voice.

## Task 3: Verify and activate

- [x] Full suite and fresh feature review; fix Important/Critical findings.
- [x] Restart worker and verify state cues, changed video and repeated vision
  answers through a real isolated LiveKit call.
- [x] Save evidence and preview artifacts; see docs/CALL-STATES.md.
- [x] Use owner-requested Higgsfield artwork on the existing website; inspect
  mobile/desktop, preview playback and reduced motion; deploy and verify.
- [ ] Final owner handset/echo check: early stop, no greeting echo, visible states.
