from __future__ import annotations

from enum import Enum
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class IntentKind(str, Enum):
    STOP = "STOP"
    REPEAT = "REPEAT"
    SLOWER = "SLOWER"
    FASTER = "FASTER"
    CHECK = "CHECK"
    FIND_TARGET = "FIND_TARGET"
    CHANGE_TARGET = "CHANGE_TARGET"
    ASK_PERSON = "ASK_PERSON"
    CONSENT_ACCEPT = "CONSENT_ACCEPT"
    CONSENT_DECLINE = "CONSENT_DECLINE"
    ASK_CLARIFICATION = "ASK_CLARIFICATION"
    CONVERSATION = "CONVERSATION"
    SOCIAL = "SOCIAL"
    UNSUPPORTED = "UNSUPPORTED"


class TaskState(str, Enum):
    WAIT_TARGET = "WAIT_TARGET"
    FINDING = "FINDING"
    CANDIDATE = "CANDIDATE"
    LABEL_VIEW = "LABEL_VIEW"
    NEED_VIEW = "NEED_VIEW"
    RECHECK_SELECTION = "RECHECK_SELECTION"
    MATCH = "MATCH"
    MISMATCH = "MISMATCH"
    UNCERTAIN = "UNCERTAIN"
    REVIEW_CONSENT = "REVIEW_CONSENT"
    REVIEW_PENDING = "REVIEW_PENDING"
    COMPLETE = "COMPLETE"


class Quality(str, Enum):
    READABLE = "READABLE"
    BLURRY = "BLURRY"
    TOO_SMALL = "TOO_SMALL"
    OCCLUDED = "OCCLUDED"
    UNKNOWN = "UNKNOWN"


class MatchProposal(str, Enum):
    MATCH = "MATCH"
    MISMATCH = "MISMATCH"
    UNKNOWN = "UNKNOWN"


class EvidenceKind(str, Enum):
    CANDIDATE = "CANDIDATE"
    NEED_VIEW = "NEED_VIEW"
    MATCH = "MATCH"
    MISMATCH = "MISMATCH"
    UNCERTAIN = "UNCERTAIN"
    UNSUPPORTED = "UNSUPPORTED"


class CameraPosition(str, Enum):
    CENTER = "CENTER"
    LEFT = "LEFT"
    RIGHT = "RIGHT"
    ABOVE = "ABOVE"
    BELOW = "BELOW"
    UNKNOWN = "UNKNOWN"


class CallSource(str, Enum):
    FACETIME = "FACETIME"
    BROWSER = "BROWSER"
    REPLAY = "REPLAY"


class Role(str, Enum):
    USER = "USER"
    HELPER = "HELPER"
    OPERATOR = "OPERATOR"


class PhoneState(str, Enum):
    PENDING = "PENDING"
    OPERATOR_ASSISTED = "OPERATOR_ASSISTED"
    VERIFIED = "VERIFIED"
    BLOCKED = "BLOCKED"


class PayoutState(str, Enum):
    QUEUED = "QUEUED"
    PREPARED = "PREPARED"
    SUBMITTED = "SUBMITTED"
    CONFIRMED = "CONFIRMED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


class DeliveryState(str, Enum):
    QUEUED = "QUEUED"
    PUBLISH_STARTED = "PUBLISH_STARTED"
    PUBLISHED_TO_CALL = "PUBLISHED_TO_CALL"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"
    UNAVAILABLE = "UNAVAILABLE"
    UNKNOWN = "UNKNOWN"


class JobState(str, Enum):
    PENDING = "PENDING"
    LEASED = "LEASED"
    DONE = "DONE"
    DEAD = "DEAD"


class VerifiedCaller(StrictModel):
    user_id: str
    provider_identity: str
    binding_id: str
    verification_source: str
    verified_at: str


class TargetSpec(StrictModel):
    requested_label: str = Field(min_length=1, max_length=200)
    required_terms: list[str] = Field(default_factory=list, max_length=10)
    excluded_terms: list[str] = Field(default_factory=list, max_length=10)


class TaskContext(StrictModel):
    session_id: str
    task_id: str
    generation: int
    analysis_revision: int
    turn_id: str
    target: Optional[TargetSpec] = None
    state: TaskState = TaskState.WAIT_TARGET
    active: bool = True


class UserIntent(StrictModel):
    kind: IntentKind
    transcript: str
    target: Optional[TargetSpec] = None
    pending_prompt_id: Optional[str] = None


class FrameRef(StrictModel):
    frame_id: str
    session_id: str
    received_at: float
    received_monotonic: float
    source_timestamp: Optional[float] = None
    jpeg_bytes: bytes
    width: int
    height: int
    scene_epoch: int
    track_name: str
    sharpness: Optional[float] = Field(default=None,ge=0)
    scene_signature: tuple[int,...] = Field(default=(),exclude=True,repr=False)

    model_config = ConfigDict(extra="forbid")


class PendingConsent(StrictModel):
    prompt_id: str
    session_id: str
    task_id: str
    generation: int
    frame_id: str
    scene_epoch: int
    helper_id: str
    expires_at: float


class Observation(StrictModel):
    frame_id: str
    objects: list[str] = Field(default_factory=list, max_length=20)
    visible_text: list[str] = Field(default_factory=list, max_length=20)
    quality: Quality = Quality.UNKNOWN
    uncertainties: list[str] = Field(default_factory=list, max_length=20)
    risk_tags: list[str] = Field(default_factory=list, max_length=20)
    candidate_label: str = ""
    camera_position: CameraPosition = CameraPosition.UNKNOWN
    match_proposal: MatchProposal = MatchProposal.UNKNOWN
    response_candidate: str = Field(default="", max_length=300)


class GroundedReply(StrictModel):
    text: str = Field(min_length=1, max_length=400)
    frame_id: Optional[str] = None
    needs_view: bool = False


class EvidenceDecision(StrictModel):
    kind: EvidenceKind
    reason: str
    visible_text: list[str] = Field(default_factory=list)
    frame_id: str
    scene_epoch: int
    generation: int
    analysis_revision: int


class SpeechEvent(StrictModel):
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    session_id: str
    task_id: str
    generation: int
    analysis_revision: int
    turn_id: str
    priority: int = 50
    text: str
    evidence_frame_id: Optional[str] = None
    scene_epoch: Optional[int] = None
    expires_at: Optional[float] = None
    dedupe_key: str
    from_template: bool = True
    explicit_check: bool = False
    visual: bool = False


class ReviewCompletion(StrictModel):
    result: str = Field(pattern="^(READABLE|UNRESOLVED)$")
    literal_text: Optional[str] = Field(default=None, max_length=500)
    notes: Optional[str] = Field(default=None, max_length=500)
    expected_version: int


class PayoutReceipt(StrictModel):
    payout_id: str
    review_id: str
    network: str = "devnet"
    lamports: int
    recipient: str
    signature: Optional[str] = None
    state: PayoutState
    last_valid_block_height: Optional[int] = None


class OutboxJob(StrictModel):
    id: str
    kind: str
    dedupe_key: str
    payload: dict
    state: JobState
    attempts: int = 0
    available_at: float = 0
    lease_owner: Optional[str] = None
    lease_until: float = 0
    expires_at: Optional[float] = None
    last_error: str = ""


def new_id() -> str:
    return str(uuid4())
