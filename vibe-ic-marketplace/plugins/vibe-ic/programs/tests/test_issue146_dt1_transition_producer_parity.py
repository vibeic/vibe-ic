"""#146 blocker-2 — DT1 transition-coverage producer must fire from PHASE 3.

The Step-11 scan cut (`cut_netlist.v`) is only born by the time phase3 runs, so
the DT1 transition producer — like the DT2 path-delay producer — must run from
phase3_one_shot_runner once the cut exists. Without it, DT1's gate
(transition_coverage_check) hard-FAILs on a permanently-absent
transition_coverage.json (evidence: sha256 clean_run_v1422 produced
path_delay_coverage.json but NOT transition_coverage.json).

NOW EXECUTED, NOT GREPPED (vibe-ic#235). These four tests used to assert
SUBSTRINGS of the runner source — `'_dt1_cut = project / "..."' in _SRC` — with
the stated excuse that "the giant phase3 runner block is integration-tested
end-to-end, not unit-callable". That excuse expired when #235 extracted the
block into `run_at_speed_atpg_producers`, and the excuse was never a good one:
a source-string test passes on a producer that is wired up perfectly and never
reached, and it FAILS on a pure rename that changes no behaviour at all. It is
wrong in both directions. Every assertion below now drives the real producer and
observes what it launched, so the #146 guarantees are pinned by behaviour.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROGS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGS))

import phase3_one_shot_runner as R  # noqa: E402


class _FakeProc:
    def __init__(self, rc=0):
        self.returncode, self.stdout, self.stderr = rc, "", ""


def _project(tmp_path: Path, *, cut: bool = True, clock: bool = True,
             dt1_verdict: str | None = None) -> Path:
    if clock:
        sdc = tmp_path / R._ATPG_SDC_REL
        sdc.parent.mkdir(parents=True, exist_ok=True)
        sdc.write_text("create_clock -name clk -period 10 [get_ports clk]\n")
    if cut:
        c = tmp_path / R._ATPG_CUT_REL
        c.parent.mkdir(parents=True, exist_ok=True)
        c.write_text("module cut(); endmodule\n")
    if dt1_verdict is not None:
        j = tmp_path / R._ATPG_COVERAGE_REL["DT1"]
        j.parent.mkdir(parents=True, exist_ok=True)
        j.write_text(json.dumps({"verdict": dt1_verdict}))
    return tmp_path


def _drive(monkeypatch, project: Path, *, boom: bool = False):
    """Run the producers, recording every program actually launched."""
    launched: list = []

    def _fake(cmd, **kw):
        launched.append(Path(cmd[1]).name)
        if boom:
            raise OSError("producer blew up")
        out = Path(cmd[cmd.index("--json") + 1])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"verdict": "PASS"}))
        return _FakeProc(rc=0)

    monkeypatch.setattr(R.subprocess, "run", _fake)
    written: list = []
    notes: list = []
    R.run_at_speed_atpg_producers(project, written, notes)
    return launched, written, notes


def test_dt1_producer_invokes_transition_atpg(tmp_path, monkeypatch):
    """The DT1 producer really launches transition_fault_atpg_run.py from
    phase3 — not merely mentions it somewhere in the file."""
    launched, written, _ = _drive(monkeypatch, _project(tmp_path))
    assert "transition_fault_atpg_run.py" in launched, launched
    assert str(tmp_path / R._ATPG_COVERAGE_REL["DT1"]) in written


def test_dt1_producer_guarded_on_cut(tmp_path, monkeypatch):
    """No scan cut -> the producer must NOT launch (and, since #235, must say
    so on disk rather than vanish).

    MUTATION THIS CATCHES: dropping the cut precondition, which launches ATPG
    on a tree that has no netlist to grade.
    """
    launched, _, _ = _drive(monkeypatch, _project(tmp_path, cut=False))
    assert "transition_fault_atpg_run.py" not in launched, launched
    rec = tmp_path / R._ATPG_NOT_RUN_REL["DT1"]
    assert rec.is_file(), "#235: the skip must be disclosed, not silent"
    assert R._ATPG_CUT_REL in rec.read_text()


def test_dt1_producer_regrades_only_non_graded_placeholders(tmp_path,
                                                            monkeypatch):
    """Idempotence, executed. A real PASS is preserved; a BLOCKED /
    ENGINE_LIMITED / ERROR placeholder left by the phase2 pass on the generic
    pre-map netlist is re-graded here.

    MUTATION THIS CATCHES: re-running unconditionally (destroys a real
    measurement on every resumed run) or never re-running (the stale
    can't-grade record wedges DT1/DT2/DT3 forever — the #146 symptom).
    """
    for verdict, should_run in (("PASS", False), ("NOT_APPLICABLE", False),
                                ("BLOCKED", True), ("ENGINE_LIMITED", True),
                                ("ERROR", True)):
        proj = _project(tmp_path / verdict, dt1_verdict=verdict)
        launched, _, _ = _drive(monkeypatch, proj)
        ran = "transition_fault_atpg_run.py" in launched
        assert ran is should_run, (
            f"verdict={verdict}: expected re-grade={should_run}, got {ran}")


def test_dt1_producer_runs_before_dt2(tmp_path, monkeypatch):
    """Order, executed: DT1 before DT2 so DT3 — which fuses BOTH coverage
    artefacts — can fire in the same pass.

    MUTATION THIS CATCHES: reordering the producer tuple. The old source-index
    test would also catch a harmless variable rename and miss a real reorder
    done via any other variable name.
    """
    launched, _, _ = _drive(monkeypatch, _project(tmp_path))
    assert launched == ["transition_fault_atpg_run.py",
                        "path_delay_fault_atpg_run.py",
                        "sdd_atpg_run.py"], launched


def test_dt1_producer_is_nonfatal(tmp_path, monkeypatch):
    """Best-effort: a producer that explodes must not crash the phase3
    finalize, and (since #235) must leave a record saying it exploded."""
    launched, written, notes = _drive(monkeypatch, _project(tmp_path),
                                      boom=True)
    assert "transition_fault_atpg_run.py" in launched
    assert written == []
    assert notes, "a failed producer must not be completely silent"
    rec = json.loads((tmp_path / R._ATPG_NOT_RUN_REL["DT1"]).read_text())
    assert rec["not_run_stage"] == "producer_execution_error"
