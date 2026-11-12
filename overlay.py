"""Indikator volume kecil yang melayang di layar (pengganti jendela video).

- Muncul saat aktivasi / mode AKTIF, lalu memudar sendiri saat terkunci.
- Selalu di atas (always-on-top), tidak bisa diklik (klik tembus), tanpa bingkai.
"""

from __future__ import annotations

import sys
import tkinter as tk

from gesture import Action, HandPose, State

W, H = 320, 78
KEY = "#ff00fe"                 # warna "transparan" untuk sudut membulat (Windows)
BG = "#16181d"
TRACK = "#2b2f38"
TEXT = "#e8eaed"
MUTED = "#8b919c"
C_ACTIVE = "#34d399"
C_ARMING = "#fbbf24"
C_LOCKED = "#9ca3af"
C_MUTED = "#f87171"
C_MEDIA = "#60a5fa"

MAX_ALPHA = 0.93
LOCK_FLASH = 1.4                # lama pesan "Terkunci" tampil (detik)
TOAST_TIME = 1.3                # lama notifikasi aksi tampil (detik)

ACTION_LABEL = {
    Action.MUTE: ("Mute", C_MUTED),
    Action.UNMUTE: ("Suara aktif kembali", C_ACTIVE),
    Action.PLAY_PAUSE: ("Play / Pause", C_MEDIA),
    Action.NEXT: ("Lagu berikutnya", C_MEDIA),
    Action.PREV: ("Lagu sebelumnya", C_MEDIA),
    Action.RIGHT_CLICK: ("Klik kanan", C_MEDIA),
}

POSE_HINT = {
    HandPose.POINT: "Pointer · ibu jari turun = klik",
    HandPose.TWO: "Scroll · geser naik / turun",
    HandPose.PINCH: "Volume · geser naik / turun",
}


