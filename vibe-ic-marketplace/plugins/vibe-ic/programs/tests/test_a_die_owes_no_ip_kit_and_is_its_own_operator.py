"""Two rulings of 2026-09-20, both derived from an owner-attested `deliverable`.

R-0915 (1): **a DIE owes NO IP delivery set.** Step 37.5ip's producers build the
LEF/lib/Verilog/GDS kit and the six IP documents. Measured on spm x gf180mcuD,
DIE route (v1.22.10, run6): that kit cost 7278.5 s — the run's longest step by a
factor of two and a half — and `ip_release_docs_gen` then refused it anyway. The
step now stands down BY DECLARATION, with the declaration cited: the flow row via
37.5ip's own `delivery_declares` condition, and the runner channel (which
dispatches the two producers directly) via a typed N/A record.

R-0915 (2): **on a DIE with no operator template the die is its own operator
(37.5self).** There is no external slot to measure against — the operator
catalogue on disk is information, not a purchase — so the file that plays the
slot's part is the design's OWN declaration (`pad_signal_map` /
`pad_order_by_side`, written at step 0.5ic), measured by signal name against
the pins the design declares.

WHERE THE DESIGN DECLARED NO RING, THIS STEP DOES NOT GUESS AND DOES NOT PASS.
The ring is then generated at step 15.5ic, and reading that output from step 2
is the dependency `test_matrix_d5_deps_correct` refuses and cannot repair:
15.5ic already has step 2 in its own ancestry, so the edge is CIRCULAR
(measured, on the first cut of this change: `D5-MISSING-EDGE: step 2 reads
'reports/phase3/padring.json', declared as a required_output of step 15.5ic`).
The measurement is not lost — `pad_ring_check` (BTERM_WITHOUT_PAD) and
`pad_bterm_coincidence_check` (per net, geometric) make it at 15.5ic, where the
ring exists — so this step names them and reports UNDECIDED. Measured on run7:
the design declares neither key, and 15.5ic's own record carries
`n_ports_on_a_pad: 38`.

SUPERSEDED IN PART BY R-0915-101 (2026-09-21) — read the next paragraph before
the one above it. The paragraph above describes the DEFERRAL: a die that declared
no `pad_signal_map` was reported UNDECIDED / BLOCKED_BY_UPSTREAM and pointed at
step 15.5ic. That answer was not a verdict about the design's pad budget, and it
cost the whole IC path: `BLOCKED_BY_UPSTREAM` is not skip-eligible, so the P0
umbrella booked flow step 2 INCOMPLETE and step 4's 10/10 L10 oracles were voided
beneath it.

R-0915-101 rules that on a DIE the budget IS the die's own pad ring, and that the
design usually HAS stated that ring — in the pad-placement section of its own
L-documents, which is where `io_pad_chip_top_gen` already derives
`pad_order_by_side` and `SIGNAL_MAP` from at 15.5ic. `slot_pad_budget_check` now
derives it from that same source through the same reader and DECIDES. What
survives untouched is the law this file was written to protect, and each re-pinned
case below asserts it explicitly:

  * this step still reads NO artefact a later step produces — asserted on the
    reader itself (`LPP.DOC_DIRS` is design INPUT only) as well as on the report;
  * a DIE is still NEVER `NOT_APPLICABLE`;
  * a die that states its ring NOWHERE still does not pass — it is `UNDECIDED`
    with a NAMED finding, now classified `ZERO_DENOMINATOR` (a design-input gap)
    rather than `BLOCKED_BY_UPSTREAM` (a wait on a step that generates the ring
    FROM the declaration the design did not write).

The three case NAMES that say "deferred" are KEPT so the id set is stable across
this change; each docstring says what it now asserts.

A HARDMACRO still owes the IP set, and still budgets against an operator slot.
Both directions are tested here.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

import phase3_one_shot_runner as R  # noqa: E402
import slot_pad_budget_check as S  # noqa: E402
import flow_compliance_check as FCC  # noqa: E402
import verdict as V  # noqa: E402  the five-word step vocabulary (#2389)
import _flow_reason_taxonomy as _RT  # noqa: E402  the class -> tier map
import _l_doc_pad_placement as LPP  # noqa: E402  the ONE ring reader (R-0915-101)
import _tapeout_declaration as TD  # noqa: E402

RTL = """module spm #(parameter size = 32) (
  input clk, input rst, input [size-1:0] x, input y, output p);
