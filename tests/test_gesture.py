from types import SimpleNamespace as P

from gesture import (Action, Config, Controller, Frame, HandPose, State,
                     both_hands_raised, classify_hand, extract, thumb_press)

DT = 1 / 30
HAND = dict(hand_id="right", hand_x=0.5, hand_y=0.5)


def run(ctrl, t0, t1, **kw):
    """Jalankan frame identik dari t0 s/d t1; kembalikan (aksi, output terakhir, t)."""
    acts, out, t = [], None, t0
    while t < t1:
        out = ctrl.update(Frame(timestamp=t, **kw))
        if out.action:
            acts.append(out.action)
        t += DT
    return acts, out, t


def active(volume=0.5):
    c = Controller(volume=volume)
    c.sync_volume(volume)
    _, _, t = run(c, 0, 1.1, both_hands_raised=True)
    _, _, t = run(c, t, t + 0.6, hand_pose=HandPose.OTHER, **HAND)
    assert c.state is State.ACTIVE
    return c, t


# ------------------------------------------------------------------ aktivasi
def test_activation_requires_hold():
    c = Controller()
    _, out, t = run(c, 0, 0.5, both_hands_raised=True)
    assert c.state is State.LOCKED and 0.4 < out.activation_progress < 0.6
    run(c, t, 1.2, both_hands_raised=True)
    assert c.state is State.ACTIVE


def test_keep_raising_does_not_retoggle():
    c = Controller()
    run(c, 0, 5, both_hands_raised=True)
    assert c.state is State.ACTIVE


def test_toggle_off_and_idle_lock():
    c, t = active()
    _, _, t = run(c, t, t + 1.1, both_hands_raised=True)
    assert c.state is State.LOCKED
    _, _, t = run(c, t, t + 0.2)
    _, _, t = run(c, t, t + 1.1, both_hands_raised=True)
    assert c.state is State.ACTIVE
    run(c, t, t + 3.5)
    assert c.state is State.LOCKED


def test_locked_ignores_gestures():
    c = Controller(volume=0.5)
    c.sync_volume(0.5)
    acts, out, _ = run(c, 0, 2, hand_pose=HandPose.FIST, **HAND)
    assert acts == [] and out.volume == 0.5 and out.pointer is None


# -------------------------------------------------------------------- volume
def pinch_move(c, t, y0, y1, dur=0.5):
    n = int(dur / DT)
    out = None
    for i in range(n + 1):
        y = y0 + (y1 - y0) * i / n
        out = c.update(Frame(timestamp=t, hand_pose=HandPose.PINCH, pinch_y=y, **HAND))
        t += DT
    return out, t


def test_pinch_slide_volume_relative_and_smooth():
    c, t = active(0.5)
    out, t = pinch_move(c, t, 0.6, 0.6, 0.2)       # pegang: volume tidak lompat
    assert out.volume == 0.5
    out, t = pinch_move(c, t, 0.6, 0.5, 0.3)       # naik 0.1 frame -> +30%
    _, out, t = run(c, t, t + 0.5, hand_pose=HandPose.PINCH, pinch_y=0.5, **HAND)
    assert abs(out.volume - 0.8) <= 0.02


def test_pinch_clamps_and_reverses_immediately():
    c, t = active(0.9)
    out, t = pinch_move(c, t, 0.6, 0.3, 0.3)       # jauh melewati 100%
    _, out, t = run(c, t, t + 0.5, hand_pose=HandPose.PINCH, pinch_y=0.3, **HAND)
    assert out.volume == 1.0
    out, t = pinch_move(c, t, 0.3, 0.35, 0.2)      # turun sedikit -> langsung turun
    _, out, t = run(c, t, t + 0.5, hand_pose=HandPose.PINCH, pinch_y=0.35, **HAND)
    assert 0.8 <= out.volume <= 0.88


# --------------------------------------------------------------- mute & media
def test_fist_toggles_mute_once_per_fist_and_blocks_volume():
    c, t = active()
    acts, _, t = run(c, t, t + 1.5, hand_pose=HandPose.FIST, **HAND)
    assert acts == [Action.MUTE] and c.muted
    before = c.display_volume
    out, t = pinch_move(c, t, 0.6, 0.3)
    assert out.volume == before
    acts, _, t = run(c, t, t + 0.6, hand_pose=HandPose.FIST, **HAND)
    assert acts == [Action.UNMUTE] and not c.muted


def swipe(c, t, x0, x1, dur=0.25):
    acts, n = [], int(dur / DT)
    for i in range(n + 1):
        out = c.update(Frame(timestamp=t, hand_pose=HandPose.OPEN, hand_id="right",
                             hand_x=x0 + (x1 - x0) * i / n, hand_y=0.5))
        acts += [out.action] if out.action else []
        t += DT
    return acts, t


