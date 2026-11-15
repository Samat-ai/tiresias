from tiresias.agent.media import CALLER_VIDEO_TRACK, FrameBuffer, IncomingFrame


def incoming(buffer: FrameBuffer, **overrides) -> IncomingFrame:
    values = dict(
        session_id=buffer.session_id,
        track_name=CALLER_VIDEO_TRACK,
        participant_kind="caller",
        jpeg_bytes=b"frame-bytes",
        width=320,
        height=240,
        received_monotonic=10.0,
        received_at=1_700_000_000.0,
        source_timestamp=1_700_000_000.0,
        scene_epoch=1,
        camera_region=(10, 10, 300, 220),
    )
    values.update(overrides)
    return IncomingFrame(**values)


def test_stale_frame_returns_none():
    buffer = FrameBuffer("session")
    buffer.push(incoming(buffer, received_monotonic=10.0))
    assert buffer.latest(1000, 11.001) is None


def test_latest_frame_replaces_older():
    buffer = FrameBuffer("session")
    buffer.push(incoming(buffer, received_monotonic=10.0))
    newer = buffer.push(incoming(buffer, received_monotonic=10.4, jpeg_bytes=b"newer"))
    assert buffer.latest(1000, 10.5).frame_id == newer.frame_id
    assert len(buffer._frames) == 2


def test_best_prefers_larger_recent_jpeg():
    buffer = FrameBuffer("session", max_frames=8)
    small = buffer.push(incoming(buffer, received_monotonic=10.0, jpeg_bytes=b"x" * 100))
    large = buffer.push(incoming(buffer, received_monotonic=10.2, jpeg_bytes=b"y" * 5000))
    buffer.push(incoming(buffer, received_monotonic=10.3, jpeg_bytes=b"z" * 200))
    chosen = buffer.best(1000, 10.4)
    assert chosen is not None
    assert chosen.frame_id == large.frame_id
    assert buffer.get(small.frame_id) is small


def test_own_agent_video_not_selected():
    buffer = FrameBuffer("session")
    assert buffer.push(incoming(buffer, participant_kind="agent")) is None
    assert buffer.push(incoming(buffer, track_name="agent-video")) is None
    assert buffer.latest(1000, 10.1) is None


def test_ui_only_or_muted_camera_is_not_evidence():
    buffer = FrameBuffer("session")
    assert buffer.push(incoming(buffer, muted=True)) is None
    assert buffer.push(incoming(buffer, ui_only_change=True)) is None
    assert buffer.push(incoming(buffer, frozen_camera=True)) is None
    assert buffer.push(incoming(buffer, camera_region=None)) is None


def test_disconnect_clears_frames_and_pending_consent():
    buffer = FrameBuffer("session")
    frame = buffer.push(incoming(buffer))
    buffer.hold_pending(frame, expires_at=40)
    buffer.clear()
    assert buffer.latest(1000, 10.1) is None
    assert buffer.pending(10.1) is None
