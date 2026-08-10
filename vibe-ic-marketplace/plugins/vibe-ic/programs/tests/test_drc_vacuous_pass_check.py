"""Unit tests for drc_vacuous_pass_check.py.

Covers the discriminator between an EARNED 0-DRC verdict and a VACUOUS one,
plus honest SKIP/INCONCLUSIVE on missing/garbage input.

The decision rests on a MEASURED observable (shape records in the layout the
run consumed), never on the tool's phrasing. The wording-independence tests
are the load-bearing ones: this program exists to close a false-clean hole, so
its NEGATIVE behaviour is what has to hold.
"""
import struct
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "drc_vacuous_pass_check.py"
assert SCRIPT.exists(), f"Script not found: {SCRIPT}"

sys.path.insert(0, str(SCRIPT.parent))
import drc_vacuous_pass_check as dvp  # noqa: E402


# ---------------------------------------------------------------------------
# GDSII fixture builder — a real, well-formed layout with N drawn shapes, so a
# populated vs an empty layout differ in the FILE, not in any prose.
# ---------------------------------------------------------------------------
def _rec(rtype: int, dtype: int, body: bytes = b"") -> bytes:
    return struct.pack(">HBB", len(body) + 4, rtype, dtype) + body


def _write_gds(path: Path, n_shapes: int = 0, cell: str = "top_design") -> Path:
    name = cell.encode()
    if len(name) % 2:
        name += b"\x00"
    out = (_rec(0x00, 0x02, struct.pack(">h", 600))     # HEADER
           + _rec(0x01, 0x02, b"\x00" * 24)             # BGNLIB
           + _rec(0x02, 0x06, b"LIB\x00")               # LIBNAME
           + _rec(0x03, 0x05, b"\x00" * 16)             # UNITS
           + _rec(0x05, 0x02, b"\x00" * 24)             # BGNSTR
           + _rec(0x06, 0x06, name))                    # STRNAME
    for _ in range(n_shapes):
        xy = [(0, 0), (100, 0), (100, 100), (0, 100), (0, 0)]
        out += (_rec(0x08, 0x00)                        # BOUNDARY
                + _rec(0x0D, 0x02, struct.pack(">h", 67))   # LAYER
                + _rec(0x0E, 0x02, struct.pack(">h", 20))   # DATATYPE
                + _rec(0x10, 0x03, b"".join(struct.pack(">ii", x, y) for x, y in xy))
                + _rec(0x11, 0x00))                     # ENDEL
    out += _rec(0x07, 0x00) + _rec(0x04, 0x00)          # ENDSTR + ENDLIB
    path.write_bytes(out)
    return path


# The SAME report text for every wording test: only the LAYOUT differs, which
# is the whole point — the verdict must track the geometry, not the prose.
_CLEAN_LOG = (
    "KLayout DRC engine\n"
    "Loading layout file top_design.gds\n"
    "Top cell: top_design\n"
    "DRC deck: pdk_mr.drc\n"
    "Total errors: 0\n"
)


# ---------------------------------------------------------------------------
# PASS: 0 violations WITH proof geometry was loaded -> earned clean
# ---------------------------------------------------------------------------
def test_earned_clean_magic_geometry(tmp_path):
    log = tmp_path / "magic_drc.log"
    log.write_text(
        "Loading user_proj_example\n"
        "Reading cell user_proj_example\n"
        "12345 rectangles\n"
        "DRC checking complete.\n"
        "Total DRC errors found: 0\n"
    )
    res = dvp.audit(tmp_path)
    assert res.verdict == "PASS"
    assert res.passed is True
    assert any(f.rule == "DRC_CLEAN_EARNED" for f in res.findings)


def test_earned_clean_klayout_shape_count(tmp_path):
    log = tmp_path / "klayout.drc.txt"
    log.write_text(
        "Layout read\n"
        "cells: 87\n"
        "98765 shapes\n"
        "DRC violations: 0\n"
    )
    res = dvp.audit(tmp_path)
    assert res.verdict == "PASS"
    assert res.passed is True


