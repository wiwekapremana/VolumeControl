"""Kontrol pointer & klik mouse lewat WinAPI (tanpa library tambahan)."""

from __future__ import annotations

import sys

_IS_WIN = sys.platform == "win32"

LEFTDOWN, LEFTUP, RIGHTDOWN, RIGHTUP, WHEEL = 0x0002, 0x0004, 0x0008, 0x0010, 0x0800


def enable_dpi_awareness() -> None:
    """Agar koordinat pointer tepat di layar dengan scaling 125%/150%."""
    if not _IS_WIN:
        return
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


class Mouse:
    def __init__(self) -> None:
        self._last = None
        if _IS_WIN:
            import ctypes
            self._u = ctypes.windll.user32
            self.width = self._u.GetSystemMetrics(0)
            self.height = self._u.GetSystemMetrics(1)
        else:
            self._u = None
            self.width, self.height = 1920, 1080

    def move(self, nx: float, ny: float) -> None:
        """nx, ny: posisi 0..1 di layar utama."""
        x = round(nx * (self.width - 1))
        y = round(ny * (self.height - 1))
        if (x, y) == self._last:
            return
        self._last = (x, y)
        if self._u:
            self._u.SetCursorPos(x, y)

    def click(self) -> None:
        self._event(LEFTDOWN)
        self._event(LEFTUP)

    def right_click(self) -> None:
        self._event(RIGHTDOWN)
        self._event(RIGHTUP)

    def left_down(self) -> None:
        self._event(LEFTDOWN)

    def left_up(self) -> None:
        self._event(LEFTUP)

    def scroll(self, amount: int) -> None:
        """amount dalam unit wheel (120 = satu notch); positif = ke atas."""
        self._event(WHEEL, amount)

    def _event(self, flags: int, data: int = 0) -> None:
        if self._u:
            self._u.mouse_event(flags, 0, 0, data & 0xFFFFFFFF, 0)
        else:
            print(f"[simulasi] mouse flags={flags:#x} data={data}")
