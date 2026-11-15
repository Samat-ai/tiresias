# Remember voice settings by verified FaceTime caller

The owner requested automatic settings on later calls, because speaking an
eight-digit profile code is burdensome for a visually impaired caller. Existing
settings already persist in hosted Tiger Data; caller-to-account linking is the
missing piece. Chert's live authenticated GET call API was inspected and returns
`from: {type, value}` for the project's calls. LiveKit metadata alone is not proof.

## Approach and user experience

Use the signed-in website to request a link to a phone number or FaceTime email.
During an inbound call from that identity, the worker reads a four-digit setup
code. Enter that code on the website once. Subsequent calls load voice, tone and
speed automatically. The user can disconnect the identity from their account.

This is the implementation choice delegated by the user's request. Alternatives:
silently trusting a typed number permits claiming somebody else's preferences;
asking for the existing profile code on every call defeats the accessibility
requirement. SMS would add another provider and outbound messages. The chosen
flow verifies possession through the call the user initiates, with no SMS.

## Trust and storage

Resolve only the exact UUID on the Chert bridge participant, using the existing
local CLI credential against its allowlisted Chert origin and project. Validate
call ID, project, inbound direction, live state and recent creation. Do not use
a participant display name, claimed phone metadata, or a spoken number as proof.
No Chert credential is sent to Vultr.

Use separate voice-link tables, never the legacy phone-auth/XOR path. Store a
keyed HMAC of the normalized handle plus a masked display; do not retain the raw
phone/email. A new random service secret is shared by the local worker and Vultr
web configuration. Setup codes are hashed, expire after five minutes, allow at
most five failed tries, and are bound to one user, request and provider call.
The worker temporarily retains a code only to speak/repeat it. Confirmation is
authenticated and CSRF-protected; unknown/expired identities keep the default
voice. Unlink stops future automatic selection. No private review or payment
authorization is derived from a voice link.

## Verification

Pin normalization, masking, wrong/expired/replayed codes, account isolation,
one-caller ownership, removal and separate-call persistence with database tests.
Pin provider ID/project/state validation and credential redaction with mocked
HTTP. Test automatic voice selection at the runtime boundary without a spoken
profile. Verify the deployed accessible web flow. An actual handset setup and
second call are the final user-operated proof; do not fabricate that evidence.
