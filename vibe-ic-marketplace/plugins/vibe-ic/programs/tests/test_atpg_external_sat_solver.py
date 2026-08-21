"""Regression tests for the external CDCL SAT-solver wiring in the at-speed
ATPG producers (DT1 transition + DT2 path-delay; DT3/SDD reuses DT2 verdicts).

ROOT CAUSE this guards: the fork's built-in ezMiniSAT times out on the large
2-frame LOC miter CNFs, ABORTing hard faults and collapsing at-speed coverage.
The fix routes the per-fault `sat -prove` at a modern external CDCL solver
(kissat/cadical) registered in the vibeic/yosys fork, selected via
`sat -select-solver <name>` when the image provides it — and falls back, with a
SELF-VALIDATING probe, to the built-in engine with NO change in grading when it
does not.

These tests are PURE (no Docker / no Yosys): they assert the script the producer
hands Yosys, and the fail-safe/anti-gaming properties of the solver probe.
"""
import sys
from pathlib import Path

import pytest

PROG_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG_DIR))

import transition_fault_atpg_run as tdf   # noqa: E402
import path_delay_fault_atpg_run as pdf   # noqa: E402


# ── DT1: -select-solver is emitted iff a solver was selected ────────────────

_FAULTS = [("_42_", "STR", "1'b0", "1'b0"), ("_43_", "STF", "1'b1", "1'b1")]

#: The per-fault `sat -timeout` these tests hand the SCRIPT BUILDER.
#:
#: Kept at or under `ci_harness_timeout_ceiling_check`'s per-call ceiling
#: (harness bound // 3 = 60 s) even though nothing here can block: as the module
#: docstring says, these tests are PURE — `_build_batch_script` returns a
#: STRING and no process is launched, so the measured worst case at these call
#: sites is the cost of formatting text. It used to be 180, which put two
#: entries on that gate's advisory list — the list of bounds it cannot resolve
#: and therefore cannot clear — where they sat as an unreviewable count. A
#: value inside the ceiling needs no exemption at all.
_SAT_TIMEOUT_S = 60


def test_dt1_batch_emits_select_solver_when_chosen():
    s = tdf._build_batch_script("f.v", "m.v", "top", _FAULTS, ["a", "b"],
                                sat_timeout=_SAT_TIMEOUT_S,
                                select_solver="kissat")
    # every per-fault prove routes at the chosen external solver
    proves = [ln for ln in s.splitlines() if ln.startswith("sat -prove trig 0")]
    assert proves, "no per-fault prove emitted"
    for ln in proves:
        assert "-select-solver kissat" in ln
        # ordering: -timeout ... -select-solver ... -set (constraints preserved)
        assert ln.index("-select-solver") < ln.index("-set f1.")


def test_dt1_batch_omits_select_solver_by_default():
    # Fallback path (no external backend) must be byte-for-byte the old command:
    # NO -select-solver token at all, so behaviour on a stale image is unchanged.
    s = tdf._build_batch_script("f.v", "m.v", "top", _FAULTS, ["a"],
                                sat_timeout=_SAT_TIMEOUT_S, select_solver="")
    assert "-select-solver" not in s
    assert f"sat -prove trig 0 -timeout {_SAT_TIMEOUT_S} -set f1." in s


# ── DT2 (path-delay; DT3/SDD reuses these verdicts) ─────────────────────────

_SPECS = [(0, "slow_to_rise", "pdf_miter_0"), (1, "slow_to_fall", "pdf_miter_1")]


def test_dt2_batch_emits_select_solver_when_chosen():
    s = pdf._build_pdf_batch("f.v", "m.v", _SPECS, ["a", "b"],
                             select_solver="cadical")
    proves = [ln for ln in s.splitlines() if ln.startswith("sat -prove ok 0")]
    assert proves
    for ln in proves:
        assert "-select-solver cadical" in ln


