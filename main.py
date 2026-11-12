"""Gesture Volume Control.

Cara pakai:
  1. Jalankan:  python main.py           (tanpa jendela video)
                python main.py --debug   (tampilkan video + landmark untuk uji coba)
  2. Angkat KEDUA tangan di atas bahu selama ~1 detik  -> mode AKTIF.
  3. Turunkan satu tangan, lalu:
       - cubit ibu jari & telunjuk          -> atur volume
       - kepalkan tangan ~0.4 detik         -> mute / unmute
       - telapak terbuka, geser kiri/kanan  -> lagu sebelumnya / berikutnya
       - telapak terbuka, diam ~0.7 detik   -> play / pause
  4. Angkat kedua tangan lagi ~1 detik, atau tinggalkan kamera ~3 detik -> TERKUNCI.

Keluar: Ctrl+C di terminal (atau tombol 'q' di jendela debug).
"""

from __future__ import annotations

import argparse
import queue
import signal
import threading
import time
import tkinter as tk

import cv2
import mediapipe as mp

from audio import get_volume_backend, send_media_key
from gesture import (Action, Config, Controller, Frame, State, both_hands_raised,
                     classify_hand, palm_center, pinch_ratio)
from overlay import Overlay


def open_camera(index: int) -> cv2.VideoCapture:
    backend = cv2.CAP_DSHOW if hasattr(cv2, "CAP_DSHOW") and _is_windows() else cv2.CAP_ANY
    cap = cv2.VideoCapture(index, backend)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    if not cap.isOpened():
        raise SystemExit(f"Kamera {index} tidak bisa dibuka.")
    return cap


def _is_windows() -> bool:
    import sys
    return sys.platform == "win32"


def vision_loop(args, frames: "queue.Queue[Frame]", stop: threading.Event) -> None:
    """Thread kamera: baca frame, deteksi pose + tangan, kirim fitur ke main thread."""
    cap = open_camera(args.camera)
    mp_holistic = mp.solutions.holistic
    draw = mp.solutions.drawing_utils

    with mp_holistic.Holistic(model_complexity=args.model, smooth_landmarks=True,
                              min_detection_confidence=0.6,
                              min_tracking_confidence=0.6) as holistic:
        while not stop.is_set():
            ok, img = cap.read()
            if not ok:
                time.sleep(0.05)
                continue
            img = cv2.flip(img, 1)
            rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            rgb.flags.writeable = False
            res = holistic.process(rgb)

            pose = res.pose_landmarks.landmark if res.pose_landmarks else None
            if res.right_hand_landmarks:
                hand, hand_id = res.right_hand_landmarks.landmark, "right"
            elif res.left_hand_landmarks:
                hand, hand_id = res.left_hand_landmarks.landmark, "left"
            else:
                hand, hand_id = None, None
            center = palm_center(hand)

            frame = Frame(timestamp=time.monotonic(),
                          both_hands_raised=both_hands_raised(pose),
                          pinch_ratio=pinch_ratio(hand),
                          hand_pose=classify_hand(hand),
                          hand_x=center[0] if center else None,
                          hand_y=center[1] if center else None,
                          hand_id=hand_id)
            try:
                frames.put_nowait(frame)
            except queue.Full:
                pass

            if args.debug:
                for lms, conn in ((res.pose_landmarks, mp_holistic.POSE_CONNECTIONS),
                                  (res.left_hand_landmarks, mp_holistic.HAND_CONNECTIONS),
                                  (res.right_hand_landmarks, mp_holistic.HAND_CONNECTIONS)):
                    if lms:
                        draw.draw_landmarks(img, lms, conn)
                pose_name = frame.hand_pose.value if frame.hand_pose else "-"
                ratio = f"{frame.pinch_ratio:.2f}" if frame.pinch_ratio is not None else "-"
                txt = f"raised={frame.both_hands_raised}  pose={pose_name}  pinch={ratio}"
                cv2.putText(img, txt, (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                            (0, 255, 0), 2)
                cv2.imshow("Gesture Volume Control (debug)", img)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    stop.set()

    cap.release()
    if args.debug:
        cv2.destroyAllWindows()


def main() -> None:
    p = argparse.ArgumentParser(description="Atur volume dengan gesture tangan.")
    p.add_argument("--debug", action="store_true", help="tampilkan jendela video")
    p.add_argument("--camera", type=int, default=0, help="indeks kamera (default 0)")
    p.add_argument("--model", type=int, default=1, choices=(0, 1, 2),
                   help="kompleksitas model pose: 0 cepat, 2 akurat (default 1)")
    p.add_argument("--hold", type=float, default=1.0,
                   help="lama angkat kedua tangan untuk aktif/kunci (detik)")
    p.add_argument("--timeout", type=float, default=3.0,
                   help="kunci otomatis bila tangan hilang selama ini (detik)")
    args = p.parse_args()

    volume = get_volume_backend()
    ctrl = Controller(Config(hold_time=args.hold, idle_timeout=args.timeout))
    ctrl.sync_volume(volume.get())
    ctrl.muted = volume.is_muted()

    frames: "queue.Queue[Frame]" = queue.Queue(maxsize=8)
    stop = threading.Event()
    worker = threading.Thread(target=vision_loop, args=(args, frames, stop), daemon=True)
    worker.start()

    root = tk.Tk()
    root.title("Gesture Volume Control")
    overlay = Overlay(root)
    signal.signal(signal.SIGINT, lambda *_: stop.set())

    last = {"state": ctrl.state, "progress": 0.0}
    sync_at = [0.0]
    print("Siap. Angkat kedua tangan ~1 detik untuk mengaktifkan. Ctrl+C untuk keluar.")

    def tick() -> None:
        if stop.is_set() or not worker.is_alive():
            root.destroy()
            return
        just_locked, action = False, None
        now = time.monotonic()
        if now - sync_at[0] > 0.25:  # ikuti perubahan dari keyboard/mixer Windows
            sync_at[0] = now
            ctrl.muted = volume.is_muted()
        while True:
            try:
                f = frames.get_nowait()
            except queue.Empty:
                break
            prev = ctrl.state
            if prev is State.LOCKED:
                ctrl.sync_volume(volume.get())  # ikuti perubahan dari keyboard/mixer
            out = ctrl.update(f)
            if out.volume_changed:
                volume.set(out.volume)
            if out.action in (Action.MUTE, Action.UNMUTE):
                volume.set_mute(out.action is Action.MUTE)
            elif out.action is not None:
                send_media_key(out.action.value)
            if out.action is not None:
                action = out.action
                print(f"aksi: {out.action.value}")
            if out.toggled:
                print("AKTIF" if out.state is State.ACTIVE else "TERKUNCI")
                just_locked |= out.state is State.LOCKED
            last["state"], last["progress"] = out.state, out.activation_progress

        overlay.render(last["state"], ctrl.display_volume, last["progress"],
                       time.monotonic(), just_locked=just_locked,
                       muted=ctrl.muted, action=action)
        root.after(16, tick)  # ~60 fps untuk animasi halus

    root.after(16, tick)
    root.mainloop()
    stop.set()
    worker.join(timeout=2)


if __name__ == "__main__":
    main()
