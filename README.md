# VolumeControl

Atur volume, media, dan mouse Windows dengan gesture tangan lewat webcam, tanpa jendela video.
Sebagai gantinya ada indikator volume kecil yang melayang di bagian bawah layar.

## Cara pakai

Tidak ada ganti mode: setiap fungsi punya bentuk tangan sendiri.

| Gerakan | Hasil |
|---|---|
| Angkat **kedua tangan** di atas bahu, tahan ~1 detik | **AKTIF** / **TERKUNCI** |
| 👌 Ujung **ibu jari + telunjuk menempel**, geser tangan naik / turun | Volume naik / turun (seperti slider) |
| ✊ **Kepalkan** tangan ~0.4 detik | Mute / unmute |
| 🖐 **Telapak terbuka**, geser cepat ke kanan / kiri | Lagu berikutnya / sebelumnya |
| 🖐 **Telapak terbuka**, diam ~0.7 detik | Play / Pause |
| 👆 **Bentuk pistol** (telunjuk lurus, ibu jari tegak) | Gerakkan pointer |
| 👆 lalu **ibu jari turun & naik** | Klik kiri (2x cepat = double click) |
| 👆 **ibu jari turun, tahan sambil gerak** | Drag |
| 👆 **ibu jari turun, tahan diam** ~0.8 detik | Klik kanan |
| ✌ **Dua jari**, geser naik / turun dari titik awal | Scroll (makin jauh makin cepat, kembali ke titik awal = berhenti) |
| Tangan tidak terlihat ~3 detik | Otomatis **TERKUNCI** |

Catatan:
- Saat terkunci, gerakan apa pun tidak berpengaruh.
- Pointer memakai area kecil di tengah kamera yang dipetakan ke seluruh layar,
  jadi tangan tidak perlu bergerak jauh. Saat ibu jari turun, pointer dibekukan
  agar klik tidak meleset.
- Kontrol media memakai tombol media Windows (Spotify, YouTube, VLC, dll).
- Selama mute, volume tidak bisa diubah; kepalkan tangan lagi untuk unmute.
- Jalankan `python main.py --debug` untuk melihat pose yang terbaca
  (`point`, `two`, `pinch`, `open`, `fist`, `other`) dan nilai `thumb`
  (besar = ibu jari tegak, kecil = ditekan) bila gesture terasa kurang peka.

## Instalasi (Windows, Python 3.9 – 3.12)

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

Opsi:

```
python main.py --debug        # tampilkan video + landmark (untuk uji coba)
python main.py --camera 1     # pakai kamera lain
python main.py --hold 0.7     # lama tahan aktivasi (detik)
python main.py --timeout 5    # kunci otomatis setelah tangan hilang (detik)
python main.py --model 0      # model lebih ringan bila PC lambat
python main.py --no-mouse     # matikan kontrol pointer/klik/scroll
```

Keluar: `Ctrl+C` di terminal, atau tombol `q` di jendela `--debug`.

## Struktur

- `main.py`: kamera + MediaPipe Holistic (pose + tangan) di thread terpisah, indikator di thread utama
- `gesture.py`: logika aktivasi, kunci, dan penghalusan volume (bisa diuji tanpa kamera)
- `overlay.py`: indikator volume (always-on-top, klik tembus)
- `audio.py`: volume & mute Windows via pycaw, tombol media via WinAPI
- `mouse.py`: pointer, klik, drag & scroll via WinAPI
- `tests/`: unit test logika gesture (`pip install pytest && pytest`)
