#!/usr/bin/env python3
"""Steps 25 / 26 — artefacts the step produces that nothing verified.

`required_outputs` is ALL-of-N (PR #455): every declared entry must be present
or the step's PASS-tier verdict is downgraded. An artefact the step PRODUCES and
that its own verdict is READ FROM, but which no step declares, is verified by
nothing.

TWO such artefacts, both confirmed present on the real completed run
`campaign_pr427/spm/converge_ihp-sg13g2` (pure-digital standard cell — both are
digital-flow artefacts):

  step 25  reports/phase3/em.json                        293 B
  step 26  reports/phase3/antenna.json                   236 B

These are the MEASUREMENTS `phase3_one_shot_runner` reads back via
`_read_verdict()` as those steps' sign-off evidence — the step's verdict came
from a file nothing checked was there.

SATISFIABILITY is the constraint on adding an entry: a declaration a real run
cannot meet manufactures red. Each is paired with an artefact ALREADY declared,
in the same emitter branch:

  * `_emit_ir_em_reports` writes em.rpt and em.json inside one `if has_em:`
  * both `_emit_antenna_report` branches write antenna.rpt and antenna.json
    together and return True only there

The tests below assert the PAIRING property (what makes the entry satisfiable),
not that a particular string appears in a file.

WHAT IT COSTS — measured over EVERY tracked root (`git ls-files benchmark-data`,
not just `benchmark-data/ic`): ZERO. No root carries `em.rpt` without `em.json`
(12 vs 13), and none carries `antenna.rpt` without `antenna.json` (13 vs 14).
The newly-MISSING set is empty for both, so no published run changes verdict.

WITHDRAWN FROM THIS CHANGE — step 23's two multi-corner STANCE files
(`multi_corner_spef_stance.json`, `mcorner_ocv_stance.json`). They belong in
`required_outputs` on the merits, but their cost is NOT zero and the original
count understated it. Re-measured over every tracked root: stance files in 7,
the already-declared `post_route_timing.rpt` in 8, and the newly-MISSING set is
SIX roots, not two — `benchmark-data/ic/{caravel_user_project,subservient}` PLUS
`benchmark-data/evaluation/phase1_parity/{espi,lpc/phase3,mdio,sgmii}`, which
were excluded only because the first count stopped at `benchmark-data/ic`.
Six of the eight roots that carry the step's existing artefact would start
reporting MISSING. That is a separate decision; `test_d1_step23_stance_files_
are_not_declared_here` pins the withdrawal so it cannot drift back in silently.

DIRECTION-1 GUARDS (`test_d1_*`) hold on the pre-fix tree too.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
_PLUGIN = _PROGRAMS.parent
_FLOW = _PLUGIN / "flow" / "phase1_phase2_phase3.yaml"
sys.path.insert(0, str(_PROGRAMS))

_RUNNER_SRC = (_PROGRAMS / "phase3_one_shot_runner.py").read_text(
    errors="replace")


def _json_write(body: str, path_expr: str) -> int:
    """Offset of the write of `path_expr` in `body`, in EITHER spelling.

    A declared report destination can be written directly, `p.write_text(x)`,
    or through the atomic-artefact helper, `_aa.write_text(p, x)` — the form
    vibe-ic#1082 introduced so a crashed run cannot leave a half-written file
    under the FINAL name that the next reader cannot tell from a complete one.

    Both are the same write. Matching only the first spelling made these tests
    fail on a tree that had become MORE correct: measured on the 28-PR batch
    `cb7a67626`, the em.json and antenna.json writes had moved to
    `_aa.write_text(...)` and this module reported two failures for a change
    that fixed a real crash-safety defect.

    The path expression stays anchored in both alternatives, so this is not a
    loosening: a write of some OTHER file still does not satisfy it, and a
    branch that writes nothing still returns -1. Whitespace around `/` is
    tolerated because that is formatting, not meaning.

    Returns -1 when absent, so callers can assert presence AND ordering.
    """
    # Built by splitting on `/` rather than post-processing `re.escape`'s
    # output: whether that escapes a plain space is version-dependent (this
    # interpreter yields `\ /\ `, others yield ` / `), and a helper that
    # silently stops matching on a different Python is the kind of check that
    # passes for the wrong reason.
    anchor = r"\s*/\s*".join(re.escape(p.strip()) for p in path_expr.split("/"))
    pat = re.compile(
        r"\(\s*" + anchor + r"\s*\)\.write_text"      # (p).write_text(x)
        r"|_aa\.write_text\(\s*" + anchor             # _aa.write_text(p, x)
    )
    m = pat.search(body)
    return m.start() if m else -1


def _json_write_count(body: str, path_expr: str) -> int:
    """How many times `path_expr` is written in `body`, either spelling.

    Separate from `_json_write` because the antenna emitter has TWO success
    branches and the property is that BOTH write the pair — a count, not a
    presence. Same anchoring, same tolerance, so the two cannot drift apart.
    """
    anchor = r"\s*/\s*".join(re.escape(p.strip()) for p in path_expr.split("/"))
    pat = re.compile(
        r"\(\s*" + anchor + r"\s*\)\.write_text"
        r"|_aa\.write_text\(\s*" + anchor
    )
    return len(pat.findall(body))


def _steps():
    import yaml  # noqa: WPS433
    doc = yaml.safe_load(_FLOW.read_text(errors="replace"))
    steps = doc.get("steps") or doc.get("flow") or []
    return {str(s.get("id")): s for s in steps if isinstance(s, dict)}


def _required(step_id: str):
    return list(_steps()[step_id].get("required_outputs") or [])


# ===========================================================================
# The artefacts the step's own verdict is read from are declared
# ===========================================================================
@pytest.mark.parametrize("step_id,path", [
    ("25", "reports/phase3/em.json"),
    ("26", "reports/phase3/antenna.json"),
])
def test_produced_evidence_is_declared(step_id, path):
    assert path in _required(step_id), (
        f"step {step_id} produces {path} and reads its verdict from it, but no "
        f"step declares it — required_outputs verifies nothing about it")


@pytest.mark.parametrize("path", [
    "reports/phase3/em.json",
    "reports/phase3/antenna.json",
])
def test_the_runner_reads_its_verdict_from_the_declared_file(path):
    """These are not incidental files: `_read_verdict` is how the runner
    decides the step's outcome."""
    name = Path(path).name
    assert re.search(rf'_read_verdict\(\s*rpt3\s*/\s*"{re.escape(name)}"',
                     _RUNNER_SRC), (
        f"{path} is no longer the runner's verdict source — re-check the "
        f"declaration")


