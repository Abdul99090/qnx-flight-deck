#!/usr/bin/env python3
"""QNX Flight-Deck — a flight recorder & pre-flight harness for QNX 8.0.

Automates the full embedded development loop on a Linux host:

    build (qcc) -> image (mkifs) -> boot (QEMU) -> harvest console
    -> structured JSON verdict

The target runs an on-board test agent that prints machine-readable
FDTEST lines over the serial console; Flight-Deck parses them into a
report, and can optionally act as a watchdog: if the target goes
silent (hang/crash), the harness restarts the VM and records the
event in the report.

No third-party dependencies: Python 3.10+ standard library only.

Example:
    ./flightdeck.py run \
        --source ../target/fdtest.c \
        --buildfile-template ../target/fdtest.build.tmpl \
        --name fdtest
"""

from __future__ import annotations

import argparse
import atexit
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

TOOL_VERSION = "0.3.0"
DONE_MARKER = "FDTEST DONE"
FDTEST_RE = re.compile(r"^FDTEST\s+(\S+)\s+(PASS|FAIL)\s*(.*)$")
DONE_RE = re.compile(r"^FDTEST DONE pass=(\d+) fail=(\d+)")
FDCRASH_RE = re.compile(r"^FDCRASH\s+(.*)$")

# The QEMU child currently running, so a killed harness never orphans it.
_ACTIVE_PROC: subprocess.Popen | None = None


def _kill_active() -> None:
    global _ACTIVE_PROC
    if _ACTIVE_PROC is not None and _ACTIVE_PROC.poll() is None:
        _ACTIVE_PROC.kill()
    _ACTIVE_PROC = None


atexit.register(_kill_active)


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------