# ---------------------------------------------------------------------------
# INCONCLUSIVE: 0 violations on a provably EMPTY layout (the real bug)
# ---------------------------------------------------------------------------
def test_vacuous_explicit_empty_token(tmp_path):
    log = tmp_path / "drc.rpt"
    log.write_text(
        "Reading GDS...\n"
        "Cell contains no geometry\n"
        "0 cells\n"
        "Total DRC errors: 0\n"
    )
    res = dvp.audit(tmp_path)
    assert res.verdict == "INCONCLUSIVE"
    assert res.passed is False
    assert any(f.rule == "DRC_VACUOUS_PASS" for f in res.findings)


def test_vacuous_no_geometry_evidence(tmp_path):
    # Clean 0-count but NOTHING that proves geometry was loaded.
    log = tmp_path / "drc.log"
    log.write_text("DRC is clean\n0 violations\n")
    res = dvp.audit(tmp_path)
    assert res.verdict == "INCONCLUSIVE"
    assert res.passed is False
    assert any(f.rule == "DRC_VACUOUS_PASS" for f in res.findings)


# ---------------------------------------------------------------------------
# PASS: nonzero violations -> not vacuous, defer to count gate
# ---------------------------------------------------------------------------
def test_nonzero_count_not_vacuous(tmp_path):
    log = tmp_path / "drc.rpt"
    log.write_text("Loading top\nTotal DRC errors: 7\nspacing violation x7\n")
    res = dvp.audit(tmp_path)
    assert res.verdict == "PASS"
    assert res.passed is True
    assert any(f.rule == "DRC_NONZERO_COUNT" for f in res.findings)


# ---------------------------------------------------------------------------
# SKIP: no DRC log at all (honest — never a vacuous PASS)
# ---------------------------------------------------------------------------
def test_no_log_skips(tmp_path):
    (tmp_path / "readme.txt").write_text("not a drc report")
    res = dvp.audit(tmp_path)
    assert res.verdict == "SKIP"
    assert res.passed is False


def test_missing_dir_skips(tmp_path):
    res = dvp.audit(tmp_path / "does_not_exist")
    assert res.verdict == "SKIP"
    assert res.passed is False


# ---------------------------------------------------------------------------
# Edge: empty / garbage log file -> SKIP or INCONCLUSIVE, never PASS
# ---------------------------------------------------------------------------
def test_empty_log_file_not_pass(tmp_path):
    (tmp_path / "drc.log").write_text("")
    res = dvp.audit(tmp_path)
    assert res.passed is False
    assert res.verdict in ("SKIP", "INCONCLUSIVE")


def test_garbage_log_file_not_pass(tmp_path):
    # Has the word "error" so it's treated as a DRC-ish log, but carries no
    # verdict AND no measurable geometry. FAIL-SAFE: a clean requires positive
    # evidence, so an unrecognised report is INCONCLUSIVE, never a pass.
    (tmp_path / "drc.log").write_text("random error log with no count tokens")
    res = dvp.audit(tmp_path)
    assert res.passed is False
    assert res.verdict == "INCONCLUSIVE"
    assert any(f.rule == "DRC_UNVERIFIABLE_RUN" for f in res.findings)


def test_no_verdict_token_but_geometry_measured_defers(tmp_path):
    # The same unparseable report, but a POPULATED layout sits behind it: the
    # run demonstrably examined geometry, so this gate defers instead of
    # blocking (no false alarm on a real-but-unparsed report).
    _write_gds(tmp_path / "top.gds", n_shapes=64)
    (tmp_path / "drc.log").write_text("top.gds :: random error log, no count tokens")
    res = dvp.audit(tmp_path)
    assert res.passed is True
    assert any(f.rule == "DRC_NO_VERDICT_TOKEN" for f in res.findings)