endmodule
"""


def _declare(project: Path, deliverable: str, *, attested: bool = True,
             operator: dict | None = None, ring: dict | None = None) -> None:
    """Stage the design's answers + the merged declaration, as a run does."""
    prov = {"deliverable": {"answered_by": "owner" if attested else "agent",
                            "citation": "R-0915-95 — fixture"}}
    answers = {"answers": {"deliverable": deliverable, "top_cell": "spm"},
               "operator_template": operator or {"path": None, "slot": None},
               "answer_provenance": prov}
    p = project / "input" / "step_0_5ic_answers.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(answers))
    _answers = {"deliverable": deliverable, "top_cell": "spm"}
    if ring is not None:
        # THE DIE'S OWN SLOT FILE: the pad ring the design declares for
        # itself, in the two questions step 0.5ic asks about it.
        _answers["pad_signal_map"] = dict(ring)
        _sides = ("south", "east", "north", "west")
        _answers["pad_order_by_side"] = {
            s: [i for n, i in enumerate(ring) if n % 4 == k]
            for k, s in enumerate(_sides)}
    doc, _ = TD.merge_answers(TD.blank_declaration(), _answers)
    doc[TD.PROVENANCE_KEY] = prov
    d = project / TD.DECLARATION_REL
    d.parent.mkdir(parents=True, exist_ok=True)
    d.write_text(json.dumps(doc, indent=2))


def _ring_map(signals) -> dict:
    """{pad instance: the top-level port it brings out} — a signal map."""
    return {f"u_pad_{i}": s for i, s in enumerate(signals)}


_FULL_RING = ["VDD", "VSS", "clk", "rst", "y", "p"] + [f"x[{i}]" for i in range(32)]


def _project(tmp_path: Path, deliverable="DIE", *, ring=True, rtl=RTL,
             declaration: dict | None = None, ring_signals=None, **kw) -> Path:
    project = tmp_path
    _declare(project, deliverable,
             ring=(_ring_map(ring_signals if ring_signals is not None
                             else _FULL_RING) if ring else None), **kw)
    rtl_dir = project / Path(*S._RTL_DIR_REL)
    rtl_dir.mkdir(parents=True, exist_ok=True)
    (rtl_dir / "spm.v").write_text(rtl)
    if declaration is not None:
        d = project / "plugin_output" / "declaration.json"
        d.parent.mkdir(parents=True, exist_ok=True)
        d.write_text(json.dumps(declaration))
    return project


def _run_budget(project: Path, *extra) -> tuple[int, dict]:
    out = project / "budget.json"
    rc = subprocess.run(
        [sys.executable, str(PROGRAMS / "slot_pad_budget_check.py"),
         str(project), "--json", str(out), *extra],
        capture_output=True, text=True).returncode
    return rc, json.loads(out.read_text())


# ---------------------------------------------------------------- ruling (1)

def test_an_owner_attested_die_stands_the_ip_producers_down_with_the_citation(tmp_path):
    project = _project(tmp_path)
    na, cited, evidence = R._ip_delivery_declared_na(project)
    assert na is True
    assert "answers.deliverable='DIE'" in cited and "owner" in cited
    assert evidence["declaration_path"] == TD.DECLARATION_REL
    row = R.step_digital_hardmacro_gen(project)
    # #2389 REDUCED THE STEP VOCABULARY TO FIVE WORDS and `SKIP` is not one of
    # them (`verdict.Verdict`: PASS / PASS_WITH_WAIVERS / FAIL / NOT_MEASURED /
    # NOT_APPLICABLE). This row was red on live main 8efd02930 before this lane
    # touched anything — the WORD moved, the invariant did not. Both are
    # asserted, the spelling and the MEANING, so the next vocabulary move is
    # caught as a change of meaning instead of passing on a string.
    assert row.status == V.Verdict.NOT_APPLICABLE.value
    assert row.status in V.EXCUSED          # a stand-down, which is the point
    assert row.detail.startswith("DESIGN-DECLARED-N/A")
    assert TD.DECLARATION_REL in row.detail
    rec = json.loads((project / "reports/phase3/digital_hardmacro_gen.json").read_text())
    assert rec["verdict"] == "NOT_APPLICABLE"
    assert rec["reason_class"] == "DESIGN_DECLARED_NA"
    assert rec["produced"] == []


