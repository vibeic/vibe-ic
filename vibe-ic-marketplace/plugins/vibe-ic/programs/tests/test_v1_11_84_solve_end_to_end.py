#!/usr/bin/env python3
"""The general path, end to end, on a real benchmark.

WHY END-TO-END AND NOT JUST THE CHAIN. `deterministic_emit_chain.try_emit` can
be tested in milliseconds, and those tests are worth having — but they cannot
catch the failures this work existed to fix, because every one of them was a
WIRING failure, not a logic failure:

  * the emitters were fine and unreachable — the runner never called them on
    plain prompt text, only one benchmark harness did, and that harness ran them
    AFTER an AI-authored file and overwrote it;
  * `--solve` did not exist at all, so the middle of the flow was hand-rolled;
  * `collect()` reported 6/6 artefacts while 4 problems had `rtl_gen` BLOCKED,
    because it globbed for files instead of reading the run's own verdict.

None of those is visible from inside a unit. They are only visible by running
the thing and looking at what came out, which is what these do.

They are SLOW (a real runner subprocess per problem) and they SKIP cleanly when
the corpus is absent. That is the price of testing the wiring; the fast
chain-level tests live beside them, not instead of them.
"""
import json
import os
import re
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))

# No hard-coded home. The corpus lives outside the plugin, so its location must
# come from the environment or not at all — a personal path baked into shipped
# source is a test that only ever runs on one machine, and it silently SKIPs
# everywhere else while looking like coverage.
_CORPUS_ENV = "VIBEIC_CORPUS_ROOT"
_CORPUS = Path(os.environ[_CORPUS_ENV]) if os.environ.get(_CORPUS_ENV) else None
_VE = (_CORPUS / "verilog-eval" / "dataset_spec-to-rtl") if _CORPUS else None
_LIMIT = int(os.environ.get("VIBEIC_SOLVE_TEST_LIMIT", "4"))

pytestmark = pytest.mark.skipif(
    _VE is None or not _VE.is_dir(),
    reason=f"VerilogEval corpus absent; set ${_CORPUS_ENV} to the external "
           f"benchmark corpus root")


@pytest.fixture(scope="module")
def solved():
    """Run the REAL front door once; every test reads the same run."""
    td = tempfile.mkdtemp(prefix="vibeic-solve-e2e-")
    rc = _pr.run(
        [sys.executable, str(_PROGRAMS / "benchmark_dispatch.py"),
         "verilogeval-v2", "--solve", "--dataset", str(_VE),
         "--run", td, "--limit", str(_LIMIT)],
        capture_output=True, text=True)
    rep = Path(td) / "solve_report.json"
    if not rep.is_file():
        pytest.fail(f"--solve wrote no report (rc={rc.returncode})\n"
                    f"{rc.stdout[-2000:]}\n{rc.stderr[-2000:]}")
    return {"dir": Path(td), "report": json.loads(rep.read_text()),
            "stdout": rc.stdout, "rc": rc.returncode}


# ── the wiring the unit tests cannot see ─────────────────────────────────────
def test_the_front_door_has_a_verb_that_solves(solved):
    """--solve exists and produced a report. Before this it did not exist, and
    the gap between --setup and --score was filled by hand."""
    assert solved["report"]["total"] == _LIMIT


def test_every_problem_was_routed_by_the_general_router(solved):
    """Nature and entry come from task_nature_route, not from a benchmark table."""
    for r in solved["report"]["results"]:
        assert r["nature"], f"{r['id']} was never classified"
        assert r["entry"], f"{r['id']} has no entry step"
        assert r["evidence"], f"{r['id']} has no evidence class"


def test_an_rtl_benchmark_never_exits_into_physical_design(solved):
    """Measured: no open RTL scorer reads a netlist or a GDS. Exiting past
    synthesis would burn work nothing consumes — the waste the two-ended model
    exists to stop."""
    import task_nature_route as T
    order = {s: i for i, s in enumerate(T.flow_step_ids())}
    for r in solved["report"]["results"]:
        assert order[str(r["exit"])] < order["9"], (
            f"{r['id']} exits at {r['exit']}, at or past synthesis")


def test_no_benchmark_specific_solver_is_on_the_path(solved):
    """The point of the overhaul: one path, no per-benchmark solver."""
    for proj in (solved["dir"] / "projects").iterdir():
        rep = proj / "reports" / "orchestrator" / "phase2_one_shot.json"
        if not rep.is_file():
            continue
        blob = rep.read_text(errors="replace")
        # Named-file assertions DECAY. The first version of this listed four
        # modules by name; three were then deleted, so three quarters of it
        # became a condition that cannot be false — a check that reads as
        # protection and stops anything. What it was actually guarding is that
        # the solve path never reaches a BENCHMARK-SPECIFIC program, so assert
        # the property: no prefixed module name appears in the run's own record.
        # This keeps working when someone adds `cvdp_something_new.py` tomorrow,
        # which a fixed list never would.
        offenders = re.findall(
            r"\b((?:cvdp|rtllm|verilogeval)_[a-z0-9_]+)\b", blob)
        assert not offenders, (
            f"{proj.name} went through benchmark-specific program(s) "
            f"{sorted(set(offenders))} — the solve path is supposed to be the "
            f"general one")


def test_a_reported_artefact_is_backed_by_a_passing_step(solved):
    """The false-success this caught: --solve reported 6/6 while 4 problems had
    rtl_gen BLOCKED and carried scaffolding. An artefact counts only when the
    step that owns it says PASS."""
    import benchmark_io_adapter as A
    for r in solved["report"]["results"]:
        if not r["ok"]:
            continue
        proj = solved["dir"] / "projects" / r["id"].replace("/", "_")
        v = A._rtl_gen_verdict(proj)
        assert v and v["status"] == "PASS", (
            f"{r['id']} was reported ok while rtl_gen said "
            f"{v['status'] if v else 'nothing'}")


def test_program_first_actually_ran_first(solved):
    """A solved problem must name the deterministic emitter that produced it.
    An artefact with no named producer means something wrote RTL that the
    program-first chain did not."""
    named = 0
    for proj in (solved["dir"] / "projects").iterdir():
        rep = proj / "reports" / "orchestrator" / "phase2_one_shot.json"
        if not rep.is_file():
            continue
        d = json.loads(rep.read_text(errors="replace"))
        last = [s for s in d.get("steps", []) if s.get("name") == "rtl_gen"]
        if last and last[-1].get("status") == "PASS":
            assert (last[-1].get("extras") or {}).get("deterministic_generator"), (
                f"{proj.name}: rtl_gen PASSed without naming its emitter")
            named += 1
    assert named, "no problem was solved deterministically — the chain is unwired"


def test_the_oracle_was_never_staged(solved):
    """§4.05 as a property of the run, not a rule someone remembered: the golden
    and the grading testbench must not appear anywhere in the project tree."""
    for proj in (solved["dir"] / "projects").iterdir():
        for f in proj.rglob("*"):
            if f.is_file():
                assert not f.name.endswith(("_ref.sv", "_test.sv")), (
                    f"oracle file {f} was staged into the project")
