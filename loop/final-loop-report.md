# Loop FINAL ber-4 — Flight-Deck v0.3 (2026-11-16)

Persiapan submisi QNX Devpost (deadline 16 Des 2026 02:00 WIB).
Sesi ini TIDAK submit, TIDAK flip repo publik, TIDAK upload video.
Prompt review: `loop/final-review-prompt.md` (teknis murni, nol data pribadi).

## 1. Hasil tes (diverifikasi sesi ini, bukan dari ingatan)

| Tes | Sebelum fix | Sesudah fix |
|---|---|---|
| Unit host `tests/test_flightdeck.py` | **9/9 PASS** | **9/9 PASS** |
| Regresi fdtest end-to-end (QEMU nyata) | **PASS** — build 4,3 dtk, image 10,6 dtk, boot 13,7 dtk; ipc PASS rtt_us=1080, timer PASS drift 27,8 ms, sched PASS 2,1,0; exit 0 (`runs/fdtest-20261116-081903/`) | **PASS** — build 3,0 dtk, image 13,3 dtk, boot 13,5 dtk; ipc PASS rtt_us=1265, timer PASS drift 14,5 ms, sched PASS 2,1,0 (`runs/fdtest-20261116-082459/`) |

## 2. Secret sweep — repo BERSIH ✅

Syarat publikasi (aturan Muhammad 15 Nov 04:52) TERPENUHI:

- Pola kredensial (password/passwd/api-key/secret/seed/mnemonic/private-key/
  token formats `AKIA…`/`ghp_…`/`sk-…`/`xox…`/`AIza…`) digrep di:
  (a) seluruh working tree, (b) `git grep` di SEMUA commit (`git rev-list --all`,
  3 commit) → **0 temuan** di file teks mana pun.
- Pola kunci lisensi QNX (5 grup × 4) + pola serial (6-8 digit) di semua
  commit → **0 temuan**. Tidak ada email, username akun, atau alamat pribadi
  di repo.
- Satu-satunya hit PII: `LICENSE:3` — "Copyright (c) 2026 Muhammad Abdul
  Faiz" = nama penulis sendiri di lisensi MIT. Disengaja dan normal untuk
  repo submisi; BUKAN penghalang publikasi.
- Hit biner: kata `passwd` di dalam image `.ifs` = string library sistem
  QNX di boot image, bukan kredensial. Lagipula `*.ifs` + `runs/` sudah
  gitignore — **0 file `.ifs`/`runs/` yang ter-track**.
- Hygiene yang dibersihkan sesi ini: `target/fdtest.build` +
  `target/fdcrash2.build` adalah artefak generate yang ter-commit dan memuat
  path absolut lokal (`/home/hatch/…`) → di-untrack + `target/*.build`
  masuk `.gitignore` (file `.build.tmpl` tetap ter-track; harness tidak
  membaca `.build` yang ter-track — terbukti `git status` bersih sesudah
  regresi jalan).

## 3. Loop ber-4 — pendapat + disposisi

Ketiga kawan MENJAWAB sesi ini. **Utang gpt-6-astra dari ronde 1–2 LUNAS**
(relay pulih; artefak `loop/kawan-final/kawan-20261116-152042-summary.json`:
sol OK 943 token out, astra OK 828 token out, attempt pertama semua).
Gemini: `gemini-3.5-flash` (`loop/gemini-final.txt`).

### Konsensus 3/3 — klaim README keliru → DIPERBAIKI (commit fc0d6b7)
1. **"nothing lost, nothing spoofed" — SALAH.** Tally DONE yang cocok cuma
   membuktikan integritas hitungan, bukan keaslian: proses apa pun yang bisa
   menulis ke konsol bisa mencetak record FDTEST palsu. → Kata "spoofed"
   dibuang dari README + komentar kode; rumusan baru: record yang hilang/
   rusak di konsol mematahkan kecocokan tally dan menggagalkan run.
2. **"three orders of magnitude tighter" — TAK TERDUKUNG.** 1000× dari
   27,8 ms = ±28 µs, padahal tick kernel default QNX = 1 ms (Gemini).
   → Klaim rasio dibuang; rumusan baru dibatasi tick 1 ms + beban, dan
   README kini menegaskan tidak mempublikasikan rasio hardware yang belum
   diukur.
3. **"works on any QNX target with a UART" — BERLEBIHAN.** Implementasi
   rilis ini x86_64/QEMU; board fisik butuh image BSP + jalur reset —
   watchdog host me-restart VM, tidak bisa power-cycle board lewat serial
   pasif (sol + astra + Gemini). → Dikualifikasi di README Notes.
4. **"crash harvesting"** berpotensi dibaca sebagai core-file/stack-trace.
   → README kini menggloss crash record sebagai bukti terminasi (exit code /
   signal / timeout); core-file tetap roadmap (sudah tertulis begitu).
