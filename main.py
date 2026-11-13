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
import os
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


LOCKED_FPS = 6        # saat terkunci: cukup cek "kedua tangan diangkat"
POSE_EVERY = 4        # saat aktif: pose (badan) cukup dicek tiap 4 frame


def vision_loop(args, frames: "queue.Queue[Frame]", stop: threading.Event,
                active: threading.Event) -> None:
    """Thread kamera: baca frame, deteksi pose + tangan, kirim fitur ke main thread.

    Hemat CPU:
      - TERKUNCI: hanya model pose versi ringan, ~6 frame/detik.
      - AKTIF: model tangan versi ringan tiap frame, pose tiap beberapa frame.
      - Tidak memakai model wajah sama sekali (Holistic dulu ikut menghitung wajah).
    """
    cap = open_camera(args.camera)
    mp_pose, mp_hands = mp.solutions.pose, mp.solutions.hands
    draw = mp.solutions.drawing_utils
    raised, n = False, 0
    pose_lms = None

    with mp_pose.Pose(model_complexity=args.model, smooth_landmarks=True,
                      min_detection_confidence=0.6, min_tracking_confidence=0.6) as pose, \
         mp_hands.Hands(max_num_hands=1, model_complexity=0,
                        min_detection_confidence=0.6, min_tracking_confidence=0.6) as hands:
        while not stop.is_set():
            is_active = active.is_set()
            t_start = time.monotonic()
            ok, img = cap.read()
            if not ok:
                time.sleep(0.05)
                continue
            img = cv2.flip(img, 1)
            rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            rgb.flags.writeable = False

            n += 1
            if not is_active or n % POSE_EVERY == 0:
                res_pose = pose.process(rgb)
                pose_lms = res_pose.pose_landmarks
                raised = both_hands_raised(pose_lms.landmark if pose_lms else None)

            hand_lms, hand_id = None, None
            if is_active:
                res_hands = hands.process(rgb)
                if res_hands.multi_hand_landmarks:
                    hand_lms = res_hands.multi_hand_landmarks[0]
                    label = res_hands.multi_handedness[0].classification[0].label
                    hand_id = label.lower()

            frame = extract(hand_lms.landmark if hand_lms else None, hand_id,
                            time.monotonic(), raised)
            try:
                frames.put_nowait(frame)
            except queue.Full:
                pass

            if args.debug:
                if pose_lms:
                    draw.draw_landmarks(img, pose_lms, mp_pose.POSE_CONNECTIONS)
                if hand_lms:
                    draw.draw_landmarks(img, hand_lms, mp_hands.HAND_CONNECTIONS)
                pose_name = frame.hand_pose.value if frame.hand_pose else "-"
                thumb = f"{frame.thumb_press:.2f}" if frame.thumb_press is not None else "-"
                txt = f"raised={raised}  pose={pose_name}  thumb={thumb}"
                cv2.putText(img, txt, (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                            (0, 255, 0), 2)
                cv2.imshow("Gesture Volume Control (debug)", img)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    stop.set()

            if is_active and args.fps < 30:
                wait = 1.0 / args.fps - (time.monotonic() - t_start)
                if wait > 0:
                    time.sleep(wait)
                    cap.grab()
            if not is_active:
                # Tidur sisa waktu; buang frame lama di buffer kamera agar tidak telat
                wait = 1.0 / LOCKED_FPS - (time.monotonic() - t_start)
                if wait > 0:
                    active.wait(wait)  # langsung bangun saat AKTIF
                cap.grab()

    cap.release()
    if args.debug:
        cv2.destroyAllWindows()


def lower_priority() -> None:
    """Prioritas proses di bawah normal: aplikasi lain selalu didahulukan."""
    cv2.setNumThreads(1)
    if sys.platform == "win32":
        import ctypes
        BELOW_NORMAL_PRIORITY_CLASS = 0x4000
        k32 = ctypes.windll.kernel32
        k32.SetPriorityClass(k32.GetCurrentProcess(), BELOW_NORMAL_PRIORITY_CLASS)
    else:
        try:
            os.nice(5)
        except OSError:
            pass


def main() -> None:
    p = argparse.ArgumentParser(description="Atur volume, media & mouse dengan gesture.")
    p.add_argument("--debug", action="store_true", help="tampilkan jendela video")
    p.add_argument("--camera", type=int, default=0, help="indeks kamera (default 0)")
    p.add_argument("--model", type=int, default=0, choices=(0, 1, 2),
                   help="kompleksitas model pose: 0 ringan (default), 2 akurat")
    p.add_argument("--hold", type=float, default=1.0,
                   help="lama angkat kedua tangan untuk aktif/kunci (detik)")
    p.add_argument("--timeout", type=float, default=3.0,
                   help="kunci otomatis bila tangan hilang selama ini (detik)")
    p.add_argument("--fps", type=int, default=30,
                   help="batas frame/detik saat aktif (mis. 20 untuk laptop lemah)")
    p.add_argument("--no-mouse", action="store_true", help="matikan kontrol pointer")
    args = p.parse_args()

    enable_dpi_awareness()
    lower_priority()
    volume = get_volume_backend()
    mouse = Mouse()
    ctrl = Controller(Config(hold_time=args.hold, idle_timeout=args.timeout))
    ctrl.sync_volume(volume.get())
    ctrl.muted = volume.is_muted()

    frames: "queue.Queue[Frame]" = queue.Queue(maxsize=8)
    stop = threading.Event()
    active = threading.Event()   # memberi tahu thread kamera kapan perlu kerja penuh
    worker = threading.Thread(target=vision_loop, args=(args, frames, stop, active),
                              daemon=True)
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
            if out.state is State.ACTIVE:
                active.set()
            else:
                active.clear()

        overlay.render(last["state"], ctrl.display_volume, last["progress"], now,
                       just_locked=just_locked, muted=ctrl.muted, action=action,
                       pose=last["pose"])
        # ~60 fps saat indikator tampil; jarang-jarang saat tersembunyi (hemat CPU)
        root.after(16 if overlay.busy else 100, tick)

    root.after(16, tick)
    root.mainloop()
    stop.set()
    worker.join(timeout=2)


if __name__ == "__main__":
    main()
