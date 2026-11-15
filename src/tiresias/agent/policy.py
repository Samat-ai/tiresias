from __future__ import annotations

import json
import re

from pydantic import ValidationError

from tiresias.contracts import (
    EvidenceDecision,
    EvidenceKind,
    FrameRef,
    IntentKind,
    MatchProposal,
    Observation,
    Quality,
    TargetSpec,
    TaskContext,
    UserIntent,
)

EXCLUDED_PATTERNS = (
    r"\bdos(?:e|ing)\b",
    r"\bmilligrams?\b",
    r"\bhow many pills\b",
    r"\bcross(?:ing)? the street\b",
    r"\bstreet crossing\b",
    r"\ballergy guarantee\b",
)
INSTRUCTION_MARKERS = ("ignore rules", "ignore previous", "system prompt", "you are now")

_META_OR_GREETING = re.compile(
    r"\b(?:what|who|why|how|hello|hi|hey|thanks|thank|please|ok|okay|sure|"
    r"yeah|yep|yes|no|nope|uhm|um|uh)\b"
)
_HELP_SEEING = re.compile(
    r"\b(?:be my eyes|help me see|help me look|help me read|i can'?t see|"
    r"what can you (?:do|see|help with)|use (?:the )?camera|"
    r"read (?:the )?labels? for me)\b"
)
_HELP_SEEING_WITH_TARGET = re.compile(
    r"\b(?:help me (?:see|look(?: at)?|read)|be my eyes (?:for|on|with)|"
    r"i can'?t see)\s+(.+)$"
)
_CHECK = re.compile(
    r"\b(?:"
    r"check(?:\s+this|\s+it|\s+that)?"
    r"|look at (?:this|that|it)"
    r"|is this (?:it|the one|right|correct|my .+)?"
    r"|confirm(?: this| that)?"
    r"|verify(?: this| that)?"
    r"|read (?:this|that|it)"
    r"|what(?:'s| is) (?:on )?(?:this|that)(?: label)?"
    r"|what am i (?:holding|looking at)"
    r"|does this (?:match|say)"
    r"|take a look"
    r")\b"
)
_ASK_PERSON = re.compile(
    r"\b(?:ask (?:a )?person|ask someone|get a person|get (?:a )?human|"
    r"need a (?:person|human|helper)|call (?:a )?helper)\b"
)
_FIND = re.compile(
    r"\b(?:"
    r"(?:can you |could you |please )?(?:find|locate|spot|get me|grab)"
    r"|(?:look|search|hunt) for"
    r"|help me (?:find|locate|get|spot)"
    r"|i(?:'?m| am) looking for"
    r"|i need(?: to find)?"
    r"|where(?:'s| is)"
    r"|show me"
    r"|looking for"
    r"|find me"
    r"|read(?: me)?(?: the)?"
    r"|see if (?:you )?(?:can )?(?:find|see)"
    r"|can you see"
    r"|help me with"
    r")\s+(.+)$"
)
_CHANGE = re.compile(
    r"\b(?:change(?:\s+to)?|switch(?:\s+to)?|actually(?:\s+find)?|instead|"
    r"never ?mind[, ]*(?:find|look for)?|different(?: one)?)\s+(.+)$"
)


