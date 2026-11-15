# QNX Flight-Deck

**A flight recorder and pre-flight harness for QNX 8.0 targets.**

Flight-Deck automates the loop every embedded QNX developer runs by hand —
build, image, boot, test, *prove it worked* — and turns it into a single
command with a machine-readable verdict:

```
$ ./flightdeck/flightdeck.py run \
    --name fdtest \
    --source target/fdtest.c \
    --buildfile-template target/fdtest.build.tmpl \
    --qemu-root /path/to/qemu-root

== QNX Flight-Deck :: fdtest ==
  build : OK  (2.9s) qcc -> fdtest (1160416 bytes)
  image : OK  (7.2s) mkifs -> fdtest.ifs (3027012 bytes)
  boot  : target reached tests in 13.2s
  test  : ipc      PASS  rtt_us=11557 seq=42
  test  : timer    PASS  slept_us=69961 drift_us=19961
  test  : sched    PASS  wake_order=2,1,0
  VERDICT: PASS
  report : runs/fdtest-20261116-051400/report.json
```

Every run leaves a `report.json`: build/image results, boot latency, each
test's outcome and measurements, **harvested crash records**, watchdog
events, and the final verdict — ready for CI gating, dashboards, or an AI
agent to consume.

## Why

Embedded CI is painful: cross-compile, hand-assemble a boot image, boot a
board or emulator, squint at a serial console, and *hope* someone notices
when a test didn't run. Worse, on a minimal QNX image a process that dies
from a signal leaves **no trace at all** on the console — the boot script
simply continues, and a "successful" run can hide a segfault.

Flight-Deck treats the target like an aircraft: nothing counts unless
the flight recorder says so. It is a fault-diagnostics harness as much
as a test runner:

- a test only counts when the target's own `FDTEST DONE` tallies match
  what the harness parsed — nothing lost, nothing spoofed;
- an on-target supervisor (`fdsup`) records *exactly* how each test
  process died — exit code, signal number and name, or timeout — and
  the harness files it in the report as a crash record;
- if the whole target hangs, the host watchdog restarts the VM — and
  the restart is in the report, not lost in someone's scrollback.

## How it works

1. **Build** — compiles the target program with `qcc` (QNX SDP 8.0).
2. **Image** — renders an `mkifs` buildfile from a template and builds a
   bootable multiboot image.
3. **Boot** — launches the image in QEMU (x86_64) with the serial console
   captured to a file. No network stack is needed on the target.
4. **Supervise** — test programs run under `fdsup`, an on-target
   supervisor that waits on each child with a deadline and prints
   exactly how it ended: clean exit, exit code, **signal (crash)**, or
   timeout. A crashed process can no longer die silently.
5. **Harvest** — the on-target agent prints machine-readable result
   lines (`FDTEST <name> PASS|FAIL key=value ...`, terminated by
   `FDTEST DONE`); `fdsup` adds `FDCRASH` lines for faulted children.
   Flight-Deck parses the console stream live.
6. **Verdict** — PASS only if the target reached `FDTEST DONE`, every
   parsed check passed, the DONE tallies match the parsed results, the
   session is free of duplicate or malformed result records, and no
   crash was recorded. Anything else — build error, boot timeout,
   hang, failing check, segfault — is a FAIL with the evidence
   attached, plus a one-line `failure_summary` correlating the boot
   attempts, watchdog restarts, test results and crash records.
7. **Watchdog** *(optional)* — with `--watchdog`, a target whose test
   session goes silent is restarted up to `--max-restarts` times;
   each restart is recorded in `report.json`. The silence watchdog
   arms only after `FDTEST START`: before that, the boot is governed
   by the overall timeout alone, so a slow boot is never mistaken
   for a hang. Every boot attempt (outcome + duration) is recorded
   in the report's `attempts` timeline.

## On-target test agent

`target/fdtest.c` is a self-test agent written against native QNX APIs:

| Check | What it proves | QNX mechanism |
|-------|----------------|---------------|
| `ipc` | Microkernel message passing round-trip with payload integrity | `ChannelCreate` / `ConnectAttach` / `MsgSend` / `MsgReceive` / `MsgReply` |
| `timer` | A 50 ms sleep lands within its deadline budget (drift reported) | `clock_gettime(CLOCK_MONOTONIC)` / `nanosleep` |
| `sched` | Highest-priority thread wakes first under `SCHED_FIFO` | POSIX threads with explicit scheduling attributes |

`target/fdwatch.c` is the watchdog demo: built with `-DFD_HANG_AFTER=3`
it wedges after three heartbeats (a runaway real-time thread); built
normally it completes cleanly. The same harness run passes one and
fails — with restart events — the other.

`target/fdcrash.c` is the crash demo: it prints one passing check and
then deliberately segfaults. `fdsup` catches the death and the harness
fails the run with the evidence in the report:

```
  test  : pre-crash PASS  note=about-to-fault
  crash : child=/proc/boot/fdcrash signal=11 signame=SIGSEGV
  VERDICT: FAIL
```

