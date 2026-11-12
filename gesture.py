"""Logika gesture murni (tanpa kamera / audio / mouse) supaya mudah diuji.

Alur:
    TERKUNCI --(angkat kedua tangan ~1 dtk)--> AKTIF
    AKTIF    --(angkat kedua tangan ~1 dtk)--> TERKUNCI
    AKTIF    --(tidak ada tangan > 3 dtk)----> TERKUNCI

Saat AKTIF (satu tangan), tanpa ganti mode:
    👌 ujung ibu jari + telunjuk menempel, geser naik/turun -> atur volume
    ✊ kepalan ~0.4 dtk                                     -> mute / unmute
    🖐 telapak terbuka, geser kiri/kanan                    -> lagu sebelumnya / berikutnya
    🖐 telapak terbuka, diam ~0.7 dtk                       -> play / pause
    👆 bentuk pistol (telunjuk lurus, ibu jari tegak)        -> gerakkan pointer
         ibu jari turun lalu naik                          -> klik kiri (2x cepat = double click)
         ibu jari turun & tahan sambil gerak               -> drag
         ibu jari turun & tahan diam ~0.8 dtk              -> klik kanan
    ✌ dua jari, geser naik/turun dari titik awal          -> scroll
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Deque, Optional, Sequence, Tuple


class State(Enum):
    LOCKED = "locked"
    ACTIVE = "active"


class HandPose(Enum):
    OPEN = "open"     # 🖐 keempat jari lurus
    FIST = "fist"     # ✊ keempat jari tertekuk
    PINCH = "pinch"   # 👌 ujung ibu jari menempel ujung telunjuk
    POINT = "point"   # 👆 hanya telunjuk lurus
    TWO = "two"       # ✌ telunjuk + jari tengah lurus
    OTHER = "other"


class Action(Enum):
    MUTE = "mute"
    UNMUTE = "unmute"
    PLAY_PAUSE = "play_pause"
    NEXT = "next"
    PREV = "prev"
    CLICK = "click"
    RIGHT_CLICK = "right_click"
    DRAG_START = "drag_start"
    DRAG_END = "drag_end"


@dataclass
class Config:
    hold_time: float = 1.0        # lama kedua tangan diangkat untuk toggle (detik)
    idle_timeout: float = 3.0     # AKTIF -> TERKUNCI bila tangan hilang selama ini
    grace_time: float = 0.5       # jeda setelah toggle sebelum tangan dibaca
    pose_frames: int = 3          # pose harus konsisten sekian frame (anti salah baca)

    # Volume (👌 geser naik/turun)
    volume_gain: float = 3.0      # perubahan volume per tinggi frame (3 = 1/3 frame -> 100%)
    smoothing: float = 0.35       # faktor EMA per frame (kecil = lebih halus)
    deadzone: float = 0.01        # perubahan < 1% tidak dikirim ke sistem
    snap: float = 0.01            # bulatkan ke kelipatan 1%

    # Mute & media
    fist_hold: float = 0.4
    palm_hold: float = 0.7
    still_tolerance: float = 0.04
    swipe_window: float = 0.35
    swipe_distance: float = 0.18
    action_cooldown: float = 0.8

    # Pointer (👆)
    region: Tuple[float, float, float, float] = (0.25, 0.20, 0.75, 0.65)  # area kamera -> layar
    min_cutoff: float = 1.5       # One Euro filter: kecil = lebih stabil saat pelan
    beta: float = 8.0             # One Euro filter: besar = lebih responsif saat cepat
    press_on: float = 0.40        # rasio ibu jari dianggap "ditekan"
    press_off: float = 0.55       # rasio ibu jari dianggap "dilepas" (histeresis)
    press_lookback: float = 0.10  # pointer dikembalikan ke posisi sebelum ibu jari turun
    drag_threshold: float = 0.025 # gerak telunjuk saat ditekan untuk mulai drag
    right_hold: float = 0.8       # tahan diam untuk klik kanan
    release_freeze: float = 0.15  # pointer diam sesaat setelah klik

    # Scroll (✌)
    scroll_deadzone: float = 0.03
    scroll_gain: float = 12000.0  # unit wheel per detik per tinggi frame
    scroll_max: float = 3600.0    # batas kecepatan (unit wheel / detik, 120 = 1 notch)


@dataclass
class Frame:
    """Fitur yang diekstrak dari satu frame kamera (koordinat 0..1, sudah dicermin)."""
    timestamp: float
    both_hands_raised: bool = False
    hand_pose: Optional[HandPose] = None
    hand_id: Optional[str] = None       # "right"/"left": cegah lompatan saat ganti tangan
    hand_x: Optional[float] = None      # tengah telapak
    hand_y: Optional[float] = None
    tip_x: Optional[float] = None       # ujung telunjuk
    tip_y: Optional[float] = None
    pinch_y: Optional[float] = None     # titik tengah ibu jari-telunjuk
    thumb_press: Optional[float] = None # jarak ibu jari ke pangkal jari / ukuran telapak


@dataclass
class Output:
    state: State
    volume: float
    muted: bool = False
    pose: Optional[HandPose] = None
    volume_changed: bool = False
    activation_progress: float = 0.0
    toggled: bool = False
    action: Optional[Action] = None
    pointer: Optional[Tuple[float, float]] = None   # posisi pointer 0..1 di layar
    scroll: int = 0                                  # unit wheel (+ = ke atas)


class OneEuro:
    """Filter 1€: stabil saat gerak pelan, tetap responsif saat gerak cepat."""

    def __init__(self, min_cutoff: float, beta: float, d_cutoff: float = 1.0) -> None:
        self.min_cutoff, self.beta, self.d_cutoff = min_cutoff, beta, d_cutoff
        self.reset()

    def reset(self) -> None:
        self._x: Optional[float] = None
        self._dx = 0.0
        self._t = 0.0

    def __call__(self, x: float, t: float) -> float:
        if self._x is None:
            self._x, self._t = x, t
            return x
        dt = max(t - self._t, 1e-3)
        self._t = t
        self._dx += _alpha(self.d_cutoff, dt) * ((x - self._x) / dt - self._dx)
        cutoff = self.min_cutoff + self.beta * abs(self._dx)
        self._x += _alpha(cutoff, dt) * (x - self._x)
        return self._x


def _alpha(cutoff: float, dt: float) -> float:
    tau = 1.0 / (2 * math.pi * cutoff)
    return 1.0 / (1.0 + tau / dt)


@dataclass
class Controller:
    config: Config = field(default_factory=Config)
    volume: float = 0.5
    muted: bool = False
    state: State = State.LOCKED

    _hold_start: Optional[float] = None
    _latch_released: bool = True
    _last_hand_seen: float = 0.0
    _toggled_at: float = -1e9
    _sent_volume: Optional[float] = None
    _last_t: Optional[float] = None

    # pose
    _pose: Optional[HandPose] = None
    _raw_pose: Optional[HandPose] = None
    _raw_count: int = 0
    _pose_since: float = 0.0
    _pose_used: bool = False
    _hand_id: Optional[str] = None
    _cooldown_until: float = 0.0
    _track: Deque[Tuple[float, float, float]] = field(default_factory=deque)

    # volume & scroll anchor
    _anchor_y: float = 0.0
    _anchor_vol: float = 0.0
    _scroll_acc: float = 0.0

    # pointer
    _fx: Optional[OneEuro] = None
    _fy: Optional[OneEuro] = None
    _pointer: Optional[Tuple[float, float]] = None
    _ptr_hist: Deque[Tuple[float, float, float]] = field(default_factory=deque)
    _armed: bool = False
    _pressed: bool = False
    _press_t: float = 0.0
    _press_anchor: Tuple[float, float] = (0.0, 0.0)
    _press_pos: Tuple[float, float] = (0.0, 0.0)
    _dragging: bool = False
    _right_done: bool = False
    _freeze_until: float = 0.0

    def __post_init__(self) -> None:
        self._fx = OneEuro(self.config.min_cutoff, self.config.beta)
        self._fy = OneEuro(self.config.min_cutoff, self.config.beta)

    # ------------------------------------------------------------------ update
    def update(self, frame: Frame) -> Output:
        cfg, now = self.config, frame.timestamp
        dt = 0.0 if self._last_t is None else min(max(now - self._last_t, 0.0), 0.2)
        self._last_t = now
        out = Output(state=self.state, volume=self.volume)

        if frame.both_hands_raised:
            if self._latch_released:
                if self._hold_start is None:
                    self._hold_start = now
                progress = (now - self._hold_start) / cfg.hold_time
                out.activation_progress = min(progress, 1.0)
                if progress >= 1.0:
                    self._leave_pose(out)
                    self._toggle(now)
                    out.toggled = True
                    out.activation_progress = 0.0
        else:
            self._hold_start = None
            self._latch_released = True

        if self.state is State.ACTIVE and not out.toggled:
            has_hand = frame.hand_pose is not None
            if has_hand or frame.both_hands_raised:
                self._last_hand_seen = now
            usable = (has_hand and not frame.both_hands_raised
                      and now - self._toggled_at >= cfg.grace_time)
            if usable:
                self._handle_hand(frame, out, dt)
            else:
                self._leave_pose(out)
                if now - self._last_hand_seen > cfg.idle_timeout:
                    self.state = State.LOCKED
                    out.toggled = True

        out.state = self.state
        out.volume = self.display_volume
        out.muted = self.muted
        out.pose = self._pose if self.state is State.ACTIVE else None
        return out

    # ------------------------------------------------------------- satu tangan
    def _handle_hand(self, f: Frame, out: Output, dt: float) -> None:
        cfg, now = self.config, f.timestamp

        if f.hand_id != self._hand_id:
            self._hand_id = f.hand_id
            self._leave_pose(out)
            self._raw_pose, self._raw_count = None, 0

        raw = f.hand_pose
        if raw is self._raw_pose:
            self._raw_count += 1
        else:
            self._raw_pose, self._raw_count = raw, 1
        if raw is not self._pose and self._raw_count >= cfg.pose_frames:
            self._leave_pose(out)
            self._enter_pose(raw, f, now)
        pose = self._pose
        if pose is None:
            return

        if f.hand_x is not None and f.hand_y is not None:
            self._track.append((now, f.hand_x, f.hand_y))
        horizon = max(cfg.swipe_window, cfg.palm_hold) + 0.1
        while self._track and now - self._track[0][0] > horizon:
            self._track.popleft()

        if pose is HandPose.FIST:
            if not self._pose_used and now - self._pose_since >= cfg.fist_hold:
                self.muted = not self.muted
                self._fire(Action.MUTE if self.muted else Action.UNMUTE, out, now)
        elif pose is HandPose.OPEN:
            if now < self._cooldown_until:
                return
            swipe = self._detect_swipe(now)
            if swipe is not None:
                self._fire(swipe, out, now)
                self._track.clear()
            elif (not self._pose_used and now - self._pose_since >= cfg.palm_hold
                  and self._is_still(now)):
                self._fire(Action.PLAY_PAUSE, out, now)
        elif pose is HandPose.PINCH:
            if not self.muted and f.pinch_y is not None:
                self._update_volume(f.pinch_y, out)
        elif pose is HandPose.TWO:
            if f.hand_y is not None:
                self._update_scroll(f.hand_y, out, dt)
        elif pose is HandPose.POINT:
            if f.tip_x is not None and f.tip_y is not None:
                self._update_pointer(f, out, now)

    def _enter_pose(self, pose: HandPose, f: Frame, now: float) -> None:
        self._pose, self._pose_since, self._pose_used = pose, now, False
        self._track.clear()
        if pose is HandPose.PINCH:
            self._anchor_y = f.pinch_y if f.pinch_y is not None else 0.5
            self._anchor_vol = self.display_volume
            self.volume = self._anchor_vol
        elif pose is HandPose.TWO:
            self._anchor_y = f.hand_y if f.hand_y is not None else 0.5
            self._scroll_acc = 0.0
        elif pose is HandPose.POINT:
            self._fx.reset()
            self._fy.reset()
            self._ptr_hist.clear()
            self._armed = self._pressed = self._dragging = False

    def _leave_pose(self, out: Output) -> None:
        if self._pose is HandPose.POINT and self._pressed and self._dragging:
            out.action = Action.DRAG_END
        self._pressed = self._dragging = False
        self._pose = None
        self._track.clear()

    def _fire(self, action: Action, out: Output, now: float) -> None:
        out.action = action
        self._pose_used = True
        self._cooldown_until = now + self.config.action_cooldown

    # ------------------------------------------------------------------ volume
    def _update_volume(self, y: float, out: Output) -> None:
        cfg = self.config
        target = self._anchor_vol + (self._anchor_y - y) * cfg.volume_gain
        if target > 1.0 or target < 0.0:
            # Mentok: geser anchor supaya arah balik langsung terasa
            target = min(max(target, 0.0), 1.0)
            self._anchor_vol, self._anchor_y = target, y
        self.volume += (target - self.volume) * cfg.smoothing
        snapped = min(max(round(self.volume / cfg.snap) * cfg.snap, 0.0), 1.0)
        if self._sent_volume is None or abs(snapped - self._sent_volume) >= cfg.deadzone:
            self._sent_volume = snapped
            out.volume_changed = True

    # ------------------------------------------------------------------ scroll
    def _update_scroll(self, y: float, out: Output, dt: float) -> None:
        cfg = self.config
        off = self._anchor_y - y          # tangan naik -> positif -> scroll ke atas
        if abs(off) <= cfg.scroll_deadzone:
            self._scroll_acc = 0.0
            return
        rate = min((abs(off) - cfg.scroll_deadzone) * cfg.scroll_gain, cfg.scroll_max)
        self._scroll_acc += math.copysign(rate, off) * dt
        step = int(self._scroll_acc)
        if step:
            out.scroll = step
            self._scroll_acc -= step

    # ----------------------------------------------------------------- pointer
    def _update_pointer(self, f: Frame, out: Output, now: float) -> None:
        cfg = self.config
        x0, y0, x1, y1 = cfg.region
        rx = _map_range(f.tip_x, x0, x1)
        ry = _map_range(f.tip_y, y0, y1)
        sx, sy = self._fx(rx, now), self._fy(ry, now)
        self._ptr_hist.append((now, sx, sy))
        while len(self._ptr_hist) > 2 and now - self._ptr_hist[0][0] > 0.5:
            self._ptr_hist.popleft()

        p = f.thumb_press
        if not self._pressed:
            if p is not None and p > cfg.press_off:
                self._armed = True  # ibu jari harus tegak dulu sebelum bisa klik
            if self._armed and p is not None and p < cfg.press_on:
                self._pressed, self._press_t = True, now
                self._press_anchor = (f.tip_x, f.tip_y)
                self._press_pos = self._pointer_at(now - cfg.press_lookback)
                self._dragging = self._right_done = False
        else:
            if p is not None and p > cfg.press_off:
                self._pressed = False
                if self._dragging:
                    out.action = Action.DRAG_END
                elif not self._right_done:
                    out.action = Action.CLICK
                self._dragging = False
                self._freeze_until = now + cfg.release_freeze
            elif not self._dragging and not self._right_done:
                ax, ay = self._press_anchor
                if math.hypot(f.tip_x - ax, f.tip_y - ay) > cfg.drag_threshold:
                    self._dragging = True
                    out.action = Action.DRAG_START
                elif now - self._press_t >= cfg.right_hold:
                    self._right_done = True
                    out.action = Action.RIGHT_CLICK

        if self._pressed and not self._dragging:
            pointer = self._press_pos
        elif now < self._freeze_until and self._pointer is not None:
            pointer = self._pointer
        else:
            pointer = (sx, sy)
        if out.action is Action.DRAG_START:
            pointer = self._press_pos   # mouse ditekan di titik awal, baru ikut bergerak
        self._pointer = pointer
        out.pointer = pointer

    def _pointer_at(self, t: float) -> Tuple[float, float]:
        best = None
        for ts, x, y in self._ptr_hist:
            if ts <= t or best is None:
                best = (x, y)
            if ts > t:
                break
        return best if best is not None else (0.5, 0.5)

    # ------------------------------------------------------------------- media
    def _detect_swipe(self, now: float) -> Optional[Action]:
        cfg = self.config
        pts = [p for p in self._track if now - p[0] <= cfg.swipe_window]
        if len(pts) < 3:
            return None
        dx = pts[-1][1] - pts[0][1]
        dy = pts[-1][2] - pts[0][2]
        if abs(dx) >= cfg.swipe_distance and abs(dx) > 2 * abs(dy):
            return Action.NEXT if dx > 0 else Action.PREV
        return None

    def _is_still(self, now: float) -> bool:
        pts = [p for p in self._track if now - p[0] <= self.config.palm_hold]
        if len(pts) < 3:
            return False
        xs, ys = [p[1] for p in pts], [p[2] for p in pts]
        tol = self.config.still_tolerance
        return max(xs) - min(xs) <= tol and max(ys) - min(ys) <= tol

    # ------------------------------------------------------------------ public
    @property
    def display_volume(self) -> float:
        return self._sent_volume if self._sent_volume is not None else self.volume

    def sync_volume(self, volume: float) -> None:
        """Samakan dengan volume sistem saat ini (mis. diubah lewat keyboard)."""
        self.volume = volume
        self._sent_volume = volume

    def _toggle(self, now: float) -> None:
        self.state = State.LOCKED if self.state is State.ACTIVE else State.ACTIVE
        self._hold_start = None
        self._latch_released = False
        self._toggled_at = now
        self._last_hand_seen = now
        self._raw_pose, self._raw_count = None, 0


# ---------------------------------------------------------------------------
# Ekstraksi fitur dari landmark MediaPipe (koordinat ternormalisasi, y ke bawah)
# ---------------------------------------------------------------------------

L_SHOULDER, R_SHOULDER, L_WRIST, R_WRIST = 11, 12, 15, 16
WRIST, THUMB_TIP, INDEX_MCP, INDEX_TIP, MIDDLE_MCP, MIDDLE_PIP = 0, 4, 5, 8, 9, 10
FINGERS = ((5, 6, 7, 8), (9, 10, 11, 12), (13, 14, 15, 16), (17, 18, 19, 20))
PALM = (0, 5, 9, 13, 17)

EXTENDED_DEG = 155.0   # rata-rata sudut sendi >= ini: jari lurus
DOWN_DEG = 130.0       # <= ini: jari tidak lurus (untuk pose pistol / dua jari)
CURLED_DEG = 110.0     # <= ini: jari tertekuk (untuk kepalan)
PINCH_TOUCH = 0.35     # jarak ujung ibu jari-telunjuk / telapak: dianggap menempel


def both_hands_raised(pose: Sequence, min_visibility: float = 0.5) -> bool:
    """True bila kedua pergelangan tangan berada di atas bahu masing-masing."""
    if pose is None:
        return False
    try:
        ls, rs, lw, rw = pose[L_SHOULDER], pose[R_SHOULDER], pose[L_WRIST], pose[R_WRIST]
    except (IndexError, TypeError):
        return False
    for lm in (ls, rs, lw, rw):
        if getattr(lm, "visibility", 1.0) < min_visibility:
            return False
    return lw.y < ls.y and rw.y < rs.y


def finger_bends(hand: Sequence) -> list:
    """Rata-rata sudut sendi PIP & DIP tiap jari (180° = lurus)."""
    bends = []
    for mcp, pip, dip, tip in FINGERS:
        a = _angle(hand[mcp], hand[pip], hand[dip])
        b = _angle(hand[pip], hand[dip], hand[tip])
        bends.append((a + b) / 2)
    return bends


def classify_hand(hand: Sequence) -> Optional[HandPose]:
    if hand is None:
        return None
    palm = _dist(hand[WRIST], hand[MIDDLE_MCP])
    if palm < 1e-6:
        return None
    bends = finger_bends(hand)
    ext = [b >= EXTENDED_DEG for b in bends]
    down = [b <= DOWN_DEG for b in bends]
    if all(b <= CURLED_DEG for b in bends):
        return HandPose.FIST
    if _dist(hand[THUMB_TIP], hand[INDEX_TIP]) / palm < PINCH_TOUCH:
        return HandPose.PINCH
    if all(ext):
        return HandPose.OPEN
    if ext[0] and ext[1] and down[2] and down[3]:
        return HandPose.TWO
    if ext[0] and down[1] and down[2] and down[3]:
        return HandPose.POINT
    return HandPose.OTHER


def thumb_press(hand: Sequence) -> Optional[float]:
    """Kecil saat ibu jari ditekan ke sisi tangan, besar saat ibu jari tegak (pistol)."""
    if hand is None:
        return None
    palm = _dist(hand[WRIST], hand[MIDDLE_MCP])
    if palm < 1e-6:
        return None
    t = hand[THUMB_TIP]
    return min(_dist(t, hand[i]) for i in (INDEX_MCP, MIDDLE_MCP, MIDDLE_PIP)) / palm


def extract(hand: Optional[Sequence], hand_id: Optional[str], timestamp: float,
            raised: bool) -> Frame:
    if hand is None:
        return Frame(timestamp=timestamp, both_hands_raised=raised)
    cx = sum(hand[i].x for i in PALM) / len(PALM)
    cy = sum(hand[i].y for i in PALM) / len(PALM)
    return Frame(
        timestamp=timestamp,
        both_hands_raised=raised,
        hand_pose=classify_hand(hand),
        hand_id=hand_id,
        hand_x=cx, hand_y=cy,
        tip_x=hand[INDEX_TIP].x, tip_y=hand[INDEX_TIP].y,
        pinch_y=(hand[THUMB_TIP].y + hand[INDEX_TIP].y) / 2,
        thumb_press=thumb_press(hand),
    )


def _dist(a, b) -> float:
    return math.hypot(a.x - b.x, a.y - b.y)


def _angle(a, b, c) -> float:
    v1 = (a.x - b.x, a.y - b.y, getattr(a, "z", 0.0) - getattr(b, "z", 0.0))
    v2 = (c.x - b.x, c.y - b.y, getattr(c, "z", 0.0) - getattr(b, "z", 0.0))
    n1, n2 = math.sqrt(sum(v * v for v in v1)), math.sqrt(sum(v * v for v in v2))
    if n1 < 1e-9 or n2 < 1e-9:
        return 180.0
    cos = sum(p * q for p, q in zip(v1, v2)) / (n1 * n2)
    return math.degrees(math.acos(min(max(cos, -1.0), 1.0)))


def _map_range(v: float, lo: float, hi: float) -> float:
    return min(max((v - lo) / (hi - lo), 0.0), 1.0)
