from __future__ import annotations

import json
import logging
import re
from typing import Any

from google import genai
from google.genai import types

from tiresias.agent.policy import _excluded, _target_from_label, route_utterance
from tiresias.agent.google_backend import create_client
from tiresias.contracts import IntentKind, TaskContext, UserIntent

logger = logging.getLogger("tiresias.agent.intent")

DEFAULT_MODEL = "gemini-3.5-flash-lite"

_VALID_KINDS = {
    "STOP": IntentKind.STOP,
    "REPEAT": IntentKind.REPEAT,
    "SLOWER": IntentKind.SLOWER,
    "FASTER": IntentKind.FASTER,
    "CHECK": IntentKind.CHECK,
    "FIND_TARGET": IntentKind.FIND_TARGET,
    "CHANGE_TARGET": IntentKind.CHANGE_TARGET,
    "ASK_PERSON": IntentKind.ASK_PERSON,
    "ASK_CLARIFICATION": IntentKind.ASK_CLARIFICATION,
    "UNSUPPORTED": IntentKind.UNSUPPORTED,
}

_SCHEMA_HINT = {
    "kind": "|".join(_VALID_KINDS),
    "target_label": "string or null — product/item name when finding or changing",
    "confidence": "number 0 to 1",
}


class IntentClassifier:
    """Route controls locally; send other questions to grounded conversation."""

    def __init__(self, api_key: str = "", model: str = "", timeout_seconds: float = 10.0,
                 *, vertexai: bool = False, project: str = "", location: str = "global") -> None:
        self.model = model or DEFAULT_MODEL
        # Gemini rejects http deadlines under 10s.
        self.timeout_seconds = max(float(timeout_seconds), 10.0)
        self._api_key = api_key
        self._backend = dict(vertexai=vertexai, project=project, location=location)
        self._client: genai.Client | None = None

    def route(
        self,
        text: str,
        task: TaskContext | None,
        pending_prompt_id: str | None = None,
    ) -> UserIntent:
        raw = text.strip()
        if not raw:
            return UserIntent(kind=IntentKind.ASK_CLARIFICATION, transcript=raw)
        norm = re.sub(r"\s+", " ", raw.lower()).strip(' .!?')
        if _excluded(norm):
            return UserIntent(kind=IntentKind.UNSUPPORTED, transcript=raw)

        # Consent + exact controls stay deterministic; Gemini never owns them.
        control = _fast_controls(norm, raw, pending_prompt_id)
        if control is not None:
            return control

        if norm.strip(' .!?') in {
            'yes', 'yeah', 'yep', 'okay', 'ok', 'sure', 'no', 'no thanks',
            'hello', 'hi', 'hey', 'hello there', 'thanks', 'thank you',
            'да', 'нет', 'привет', 'спасибо', 'хорошо',
        }:
            return UserIntent(kind=IntentKind.SOCIAL, transcript=raw)

        # Do not turn non-English questions into the bare-noun product shortcut.
        if re.search(r'[а-яё]', norm):
            return UserIntent(kind=IntentKind.CONVERSATION, transcript=raw)

        # Prefer fast heuristics for clear find/check/change so vision is not
        # blocked behind a second Gemini round-trip on every turn.
        heuristic = route_utterance(raw, task, pending_prompt_id)
        if heuristic.kind != IntentKind.ASK_CLARIFICATION:
            return heuristic

        # Unknown questions go directly to one grounded multimodal request.
        # A text-only classifier must never invent sharing/consent or refusals.
        return UserIntent(kind=IntentKind.CONVERSATION, transcript=raw)

    def _classify_gemini(self, raw: str, task: TaskContext | None) -> UserIntent | None:
        if self._client is None:
            self._client = create_client(self._api_key, **self._backend)
        has_target = bool(task and task.target)
        current = task.target.requested_label if task and task.target else None
        prompt = (
            "Classify a FaceTime label-assistant utterance. JSON only.\n"
            "Kinds: FIND_TARGET, CHANGE_TARGET, CHECK, ASK_PERSON, ASK_CLARIFICATION, "
            "STOP, REPEAT, SLOWER, FASTER, UNSUPPORTED.\n"
            "FIND/CHANGE need target_label. CHECK = verify current camera label.\n"
            f"Current target: {current or 'none'}; has_target={has_target}.\n"
            f"Utterance: {raw}\n"
            f"Schema: {json.dumps(_SCHEMA_HINT)}"
        )
        response = self._client.models.generate_content(
            model=self.model,
            contents=[prompt],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                max_output_tokens=256,
                thinking_config=(
                    types.ThinkingConfig(thinking_level="minimal")
                    if self.model.startswith("gemini-3")
                    else types.ThinkingConfig(thinking_budget=0)
                ),
                http_options=types.HttpOptions(timeout=int(self.timeout_seconds * 1000)),
            ),
        )
        payload = _extract_json(response)
        return intent_from_payload(payload, raw, task)


def intent_from_payload(payload: object, transcript: str, task: TaskContext | None) -> UserIntent | None:
    if not isinstance(payload, dict):
        return None
    kind_raw = str(payload.get("kind", "")).strip().upper()
    kind = _VALID_KINDS.get(kind_raw)
    if kind is None:
        return None
    try:
        confidence = float(payload.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    if confidence < 0.45 and kind not in {IntentKind.UNSUPPORTED, IntentKind.STOP}:
        return None

    label = payload.get("target_label")
    label_text = str(label).strip() if label is not None else ""
    if label_text and _excluded(label_text.lower()):
        return UserIntent(kind=IntentKind.UNSUPPORTED, transcript=transcript)

    if kind in {IntentKind.FIND_TARGET, IntentKind.CHANGE_TARGET}:
        if not label_text:
            # "help me see" with no product → clarify rather than invent a target
            return UserIntent(kind=IntentKind.ASK_CLARIFICATION, transcript=transcript)
        if kind == IntentKind.CHANGE_TARGET and task is not None and task.target is None:
            kind = IntentKind.FIND_TARGET
        return UserIntent(kind=kind, transcript=transcript, target=_target_from_label(label_text[:200]))

    if kind == IntentKind.UNSUPPORTED:
        return UserIntent(kind=IntentKind.UNSUPPORTED, transcript=transcript)

    return UserIntent(kind=kind, transcript=transcript)


def _fast_controls(norm: str, raw: str, pending_prompt_id: str | None) -> UserIntent | None:
    if norm in {"stop", "stop talking", "quiet", "cancel", "wait", "hold on", "pause", "listen"} or norm.startswith("stop "):
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
    return None


def _extract_json(response: Any) -> object:
    text = getattr(response, "text", None)
    if not text:
        raise RuntimeError("empty gemini intent response")
    return json.loads(text)


__all__ = ["IntentClassifier", "intent_from_payload"]
