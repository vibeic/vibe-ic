"""Verdict-safety of the parallel per-step / structural-gate evaluation.

`flow_compliance_check` evaluates independent read-only gates concurrently
(bounded ThreadPoolExecutor, env `VIBE_IC_COMPLIANCE_WORKERS`). The gates are
pure validators run as subprocesses with `cwd=project` (no `os.chdir`) that
write only their own distinct report file, so concurrency must NOT change the
verdict. These tests pin that invariant:

  * `_compliance_workers` returns sane, bounded worker counts and honours the
    env override (1 = the sequential fallback), never crashing on junk input.
  * A serial (workers=1) run and a parallel (workers>1) run over the SAME
    starting project state produce a BYTE-IDENTICAL compliance report.

The parity run uses two same-source copies (one serial, one parallel) rather
than re-running one project twice: some individual gate PROGRAMS write
run-to-run-varying report content into the project they audit (timestamps /
temp paths) — a pre-existing non-determinism unrelated to concurrency — so the
project *state* legitimately drifts across runs. What must stay identical is
the compliance REPORT itself (what the runner consumes for pass/fail), which is
exactly what we assert (with the differing project-path basename normalised).
"""
from __future__ import annotations
import json
import shutil
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / "flow_compliance_check.py"
sys.path.insert(0, str(PROG.parent))
import flow_compliance_check as _flow  # noqa: E402


# ---------------------------------------------------------------------------
# _compliance_workers — bounded, env-overridable, crash-proof
# ---------------------------------------------------------------------------
def test_compliance_workers_trivial_is_serial():
    assert _flow._compliance_workers(0) == 1
    assert _flow._compliance_workers(1) == 1


def test_compliance_workers_env_override(monkeypatch):
    monkeypatch.setenv("VIBE_IC_COMPLIANCE_WORKERS", "4")
    assert _flow._compliance_workers(10) == 4
    # clamped down to the number of tasks — never more workers than work
    assert _flow._compliance_workers(2) == 2


def test_compliance_workers_env_forces_serial(monkeypatch):
    monkeypatch.setenv("VIBE_IC_COMPLIANCE_WORKERS", "1")
    assert _flow._compliance_workers(50) == 1


def test_compliance_workers_junk_env_falls_back(monkeypatch):
    # Non-integer / non-positive env must not crash and must stay >= 1.
    for junk in ("garbage", "0", "-3", ""):
        monkeypatch.setenv("VIBE_IC_COMPLIANCE_WORKERS", junk)
        w = _flow._compliance_workers(8)
        assert isinstance(w, int) and w >= 1


def test_compliance_workers_default_bounded(monkeypatch):
    monkeypatch.delenv("VIBE_IC_COMPLIANCE_WORKERS", raising=False)
    # Default is cpu-derived but capped at 8 and never exceeds the task count.
    assert _flow._compliance_workers(3) <= 3
    assert _flow._compliance_workers(1000) <= 8


# ---------------------------------------------------------------------------
# serial vs parallel → identical compliance report (verdict-safety)
# ---------------------------------------------------------------------------
def _make_fixture(root: Path) -> None:
    """A minimal but RTL-bearing project so BOTH the structural-gate umbrella
    and the per-step loop actually execute their gate subprocesses."""
    rtl = root / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "adder.v").write_text(
        "module adder(input [3:0] a, input [3:0] b, output [4:0] y);\n"
        "  assign y = a + b;\n"
        "endmodule\n"
    )
    docs = root / "phase1" / "generated_docs"
    docs.mkdir(parents=True)
    (docs / "L1_DATASHEET.json").write_text(json.dumps({"ic_name": "adder"}))


def _run_json(proj: Path, workers: str, out: Path) -> None:
    import os
    env = dict(os.environ)
    env["VIBE_IC_COMPLIANCE_WORKERS"] = workers
    subprocess.run(
        [sys.executable, str(PROG), str(proj), "--json", str(out)],
        capture_output=True, text=True, env=env,
    )


def test_serial_and_parallel_reports_are_identical(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    _make_fixture(src)

    # Two same-source copies: one evaluated serially, one in parallel. Running
    # on separate copies isolates the compliance REPORT from the pre-existing
    # per-gate report-file non-determinism (which mutates the project in place).
    a = tmp_path / "proj_A"
    b = tmp_path / "proj_B"
    shutil.copytree(src, a)
    shutil.copytree(src, b)

    ra = tmp_path / "report_serial.json"
    rb = tmp_path / "report_parallel.json"
    _run_json(a, "1", ra)
    _run_json(b, "8", rb)

    assert ra.exists() and rb.exists(), "both runs must emit a report"

    # Normalise the only legitimate difference — the project path basename —
    # then require byte-for-byte equality of the report (verdict + per-step
    # status + ordering all pinned).
    ta = ra.read_text().replace("proj_A", "proj_X")
    tb = rb.read_text().replace("proj_B", "proj_X")
    assert ta == tb, (
        "parallel gate evaluation changed the compliance report — "
        "concurrency must be verdict-safe and order-preserving"
    )

    # And the parsed verdicts must match (belt-and-braces, order-independent).
    da = json.loads(ta)
    db = json.loads(tb)
    assert da["overall"] == db["overall"]
    assert da["counts"] == db["counts"]
    assert {s["id"]: s["status"] for s in da["steps"]} == \
           {s["id"]: s["status"] for s in db["steps"]}
