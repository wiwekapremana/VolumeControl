"""Gesture Volume Control.

Cara pakai:
  1. Jalankan:  python main.py           (tanpa jendela video)
                python main.py --debug   (tampilkan video + landmark untuk uji coba)
  2. Angkat KEDUA tangan di atas bahu selama ~1 detik  -> AKTIF.
  3. Turunkan satu tangan, lalu (tanpa ganti mode):
       👌 ujung ibu jari + telunjuk menempel, geser naik/turun -> volume
       ✊ kepalan ~0.4 detik                                    -> mute / unmute
       🖐 telapak terbuka, geser kiri/kanan                    -> lagu sebelumnya / berikutnya
       🖐 telapak terbuka, diam ~0.7 detik                     -> play / pause
       👆 bentuk pistol (telunjuk lurus, ibu jari tegak)        -> gerakkan pointer
            ibu jari turun lalu naik                           -> klik
            ibu jari turun, tahan sambil gerak                 -> drag
            ibu jari turun, tahan diam ~0.8 detik              -> klik kanan
       ✌ dua jari, geser naik/turun dari titik awal           -> scroll
  4. Angkat kedua tangan lagi ~1 detik, atau tinggalkan kamera ~3 detik -> TERKUNCI.

Keluar: Ctrl+C di terminal (atau tombol 'q' di jendela debug).
"""

from __future__ import annotations

import argparse
import queue
import signal
import sys
import threading
import time
import tkinter as tk

import cv2
import mediapipe as mp

from audio import get_volume_backend, send_media_key
from gesture import Action, Config, Controller, Frame, State, both_hands_raised, extract
from mouse import Mouse, enable_dpi_awareness
from overlay import Overlay

MEDIA = {Action.PLAY_PAUSE, Action.NEXT, Action.PREV}


def open_camera(index: int) -> cv2.VideoCapture:
    backend = cv2.CAP_DSHOW if sys.platform == "win32" else cv2.CAP_ANY
    cap = cv2.VideoCapture(index, backend)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    if not cap.isOpened():
        raise SystemExit(f"Kamera {index} tidak bisa dibuka.")
    return cap


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

            frame = extract(hand, hand_id, time.monotonic(), both_hands_raised(pose))
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
                thumb = f"{frame.thumb_press:.2f}" if frame.thumb_press is not None else "-"
                txt = f"raised={frame.both_hands_raised}  pose={pose_name}  thumb={thumb}"
                cv2.putText(img, txt, (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                            (0, 255, 0), 2)
                cv2.imshow("Gesture Volume Control (debug)", img)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    stop.set()

    cap.release()
    if args.debug:
        cv2.destroyAllWindows()


def main() -> None:
    p = argparse.ArgumentParser(description="Atur volume, media & mouse dengan gesture.")
    p.add_argument("--debug", action="store_true", help="tampilkan jendela video")
    p.add_argument("--camera", type=int, default=0, help="indeks kamera (default 0)")
    p.add_argument("--model", type=int, default=1, choices=(0, 1, 2),
                   help="kompleksitas model pose: 0 cepat, 2 akurat (default 1)")
    p.add_argument("--hold", type=float, default=1.0,
                   help="lama angkat kedua tangan untuk aktif/kunci (detik)")
    p.add_argument("--timeout", type=float, default=3.0,
                   help="kunci otomatis bila tangan hilang selama ini (detik)")
    p.add_argument("--no-mouse", action="store_true", help="matikan kontrol pointer")
    args = p.parse_args()

    enable_dpi_awareness()
    volume = get_volume_backend()
    mouse = Mouse()
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

    last = {"state": ctrl.state, "progress": 0.0, "pose": None}
    sync_at = [0.0]
    print("Siap. Angkat kedua tangan ~1 detik untuk mengaktifkan. Ctrl+C untuk keluar.")

    def handle_action(a: Action) -> None:
        if a in (Action.MUTE, Action.UNMUTE):
            volume.set_mute(a is Action.MUTE)
        elif a in MEDIA:
            send_media_key(a.value)
        elif args.no_mouse:
            return
        elif a is Action.CLICK:
            mouse.click()
        elif a is Action.RIGHT_CLICK:
            mouse.right_click()
        elif a is Action.DRAG_START:
            mouse.left_down()
        elif a is Action.DRAG_END:
            mouse.left_up()

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
            if ctrl.state is State.LOCKED:
                ctrl.sync_volume(volume.get())
            out = ctrl.update(f)
            if out.volume_changed:
                volume.set(out.volume)
            if out.pointer is not None and not args.no_mouse:
                mouse.move(*out.pointer)   # pindah dulu, baru klik di posisi itu
            if out.scroll and not args.no_mouse:
                mouse.scroll(out.scroll)
            if out.action is not None:
                handle_action(out.action)
                action = out.action
                if out.action not in (Action.CLICK, Action.DRAG_START, Action.DRAG_END):
                    print(f"aksi: {out.action.value}")
            if out.toggled:
                print("AKTIF" if out.state is State.ACTIVE else "TERKUNCI")
                just_locked |= out.state is State.LOCKED
            last.update(state=out.state, progress=out.activation_progress, pose=out.pose)

        overlay.render(last["state"], ctrl.display_volume, last["progress"], now,
                       just_locked=just_locked, muted=ctrl.muted, action=action,
                       pose=last["pose"])
        root.after(16, tick)  # ~60 fps untuk animasi halus

    root.after(16, tick)
    root.mainloop()
    stop.set()
    worker.join(timeout=2)


if __name__ == "__main__":
    main()
