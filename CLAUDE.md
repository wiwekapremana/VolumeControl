# VolumeControl: konteks project untuk Claude

## Tentang pemilik & cara kerja
- Selalu berkomunikasi dalam **Bahasa Indonesia**.
- Sebelum mengerjakan fitur besar, jelaskan dulu pemahaman/rancangan agar pemilik bisa
  memverifikasi, kecuali pemilik sudah bilang "lanjutkan".
- **Claude tidak boleh tampil sebagai contributor**: commit atas nama
  `wiwekapremana <74669782+wiwekapremana@users.noreply.github.com>`, tanpa
  `Co-Authored-By` / trailer Claude, dan tanpa footer "Generated with Claude Code" di PR.
  (Commit akan berlabel "Unverified" di GitHub; pemilik sudah menerima itu.)
- Pemilik memakai **Windows** (laptop). Aplikasi harus ringan dan tidak mengganggu pekerjaan lain.

## Apa aplikasinya
Kontrol volume, media, dan mouse Windows dengan gesture tangan lewat webcam.
Tanpa jendela video; sebagai gantinya ada indikator kecil melayang di bawah layar.
Satu tangan, **tanpa ganti mode**: setiap fungsi punya bentuk tangan sendiri.

| Gerakan | Hasil |
|---|---|
| Angkat kedua tangan (pergelangan di atas bahu) ~1 dtk | AKTIF ⇄ TERKUNCI |
| Tangan hilang ~3 dtk | otomatis TERKUNCI |
| 👌 `pinch`: ujung ibu jari + telunjuk menempel, geser naik/turun | volume (relatif, seperti slider) |
| ✊ `fist` ~0.4 dtk | mute / unmute (selama mute, volume dikunci) |
| 🖐 `open` geser kanan/kiri | lagu berikutnya / sebelumnya |
| 🖐 `open` diam ~0.7 dtk | play / pause |
| 👆 `point` (pistol: telunjuk lurus, ibu jari tegak) | gerakkan pointer |
| 👆 ibu jari turun lalu naik | klik kiri (2x cepat = double click) |
| 👆 ibu jari turun + gerak | drag |
| 👆 ibu jari turun + diam ~0.8 dtk | klik kanan |
| ✌ `two` geser naik/turun dari titik awal | scroll gaya joystick |

## Keputusan desain (jangan diubah tanpa alasan)
- **Volume dulu memakai jarak cubitan**; diganti "tempel lalu geser" karena cubitan
  terbuka lebar bentuknya sama dengan pose pistol (bentrok dengan pointer).
- Klik memakai **ibu jari ke sisi jari tengah**, bukan cubit telunjuk, agar telunjuk
  (pointer) tidak bergerak saat klik. Pointer dibekukan ke posisi ~0.1 dtk sebelum
  ibu jari turun. Klik baru bisa setelah ibu jari terlihat tegak (anti klik tak sengaja).
- Pose harus konsisten `pose_frames` (3) frame sebelum dianggap berganti.
- Pointer: area kamera `region` (0.25–0.75 × 0.20–0.65) dipetakan ke layar, filter One Euro.
- Swipe: riwayat posisi direset saat pose/tangan berganti (pernah jadi bug arah terbalik).

## Struktur
- `gesture.py`: logika murni (State, HandPose, Action, Config, Controller, ekstraksi
  fitur landmark). Semua ambang ada di `Config` dan konstanta `EXTENDED_DEG`,
  `DOWN_DEG`, `CURLED_DEG`, `PINCH_TOUCH`.
- `main.py`: thread kamera (MediaPipe Pose + Hands versi ringan) dan loop tkinter.
- `overlay.py`: indikator always-on-top, klik-tembus, skala DPI, digambar ulang hanya bila berubah.
- `audio.py`: volume/mute via pycaw (skala scalar), tombol media via `keybd_event`.
- `mouse.py`: pointer/klik/scroll via WinAPI, DPI-aware.
- `tests/test_gesture.py`: 23 unit test (`pip install pytest && pytest`).

## Performa
- TERKUNCI: hanya Pose lite ~6 fps → sekitar 13% dari 1 core (≈3% laptop 4 core),
  diukur dengan kamera palsu. Versi lama (Holistic, selalu 30 fps) ~64% dari 1 core.
- AKTIF: Hands lite tiap frame, Pose tiap 4 frame. Belum terukur dengan tangan sungguhan.
- Prioritas proses di bawah normal; `--fps 20` untuk laptop lemah.

## Status
- Branch `claude/gesture-volume-control-h9fiuh`, PR #1 ke `main`.
- **Belum pernah diuji dengan webcam & tangan sungguhan.** Ambang pose dan nilai
  `thumb` (`press_on` 0.40 / `press_off` 0.55) masih perkiraan; setel memakai
  `python main.py --debug` (menampilkan `pose` dan `thumb`).
- Butuh Python 3.9–3.12 (mediapipe 0.10.14 masih punya `mp.solutions`).

## Ide fitur berikutnya (belum dikerjakan)
Ikon system tray, auto-start saat Windows nyala, kalibrasi gesture, suara "klik"
saat aktif/kunci, volume per aplikasi, kecerahan layar, file pengaturan (config).