def test_a_hardmacro_still_owes_the_ip_kit(tmp_path):
    """The other direction: the kit is the hardmacro's whole deliverable."""
    project = _project(tmp_path, "HARDMACRO")
    assert R._ip_delivery_declared_na(project)[0] is False


@pytest.mark.parametrize("case,kw", [
    ("an agent's reading is not the owner's word", {"attested": False}),
    ("no declaration at all", {"deliverable": "NOT_DETERMINED"}),
])
def test_only_the_owners_word_stands_the_ip_kit_down(tmp_path, case, kw):
    deliverable = kw.pop("deliverable", "DIE")
    project = _project(tmp_path, deliverable, **kw)
    assert R._ip_delivery_declared_na(project)[0] is False, case


def test_the_flow_row_stands_down_by_the_same_declaration(tmp_path):
    project = _project(tmp_path)
    spec = {"declaration": TD.DECLARATION_REL, "field": "answers.deliverable",
            "absent_when": ["DIE"], "corroborated_by": "owner_attestation"}
    got = FCC._delivery_declares_absence(project, spec)
    assert got is not None and got[0] == TD.DECLARATION_REL
    assert "owner-attested" in got[1]
    assert FCC._check_condition(project, {"delivery_declares": spec}) is False
    # un-attested, a different word, and an unknown corroboration all RUN it
    assert FCC._delivery_declares_absence(
        _project(tmp_path / "b", attested=False), spec) is None
    assert FCC._delivery_declares_absence(
        _project(tmp_path / "c", "HARDMACRO"), spec) is None
    assert FCC._delivery_declares_absence(
        project, {**spec, "corroborated_by": "something_else"}) is None


def test_the_flow_yaml_carries_that_condition_on_37_5ip():
    import yaml
    flow = yaml.safe_load(
        (PROGRAMS.parent / "flow" / "phase1_phase2_phase3.yaml").read_text())
    step = next(s for s in flow["steps"] if str(s.get("id")) == "37.5ip")
    dd = step["condition"]["delivery_declares"]
    assert dd["absent_when"] == ["DIE"]
    assert dd["corroborated_by"] == "owner_attestation"
    # and 37.5ic keeps its own, opposite, corroboration
    ic = next(s for s in flow["steps"] if str(s.get("id")) == "37.5ic")
    assert ic["condition"]["delivery_declares"]["absent_when"] == ["HARDMACRO"]
    assert "corroborated_by" not in ic["condition"]["delivery_declares"]


# ---------------------------------------------------------------- ruling (2)

def test_a_die_is_budgeted_against_the_ring_it_declares(tmp_path):
    rc, rep = _run_budget(_project(tmp_path))
    assert rc == 0 and rep["verdict"] == "FITS", rep
    assert rep["budget_basis"] == "37.5self:own_pad_ring"
    assert rep["own_ring"]["declared_signal_bits"] == 34
    assert rep["own_ring"]["bonded_declared_bits"] == 34
    assert rep["own_ring"]["declared_pads_total"] == 38
    assert rep["own_ring"]["declared_by"] == ["pad_signal_map",
                                              "pad_order_by_side"]
    assert rep["top"] == "spm" and "top_cell" in rep["top_source"]


def test_a_pin_the_declared_ring_never_bonds_is_a_refusal(tmp_path):
    """The check can fail: drop one bit from the map and the die does not fit."""
    project = _project(tmp_path, ring_signals=[
        "VDD", "VSS", "clk", "rst", "y", "p"] + [f"x[{i}]" for i in range(31)])
    rc, rep = _run_budget(project)
    assert rc == 1 and rep["verdict"] == "DOES_NOT_FIT", rep
    assert rep["own_ring"]["unbonded_declared_bits"] == ["x[31]"]
    assert "x[31]" in rep["reason"]


