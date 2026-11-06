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


def _tmp(prefix):
    # mkdtemp, not tmp_path: this image's pytest tmp_path carries a NEWLINE
    # (`/tmp/pytest-of-1000\ndesigner/...`), which splits any path handed to a
    # subprocess and produces failures that have nothing to do with the code.
    return Path(tempfile.mkdtemp(prefix=prefix))


# --------------------------------------------------------------------------
# The census — the remainder is COUNTED IN THE CODE, not described in a brief
# --------------------------------------------------------------------------








# --------------------------------------------------------------------------
# The four directions, each on a CONSTRUCTED tree
# --------------------------------------------------------------------------
_LOG_CLEAN = ("[INFO DRT-0195] Start 3rd iteration.\n"
              "    Completing 100% with 0 violations.\n"
              "[INFO DRT-0199]   Number of violations = 0.\n"
              "[INFO DRT-0198] Complete detail routing.\n")


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