# ===========================================================================
# SATISFIABILITY — the pairing that makes each entry meetable
# ===========================================================================
def test_em_json_is_written_in_the_same_branch_as_em_rpt(tmp_path):
    """Drive the emitter's own JSON-writing statement rather than asserting a
    substring: build the pair the way `_emit_ir_em_reports` does and confirm
    both land together."""
    src = _RUNNER_SRC
    # The two writes must live inside one `if has_em:` branch, i.e. between
    # `em_ok = False` and `em_ok = True` there is exactly one branch guard.
    body = src[src.index("    em_ok = False"):src.index("    return ir_ok, em_ok")]
    assert body.count("if has_em:") == 1, body[:200]
    assert "em_rpt.write_text(body)" in body
    j = _json_write(body, 'em_rpt.parent / "em.json"')
    assert j >= 0, (
        "em.json is not written in the same branch as em.rpt, so the step's "
        "declared verdict source can be absent on a run that emitted the "
        "report — in either spelling, direct or atomic")
    assert body.index("em_rpt.write_text(body)") < j
    assert "em_ok = True" in body


def test_antenna_json_is_written_wherever_antenna_rpt_is():
    """`_emit_antenna_report` has two success branches; both must write the
    pair, or the declaration is unsatisfiable on one of them."""
    start = _RUNNER_SRC.index("def _emit_antenna_report(")
    end = _RUNNER_SRC.index("def _parse_spef_caps(")
    body = _RUNNER_SRC[start:end]
    assert body.count("antenna_rpt.write_text(") == 2, body.count(
        "antenna_rpt.write_text(")
    n = _json_write_count(body, 'antenna_rpt.parent / "antenna.json"')
    assert n == 2, (
        f"both _emit_antenna_report success branches must write antenna.json "
        f"beside antenna.rpt; found {n} write(s) in either spelling")


