"""Akses volume sistem. Windows memakai pycaw; OS lain memakai dummy (untuk uji coba)."""

from __future__ import annotations

import sys


class _DummyVolume:
    def __init__(self) -> None:
        self._level = 0.5
        self._muted = False

    def get(self) -> float:
        return self._level

    def set(self, level: float) -> None:
        self._level = level

    def is_muted(self) -> bool:
        return self._muted

    def set_mute(self, muted: bool) -> None:
        self._muted = muted


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

    def is_muted(self) -> bool:
        return bool(self._ep.GetMute())

    def set_mute(self, muted: bool) -> None:
        self._ep.SetMute(1 if muted else 0, None)


def get_volume_backend():
    if sys.platform == "win32":
        return _WindowsVolume()
    print("[info] Bukan Windows: volume sistem tidak diubah (mode simulasi).")
    return _DummyVolume()


# Tombol media virtual Windows (sama seperti tombol media di keyboard),
# jadi bekerja di Spotify, YouTube di browser, VLC, dll.
_MEDIA_KEYS = {"play_pause": 0xB3, "next": 0xB0, "prev": 0xB1}


def send_media_key(name: str) -> None:
    vk = _MEDIA_KEYS[name]
    if sys.platform != "win32":
        print(f"[simulasi] tombol media: {name}")
        return
    import ctypes
    KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP = 0x1, 0x2
    user32 = ctypes.windll.user32
    user32.keybd_event(vk, 0, KEYEVENTF_EXTENDEDKEY, 0)
    user32.keybd_event(vk, 0, KEYEVENTF_EXTENDEDKEY | KEYEVENTF_KEYUP, 0)
