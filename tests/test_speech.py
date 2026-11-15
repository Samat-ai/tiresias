from tiresias.agent.controller import TaskController
from tiresias.agent.media import FrameBuffer
from tiresias.agent.policy import route_utterance
from tiresias.agent.speech import CallLifecycle, SpeechScheduler
from tiresias.contracts import MatchProposal, Observation, Quality, SpeechEvent
from tests.test_frames import incoming


def scheduler_event(**overrides) -> SpeechEvent:
    values = dict(
        session_id="s",
        task_id="t",
        generation=0,
        analysis_revision=1,
        turn_id="turn",
        text="The label in this view says LEMON.",
        dedupe_key="t:0:1:MATCH:lemon",
        from_template=True,
        visual=True,
        expires_at=15.0,
        scene_epoch=1,
    )
    values.update(overrides)
    return SpeechEvent(**values)


def test_greeting_waits_for_bridge_ready():
    call = CallLifecycle()
    assert call.greeted is False
    greeting = call.on_bridge_ready("epoch-1")
    assert "label" in greeting
    assert call.on_bridge_ready("epoch-1") is None


def test_duplicate_ready_does_not_greet_twice():
    call = CallLifecycle()
    call.on_bridge_ready("epoch-1")
    assert call.on_bridge_ready("epoch-1") is None


def test_agent_audio_not_transcribed():
    call = CallLifecycle()
    call.on_bridge_ready("epoch-1")
    assert call.accept_audio("agent", "my own voice") is None
    assert call.accept_audio("caller", "find lemon sparkling water") == "find lemon sparkling water"


def test_disconnect_closes_scoped_media():
    call = CallLifecycle()
    call.on_bridge_ready("epoch-1")
    call.disconnect()
    assert call.media_open is False
    assert call.accept_audio("caller", "hello") is None


def test_reused_room_gets_new_call_epoch():
    call = CallLifecycle()
    call.on_bridge_ready("epoch-1")
    call.authorize("epoch-1", "user-a")
    call.on_bridge_ready("epoch-2")
    assert call.authorized is False
    assert call.user_id is None
    assert call.greeted is True


def test_stop_clears_queue():
    scheduler = SpeechScheduler()
    scheduler.enqueue(scheduler_event(), now=10)
    scheduler.stop()
    assert scheduler.publish(10) == []


def test_duplicate_observation_suppressed_for_10_seconds():
    scheduler = SpeechScheduler()
    assert scheduler.enqueue(scheduler_event(), now=10) is True
    scheduler.publish(10)
    assert scheduler.enqueue(scheduler_event(event_id="other"), now=15) is False


def test_explicit_new_check_can_repeat_current_label():
    scheduler = SpeechScheduler()
    scheduler.enqueue(scheduler_event(), now=10)
    scheduler.publish(10)
    again = scheduler_event(analysis_revision=2, dedupe_key="t:0:2:MATCH:lemon", explicit_check=True)
    assert scheduler.enqueue(again, now=12) is True


def test_repeat_does_not_reassert_old_match():
    scheduler = SpeechScheduler()
    event = scheduler_event(expires_at=15)
    scheduler.enqueue(event, now=10)
    scheduler.publish(10)
    assert scheduler.repeat(now=16, current_scene_epoch=2) is None


def test_visual_event_expires_5_seconds_after_frame_receipt():
    scheduler = SpeechScheduler()
    assert scheduler.enqueue(scheduler_event(expires_at=15.0), now=15.1) is False
    assert scheduler.enqueue(scheduler_event(expires_at=15.0, dedupe_key="fresh"), now=14.9) is True


def test_response_candidate_not_spoken_directly():
    scheduler = SpeechScheduler()
    rejected = scheduler_event(from_template=False, text="The label in this view says lemon sparkling water.")
    assert scheduler.enqueue(rejected, now=10) is False


def test_selection_requires_new_frame():
    buffer = FrameBuffer("s")
    controller = TaskController("s", buffer, SpeechScheduler())
    controller.set_time(10)
    first = buffer.push(incoming(buffer, received_monotonic=10))
    controller.candidate_frame_id = first.frame_id
    controller.task.analysis_revision = 2
    controller.inflight_revision = 2
    spoken = controller.complete_inflight(2, _readable(["LEMON", "SPARKLING WATER"], first.frame_id), "recheck")
    assert any("fresh view" in event.text.lower() or "new view" in event.text.lower() for event in spoken)


def test_wrong_selected_label_is_mismatch():
    buffer = FrameBuffer("s")
    controller = TaskController("s", buffer, SpeechScheduler())
    controller.set_time(10)
    buffer.push(incoming(buffer, received_monotonic=10))
    controller.handle(route_utterance("find lemon sparkling water", None))
    controller.candidate_frame_id = "older"
    buffer.push(incoming(buffer, received_monotonic=10.2, jpeg_bytes=b"next"))
    controller.set_time(10.3)
    spoken = controller.handle(
        route_utterance("check this", controller.task),
        observation_factory=lambda seen: _readable(["COLA"], seen.frame_id),
    )
    assert any("not" in event.text.lower() and "lemon" in event.text.lower() for event in spoken)


def test_target_change_invalidates_slow_result():
    buffer = FrameBuffer("s")
    controller = TaskController("s", buffer, SpeechScheduler())
    controller.set_time(10)
    buffer.push(incoming(buffer, received_monotonic=10))
    controller.handle(route_utterance("find lemon sparkling water", None))
    old_revision = controller.inflight_revision
    controller.handle(route_utterance("change to cola", controller.task))
    late = controller.complete_inflight(old_revision, _readable(["LEMON", "SPARKLING WATER"]), "candidate")
    assert late == []


def test_same_target_new_check_invalidates_old_revision():
    buffer = FrameBuffer("s")
    controller = TaskController("s", buffer, SpeechScheduler())
    controller.set_time(10)
    buffer.push(incoming(buffer, received_monotonic=10))
    controller.handle(route_utterance("find lemon sparkling water", None))
    controller.handle(route_utterance("check this", controller.task))
    old = controller.inflight_revision
    controller.handle(route_utterance("check this", controller.task))
    assert controller.complete_inflight(old, _readable(["LEMON", "SPARKLING WATER"]), "recheck") == []


def _readable(text: list[str], frame_id: str = "frame") -> Observation:
    return Observation(
        frame_id=frame_id,
        visible_text=text,
        quality=Quality.READABLE,
        match_proposal=MatchProposal.UNKNOWN,
    )
