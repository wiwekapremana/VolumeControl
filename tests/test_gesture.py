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


# ---------------------------------------------------------------- fitur baru
from gesture import Action, HandPose, classify_hand


def make_hand(curled):
    """Tangan sintetis: 4 jari menghadap atas; curled=True menekuk jari ke bawah."""
    hand = [P(x=0.5, y=0.8, z=0.0) for _ in range(21)]
    for i, (mcp, pip, dip, tip) in enumerate(((5, 6, 7, 8), (9, 10, 11, 12),
                                              (13, 14, 15, 16), (17, 18, 19, 20))):
        x = 0.44 + i * 0.04
        hand[mcp] = P(x=x, y=0.65, z=0.0)
        hand[pip] = P(x=x, y=0.60, z=0.0)
        if curled:
            hand[dip] = P(x=x, y=0.62, z=-0.04)
            hand[tip] = P(x=x, y=0.66, z=-0.02)
        else:
            hand[dip] = P(x=x, y=0.56, z=0.0)
            hand[tip] = P(x=x, y=0.52, z=0.0)
    return hand


def test_classify_hand():
    assert classify_hand(make_hand(False)) is HandPose.OPEN
    assert classify_hand(make_hand(True)) is HandPose.FIST
    mixed = make_hand(True)
    open_ = make_hand(False)
    for k in (5, 6, 7, 8):
        mixed[k] = open_[k]  # telunjuk lurus, lainnya menekuk
    assert classify_hand(mixed) is HandPose.OTHER
    assert classify_hand(None) is None


def active_controller(volume=0.5):
    c = Controller(volume=volume)
    c.sync_volume(volume)
    _, t = run(c, 0, 1.1, both_hands_raised=True)
    _, t = run(c, t, t + 0.6, pinch_ratio=0.65, hand_pose=HandPose.OTHER,
               hand_x=0.5, hand_y=0.5, hand_id="right")
    return c, t


def collect(c, t0, t1, dt=1 / 30, **kw):
    acts, t = [], t0
    while t < t1:
        out = c.update(Frame(timestamp=t, **kw))
        if out.action:
            acts.append(out.action)
        t += dt
    return acts, t


def test_fist_toggles_mute_once_per_fist():
    c, t = active_controller()
    acts, t = collect(c, t, t + 1.5, pinch_ratio=0.1, hand_pose=HandPose.FIST,
                      hand_x=0.5, hand_y=0.5, hand_id="right")
    assert acts == [Action.MUTE] and c.muted
    _, t = collect(c, t, t + 0.3, pinch_ratio=0.6, hand_pose=HandPose.OTHER,
                   hand_x=0.5, hand_y=0.5, hand_id="right")
    acts, t = collect(c, t, t + 0.6, pinch_ratio=0.1, hand_pose=HandPose.FIST,
                      hand_x=0.5, hand_y=0.5, hand_id="right")
    assert acts == [Action.UNMUTE] and not c.muted


def test_muted_ignores_pinch():
    c, t = active_controller()
    _, t = collect(c, t, t + 0.6, pinch_ratio=0.1, hand_pose=HandPose.FIST,
                   hand_x=0.5, hand_y=0.5, hand_id="right")
    before = c.display_volume
    collect(c, t, t + 1, pinch_ratio=2.0, hand_pose=HandPose.OTHER,
            hand_x=0.5, hand_y=0.5, hand_id="right")
    assert c.display_volume == before


def test_volume_restored_after_fist_transition():
    c, t = active_controller()
    _, t = run(c, t, t + 2, pinch_ratio=0.65, hand_pose=HandPose.OTHER,
               hand_x=0.5, hand_y=0.5, hand_id="right")
    steady = c.display_volume
    # menutup tangan: jarak cubit mengecil sebelum dikenali sebagai kepalan
    _, t = run(c, t, t + 0.2, pinch_ratio=0.15, hand_pose=HandPose.OTHER,
               hand_x=0.5, hand_y=0.5, hand_id="right")
    assert c.display_volume < steady
    run(c, t, t + 0.6, pinch_ratio=0.1, hand_pose=HandPose.FIST,
        hand_x=0.5, hand_y=0.5, hand_id="right")
    assert abs(c.display_volume - steady) <= 0.02


def test_swipe_right_and_left():
    c, t = active_controller()
    acts, t2, x = [], t, 0.3
    while t2 < t + 0.3:  # geser ke kanan cepat
        out = c.update(Frame(timestamp=t2, pinch_ratio=1.5, hand_pose=HandPose.OPEN,
                             hand_x=x, hand_y=0.5, hand_id="right"))
        acts += [out.action] if out.action else []
        x += 0.03
        t2 += 1 / 30
    assert acts == [Action.NEXT]
    t2 += 1.0
    acts = []
    while x > 0.2:
        out = c.update(Frame(timestamp=t2, pinch_ratio=1.5, hand_pose=HandPose.OPEN,
                             hand_x=x, hand_y=0.5, hand_id="right"))
        acts += [out.action] if out.action else []
        x -= 0.03
        t2 += 1 / 30
    assert acts == [Action.PREV]


def test_still_open_palm_play_pause_once():
    c, t = active_controller()
    acts, t = collect(c, t, t + 3, pinch_ratio=1.5, hand_pose=HandPose.OPEN,
                      hand_x=0.5, hand_y=0.5, hand_id="right")
    assert acts == [Action.PLAY_PAUSE]


def test_moving_palm_no_play_pause():
    c, t = active_controller()
    acts, x = [], 0.4
    for i in range(60):  # gerak pelan bolak-balik, bukan swipe & bukan diam
        x = 0.45 + 0.05 * ((i // 5) % 2)
        out = c.update(Frame(timestamp=t + i / 30, pinch_ratio=1.5,
                             hand_pose=HandPose.OPEN, hand_x=x, hand_y=0.5,
                             hand_id="right"))
        acts += [out.action] if out.action else []
    assert acts == []


def test_switching_hand_does_not_swipe():
    c, t = active_controller()
    acts = []
    for i in range(20):
        hid, x = ("right", 0.3) if i % 2 else ("left", 0.7)
        out = c.update(Frame(timestamp=t + i / 30, pinch_ratio=1.5,
                             hand_pose=HandPose.OPEN, hand_x=x, hand_y=0.5, hand_id=hid))
        acts += [out.action] if out.action else []
    assert Action.NEXT not in acts and Action.PREV not in acts
