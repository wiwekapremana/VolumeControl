"""Logika gesture murni (tanpa kamera / audio) supaya mudah diuji.

Alur:
    TERKUNCI --(angkat kedua tangan ~1 dtk)--> AKTIF
    AKTIF    --(angkat kedua tangan ~1 dtk)--> TERKUNCI
    AKTIF    --(tidak ada tangan > 3 dtk)----> TERKUNCI

Saat AKTIF (satu tangan):
    cubit ibu jari & telunjuk        -> atur volume (dihaluskan)
    kepalkan tangan ~0.4 dtk         -> mute / unmute
    telapak terbuka, geser kiri/kanan -> lagu sebelumnya / berikutnya
    telapak terbuka, diam ~0.7 dtk   -> play / pause
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
    OPEN = "open"     # keempat jari lurus (telapak terbuka)
    FIST = "fist"     # keempat jari tertekuk (kepalan)
    OTHER = "other"   # pose lain -> dipakai untuk cubitan volume


class Action(Enum):
    MUTE = "mute"
    UNMUTE = "unmute"
    PLAY_PAUSE = "play_pause"
    NEXT = "next"
    PREV = "prev"


@dataclass
class Config:
    hold_time: float = 1.0        # lama kedua tangan diangkat untuk toggle (detik)
    idle_timeout: float = 3.0     # AKTIF -> TERKUNCI bila tangan hilang selama ini
    grace_time: float = 0.5       # jeda setelah toggle sebelum tangan dibaca
    pinch_min: float = 0.20       # rasio cubit = volume 0%
    pinch_max: float = 1.10       # rasio cubit = volume 100%
    smoothing: float = 0.25       # faktor EMA per frame (0..1, kecil = lebih halus)
    deadzone: float = 0.01        # perubahan < 1% tidak dikirim ke sistem
    snap: float = 0.02            # bulatkan ke kelipatan 2%

    fist_hold: float = 0.4        # lama kepalan untuk mute/unmute
    palm_hold: float = 0.7        # lama telapak diam untuk play/pause
    still_tolerance: float = 0.04 # gerak maks (lebar frame) agar dianggap diam
    swipe_window: float = 0.35    # jendela waktu deteksi geser (detik)
    swipe_distance: float = 0.18  # jarak geser minimum (lebar frame)
    action_cooldown: float = 0.8  # jeda antar aksi media
    restore_lookback: float = 0.3 # kembalikan volume ke nilai sebelum ganti pose


@dataclass
class Frame:
    """Fitur yang diekstrak dari satu frame kamera."""
    timestamp: float
    both_hands_raised: bool = False
    pinch_ratio: Optional[float] = None
    hand_pose: Optional[HandPose] = None
    hand_x: Optional[float] = None      # posisi tengah telapak (0..1, sudah dicermin)
    hand_y: Optional[float] = None
    hand_id: Optional[str] = None       # "right"/"left": cegah lompatan saat ganti tangan


@dataclass
class Output:
    state: State
    volume: float                       # volume halus saat ini (0..1)
    muted: bool = False
    volume_changed: bool = False        # True bila volume perlu dikirim ke sistem
    activation_progress: float = 0.0    # 0..1 saat kedua tangan sedang diangkat
    toggled: bool = False               # True pada frame terjadinya perubahan state
    action: Optional[Action] = None     # aksi mute / media pada frame ini


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

    _pose: Optional[HandPose] = None
    _pose_since: float = 0.0
    _pose_used: bool = False            # aksi sudah dipicu untuk pose ini
    _hand_id: Optional[str] = None
    _cooldown_until: float = 0.0
    _restore_volume: Optional[float] = None
    _track: Deque[Tuple[float, float, float]] = field(default_factory=deque)
    _vol_hist: Deque[Tuple[float, float]] = field(default_factory=deque)

    def update(self, frame: Frame) -> Output:
        cfg, now = self.config, frame.timestamp
        out = Output(state=self.state, volume=self.volume)

        # --- Gesture aktivasi (kedua tangan diangkat & ditahan) ---
        if frame.both_hands_raised:
            if self._latch_released:
                if self._hold_start is None:
                    self._hold_start = now
                progress = (now - self._hold_start) / cfg.hold_time
                out.activation_progress = min(progress, 1.0)
                if progress >= 1.0:
                    self._toggle(now)
                    out.toggled = True
                    out.activation_progress = 0.0
        else:
            self._hold_start = None
            self._latch_released = True  # harus turunkan tangan sebelum toggle lagi

        if self.state is State.ACTIVE and not out.toggled:
            has_hand = frame.pinch_ratio is not None
            if has_hand or frame.both_hands_raised:
                self._last_hand_seen = now
            usable = (has_hand and not frame.both_hands_raised
                      and now - self._toggled_at >= cfg.grace_time)
            if usable:
                self._handle_hand(frame, out)
            else:
                self._reset_pose()
                if now - self._last_hand_seen > cfg.idle_timeout:
                    self.state = State.LOCKED
                    out.toggled = True

        out.state = self.state
        out.volume = self.display_volume
        out.muted = self.muted
        return out

    # ------------------------------------------------------------- satu tangan
    def _handle_hand(self, f: Frame, out: Output) -> None:
        cfg, now = self.config, f.timestamp
        pose = f.hand_pose or HandPose.OTHER

        if f.hand_id != self._hand_id:
            self._track.clear()
            self._hand_id = f.hand_id
        if pose is not self._pose:
            if self._pose is HandPose.OTHER:
                # Saat berganti pose, jarak cubit ikut berubah sebentar.
                # Simpan volume sebelum transisi agar bisa dikembalikan.
                self._restore_volume = self._volume_at(now - cfg.restore_lookback)
            self._pose, self._pose_since, self._pose_used = pose, now, False
            self._track.clear()  # gerakan dari pose sebelumnya bukan swipe

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
        elif not self.muted:
            self._restore_volume = None
            self._update_volume(f.pinch_ratio, out, now)

    def _fire(self, action: Action, out: Output, now: float) -> None:
        out.action = action
        self._pose_used = True
        self._cooldown_until = now + self.config.action_cooldown
        restore = self._restore_volume
        self._restore_volume = None
        if restore is not None and self._sent_volume is not None \
                and abs(restore - self._sent_volume) >= self.config.deadzone:
            self.volume = self._sent_volume = restore
            out.volume_changed = True

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

    def _update_volume(self, ratio: float, out: Output, now: float) -> None:
        cfg = self.config
        target = _map_range(ratio, cfg.pinch_min, cfg.pinch_max)
        self.volume += (target - self.volume) * cfg.smoothing
        snapped = min(max(round(self.volume / cfg.snap) * cfg.snap, 0.0), 1.0)
        if self._sent_volume is None or abs(snapped - self._sent_volume) >= cfg.deadzone:
            self._sent_volume = snapped
            out.volume_changed = True
        self._vol_hist.append((now, self.display_volume))
        while len(self._vol_hist) > 2 and now - self._vol_hist[1][0] > 1.0:
            self._vol_hist.popleft()

    def _volume_at(self, t: float) -> float:
        best = self.display_volume
        for ts, v in reversed(self._vol_hist):
            best = v
            if ts <= t:
                break
        return best

    def _reset_pose(self) -> None:
        self._pose = None
        self._track.clear()

    # ------------------------------------------------------------------ public
    @property
    def display_volume(self) -> float:
        return self._sent_volume if self._sent_volume is not None else self.volume

    def sync_volume(self, volume: float) -> None:
        """Samakan dengan volume sistem saat ini (mis. diubah lewat keyboard)."""
        self.volume = volume
        self._sent_volume = volume
        self._vol_hist.clear()

    def _toggle(self, now: float) -> None:
        self.state = State.LOCKED if self.state is State.ACTIVE else State.ACTIVE
        self._hold_start = None
        self._latch_released = False
        self._toggled_at = now
        self._last_hand_seen = now
        self._reset_pose()


# ---------------------------------------------------------------------------
# Ekstraksi fitur dari landmark MediaPipe (koordinat ternormalisasi, y ke bawah)
# ---------------------------------------------------------------------------

# Indeks landmark MediaPipe Pose
L_SHOULDER, R_SHOULDER, L_WRIST, R_WRIST = 11, 12, 15, 16
# Indeks landmark MediaPipe Hands
WRIST, THUMB_TIP, INDEX_TIP, MIDDLE_MCP = 0, 4, 8, 9
# (MCP, PIP, DIP, TIP) untuk telunjuk, tengah, manis, kelingking
FINGERS = ((5, 6, 7, 8), (9, 10, 11, 12), (13, 14, 15, 16), (17, 18, 19, 20))
PALM = (0, 5, 9, 13, 17)

EXTENDED_DEG = 155.0   # sudut sendi di atas ini = jari lurus
CURLED_DEG = 110.0     # sudut sendi di bawah ini = jari tertekuk


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


def pinch_ratio(hand: Sequence) -> Optional[float]:
    """Jarak ibu jari–telunjuk dibagi ukuran telapak (tak bergantung jarak ke kamera)."""
    if hand is None:
        return None
    palm = _dist(hand[WRIST], hand[MIDDLE_MCP])
    if palm < 1e-6:
        return None
    return _dist(hand[THUMB_TIP], hand[INDEX_TIP]) / palm


def classify_hand(hand: Sequence) -> Optional[HandPose]:
    """Tentukan pose tangan dari sudut lipatan keempat jari (3D, tahan rotasi)."""
    if hand is None:
        return None
    bends = []
    for mcp, pip, dip, tip in FINGERS:
        # Rata-rata sudut di sendi PIP & DIP: 180° = lurus, makin kecil makin tertekuk
        a = _angle(hand[mcp], hand[pip], hand[dip])
        b = _angle(hand[pip], hand[dip], hand[tip])
        bends.append((a + b) / 2)
    if all(x >= EXTENDED_DEG for x in bends):
        return HandPose.OPEN
    if all(x <= CURLED_DEG for x in bends):
        return HandPose.FIST
    return HandPose.OTHER


def palm_center(hand: Sequence) -> Optional[Tuple[float, float]]:
    if hand is None:
        return None
    return (sum(hand[i].x for i in PALM) / len(PALM),
            sum(hand[i].y for i in PALM) / len(PALM))


def _dist(a, b) -> float:
    return math.hypot(a.x - b.x, a.y - b.y)


def _angle(a, b, c) -> float:
    """Sudut ABC dalam derajat, memakai z bila tersedia."""
    v1 = (a.x - b.x, a.y - b.y, getattr(a, "z", 0.0) - getattr(b, "z", 0.0))
    v2 = (c.x - b.x, c.y - b.y, getattr(c, "z", 0.0) - getattr(b, "z", 0.0))
    n1, n2 = math.sqrt(sum(v * v for v in v1)), math.sqrt(sum(v * v for v in v2))
    if n1 < 1e-9 or n2 < 1e-9:
        return 180.0
    cos = sum(p * q for p, q in zip(v1, v2)) / (n1 * n2)
    return math.degrees(math.acos(min(max(cos, -1.0), 1.0)))


def _map_range(v: float, lo: float, hi: float) -> float:
    return min(max((v - lo) / (hi - lo), 0.0), 1.0)
