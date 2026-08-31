"""Every path a flow step declares must have an ENTRY in the d3 evidence manifest.

`flow/phase1_phase2_phase3.yaml` declares what each step must produce.
`programs/tests/fixtures/matrix_d3_output_manifest.json` records, per declared
path, where a real run produced it — its own header states the contract:
*"For every required_outputs entry of every flow step"*. Until this file existed
NOTHING enforced that pairing over the tree, so a two-line yaml edit could add a
`required_outputs` entry and leave the manifest un-re-measured.

WHY A DESYNC IS WORSE THAN ONE MORE RED CELL, which is the whole reason this is
a gate of its own. `matrix_mutation_ledger.py` declares `witness="D1"` for the
`D3-UNDECLARED-ARTEFACT` mutation, and LOCK 2's first requirement is that the
UNMUTATED run passes — *"an already-red cell proves nothing"*. Reddening
`d3/stepD1` therefore does not merely add a red: it REMOVES the proof that an
entire class of undeclared-artefact defects is still caught. Measured on
`3d13e2c59`, by deleting D1's two `reports/phase1/extraction_coverage_report.*`
records from the manifest and changing nothing else:

    flow yaml     7a3754ddd373083f20f0d21aca9aade5   (identical on both arms)

    manifest 1b8c3c347095fbe9593cc7faf0bfe603   96 passed in 131.80s
    manifest 5c3bc7ae48a0d968f82c7f245ff5400d    2 failed, 94 passed in 158.69s
        test_lock2_the_mutation_really_reddens_its_witness[D3-UNDECLARED-ARTEFACT]
        test_the_replay_actually_ran_and_is_not_starved
            -> "D3-UNDECLARED-ARTEFACT@D1: expected REDDENED, got ALREADY_RED"

(`pytest programs/tests/test_matrix_mutation_ledger.py -q`.) The ledger has
already been through this once: its own comment records the witness moving off
step 21 on 2026-08-11 for exactly this reason.

WHAT THIS GATE ASSERTS, AND WHAT IT DELIBERATELY DOES NOT. It asserts only that
the manifest carries an ENTRY for every declared path, and no entry for a path
no step declares. It does NOT ask whether the artefact exists — that is
dimension 3's question, it needs the campaign's run roots, and it is red today
for the separate reason in vibe-ic#1266. The two questions fail for different
reasons and must never be readable as substitutes, so
`test_a_declared_path_whose_artefact_is_ABSENT_is_NOT_flagged_here` pins the
silence in that direction rather than leaving it untested.

STATED OVER THE TREE, NOT OVER A DIFF. A diff-based version needs a base ref and
silently changes its answer under a rebase, a stacked branch, or a batch merge —
and a batch merge is precisely how two yaml-only branches reached main together
in the measurement above. Over the tree there is one answer and every host gets
it: no run roots, no git, no network. Measured on `3d13e2c59`: 63 steps, 61 of
them declaring, 134 declared paths, 134 manifest entries, a strict bijection.

The step-SET half of the pairing (a flow step missing from the manifest, or a
manifest step no longer in the flow) is already guarded, host-independently, by
`test_d3_manifest_covers_exactly_the_flow_steps`. This file is the ENTRY half of
the same contract, which lived only inside `audit_step` — behind run-root
discovery, in a per-cell test that can be red for unrelated reasons.
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Sequence, Tuple

from flow_matrix import flowref as F

# The manifest is READ THROUGH ITS CONSUMER, not re-opened from a path spelled
# again here. A guard that loaded its own copy of the file would keep passing if
# dimension 3 ever moved to a different manifest, which is the exact failure
# mode this gate exists to prevent one level up.
import test_matrix_d3_outputs_produced as D3


def declaration_parity(
    steps: Sequence[Mapping[str, Any]],
    manifest_steps: Mapping[str, Mapping[str, Any]],
) -> Tuple[Dict[str, List[str]], Dict[str, List[str]]]:
    """``(uncovered, orphaned)``, both ``{step id: [paths]}``. Empty is clean.

    * uncovered — declared in the flow yaml, no entry in the manifest.
    * orphaned  — an entry in the manifest, declared by that step no longer.

    Entries are compared RAW. `required_outputs` any-of entries keep their
    ``" OR "`` intact (`flowref.required_outputs` returns them unsplit) and the
    manifest keys on that same raw string, so parity is string identity — see
    `test_an_any_of_entry_is_matched_RAW_and_not_by_its_halves`.

    Takes the data rather than reading the flow and the manifest itself, so the
    assertion over the SHIPPED tree and the paired guards below run the exact
    same predicate. A guard that exercised a private copy of this logic would
    prove only that the copy works.
    """
    uncovered: Dict[str, List[str]] = {}
    orphaned: Dict[str, List[str]] = {}
    for step in steps:
        sid = str(step.get("id"))
        declared = [str(e) for e in (step.get("required_outputs") or [])]
        recorded = list((manifest_steps.get(sid) or {}).get("entries") or {})
        missing = sorted({e for e in declared if e not in recorded})
        extra = sorted({e for e in recorded if e not in declared})
        if missing:
            uncovered[sid] = missing
        if extra:
            orphaned[sid] = extra
    return uncovered, orphaned


def _shipped() -> Tuple[Any, Any]:
    return F.steps(), D3.manifest()["steps"]


# ──────────────────────────────────────────────────────────────────────
# The shipped tree — the population that actually ships
# ──────────────────────────────────────────────────────────────────────
def test_every_declared_path_has_a_manifest_entry():
    """The forward direction: a yaml edit that never reached the manifest."""
    uncovered, _ = declaration_parity(*_shipped())
    assert uncovered == {}, (
        "flow yaml and the dimension-3 evidence manifest have drifted apart: "
        f"{sum(len(v) for v in uncovered.values())} declared path(s) have NO "
        f"manifest entry: {uncovered}\n"
        "Re-measure those paths into "
        "programs/tests/fixtures/matrix_d3_output_manifest.json in the SAME "
        "change that declares them. Leaving them unmeasured reddens the d3 cell "
        "that is the D3-UNDECLARED-ARTEFACT witness, and an already-red witness "
        "stops proving that undeclared artefacts are caught at all."
    )


def test_no_manifest_entry_names_a_path_its_step_no_longer_declares():
    """The reverse direction: a yaml deletion that never reached the manifest.

    Measured zero on `3d13e2c59`. It is asserted rather than assumed because a
    record left behind by a removed declaration is evidence for a claim nobody
    makes any more — the same disease read from the other end, and the shape of
    the manifest-only branch in this issue's own survey.
    """
    _, orphaned = declaration_parity(*_shipped())
    assert orphaned == {}, (
        "the manifest records evidence for paths no step declares any more: "
        f"{orphaned}\n"
        "Drop those records in the change that drops the declaration."
    )


def test_the_population_is_the_whole_flow_and_is_not_empty():
    """Without this, both assertions above could pass over nothing.

    A set-difference check is exactly the shape that goes quietly green when its
    input vanishes: no steps, no differences, PASS. Both inputs are asserted
    non-empty, and the manifest's entry count is asserted against the flow's
    declared count — which, given the two assertions above, makes the pairing a
    bijection rather than a one-way covering.
    """
    steps, manifest_steps = _shipped()
    assert len(steps) > 0, "no flow steps — check the yaml loader"
    assert len(manifest_steps) > 0, "no manifest steps — check the fixture"

    declared = [e for s in steps for e in (s.get("required_outputs") or [])]
    declaring = [s for s in steps if s.get("required_outputs")]
    assert declaring, "no step declares required_outputs — check the loader"
    assert declared, "no declared paths at all — check the loader"

    entries = sum(len(r.get("entries") or {}) for r in manifest_steps.values())
    assert entries == len(declared), (
        f"{len(declared)} declared paths vs {entries} manifest entries "
        "(measured 134 == 134 on 3d13e2c59) — the two sides no longer pair "
        "one-to-one even where the names still line up"
    )


def test_this_guard_reads_the_manifest_dimension_3_consumes():
    """One manifest, not two.

    Read out of the consumer module, so the gate cannot end up guarding a file
    that dimension 3 stopped reading.
    """
    assert D3.MANIFEST_PATH.is_file(), D3.MANIFEST_PATH
    assert D3.MANIFEST_PATH.name == "matrix_d3_output_manifest.json"
    assert D3.MANIFEST_PATH.parent.name == "fixtures"


# ──────────────────────────────────────────────────────────────────────
# Paired guards — the check must FIRE on the real defect
# ──────────────────────────────────────────────────────────────────────
def test_the_check_FIRES_on_the_reconstructed_desync():
    """The measured case, with its real names: two yaml-only branches on D1.

    `reports/phase1/extraction_coverage_report.md` and `.json` moved onto step
    D1 in the yaml; the branches that did not also re-measure the manifest are
    the ones that reddened the witness.
    """
    md = "reports/phase1/extraction_coverage_report.md"
    js = "reports/phase1/extraction_coverage_report.json"
    steps = [{"id": "D1", "required_outputs": [
        "phase1/generated_docs/L1_DATASHEET.json", md, js]}]
    manifest_steps = {"D1": {"verdict": "ENFORCED", "entries": {
        "phase1/generated_docs/L1_DATASHEET.json": {"status": "PRODUCED_BY_RUN"},
    }}}
    uncovered, orphaned = declaration_parity(steps, manifest_steps)
    assert uncovered == {"D1": [js, md]}
    assert orphaned == {}


def test_the_check_FIRES_on_a_manifest_entry_no_step_declares():
    """The reverse arm of the same pair."""
    steps = [{"id": "27", "required_outputs": ["reports/phase3/si_mcf_sta.json"]}]
    manifest_steps = {"27": {"entries": {
        "reports/phase3/si_mcf_sta.json": {"status": "PRODUCED_BY_RUN"},
        "reports/phase3/si_crosstalk.rpt": {"status": "PRODUCED_BY_RUN"},
    }}}
    uncovered, orphaned = declaration_parity(steps, manifest_steps)
    assert uncovered == {}
    assert orphaned == {"27": ["reports/phase3/si_crosstalk.rpt"]}


def test_the_check_FIRES_when_a_declaring_step_is_absent_from_the_manifest():
    """A whole step added to the flow and never measured — all of it uncovered.

    The step-SET mismatch is `test_d3_manifest_covers_exactly_the_flow_steps`'s
    subject; what is asserted here is that this predicate does not silently skip
    a step it cannot find a record for.
    """
    steps = [{"id": "45", "required_outputs": ["reports/phase3/new_thing.json"]}]
    uncovered, orphaned = declaration_parity(steps, {})
    assert uncovered == {"45": ["reports/phase3/new_thing.json"]}
    assert orphaned == {}


# ──────────────────────────────────────────────────────────────────────
# Negative controls — the check must stay SILENT where it must
# ──────────────────────────────────────────────────────────────────────
def test_a_declared_path_whose_artefact_is_ABSENT_is_NOT_flagged_here():
    """THE control that keeps this gate from becoming a second dimension 3.

    A path that is declared, carries a manifest record, and whose artefact no
    run root holds is a dimension-3 failure and this gate must be silent on it —
    it has no run roots, does no filesystem probe, and asks only about the
    pairing. If this ever fired, greening it would mean deleting a true
    declaration or forging evidence, and both are worse than the defect.
    """
    entry = "phase3/stage3/nowhere/does/this/exist.gds"
    steps = [{"id": "31", "required_outputs": [entry]}]
    manifest_steps = {"31": {"entries": {entry: {
        "status": "PRODUCED_BY_RUN",
        "run": "benchmark-data/ic/<a run root>",
        "path": entry,
        "size_bytes": 0,
    }}}}
    assert declaration_parity(steps, manifest_steps) == ({}, {})


def test_a_step_that_declares_nothing_is_not_an_error():
    """Absent and empty both pair with an empty record set."""
    steps = [{"id": "P0"}, {"id": "35", "required_outputs": []}]
    manifest_steps = {
        "P0": {"verdict": "NA_NO_REQUIRED_OUTPUTS", "entries": {}},
        "35": {"verdict": "NA_NO_REQUIRED_OUTPUTS"},
    }
    assert declaration_parity(steps, manifest_steps) == ({}, {})


def test_a_dormant_or_waived_step_is_held_to_the_same_pairing():
    """Verdict does not enter the predicate, and that is deliberate.

    5 steps are NA_DORMANT_CONDITION and 3 are WAIVED on `3d13e2c59`, and all 8
    carry a full entry set. Exempting them would make the cheapest way to escape
    this gate a verdict edit in the file the gate reads.
    """
    steps = [{"id": "39", "required_outputs": ["reports/silicon/bringup.json"]}]
    for verdict in ("NA_DORMANT_CONDITION", "WAIVED", "ENFORCED"):
        assert declaration_parity(
            steps, {"39": {"verdict": verdict, "entries": {}}},
        ) == ({"39": ["reports/silicon/bringup.json"]}, {})


def test_an_any_of_entry_is_matched_RAW_and_not_by_its_halves():
    """`"a OR b"` is ONE declaration and ONE manifest key.

    `flowref.required_outputs` returns entries unsplit and the manifest keys on
    that same string — step 1's record is literally
    `"phase2/stage1/rtl/*.sv OR phase2/stage1/rtl/*.v"`. A manifest that
    recorded the two halves separately would cover the declaration in neither
    direction, and this pins that it reads as the drift it is rather than as a
    match.
    """
    raw = "phase2/stage1/rtl/*.sv OR phase2/stage1/rtl/*.v"
    steps = [{"id": "1", "required_outputs": [raw]}]
    assert declaration_parity(steps, {"1": {"entries": {raw: {}}}}) == ({}, {})

    halves = {"phase2/stage1/rtl/*.sv": {}, "phase2/stage1/rtl/*.v": {}}
    uncovered, orphaned = declaration_parity(steps, {"1": {"entries": halves}})
    assert uncovered == {"1": [raw]}
    assert orphaned == {"1": sorted(halves)}


def test_int_and_str_step_ids_collapse_to_the_same_key():
    """The yaml carries `id: 27` as an int and the manifest keys on `"27"`.

    `flowref.normalize_id` states the same rule for the same reason; a predicate
    that compared them unnormalised would report every numeric step as entirely
    uncovered — a 100%-red gate, which is as useless as a silent one.
    """
    entry = "reports/phase3/si_mcf_sta.json"
    steps = [{"id": 27, "required_outputs": [entry]}]
    assert declaration_parity(steps, {"27": {"entries": {entry: {}}}}) == ({}, {})