def route_utterance(text: str, task: TaskContext | None, pending_prompt_id: str | None = None) -> UserIntent:
    """Heuristic intent router (also used as Gemini fallback)."""
    raw = text.strip()
    norm = re.sub(r"\s+", " ", raw.lower())
    if _excluded(norm):
        return UserIntent(kind=IntentKind.UNSUPPORTED, transcript=raw)
    if norm in {"stop", "stop talking", "quiet", "cancel"} or norm.startswith("stop "):
        return UserIntent(kind=IntentKind.STOP, transcript=raw)
    if norm in {"repeat", "say that again", "what did you say"}:
        return UserIntent(kind=IntentKind.REPEAT, transcript=raw)
    if norm in {"slower", "slow down"}:
        return UserIntent(kind=IntentKind.SLOWER, transcript=raw)
    if norm in {"faster", "speed up"}:
        return UserIntent(kind=IntentKind.FASTER, transcript=raw)
    if pending_prompt_id and norm in {"yes", "yes share", "share it", "i consent"}:
        return UserIntent(kind=IntentKind.CONSENT_ACCEPT, transcript=raw, pending_prompt_id=pending_prompt_id)
    if pending_prompt_id and norm in {"no", "no thanks", "don't share", "do not share"}:
        return UserIntent(kind=IntentKind.CONSENT_DECLINE, transcript=raw, pending_prompt_id=pending_prompt_id)
    if _ASK_PERSON.search(norm):
        return UserIntent(kind=IntentKind.ASK_PERSON, transcript=raw)
    if _CHECK.search(norm):
        return UserIntent(kind=IntentKind.CHECK, transcript=raw)

    change = _CHANGE.search(norm)
    if change:
        label = _clean_label(change.group(1))
        if label:
            kind = IntentKind.CHANGE_TARGET if task is not None and task.target is not None else IntentKind.FIND_TARGET
            return UserIntent(kind=kind, transcript=raw, target=_target_from_label(label))

    help_target = _HELP_SEEING_WITH_TARGET.search(norm)
    if help_target:
        label = _clean_label(help_target.group(1))
        if label:
            return UserIntent(kind=IntentKind.FIND_TARGET, transcript=raw, target=_target_from_label(label))

    find = _FIND.search(norm)
    if find:
        label = _clean_label(find.group(1))
        if label and not _HELP_SEEING.fullmatch(label):
            return UserIntent(kind=IntentKind.FIND_TARGET, transcript=raw, target=_target_from_label(label))

    if _HELP_SEEING.search(norm):
        return UserIntent(kind=IntentKind.ASK_CLARIFICATION, transcript=raw)

    # After greeting, a short noun phrase is treated as the item to find.
    if task is not None and task.target is None and 1 <= len(norm.split()) <= 8:
        if not _META_OR_GREETING.search(norm) and not _HELP_SEEING.search(norm):
            return UserIntent(kind=IntentKind.FIND_TARGET, transcript=raw, target=_target_from_label(norm))
    return UserIntent(kind=IntentKind.ASK_CLARIFICATION, transcript=raw)


def clarification_speech(task: TaskContext | None) -> str:
    if task is None or task.target is None:
        return "What should I look for? Name the product, or hold a label up and say check this."
    label = task.target.requested_label
    return f"Want me to keep looking for {label}, check this label, or look for something else?"


