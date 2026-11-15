from __future__ import annotations

from tiresias.contracts import SpeechEvent


class SpeechScheduler:
    def __init__(self, dedupe_window_s: float = 10.0, max_queue: int = 3) -> None:
        self.dedupe_window_s = dedupe_window_s
        self.max_queue = max_queue
        self.generation = 0
        self.queue: list[SpeechEvent] = []
        self.spoken: list[SpeechEvent] = []
        self._recent: dict[str, float] = {}
        self.last_applicable: SpeechEvent | None = None

    def enqueue(self, event: SpeechEvent, now: float) -> bool:
        if not event.from_template:
            return False
        if event.generation != self.generation:
            return False
        if event.visual and event.expires_at is not None and now > event.expires_at:
            return False
        if not event.explicit_check:
            previous = self._recent.get(event.dedupe_key)
            if previous is not None and now - previous < self.dedupe_window_s:
                return False
        self._recent[event.dedupe_key] = now
        if event.priority <= 10:
            self.queue = [item for item in self.queue if item.priority <= 10]
        self.queue.append(event)
        self.queue.sort(key=lambda item: item.priority)
        if len(self.queue) > self.max_queue:
            self.queue = self.queue[: self.max_queue]
        return True

    def interrupt(self, new_generation: int) -> None:
        self.generation = new_generation
        self.queue.clear()

    def stop(self) -> None:
        self.queue.clear()

    def publish(self, now: float) -> list[SpeechEvent]:
        ready: list[SpeechEvent] = []
        kept: list[SpeechEvent] = []
        for event in self.queue:
            if event.generation != self.generation:
                continue
            if event.visual and event.expires_at is not None and now > event.expires_at:
                continue
            ready.append(event)
        self.queue = kept
        self.spoken.extend(ready)
        if ready:
            self.last_applicable = ready[-1]
        return ready

    def repeat(self, now: float, current_scene_epoch: int | None) -> SpeechEvent | None:
        last = self.last_applicable
        if last is None:
            return None
        if last.visual and last.scene_epoch != current_scene_epoch:
            return None
        if last.visual and last.expires_at is not None and now > last.expires_at:
            return None
        return last


class CallLifecycle:
    def __init__(self) -> None:
        self.bridge_ready = False
        self.greeted = False
        self.media_open = False
        self.epoch: str | None = None
        self.authorized = False
        self.user_id: str | None = None
        self.transcripts: list[str] = []

    def on_bridge_ready(self, epoch: str) -> str | None:
        if self.epoch != epoch:
            self._reset(epoch)
        self.bridge_ready = True
        self.media_open = True
        if self.greeted:
            return None
        self.greeted = True
        return "Hey, I'm Tiresias — I help you find and read product labels. What are you looking for?"

    def on_caller_audio(self, epoch: str) -> None:
        if self.epoch != epoch:
            self._reset(epoch)
        self.media_open = True

    def accept_audio(self, participant_kind: str, text: str) -> str | None:
        if participant_kind == "agent" or not self.media_open:
            return None
        self.transcripts.append(text)
        return text

    def authorize(self, epoch: str, user_id: str) -> None:
        if epoch != self.epoch:
            return
        self.authorized = True
        self.user_id = user_id

    def disconnect(self) -> None:
        self.media_open = False
        self.bridge_ready = False

    def _reset(self, epoch: str) -> None:
        self.epoch = epoch
        self.bridge_ready = False
        self.greeted = False
        self.media_open = False
        self.authorized = False
        self.user_id = None
        self.transcripts.clear()
