# Audible call states and animated Tiresias

The owner requested audible state feedback when an interruption leaves silence,
and replacement of the static blue FaceTime card with a talking/thinking avatar.
Keep the current voice/vision pipeline and saved caller preferences.

## Approach

Use a small per-call feedback controller and a locally played animated portrait.
The controller derives connecting/listening/thinking/speaking/ended from real
user speech, application work and SDK audio state. Work generations prevent a
cancelled old request from restoring the wrong state. Spoken cues are sparse,
wait for caller silence, and do not enter the model's conversation history.

- Stop/wait/hold-on: interrupt output, then “I'm listening.”
- A meaningful new question interrupts active speech/work: “Got it” while the
  replacement request runs. Positive backchannels still do not cancel answers.
- Processing lasts longer than 1.5 seconds: one brief “Taking a look” cue. An
  already acknowledged label request gets a later “Still checking” cue instead.
  Fast answers cancel pending cues. If a cue already started, finish the short
  cue before the answer; user interruption cancels both. Rate-limit reminders.
- Visual listening state follows speech detection immediately, but speech is not
  added over the caller merely because a VAD event fired.

Create a calm illustrated seer with a laurel/halo motif, warm background and
high-contrast labels. Listening has gentle receptive arcs; thinking has orbiting
dots; speaking animates mouth/wave bars. Render at approximately 10 fps on the
same LiveKit participant that publishes agent audio. Use background rendering,
bound task ownership and close the animation on disconnect. No external avatar
provider, additional inference calls, camera images or voice change is needed.

Owner update: use Higgsfield to generate a consistent original character and
matching listening/thinking/speaking loops, and use it on the existing website
as well. The connected account's available unlimited allowance covers generation;
all requests explicitly use that allowance and must never fall back to credits.
Download completed assets into public static/avatar and play them locally; no
Higgsfield service or generation runs during a call. Keep the procedural renderer
as a fallback if assets are absent or invalid. Website motion is opt-in through
voice preview; respect reduced motion with the still master image. The public
sign-in page and signed-in call card use that same master character.

Alternatives: announcing every VAD transition would compete with the caller;
silence plus animation alone fails the user's accessibility need. An external
photorealistic avatar adds provisioning, latency and failure modes before the
deadline. The chosen implementation is a bounded extension of the existing
Pillow status-video path, and can be previewed locally before a real call.

## Validation

Test cues after stop, interruption acknowledgment, quiet gating, fast-answer
suppression, stale-work cancellation, cooldown and disconnect. Preserve repeat,
backchannel, caller profile and vision tests. Render and inspect a contact sheet
and GIF; verify actual published video changes states in an isolated LiveKit
call while returned answer audio remains correct. Finish with a handset test.
