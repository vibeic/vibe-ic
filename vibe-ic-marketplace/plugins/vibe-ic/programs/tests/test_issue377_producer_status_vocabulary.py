#!/usr/bin/env python3
"""vibe-ic#377 — the producer `extraction_status` vocabulary.

TWO THINGS ARE PINNED HERE, and they are the two halves of one measurement.

(1) THE NON-FUSION INVARIANT.
    `l_doc_consumer_contract.is_extraction_claimed` and the L16/L17/L18 gates'
    local `_STATUS_FOUND_NOTHING` set read the SAME producer field and look
    like two spellings of one concept. They are not. They are two different
    binary projections of a THREE-valued producer state, and the property that
    proves it is a state on which BOTH are False. These tests assert that
    property directly on the real functions, so a future "unification" that
    makes one the negation of the other reddens here instead of silently
    turning an honest empty layer into a blocking assertion.

(2) THE ARM THAT VOCABULARY WAS DECLARED FOR AND NEVER WIRED.
    `l16_compliance_properties_actionable_check` defined `_STATUS_FOUND_NOTHING`
    and never loaded it. E2 catches "status claims success, payload empty";
    the opposite direction — "status says it found nothing, payload populated"
    — went unchecked, while both sibling gates in the same family check it.

NEGATIVE CONTROL IS THE POINT: every rail is asserted in both directions.
All fixtures are SYNTHESIZED neutral data. No design/PDK/vendor name appears.
"""
from __future__ import annotations

import ast
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parent.parent
PROG = _PROGRAMS / "l16_compliance_properties_actionable_check.py"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, _PROGRAMS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(name, mod)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# (1) The non-fusion invariant
# ---------------------------------------------------------------------------
def test_the_two_status_predicates_are_not_complements():
    """The load-bearing property: a state on which BOTH answer False.

    If someone "unifies" the two by making `_STATUS_FOUND_NOTHING` the
    complement of `is_extraction_claimed`, NOT_YET_EXTRACTED must become True
    for one of them and this reddens.
    """
    contract = _load("l_doc_consumer_contract")
    g16 = _load("l16_compliance_properties_actionable_check")

    doc = {"extraction_status": "NOT_YET_EXTRACTED"}
    claimed = contract.is_extraction_claimed(doc)
    found_nothing = "NOT_YET_EXTRACTED" in g16._STATUS_FOUND_NOTHING

    assert claimed is False, (
        "is_extraction_claimed must treat an un-run skeleton as asserting "
        "nothing")
    assert found_nothing is False, (
        "_STATUS_FOUND_NOTHING must NOT contain NOT_YET_EXTRACTED: 'has not "
        "run yet' is not 'ran and reported empty'")
    assert claimed == found_nothing, (
        "both are False on this state, which is what makes them two "
        "projections of a 3-valued space rather than complements")


def test_ran_and_found_nothing_is_true_for_both_questions():
    """The overlap is an answer to two questions, not drift.

    EXTRACTION_FOUND_NOTHING means extraction RAN (so it is a claim about the
    run) AND reported empty (so the payload should be empty). Both predicates
    saying True is correct; a "fix" that makes one False to match the other
    would break the arm that depends on it.
    """
    contract = _load("l_doc_consumer_contract")
    g16 = _load("l16_compliance_properties_actionable_check")

    doc = {"extraction_status": "EXTRACTION_FOUND_NOTHING"}
    assert contract.is_extraction_claimed(doc) is True
    assert "EXTRACTION_FOUND_NOTHING" in g16._STATUS_FOUND_NOTHING


def test_the_three_local_copies_of_the_vocabulary_have_not_drifted():
    """L16/L17/L18 each hand-roll the set. They are equal today; if a future
    edit changes one, this names the drift instead of letting a gate quietly
    stop recognising a token its siblings still recognise."""
    g16 = _load("l16_compliance_properties_actionable_check")
    g17 = _load("l17_channel_catalog_consumer_contract_check")
    g18 = _load("l18_interconnect_topology_factuality_check")
    assert g16._STATUS_FOUND_NOTHING == g17._STATUS_FOUND_NOTHING
    assert g16._STATUS_FOUND_NOTHING == g18._STATUS_FOUND_NOTHING


