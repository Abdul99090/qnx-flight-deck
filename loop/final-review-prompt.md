# FINAL review request — QNX Flight-Deck v0.3 (hackathon submission package)

You are doing the FINAL review of a hackathon project before submission to
the QNX Global Developer Hackathon (QNX 8.0, category: Developer Tooling &
Host Tools; judging criteria: Technological Implementation, Design,
Potential Impact, Innovation; there is also a "Best use of QNX-specific
Technologies" prize). Two similar projects exist (a one-command
build/boot lab, and an MCP server for QNX agents). Our differentiation:
test orchestration + fault diagnostics/crash harvesting + watchdog
verdicts.

This is the last review round. Two earlier rounds were already applied:
- Round 1 fixes (v0.2): on-target supervisor `fdsup` recording exactly how
  each test process died (exit code / signal / timeout) as crash records;
  DONE tally cross-check; 1.5 s grace window after DONE; orphan QEMU
  cleanup via atexit + signal handlers; all target programs use
  `setvbuf(stdout, NULL, _IONBF, 0)`.
- Round 2 fixes (v0.3): duplicate or malformed FDTEST records are flagged
  in `problems[]` and veto PASS; watchdog silence arms only after
  `FDTEST START` (boot deadline separated from test deadline); a boot
  attempt where QEMU dies on its own gets outcome `exited`, not
  `timeout`; report gained `attempts[]` timeline and a one-line
  `failure_summary`.

## What Flight-Deck v0.3 does (working end-to-end)

Host harness (Python 3, single file, stdlib only):
build (qcc -static) -> image (mkifs from a buildfile template) -> boot
(QEMU x86_64, `-cpu max`, serial console to file, `-nic none`) ->
supervise -> harvest -> verdict + report.json.

On-target: test programs run under `fdsup`, which waits on each child
with a deadline and prints exactly how it ended. The test agent prints
`FDTEST <name> PASS|FAIL key=value ...` lines and a final
`FDTEST DONE pass=n fail=n`.

VERDICT = PASS only if ALL hold: `FDTEST DONE` reached; every parsed
test passed; the target's own DONE tallies equal the parsed counts;
`problems[]` is empty (no duplicate/malformed records); zero crash
records. Anything else is FAIL with evidence + `failure_summary`.

Verified results (fresh, today):
- Host unit tests: 9/9 PASS (console/session parsing, veto logic,
  failure summary; no QNX/QEMU needed).
- Full end-to-end regression on QEMU: build OK 4.3 s, image OK 10.6 s,
  boot to tests 13.7 s; ipc PASS (native QNX MsgSend/MsgReceive
  round-trip, rtt_us=1080), timer PASS (50 ms nanosleep, drift 27.8 ms
  under TCG), sched PASS (SCHED_FIFO wake order 2,1,0); VERDICT PASS,
  exit code 0.
- Watchdog demo: healthy build PASS; hang build (wedges after 3
  heartbeats) FAIL with 2 recorded watchdog restarts.
- Crash demo: target prints one PASS then deliberately segfaults;
  `fdsup` records signal=11 SIGSEGV; VERDICT FAIL with crash record.

## README claims to audit (verbatim excerpts)

1. "a test only counts when the target's own `FDTEST DONE` tallies match
   what the harness parsed — nothing lost, nothing spoofed"
2. "if the whole target hangs, the host watchdog restarts the VM — and
   the restart is in the report"
3. "Timer drift budgets are set for QEMU/TCG emulation; on real QNX
   hardware the same checks are typically three orders of magnitude
   tighter."
4. "Target binaries are linked statically so the minimal boot image
   needs no loader setup"
5. "The serial console is the only channel: deliberately. It works on
   any QNX target with a UART, including boards with no network."
6. Roadmap section lists: streaming `slog2` into the report, and
   `dumper` core-file harvesting on targets with a filesystem.
7. Requirements: Linux host, QNX SDP 8.0, QEMU qemu-system-x86_64,
   Python 3.10+ stdlib only. Exit code 0 on PASS, 1 otherwise.

## Questions (answer concisely, prioritized, no flattery)

(a) README claims: which of the claims above (or any claim implied by
    the description) are exaggerated, inaccurate, or worded in a way a
    QNX-expert judge would penalize? Quote the claim and say what's
    wrong.
(b) Design gaps: what remaining weakness in the verdict rules, harness
    design, or demo set could a judge or a live demo expose? Focus on
    what is NOT already fixed in rounds 1-2 above.
(c) Concrete fixes: the top 3 changes worth making before submission,
    ordered by (impact on judging) / (effort). At most one may be a new
    feature; the rest should be corrections, clarifications, or polish.

Flag anything factually wrong about QNX 8.0 in the description above.