# ---------------------------------------------------------------------------
# Single-file path argument
# ---------------------------------------------------------------------------
def test_single_file_arg_vacuous(tmp_path):
    log = tmp_path / "my_drc.log"
    log.write_text("empty layout\n0 errors\n")
    res = dvp.audit(log)
    assert res.verdict == "INCONCLUSIVE"
    assert res.passed is False


# ---------------------------------------------------------------------------
# CLI exit codes
# ---------------------------------------------------------------------------
def test_cli_exit_codes(tmp_path):
    good = tmp_path / "good_drc.log"
    good.write_text("Loading top\n500 shapes\n0 DRC violations\n")
    assert dvp.main([str(good)]) == 0

    bad = tmp_path / "bad_drc.log"
    bad.write_text("0 cells\n0 DRC violations\n")
    assert dvp.main([str(bad)]) == 1

    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    assert dvp.main([str(empty_dir)]) == 2


def test_cli_json_output(tmp_path):
    log = tmp_path / "drc.log"
    log.write_text("Loading top\n42 cells\n0 errors\n")
    out = tmp_path / "report.json"
    dvp.main([str(log), "--json", str(out)])
    assert out.exists()
    import json
    data = json.loads(out.read_text())
    assert data["verdict"] == "PASS"


# ===========================================================================
# The MEASURED observable — the decision the verdict actually rests on.
# ===========================================================================
def test_measured_populated_layout_earns_clean(tmp_path):
    """POSITIVE GATE: a genuinely clean DRC on a real populated layout still
    reports CLEAN. No false alarm."""
    _write_gds(tmp_path / "top_design.gds", n_shapes=4200)
    (tmp_path / "klayout_drc.rpt").write_text(_CLEAN_LOG)
    res = dvp.audit(tmp_path)
    assert res.verdict == "PASS"
    assert res.passed is True
    assert any(f.rule == "DRC_CLEAN_EARNED" for f in res.findings)
    assert "MEASURED" in res.summary["per_file"][0]["geometry_evidence"]


def test_measured_empty_layout_is_vacuous_same_prose(tmp_path):
    """PROVEN-NEGATIVE: byte-identical report text, EMPTY layout -> VACUOUS.
    The verdict tracks the geometry, not the wording."""
    _write_gds(tmp_path / "top_design.gds", n_shapes=0)
    (tmp_path / "klayout_drc.rpt").write_text(_CLEAN_LOG)
    res = dvp.audit(tmp_path)
    assert res.verdict == "INCONCLUSIVE"
    assert res.passed is False
    assert any(f.rule == "DRC_VACUOUS_PASS" for f in res.findings)


def test_measurement_overrides_a_lying_report(tmp_path):
    """A report CLAIMING 9999 shapes cannot rescue a measurably empty layout —
    measurement outranks anything the tool says."""
    _write_gds(tmp_path / "top_design.gds", n_shapes=0)
    (tmp_path / "drc.rpt").write_text(
        "Loading layout file top_design.gds\n9999 shapes\nTotal errors: 0\n")
    res = dvp.audit(tmp_path)
    assert res.verdict == "INCONCLUSIVE"
    assert any(f.rule == "DRC_VACUOUS_PASS" for f in res.findings)


@pytest.mark.parametrize("prose", [
    # the exact rewordings that produced the FALSE CLEAN before the fix
    "Loading layout file top_design.gds\nLayer statistics: shape count 0\nTotal errors: 0\n",
    "Reading top_design.gds\nHierarchy traversed OK\nDRC is clean\n",
    "Loading top_design.gds\nZZZ-DRC v9 materialised the cellview\nviolations: 0\n",
    "top_design.gds :: $%^ garbled record stream ~~~\n0 errors\n",
    "checking top_design.gds\ncell top_design loaded\nlayout read\nno violations found\n",
])
def test_vacuous_regardless_of_wording(tmp_path, prose):
    """PROVEN-NEGATIVE: an empty layout classifies VACUOUS under ANY phrasing,
    including phrasings no regex table could have anticipated. Wording rot can
    no longer re-open the hole this program guards."""
    _write_gds(tmp_path / "top_design.gds", n_shapes=0)
    (tmp_path / "drc.rpt").write_text(prose)
    res = dvp.audit(tmp_path)
    assert res.passed is False, f"empty layout scored clean on prose: {prose!r}"
    assert res.verdict == "INCONCLUSIVE"


