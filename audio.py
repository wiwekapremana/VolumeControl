"""Akses volume sistem. Windows memakai pycaw; OS lain memakai dummy (untuk uji coba)."""

from __future__ import annotations

import sys


class _DummyVolume:
    def __init__(self) -> None:
        self._level = 0.5

    def get(self) -> float:
        return self._level

    def set(self, level: float) -> None:
        self._level = level


class _WindowsVolume:
    def __init__(self) -> None:
        from ctypes import POINTER, cast

        from comtypes import CLSCTX_ALL
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

        speakers = AudioUtilities.GetSpeakers()
        endpoint = getattr(speakers, "EndpointVolume", None)  # pycaw versi baru
        if endpoint is None:  # pycaw versi lama
            interface = speakers.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            endpoint = cast(interface, POINTER(IAudioEndpointVolume))
        self._ep = endpoint

    def get(self) -> float:
        return float(self._ep.GetMasterVolumeLevelScalar())

    def set(self, level: float) -> None:
        # Skala "scalar" mengikuti persepsi telinga (sama seperti slider Windows),
        # jauh lebih natural daripada skala dB yang dipakai versi lama.
        self._ep.SetMasterVolumeLevelScalar(min(max(level, 0.0), 1.0), None)


def get_volume_backend():
    if sys.platform == "win32":
        return _WindowsVolume()
    print("[info] Bukan Windows: volume sistem tidak diubah (mode simulasi).")
    return _DummyVolume()
