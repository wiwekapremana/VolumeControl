# VolumeControl

Atur volume Windows dengan gesture tangan lewat webcam, tanpa jendela video.
Sebagai gantinya ada indikator volume kecil yang melayang di bagian bawah layar.

## Cara pakai

| Gerakan | Hasil |
|---|---|
| Angkat **kedua tangan** di atas bahu, tahan ~1 detik | Mode **AKTIF** (cincin kuning terisi, lalu hijau) |
| Turunkan satu tangan, rapatkan/renggangkan **ibu jari & telunjuk** | Volume turun/naik dengan halus |
| **Kepalkan** tangan ~0.4 detik | Mute / unmute |
| **Telapak terbuka**, geser cepat ke kanan / kiri | Lagu berikutnya / sebelumnya |
| **Telapak terbuka**, diam ~0.7 detik | Play / Pause |
| Angkat kedua tangan lagi ~1 detik | **TERKUNCI** |
| Tangan tidak terlihat ~3 detik | Otomatis **TERKUNCI** |

Saat terkunci, gerakan tangan apa pun tidak berpengaruh. Kontrol media memakai
tombol media Windows, jadi bekerja di Spotify, YouTube (browser), VLC, dan lainnya.
Selama mute, cubitan tidak mengubah volume; kepalkan tangan lagi untuk unmute.

Tips: jalankan `python main.py --debug` untuk melihat pose yang terbaca
(`open` / `fist` / `other`) bila gesture terasa kurang peka.

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
```

Keluar: `Ctrl+C` di terminal, atau tombol `q` di jendela `--debug`.

## Struktur

- `main.py`: kamera + MediaPipe Holistic (pose + tangan) di thread terpisah, indikator di thread utama
- `gesture.py`: logika aktivasi, kunci, dan penghalusan volume (bisa diuji tanpa kamera)
- `overlay.py`: indikator volume (always-on-top, klik tembus)
- `audio.py`: volume & mute Windows via pycaw, tombol media via WinAPI
- `tests/`: unit test logika gesture (`pip install pytest && pytest`)
