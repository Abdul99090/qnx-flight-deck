# Review request — QNX Flight-Deck v1 (hackathon entry, Developer Tooling category)

You are reviewing a hackathon project for the QNX Global Developer Hackathon
(QNX 8.0, category: Developer Tooling & Host Tools; judging: Technological
Implementation, Design, Potential Impact, Innovation). Two similar projects
exist (a one-command build/boot lab, and an MCP server for QNX agents).
Our differentiation: test orchestration + console/crash harvesting +
watchdog verdicts.

## What Flight-Deck v1 does (already working end-to-end)

Host harness (Python 3, stdlib only) pipeline:
build (qcc) -> image (mkifs) -> boot (QEMU x86_64, TCG) -> harvest serial
console -> structured report.json + PASS/FAIL verdict.

An on-target C agent prints machine-readable lines `FDTEST <name> PASS|FAIL
k=v...` and `FDTEST DONE pass=n fail=n`. The harness parses them.

Watchdog mode: if the target produced console output and then goes silent
for N seconds, the harness kills QEMU, restarts it (up to max-restarts),
and records each restart as an event in report.json. Final verdict FAIL if
no boot attempt reaches FDTEST DONE.

Verified runs:
- Self-test agent: ipc PASS (native QNX MsgSend/MsgReceive round-trip),
  timer PASS (50 ms nanosleep drift measured), sched PASS (SCHED_FIFO
  wake order 2,1,0) -> verdict PASS.
- Watchdog demo target in "hang" build (spins forever after 3 heartbeats):
  watchdog restarted it twice, verdict FAIL, 2 events in report.

## Design choices to critique

1. Serial console as the ONLY channel (no network stack in the image;
   QEMU `-nic none`). Tests report via printf to the console.
2. Static linking for target binaries (dynamic loading from the minimal
   mkifs image was unreliable in our early tests).
3. The timer test uses a 60 ms drift budget because the host is QEMU/TCG
   emulation; on hardware QNX sleeps are far tighter.
4. report.json is the single source of truth; the console summary is a
   rendering of it.
5. Boot uses QEMU `-kernel` with a mkifs multiboot image and `-cpu max`
   (QNX 8 startup requires the XSAVE CPUID feature).

## Questions

1. Correctness: what failure modes of this harness design would make a
   PASS verdict untrustworthy? What could make it flaky in CI?
2. QNX-specific: are we missing idiomatic QNX 8 mechanisms that judges
   would expect (slog2 logging, dumper/core analysis, pidin, ham —
   high-availability manager, adaptive partitioning)? Which ONE addition
   gives the most "Best use of QNX-specific Technologies" value for the
   least work?
3. Differentiation: is test-orchestration + watchdog + JSON verdict
   enough against a build/boot lab and an MCP server? What feature
   would make this clearly a different product?
4. What is the single most impressive demo moment we should make sure
   the <3-minute video shows?

Answer concisely, prioritized, no flattery. Flag anything factually
wrong about QNX in the description above.
