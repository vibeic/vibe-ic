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
from _source_record_merge import merge_source_records   # noqa: E402


# ══════════════════════════════════════════════════════════ 1. THE RULE ══════

def test_empty_record_does_not_erase_a_populated_one_in_either_order():
    """THE defect, at its smallest. Both orders must give the same answer, and
    that answer must be the one that carries the content."""
    speaks = {"CELL_A": {"A": "input", "Y": "output"}}
    silent = {"CELL_A": {}}

    forward, _ = merge_source_records([speaks, silent])
    reverse, _ = merge_source_records([silent, speaks])

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
    answers = {json.dumps(merge_source_records(list(p))[0], sort_keys=True)
               for p in itertools.permutations(sources)}
    assert len(answers) == 1, "merge result depends on source order"


def test_content_callable_sees_emptiness_one_level_down():
    """A record can be TRUTHY and still say nothing. `{"blocked": {}, "size":
    (10, 20)}` is the measured shape; without `content=` its truthiness hides
    the silence and the erase comes straight back."""
    speaks = {"MX": {"blocked": {"met4": 61.5}, "size": (10.0, 20.0)}}
    silent = {"MX": {"blocked": {}, "size": (10.0, 20.0)}}

    naive, _ = merge_source_records([speaks, silent])
    assert naive["MX"]["blocked"] == {}, "plain truthiness cannot see this"

    aware, _ = merge_source_records([speaks, silent],
                                    content=lambda e: e.get("blocked"))
    reverse, _ = merge_source_records([silent, speaks],
                                      content=lambda e: e.get("blocked"))
    assert aware["MX"]["blocked"] == {"met4": 61.5}
    assert aware == reverse


def test_disagreement_between_two_speaking_sources_is_reported_not_hidden():
    a = {"k": {"x": 1}}
    b = {"k": {"x": 1, "y": 2}}
    richer, conflicts = merge_source_records([a, b], on_conflict="richer")
    sparser, conflicts2 = merge_source_records([b, a], on_conflict="sparser")

    assert richer["k"] == {"x": 1, "y": 2}
    assert sparser["k"] == {"x": 1}
    assert [c["key"] for c in conflicts] == ["k"]
    assert [c["key"] for c in conflicts2] == ["k"]


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
        merged, _ = merge_source_records(order, on_conflict="richer")
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
    merged, _ = merge_source_records([good, erased], on_conflict="richer")
    assert merged == good


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
    merged, conflicts = merge_source_records([{"k": {}}, {"k": {}}])
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
    merged, conflicts = merge_source_records([a, b], on_conflict="richer")
    assert merged["MX"] in ({"met1": 5.0}, {"met2": 7.0})
    assert merged["MX"] != {"met1": 5.0, "met2": 7.0}, "records must not blend"
    assert conflicts, "and the disagreement must be reported, not swallowed"


def test_sparser_policy_cannot_manufacture_a_finding():
    """`on_conflict="sparser"` exists so a BLOCKING gate takes the floor. Pin
    that it really does: the smaller record wins in either order."""
    small = {"MX": {"met1": 1.0}}
    large = {"MX": {"met1": 1.0, "met2": 2.0, "met3": 3.0}}
    for order in ([small, large], [large, small]):
        merged, _ = merge_source_records(order, on_conflict="sparser")
        assert merged["MX"] == {"met1": 1.0}


def test_single_source_and_no_source_are_untouched():
    """The fix must be inert where there was nothing to fix."""
    one = {"a": {"x": 1}, "b": {}}
    merged, conflicts = merge_source_records([one])
    assert merged == one and conflicts == []
    assert merge_source_records([])[0] == {}
    assert merge_source_records([None, {}, None])[0] == {}


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

    KNOWN, DECLARED EXCEPTION -- and it is not an exclusion list:
    `macro_obs_geometry_intersect_check.py` is the ORIGINAL measured instance
    of this defect and is fixed by a separate open PR, not by this one. Until
    that lands, this repository has exactly one matching site and it is a real
    defect, so the guard is RIGHT to fire on it. Asserting `<= 1` rather than
    `== 0` is what makes this test tell the truth in both worlds: it goes green
    at 0 the moment that PR merges, and it fails at 2 if a new site appears.
    """
    findings = guard.sweep(PROGRAMS)
    names = sorted({f["file"] for f in findings})
    assert len(findings) <= 1, f"a NEW per-source record merge appeared: {names}"
    if findings:
        assert names == ["macro_obs_geometry_intersect_check.py"], names