def test_reported_zero_count_in_any_word_order_is_not_geometry(tmp_path):
    """"shape count 0" is a ZERO observable, whatever the word order. The old
    table only knew "0 shapes" and so read this as geometry-loaded."""
    (tmp_path / "drc.rpt").write_text(
        "Loading layout file top.gds\nLayer statistics: shape count 0\nTotal errors: 0\n")
    res = dvp.audit(tmp_path)
    assert res.passed is False
    assert any(f.rule == "DRC_VACUOUS_PASS" for f in res.findings)


def test_wording_hints_are_recorded_but_never_decide(tmp_path):
    """Prose survives as EXPLANATION only: the hints are present in the report
    while the verdict is VACUOUS."""
    _write_gds(tmp_path / "top_design.gds", n_shapes=0)
    (tmp_path / "drc.rpt").write_text(_CLEAN_LOG)
    res = dvp.audit(tmp_path)
    pf = res.summary["per_file"][0]
    assert "loading_reading" in pf["wording_hints"]     # the prose DID fire
    assert pf["geometry_established"] is False          # and decided nothing
    assert res.passed is False


def test_explicit_layout_flag_is_measured(tmp_path):
    """--layout points the gate at the artifact the run actually consumed."""
    lay = _write_gds(tmp_path / "elsewhere.gds", n_shapes=0)
    log = tmp_path / "drc.rpt"
    log.write_text("Loading design\n500 shapes\n0 violations\n")
    assert dvp.audit(log, layout=lay).verdict == "INCONCLUSIVE"
    lay2 = _write_gds(tmp_path / "full.gds", n_shapes=12)
    assert dvp.audit(log, layout=lay2).verdict == "PASS"


def test_def_component_count_is_the_observable(tmp_path):
    """DEF geometry comes from its own structured section headers."""
    (tmp_path / "top.def").write_text(
        "VERSION 5.8 ;\nDESIGN top ;\nCOMPONENTS 0 ;\nEND COMPONENTS\nEND DESIGN\n")
    (tmp_path / "drc.rpt").write_text("Loading top.def\nDRC is clean\n0 violations\n")
    assert dvp.audit(tmp_path).verdict == "INCONCLUSIVE"
    (tmp_path / "top.def").write_text(
        "VERSION 5.8 ;\nDESIGN top ;\nCOMPONENTS 1841 ;\nEND COMPONENTS\nEND DESIGN\n")
    assert dvp.audit(tmp_path).verdict == "PASS"


def test_gds_measurement_counts_shape_records(tmp_path):
    """The measurer itself: shape records and structures, no layout tool."""
    m = dvp.measure_layout(_write_gds(tmp_path / "a.gds", n_shapes=7))
    assert m.shapes == 7 and m.cells == 1 and m.method == "gds_record_walk"
    assert dvp.measure_layout(_write_gds(tmp_path / "b.gds", n_shapes=0)).shapes == 0


def test_unmeasurable_layout_is_not_evidence_of_geometry(tmp_path):
    """FAIL-SAFE: a corrupt/unknown layout measures None, which is NOT geometry."""
    (tmp_path / "top.gds").write_bytes(b"\x00\x01not a gds at all")
    (tmp_path / "drc.rpt").write_text("Loading top.gds\nDRC is clean\n0 violations\n")
    res = dvp.audit(tmp_path)
    assert res.passed is False


