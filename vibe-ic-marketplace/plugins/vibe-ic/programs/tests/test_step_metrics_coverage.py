"""The gated number must be the number the tool computed — and both readings
must agree. vibe-ic#1080, consumption half.

WHAT WAS ACTUALLY WRONG
=======================
`step_metrics.py` shipped the schema and an emitter, and its own header said it
"wires ONE gate (`coverage_metric_check`) as a worked example". Measured on
v1.10.92 that sentence is wrong in both halves:

  * `coverage_metric_check` is named NOWHERE in `flow/phase1_phase2_phase3.yaml`
    and IS listed in `programs/gate_is_wired_baseline.json` under `unwired`
    ("gates no automatic verdict consults"). The gate the docstring offers as
    the worked example is the one gate that is not wired.
  * The only emitter a real flow run reaches is `magic_illegal_overlap_check`
    (step 31) — and reaching an emitter is not the same as consuming it.

The number that matters is CONSUMPTION: before this change, ZERO of the 62
gate-carrying steps decided anything from a tool-computed number.
`git grep -c step_metrics -- "*phase3_one_shot_runner.py"` returned 0, so the
one-shot runner — which implements the phase-3 step verdicts — never called it.

THE CONTRACT THESE TESTS PIN
============================
Both readings run. `reconcile` does NOT pick a winner:

    AGREE       -> the step passes on the number
    DISAGREE    -> the step FAILS, and the message names BOTH numbers
    NO_METRIC   -> NOT silently green; the value is named a proxy
    PROSE_BLIND -> the parser matched nothing; the verdict is unaffected
                   because it no longer depends on the parser, and the dead
                   parser is named so nobody keeps trusting it
    NEITHER     -> UNDETERMINED, never zero

chip-AGNOSTIC: OpenROAD/TritonRoute log and metric grammar only.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

import step_metrics as sm            # noqa: E402
import phase3_one_shot_runner as R   # noqa: E402


def _tmp(prefix):
    # mkdtemp, not tmp_path: this image's pytest tmp_path carries a NEWLINE
    # (`/tmp/pytest-of-1000\ndesigner/...`), which splits any path handed to a
    # subprocess and produces failures that have nothing to do with the code.
    return Path(tempfile.mkdtemp(prefix=prefix))


# --------------------------------------------------------------------------
# The census — the remainder is COUNTED IN THE CODE, not described in a brief
# --------------------------------------------------------------------------
def test_declared_coverage_matches_the_tree():
    """Wiring a gate without declaring it fails. Un-wiring one fails too.

    This is what keeps the coverage number from rotting the way the module's
    own docstring did: it is re-derived from the flow plus the program sources
    on every run, and compared against the literals in `step_metrics`.
    """
    from flow_compliance_check import _find_flow_def
    rep = sm.coverage(_find_flow_def(), PROGRAMS)

    assert rep["gate_carrying"] == sm.GATE_CARRYING_STEPS
    assert tuple(rep["emitting"]) == tuple(sm.EMITTING_STEPS)
    assert tuple(rep["consuming"]) == tuple(sorted(sm.CONSUMING_STEPS))
    # The remainder is a NUMBER a reader can act on, not "the other 61".
    assert (len(rep["consuming"]) + len(rep["not_consuming"])
            == rep["gate_carrying"])


def test_the_census_cannot_count_its_own_prose():
    """A docstring mentioning `emit` must not register as a wired gate.

    The census is AST-based for exactly this reason — and this module's own
    header mentions both `emit` and `reconcile` several times.
    """
    d = _tmp("census_")
    (d / "talks_about_it.py").write_text(
        '"""This program calls step_metrics.emit(...) and reconcile(...)."""\n'
        "# emit(project, '9', {}) — a comment, not a call\n"
        "X = 'step_metrics.emit(1)'\n")
    assert sm._program_emits(d / "talks_about_it.py") is False
    assert sm._program_consumes(d / "talks_about_it.py") is False


def test_runner_consumers_are_declared_with_the_file_that_implements_them():
    """Step 21's verdict lives in the runner, not in a gate program, so it
    cannot be derived from the flow's `gate:` blob. It is declared with its
    file, and the declaration is only honoured if that file really reconciles.
    """
    for sid, fname in sm.CONSUMING_STEPS.items():
        assert (PROGRAMS / fname).is_file(), (sid, fname)
        assert sm._program_consumes(PROGRAMS / fname), (
            f"step {sid} is declared CONSUMING but {fname} never calls "
            f"step_metrics.reconcile — the declaration would be a claim with "
            f"nothing behind it")


# --------------------------------------------------------------------------
# The four directions, each on a CONSTRUCTED tree
# --------------------------------------------------------------------------
_LOG_CLEAN = ("[INFO DRT-0195] Start 3rd iteration.\n"
              "    Completing 100% with 0 violations.\n"
              "[INFO DRT-0199]   Number of violations = 0.\n"
              "[INFO DRT-0198] Complete detail routing.\n")


def _route_tree(metric, log=_LOG_CLEAN):
    d = _tmp("route_")
    # The on-disk log is load-bearing: `_drt_reading` falls back to it when the
    # captured stdout carried no DRT line, so a fixture that mangles only the
    # passed text has not changed the wording at all.
    (d / "openroad.log").write_text(log)
    if metric is not None:
        (d / R._PNR_METRICS).write_text(json.dumps({R._KEY_DRT: metric}))
    return d


def test_agree_passes():
    rec, _ = R._drt_reading(_route_tree(0), _LOG_CLEAN)
    assert rec.status == sm.AGREE
    assert rec.ok is True and rec.value == 0


def test_disagree_fails_and_names_both_numbers():
    rec, _ = R._drt_reading(_route_tree(7), _LOG_CLEAN)
    assert rec.status == sm.DISAGREE
    assert rec.ok is False, "a disagreement must FAIL, not resolve"
    assert rec.value is None, (
        "a caller that ignores .ok must get NO reading, never the wrong one "
        "of the two")
    assert rec.metric == 7 and rec.prose == 0
    assert "METRIC=7" in rec.detail and "LOG=0" in rec.detail, (
        "the failure must NAME BOTH numbers — that is the whole point of "
        "refusing to pick a winner")
    assert "will not choose between them" in rec.detail


def test_no_metric_is_not_silently_green():
    rec, _ = R._drt_reading(_route_tree(None), _LOG_CLEAN)
    assert rec.status == sm.NO_METRIC
    assert rec.status != sm.AGREE, "it must be DISTINGUISHABLE from agreement"
    assert "proxy" in rec.detail and "not the measurement" in rec.detail
    # and a caller that must not accept a proxy can refuse one
    assert sm.reconcile("x", None, 0, require_metric=True).ok is False


def test_wording_change_no_longer_reaches_the_verdict():
    """The failure mode the substrate exists to remove."""
    blind = _LOG_CLEAN.replace("Number of violations = 0.",
                               "Number of DRC violations = 0.") \
                      .replace("Completing 100% with", "Completed 100%,")
    # the OLD source of truth reads nothing at all off that log
    assert R._drt_final_violations(blind) is None
    rec, _ = R._drt_reading(_route_tree(0, blind), blind)
    assert rec.status == sm.PROSE_BLIND
    assert rec.ok is True and rec.value == 0, "verdict unaffected"


def test_neither_is_undetermined_never_zero():
    d = _tmp("none_")
    rec, _ = R._drt_reading(d, "global route only\n")
    assert rec.status == sm.NEITHER and rec.value is None
    assert not (rec.value is not None and rec.value > 0)


# --------------------------------------------------------------------------
# The supply side: a call site is not a metric file
# --------------------------------------------------------------------------
def test_emit_failure_is_loud(capsys):
    """MEASURED while wiring step 17: `check_placement_violations` is a LIST,
    `emit` correctly refused it, and a silent swallow left the gate exiting 0,
    the census reporting the step wired, and NO file on disk."""
    d = _tmp("loud_")
    assert sm.emit_best_effort(d, "17", {"bad": ["a", "list"]}) is None
    assert "EMIT FAILED" in capsys.readouterr().err
    assert not (d / "reports" / "metrics").exists()


@pytest.mark.parametrize("prog,step,build", [
    ("placement_legality_check.py", "17", "placed"),
    ("metal_fill_density_check.py", "34", "fill"),
])
def test_wired_program_actually_writes_a_metric_file(prog, step, build):
    """Runs the real program and looks for the FILE. Asserting the call site
    exists is what let step 17 look wired while emitting nothing."""
    proj = _tmp("emit_")
    pnr = proj / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True)
    if build == "placed":
        lines = ["VERSION 5.8 ;", "DESIGN top ;",
                 "UNITS DISTANCE MICRONS 1000 ;",
                 "DIEAREA ( 0 0 ) ( 100000 100000 ) ;", "COMPONENTS 3 ;"]
        lines += [f"    - U_{i} AND2X1 + PLACED ( {i*100} {i*200} ) N ;"
                  for i in range(3)]
        lines += ["END COMPONENTS", "END DESIGN"]
        (pnr / "placed.def").write_text("\n".join(lines) + "\n")
    else:
        (pnr / "routed.def").write_text("x" * 1000)
        (pnr / "filled.def").write_text("x" * 2000)

    r = subprocess.run([sys.executable, str(PROGRAMS / prog), str(proj)],
                       capture_output=True, text=True)
    assert "EMIT FAILED" not in r.stderr, r.stderr
    mf = proj / "reports" / "metrics" / f"{step}.json"
    assert mf.is_file(), f"{prog} declared wired but wrote no {mf.name}"
    doc = json.loads(mf.read_text())
    assert doc, "an empty metrics file is not an emission"
    assert all(k.startswith(f"{step}__") for k in doc), sorted(doc)
    assert sm.conformance_defects(proj) == []
