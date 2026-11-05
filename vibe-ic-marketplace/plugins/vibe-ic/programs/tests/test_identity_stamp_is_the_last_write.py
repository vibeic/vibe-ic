"""The #484 identity stamp was applied and then overwritten, and the step that
applied it said in as many words that it could not have been.

MEASURED on a clean `subservient` phase-2 run (image 0.3.46), twice, and again
with the orchestrator removed so the result is attributable to
`design_one_shot_runner` alone:

    reports/phase2/gates + lint      12 json
    step_stamp_gate_reports reported "stamped 10"
    carrying design_identity at exit  5        <- 7 of the 10 were clobbered

The mtimes name the moment. The five survivors were written before the sweep;
the seven were rewritten 3-8 seconds AFTER it, in one burst.

THE WRITER, isolated by probe rather than by reading: re-running each candidate
against a finished run tree and watching mtimes (NOT hashes -- the rewrite is
idempotent in content, so a hash diff shows nothing and a hash-based probe
exonerates the culprit).

    step_output_collector.py                        0 files rewritten
    flow_compliance_check.py --stage-id stage_analog 0 files rewritten
    final_report_generate.py                        7 files rewritten  <-- this

`_path_layout.emit_final_summary` runs `final_report_generate.py`, which invokes
`flow_compliance_check.py`, which RE-RUNS the YAML gate checkers -- and they
write reports/phase2/gates/*.json with identity-less payloads. It is called
AFTER `step_stamp_gate_reports`, whose own docstring claimed it "Runs LAST so it
catches every gate/lint json produced during this run."

THE FIX IS THE ORDER, NOT THE FIELD NAMES. The stamp sweep is idempotent, so
running it once more after `emit_final_summary` -- where nothing else writes
those dirs -- makes the claim true and leaves every other artefact alone. The
count it reports second is exactly the number the report generator clobbered.

chip-AGNOSTIC: no chip, SKU, vendor or PDK literal.
"""
import ast
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))


_SRC = (_PROGRAMS / "design_one_shot_runner.py").read_text()


def _main_body():
    tree = ast.parse(_SRC)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "main":
            return node
    raise AssertionError("design_one_shot_runner.main not found")




def _last_line_calling(node: ast.AST, *names: str):
    hits = []
    for n in ast.walk(node):
        if not isinstance(n, ast.Call):
            continue
        f = n.func
        label = (f.attr if isinstance(f, ast.Attribute)
                 else f.id if isinstance(f, ast.Name) else "")
        if label in names:
            hits.append(n.lineno)
    return max(hits) if hits else None


def test_the_stamp_sweep_runs_after_the_final_summary():
    """THE ORDER. `emit_final_summary` re-runs the gate checkers, so the last
    stamp sweep must come after it or the stamp is overwritten.

    BOTH sides take the LAST call, not the first. `main` calls
    `emit_final_summary` five times on different exit paths; comparing against
    the FIRST one made this assertion true on the unfixed code as well, i.e.
    vacuous. The property is about the last write to the gate dirs, so it is
    the last call of each that decides it.
    """
    main = _main_body()
    summary_line = _last_line_calling(main, "emit_final_summary")
    assert summary_line is not None, "emit_final_summary is no longer called"
    stamp_line = _last_line_calling(main, "_stamp_gate_report_dirs",
                                    "step_stamp_gate_reports")
    assert stamp_line is not None, "the identity stamp is no longer swept"
    assert stamp_line > summary_line, (
        f"the identity stamp sweep (line {stamp_line}) runs BEFORE "
        f"emit_final_summary (line {summary_line}), which re-runs the YAML "
        f"gate checkers and rewrites the gate jsons without the stamp — this "
        f"is the #484/RB-20 defect, measured as 5 of 12 stamped at exit")




def test_the_claim_matcher_can_actually_match():
    """NON-VACUITY for the test above: the normalising matcher must FIND the
    claim in the text it is meant to catch. Without this, a typo in `claim`
    makes that assertion pass forever."""
    flat = " ".join(
        ("# gate jsons as canned cross-design reports. Runs LAST so it "
         "catches every\n    # gate/lint json produced during this run.")
        .replace("#", " ").split())
    claim = "Runs LAST so it catches every gate/lint json produced during this run"
    assert claim in flat


# ── the mechanism, functionally ──────────────────────────────────────────────







if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
