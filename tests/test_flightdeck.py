"""Host-side unit tests for Flight-Deck (no QNX/QEMU needed).

Run:  python3 -m pytest tests/ -q     (or: python3 tests/test_flightdeck.py)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "flightdeck"))

from flightdeck import (  # noqa: E402
    parse_console, parse_session, build_failure_summary,
    Report, TestResult, WatchdogEvent, AttemptRecord,
)


def write_log(tmp: Path, text: str) -> Path:
    p = tmp / "console.log"
    p.write_text(text)
    return p


def test_parse_basic(tmp: Path):
    log = write_log(tmp, "\n".join([
        "kernel noise",
        "FDTEST START sysname=QNX",
        "FDTEST ipc PASS rtt_us=100 seq=42",
        "FDTEST timer FAIL drift_us=99999",
        "FDTEST DONE pass=1 fail=1",
    ]))
    tests = parse_console(log)
    assert [t.name for t in tests] == ["ipc", "timer"]
    assert tests[0].ok and not tests[1].ok
    assert tests[0].detail == "rtt_us=100 seq=42"


def test_parse_uses_last_session_after_watchdog_restart(tmp: Path):
    log = write_log(tmp, "\n".join([
        "===== boot attempt 1 =====",
        "FDTEST START sysname=QNX",
        "FDTEST ipc PASS rtt_us=100",
        "===== boot attempt 2 =====",
        "FDTEST START sysname=QNX",
        "FDTEST ipc PASS rtt_us=90",
        "FDTEST sched PASS wake_order=2,1,0",
        "FDTEST DONE pass=2 fail=0",
    ]))
    tests = parse_console(log)
    assert len(tests) == 2
    assert tests[0].detail == "rtt_us=90"


def test_parse_missing_file(tmp: Path):
    assert parse_console(tmp / "nope.log") == []


def test_parse_session_done_counts_and_crash(tmp: Path):
    log = write_log(tmp, "\n".join([
        "FDTEST START sysname=QNX",
        "FDTEST pre-crash PASS note=about-to-fault",
        "FDCRASH child=/proc/boot/fdcrash signal=11 signame=SIGSEGV",
    ]))
    tests, done_counts, crashes, problems = parse_session(log)
    assert len(tests) == 1 and tests[0].ok
    assert done_counts is None
    assert crashes == ["child=/proc/boot/fdcrash signal=11 signame=SIGSEGV"]
    assert problems == []


def test_parse_session_done_counts(tmp: Path):
    log = write_log(tmp, "\n".join([
        "FDTEST START sysname=QNX",
        "FDTEST ipc PASS rtt_us=1",
        "FDTEST DONE pass=1 fail=0",
    ]))
    tests, done_counts, crashes, problems = parse_session(log)
    assert done_counts == {"pass": 1, "fail": 0}
    assert crashes == []
    assert problems == []


def test_parse_session_duplicate_records_flagged(tmp: Path):
    # A duplicated PASS must not be able to stand in for a lost record:
    # the DONE tally (pass=2) matches the parsed counts, so only the
    # duplicate check can catch this.
    log = write_log(tmp, "\n".join([
        "FDTEST START sysname=QNX",
        "FDTEST ipc PASS rtt_us=1",
        "FDTEST ipc PASS rtt_us=2",
        "FDTEST DONE pass=2 fail=0",
    ]))
    tests, done_counts, crashes, problems = parse_session(log)
    assert len(tests) == 2
    assert any("duplicate" in p and "ipc" in p for p in problems)


def test_parse_session_malformed_records_flagged(tmp: Path):
    log = write_log(tmp, "\n".join([
        "FDTEST START sysname=QNX",
        "FDTEST ipc PASS rtt_us=1",
        "FDTEST timer PAS",  # truncated on the wire
        "FDTEST DONE pass=1 fail=0",
    ]))
    tests, done_counts, crashes, problems = parse_session(log)
    assert [t.name for t in tests] == ["ipc"]
    assert any("malformed" in p for p in problems)


def test_failure_summary_crash_and_attempt(_tmp: Path):
    r = Report(run_name="demo")
    r.attempts = [AttemptRecord(1, "ended", 3.5)]
    r.tests = [TestResult("pre-crash", True, "")]
    r.crashes = ["child=/proc/boot/fdcrash signal=11 signame=SIGSEGV"]
    s = build_failure_summary(r)
    assert "ended" in s and "SIGSEGV" in s


def test_report_shape():
    r = Report(run_name="demo")
    r.tests = [TestResult("ipc", True, "rtt_us=1"), TestResult("timer", False, "drift")]
    r.watchdog_events = [WatchdogEvent(12.0, "silent", 1)]
    d = r.to_dict()
    assert d["summary"] == {"pass": 1, "fail": 1}
    assert d["watchdog_events"][0]["restart_no"] == 1
    assert d["run_name"] == "demo"
    assert d["attempts"] == []
    assert d["problems"] == []
    assert d["failure_summary"] == ""


if __name__ == "__main__":
    import tempfile
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        if fn is test_report_shape:
            fn()
        else:
            with tempfile.TemporaryDirectory() as td:
                fn(Path(td))
        print(f"ok - {fn.__name__}")
    print(f"{len(fns)} tests passed")
