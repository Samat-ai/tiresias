from __future__ import annotations

from tiresias.agent.media import FrameBuffer
from tiresias.agent.policy import clarification_speech, decide, speech_for
from tiresias.agent.speech import SpeechScheduler
from tiresias.contracts import (
    EvidenceKind,
    IntentKind,
    SpeechEvent,
    TargetSpec,
    TaskContext,
    TaskState,
    UserIntent,
    new_id,
)


class TaskController:
    def __init__(
        self,
        session_id: str,
        buffer: FrameBuffer,
        scheduler: SpeechScheduler,
        *,
        evidence_max_age_ms: int = 5000,
        frame_max_age_ms: int = 1000,
    ) -> None:
        self.session_id = session_id
        self.buffer = buffer
        self.scheduler = scheduler
        self.evidence_max_age_ms = evidence_max_age_ms
        self.frame_max_age_ms = frame_max_age_ms
        self.task = TaskContext(
            session_id=session_id,
            task_id=new_id(),
            generation=0,
            analysis_revision=0,
            turn_id=new_id(),
            state=TaskState.WAIT_TARGET,
        )
        self.scheduler.generation = 0
        self.speed = 1.0
        self.candidate_frame_id: str | None = None
        self.inflight_revision: int | None = None
        self.consent_prompt_id: str | None = None
        self._now = 0.0

    def set_time(self, now: float) -> None:
        self._now = now

    def handle(self, intent: UserIntent, observation_factory=None) -> list[SpeechEvent]:
        self.task.turn_id = new_id()
        if intent.kind == IntentKind.STOP:
            self.task.generation += 1
            self.task.analysis_revision += 1
            self.scheduler.interrupt(self.task.generation)
            self.scheduler.stop()
            self.inflight_revision = None
            return []
        if intent.kind == IntentKind.REPEAT:
            replay = self.scheduler.repeat(self._now, self._scene())
            if replay is None or (replay.visual and replay.analysis_revision != self.task.analysis_revision):
                return self._say("I need a fresh check before I can repeat that.", visual=False, priority=40)
            return self._say(replay.text, visual=replay.visual, explicit_check=True, priority=40)
        if intent.kind in {IntentKind.SLOWER, IntentKind.FASTER}:
            delta = -0.1 if intent.kind == IntentKind.SLOWER else 0.1
            self.speed = min(1.2, max(0.7, round(self.speed + delta, 2)))
            pace = "slower" if intent.kind == IntentKind.SLOWER else "faster"
            return self._say(f"Okay, a bit {pace}.", visual=False, priority=30)
        if intent.kind == IntentKind.UNSUPPORTED:
            return self._say(
                "I can't help with dosing or crossing. I can read a regular product label though.",
                visual=False,
                priority=5,
            )
        if intent.kind in {IntentKind.FIND_TARGET, IntentKind.CHANGE_TARGET} and intent.target:
            self._begin_target(intent.target, changed=intent.kind == IntentKind.CHANGE_TARGET or self.task.target is not None)
            return self._analyze(observation_factory, stage="candidate")
        if intent.kind == IntentKind.CHECK:
            self.task.analysis_revision += 1
            self.scheduler.generation = self.task.generation
            if self.task.state in {TaskState.CANDIDATE, TaskState.LABEL_VIEW, TaskState.NEED_VIEW, TaskState.MISMATCH}:
                self.task.state = TaskState.RECHECK_SELECTION
            return self._analyze(observation_factory, stage="recheck", explicit_check=True)
        if intent.kind == IntentKind.ASK_PERSON:
            return self._say(
                "A live helper isn't connected yet. I can take another look with you.",
                visual=False,
                priority=20,
            )
        if intent.kind == IntentKind.ASK_CLARIFICATION:
            return self._say(clarification_speech(self.task), visual=False, priority=40)
        return []

    def conversational_reply(self, reply, frame=None) -> list[SpeechEvent]:
        return self._say(
            reply.text, visual=frame is not None,
            frame_id=frame.frame_id if frame else None,
            scene_epoch=frame.scene_epoch if frame else None,
        )

    def complete_inflight(
        self,
        revision: int,
        observation,
        stage: str,
        *,
        analyzed_frame=None,
    ) -> list[SpeechEvent]:
        if revision != self.task.analysis_revision or self.inflight_revision != revision:
            return []
        self.inflight_revision = None
        # Pin the frame Gemini actually saw — latest() drifts during the API call.
        frame = analyzed_frame
        if frame is None and getattr(observation, "frame_id", None):
            frame = self.buffer.get(observation.frame_id)
        if frame is None:
            frame = self.buffer.latest(self.evidence_max_age_ms, self._now)
        if frame is None:
            return self._say(
                "That view's gone. Hold it still and try again.",
                visual=True,
                explicit_check=stage == "recheck",
            )
        # Freshness is enforced at capture; allow Gemini round-trip on the pinned frame.
        max_age_ms = self.evidence_max_age_ms
        if analyzed_frame is not None:
            max_age_ms = max(self.evidence_max_age_ms, 20_000)
        decision = decide(
            self.task,
            frame,
            observation,
            stage=stage,
            now_monotonic=self._now,
            max_age_ms=max_age_ms,
        )
        if stage == "recheck" and self.candidate_frame_id and frame.frame_id == self.candidate_frame_id:
            return self._say("Show me a fresh view of the one you picked.", visual=False, priority=15)
        if decision.kind == EvidenceKind.CANDIDATE:
            self.candidate_frame_id = frame.frame_id
            self.task.state = TaskState.LABEL_VIEW
        elif decision.kind == EvidenceKind.MATCH:
            self.task.state = TaskState.MATCH
        elif decision.kind == EvidenceKind.MISMATCH:
            self.task.state = TaskState.MISMATCH
        elif decision.kind == EvidenceKind.NEED_VIEW:
            self.task.state = TaskState.NEED_VIEW
        else:
            self.task.state = TaskState.UNCERTAIN
        return self._say(
            speech_for(decision, self.task),
            visual=True,
            explicit_check=stage == "recheck",
            frame_id=frame.frame_id,
            scene_epoch=frame.scene_epoch,
            priority=12 if decision.kind == EvidenceKind.MISMATCH else 25,
        )

    def _begin_target(self, target: TargetSpec, changed: bool) -> None:
        if changed and self.task.target is not None:
            self.task.generation += 1
            self.scheduler.interrupt(self.task.generation)
        self.task.target = target
        self.task.analysis_revision += 1
        self.task.state = TaskState.FINDING
        self.candidate_frame_id = None
        self.task.task_id = new_id() if changed else self.task.task_id

    def _analyze(self, observation_factory, stage: str, explicit_check: bool = False) -> list[SpeechEvent]:
        frame = self.buffer.best(self.frame_max_age_ms, self._now)
        if frame is None:
            self.task.state = TaskState.NEED_VIEW
            return self._say(
                "Point the camera at it and say check this when you're ready.",
                visual=False,
                priority=15,
            )
        if self.inflight_revision is not None:
            self.task.analysis_revision += 1
            self.scheduler.interrupt(self.task.generation)
            self.scheduler.generation = self.task.generation
        self.inflight_revision = self.task.analysis_revision
        if observation_factory is None:
            label = self.task.target.requested_label if self.task.target else "that"
            if explicit_check:
                return self._say(f"Checking {label}.", visual=False, priority=35)
            return self._say(f"Okay — looking for {label}.", visual=False, priority=35)
        observation = observation_factory(frame)
        revision = self.inflight_revision
        return self.complete_inflight(revision, observation, stage, analyzed_frame=frame)

    def _scene(self) -> int | None:
        frame = self.buffer.latest(self.evidence_max_age_ms, self._now)
        return frame.scene_epoch if frame else None

    def _say(
        self,
        text: str,
        *,
        visual: bool,
        priority: int = 25,
        explicit_check: bool = False,
        frame_id: str | None = None,
        scene_epoch: int | None = None,
    ) -> list[SpeechEvent]:
        frame = self.buffer.latest(10_000_000, self._now)
        expires = None
        if visual and frame is not None:
            expires = frame.received_monotonic + (self.evidence_max_age_ms / 1000)
        event = SpeechEvent(
            session_id=self.session_id,
            task_id=self.task.task_id,
            generation=self.task.generation,
            analysis_revision=self.task.analysis_revision,
            turn_id=self.task.turn_id,
            priority=priority,
            text=text,
            evidence_frame_id=frame_id,
            scene_epoch=scene_epoch if scene_epoch is not None else (frame.scene_epoch if frame else None),
            expires_at=expires,
            dedupe_key=f"{self.task.task_id}:{self.task.generation}:{self.task.analysis_revision}:{text}",
            from_template=True,
            explicit_check=explicit_check,
            visual=visual,
        )
        if self.scheduler.enqueue(event, self._now):
            return self.scheduler.publish(self._now)
        return []
