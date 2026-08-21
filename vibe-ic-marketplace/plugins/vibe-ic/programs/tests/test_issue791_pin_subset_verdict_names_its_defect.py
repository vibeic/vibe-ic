"""ORGANIC #791 — one verdict was hiding two defects.

``R_pin_table_subset_ports`` answers "is every L1 pin present in L9?".  When it
is not, the reason is one of two things that live in DIFFERENT files:

  * the L1 pin table carries a token that was never a pin at all (an enum /
    register identifier, a language keyword, an SDC directive, a stdcell
    library token, the design's own module name, a glob) — repair the L1
    EXTRACTOR;
  * a pin the documents really do declare never reached L9 — the chip-top
    wrapper is generated from L9, so the port is gone from the design; repair
    L9.

Before this change both produced the SAME string.  ``test_the_two_defects_were
_byte_identical_before_the_split`` is the reproduction: two fixtures differing
ONLY in the structure of the L1 entry (same pin name, same L9, same count)
whose legacy verdict fields are byte-identical, and whose causes now differ.

The split must not FILTER.  ``test_a_genuinely_absent_port_is_not_silenced``
and ``test_the_legacy_verdict_is_unchanged`` are the second direction of the
negative control: a fix that made the extractor noise disappear would take the
genuinely-lost ports with it.

chip-AGNOSTIC: HDL identifier syntax, IEEE reserved words and the design's own
extracted name only.  No chip, vendor, PDK or IC literal participates.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import l_doc_cross_consistency_check as M  # noqa: E402

from l_doc_cross_consistency_check import check, main  # noqa: E402

# Read the cause names through `getattr` with the literal as the fallback, so
# this module still IMPORTS against the byte-identical pre-split gate.  Every
# assertion below then fails on the EMITTED verdict -- the thing a maintainer
# actually reads -- rather than on a symbol the old program did not export.
CAUSE_L1_NON_PORT = getattr(M, "CAUSE_L1_NON_PORT", "L1_PIN_TABLE_NON_PORT")
CAUSE_L9_INCOMPLETE = getattr(M, "CAUSE_L9_INCOMPLETE",
                              "L9_PORT_LIST_INCOMPLETE")
CAUSE_UNATTRIBUTED = getattr(M, "CAUSE_UNATTRIBUTED", "UNATTRIBUTED")


def _w(d: Path, name: str, blob) -> None:
    gd = d / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    (gd / name).write_text(json.dumps(blob), encoding="utf-8")


def _rel(tmp_path: Path):
    _verdict, findings, _s = check(tmp_path)
    return {f.relation: f for f in findings}["R_pin_table_subset_ports"]


def _causes(finding):
    return {c["pin"]: c["cause"]
            for c in (getattr(finding, "causes", None) or [])}


def _cause_records(finding):
    return getattr(finding, "causes", None) or []


# The L9 both fixtures share: two real ports, and NO `vref`.
_L9 = {"ic_name": "demo", "top_module": "demo_top",
       "ports": [{"name": "clk"}, {"name": "rst_n"}]}

# Defect A only — `vref` is in the pin table but no walker ever established it
# as a port (`mode="unspecified"` is the extractor's own "I looked and could
# not tell" marker).
_L1_DEFECT_A = {"ic_name": "demo", "pin_table": [
    {"name": "clk", "mode": "input"},
    {"name": "rst_n", "mode": "input"},
    {"name": "vref", "mode": "unspecified", "function": "see datasheet"},
]}

# Defect B only — `vref` IS a declared port: a direction AND a port-only
# attribute only a real declaration site can fill.  L9 lost it.
_L1_DEFECT_B = {"ic_name": "demo", "pin_table": [
    {"name": "clk", "mode": "input"},
    {"name": "rst_n", "mode": "input"},
    {"name": "vref", "mode": "inout", "io_standard": "ANALOG", "width": 1},
]}


def test_defect_a_alone_is_named_an_l1_extraction_defect(tmp_path):
    _w(tmp_path, "L1_DATASHEET.json", _L1_DEFECT_A)
    _w(tmp_path, "L9_INTEGRATION_SPEC.json", _L9)
    f = _rel(tmp_path)
    assert f.verdict == "FAIL"
    assert _causes(f) == {"vref": CAUSE_L1_NON_PORT}, f.causes
    assert CAUSE_L1_NON_PORT in f.detail
    assert CAUSE_L9_INCOMPLETE not in f.detail, (
        "an L1 extraction defect was reported as an L9 completeness defect — "
        "the reader is sent to the wrong file: %r" % (f.detail,))


def test_defect_b_alone_is_named_an_l9_completeness_defect(tmp_path):
    _w(tmp_path, "L1_DATASHEET.json", _L1_DEFECT_B)
    _w(tmp_path, "L9_INTEGRATION_SPEC.json", _L9)
    f = _rel(tmp_path)
    assert f.verdict == "FAIL"
    assert _causes(f) == {"vref": CAUSE_L9_INCOMPLETE}, f.causes
    assert CAUSE_L9_INCOMPLETE in f.detail
    assert CAUSE_L1_NON_PORT not in f.detail
    assert [c["severity"] for c in _cause_records(f)] == ["ERROR"]


def test_the_two_defects_were_byte_identical_before_the_split(tmp_path):
    """THE REPRODUCTION — the issue's claim, verified.

    The two fixtures differ ONLY in the structure of one L1 entry.  Every
    field the pre-split verdict carried (verdict, count, violations) is
    byte-identical between them, so the old output could not tell a
    maintainer which file to open.  The causes now can.
    """
    a, b = tmp_path / "a", tmp_path / "b"
    _w(a, "L1_DATASHEET.json", _L1_DEFECT_A)
    _w(a, "L9_INTEGRATION_SPEC.json", _L9)
    _w(b, "L1_DATASHEET.json", _L1_DEFECT_B)
    _w(b, "L9_INTEGRATION_SPEC.json", _L9)
    fa, fb = _rel(a), _rel(b)
    # Everything the OLD verdict carried is identical ...
    assert fa.verdict == fb.verdict == "FAIL"
    assert fa.violations == fb.violations == ["vref"]
    assert (fa.detail.split(" — ")[0] == fb.detail.split(" — ")[0]
            == "1 L1 pin(s) absent from L9 ports[ports]")
    # ... and the two defects are nevertheless different ones.
    assert _causes(fa) != _causes(fb), (
        "the split does not separate the two defects: both report %r"
        % (_causes(fa),))


def test_the_legacy_verdict_is_unchanged(tmp_path):
    """ATTRIBUTION ONLY — the split may not filter.

    Verdict, violation list and exit code must be exactly what they were, or
    the "fix" has silenced part of the population.
    """
    for l1 in (_L1_DEFECT_A, _L1_DEFECT_B):
        d = tmp_path / ("case%d" % id(l1))
        _w(d, "L1_DATASHEET.json", l1)
        _w(d, "L9_INTEGRATION_SPEC.json", _L9)
        f = _rel(d)
        assert f.verdict == "FAIL"
        assert f.violations == ["vref"]
        assert main([str(d)]) == 1


def test_a_genuinely_absent_port_is_not_silenced(tmp_path):
    """NEGATIVE CONTROL, direction 2 (the one the issue insists on).

    A design whose L1 legitimately names a port L9 omits must still FAIL, and
    must be named as an L9 defect — never quietly reclassified into the noisy
    bucket and never dropped.
    """
    _w(tmp_path, "L1_DATASHEET.json", _L1_DEFECT_B)
    _w(tmp_path, "L9_INTEGRATION_SPEC.json", _L9)
    f = _rel(tmp_path)
    assert f.verdict == "FAIL"
    assert "vref" in f.violations
    assert _causes(f)["vref"] == CAUSE_L9_INCOMPLETE
    assert main([str(tmp_path)]) == 1


def test_a_clean_design_still_passes(tmp_path):
    """NEGATIVE CONTROL, direction 1 — no absent pin, no attribution."""
    _w(tmp_path, "L1_DATASHEET.json", {"ic_name": "demo", "pin_table": [
        {"name": "clk", "mode": "input"}, {"name": "rst_n", "mode": "input"}]})
    _w(tmp_path, "L9_INTEGRATION_SPEC.json", _L9)
    f = _rel(tmp_path)
    assert f.verdict == "PASS"
    assert not _cause_records(f)
    assert main([str(tmp_path)]) == 0


def test_decisive_non_port_token_classes_are_named_l1_defects(tmp_path):
    """Each decisive class names ITSELF, so the reader knows what to remove.

    `wbs_*` is a glob, `input` is a language keyword, `demo_top` is the
    design's own module.  None can ever be a port, whatever direction the
    entry happens to carry — so each must be an L1 defect even when a
    direction IS present.
    """
    _w(tmp_path, "L1_DATASHEET.json", {"ic_name": "demo", "pin_table": [
        {"name": "wbs_*", "mode": "input", "io_standard": "LVCMOS"},
        {"name": "input", "mode": "input", "io_standard": "LVCMOS"},
        {"name": "demo_top", "mode": "output", "io_standard": "LVCMOS"},
    ]})
    _w(tmp_path, "L9_INTEGRATION_SPEC.json", _L9)
    f = _rel(tmp_path)
    assert f.verdict == "FAIL"
    assert set(_causes(f).values()) == {CAUSE_L1_NON_PORT}, f.causes
    assert {c["pin"]: c["reason"] for c in _cause_records(f)} == {
        "wbs_*": "not_an_hdl_identifier",
        "input": "hdl_reserved_word",
        "demo_top": "design_own_module_name",
    }


def test_an_undecidable_pin_is_not_guessed_onto_either_side(tmp_path):
    """The third bucket exists because the corpus really is silent.

    A direction was established but nothing corroborates a declaration site.
    Guessing L9 would manufacture a port defect; guessing L1 would silence a
    real one.  It must say so.
    """
    _w(tmp_path, "L1_DATASHEET.json", {"ic_name": "demo", "pin_table": [
        {"name": "gcm_aad", "mode": "input", "function": "input"}]})
    _w(tmp_path, "L9_INTEGRATION_SPEC.json", _L9)
    f = _rel(tmp_path)
    assert f.verdict == "FAIL"
    assert _causes(f) == {"gcm_aad": CAUSE_UNATTRIBUTED}, f.causes
    assert CAUSE_UNATTRIBUTED in f.detail


def test_a_name_derived_io_standard_does_not_corroborate(tmp_path):
    """A supply RAIL out of a voltage table must not read as a lost port.

    The Phase-1 extractor DERIVES ``io_standard`` ``POWER`` / ``GROUND`` from
    the pin's own NAME, while every other value needs positive evidence in the
    doc text.  Accepting the derived marker as corroboration would let the name
    vouch for itself, and a rail lifted out of a "Supplies / levels" table
    would be reported as a port L9 lost -- sending the reader to the wrong
    file, which is the whole defect this split exists to remove.
    """
    _w(tmp_path, "L1_DATASHEET.json", {"ic_name": "demo", "pin_table": [
        # name-derived marker: corroborates nothing
        {"name": "iovdd", "mode": "input", "io_standard": "POWER"},
        # doc-evidenced JEDEC standard: real corroboration
        {"name": "hsync", "mode": "input", "io_standard": "3.3-V LVTTL"},
    ]})
    _w(tmp_path, "L9_INTEGRATION_SPEC.json", _L9)
    f = _rel(tmp_path)
    assert _causes(f) == {"iovdd": CAUSE_UNATTRIBUTED,
                          "hsync": CAUSE_L9_INCOMPLETE}, f.causes


def test_a_pin_with_no_direction_key_at_all_is_not_blamed_on_l1(tmp_path):
    """A MISSING direction key is not the same evidence as `unspecified`.

    `mode="unspecified"` is a walker's explicit "I could not establish one".
    No key at all means no walker recorded anything — which establishes
    nothing, and must not be read as proof the name is not a port.
    """
    _w(tmp_path, "L1_DATASHEET.json", {"ic_name": "demo", "pin_table": [
        {"name": "o_wb_ext_adr"}]})
    _w(tmp_path, "L9_INTEGRATION_SPEC.json", _L9)
    f = _rel(tmp_path)
    assert _causes(f) == {"o_wb_ext_adr": CAUSE_UNATTRIBUTED}, f.causes


def test_empty_l9_port_list_branch_is_attributed_too(tmp_path):
    """The other FAIL branch conflated the same two defects."""
    _w(tmp_path, "L1_DATASHEET.json", {"ic_name": "demo", "pin_table": [
        {"name": "hsync", "mode": "input", "io_standard": "3.3-V LVTTL"},
        {"name": "bits", "mode": "unspecified"},
    ]})
    _w(tmp_path, "L9_INTEGRATION_SPEC.json", {"ic_name": "demo", "ports": []})
    f = _rel(tmp_path)
    assert f.verdict == "FAIL"
    assert _causes(f) == {"hsync": CAUSE_L9_INCOMPLETE,
                          "bits": CAUSE_L1_NON_PORT}, f.causes


def test_causes_survive_json_serialisation(tmp_path):
    """The attribution has to reach the report a maintainer actually reads."""
    _w(tmp_path, "L1_DATASHEET.json", _L1_DEFECT_B)
    _w(tmp_path, "L9_INTEGRATION_SPEC.json", _L9)
    out = tmp_path / "r.json"
    assert main([str(tmp_path), "--json", str(out)]) == 1
    blob = json.loads(out.read_text())
    rel = [f for f in blob["findings"]
           if f["relation"] == "R_pin_table_subset_ports"][0]
    assert rel["causes"] == [{"pin": "vref", "cause": CAUSE_L9_INCOMPLETE,
                              "reason": "port_declaration_corroborated_by_io_standard",
                              "severity": "ERROR"}]