def test_nonzero_violations_imply_geometry_no_false_alarm(tmp_path):
    """POSITIVE GATE: N>=1 violations cannot come from an empty layout, so a
    failing DRC with no shape count is still 'not vacuous' (defer, don't block)."""
    (tmp_path / "drc.rpt").write_text("Loading top\nTotal DRC errors: 7\n")
    res = dvp.audit(tmp_path)
    assert res.verdict == "PASS"
    assert any(f.rule == "DRC_NONZERO_COUNT" for f in res.findings)


def test_unbound_layouts_require_unanimity(tmp_path):
    """A stray empty artifact the report never names must not condemn a run
    whose real layout is populated (no false alarm from discovery noise)."""
    _write_gds(tmp_path / "scratch_empty.gds", n_shapes=0)
    _write_gds(tmp_path / "real_top.gds", n_shapes=900)
    (tmp_path / "drc.rpt").write_text("DRC complete\n0 violations\n")
    assert dvp.audit(tmp_path).verdict == "PASS"


def test_the_earned_finding_does_not_claim_the_deck_was_adequate(tmp_path):
    """The message must scope its claim to what this gate actually measured.

    WHAT WENT WRONG. This finding read "earned DRC-clean". This gate answers
    exactly one question -- is the 0 vacuous because the layout is empty? -- and
    never looks at WHICH deck produced the 0, so a router in-loop pass and a
    foundry sign-off deck are indistinguishable to it.

    OBSERVED on a full run: the sign-off DRC was killed at its wall-clock cap
    and wrote no report; the surviving report was the router's in-loop
    projection covering antenna and via only -- no spacing, no width, no
    min-area; and this line stamped PASS / "earned DRC-clean" over a layout
    independently measured to carry ~1,968 unpatchable min-area shapes.
    `drc_signoff.json` had it right (`passed=false`, `is_signoff_deck=false`)
    and even warned that the spacing and width categories were absent, so the
    truth was on disk and this sentence contradicted it.

    The 29 tests that already existed all assert on `rule ==
    "DRC_CLEAN_EARNED"` and never on the message, so the overclaiming sentence
    was unguarded -- which is why it could be written, and why it needs a guard
    of its own rather than relying on the rule name.
    """
    log = tmp_path / "magic.drc.log"
    log.write_text(
        "Loading top\n"
        "Reading cell top\n"
        "12345 rectangles\n"
        "DRC checking complete.\n"
        "Total DRC errors found: 0\n"
    )
    res = dvp.audit(tmp_path)
    earned = [f for f in res.findings if f.rule == "DRC_CLEAN_EARNED"]
    assert earned, "the not-vacuous finding is missing entirely"
    msg = earned[0].message

    # It must NOT assert the thing it cannot know.
    assert "earned DRC-clean" not in msg, (
        f"the finding still claims the deck was adequate for sign-off, which "
        f"this gate never checks: {msg!r}")

    # It MUST say what it did establish, and where deck adequacy actually lives.
    assert "NOT vacuous" in msg, msg
    assert "drc_signoff.json" in msg, (
        f"the reader is not pointed at the artefact that owns deck adequacy: "
        f"{msg!r}")


def test_the_verdict_itself_is_unchanged_by_the_wording_fix(tmp_path):
    """Guard the guard: this was a DISCLOSURE change, not a verdict change.

    Narrowing the sentence must not turn a genuinely non-vacuous zero into a
    failure -- that would restate published results, which is a separate
    decision from fixing an overclaiming string.
    """
    log = tmp_path / "magic.drc.log"
    log.write_text(
        "Loading top\n"
        "Reading cell top\n"
        "12345 rectangles\n"
        "DRC checking complete.\n"
        "Total DRC errors found: 0\n"
    )
    res = dvp.audit(tmp_path)
    assert res.verdict == "PASS"
    assert res.passed is True
    assert all(f.severity != "ERROR" for f in res.findings
               if f.rule == "DRC_CLEAN_EARNED")