## Requirements

- Linux host (developed on Ubuntu 24.04)
- **QNX SDP 8.0** installed (`qcc`, `mkifs`); point `--sdp` at it or set
  `QNX_SDP_DIR` (default `~/qnx/qnx800`). A non-commercial license is
  available free from QNX Everywhere / myQNX.
- **QEMU** `qemu-system-x86_64`: either a system install, or a user-level
  tree passed via `--qemu-root` (a directory containing
  `usr/bin/qemu-system-x86_64` plus its libraries/firmware).
- Python 3.10+ (standard library only).

> **QEMU note:** always boot with `-cpu max` (Flight-Deck does this for
> you). QNX 8's startup requires the XSAVE CPU feature; QEMU's default
> `qemu64` model doesn't expose it and the QNX bootstrap then hangs
> silently before printing anything.

## Quick start

```bash
# Self-test suite
./flightdeck/flightdeck.py run --name fdtest \
    --source target/fdtest.c \
    --buildfile-template target/fdtest.build.tmpl \
    --qemu-root "$FD_QEMU_ROOT"

# Watchdog demo — healthy target (expect PASS)
./flightdeck/flightdeck.py run --name fdwatch-ok \
    --source target/fdwatch.c \
    --buildfile-template target/fdwatch.build.tmpl \
    --qemu-root "$FD_QEMU_ROOT" \
    --watchdog --watchdog-silence 6 --max-restarts 2

# Watchdog demo — hanging target (expect FAIL + 2 restart events)
./flightdeck/flightdeck.py run --name fdwatch-hang \
    --source target/fdwatch.c \
    --buildfile-template target/fdwatch.build.tmpl \
    --qcc-flags=-DFD_HANG_AFTER=3 \
    --qemu-root "$FD_QEMU_ROOT" \
    --watchdog --watchdog-silence 6 --max-restarts 2

# Crash demo — target segfaults under the supervisor (expect FAIL + crash record)
./flightdeck/flightdeck.py run --name fdcrash \
    --source target/fdcrash.c \
    --buildfile-template target/fdcrash.build.tmpl \
    --qemu-root "$FD_QEMU_ROOT"
```

Exit code is `0` on PASS, `1` otherwise — drop it straight into CI.

## Report format

```json
{
  "tool": "qnx-flight-deck 0.3.0",
  "run_name": "fdtest",
  "started_at": "2026-11-16T05:14:00+07:00",
  "target": "qemu-x86_64",
  "build":  {"ok": true, "seconds": 2.9, "detail": "qcc -> fdtest (1160416 bytes)"},
  "image":  {"ok": true, "seconds": 7.2, "detail": "mkifs -> fdtest.ifs (3027012 bytes)"},
  "boot_seconds": 13.2,
  "tests": [
    {"name": "ipc",   "ok": true, "detail": "rtt_us=11557 seq=42"},
    {"name": "timer", "ok": true, "detail": "slept_us=69961 drift_us=19961"},
    {"name": "sched", "ok": true, "detail": "wake_order=2,1,0"}
  ],
  "crashes": [],
  "problems": [],
  "done_counts": {"pass": 3, "fail": 0},
  "attempts": [{"attempt": 1, "outcome": "done", "seconds": 21.4}],
  "failure_summary": "",
  "summary": {"pass": 3, "fail": 0},
  "watchdog_events": [],
  "console_log": "runs/fdtest-.../console.log",
  "verdict": "PASS"
}
```

## Project layout

```
flightdeck/flightdeck.py   the harness (single file, stdlib only)
target/fdsup.c             on-target supervisor (crash/timeout recorder)
target/fdtest.c            on-target self-test agent (native QNX IPC/timer/sched)
target/fdtest.build.tmpl   mkifs buildfile template for the self-test image
target/fdwatch.c           watchdog demo target (healthy / hanging builds)
target/fdwatch.build.tmpl  buildfile template for the watchdog image
target/fdcrash.c           crash-harvest demo target (deliberate SIGSEGV)
target/fdcrash.build.tmpl  buildfile template for the crash image
tests/test_flightdeck.py   host-side unit tests (no QNX/QEMU required)
runs/                      per-run artifacts: report.json + console logs
```

## Notes & limitations

- Timer drift budgets are set for QEMU/TCG emulation; on real QNX
  hardware the same checks are typically three orders of magnitude
  tighter. The measured values are always in the report. Treat the
  budget as a TCG tolerance, not as evidence of hardware timing
  quality.
- Target binaries are linked statically so the minimal boot image needs
  no loader setup; the harness keeps the image small and the boot fast.
- The serial console is the only channel: deliberately. It works on any
  QNX target with a UART, including boards with no network.
- Roadmap: streaming `slog2` (via `slogger2`/`slog2info`) into the
  report for kernel-level fault context, and `dumper` core-file
  harvesting on targets with a filesystem.

## License

MIT — see `LICENSE`.