class Overlay:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.attributes("-alpha", 0.0)

        is_win = sys.platform == "win32"
        bg = KEY if is_win else BG
        if is_win:
            root.attributes("-transparentcolor", KEY)
        root.configure(bg=bg)

        # Skala untuk layar DPI tinggi (125%, 150%, ...)
        self.s = s = max(1.0, root.winfo_fpixels("1i") / 96.0)
        w, h = round(W * s), round(H * s)
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        root.geometry(f"{w}x{h}+{(sw - w) // 2}+{sh - h - round(110 * s)}")

        self.c = tk.Canvas(root, width=w, height=h, bg=bg, highlightthickness=0)
        self.c.pack()
        if is_win:
            root.after(50, self._make_click_through)

        self._alpha = 0.0
        self._shown_vol = 0.0
        self._lock_flash_until = 0.0
        self._visible = True
        self._toast: Action | None = None
        self._toast_at = -1e9
        self._now = 0.0
        self._pose: HandPose | None = None
        self._last_key = None
        self.busy = False   # True saat indikator tampil / beranimasi

    # ------------------------------------------------------------------ public
    def render(self, state: State, volume: float, progress: float, now: float,
               just_locked: bool = False, muted: bool = False,
               action: Action | None = None, pose: HandPose | None = None) -> None:
        self._now = now
        self._pose = pose
        if action in ACTION_LABEL:
            self._toast, self._toast_at = action, now
        if just_locked:
            self._lock_flash_until = now + LOCK_FLASH

        want_visible = (
            state is State.ACTIVE or progress > 0 or now < self._lock_flash_until
        )
        target = MAX_ALPHA if want_visible else 0.0
        self._alpha += (target - self._alpha) * 0.18
        if abs(target - self._alpha) < 0.01:
            self._alpha = target
        self._shown_vol += (volume - self._shown_vol) * 0.3

        self.busy = want_visible or self._alpha > 0.0
        if self._alpha <= 0.0:
            if self._visible:
                self.root.withdraw()
                self._visible = False
            return
        if not self._visible:
            self.root.deiconify()
            self.root.attributes("-topmost", True)
            self._visible = True
        # Gambar ulang hanya bila ada yang berubah
        toast = self._toast if now - self._toast_at < TOAST_TIME else None
        key = (state, round(progress, 2), muted, self._pose, toast,
               round(self._shown_vol, 3), round(self._alpha, 2),
               toast is not None and now - self._toast_at < 0.25 and round(now - self._toast_at, 2))
        if key == self._last_key:
            return
        self._last_key = key
        self.root.attributes("-alpha", self._alpha)
        self._draw(state, progress, muted)

    # ----------------------------------------------------------------- drawing
    def _draw(self, state: State, progress: float, muted: bool) -> None:
        c = self.c
        c.delete("all")
        _round_rect(c, 2, 2, W - 2, H - 2, 22, fill=BG, outline="#262a33")

        toast_age = self._now - self._toast_at
        toast = self._toast if toast_age < TOAST_TIME else None

        if toast is not None and progress == 0:
            label, accent = ACTION_LABEL[toast]
        elif progress > 0:
            accent, label = C_ARMING, ("Tahan untuk kunci…" if state is State.ACTIVE
                                       else "Tahan untuk aktifkan…")
        elif muted:
            accent, label = C_MUTED, "Mute · kepalkan tangan"
        elif state is State.ACTIVE:
            accent, label = C_ACTIVE, POSE_HINT.get(self._pose, "Gesture control aktif")
        else:
            accent, label = C_LOCKED, "Terkunci"

        # Ikon speaker + cincin progres aktivasi
        cx, cy, r = 40, H // 2, 20
        if toast is not None and toast_age < 0.25:  # efek "pop" saat aksi
            r += round(5 * (1 - toast_age / 0.25))
        c.create_oval(cx - r, cy - r, cx + r, cy + r, outline=TRACK, width=3)
        if progress > 0:
            c.create_arc(cx - r, cy - r, cx + r, cy + r, start=90,
                         extent=-359.9 * progress, style="arc", outline=accent, width=3)
        elif state is State.ACTIVE or toast is not None:
            c.create_oval(cx - r, cy - r, cx + r, cy + r, outline=accent, width=3)
        if toast in (Action.PLAY_PAUSE, Action.NEXT, Action.PREV) and progress == 0:
            self._media_icon(cx, cy, accent, toast)
        else:
            self._speaker(cx, cy, accent, muted=muted or self._shown_vol < 0.01)

        # Label + persentase
        x0, x1 = 76, W - 24
        c.create_text(x0, 24, text=label, anchor="w", fill=MUTED,
                      font=("Segoe UI", 9))
        c.create_text(x1, 24, text=f"{round(self._shown_vol * 100)}%", anchor="e",
                      fill=TEXT, font=("Segoe UI Semibold", 12))

        # Bar volume
        by = 50
        _round_rect(c, x0, by - 4, x1, by + 4, 4, fill=TRACK, outline="")
        fx = x0 + (x1 - x0) * self._shown_vol
        bar = C_LOCKED if muted else accent
        if fx - x0 > 8:
            _round_rect(c, x0, by - 4, fx, by + 4, 4, fill=bar, outline="")
        c.create_oval(fx - 7, by - 7, fx + 7, by + 7, fill=TEXT, outline="")
        if self.s != 1.0:
            c.scale("all", 0, 0, self.s, self.s)

    def _media_icon(self, cx: int, cy: int, color: str, action: Action) -> None:
        c = self.c
        if action is Action.PLAY_PAUSE:
            c.create_polygon(cx - 9, cy - 8, cx - 9, cy + 8, cx + 1, cy, fill=color)
            c.create_rectangle(cx + 3, cy - 8, cx + 6, cy + 8, fill=color, outline="")
            c.create_rectangle(cx + 8, cy - 8, cx + 11, cy + 8, fill=color, outline="")
            return
        s = 1 if action is Action.NEXT else -1
        for off in (-8, 0):
            x = cx + s * off
            c.create_polygon(x, cy - 7, x, cy + 7, x + s * 8, cy, fill=color)
        bx = cx + s * 9
        c.create_rectangle(min(bx, bx + s * 3), cy - 7, max(bx, bx + s * 3), cy + 7,
                           fill=color, outline="")

    def _speaker(self, cx: int, cy: int, color: str, muted: bool) -> None:
        c = self.c
        c.create_polygon(cx - 9, cy - 4, cx - 4, cy - 4, cx + 2, cy - 9,
                         cx + 2, cy + 9, cx - 4, cy + 4, cx - 9, cy + 4, fill=color)
        if muted:
            c.create_line(cx + 5, cy - 4, cx + 11, cy + 4, fill=color, width=2)
            c.create_line(cx + 5, cy + 4, cx + 11, cy - 4, fill=color, width=2)
            return
        waves = 1 + (self._shown_vol > 0.33) + (self._shown_vol > 0.66)
        for i in range(waves):
            rr = 5 + i * 4
            c.create_arc(cx + 2 - rr, cy - rr, cx + 2 + rr, cy + rr, start=-45,
                         extent=90, style="arc", outline=color, width=2)

    def _make_click_through(self) -> None:
        try:
            import ctypes
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
            GWL_EXSTYLE, WS_EX_LAYERED, WS_EX_TRANSPARENT = -20, 0x80000, 0x20
            WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE = 0x80, 0x08000000
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            style |= WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
        except Exception as exc:  # tidak fatal
            print(f"[info] Overlay tidak bisa dibuat klik-tembus: {exc}")


def _round_rect(c: tk.Canvas, x0, y0, x1, y1, r, **kw):
    r = min(r, (x1 - x0) / 2, (y1 - y0) / 2)
    pts = [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1,
           x1 - r, y1, x0 + r, y1, x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]
    return c.create_polygon(pts, smooth=True, **kw)
