"""test_issue773_all_zero_delta_needs_post_layout_evidence.py

THE RULE UNDER TEST, with no tool, step or block name in it:

    A measurement that reports NO CHANGE AT ALL, on every quantity it measured,
    has produced the one result that is indistinguishable from not having
    measured a second time. It may certify only if it NAMES the second
    measurement's own artefact and that artefact RESOLVES ON DISK.

WHAT WAS MEASURED. A converged tree whose `post_value` equalled `pre_value` on
all nine specs, whose every `delta_pct` was `0.0`, and whose own note said the
post column was inherited from the pre column:

    analog_pre_vs_post_layout_check    rc 0  [PASS]
      summary: specs_compared 9, max_degradation_pct 0.0, errors 0
    analog_a7_post_layout_resim_check  rc 0  PASS — 1/1 block(s) clean

Both gates certified it. The consumer of this artefact is a DEGRADATION gate:
it computes `|post - pre| / |pre|` and tiers the answer at 20 % / 30 %. Fed a
copied column it can only ever compute 0 %, which is its MOST ACCEPTABLE tier —
so the copy scored strictly better than every honest comparison. The existing
zero-compared rule cannot see it either: a copy is not `items_compared == 0`,
it is N comparisons of a number against itself, and it reports N.

THE THREE OUTCOMES, and the third is why this is a fail-safe rather than a
heuristic — an honest all-zero measurement is not made unfixable, it is made
to carry its provenance:

    copied numbers, no evidence named            -> FAIL
    copied numbers, evidence named but absent    -> FAIL   (a claim, not evidence)
    copied numbers, a real extraction on disk    -> PASS

WHAT THE TRIGGER IS: every compared spec's post value is EXACTLY equal to its
pre value. WHAT IT DOES NOT CATCH is pinned below in
`test_the_limit_of_the_trigger_is_recorded_not_assumed`, so the limit is a
reviewable fact rather than something a later reader has to rediscover.

Every fixture is synthetic: invented block names, invented numbers, no PDK, no
vendor, no part number.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

DECLARED_GATE = PROGRAMS / "analog_pre_vs_post_layout_check.py"
STEP_GATE = PROGRAMS / "analog_a7_post_layout_resim_check.py"

#: Both gates that certify `phase3/analog/<block>/pre_vs_post.json`: the FLOW
#: declares the first, the A-track runner runs the second. The rule lives at
#: one shared site, so neither may certify what the other refuses.
GATES = (DECLARED_GATE, STEP_GATE)

BLOCK = "blk_alpha"

#: Nine specs, the shape the measured artefact had.
PRE = {
    "dcgain_tt": 61.42, "dcgain_ss": 59.03, "dcgain_ff": 63.11,
    "vout_tt": 1.7998, "vout_ss": 1.7991, "vout_ff": 1.8004,
    "psrr_tt": 74.5, "psrr_ss": 71.9, "psrr_ff": 76.2,
}

EXTRACTED = f"{BLOCK}_extracted.spice"

_EXTRACTED_DECK = (
    "* extracted post-layout netlist\n"
    f".subckt {BLOCK} vdd vss vin vout\n"
    "xm1 vout vin vss vss nch w=8 l=1\n"
    "c1 vout vss 3.1f\n"
    "r1 vout n1 4.2\n"
    f".ends {BLOCK}\n")


def _tree(root: Path, specs: list, provenance: dict | None = None,
          top: dict | None = None, design_content="structure_and_geometry",
          extraction: str | None = None) -> Path:
    """A complete single-block analog tree.

    Everything a rule OTHER than the one under test could catch is deliberately
    clean: the corner artefact is design-bound and records a real simulator run,
    so no assertion below can be satisfied by a gate failing for another reason.
    """
    ad = root / "phase3" / "analog"
    bd = ad / BLOCK
    bd.mkdir(parents=True, exist_ok=True)
    ad.joinpath("analog_block_list.json").write_text(json.dumps(
        {"blocks": [{"name": BLOCK, "type": "ldo"}]}, indent=2))
    corner = {"block": BLOCK, "_provenance": "real_ngspice",
              "corners": [{"name": "tt_27c_1v8", "simulator_run": True}]}
    if design_content is not None:
        corner["design_content"] = design_content
    (bd / "corner_results.json").write_text(json.dumps(corner, indent=2))

    doc: dict = {"block": BLOCK, "specs": specs}
    if design_content is not None:
        doc["design_content"] = design_content
    if provenance is not None:
        doc["_provenance"] = provenance
    if top:
        doc.update(top)
    (bd / "pre_vs_post.json").write_text(json.dumps(doc, indent=2))

    if extraction is not None:
        (bd / EXTRACTED).write_text(extraction)
    return root


def _copied_specs() -> list:
    """The measured shape: post := pre on every spec, delta_pct 0.0 on every
    spec, and the artefact saying so in its own note."""
    return [{"name": k, "pre_value": v, "post_value": v, "delta_pct": 0.0}
            for k, v in PRE.items()]


def _drifted_specs(pct: float) -> list:
    return [{"name": k, "pre_value": v,
             "post_value": round(v * (1.0 - pct / 100.0), 9)}
            for k, v in PRE.items()]


def _run(gate: Path, project: Path, *args) -> subprocess.CompletedProcess:
    # 55s, not 120s: the CI harness runs this file under `pytest --timeout=180`,
    # which puts the per-call ceiling at 60s (180 // 3). A 120s inner bound can
    # never fire — the harness ends the SESSION first, so the diagnosis lands on
    # whichever test was running rather than on the call that hung. MEASURED on
    # this file: the slowest test is 0.22s wall and every `_run` launches a gate
    # over a tmp_path tree of a few hundred bytes. 55s is the bound the repo
    # already uses for this shape.
    return subprocess.run([sys.executable, str(gate), str(project), *args],
                          capture_output=True, text=True, timeout=55)


def _both(cp) -> str:
    return (cp.stdout or "") + (cp.stderr or "")


# ═══ 1. THE THREE OUTCOMES ═════════════════════════════════════════════════

@pytest.mark.parametrize("gate", GATES, ids=lambda g: g.stem)
def test_copied_numbers_with_no_evidence_do_not_certify(tmp_path, gate):
    """OUTCOME (i). Pre-fix both gates answered rc 0 on exactly this tree."""
    project = _tree(tmp_path, _copied_specs())
    cp = _run(gate, project)
    assert cp.returncode == 1, (
        f"{gate.stem} certified (rc={cp.returncode}) nine comparisons of a "
        f"number against itself, with nothing on the tree naming a "
        f"post-layout measurement:\n{_both(cp)}")
    assert "ALL_ZERO_DELTA_UNEVIDENCED" in _both(cp), _both(cp)


@pytest.mark.parametrize("gate", GATES, ids=lambda g: g.stem)
def test_named_but_absent_evidence_is_a_claim_not_evidence(tmp_path, gate):
    """OUTCOME (ii). The whole point of "resolves on disk": a string is free,
    so a gate that accepted the NAME would have raised the price of the copy by
    exactly one line of JSON."""
    project = _tree(tmp_path, _copied_specs(),
                    provenance={"extracted_netlist": EXTRACTED})
    assert not (project / "phase3" / "analog" / BLOCK / EXTRACTED).exists()
    cp = _run(gate, project)
    assert cp.returncode == 1, (
        f"{gate.stem} certified (rc={cp.returncode}) an all-zero comparison on "
        f"a NAMED post-layout artefact that is not on the disk it is "
        f"reading:\n{_both(cp)}")
    out = _both(cp)
    assert "ALL_ZERO_DELTA_UNEVIDENCED" in out, out
    # The finding must NAME the broken claim — a reader who can see the key in
    # the file would read a generic "nothing named" message as a gate bug.
    assert EXTRACTED in out and "no such file" in out, out


@pytest.mark.parametrize("gate", GATES, ids=lambda g: g.stem)
def test_an_all_zero_comparison_carrying_its_provenance_certifies(
        tmp_path, gate):
    """OUTCOME (iii), and the reason this is fail-SAFE rather than a ban. An
    honest all-zero measurement is surprising, not forbidden; with the artefact
    its post column was simulated from on disk it still passes."""
    project = _tree(tmp_path, _copied_specs(),
                    provenance={"extracted_netlist": EXTRACTED},
                    extraction=_EXTRACTED_DECK)
    cp = _run(gate, project)
    assert cp.returncode == 0, (
        f"{gate.stem} refused (rc={cp.returncode}) an all-zero comparison that "
        f"NAMES the extracted post-layout netlist it was simulated from, and "
        f"that netlist is on disk:\n{_both(cp)}")
    assert "ALL_ZERO_DELTA_UNEVIDENCED" not in _both(cp), _both(cp)


def test_the_two_gates_over_one_artefact_agree_on_all_three_trees(tmp_path):
    """THE INVARIANT this repo already holds for this artefact: two gates that
    certify ONE file must not disagree about it. The rule lives at one shared
    site precisely so this cannot drift."""
    trees = {
        "no_evidence": _tree(tmp_path / "a", _copied_specs()),
        "named_absent": _tree(tmp_path / "b", _copied_specs(),
                              provenance={"extracted_netlist": EXTRACTED}),
        "resolves": _tree(tmp_path / "c", _copied_specs(),
                          provenance={"extracted_netlist": EXTRACTED},
                          extraction=_EXTRACTED_DECK),
    }
    for name, project in trees.items():
        rcs = {g.stem: _run(g, project).returncode for g in GATES}
        assert len(set(rcs.values())) == 1, (
            f"two gates over ONE artefact disagree about the {name!r} tree: "
            f"{rcs}")


# ═══ 2. WHAT COUNTS AS EVIDENCE, AND WHAT ONLY LOOKS LIKE IT ═══════════════

def test_the_skills_own_documented_key_is_accepted(tmp_path):
    """`post_layout_file` at the top level is the spelling the authoring
    skill's own documented example uses. A rule that only read one new key
    would have failed artefacts written exactly per their instructions."""
    project = _tree(tmp_path, _copied_specs(),
                    top={"post_layout_file": "post_layout_corner_results.json"})
    (project / "phase3" / "analog" / BLOCK
     / "post_layout_corner_results.json").write_text(
        json.dumps({"block": BLOCK, "corners": [{"name": "tt_27c_1v8"}]}))
    for gate in GATES:
        cp = _run(gate, project)
        assert cp.returncode == 0, (
            f"{gate.stem} refused evidence named under the key the authoring "
            f"skill documents:\n{_both(cp)}")


@pytest.mark.parametrize("why,claim,make", [
    ("an EMPTY file satisfies an existence check and measures nothing",
     EXTRACTED, ""),
    ("the PRE-layout baseline is not post-layout evidence",
     "corner_results.json", None),
    ("the comparison artefact cannot be its own evidence",
     "pre_vs_post.json", None),
])
def test_a_disqualified_path_is_not_evidence(tmp_path, why, claim, make):
    """Each of these RESOLVES. None of them is a second measurement, and each
    is guaranteed to exist wherever this rule runs, so a rule that only asked
    "is there a file?" would have been satisfied by the tree itself."""
    project = _tree(tmp_path, _copied_specs(),
                    provenance={"extracted_netlist": claim})
    bd = project / "phase3" / "analog" / BLOCK
    if make is not None:
        (bd / claim).write_text(make)
    assert (bd / claim).is_file(), "fixture is not exercising the case"
    for gate in GATES:
        cp = _run(gate, project)
        assert cp.returncode == 1, (
            f"{gate.stem} accepted `{claim}` as post-layout evidence "
            f"(rc={cp.returncode}) — {why}:\n{_both(cp)}")
        assert "ALL_ZERO_DELTA_UNEVIDENCED" in _both(cp), _both(cp)


def test_a_path_outside_the_project_is_not_evidence(tmp_path):
    """Otherwise any file anywhere on the host stands in for the extraction."""
    outside = tmp_path / "elsewhere.spice"
    outside.write_text(_EXTRACTED_DECK)
    project = _tree(tmp_path / "p", _copied_specs(),
                    provenance={"extracted_netlist": str(outside)})
    assert outside.is_file(), "fixture is not exercising the case"
    for gate in GATES:
        cp = _run(gate, project)
        assert cp.returncode == 1, (
            f"{gate.stem} accepted a file OUTSIDE the project as post-layout "
            f"evidence (rc={cp.returncode}):\n{_both(cp)}")


def test_a_symlink_out_of_the_project_is_not_evidence(tmp_path):
    """The containment rule is enforced on the RESOLVED path, so a link that
    lives inside the project and points out of it is not a way round it."""
    outside = tmp_path / "outside.spice"
    outside.write_text(_EXTRACTED_DECK)
    project = _tree(tmp_path / "p", _copied_specs(),
                    provenance={"extracted_netlist": EXTRACTED})
    (project / "phase3" / "analog" / BLOCK / EXTRACTED).symlink_to(outside)
    for gate in GATES:
        cp = _run(gate, project)
        assert cp.returncode == 1, (
            f"{gate.stem} accepted a symlink escaping the project as "
            f"post-layout evidence (rc={cp.returncode}):\n{_both(cp)}")


def test_a_bare_string_provenance_does_not_break_the_lookup(tmp_path):
    """The deterministic corner producer writes `_provenance` as a bare STRING
    (`"real_ngspice"`), and an authoring skill may copy that shape into this
    artefact. Looking for keys inside a string must not raise, and must not
    stop the top-level lookup from finding the evidence."""
    project = _tree(tmp_path, _copied_specs(), provenance="real_ngspice",
                    top={"post_layout_file": "post_layout_corner_results.json"})
    (project / "phase3" / "analog" / BLOCK
     / "post_layout_corner_results.json").write_text(json.dumps({"c": []}))
    for gate in GATES:
        cp = _run(gate, project)
        assert cp.returncode == 0, (
            f"{gate.stem} could not read top-level evidence beside a "
            f"string-valued `_provenance` (rc={cp.returncode}):\n{_both(cp)}")


def test_a_declared_delta_cannot_buy_a_pass_for_a_copied_column(tmp_path):
    """The step gate PREFERS a `delta_pct` the artefact declares about itself
    over the one its values imply. So a rule reading the declared field would
    have let an author write `delta_pct: 1.7` beside `post_value == pre_value`
    and walk past this gate while the sibling — which computes from the values
    — refused: two gates over one file, in disagreement. The shared rule reads
    the VALUES on both sides."""
    specs = [{"name": k, "pre_value": v, "post_value": v, "delta_pct": 1.7}
             for k, v in PRE.items()]
    project = _tree(tmp_path, specs)
    rcs = {}
    for gate in GATES:
        cp = _run(gate, project)
        rcs[gate.stem] = cp.returncode
        assert cp.returncode == 1, (
            f"{gate.stem} certified (rc={cp.returncode}) a copied post column "
            f"carrying a fabricated non-zero `delta_pct`:\n{_both(cp)}")
    assert len(set(rcs.values())) == 1, rcs


def test_the_flat_pre_post_schema_is_covered_too(tmp_path):
    """The step gate also accepts `{"pre": {...}, "post": {...}}`. A rule wired
    only into the `specs[]` path would leave the second schema open."""
    project = _tree(tmp_path, [])
    bd = project / "phase3" / "analog" / BLOCK
    (bd / "pre_vs_post.json").write_text(json.dumps({
        "block": BLOCK, "design_content": "structure_and_geometry",
        "pre": dict(PRE), "post": dict(PRE)}, indent=2))
    cp = _run(STEP_GATE, project)
    assert cp.returncode == 1, (
        f"the flat pre/post schema certified a column compared against itself "
        f"(rc={cp.returncode}):\n{_both(cp)}")
    assert "ALL_ZERO_DELTA_UNEVIDENCED" in _both(cp), _both(cp)


# ═══ 3. NON-WEAKENING — the rules that already worked still work ═══════════

def test_a_genuine_degradation_is_still_reported_as_before(tmp_path):
    """THE NON-WEAKENING CONTROL the fix is judged against: the 20 %/30 % tiers
    this gate exists for still bite. A 25 % drift is a MODERATE degradation and
    is named as one."""
    project = _tree(tmp_path, _drifted_specs(25.0))
    cp = _run(DECLARED_GATE, project)
    assert cp.returncode == 0, _both(cp)
    out = _both(cp)
    assert "LAYOUT_MODERATE_DEGRADATION" in out, out
    assert "25.0% degradation" in out, out
    assert "ALL_ZERO_DELTA_UNEVIDENCED" not in out, out


def test_a_severe_degradation_is_still_severe(tmp_path):
    """...and past 30 % it is still an ERROR that fails the gate."""
    project = _tree(tmp_path, _drifted_specs(45.0))
    cp = _run(DECLARED_GATE, project)
    assert cp.returncode == 1, _both(cp)
    out = _both(cp)
    assert "LAYOUT_SEVERE_DEGRADATION" in out, out
    assert "ALL_ZERO_DELTA_UNEVIDENCED" not in out, out


def test_a_normal_measurement_needs_no_evidence_at_all(tmp_path):
    """BLAST-RADIUS CONTROL, and the reason this is a TRIGGERED rule rather
    than an unconditional one: a comparison whose numbers actually moved is
    untouched, evidence or no evidence. Artefacts whose post column came from a
    modelled parasitic bump — which disclose themselves honestly and carry no
    extracted netlist — keep passing."""
    project = _tree(tmp_path, _drifted_specs(5.0))
    for gate in GATES:
        cp = _run(gate, project)
        assert cp.returncode == 0, (
            f"{gate.stem} newly refused an ordinary non-zero comparison that "
            f"names no evidence (rc={cp.returncode}):\n{_both(cp)}")


def test_zero_comparable_specs_is_still_zero_comparable_specs(tmp_path):
    """ORDERING CONTROL. `#438(c)`'s rule owns the file that compares NOTHING;
    this one owns the file that compares N numbers against themselves. A file
    with no comparable pair must still be diagnosed as that — the new rule
    cannot fire on it, because it requires at least one compared pair."""
    project = _tree(tmp_path, [])
    bd = project / "phase3" / "analog" / BLOCK
    (bd / "pre_vs_post.json").write_text(json.dumps(
        {"block": BLOCK, "comparison": {"vout": "ok"}}))
    cp = _run(DECLARED_GATE, project)
    assert cp.returncode == 1
    out = _both(cp)
    assert "PRE_VS_POST_ZERO_COMPARED" in out, out
    assert "ALL_ZERO_DELTA_UNEVIDENCED" not in out, out


def test_the_copy_is_named_before_the_content_question(tmp_path):
    """ORDERING CONTROL, the other direction. A tree that is BOTH a copy and
    silent about what circuit was compared reports the copy: what was compared
    does not matter yet if the post column is the pre column, and a reader sent
    to fix the disclosure first would fix the wrong thing."""
    project = _tree(tmp_path, _copied_specs(), design_content=None)
    for gate, content_rule in ((DECLARED_GATE,
                                "PRE_VS_POST_DESIGN_CONTENT_UNDECLARED"),
                               (STEP_GATE, "A7_DESIGN_CONTENT_UNDECLARED")):
        cp = _run(gate, project)
        assert cp.returncode == 1, _both(cp)
        out = _both(cp)
        assert "ALL_ZERO_DELTA_UNEVIDENCED" in out, out
        assert content_rule not in out, out


def test_a_disclosed_library_default_keeps_its_own_tier(tmp_path):
    """NEGATIVE CONTROL on the tier ladder: an honest all-zero measurement over
    a disclosed library default still certifies, in the disclosed tier. Only
    the copy costs — failing an honest ceiling teaches the next run to stop
    being honest."""
    project = _tree(tmp_path, _copied_specs(), design_content="structure_only",
                    provenance={"extracted_netlist": EXTRACTED},
                    extraction=_EXTRACTED_DECK)
    cp = _run(DECLARED_GATE, project)
    assert cp.returncode == 0, _both(cp)
    assert "[PASS_STRUCTURE_ONLY]" in cp.stdout, cp.stdout


# ═══ 4. THE LIMIT, RECORDED ════════════════════════════════════════════════

def test_the_limit_of_the_trigger_is_recorded_not_assumed(tmp_path):
    """WHAT THIS RULE DOES NOT CATCH, pinned as a fact rather than left in a
    comment: a fabricator who PERTURBS the post column instead of copying it —
    0.0001 % on every spec — writes numbers no rule here can distinguish from a
    measurement, and passes.

    It is not closed by widening the trigger. "Every delta is suspiciously
    small" needs a threshold, and a threshold is the heuristic this rule exists
    not to be. The one threshold-free widening does not survive floating point:
    two specs both authored to drift 1 % compute to 1.0000000000000009 % and
    0.9999999999999963 %, so an equality test over "every spec drifted by the
    SAME amount" never fires. Closing it needs the evidence requirement to be
    UNCONDITIONAL, which fails every honest artefact whose post column came
    from a modelled parasitic bump — a different change with a different blast
    radius.

    This test is the record. If a later round widens the trigger it goes red,
    and that is the moment to decide deliberately rather than by accident.
    """
    specs = [{"name": k, "pre_value": v,
              "post_value": round(v * 1.000001, 12)} for k, v in PRE.items()]
    project = _tree(tmp_path, specs)
    for gate in GATES:
        cp = _run(gate, project)
        assert cp.returncode == 0, (
            f"{gate.stem} now REFUSES a uniformly-perturbed post column "
            f"(rc={cp.returncode}). That is a wider trigger than this rule "
            f"documents; re-read the limits at "
            f"`_analog_a_check_common.pre_vs_post_zero_delta` and update this "
            f"record deliberately:\n{_both(cp)}")

    # ...and the floating-point measurement the reasoning above rests on,
    # asserted rather than asserted-about, so it cannot quietly stop being true.
    d1 = abs(round(1.80 * 0.99, 6) - 1.80) / 1.80 * 100
    d2 = abs(20.2 - 20.0) / 20.0 * 100
    assert d1 != d2, (
        f"two specs both authored to drift 1 % now compute to the SAME float "
        f"({d1!r}); a uniformity trigger may have become implementable and the "
        f"reasoning for the narrow trigger should be revisited")