def test_an_undeclared_ring_is_deferred_to_the_step_that_builds_it(tmp_path):
    """R-0915-101 MOVED THIS EXPECTATION. The name is kept so the id set is
    stable; what it asserts is no longer a DEFERRAL.

    This fixture states its ring in NEITHER place it may be stated: no
    `pad_signal_map` in the declaration, and no pad-placement section in any
    design document (the fixture writes no `input/docs`). That is a DESIGN-INPUT
    GAP, and it is booked as one — `ZERO_DENOMINATOR` with a named finding —
    not as `BLOCKED_BY_UPSTREAM`, which would send a reader to step 15.5ic for
    an answer 15.5ic generates FROM this same declaration.

    WHAT SURVIVES UNCHANGED, and is the reason this case exists: it still does
    not PASS. rc 2, verdict UNDECIDED, the finding names the owner."""
    rc, rep = _run_budget(_project(tmp_path, ring=False))
    assert rc == 2 and rep["verdict"] == "UNDECIDED"
    assert rep["reason_class"] == "ZERO_DENOMINATOR"
    assert rep["reason_class"] != "BLOCKED_BY_UPSTREAM"
    assert [f["rule"] for f in rep["findings"]] == ["DIE_DECLARES_NO_PAD_RING"]
    assert rep["findings"][0]["owner"] == "design input"
    assert rep["note"].endswith("not a question blocked on an upstream step")
    # BOTH spellings really are absent — the typed one and the prose one — so
    # this is the gap and not a reader that failed to look.
    assert rep["declared_ring"]["keys_present"] == []
    assert rep["derived_ring"]["measurable"] is False


def test_a_side_order_without_a_signal_map_is_not_a_budget(tmp_path):
    """Instances are not signals: a pad count cannot tell a ring that carries
    these pins from one that carries the wrong nets."""
    project = _project(tmp_path, ring=False)
    doc = json.loads((project / TD.DECLARATION_REL).read_text())
    doc["answers"]["pad_order_by_side"] = {"south": [f"u_pad_{i}"
                                                    for i in range(38)]}
    (project / TD.DECLARATION_REL).write_text(json.dumps(doc))
    rc, rep = _run_budget(project)
    assert rc == 2 and rep["verdict"] == "UNDECIDED", rep
    assert rep["declared_ring"]["keys_present"] == ["pad_order_by_side"]
    assert "pad_signal_map" in rep["reason"] and "38 pad instance(s)" in rep["reason"]


def test_this_step_reads_no_artefact_a_later_step_produces(tmp_path):
    """The repair, as an invariant. `reports/phase3/padring.json` is step
    15.5ic's declared required_output and 15.5ic has step 2 in its own
    ancestry — so no string literal in this program may name it. A comment
    may, and does; `ast` sees only the literals."""
    import ast as _ast
    tree = _ast.parse((PROGRAMS / "slot_pad_budget_check.py").read_text())
    literals = {n.value for n in _ast.walk(tree)
                if isinstance(n, _ast.Constant) and isinstance(n.value, str)}
    assert "padring.json" not in literals
    assert "io_pad_chip_top.json" not in literals
    # the one phase-3 name it carries is the POINTER in the report
    assert "pad_bterm_coincidence.json" in literals
    # and the behaviour, not just the source: a project that HAS a complete
    # ring record still gets the deferral, because nothing here reads it.
    project = _project(tmp_path, ring=False)
    rec = project / "reports" / "phase3" / "padring.json"
    rec.parent.mkdir(parents=True, exist_ok=True)
    rec.write_text(json.dumps({"producer": {"pads": [
        {"instance": f"u_pad_{i}", "signal": sig}
        for i, sig in enumerate(_FULL_RING)]}}))
    rc, rep = _run_budget(project)
    assert rc == 2 and rep["verdict"] == "UNDECIDED", rep
    # R-0915-101 moved the CLASS (a design-input gap, not a wait on 15.5ic);
    # the law this case exists for is untouched and is asserted below on the
    # reader itself, which is stronger than asserting it on one report.
    assert rep["reason_class"] == "ZERO_DENOMINATOR"
    # THE READER, NAMED. Every directory the ring reader scans is design INPUT,
    # and design input is in step 2's own `blocks_on` closure. A phase-2 or
    # phase-3 directory appearing here is the defect this case refuses,
    # whichever report happens to be produced.
    assert LPP.DOC_DIRS == ("input/docs", "phase1/input_doc",
                            "phase1/generated_docs")
    for _dir in LPP.DOC_DIRS:
        assert _dir.split("/")[0] in {"input", "phase1"}, _dir
    # and the run's OWN record of what it read names none of it: the planted
    # phase-3 ring above was not scanned and is nowhere in the report.
    assert rep["documents_scanned"] == [
        "input/step_0_5ic_answers.json", TD.DECLARATION_REL]
    assert "padring.json" not in json.dumps(rep)