def test_swipe_right_and_left():
    c, t = active()
    _, _, t = run(c, t, t + 0.15, hand_pose=HandPose.OPEN, hand_id="right",
                  hand_x=0.3, hand_y=0.5)
    acts, t = swipe(c, t, 0.3, 0.6)
    assert acts == [Action.NEXT]
    _, _, t = run(c, t, t + 1.0, hand_pose=HandPose.OTHER, **HAND)
    _, _, t = run(c, t, t + 0.15, hand_pose=HandPose.OPEN, hand_id="right",
                  hand_x=0.6, hand_y=0.5)
    acts, t = swipe(c, t, 0.6, 0.3)
    assert acts == [Action.PREV]


def test_still_open_palm_play_pause_once():
    c, t = active()
    acts, _, _ = run(c, t, t + 3, hand_pose=HandPose.OPEN, **HAND)
    assert acts == [Action.PLAY_PAUSE]


def test_switching_hand_does_not_swipe():
    c, t = active()
    acts = []
    for i in range(20):
        hid, x = ("right", 0.3) if i % 2 else ("left", 0.7)
        out = c.update(Frame(timestamp=t + i * DT, hand_pose=HandPose.OPEN,
                             hand_x=x, hand_y=0.5, hand_id=hid))
        acts += [out.action] if out.action else []
    assert Action.NEXT not in acts and Action.PREV not in acts


# ------------------------------------------------------------------- pointer
def point(c, t, x, y, thumb, dur=DT):
    outs, end = [], t + dur
    while t < end - 1e-9:
        outs.append(c.update(Frame(timestamp=t, hand_pose=HandPose.POINT, hand_id="right",
                                   hand_x=x, hand_y=y + 0.1, tip_x=x, tip_y=y,
                                   thumb_press=thumb)))
        t += DT
    return outs, t


def actions(outs):
    return [o.action for o in outs if o.action]


def test_pointer_maps_region_to_screen():
    c, t = active()
    outs, t = point(c, t, 0.75, 0.65, thumb=0.9, dur=0.6)
    assert outs[-1].pointer is not None
    assert outs[-1].pointer[0] > 0.97 and outs[-1].pointer[1] > 0.97


def test_click_requires_thumb_up_first():
    c, t = active()
    outs, t = point(c, t, 0.5, 0.4, thumb=0.2, dur=0.5)   # masuk pose dgn ibu jari turun
    outs2, t = point(c, t, 0.5, 0.4, thumb=0.9, dur=0.2)
    assert actions(outs + outs2) == []


def test_click_freezes_pointer():
    c, t = active()
    outs, t = point(c, t, 0.5, 0.4, thumb=0.9, dur=0.5)
    before = outs[-1].pointer
    o1, t = point(c, t, 0.505, 0.405, thumb=0.2, dur=0.2)   # jari sedikit goyang saat klik
    assert all(abs(o.pointer[0] - before[0]) < 0.01 for o in o1)
    o2, t = point(c, t, 0.505, 0.405, thumb=0.9, dur=0.1)
    assert actions(o1 + o2) == [Action.CLICK]


def test_double_click_is_two_clicks():
    c, t = active()
    _, t = point(c, t, 0.5, 0.4, thumb=0.9, dur=0.4)
    acts = []
    for _ in range(2):
        o1, t = point(c, t, 0.5, 0.4, thumb=0.2, dur=0.1)
        o2, t = point(c, t, 0.5, 0.4, thumb=0.9, dur=0.1)
        acts += actions(o1 + o2)
    assert acts == [Action.CLICK, Action.CLICK]


def test_drag():
    c, t = active()
    _, t = point(c, t, 0.4, 0.4, thumb=0.9, dur=0.4)
    o1, t = point(c, t, 0.4, 0.4, thumb=0.2, dur=0.1)
    o2 = []
    for i in range(10):
        o, t = point(c, t, 0.4 + 0.02 * i, 0.4, thumb=0.2)
        o2 += o
    o3, t = point(c, t, 0.6, 0.4, thumb=0.9, dur=0.1)
    assert actions(o1 + o2 + o3) == [Action.DRAG_START, Action.DRAG_END]
    assert o3[-1].pointer[0] > o1[-1].pointer[0] + 0.2


def test_long_press_right_click():
    c, t = active()
    _, t = point(c, t, 0.5, 0.4, thumb=0.9, dur=0.4)
    o1, t = point(c, t, 0.5, 0.4, thumb=0.2, dur=1.2)
    o2, t = point(c, t, 0.5, 0.4, thumb=0.9, dur=0.1)
    assert actions(o1 + o2) == [Action.RIGHT_CLICK]