def test_the_two_predicates_are_never_applied_to_the_same_document():
    """AST, not grep — a grep miss does not prove a call site absent.

    The disjointness is what makes "fuse them" unjustifiable: no document is
    read by both, so no measurement of their disagreement is possible on real
    data. If a future change imports one into the other's gate family, this
    reddens and the fusion question must be re-measured rather than assumed.
    """
    claimed_in: set[str] = set()
    found_nothing_in: set[str] = set()
    for path in sorted(_PROGRAMS.glob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError:                                   # pragma: no cover
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                if node.id == "is_extraction_claimed":
                    claimed_in.add(path.stem)
                elif node.id == "_STATUS_FOUND_NOTHING":
                    found_nothing_in.add(path.stem)

    assert claimed_in, "expected at least one consumer of is_extraction_claimed"
    assert found_nothing_in, "expected at least one consumer of the local set"
    overlap = claimed_in & found_nothing_in
    assert not overlap, (
        f"{sorted(overlap)} now reads BOTH producer-status predicates. They "
        "answer different questions about a 3-valued state; a module using "
        "both must say which question each call is asking.")


# ---------------------------------------------------------------------------
# (2) L16 E4 — fixtures
# ---------------------------------------------------------------------------
def _mk_project(tmp: Path, l16: dict) -> Path:
    """A neutral design: 4 declared ports, two registers, one clock domain."""
    proj = tmp / "run"
    gd = proj / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({
        "top_module": "widget_top",
        "ports": [
            {"name": "core_clk", "direction": "input", "width": 1},
            {"name": "core_rst_n", "direction": "input", "width": 1},
            {"name": "load_enable", "direction": "input", "width": 1},
            {"name": "result_valid", "direction": "output", "width": 1},
        ],
        "clock_domains": [{"name": "core_clk"}],
    }))
    (gd / "L4_REGMAP.json").write_text(json.dumps({
        "registers": [{"name": "ctrl_mode"}, {"name": "status_flags"}]}))
    (gd / "L16_COMPLIANCE_PROPERTIES.json").write_text(json.dumps(l16))
    return proj


def _mk_programs_dir(tmp: Path) -> Path:
    pdir = tmp / "programs_stub"
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "professional_tb_gen.py").write_text(
        "from pathlib import Path\n"
        "def build_assertions(gd):\n"
        "    return (gd / 'L16_COMPLIANCE_PROPERTIES.json').read_text()\n")
    return pdir


# Anchored on a port this synthetic design declares, so the property is
# ACTIONABLE and the run cannot fail for an unrelated reason.
_ANCHORED = [{"english_form": "load_enable must be stable while busy",
              "signals": ["load_enable"]}]


def _run(project: Path, pdir: Path, *extra: str):
    return subprocess.run(
        [sys.executable, str(PROG), str(project), "--programs-dir", str(pdir),
         *extra], capture_output=True, text=True)


def _cats(cp) -> set[str]:
    return {f["category"] for f in json.loads(cp.stdout)["findings"]}


def test_NEGATIVE_found_nothing_with_a_populated_payload_is_reported(tmp_path):
    """The measured defect: the emitter wrote 'I found nothing' and a payload
    in the same emission, and the gate said nothing at all."""
    proj = _mk_project(tmp_path, {
        "extraction_status": "EXTRACTION_FOUND_NOTHING",
        "extraction_evidence": {},
        "emitted_by": "some_extractor v0",
        "fields": {"properties": _ANCHORED}})
    r = _run(proj, _mk_programs_dir(tmp_path))
    assert "PAYLOAD_WITHOUT_EXTRACTION" in _cats(r), r.stdout
    assert r.returncode == 1, r.stdout


