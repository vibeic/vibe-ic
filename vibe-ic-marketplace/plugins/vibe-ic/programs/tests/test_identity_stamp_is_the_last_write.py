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
import json
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import design_one_shot_runner as P2  # noqa: E402

_SRC = (_PROGRAMS / "design_one_shot_runner.py").read_text()


def _main_body():
    tree = ast.parse(_SRC)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "main":
            return node
    raise AssertionError("design_one_shot_runner.main not found")


def _first_line_calling(node: ast.AST, *names: str):
    """Lowest line number in `node` at which any of `names` is CALLED."""
    hits = []
    for n in ast.walk(node):
        if not isinstance(n, ast.Call):
            continue
        f = n.func
        label = (f.attr if isinstance(f, ast.Attribute)
                 else f.id if isinstance(f, ast.Name) else "")
        if label in names:
            hits.append(n.lineno)
    return min(hits) if hits else None


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


def test_the_source_no_longer_claims_a_last_write_it_does_not_have():
    """An artefact must not contradict its own message. The old comment said
    the first sweep "Runs LAST so it catches every gate/lint json produced
    during this run"; the mtimes said it did not.

    The claim is matched over WHITESPACE-NORMALISED source. The first version
    of this test matched the raw text and was vacuous on both arms, because the
    sentence is wrapped across two comment lines and the literal never occurred
    in either file. A re-wrap must not be able to silence this again.
    """
    flat = " ".join(_SRC.replace("#", " ").split())
    claim = "Runs LAST so it catches every gate/lint json produced during this run"
    assert claim not in flat, (
        "the superseded claim is back: the first sweep is NOT the last write "
        "to reports/phase2/gates — final_report_generate.py writes after it")
    assert P2.step_stamp_gate_reports.__doc__, \
        "step_stamp_gate_reports lost its docstring"


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

def _seed_gate(project: Path, name: str, payload) -> Path:
    d = project / "reports" / "phase2" / "gates"
    d.mkdir(parents=True, exist_ok=True)
    fp = d / f"{name}.json"
    fp.write_text(json.dumps(payload) + "\n")
    return fp


def test_a_clobbered_stamp_is_restored_by_a_second_sweep(tmp_path):
    """The sweep is idempotent, so running it again is free for a file nobody
    touched — and is the whole repair for one that was rewritten."""
    proj = tmp_path / "proj"
    gd = P2._pl.generated_docs_dir(proj)
    gd.mkdir(parents=True)
    (gd / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({"top_module": "t"}))

    kept = _seed_gate(proj, "kept", {"verdict": "PASS"})
    clobbered = _seed_gate(proj, "clobbered", {"verdict": "PASS"})

    first = P2._stamp_gate_report_dirs(proj)
    assert sorted(Path(p).name for p in first) == ["clobbered.json", "kept.json"]
    assert "design_identity" in json.loads(kept.read_text())

    # `final_report_generate.py` re-runs the checker, which rewrites the file
    # with an identity-less payload. This is the measured event.
    clobbered.write_text(json.dumps({"verdict": "PASS"}) + "\n")
    assert "design_identity" not in json.loads(clobbered.read_text())

    second = P2._stamp_gate_report_dirs(proj)
    # ONLY the clobbered one is rewritten — the count is the damage report.
    assert [Path(p).name for p in second] == ["clobbered.json"]
    assert "design_identity" in json.loads(clobbered.read_text())
    assert "design_identity" in json.loads(kept.read_text())


def test_a_second_sweep_over_an_untouched_tree_reports_nothing(tmp_path):
    """NON-VACUITY / NO-LEAK. If the second sweep re-stamped unconditionally,
    its count would be noise instead of a measurement, and this test would be
    unable to tell a clobbered run from a clean one."""
    proj = tmp_path / "proj"
    gd = P2._pl.generated_docs_dir(proj)
    gd.mkdir(parents=True)
    (gd / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({"top_module": "t"}))
    _seed_gate(proj, "a", {"verdict": "PASS"})
    _seed_gate(proj, "b", {"verdict": "FAIL"})
    assert len(P2._stamp_gate_report_dirs(proj)) == 2
    assert P2._stamp_gate_report_dirs(proj) == []


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
