# Loop ber-3 ronde 2 — disposisi review gpt-6.1-sol (2026-11-16)

Sumber: `~/workspace/tools/ask-kawan/runs/kawan-20261116-051651-summary.json`
(gpt-6-astra: 503 lagi — utang konsultasi, pendapatnya TIDAK dikarang.)

## Diterapkan di v0.3
1. **Integritas sesi** (sol §1): parse_session kini menandai *duplicate
   test record* dan *malformed FDTEST record* sebagai `problems`;
   PASS diveto bila problems non-kosong. Menutup celah yang tidak
   tertangkap cross-check DONE: PASS ganda bisa menutupi record hilang
   sementara hitungan tetap cocok.
2. **Pemisahan deadline boot vs tes** (sol §1): watchdog silence hanya
   bersenjata sesudah `FDTEST START`; fase boot hanya diatur timeout
   keseluruhan — boot lambat tidak lagi bisa divonis hang.
3. **QEMU exit ≠ timeout** (sol §1): boot_once mengembalikan outcome
   `exited` bila QEMU mati sendiri (mis. guest reboot di `-no-reboot`).
4. **Timeline attempt + failure_summary** (sol §1 & §3, diferensiasi
   "failure diagnosis across boots"): report.json kini punya
   `attempts[]` (nomor, outcome, durasi), `problems[]`, dan
   `failure_summary` satu baris yang mengkorelasikan outcome attempt
   terakhir, jumlah restart watchdog, tes gagal, crash, dan mismatch
   DONE. Diverifikasi di demo fdcrash + fdwatch-hang.
5. **Framing budget timer** (sol §1): README menegaskan budget 60 ms =
   toleransi TCG, bukan bukti kualitas timing hardware (fdtest.c sudah
   berkomentar serupa sejak v0.2).

## Sudah ada di v0.2 (tidak diulang)
- DONE tally cross-check + veto crash atas PASS, grace window 1,5 s,
  cleanup QEMU yatim, parse sesi terakhir sesudah restart, log konsol
  per-attempt tersimpan, `-cpu max` didokumentasikan sebagai syarat
  kompatibilitas emulator untuk startup path ini (bukan syarat umum
  QNX), static linking sebagai pilihan sadar untuk image minimal.

## Ditolak / ditunda + alasan
- **slog2 capture** (sol §2, disebut "low-effort"): DITUNDA ke roadmap.
  Eksperimen langsung di image minimal kita: `slogger2` tidak pernah
  memunculkan `/dev/slog2`, `slog2info` kosong. Bukan low-effort di
  image ini; README sudah mencantumkannya sebagai roadmap.
- **Core analysis / HAM / adaptive partitioning** (sol §2): di luar
  scope v0.3 — setup + failure mode tambahan tanpa nilai demo
  sebanding.
- **Demo moment** (sol §4): diadopsi untuk fase video (hang → restart
  → report yang menjelaskan), bukan perubahan kode; demo fdwatch-hang
  sudah membuktikan alurnya.
