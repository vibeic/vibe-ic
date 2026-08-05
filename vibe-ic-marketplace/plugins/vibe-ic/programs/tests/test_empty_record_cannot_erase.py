#!/usr/bin/env python3
"""A source that says nothing about a key cannot erase one that said something.

Written against the OBSERVABLE PROPERTY, not against the implementation: every
assertion here is about what a merge RETURNS for a given set of sources, or
about what a program REPORTS for given input files. A different correct fix --
a hand-rolled merge, a different tie-break, a different helper name -- passes
all of it.

FIXTURES ARE PUBLIC MATERIAL ONLY: sky130A / gf180mcuD / nangate45 names, or
pure LEF / Liberty / JSON grammar with invented identifiers. Nothing here names
a foundry, SKU, process node or part number.

Layout:
  1. THE RULE          -- silence cannot erase, in the helper and at each site
  2. THE REVERSE CASE  -- what the OVER-correction looks like, and that it is
                          not what shipped. These are the ones that matter.
  3. THE GUARD         -- fires on the shape, abstains on the legitimate ones
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

import atpg_untestable_fault_classify as auc            # noqa: E402
import payload_bit_position_check as pbp                # noqa: E402
import per_source_record_merge_check as guard           # noqa: E402
from _source_record_merge import (DENIES, INDETERMINATE,  # noqa: E402
                                  SILENT, merge_source_records)


# ══════════════════════════════════════════════════════════ 1. THE RULE ══════

def test_empty_record_does_not_erase_a_populated_one_in_either_order():
    """THE defect, at its smallest. Both orders must give the same answer, and
    that answer must be the one that carries the content."""
    speaks = {"CELL_A": {"A": "input", "Y": "output"}}
    silent = {"CELL_A": {}}

    forward = merge_source_records([speaks, silent]).merged
    reverse = merge_source_records([silent, speaks]).merged

    assert forward == reverse
    assert forward["CELL_A"] == {"A": "input", "Y": "output"}


def test_result_is_invariant_under_permutation_of_sources():
    """The property the caller actually needs: renaming a file cannot change
    the verdict. Every permutation of five sources, one of them silent."""
    import itertools
    sources = [
        {"m1": {"met1": 2.0}},
        {"m1": {}},
        {"m2": {"met2": 1.0}},
        {"m3": {}},
        {"m1": {"met1": 2.0}, "m4": {"met4": 9.0}},
    ]
    answers = {json.dumps(merge_source_records(list(p)).merged, sort_keys=True)
               for p in itertools.permutations(sources)}
    assert len(answers) == 1, "merge result depends on source order"


def test_content_callable_sees_emptiness_one_level_down():
    """A record can be TRUTHY and still say nothing. `{"blocked": {}, "size":
    (10, 20)}` is the measured shape; without `content=` its truthiness hides
    the silence and the erase comes straight back."""
    speaks = {"MX": {"blocked": {"met4": 61.5}, "size": (10.0, 20.0)}}
    silent = {"MX": {"blocked": {}, "size": (10.0, 20.0)}}

    naive = merge_source_records([speaks, silent]).merged
    assert naive["MX"]["blocked"] == {}, "plain truthiness cannot see this"

    aware = merge_source_records([speaks, silent],
                                 content=lambda e: e.get("blocked")).merged
    reverse = merge_source_records([silent, speaks],
                                   content=lambda e: e.get("blocked")).merged
    assert aware["MX"]["blocked"] == {"met4": 61.5}
    assert aware == reverse


def test_disagreement_between_two_speaking_sources_is_reported_not_hidden():
    a = {"k": {"x": 1}}
    b = {"k": {"x": 1, "y": 2}}
    richer, conflicts, _ = merge_source_records([a, b], on_conflict="richer")
    sparser, conflicts2, _ = merge_source_records([b, a], on_conflict="sparser")

    assert richer["k"] == {"x": 1, "y": 2}
    assert sparser["k"] == {"x": 1}
    assert [c["key"] for c in conflicts] == ["k"]
    assert [c["key"] for c in conflicts2] == ["k"]


# ─────────────────── 1b. ABSENCE, DENIAL, AND "CANNOT TELL" ARE THREE ──────
# An empty record is not one fact. The merge must not treat "this file said
# nothing about K" and "this file measured K to be empty" as the same input,
# and it must not quietly file "cannot tell which" under either.

def test_silence_is_unconditional_but_a_denial_is_governed_by_the_policy():
    """THE distinction, stated as the one place the two states diverge.

    A denial is a MEASUREMENT that happens to be empty, so a denial against
    content is two sources disagreeing and belongs to `on_conflict` like any
    other disagreement -- a blocking gate that takes the floor must be able to
    honour a variant that measured nothing there.

    Silence is not a measurement, so NO policy may promote it into one. Under
    the same `on_conflict="sparser"` that lets a denial win, silence still
    cannot displace a single key.

    Both directions are asserted, because a fix that made denial win
    everywhere, or silence win under sparser, would pass a one-sided test.
    """
    content = {"MX": {"met4": 61.5}}
    empty = {"MX": {}}

    silent_floor = merge_source_records([content, empty], on_conflict="sparser",
                                        stance=lambda _r: SILENT)
    denied_floor = merge_source_records([content, empty], on_conflict="sparser",
                                        stance=lambda _r: DENIES)
    assert silent_floor.merged["MX"] == {"met4": 61.5}, \
        "silence took the floor -- no policy may turn an absence into evidence"
    assert denied_floor.merged["MX"] == {}, \
        "an explicit measurement of nothing could not be honoured by the " \
        "policy that exists to honour it"

    # ...and neither direction may depend on argument order
    assert merge_source_records([empty, content], on_conflict="sparser",
                                stance=lambda _r: DENIES).merged == \
        denied_floor.merged

    # Under `richer` both keep the content -- but only ONE of them is a
    # disagreement, and only that one is reported as one.
    silent_rich = merge_source_records([content, empty], on_conflict="richer",
                                       stance=lambda _r: SILENT)
    denied_rich = merge_source_records([content, empty], on_conflict="richer",
                                       stance=lambda _r: DENIES)
    assert silent_rich.merged == denied_rich.merged == content
    assert silent_rich.conflicts == [], "silence is not a disagreement"
    assert [c["kind"] for c in denied_rich.conflicts] == ["content-vs-denial"]


def test_an_unclassified_empty_is_filed_as_neither_silence_nor_denial():
    """"Cannot tell which" gets its OWN state. Pinned from both sides, because
    the cheap wrong fix is to give it a name and then treat it as one of the
    two anyway.

    Unlike a DENIAL: it cannot take the floor, even under `sparser`. An
    unproven denial is not a denial, and letting one act like a measurement is
    how a blocking gate fabricates a finding.

    Unlike SILENCE: it is REPORTED. The answer came out the same, but what we
    are entitled to say about it did not -- with silence the merge knows the
    other source had nothing; here it knows only that nobody classified it.
    """
    content = {"MX": {"met4": 61.5}}
    empty = {"MX": {}}

    unsure = merge_source_records([content, empty], on_conflict="sparser")
    assert unsure.merged["MX"] == {"met4": 61.5}, \
        "an unclassified empty took the floor as if it were a measurement"
    assert unsure.conflicts == [], "and it is not a disagreement either"

    kinds = {a["kind"] for a in unsure.absences}
    assert kinds == {"indeterminate-could-not-erase"}, kinds
    assert unsure.absences[0]["counts"] == {
        "speaks": 1, "silent": 0, "denies": 0, "indeterminate": 1}

    # the three states really are three: same inputs, same merged answer under
    # `richer`, three distinguishable reports
    reports = {}
    for name, st in (("silent", SILENT), ("denies", DENIES),
                     ("indeterminate", INDETERMINATE)):
        out = merge_source_records([content, empty], on_conflict="richer",
                                   stance=lambda _r, s=st: s)
        reports[name] = (json.dumps(out.conflicts, sort_keys=True, default=str),
                         json.dumps(out.absences, sort_keys=True, default=str))
    assert len(set(reports.values())) == 3, \
        f"two of the three states report identically: {reports}"


def test_the_report_names_the_state_when_every_source_is_empty():
    """No content anywhere. The key still survives and stays empty -- but
    "every source measured this empty" and "nobody said anything" are still
    different facts, and the one the report gives must be the true one."""
    both_empty = [{"k": {}}, {"k": {}}]
    for stance, expected in ((SILENT, "silent-everywhere"),
                             (DENIES, "denied-everywhere"),
                             (INDETERMINATE, "indeterminate-empty")):
        out = merge_source_records(both_empty, stance=lambda _r, s=stance: s)
        assert out.merged == {"k": {}}, stance
        assert [a["kind"] for a in out.absences] == [expected], stance


def test_a_stance_the_module_does_not_know_raises_rather_than_guessing():
    """Same argument as the unknown-policy case: an unrecognised stance quietly
    accepted is a classification nobody declared."""
    with pytest.raises(ValueError):
        merge_source_records([{"k": {}}], stance=lambda _r: "probably-empty")


def test_a_caller_cannot_declare_a_blank_to_be_a_measurement():
    """The over-correction on the new axis: if `stance=` could return SPEAKS,
    a caller could promote an empty record into content and the whole rule
    would be one lambda away from being switched off. Content is decided by
    the payload; the stance only says WHY an empty one is empty."""
    with pytest.raises(ValueError):
        merge_source_records([{"k": {}}], stance=lambda _r: "speaks")


def test_reporting_an_absence_never_changes_the_answer():
    """The report is a report. Under the policy that keeps content, the merged
    mapping must be byte-identical whichever of the three states the empties
    are declared to be -- otherwise the classification has become a second,
    undeclared policy."""
    sources = [{"a": {"x": 1}}, {"a": {}}, {"b": {}}, {"c": {"y": 2}}, {"b": {}}]
    answers = {json.dumps(merge_source_records(
        sources, on_conflict="richer", stance=lambda _r, s=st: s).merged,
        sort_keys=True)
        for st in (SILENT, DENIES, INDETERMINATE)}
    assert len(answers) == 1, answers


def test_the_absence_report_is_itself_order_independent():
    """A report that reordered when the files did would put the defect back in
    the one place a reader goes to check for it."""
    import itertools
    sources = [{"a": {"x": 1}}, {"a": {}}, {"b": {}}]
    rendered = {json.dumps(merge_source_records(
        list(p), stance=lambda _r: SILENT).absences, sort_keys=True, default=str)
        for p in itertools.permutations(sources)}
    assert len(rendered) == 1, rendered


def test_a_denial_that_wins_returns_the_record_it_was_given():
    """A denial taking the floor must yield an EMPTY record a source actually
    supplied -- not a fabricated blank, and not a blend. Same no-invention rule
    the content path obeys."""
    supplied = {"met0": 0.0}                  # a falsy-payload record with shape
    a = {"MX": {"blocked": {"met4": 61.5}, "size": (10.0, 20.0)}}
    b = {"MX": {"blocked": {}, "size": (10.0, 20.0), "note": supplied}}
    out = merge_source_records([a, b], content=lambda e: e.get("blocked"),
                               on_conflict="sparser", stance=lambda _r: DENIES)
    assert out.merged["MX"] is b["MX"], "the winner must be a supplied record"
    assert out.merged["MX"]["blocked"] == {}


def test_liberty_pin_directions_survive_a_pg_pin_only_declaration():
    """SITE 1+2, end to end through the real parser.

    `parse_liberty_pin_directions` yields `{cell: {}}` for a cell whose pins
    declare no `direction` -- a `pg_pin`-only block, which the parser documents
    as contributing nothing. Two liberties naming the same cell must not have
    the verdict decided by which one is passed last.

    Public grammar, nangate45-style cell name.
    """
    full = """
    library (lib_full) {
      cell (INV_X1) {
        pin (A) { direction : input; }
        pin (ZN) { direction : output; }
      }
    }
    """
    pg_only = """
    library (lib_pg) {
      cell (INV_X1) {
        pg_pin (VDD) { pg_type : primary_power; }
        pg_pin (VSS) { pg_type : primary_ground; }
      }
    }
    """
    d_full = auc.parse_liberty_pin_directions(full)
    d_pg = auc.parse_liberty_pin_directions(pg_only)
    assert d_full["INV_X1"] == {"A": "input", "ZN": "output"}
    assert d_pg["INV_X1"] == {}, "precondition: the empty record really is emitted"

    for order in ([d_full, d_pg], [d_pg, d_full]):
        merged = merge_source_records(order, on_conflict="richer").merged
        assert merged["INV_X1"] == {"A": "input", "ZN": "output"}


def test_erased_pin_map_would_have_inflated_coverage():
    """WHY it matters, measured through `classify()` rather than asserted.

    An emptied pin map makes `classify()` drop every instance of that cell, and
    with it the observability edges THROUGH the cell -- so nets upstream come
    back unobservable and are counted untestable. Coverage goes UP. This test
    pins the consequence so a future change that reintroduces the erase fails
    on the number, not just on the merge.
    """
    ports = {"pi": "input", "po": "output"}
    instances = [
        ("BUF_X1", "u1", {"A": "pi", "Z": "mid"}),
        ("BUF_X1", "u2", {"A": "mid", "Z": "po"}),
    ]
    good = {"BUF_X1": {"A": "input", "Z": "output"}}
    erased = {"BUF_X1": {}}

    r_good = auc.classify(ports, instances, good, auc.constant_cells(good))
    r_bad = auc.classify(ports, instances, erased, auc.constant_cells(erased))

    assert r_good["nets"], "precondition: the intact map builds a graph"
    assert not r_bad["nets"], "the erased map drops the whole cell out"
    assert r_bad["unresolved_cells"] == ["BUF_X1"]
    # and the erase is exactly what the merge now prevents
    merged = merge_source_records([good, erased], on_conflict="richer").merged
    assert merged == good


def test_atpg_cli_verdict_does_not_depend_on_liberty_argument_order(tmp_path):
    """SITE 1, at the CALL SITE, through `main()`.

    The property tests above exercise the parser and the helper. This one
    exercises the merge the program actually performs: two `--liberty` files
    naming the same cell, one of them `pg_pin`-only, in both orders. The
    reported untestable set must be identical.

    Public grammar; nangate45-style names; no PDK, vendor or SKU literal.
    """
    full = tmp_path / "a_full.lib"
    pg = tmp_path / "z_pg.lib"
    full.write_text("""
    library (l0) {
      cell (BUF_X1) { pin (A) { direction : input; } pin (Z) { direction : output; } }
      cell (INV_X1) { pin (A) { direction : input; } pin (ZN) { direction : output; } }
    }
    """)
    pg.write_text("""
    library (l1) {
      cell (BUF_X1) { pg_pin (VDD) { pg_type : primary_power; } }
    }
    """)
    netlist = tmp_path / "cut.v"
    netlist.write_text(
        "module top (pi, po);\n"
        "  input pi; output po; wire mid;\n"
        "  BUF_X1 u1 (.A(pi), .Z(mid));\n"
        "  BUF_X1 u2 (.A(mid), .Z(po));\n"
        "  INV_X1 u3 (.A(mid), .ZN(spare));\n"
        "endmodule\n")

    def run(first, second):
        out = tmp_path / f"o_{first.stem}.json"
        auc.main(["--netlist", str(netlist), "--top", "top",
                  "--liberty", str(first), "--liberty", str(second),
                  "--json", str(out)])
        return json.loads(out.read_text())

    forward = run(full, pg)          # `sorted()` order: a_full then z_pg
    reverse = run(pg, full)

    assert forward["unresolved_cells"] == reverse["unresolved_cells"]
    assert "BUF_X1" not in forward["unresolved_cells"], \
        "the pg_pin-only liberty erased the cell's real pin map"
    assert sorted(forward["uncontrollable"]) == sorted(reverse["uncontrollable"])
    assert sorted(forward["unobservable"]) == sorted(reverse["unobservable"])


def test_pdn_planner_sees_the_obstruction_whichever_lef_is_last():
    """SITE 3, at the CALL SITE, through the real planner.

    Two LEFs declare the same MACRO: one with an OBS blocking a stripe layer,
    one with no OBS at all. The observable: adding a LEF that says NOTHING about
    obstructions must not change the plan, in either order -- so both must equal
    the plan from the speaking LEF alone, and must NOT equal the plan from the
    silent LEF alone.

    Measured pre-fix: `blocked_layers []` instead of `['L4']`, and a stripe
    pitch of 12.0 instead of 10.0. Not a missing report -- a different PDN, from
    the same design, decided by argument order.
    """
    import importlib.util as ilu
    import re as _re

    spec = ilu.spec_from_file_location(
        "_erase_phase3", PROGRAMS / "phase3_one_shot_runner.py")
    R = ilu.module_from_spec(spec)
    sys.modules["_erase_phase3"] = R
    try:
        spec.loader.exec_module(R)
    except SystemExit:
        pass
    tspec = ilu.spec_from_file_location(
        "_erase_pdnfix", PROGRAMS / "tests" / "test_macro_pdn_grid.py")
    T = ilu.module_from_spec(tspec)
    sys.modules["_erase_pdnfix"] = T
    try:
        tspec.loader.exec_module(T)
    except SystemExit:
        pass

    lef = T.MACRO_LEF
    name = _re.search(r"MACRO\s+(\S+)", lef).group(1)
    m = _re.search(r"SIZE\s+([\d.]+)\s+BY\s+([\d.]+)\s*;", lef)
    w, h = m.group(1), m.group(2)
    body = (f"  OBS\n    LAYER OVERLAP ;\n      RECT 0 0 {w} {h} ;\n"
            f"    LAYER L4 ;\n      RECT 0 0 {w} {h} ;\n  END\n")
    with_obs = lef.replace(f"END {name}", body + f"END {name}", 1)
    no_obs = lef                       # same MACRO, says nothing about OBS

    def plan(texts):
        return R._macro_pdn_grid_outcome(texts, T.TECH_LEF, T.STRIPES, "L1")

    speaking = plan([with_obs])
    silent = plan([no_obs])
    a = plan([with_obs, no_obs])
    b = plan([no_obs, with_obs])

    # precondition: the two LEFs really do produce different plans, so the
    # assertions below are measuring something
    assert speaking["plan"] != silent["plan"]
    assert speaking["plan"]["blocked_layers"] == ["L4"]
    assert silent["plan"]["blocked_layers"] == []

    assert a["plan"] == b["plan"], "the plan depends on LEF argument order"
    assert a["plan"] == speaking["plan"], \
        "a LEF that says nothing about OBS erased the one that declared L4 blocked"
    assert [r["reason"] for r in a["refusals"]] == \
           [r["reason"] for r in b["refusals"]]


def _phase3_pdn():
    """`(runner_module, pdn_fixture_module)`, loaded once.

    Both are loaded from source by path rather than imported, because
    `programs/` is a flat directory and these two names are not packages.
    """
    import importlib.util as ilu
    mods = {}
    for alias, path in (("R", PROGRAMS / "phase3_one_shot_runner.py"),
                        ("T", PROGRAMS / "tests" / "test_macro_pdn_grid.py")):
        key = f"_erase_{alias}"
        if key in sys.modules:
            mods[alias] = sys.modules[key]
            continue
        spec = ilu.spec_from_file_location(key, path)
        mod = ilu.module_from_spec(spec)
        sys.modules[key] = mod
        try:
            spec.loader.exec_module(mod)
        except SystemExit:
            pass
        mods[alias] = mod
    return mods["R"], mods["T"]


def _lef_with_obs(base: str, *layers: str) -> str:
    """`base` with an OBS section blocking each of `layers` across the whole
    footprint. No `layers` at all still emits the OBS section, carrying only
    the `OVERLAP` placement extent -- a LEF that has LOOKED and found no
    routing blockage, which is a different statement from one that never
    mentions OBS.

    Pure LEF grammar; the layer names come from the caller's own tech fixture.
    """
    import re as _re
    name = _re.search(r"MACRO\s+(\S+)", base).group(1)
    m = _re.search(r"SIZE\s+([\d.]+)\s+BY\s+([\d.]+)\s*;", base)
    w, h = m.group(1), m.group(2)
    body = f"  OBS\n    LAYER OVERLAP ;\n      RECT 0 0 {w} {h} ;\n"
    for lay in layers:
        body += f"    LAYER {lay} ;\n      RECT 0 0 {w} {h} ;\n"
    body += "  END\n"
    return base.replace(f"END {name}", body + f"END {name}", 1)


def _fully_blocked_layers(R, T, *lef_texts) -> set:
    """Every layer any ONE of these LEFs declares blocked across the whole
    footprint, read one LEF at a time so no merge policy can enter the
    answer. This is the ground truth the planner must not fall below."""
    out = set()
    for text in lef_texts:
        for entry in R._macro_obs_layers_from_lef(text).values():
            for lay in (entry.get("blocked") or {}):
                if R._layer_is_fully_blocked(entry, lay) is True:
                    out.add(lay)
    return out


def test_pdn_planner_keeps_the_declared_blockage_when_two_lefs_disagree():
    """SITE 3, and the DIRECTION of its policy, pinned AT THE CALL SITE.

    `on_conflict=` is one word and the two directions are both defensible in
    the abstract, so nothing but a test can hold the planner to the one its own
    comment argues for. Measured: with the word flipped to `"sparser"` the
    whole suite still passed while the planner quietly lost a blockage.

    Two LEFs declare the same macro and BOTH speak: one blocks the two strap
    layers above the supply-pin layer, the other blocks only the lower of them.
    Keeping the sparser record drops L5 off the blocked list and the planner
    straps supply across metal the first LEF declares unroutable across the
    macro's whole footprint.

    The invariant asserted is the general one -- no strap may land on a layer
    ANY supplied LEF declares fully blocked -- so a different correct fix
    passes it, and it does not care how the policy is spelled.
    """
    R, T = _phase3_pdn()
    both = _lef_with_obs(T.MACRO_LEF, "L4", "L5")
    lower = _lef_with_obs(T.MACRO_LEF, "L4")

    declared = _fully_blocked_layers(R, T, both, lower)
    assert declared == {"L4", "L5"}, \
        f"precondition: the fixtures must really declare blockages: {declared}"

    for texts in ([both, lower], [lower, both]):
        out = R._macro_pdn_grid_outcome(texts, T.TECH_LEF, T.STRIPES, "L1")
        strap = (out["plan"] or {}).get("strap_layer")
        assert strap not in declared, (
            f"the planner strapped supply on {strap}, which a supplied LEF "
            f"declares blocked across the macro's whole footprint")
        # and the reason survives rather than the macro silently going ungridded
        assert out["plan"] is None
        assert [r["reason"] for r in out["refusals"]] == \
            ["ALL_CANDIDATE_LAYERS_BLOCKED_BY_MACRO_OBS"]
        assert out["refusals"][0]["blocked_layers"] == ["L4", "L5"]


def test_pdn_planner_will_not_let_an_empty_obs_section_unblock_a_layer():
    """The same direction, reached through the DENIAL path rather than through
    two speaking sources -- because that is the path the new stance opens.

    One LEF blocks L4. The other carries an OBS section that declares only the
    macro's placement extent: it has looked and measured no routing blockage,
    so it DENIES rather than being silent, and a denial is exactly what
    `on_conflict` is allowed to act on. At a PLANNER the answer must still be
    the blockage -- an over-read here costs one loud, non-fatal refusal record,
    while an under-read puts supply metal on obstructed layer.

    Flipping the policy word makes the denial win, L4 comes off the blocked
    list, and the strap lands on it.
    """
    R, T = _phase3_pdn()
    blocks_l4 = _lef_with_obs(T.MACRO_LEF, "L4")
    denies = _lef_with_obs(T.MACRO_LEF)              # OBS present, nothing blocked

    parsed = R._macro_obs_layers_from_lef(denies)
    entry = parsed["BLOCKA"]
    assert entry["blocked"] == {} and entry["obs_declared"] is True, \
        "precondition: this LEF measures no blockage rather than omitting OBS"

    declared = _fully_blocked_layers(R, T, blocks_l4, denies)
    assert declared == {"L4"}

    for texts in ([blocks_l4, denies], [denies, blocks_l4]):
        out = R._macro_pdn_grid_outcome(texts, T.TECH_LEF, T.STRIPES, "L1")
        assert out["plan"] is not None, "precondition: a grid is buildable here"
        assert out["plan"]["strap_layer"] not in declared, (
            f"a LEF measuring no obstruction unblocked layer "
            f"{out['plan']['strap_layer']}, which the other LEF declares "
            f"blocked across the macro's whole footprint")
        assert out["plan"]["strap_layer"] == "L5"
        assert out["plan"]["blocked_layers"] == ["L4"]


def test_a_lef_with_no_obs_section_is_silent_and_one_with_an_empty_obs_denies():
    """The parser-level fact the two call-site tests above rest on: `blocked ==
    {}` alone cannot separate "measured nothing" from "did not look", so the
    record carries which one it was. Without this the caller has nothing
    truthful to declare and the planner is back to guessing."""
    R, T = _phase3_pdn()
    no_obs = T.MACRO_LEF                       # never mentions OBS
    empty_obs = _lef_with_obs(T.MACRO_LEF)     # OBS present, no routing layer

    silent_entry = R._macro_obs_layers_from_lef(no_obs)["BLOCKA"]
    denial_entry = R._macro_obs_layers_from_lef(empty_obs)["BLOCKA"]

    assert silent_entry["blocked"] == denial_entry["blocked"] == {}, \
        "both really are empty -- that is why the flag is needed"
    assert silent_entry["obs_declared"] is False
    assert denial_entry["obs_declared"] is True


def test_payload_bitmap_byte_named_without_bits_does_not_blank_the_other_layer(tmp_path):
    """SITE 4, through the real `parse_bitmap`."""
    l3 = tmp_path / "l3.json"
    l4 = tmp_path / "l4.json"
    l3.write_text(json.dumps({"bit_layouts": {
        "status_byte": {"bit0": "busy", "bit1": "err"}}}))
    l4.write_text(json.dumps({"bit_layouts": {"status_byte": {}}}))

    both = pbp.parse_bitmap(None, l3, l4)
    swapped = pbp.parse_bitmap(None, l4, l3)
    assert both == swapped
    assert both["status_byte"] == {"bit0": "busy", "bit1": "err"}


# ═══════════════════════════════════════════════ 2. THE REVERSE CASE ══════
# What does the OVER-correction look like? Three ways this fix could be wrong
# in the other direction. Each of these must STILL pass.

def test_a_genuinely_empty_key_stays_empty_and_stays_present():
    """The over-correction: 'never let anything be empty' -- dropping the key
    entirely, or inventing content for it. A key every source describes as
    empty is a real, reportable fact and must survive as one.

    This is the one that catches tightening a filter until a count reaches
    zero: `parse_bitmap` returning nothing at all would suppress the
    `empty_bitmap` WARN that tells a user their bitmap said nothing.
    """
    merged, conflicts, _ = merge_source_records([{"k": {}}, {"k": {}}])
    assert "k" in merged, "the key must not be dropped"
    assert merged["k"] == {}, "and must not be given invented content"
    assert conflicts == []


def test_empty_bitmap_warning_still_fires_when_every_layer_is_silent(tmp_path):
    """Same over-correction, through the real program: if the fix suppressed
    empty records the user would lose the warning that their input said
    nothing -- trading a silent under-check for a silent no-check."""
    l3 = tmp_path / "l3.json"
    l3.write_text(json.dumps({"bit_layouts": {"status_byte": {}}}))
    rtl = tmp_path / "d.v"
    rtl.write_text("module d(input wire clk); endmodule\n")

    bitmap = pbp.parse_bitmap(None, l3, None)
    assert bitmap == {"status_byte": {}}
    findings = pbp.audit(rtl, bitmap)
    assert any(f.rule == "empty_bitmap" for f in findings), \
        "an all-silent bitmap must still be reported as saying nothing"


def test_merge_does_not_union_records_into_content_no_source_declared():
    """The other over-correction, and the dangerous one on a blocking gate:
    'keep everything' by unioning the two records. That FABRICATES a record
    no source ever declared -- the failure mode where a gate invents a
    violation and stops a clean design.

    The merge must return one of the records it was GIVEN, never a blend.
    """
    a = {"MX": {"met1": 5.0}}
    b = {"MX": {"met2": 7.0}}
    merged, conflicts, _ = merge_source_records([a, b], on_conflict="richer")
    assert merged["MX"] in ({"met1": 5.0}, {"met2": 7.0})
    assert merged["MX"] != {"met1": 5.0, "met2": 7.0}, "records must not blend"
    assert conflicts, "and the disagreement must be reported, not swallowed"


def test_sparser_policy_cannot_manufacture_a_finding():
    """`on_conflict="sparser"` exists so a BLOCKING gate takes the floor. Pin
    that it really does: the smaller record wins in either order."""
    small = {"MX": {"met1": 1.0}}
    large = {"MX": {"met1": 1.0, "met2": 2.0, "met3": 3.0}}
    for order in ([small, large], [large, small]):
        merged = merge_source_records(order, on_conflict="sparser").merged
        assert merged["MX"] == {"met1": 1.0}


def test_single_source_and_no_source_are_untouched():
    """The fix must be inert where there was nothing to fix."""
    one = {"a": {"x": 1}, "b": {}}
    merged, conflicts, _ = merge_source_records([one])
    assert merged == one and conflicts == []
    assert merge_source_records([]).merged == {}
    assert merge_source_records([None, {}, None]).merged == {}


def test_unknown_policy_raises_rather_than_silently_reordering():
    with pytest.raises(ValueError):
        merge_source_records([{"k": {"x": 1}}], on_conflict="last-wins")


# ══════════════════════════════════════════════════════════ 3. THE GUARD ══════

_DEFECTIVE = '''
from typing import Any, Dict

def parse_one(text: str) -> Dict[str, Dict[str, Any]]:
    return {}

def audit(sources):
    acc: Dict[str, Dict[str, Any]] = {}
    for t in sources:
        acc.update(parse_one(t))
    return acc
'''

_ALIASED = '''
from pathlib import Path
from typing import Dict

def parse_one(text: str) -> Dict[str, Dict[str, str]]:
    return {}

def audit(paths):
    acc: Dict[str, Dict[str, str]] = {}
    for lp in paths:
        p = Path(lp)
        if p.is_file():
            acc.update(parse_one(p.read_text()))
    return acc
'''


def _scan(src: str, tmp_path: Path, name: str = "m.py"):
    (tmp_path / name).write_text(src)
    return guard.sweep(tmp_path)


def test_guard_fires_on_the_shape(tmp_path):
    found = _scan(_DEFECTIVE, tmp_path)
    assert len(found) == 1
    assert found[0]["rule"] == "empty-record-cannot-erase"
    assert found[0]["accumulator"] == "acc"


def test_guard_fires_on_the_or_equals_spelling_of_the_same_merge(tmp_path):
    """`acc |= parse_one(t)` is `acc.update(parse_one(t))` with the same
    last-wins semantics and one token instead of seven. A guard that knows only
    the method call is a guard that a tidy-up walks straight past -- and the
    edit needs no intent to be an evasion, which is worse, because then nobody
    is looking for it.

    Measured elsewhere this session: a guard whose predicate keyed on a literal
    spelling was evaded by changing a double quote to a single quote."""
    src = _DEFECTIVE.replace("acc.update(parse_one(t))", "acc |= parse_one(t)")
    assert "|=" in src and ".update(" not in src, "precondition: the rewrite took"
    found = _scan(src, tmp_path)
    assert len(found) == 1, "the `|=` spelling walked past the guard"
    assert found[0]["accumulator"] == "acc"


def test_guard_follows_the_source_through_an_alias(tmp_path):
    """The measured site reaches the parser through `p = Path(lp)`. A guard
    that only matched the loop target directly would miss it."""
    assert len(_scan(_ALIASED, tmp_path)) == 1


def test_guard_abstains_on_a_set_accumulator(tmp_path):
    """A set merges by UNION; nothing can be erased. Firing here would be
    noise, and noise is how a guard gets switched off."""
    src = '''
from typing import Dict, Set

def parse_one(text: str) -> Dict[str, Dict[str, str]]:
    return {}

def audit(sources):
    acc: Set[str] = set()
    for t in sources:
        acc.update(parse_one(t))
    return acc
'''
    assert _scan(src, tmp_path) == []


def test_guard_abstains_on_scalar_valued_records(tmp_path):
    """`Dict[str, int]` / `Dict[str, str]`: a scalar has no 'present but empty'
    state, so a source cannot be silent about a key it names. Re-stating the
    same scalar erases nothing.

    This is the clause that keeps the guard off the legitimate merges measured
    in this repo (flow layer refs, localparam values, subckt terminal counts).
    """
    for value_type in ("int", "str", "float", "bool"):
        src = f'''
from typing import Dict

def parse_one(text: str) -> Dict[str, {value_type}]:
    return {{}}

def audit(sources):
    acc: Dict[str, {value_type}] = {{}}
    for t in sources:
        acc.update(parse_one(t))
    return acc
'''
        assert _scan(src, tmp_path, f"m_{value_type}.py") == [], value_type


def test_guard_abstains_when_it_cannot_tell(tmp_path):
    """No annotation, or a bare `dict`: the guard does not know whether the
    value is a record, so it says nothing. Abstaining is the safe direction --
    a missed site is a gap, a wrong site is why guards get deleted."""
    for returns in ("", " -> dict", " -> Dict"):
        src = f'''
from typing import Dict

def parse_one(text){returns}:
    return {{}}

def audit(sources):
    acc: Dict[str, dict] = {{}}
    for t in sources:
        acc.update(parse_one(t))
    return acc
'''
        assert _scan(src, tmp_path, "m_u.py") == [], returns


def test_guard_abstains_on_a_merge_that_is_not_per_source(tmp_path):
    """`for c in (spec, spec.get("specs")): acc.update(c)` flattens ONE already
    loaded object. There is no second source, so there is no discovery order to
    depend on."""
    src = '''
from typing import Any, Dict

def generate(spec):
    acc: Dict[str, Any] = {}
    for container in (spec, spec.get("specs"), spec.get("targets")):
        if isinstance(container, dict):
            acc.update(container)
    return acc
'''
    assert _scan(src, tmp_path) == []


def test_guard_accepts_the_fixed_form(tmp_path):
    """The site stops being flagged by actually changing -- not by being named
    in an exclusion list. There is no such list to add it to."""
    src = '''
from typing import Any, Dict
from _source_record_merge import merge_source_records

def parse_one(text: str) -> Dict[str, Dict[str, Any]]:
    return {}

def audit(sources):
    acc, conflicts = merge_source_records(
        [parse_one(t) for t in sources], on_conflict="richer")
    return acc
'''
    assert _scan(src, tmp_path) == []


def test_guard_exit_codes_and_report(tmp_path):
    (tmp_path / "m.py").write_text(_DEFECTIVE)
    out = tmp_path / "r.json"
    rc = guard.main(["--root", str(tmp_path), "--json", str(out)])
    assert rc == guard.RC_FOUND
    payload = json.loads(out.read_text())
    assert payload["count"] == 1
    assert payload["skipped_prefixes"] == []
    # the funnel travels with the machine-readable report too, so a consumer
    # can tell a clean sweep from one that never got started
    assert payload["clause_funnel"]["candidates"] == 1
    assert payload["clause_funnel"]["record_valued_producer"] == 1

    (tmp_path / "m.py").write_text("x = 1\n")
    assert guard.main(["--root", str(tmp_path)]) == guard.RC_CLEAN
    assert guard.main(["--root", str(tmp_path / "nope")]) == guard.RC_USAGE


def test_guard_reports_what_it_left_out(tmp_path):
    """A narrowed sweep must not read as a full one."""
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "m.py").write_text(_DEFECTIVE)
    out = tmp_path / "r.json"
    rc = guard.main(["--root", str(tmp_path), "--skip", "sub", "--json", str(out)])
    assert rc == guard.RC_CLEAN
    payload = json.loads(out.read_text())
    assert payload["skipped_prefixes"] == ["sub"]


def test_guard_runs_clean_on_the_programs_directory():
    """CORPUS SWEEP, as a test.

    This asserted `<= 1` while the ORIGINAL measured instance of this defect --
    `macro_obs_geometry_intersect_check.py` -- was still in flight on its own
    branch. It has landed, so the exception has no subject and the assertion is
    the plain one: ZERO. A tolerance kept past the thing it tolerated is an
    exclusion list with better manners.
    """
    findings = guard.sweep(PROGRAMS)
    names = sorted({f["file"] for f in findings})
    assert findings == [], f"a per-source record merge is present: {names}"


def test_the_sweep_actually_reaches_its_decision_point():
    """A CLEAN SWEEP AND A SWEEP THAT NEVER RAN LOOK IDENTICAL FROM THE EXIT
    CODE. Measured elsewhere this session: a corpus sweep reported exit 0 with
    all 756 cases returning NOT_COMPARABLE -- the guard's decision point was
    never entered and nothing in the output said so.

    So the sweep counts what reached each clause, and this holds the real
    corpus to a funnel that actually descends. If a refactor turned every
    candidate away at clause 1, the exit code would stay 0, the report would
    stay `[PASS]`, and this test would fail -- which is the only place that
    difference can be caught.
    """
    stats = guard.new_stats()
    findings = guard.sweep(PROGRAMS, stats=stats)

    assert stats["candidates"] > 0, \
        "no accumulator-merge candidate at all: the sweep matched nothing"
    assert stats["source_dependent"] > 0, \
        "no candidate was per-source: clause 2 never selected anything"
    assert stats["mapping_accumulator"] > 0, (
        "clause 3 admitted no mapping accumulator, so the load-bearing clause "
        "4 was never reached and the PASS is vacuous")
    # the funnel must be monotone -- each clause is a filter on the last
    assert (stats["candidates"] >= stats["source_dependent"]
            >= stats["mapping_accumulator"] >= stats["record_valued_producer"])
    assert stats["record_valued_producer"] == len(findings)