def test_leaving_pose_while_dragging_releases_mouse():
    c, t = active()
    _, t = point(c, t, 0.4, 0.4, thumb=0.9, dur=0.4)
    _, t = point(c, t, 0.4, 0.4, thumb=0.2, dur=0.1)
    o, t = point(c, t, 0.5, 0.4, thumb=0.2, dur=0.1)
    assert Action.DRAG_START in actions(o)
    acts, _, _ = run(c, t, t + 0.3)   # tangan hilang
    assert acts == [Action.DRAG_END]


# -------------------------------------------------------------------- scroll
def test_scroll_joystick():
    c, t = active()
    _, out, t = run(c, t, t + 0.2, hand_pose=HandPose.TWO, hand_id="right",
                    hand_x=0.5, hand_y=0.5)
    total = 0
    for _ in range(30):   # tangan naik 0.1 -> scroll ke atas terus
        out = c.update(Frame(timestamp=t, hand_pose=HandPose.TWO, hand_id="right",
                             hand_x=0.5, hand_y=0.4))
        total += out.scroll
        t += DT
    assert total > 500
    total = 0
    for _ in range(30):   # kembali ke titik awal -> berhenti
        out = c.update(Frame(timestamp=t, hand_pose=HandPose.TWO, hand_id="right",
                             hand_x=0.5, hand_y=0.51))
        total += out.scroll
        t += DT
    assert total == 0
    for _ in range(30):
        out = c.update(Frame(timestamp=t, hand_pose=HandPose.TWO, hand_id="right",
                             hand_x=0.5, hand_y=0.6))
        total += out.scroll
        t += DT
    assert total < -500


def test_pose_debounce_ignores_single_frame_glitch():
    c, t = active()
    _, _, t = run(c, t, t + 0.3, hand_pose=HandPose.TWO, **HAND)
    out = c.update(Frame(timestamp=t, hand_pose=HandPose.FIST, **HAND))
    assert out.pose is HandPose.TWO


# -------------------------------------------------------- ekstraksi landmark
def make_hand(fingers="0000", thumb="out", pinch=False):
    """Tangan sintetis menghadap atas. fingers: '1' = lurus, '0' = tertekuk."""
    hand = [P(x=0.5, y=0.8, z=0.0) for _ in range(21)]
    for i, (mcp, pip, dip, tip) in enumerate(((5, 6, 7, 8), (9, 10, 11, 12),
                                              (13, 14, 15, 16), (17, 18, 19, 20))):
        x = 0.44 + i * 0.04
        hand[mcp] = P(x=x, y=0.65, z=0.0)
        hand[pip] = P(x=x, y=0.60, z=0.0)
        if fingers[i] == "1":
            hand[dip] = P(x=x, y=0.56, z=0.0)
            hand[tip] = P(x=x, y=0.52, z=0.0)
        else:
            hand[dip] = P(x=x, y=0.62, z=-0.04)
            hand[tip] = P(x=x, y=0.66, z=-0.02)
    if pinch:
        hand[4] = P(x=hand[8].x + 0.01, y=hand[8].y, z=0.0)
    elif thumb == "out":
        hand[4] = P(x=0.30, y=0.62, z=0.0)
    else:
        hand[4] = P(x=0.46, y=0.63, z=-0.03)
    return hand


def test_classify_hand():
    assert classify_hand(make_hand("1111")) is HandPose.OPEN
    assert classify_hand(make_hand("0000")) is HandPose.FIST
    assert classify_hand(make_hand("1000")) is HandPose.POINT
    assert classify_hand(make_hand("1100")) is HandPose.TWO
    assert classify_hand(make_hand("1011")) is HandPose.OTHER
    assert classify_hand(None) is None


def test_classify_pinch_ok_sign():
    h = make_hand("0111", pinch=True)
    assert classify_hand(h) is HandPose.PINCH


def test_thumb_press_out_vs_in():
    assert thumb_press(make_hand("1000", thumb="out")) > 0.55
    assert thumb_press(make_hand("1000", thumb="in")) < 0.40


def test_extract_and_both_hands_raised():
    f = extract(make_hand("1000"), "right", 1.0, False)
    assert f.hand_pose is HandPose.POINT and f.tip_y == 0.52
    assert extract(None, None, 1.0, True).hand_pose is None

    pose = [P(x=0, y=0.5, visibility=1.0) for _ in range(33)]
    pose[11] = P(x=0.4, y=0.5, visibility=1); pose[12] = P(x=0.6, y=0.5, visibility=1)
    pose[15] = P(x=0.3, y=0.2, visibility=1); pose[16] = P(x=0.7, y=0.2, visibility=1)
    assert both_hands_raised(pose)
    pose[16] = P(x=0.7, y=0.8, visibility=1)
    assert not both_hands_raised(pose)
