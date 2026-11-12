from types import SimpleNamespace as P

from gesture import Config, Controller, Frame, State, both_hands_raised, pinch_ratio


def run(ctrl, t0, t1, dt=1 / 30, **kw):
    out, t = None, t0
    while t < t1:
        out = ctrl.update(Frame(timestamp=t, **kw))
        t += dt
    return out, t


def test_activation_requires_hold():
    c = Controller(Config(hold_time=1.0))
    out, t = run(c, 0, 0.5, both_hands_raised=True)
    assert c.state is State.LOCKED and 0.4 < out.activation_progress < 0.6
    run(c, t, 1.2, both_hands_raised=True)
    assert c.state is State.ACTIVE


def test_keep_raising_does_not_retoggle():
    c = Controller()
    run(c, 0, 5, both_hands_raised=True)
    assert c.state is State.ACTIVE


def test_toggle_off_and_idle_lock():
    c = Controller()
    _, t = run(c, 0, 1.1, both_hands_raised=True)
    _, t = run(c, t, t + 0.3, pinch_ratio=0.6)
    _, t = run(c, t, t + 1.1, both_hands_raised=True)
    assert c.state is State.LOCKED
    _, t = run(c, t, t + 0.2)
    _, t = run(c, t, t + 1.1, both_hands_raised=True)
    assert c.state is State.ACTIVE
    run(c, t, t + 3.5)  # tangan hilang
    assert c.state is State.LOCKED


def test_locked_ignores_pinch():
    c = Controller(volume=0.5)
    c.sync_volume(0.5)
    out, _ = run(c, 0, 2, pinch_ratio=2.0)
    assert out.volume == 0.5 and not out.volume_changed


def test_volume_moves_smoothly_to_target():
    c = Controller(volume=0.5)
    c.sync_volume(0.5)
    _, t = run(c, 0, 1.1, both_hands_raised=True)
    out = c.update(Frame(timestamp=t + 0.6, pinch_ratio=2.0))
    assert 0.5 < out.volume < 0.8  # tidak langsung lompat
    out, _ = run(c, t + 0.7, t + 2.5, pinch_ratio=2.0)
    assert out.volume == 1.0
    out, _ = run(c, t + 2.5, t + 4.5, pinch_ratio=0.0)
    assert out.volume == 0.0


def test_feature_extraction():
    pose = [P(x=0, y=0.5, visibility=1.0) for _ in range(33)]
    pose[11] = P(x=0.4, y=0.5, visibility=1); pose[12] = P(x=0.6, y=0.5, visibility=1)
    pose[15] = P(x=0.3, y=0.2, visibility=1); pose[16] = P(x=0.7, y=0.2, visibility=1)
    assert both_hands_raised(pose)
    pose[16] = P(x=0.7, y=0.8, visibility=1)
    assert not both_hands_raised(pose)
    hand = [P(x=0, y=0) for _ in range(21)]
    hand[9] = P(x=0, y=0.1); hand[4] = P(x=0.05, y=0); hand[8] = P(x=0.1, y=0)
    assert abs(pinch_ratio(hand) - 0.5) < 1e-9
