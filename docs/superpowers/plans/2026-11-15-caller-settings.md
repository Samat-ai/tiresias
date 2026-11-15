# Caller settings implementation plan

> **For agentic workers:** Use superpowers:executing-plans inline. The owner
> delegated implementation choices in the request to remember settings by number.

**Goal:** One-time caller verification followed by automatic voice preferences
on later FaceTime calls.

**Architecture:** Existing FastAPI, Tiger Data and local LiveKit worker. A
separate voice-only caller link uses authenticated Chert call identity; one-time
inbound spoken challenge links it to the signed-in account.

**Spec:** `docs/superpowers/specs/2026-11-15-caller-settings-design.md`

## Constraints and review focus

No raw phone storage, no identity from client metadata, no SMS/outbound calls,
no reuse of profile codes for authentication. Preserve unknown-caller usability.
Check concurrent confirmation, unlink during a call, stale provider calls,
web/session isolation and expired code retries.

## Task 1: Durable voice-only caller links

- [x] Add failing database tests for request/challenge/confirmation, code
  attempts/expiry/replay, isolation and unlink, then implement migration 004 and
  `caller_links.py` with keyed fingerprints and masked displays.
- [x] Add failing mocked-HTTP tests, then implement a local authenticated Chert
  resolver that validates exact call/project/status and never logs credentials.
- [x] Run focused tests. Expected: all pass with no application DB reset.

## Task 2: Web setup and runtime automatic loading

- [x] Add failing auth/CSRF web tests and runtime auto-load tests.
- [x] Add accessible connect/verify/disconnect controls to existing settings UI;
  wire the worker to speak a challenge and apply verified settings automatically.
- [x] Run full suite. Expected: all pass; explicit profile fallback still works.

## Task 3: Deploy and verify

- [x] Generate a service linking secret privately; share only that new secret
  with the owner's Vultr app and local worker, without exposing credentials.
- [x] Apply additive migration, deploy web, restart worker, verify public pages
  and existing conversation smoke. Record evidence and limitations in ledger.
- [ ] Have owner initiate one setup call and one later call from same identity.
  This final real-call step cannot be replaced with an offline unit test.