def test_POSITIVE_found_nothing_with_an_empty_payload_still_passes(tmp_path):
    """The honesty arm must survive. A layer that extracted nothing and says
    so, holding nothing, is truthful — punishing it pushes producers toward
    inventing filler, which is the defect this gate exists to stop."""
    proj = _mk_project(tmp_path, {
        "extraction_status": "EXTRACTION_FOUND_NOTHING",
        "fields": {"properties": []}})
    r = _run(proj, _mk_programs_dir(tmp_path))
    assert r.returncode == 0, r.stdout
    assert "HONEST_EMPTY" in _cats(r)
    assert "PAYLOAD_WITHOUT_EXTRACTION" not in _cats(r)


def test_POSITIVE_a_successful_status_with_a_payload_is_not_touched(tmp_path):
    """The normal case must not acquire the new finding."""
    proj = _mk_project(tmp_path, {
        "extraction_status": "EXTRACTED",
        "extraction_evidence": {"line": 1},
        "fields": {"properties": _ANCHORED}})
    r = _run(proj, _mk_programs_dir(tmp_path))
    assert "PAYLOAD_WITHOUT_EXTRACTION" not in _cats(r), r.stdout
    assert r.returncode == 0, r.stdout


def test_POSITIVE_an_unrun_skeleton_with_a_payload_is_not_touched(tmp_path):
    """The third state, guarded end-to-end. A skeleton whose extraction has
    not run yet is not contradicting itself by carrying content — that is the
    exact case a fusion of the two predicates would misclassify."""
    proj = _mk_project(tmp_path, {
        "extraction_status": "NOT_YET_EXTRACTED",
        "fields": {"properties": _ANCHORED}})
    r = _run(proj, _mk_programs_dir(tmp_path))
    assert "PAYLOAD_WITHOUT_EXTRACTION" not in _cats(r), r.stdout
    assert r.returncode == 0, r.stdout


def test_the_finding_makes_no_provenance_claim(tmp_path):
    """L17-E1 / L18-E4 word this shape as "template content from an unrelated
    protocol". That claim was measured FALSE on the published parity corpus.
    E4 must state the self-contradiction and nothing more, or the
    over-reaching verdict removed one layer over comes back here."""
    proj = _mk_project(tmp_path, {
        "extraction_status": "EXTRACTION_FOUND_NOTHING",
        "fields": {"properties": _ANCHORED}})
    r = _run(proj, _mk_programs_dir(tmp_path))
    finding = next(f for f in json.loads(r.stdout)["findings"]
                   if f["category"] == "PAYLOAD_WITHOUT_EXTRACTION")
    message = finding["message"].lower()
    for forbidden in ("unrelated protocol", "template content"):
        assert forbidden not in message, (
            f"E4 must not assert provenance; found {forbidden!r} in: "
            f"{finding['message']}")
    # ...and it must disclose the two numbers it read.
    assert finding["evidence"]["properties_found"] == len(_ANCHORED)
    assert finding["evidence"]["status"] == "EXTRACTION_FOUND_NOTHING"


def test_advisory_mode_still_downgrades_the_new_finding(tmp_path):
    """The gate is wired `advisory_program_exit_zero`, so the new ERROR must
    not become a way to fail a flow step that never opted into blocking."""
    proj = _mk_project(tmp_path, {
        "extraction_status": "EXTRACTION_FOUND_NOTHING",
        "fields": {"properties": _ANCHORED}})
    pdir = _mk_programs_dir(tmp_path)
    blocking = _run(proj, pdir)
    advisory = _run(proj, pdir, "--advisory")
    assert blocking.returncode == 1
    assert advisory.returncode == 0
    assert _cats(blocking) == _cats(advisory)


def test_the_local_vocabulary_is_actually_loaded_now(tmp_path):
    """The set was defined with ZERO loads — an ornament, not a check. A
    definition nothing reads is how a gate keeps a clean record by examining
    nothing. Asserted on the AST, not on the presence of a comment."""
    tree = ast.parse(PROG.read_text(encoding="utf-8"))
    loads = [n.lineno for n in ast.walk(tree)
             if isinstance(n, ast.Name) and n.id == "_STATUS_FOUND_NOTHING"
             and isinstance(n.ctx, ast.Load)]
    assert loads, (
        "_STATUS_FOUND_NOTHING is defined in this gate and never read; either "
        "wire it or delete it, but do not ship a vocabulary that checks "
        "nothing")