5. **Static linking** → dibingkai eksplisit sebagai pilihan sadar untuk
   target demo + di-scope ke binary demo (Gemini: SDP tidak menganjurkan
   static libc sebagai praktik baku — README tidak lagi mengesankan itu).

### Temuan desain — hasil bedah kode sesi ini
- **Suite kosong PASS? TIDAK.** Sol + astra mengangkat skenario
  `DONE pass=0 fail=0` → terbukti SUDAH diveto kode: syarat verdict memuat
  `passed > 0` (flightdeck.py). Direproduksi empiris sesi ini: log sintetis
  suite-kosong → ekspresi verdict = FAIL. Sekalian README kini menyebut
  syarat "at least one check ran and passed" agar dok = kode.
- **Suite yang menghilangkan satu tes** (mis. cuma `ipc` + DONE pass=1):
  tally cocok menurut konstruksi — celah inventaris tes yang DIHARAPKAN
  itu NYATA. Perbaikannya = fitur baru (opsi inventaris wajib) →
  REKOMENDASI, tidak dibangun sesi ini (lihat §5).
- **Bleed antar-attempt (Gemini)** → SUDAH ditangani v0.2: parser memakai
  sesi terakhir; bukti = unit test
  `test_parse_uses_last_session_after_watchdog_restart` (PASS sesi ini).
- **Semantik recovery watchdog (sol + astra)** → perilaku aktual: attempt
  bersih sesudah restart = PASS, restart tetap tercatat. Itu desain yang
  disengaja (watchdog = resilience), kini DIDOKUMENTASIKAN eksplisit di
  README §7 agar juri tidak menebak.
- **DONE vs penyelesaian supervisor (sol + astra)** → termitigasi sebagian:
  grace 1,5 dtk sesudah DONE + return dini di `FDSCRIPT END`; record
  penyelesaian supervisor eksplisit = REKOMENDASI (§5), bukan fix sesi ini.
- **Wake order sched (sol + astra)** → fdtest.c memasang prioritas
  SCHED_FIFO eksplisit; README melaporkan HASIL TERUKUR demo, bukan janji
  jaminan — tidak ada koreksi yang diperlukan.

## 4. Perubahan yang diterapkan — commit `fc0d6b7`

- README: 6 koreksi/kualifikasi klaim di §2–§3 di atas + syarat verdict
  "at least one check ran" + semantik recovery watchdog + gloss crash
  record + scope static linking.
- `flightdeck/flightdeck.py`: komentar verdict diselaraskan ("spoofed"
  dibuang). NOL perubahan perilaku; versi tetap 0.3.0.
- `.gitignore` + untrack 2 file `.build` (lihat §2).
- Artefak loop: prompt final, jawaban Gemini, jawaban sol + astra.
- Verifikasi sesudah perubahan: unit 9/9 PASS + regresi fdtest PASS (§1).

## 5. REKOMENDASI (tidak diterapkan — keputusan sesi submisi)

1. **Inventaris tes wajib** (`--expect-tests ipc,timer,sched`): PASS hanya
   bila himpunan tes parsed == inventaris. Menutup celah "tes hilang diam-
   diam" (sol + astra, prioritas fitur #1 mereka). ±Sedang.
2. **Record penyelesaian supervisor eksplisit**: PASS menunggu fdsup
   menyatakan semua child sudah di-reap, menggantikan ketergantungan pada
   grace window saja. ±Sedang.
3. **Metadata syspage di report.json** (Gemini): nama sysname/release/CPU
   dari system page QNX dicetak agent saat start → nilai "Best use of
   QNX-specific Technologies" dengan usaha kecil. ±Kecil–sedang.
4. **Cuplikan report.json di teks submisi Devpost** (sol): excerpt PASS /
   hang / crash yang menunjukkan `attempts[]`, bukti terminasi, dan
   `failure_summary`. ±Kecil, dikerjakan pas nulis form submisi.

## 6. Checklist sisa menuju submit (deadline 16 Des 2026 02:00 WIB)

- [x] Loop final ber-4 tuntas (Gemini + sol + astra; utang astra lunas)
- [x] Secret sweep bersih — repo LAYAK dipublikasikan
- [ ] Flip repo GitHub jadi publik (sesudah sweep ini — sudah boleh)
- [ ] Putuskan rekomendasi §5 mana yang dikerjakan sebelum submit
- [ ] Video demo < 3 menit (urutan usulan Gemini ronde 1: run bersih →
      hang + watchdog restart → inspeksi report.json FAIL → pitch)
- [ ] Isi form submisi Devpost (kategori Developer Tooling & Host Tools;
      sebut diferensiasi: test orchestration + fault diagnostics +
      watchdog verdicts)
- [ ] Submit sebelum 16 Des 2026 02:00 WIB