def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def run_cmd(cmd: list[str], env: dict | None = None, timeout: int = 300) -> tuple[int, str]:
    """Run a command, return (exit_code, combined_output)."""
    proc = subprocess.run(
        cmd, env=env, timeout=timeout,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    return proc.returncode, proc.stdout


def sdp_env(sdp_dir: Path) -> dict:
    """Environment with the QNX SDP paths set (equivalent of sourcing
    qnxsdp-env.sh, restricted to what qcc/mkifs need)."""
    env = dict(os.environ)
    env["QNX_HOST"] = str(sdp_dir / "host/linux/x86_64")
    env["QNX_TARGET"] = str(sdp_dir / "target/qnx")
    env["PATH"] = env["QNX_HOST"] + "/usr/bin:" + env.get("PATH", "")
    return env


# --------------------------------------------------------------------------
# phases
# --------------------------------------------------------------------------

@dataclass
class PhaseResult:
    ok: bool
    seconds: float
    detail: str = ""


@dataclass
class TestResult:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class WatchdogEvent:
    at_seconds: float
    reason: str
    restart_no: int


@dataclass
class AttemptRecord:
    attempt: int
    outcome: str  # done | silent | timeout | ended | exited
    seconds: float


@dataclass
class Report:
    tool: str = f"qnx-flight-deck {TOOL_VERSION}"
    run_name: str = ""
    started_at: str = ""
    qnx_sdp: str = ""
    target: str = "qemu-x86_64"
    build: PhaseResult | None = None
    image: PhaseResult | None = None
    boot_seconds: float | None = None
    tests: list[TestResult] = field(default_factory=list)
    crashes: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    done_counts: dict | None = None
    attempts: list[AttemptRecord] = field(default_factory=list)
    failure_summary: str = ""
    watchdog_events: list[WatchdogEvent] = field(default_factory=list)
    console_log: str = ""
    verdict: str = "ERROR"

    def to_dict(self) -> dict:
        return {
            "tool": self.tool,
            "run_name": self.run_name,
            "started_at": self.started_at,
            "qnx_sdp": self.qnx_sdp,
            "target": self.target,
            "build": vars(self.build) if self.build else None,
            "image": vars(self.image) if self.image else None,
            "boot_seconds": self.boot_seconds,
            "tests": [vars(t) for t in self.tests],
            "crashes": self.crashes,
            "problems": self.problems,
            "done_counts": self.done_counts,
            "attempts": [vars(a) for a in self.attempts],
            "failure_summary": self.failure_summary,
            "summary": {
                "pass": sum(1 for t in self.tests if t.ok),
                "fail": sum(1 for t in self.tests if not t.ok),
            },
            "watchdog_events": [vars(e) for e in self.watchdog_events],
            "console_log": self.console_log,
            "verdict": self.verdict,
        }


def phase_build(args, env: dict, workdir: Path) -> tuple[PhaseResult, Path | None]:
    """Compile the target program with qcc."""
    t0 = time.monotonic()
    binary = workdir / args.name
    cmd = [
        "qcc", "-V", "gcc_ntox86_64",
        *(["-static"] if args.static else []),
        "-O2", "-o", str(binary), str(Path(args.source).resolve()),
    ]
    if args.qcc_flags:
        cmd[3:3] = args.qcc_flags.split()
    rc, out = run_cmd(cmd, env=env)
    dt = time.monotonic() - t0
    if rc != 0:
        return PhaseResult(False, dt, out.strip()[-2000:]), None
    return PhaseResult(True, dt, f"qcc -> {binary.name} ({binary.stat().st_size} bytes)"), binary


def phase_image(args, env: dict, workdir: Path, binary: Path) -> tuple[PhaseResult, Path | None]:
    """Render the mkifs buildfile from its template and build the image.

    If the template references {SUP_PATH}, the on-target supervisor
    (fdsup.c, next to the template by default) is compiled first.
    """
    t0 = time.monotonic()
    tmpl = Path(args.buildfile_template).read_text()
    if "{SUP_PATH}" in tmpl:
        sup_src = Path(args.supervisor_source) if args.supervisor_source else \
            Path(args.buildfile_template).resolve().parent / "fdsup.c"
        sup_bin = workdir / "fdsup"
        rc, out = run_cmd(
            ["qcc", "-V", "gcc_ntox86_64", "-static", "-O2",
             "-o", str(sup_bin), str(sup_src)], env=env)
        if rc != 0:
            return PhaseResult(False, time.monotonic() - t0,
                               "supervisor build failed: " + out.strip()[-1000:]), None
        tmpl = tmpl.replace("{SUP_PATH}", str(sup_bin))
    buildfile = workdir / (args.name + ".build")
    buildfile.write_text(
        tmpl.replace("{BIN_PATH}", str(binary)).replace("{BIN_NAME}", args.name)
    )
    image = workdir / (args.name + ".ifs")
    rc, out = run_cmd(["mkifs", str(buildfile), str(image)], env=env)
    dt = time.monotonic() - t0
    if rc != 0:
        return PhaseResult(False, dt, out.strip()[-2000:]), None
    return PhaseResult(True, dt, f"mkifs -> {image.name} ({image.stat().st_size} bytes)"), image


def qemu_command(args, image: Path, serial_path: Path) -> tuple[list[str], dict]:
    """Build the QEMU command line (+env) for the proven local recipe.

    QNX 8's startup requires the XSAVE CPU feature: always use
    `-cpu max` under TCG (the default qemu64 model lacks it and the
    QNX bootstrap hangs silently).
    """
    env = dict(os.environ)
    cmd: list[str] = []
    if args.qemu_root:
        root = Path(args.qemu_root)
        env["LD_LIBRARY_PATH"] = (
            f"{root}/usr/lib/x86_64-linux-gnu:{root}/lib/x86_64-linux-gnu"
        )
        env["QEMU_MODULE_DIR"] = f"{root}/usr/lib/x86_64-linux-gnu/qemu"
        cmd += [str(root / "usr/bin/qemu-system-x86_64"),
                "-L", str(root / "usr/share/qemu"),
                "-L", str(root / "usr/share/seabios")]
    else:
        cmd += [shutil.which("qemu-system-x86_64") or "qemu-system-x86_64"]
    cmd += [
        "-kernel", str(image),
        "-cpu", "max",
        "-m", str(args.memory_mb),
        "-display", "none",
        "-serial", f"file:{serial_path}",
        "-monitor", "none",
        "-no-reboot",
        "-nic", "none",
    ]
    return cmd, env


def boot_once(args, image: Path, serial_path: Path,
              report: Report, boot_t0: float) -> str:
    """Run one QEMU boot. Returns "done" (FDTEST DONE seen), "silent"
    (watchdog: test session started, then went quiet), "ended" (boot
    script finished without DONE), "exited" (QEMU died on its own), or
    "timeout" (boot deadline hit).

    Boot and test phases have separate failure handling: before
    FDTEST START the only deadline is the overall timeout (a slow
    boot is not a hang); the silence watchdog arms only once the
    test session has started producing progress output.
    """
    if serial_path.exists():
        serial_path.unlink()
    serial_path.touch()
    cmd, env = qemu_command(args, image, serial_path)
    proc = subprocess.Popen(cmd, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    global _ACTIVE_PROC
    _ACTIVE_PROC = proc
    run_t0 = time.monotonic()
    last_size = 0
    last_output_at = time.monotonic()
    saw_start = False
    done_at: float | None = None
    try:
        while time.monotonic() - run_t0 < args.timeout:
            time.sleep(0.25)
            try:
                size = serial_path.stat().st_size
            except FileNotFoundError:
                size = 0
            if size != last_size:
                last_size = size
                last_output_at = time.monotonic()
                text = serial_path.read_text(errors="replace")
                if "FDTEST START" in text:
                    saw_start = True
                if report.boot_seconds is None and "FDTEST START" in text:
                    report.boot_seconds = round(time.monotonic() - boot_t0, 2)
                if done_at is None and DONE_MARKER in text:
                    done_at = time.monotonic()
                if done_at is None and "FDSCRIPT END" in text:
                    # The boot script finished without the target ever
                    # reporting DONE (e.g. it crashed under the
                    # supervisor): the session is over, don't burn the
                    # whole timeout waiting.
                    return "ended"
            if done_at is not None and time.monotonic() - done_at > 1.5:
                # Grace window: give a late crash line (e.g. a supervisor
                # reporting a child that died right at the end) time to
                # reach the console before we call it done.
                return "done"
            if proc.poll() is not None:
                # QEMU exited on its own (e.g. guest reboot under
                # -no-reboot): distinct from a harness timeout.
                return "done" if done_at is not None else "exited"
            if (args.watchdog and saw_start
                    and time.monotonic() - last_output_at > args.watchdog_silence):
                return "silent"
        return "done" if done_at is not None else "timeout"
    finally:
        if proc.poll() is None:
            proc.send_signal(signal.SIGTERM)
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        _ACTIVE_PROC = None


def phase_boot_and_harvest(args, image: Path, workdir: Path,
                           report: Report) -> bool:
    """Boot the target, restarting it under the watchdog when it hangs.

    Per-attempt serial logs are kept as console-attempt-N.log and then
    concatenated into console.log. Returns True iff some attempt
    reached FDTEST DONE.
    """
    boot_t0 = time.monotonic()
    attempt = 0
    chunks: list[str] = []
    while True:
        attempt += 1
        serial_path = workdir / f"console-attempt-{attempt}.log"
        a_t0 = time.monotonic()
        outcome = boot_once(args, image, serial_path, report, boot_t0)
        report.attempts.append(AttemptRecord(
            attempt=attempt, outcome=outcome,
            seconds=round(time.monotonic() - a_t0, 2)))
        if serial_path.exists():
            chunks.append(f"===== boot attempt {attempt} =====\n"
                          + serial_path.read_text(errors="replace"))
        if outcome == "done":
            break
        if outcome == "silent" and args.watchdog and attempt <= args.max_restarts:
            report.watchdog_events.append(WatchdogEvent(
                at_seconds=round(time.monotonic() - boot_t0, 2),
                reason=f"target silent > {args.watchdog_silence}s (hang suspected)",
                restart_no=attempt,
            ))
            continue
        break
    (workdir / "console.log").write_text("\n".join(chunks))
    return outcome == "done"


def parse_console(serial_path: Path) -> list[TestResult]:
    return parse_session(serial_path)[0]


def parse_session(serial_path: Path) -> tuple[list[TestResult], dict | None, list[str], list[str]]:
    """Parse the LAST test session in the log (earlier sessions belong
    to watchdog-restarted attempts).

    Returns (tests, done_counts, crashes, problems): the FDTEST
    results, the pass/fail counts the target itself declared on its
    FDTEST DONE line (None when absent), any FDCRASH lines the
    on-target supervisor reported, and session-integrity problems —
    duplicate test records and malformed FDTEST lines. A session with
    problems is never the basis for a PASS: the DONE tally alone
    cannot distinguish "test B passed" from "test A reported twice".
    """
    tests: list[TestResult] = []
    done_counts: dict | None = None
    crashes: list[str] = []
    problems: list[str] = []
    if not serial_path.exists():
        return tests, done_counts, crashes, problems
    lines = serial_path.read_text(errors="replace").splitlines()
    start = 0
    for i, line in enumerate(lines):
        if "FDTEST START" in line:
            start = i
    seen: dict[str, int] = {}
    for line in lines[start:]:
        s = line.strip()
        m = FDTEST_RE.match(s)
        if m and m.group(1) not in ("DONE", "START"):
            seen[m.group(1)] = seen.get(m.group(1), 0) + 1
            tests.append(TestResult(m.group(1), m.group(2) == "PASS", m.group(3).strip()))
            continue
        d = DONE_RE.match(s)
        if d:
            done_counts = {"pass": int(d.group(1)), "fail": int(d.group(2))}
            continue
        c = FDCRASH_RE.match(s)
        if c:
            crashes.append(c.group(1).strip())
            continue
        if s.startswith("FDTEST") and "FDTEST START" not in s:
            problems.append(f"malformed FDTEST record: {s[:80]}")
    for name, n in seen.items():
        if n > 1:
            problems.append(f"duplicate test record: {name} reported {n}x")
    return tests, done_counts, crashes, problems


# --------------------------------------------------------------------------
# main run
# --------------------------------------------------------------------------

def cmd_run(args) -> int:
    report = Report(run_name=args.name, started_at=now_iso(), qnx_sdp=args.sdp)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    workdir = Path(args.out) / f"{args.name}-{stamp}"
    workdir.mkdir(parents=True, exist_ok=True)
    env = sdp_env(Path(args.sdp))

    report.build, binary = phase_build(args, env, workdir)
    if binary is None:
        return finish(args, report, workdir)
    report.image, image = phase_image(args, env, workdir, binary)
    if image is None:
        return finish(args, report, workdir)

    done = phase_boot_and_harvest(args, image, workdir, report)
    serial_path = workdir / "console.log"
    (report.tests, report.done_counts,
     report.crashes, report.problems) = parse_session(serial_path)
    report.console_log = str(serial_path)
    passed = sum(1 for t in report.tests if t.ok)
    failed = sum(1 for t in report.tests if not t.ok)
    counts_match = report.done_counts == {"pass": passed, "fail": failed}
    # A PASS must be trustworthy: the target reached DONE, every parsed
    # check passed, the target's own DONE tallies match what we parsed
    # (a dropped or garbled record breaks the match), the session is free of
    # duplicate/malformed records, and no supervised process crashed
    # during the session.
    report.verdict = "PASS" if (
        done and failed == 0 and passed > 0 and counts_match
        and not report.crashes and not report.problems
    ) else "FAIL"
    return finish(args, report, workdir)


def build_failure_summary(report: Report) -> str:
    """One-line diagnosis across all boot attempts: why this run did
    not pass, correlating attempt outcomes, watchdog restarts, test
    results, crash records and session-integrity problems."""
    reasons: list[str] = []
    if report.build and not report.build.ok:
        reasons.append("build failed")
    elif report.image and not report.image.ok:
        reasons.append("image build failed")
    if report.attempts and report.attempts[-1].outcome != "done":
        reasons.append(f"final boot attempt ended '{report.attempts[-1].outcome}'")
    if report.watchdog_events:
        reasons.append(f"watchdog restarts: {len(report.watchdog_events)}")
    failed = [t.name for t in report.tests if not t.ok]
    if failed:
        reasons.append("failed tests: " + ", ".join(failed))
    for c in report.crashes:
        reasons.append(f"crash: {c}")
    passed = sum(1 for t in report.tests if t.ok)
    if report.done_counts is not None and report.tests:
        if report.done_counts != {"pass": passed, "fail": len(failed)}:
            reasons.append(
                f"DONE tallies mismatch (target pass={report.done_counts['pass']} "
                f"fail={report.done_counts['fail']}; parsed pass={passed} "
                f"fail={len(failed)})")
    reasons.extend(report.problems)
    if not reasons:
        reasons.append("no passing test session recorded")
    return "; ".join(reasons)


def finish(args, report: Report, workdir: Path) -> int:
    if report.build and not report.build.ok and report.verdict == "ERROR":
        report.verdict = "BUILD-FAILED"
    if report.image and not report.image.ok and report.verdict == "ERROR":
        report.verdict = "IMAGE-FAILED"
    if report.verdict != "PASS" and not report.failure_summary:
        report.failure_summary = build_failure_summary(report)
    out = workdir / "report.json"
    out.write_text(json.dumps(report.to_dict(), indent=2) + "\n")
    print(f"== QNX Flight-Deck :: {report.run_name} ==")
    if report.build:
        print(f"  build : {'OK ' if report.build.ok else 'FAIL'} ({report.build.seconds:.1f}s) {report.build.detail.splitlines()[-1] if report.build.detail else ''}")
    if report.image:
        print(f"  image : {'OK ' if report.image.ok else 'FAIL'} ({report.image.seconds:.1f}s) {report.image.detail.splitlines()[-1] if report.image.detail else ''}")
    if report.boot_seconds is not None:
        print(f"  boot  : target reached tests in {report.boot_seconds:.1f}s")
    for t in report.tests:
        print(f"  test  : {t.name:<8} {'PASS' if t.ok else 'FAIL'}  {t.detail}")
    for c in report.crashes:
        print(f"  crash : {c}")
    for e in report.watchdog_events:
        print(f"  watch : restart #{e.restart_no} at {e.at_seconds:.0f}s ({e.reason})")
    for p in report.problems:
        print(f"  integ : {p}")
    if report.failure_summary:
        print(f"  why   : {report.failure_summary}")
    print(f"  VERDICT: {report.verdict}")
    print(f"  report : {out}")
    return 0 if report.verdict == "PASS" else 1


def main(argv: list[str] | None = None) -> int:
    def _on_signal(signum, _frame):
        _kill_active()
        raise SystemExit(128 + signum)
    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)
    p = argparse.ArgumentParser(prog="flightdeck", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="build -> image -> boot -> harvest -> verdict")
    r.add_argument("--name", required=True, help="run/image name")
    r.add_argument("--source", required=True, help="target C source file")
    r.add_argument("--buildfile-template", required=True,
                   help="mkifs buildfile template with {BIN_PATH}/{BIN_NAME}")
    r.add_argument("--sdp", default=os.environ.get("QNX_SDP_DIR", str(Path.home() / "qnx/qnx800")),
                   help="QNX SDP 8.0 install dir (default: ~/qnx/qnx800)")
    r.add_argument("--out", default="runs", help="output root for run artifacts")
    r.add_argument("--static", action="store_true", default=True,
                   help="link the target statically (default)")
    r.add_argument("--qcc-flags", default="", help="extra qcc flags, space-separated")
    r.add_argument("--supervisor-source", default="",
                   help="fdsup.c path (default: next to the buildfile template)")
    r.add_argument("--qemu-root", default=os.environ.get("FD_QEMU_ROOT", ""),
                   help="user-level QEMU tree (usr/bin/qemu-system-x86_64 inside); "
                        "empty = use system qemu")
    r.add_argument("--memory-mb", type=int, default=256)
    r.add_argument("--timeout", type=int, default=90, help="per-boot timeout, seconds")
    r.add_argument("--watchdog", action="store_true",
                   help="restart the target when it goes silent")
    r.add_argument("--watchdog-silence", type=int, default=6,
                   help="seconds of console silence that count as a hang")
    r.add_argument("--max-restarts", type=int, default=2)
    r.set_defaults(fn=cmd_run)
    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