def _gate_commands(step: dict):
    """Every `program_exit_zero` command string in a step's gate, at any
    nesting (`all_of`, `optional_program_exit_zero`, mapping form)."""
    out = []

    def walk(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if k.endswith("program_exit_zero"):
                    out.append(v if isinstance(v, str)
                               else str(v.get("command", "")))
                else:
                    walk(v)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(step.get("gate") or {})
    return out


def test_every_declared_output_of_these_steps_has_a_producer():
    """The rule an added entry must satisfy: something WRITES it. A
    declaration with no producer is the step-23 post_route_summary.json defect
    PR #473 fixed — the file was named in the flow and by nothing else.

    A mention in the flow is NOT a producer, and neither is a mention in a
    comment. The two accepted producers are: the phase-3 runner CONSTRUCTING
    that path (`<dir> / "<name>"` — how it builds every artefact path), or this
    step's own gate passing the path to `--json`, which the wrappers now
    forward.

    LIMIT of this test, stated rather than implied: it proves a producer
    EXISTS, not that it runs on every path. Satisfiability on real runs is
    measured separately — see the corpus counts in this module's docstring.
    """
    steps = _steps()
    for step_id in ("23", "25", "26"):
        gate_json_targets = set()
        for cmd in _gate_commands(steps[step_id]):
            toks = cmd.split()
            gate_json_targets.update(
                toks[i + 1] for i, t in enumerate(toks) if t == "--json")
        for entry in _required(step_id):
            name = Path(entry).name
            built_by_runner = re.search(
                rf'/\s*f?["\'][^"\'\n]*{re.escape(name)}["\']', _RUNNER_SRC)
            assert built_by_runner or entry in gate_json_targets, (
                f"step {step_id} declares {entry} but neither the runner "
                f"builds that path nor does this step's gate produce it "
                f"via --json")


# ===========================================================================
# DIRECTION-1 GUARDS — hold on the pre-fix tree too
# ===========================================================================
@pytest.mark.parametrize("step_id,path", [
    ("23", "phase3/stage3/sta/post_route_timing.rpt"),
    ("23", "reports/phase3/sta/post_route_summary.json"),
    ("25", "reports/phase3/em.rpt"),
    ("26", "reports/phase3/antenna.rpt"),
])
def test_d1_the_existing_declarations_are_untouched(step_id, path):
    assert path in _required(step_id)


@pytest.mark.parametrize("step_id,path", [
    # Conditional on the PDK shipping distinct ss/ff process libraries.
    ("23", "phase3/stage3/sta/sta_mcorner_ocv.rpt"),
    # Conditional on a non-empty SPEF; extraction has a documented waiver.
    ("23", "phase3/stage3/sta/sta_spef_based.rpt"),
])
def test_d1_conditional_artefacts_are_not_declared(step_id, path):
    """Declaring a transient or a conditional artefact manufactures a false
    MISSING — the failure mode the ALL-of-N rule makes expensive."""
    assert path not in _required(step_id), (
        f"{path} is not produced on every real run; declaring it creates a "
        f"false MISSING")


@pytest.mark.parametrize("path", [
    "reports/phase3/multi_corner_spef_stance.json",
    "reports/phase3/mcorner_ocv_stance.json",
])
def test_d1_step23_stance_files_are_not_declared_here(path):
    """WITHDRAWN, deliberately — pinned so it cannot drift back in unnoticed.

    Declaring these makes 6 of the 8 tracked roots that carry step 23's
    already-declared `post_route_timing.rpt` report MISSING (see this module's
    docstring for the enumeration). Landing that needs its own decision with
    that number stated, not a ride-along on a batch whose other entries cost
    nothing.
    """
    assert path not in _required("23"), (
        f"{path} was re-added to step 23 without the 6-root cost being "
        f"restated — see the module docstring")


def test_d1_required_outputs_stay_all_of_n():
    """The semantics the additions rely on. ` OR ` inside ONE entry is the
    any-of spelling; the LIST is all-of."""
    src = (_PROGRAMS / "flow_compliance_check.py").read_text(errors="replace")
    assert "EACH declared entry must be satisfied" in src
    for step_id in ("23", "25", "26"):
        for entry in _required(step_id):
            assert " OR " not in entry, (
                f"step {step_id} entry {entry} is an any-of alternation; the "
                f"additions here assume plain all-of entries")
