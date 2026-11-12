"""Logika gesture murni (tanpa kamera / audio) supaya mudah diuji.

Alur:
    TERKUNCI --(angkat kedua tangan ~1 dtk)--> AKTIF
    AKTIF    --(angkat kedua tangan ~1 dtk)--> TERKUNCI
    AKTIF    --(tidak ada tangan > 3 dtk)----> TERKUNCI

Saat AKTIF, volume diatur dari jarak ibu jari ke telunjuk yang
dinormalisasi dengan ukuran telapak tangan, lalu dihaluskan.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Sequence, Tuple

Point = Tuple[float, float]


class State(Enum):
    LOCKED = "locked"
    ACTIVE = "active"


@dataclass
class Config:
    hold_time: float = 1.0        # lama kedua tangan diangkat untuk toggle (detik)
    idle_timeout: float = 3.0     # AKTIF -> TERKUNCI bila tangan hilang selama ini
    grace_time: float = 0.5       # jeda setelah toggle sebelum cubitan dibaca
    pinch_min: float = 0.20       # rasio cubit = volume 0%
    pinch_max: float = 1.10       # rasio cubit = volume 100%
    smoothing: float = 0.25       # faktor EMA per frame (0..1, kecil = lebih halus)
    deadzone: float = 0.01        # perubahan < 1% tidak dikirim ke sistem
    snap: float = 0.02            # bulatkan ke kelipatan 2%


@dataclass
class Frame:
    """Fitur yang diekstrak dari satu frame kamera."""
    timestamp: float
    both_hands_raised: bool = False
    pinch_ratio: Optional[float] = None


@dataclass
class Output:
    state: State
    volume: float                       # volume halus saat ini (0..1)
    volume_changed: bool = False        # True bila volume perlu dikirim ke sistem
    activation_progress: float = 0.0    # 0..1 saat kedua tangan sedang diangkat
    toggled: bool = False               # True pada frame terjadinya perubahan state


@dataclass
class Controller:
    config: Config = field(default_factory=Config)
    volume: float = 0.5

    state: State = State.LOCKED
    _hold_start: Optional[float] = None
    _latch_released: bool = True
    _last_hand_seen: float = 0.0
    _toggled_at: float = -1e9
    _sent_volume: Optional[float] = None

    def update(self, frame: Frame) -> Output:
        cfg, now = self.config, frame.timestamp
        out = Output(state=self.state, volume=self.volume)

        # --- Deteksi gesture aktivasi (kedua tangan diangkat & ditahan) ---
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

        # --- Kontrol volume ---
        if self.state is State.ACTIVE and not out.toggled:
            usable = (
                frame.pinch_ratio is not None
                and not frame.both_hands_raised
                and now - self._toggled_at >= cfg.grace_time
            )
            if frame.pinch_ratio is not None or frame.both_hands_raised:
                self._last_hand_seen = now
            if usable:
                target = _map_range(frame.pinch_ratio, cfg.pinch_min, cfg.pinch_max)
                self.volume += (target - self.volume) * cfg.smoothing
                snapped = round(self.volume / cfg.snap) * cfg.snap
                snapped = min(max(snapped, 0.0), 1.0)
                if self._sent_volume is None or abs(snapped - self._sent_volume) >= cfg.deadzone:
                    self._sent_volume = snapped
                    out.volume_changed = True
            elif now - self._last_hand_seen > cfg.idle_timeout:
                self.state = State.LOCKED
                out.toggled = True

        out.state = self.state
        out.volume = self.display_volume
        return out

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


# ---------------------------------------------------------------------------
# Ekstraksi fitur dari landmark MediaPipe (koordinat ternormalisasi, y ke bawah)
# ---------------------------------------------------------------------------

# Indeks landmark MediaPipe Pose
L_SHOULDER, R_SHOULDER, L_WRIST, R_WRIST = 11, 12, 15, 16
# Indeks landmark MediaPipe Hands
WRIST, THUMB_TIP, INDEX_TIP, MIDDLE_MCP = 0, 4, 8, 9


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


def _dist(a, b) -> float:
    return math.hypot(a.x - b.x, a.y - b.y)


def _map_range(v: float, lo: float, hi: float) -> float:
    return min(max((v - lo) / (hi - lo), 0.0), 1.0)