def test_dt2_batch_omits_select_solver_by_default():
    s = pdf._build_pdf_batch("f.v", "m.v", _SPECS, ["a"], select_solver="")
    assert "-select-solver" not in s
    assert "sat -prove ok 0" in s


# ── solver probe: override + self-validating auto-detect + fail-safe ────────

@pytest.fixture(autouse=True)
def _clear_probe_cache():
    tdf._SAT_SOLVER_PROBE_CACHE.clear()
    yield
    tdf._SAT_SOLVER_PROBE_CACHE.clear()


def test_probe_env_override_forces_builtin(monkeypatch):
    monkeypatch.setenv("VIBEIC_ATPG_SAT_SOLVER", "none")
    # must NOT even touch Docker when the built-in engine is forced
    monkeypatch.setattr(tdf, "_run_in_docker",
                        lambda *a, **k: pytest.fail("probed despite override"))
    assert tdf._detect_sat_solver(Path("."), None) == ""


def test_probe_selects_solver_only_on_end_to_end_success(monkeypatch):
    monkeypatch.setenv("VIBEIC_ATPG_SAT_SOLVER", "auto")
    # kissat probe finds a model on the known-SAT trivial prove → selected.
    def fake(project, cmd, timeout=0, pdk_dir=None):
        if "-select-solver kissat" in cmd:
            return 0, "SAT proof finished - model found: FAIL!\n", ""
        return 0, "", ""
    monkeypatch.setattr(tdf, "_run_in_docker", fake)
    assert tdf._detect_sat_solver(Path("."), None) == "kissat"


def test_probe_falls_back_when_solver_unknown(monkeypatch):
    # Stale image: yosys does not register the backend → `Unknown SAT solver`.
    # Every candidate must fall back to the built-in engine ("").
    monkeypatch.setenv("VIBEIC_ATPG_SAT_SOLVER", "auto")
    monkeypatch.setattr(
        tdf, "_run_in_docker",
        lambda *a, **k: (1, "", "ERROR: Unknown SAT solver 'kissat'. "
                                "Available solvers: minisat\n"))
    assert tdf._detect_sat_solver(Path("."), None) == ""


def test_probe_falls_back_when_backend_cannot_decide(monkeypatch):
    # Solver registered but binary missing / backend can't decide the known-SAT
    # prove (no "model found: FAIL"): fail-safe to built-in, never a false pick.
    monkeypatch.setenv("VIBEIC_ATPG_SAT_SOLVER", "auto")
    monkeypatch.setattr(
        tdf, "_run_in_docker",
        lambda *a, **k: (0, "Solving problem..\nTimeout!\n", ""))
    assert tdf._detect_sat_solver(Path("."), None) == ""


def test_probe_prefers_first_available_candidate(monkeypatch):
    # auto tries kissat first, then cadical; if only cadical answers, pick it.
    monkeypatch.setenv("VIBEIC_ATPG_SAT_SOLVER", "auto")
    def fake(project, cmd, timeout=0, pdk_dir=None):
        if "-select-solver cadical" in cmd:
            return 0, "model found: FAIL!\n", ""
        return 1, "", "ERROR: Unknown SAT solver 'kissat'.\n"
    monkeypatch.setattr(tdf, "_run_in_docker", fake)
    assert tdf._detect_sat_solver(Path("."), None) == "cadical"


# ── anti-gaming: solver choice never changes the verdict classifier ─────────

def test_verdict_classifier_is_solver_independent():
    # The fix speeds up / decides the SAT problem; it must NOT relax the grading.
    # An undecided block is still ABORT (never a false detection); only an
    # explicit model-found is DET, only an explicit proof-holds is RED — exactly
    # as before, regardless of which solver produced the block.
    assert tdf.parse_sat_verdict("SAT proof finished - model found: FAIL!") == "DET"
    assert tdf.parse_sat_verdict("no model found: SUCCESS!") == "RED"
    assert tdf.parse_sat_verdict("Solving problem..\nTimeout!") == "ABORT"
    assert tdf.parse_sat_verdict("") == "ABORT"