def test_a_hardmacro_is_still_budgeted_against_an_operator_slot(tmp_path):
    """The other direction: a macro with no slot is still a design-declared N/A,
    and nothing here turns it into a die."""
    rc, rep = _run_budget(_project(tmp_path, "HARDMACRO"))
    assert rep["verdict"] == "NOT_APPLICABLE" and rc == 2
    assert rep["reason_class"] == "DESIGN_DECLARED_NA"
    assert rep.get("budget_basis") is None


def test_a_die_that_bound_an_operator_slot_is_not_its_own_operator(tmp_path):
    project = _project(tmp_path, "DIE",
                       operator={"path": "shuttle/x.yaml", "slot": "1x1"})
    rc, rep = _run_budget(project)
    assert rep.get("budget_basis") is None, rep


def test_the_design_declaration_supplies_a_width_the_clause_does_not(tmp_path):
    """MEASURED: the auditor's clause passes no --param, the RTL default was
    the only source, and a design whose own declaration answered was refused."""
    rtl = RTL.replace("parameter size = 32", "parameter size")
    project = _project(tmp_path, rtl=rtl, declaration={"size_param": 32})
    rc, rep = _run_budget(project)
    assert rc == 0 and rep["verdict"] == "FITS", rep
    # and with neither source the refusal stands
    bare = _project(tmp_path / "bare", rtl=rtl)
    rc2, rep2 = _run_budget(bare)
    assert rc2 == 2 and rep2["reason_class"] == "ZERO_DENOMINATOR"
    assert "parameterised" in rep2["reason"]


def test_two_answers_about_one_width_are_refused(tmp_path):
    """First in the chain, for every route: a contradiction in the design's
    own records is not made smaller by the branch that would have read it."""
    project = _project(tmp_path, declaration={"size_param": 8})   # RTL says 32
    rc, rep = _run_budget(project)
    assert rc == 2 and rep["verdict"] == "UNDECIDED", rep
    assert rep["parameter_conflicts"]["size"] == {"rtl_default": 32,
                                                  "declared": 8}


def test_a_die_is_never_not_applicable_however_the_word_was_written(tmp_path):
    """R-0915-98(2), the landed contract
    (`test_issue2277…::test_a_DIE_against_the_same_catalogue_still_gets_a_real
    _verdict`): a DIE against the operator's CATALOGUE still gets a REAL
    verdict. Attestation gates a STAND-DOWN, not a measurement — the die is
    measured as a die whoever wrote the word, and the report says which source
    it read. An un-measurable die is UNDECIDED with a named reason, never
    NOT_APPLICABLE and never a pass."""
    for attested in (True, False):
        project = _project(tmp_path / f"a{int(attested)}", attested=attested)
        rc, rep = _run_budget(project)
        assert rep["verdict"] == "FITS" and rc == 0, (attested, rep)
        assert rep["verdict"] != "NOT_APPLICABLE"
        assert rep["budget_basis"] == "37.5self:own_pad_ring"
        assert ("owner-attested" in rep["deliverable_source"]) is attested
    # and a die whose declared pins cannot be read is UNDECIDED, not N/A
    blind = _project(tmp_path / "blind")
    (blind / Path(*S._RTL_DIR_REL) / "spm.v").write_text(
        "module other(input clk); endmodule\n")
    rc, rep = _run_budget(blind)
    assert rc == 2 and rep["verdict"] == "UNDECIDED", rep
    # THE LAW, UNCHANGED BY R-0915-101 and asserted in as many words: whatever
    # else an unmeasurable die is, it is never NOT_APPLICABLE and never a pass.
    assert rep["verdict"] != "NOT_APPLICABLE"
    assert rep["budget_basis"] == "37.5self:own_pad_ring"
    # THE CLASS MOVED. A die that declares no top-level port is a design-input
    # gap NAMED AS ONE, not an error in this gate: nothing downstream supplies a
    # port list the design never wrote, so `EXECUTION_ERROR` sent the reader to
    # the wrong place. It is still not skip-eligible, so the step is still not
    # credited — which is what this case has always been here to hold.
    assert rep["reason_class"] == "ZERO_DENOMINATOR"
    assert rep["reason_class"] not in _RT.SKIP_ELIGIBLE     # still not credited
    assert [f["rule"] for f in rep["findings"]] == ["DIE_DECLARES_NO_TOP_PORT"]
    assert rep["findings"][0]["owner"] == "design input"