def _clean_label(label: str) -> str:
    cleaned = label.strip(" .,!?")
    cleaned = re.sub(
        r"^(?:the |a |an |my |some |for me |please |this |that )+",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"\b(?:for me|please|thanks|thank you)\b", "", cleaned, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", cleaned).strip(" .,!?")


def _target_from_label(label: str) -> TargetSpec:
    cleaned = _clean_label(label) or label.strip()[:200]
    terms = [part for part in re.split(r"[^a-z0-9]+", cleaned.lower()) if len(part) > 2][:10]
    return TargetSpec(requested_label=cleaned[:200], required_terms=terms)


def _excluded(text: str) -> bool:
    return any(re.search(pattern, text) for pattern in EXCLUDED_PATTERNS)


def parse_observation(payload: object, frame_id: str) -> Observation:
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            return _uncertain(frame_id)
    if not isinstance(payload, dict):
        return _uncertain(frame_id)
    try:
        observation = Observation.model_validate(payload)
    except ValidationError:
        return _uncertain(frame_id)
    for span in observation.visible_text:
        if len(span) > 300:
            return _uncertain(frame_id)
    return observation


def _uncertain(frame_id: str) -> Observation:
    return Observation(
        frame_id=frame_id,
        quality=Quality.UNKNOWN,
        uncertainties=["malformed model output"],
        match_proposal=MatchProposal.UNKNOWN,
    )


def decide(
    task: TaskContext,
    frame: FrameRef,
    observation: Observation,
    *,
    stage: str,
    now_monotonic: float,
    max_age_ms: int = 5000,
) -> EvidenceDecision:
    base = dict(
        visible_text=list(observation.visible_text),
        frame_id=frame.frame_id,
        scene_epoch=frame.scene_epoch,
        generation=task.generation,
        analysis_revision=task.analysis_revision,
    )
    joined = " ".join(observation.visible_text).lower()
    if _excluded(joined) or any(tag.lower() in {"dosing", "crossing", "medical"} for tag in observation.risk_tags):
        return EvidenceDecision(kind=EvidenceKind.UNSUPPORTED, reason="excluded request", **base)
    if observation.frame_id != frame.frame_id:
        return EvidenceDecision(kind=EvidenceKind.UNCERTAIN, reason="frame id mismatch", **base)
    age_ms = (now_monotonic - frame.received_monotonic) * 1000
    if age_ms > max_age_ms:
        return EvidenceDecision(kind=EvidenceKind.UNCERTAIN, reason="evidence expired", **base)
    if any(marker in joined for marker in INSTRUCTION_MARKERS):
        return EvidenceDecision(kind=EvidenceKind.UNCERTAIN, reason="image instruction ignored", **base)

    usable_text = _usable_label_text(observation)
    if not usable_text:
        if observation.quality in {Quality.BLURRY, Quality.TOO_SMALL, Quality.OCCLUDED}:
            return EvidenceDecision(kind=EvidenceKind.NEED_VIEW, reason=observation.quality.value.lower(), **base)
        if observation.quality == Quality.UNKNOWN and observation.uncertainties:
            return EvidenceDecision(kind=EvidenceKind.UNCERTAIN, reason="uncertain observation", **base)
        return EvidenceDecision(kind=EvidenceKind.NEED_VIEW, reason="incomplete text", **base)

    # Soft model hedges (glare/motion) must not discard quoted label text.
    base["visible_text"] = usable_text
    if stage != "recheck":
        return EvidenceDecision(kind=EvidenceKind.CANDIDATE, reason="candidate stage cannot match", **base)
    observation_with_text = observation.model_copy(update={"visible_text": usable_text})
    if _terms_present(task, observation_with_text) and not _excluded_terms_visible(task, observation_with_text):
        return EvidenceDecision(kind=EvidenceKind.MATCH, reason="readable recheck label", **base)
    return EvidenceDecision(kind=EvidenceKind.MISMATCH, reason="visible contradiction", **base)


def _usable_label_text(observation: Observation) -> list[str]:
    spans = [span.strip() for span in observation.visible_text if span and span.strip()]
    if not spans:
        return []
    if observation.quality == Quality.OCCLUDED and len(" ".join(spans)) < 3:
        return []
    # BLURRY/TOO_SMALL/UNKNOWN with quoted text is still usable for demos.
    return spans


def _terms_present(task: TaskContext, observation: Observation) -> bool:
    if task.target is None:
        return False
    blob = " ".join(observation.visible_text).lower()
    return all(term.lower() in blob for term in task.target.required_terms)


def _excluded_terms_visible(task: TaskContext, observation: Observation) -> bool:
    if task.target is None:
        return False
    blob = " ".join(observation.visible_text).lower()
    return any(term.lower() in blob for term in task.target.excluded_terms)


def speech_for(decision: EvidenceDecision, task: TaskContext) -> str:
    label = task.target.requested_label if task.target else "that item"
    shown = ", ".join(decision.visible_text[:4])
    if decision.kind == EvidenceKind.MATCH:
        return f"This one says {shown}."
    if decision.kind == EvidenceKind.MISMATCH:
        return f"That's not {label}. Show me the one you meant."
    if decision.kind == EvidenceKind.CANDIDATE:
        if shown:
            return f"I can see {shown}. Hold the name still and say check this."
        return f"Might be {label}. Hold the name still and say check this."
    if decision.kind == EvidenceKind.NEED_VIEW:
        if shown:
            return f"I partly see {shown}. Hold the name still for a clearer look."
        return "I need a clearer look at the label — hold it steady."
    if decision.kind == EvidenceKind.UNSUPPORTED:
        return "I can't help with dosing or crossing. I can read a regular product label though."
    if decision.reason == "evidence expired":
        return "That view's gone. Hold it still and try again."
    return "Not sure on this one. Hold it steady, or ask a person."
