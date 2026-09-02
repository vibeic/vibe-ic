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


def test_no_verdict_token_alone_is_not_a_pass(tmp_path):
    # THIS TEST USED TO ASSERT `passed is True`, AND THAT WAS THE HOLE.
    #
    # Its reasoning was: an unparseable report with a POPULATED layout behind
    # it shows the run "demonstrably examined geometry", so defer rather than
    # raise a false alarm. The premise does not follow. Geometry in the layout
    # proves the layout was worth checking; it proves nothing about whether the
    # checker ever looked at it.
    #
    # MEASURED, on a real run (gf180mcuD 16-stage precheck, step 12): Magic ran
    # 14:47 and stopped at "Loading DRC CIF style.", before its own checker
    # output. Its report was 0 bytes -- caught by DRC_REPORT_EMPTY. DELETE that
    # one empty file, leaving only the truncated log, and the same unfinished
    # run reached HERE and scored PASS, on the strength of 4 556 379 shapes the
    # checker never reached.
    #
    # The deferral had nowhere to defer TO: no file in scope carried a count,
    # so the "violation-count gate" this rule hands off to would have been
    # handed nothing. That is now INCONCLUSIVE.
    _write_gds(tmp_path / "top.gds", n_shapes=64)
    (tmp_path / "drc.log").write_text("top.gds :: random error log, no count tokens")
    res = dvp.audit(tmp_path)
    assert res.passed is False
    assert res.verdict == "INCONCLUSIVE"
    # This report offers no proof its checker examined anything, so the STEP
    # rule reaches it before the scope rollup does. Same verdict; only the rule
    # that gets there changes. The rollup still owns the case where proof IS
    # present -- pinned by the scope-rollup test below.
    assert any(f.rule == "DRC_STEP_NEVER_REPORTED" for f in res.findings)


def test_no_verdict_token_still_defers_beside_a_real_count(tmp_path):
    # The false-alarm concern the ORIGINAL test was written for, preserved
    # exactly where it is now sound: an unparsed report beside a real count is
    # not blocking WHEN THAT STEP PROVES IT RAN.
    #
    # NARROWED, deliberately, and re-pointed at the published corpus cell's
    # REAL shape rather than a paraphrase of it. Its two unparsed reports are
    # `drc.rpt` and `drc_signoff.rpt`, and both ARE report-databases naming
    # `spm`, so they carry their own proof. MEASURED on that cell: PASS before
    # this rule and PASS after it. An unparsed report with NO proof beside it
    # is a different case and is now refused -- see
    # test_deleting_the_database_too_does_not_buy_a_pass.
    _write_gds(tmp_path / "top.gds", n_shapes=64)
    (tmp_path / "drc.rpt").write_text(_DB_TOP_CELL_FORM)
    (tmp_path / "drc_router.rpt").write_text(
        "top.gds\nDRC violations found: 35\n")
    res = dvp.audit(tmp_path)
    assert res.passed is True
    assert res.verdict == "PASS"
    assert any(f.rule == "DRC_NO_VERDICT_TOKEN" for f in res.findings)
    assert any(f.rule == "DRC_NONZERO_COUNT" for f in res.findings)
    assert not any(f.rule == "DRC_STEP_NEVER_REPORTED" for f in res.findings)


def test_scope_rollup_still_refuses_a_scope_with_proof_but_no_count(tmp_path):
    # The scope rule is NOT made unreachable by the step rule. A report that
    # proves its checker ran but states no count passes the step rule and is
    # then refused by the rollup: proof of a run is not a verdict.
    _write_gds(tmp_path / "top.gds", n_shapes=64)
    (tmp_path / "drc.rpt").write_text(_DB_TOP_CELL_FORM)
    res = dvp.audit(tmp_path)
    assert res.passed is False
    assert res.verdict == "INCONCLUSIVE"
    assert any(f.rule == "DRC_NO_VERDICT_IN_SCOPE" for f in res.findings)
    assert not any(f.rule == "DRC_STEP_NEVER_REPORTED" for f in res.findings)


# ---------------------------------------------------------------------------
# (D) The checker's own statement of what it examined.
#
# These fixtures are the two REAL report-databases this work measured, byte for
# byte. They differ by one byte, inside the cell name, and mean opposite things.
# ---------------------------------------------------------------------------
_DB_NO_CELL = (
    "<?xml version='1.0' encoding='utf8'?>\n"
    "<report-database><cells><cell><name>UNKNOWN</name></cell></cells>"
    "<categories></categories><items></items></report-database>")
_DB_NAMED_CELL = (
    "<?xml version='1.0' encoding='utf8'?>\n"
    "<report-database><cells><cell><name>chip_top</name></cell></cells>"
    "<categories></categories><items></items></report-database>")
_DB_TOP_CELL_FORM = (
    '<?xml version="1.0" encoding="utf-8"?>\n<report-database>\n'
    ' <description/>\n <generator>drc: script=\'x.drc\'</generator>\n'
    ' <top-cell>spm</top-cell>\n <categories>\n </categories>\n'
    ' <items>\n </items>\n</report-database>')


def test_report_db_cell_reads_both_element_forms(tmp_path):
    # The two shapes a report-database takes in the wild: the compact converter
    # form that starts with <cells>, and the KLayout form with <top-cell>.
    (tmp_path / "a.lyrdb").write_text(_DB_NO_CELL)
    (tmp_path / "b.lyrdb").write_text(_DB_NAMED_CELL)
    (tmp_path / "c.lyrdb").write_text(_DB_TOP_CELL_FORM)
    (tmp_path / "not_a_db.log").write_text("Loading DRC CIF style.\n")
    assert dvp.report_db_cell(tmp_path / "a.lyrdb") == b""
    assert dvp.report_db_cell(tmp_path / "b.lyrdb") == b"chip_top"
    assert dvp.report_db_cell(tmp_path / "c.lyrdb") == b"spm"
    # Not a report-database at all -> None, which DEFERS. Never condemns.
    assert dvp.report_db_cell(tmp_path / "not_a_db.log") is None
    assert dvp.report_db_cell(tmp_path / "missing.lyrdb") is None


def test_a_step_with_no_proof_of_completion_is_not_deferred_over(tmp_path):
    # The truncated log alone would defer (geometry is established). The step's
    # own database says it loaded no cell, which is the checker stating it
    # examined nothing -- decisive, exactly like a measured-empty layout.
    step = tmp_path / "12-magic-drc"
    (step / "reports").mkdir(parents=True)
    _write_gds(tmp_path / "chip_top.gds", n_shapes=4096)
    (step / "magic-drc.log").write_text(
        'Reading "chip_top".\nDRC style is now "drc(full)"\n'
        'Loading DRC CIF style.\n')
    (step / "reports" / "drc.magic.lyrdb").write_text(_DB_NO_CELL)
    res = dvp.audit(tmp_path)
    assert res.passed is False
    assert res.verdict == "INCONCLUSIVE"
    assert any(f.rule == "DRC_STEP_NEVER_REPORTED" for f in res.findings)


def test_a_database_naming_a_cell_still_defers(tmp_path):
    # ONE BYTE different from the fixture above, and it must not be condemned:
    # this checker ran and found nothing, it merely phrased its verdict in a way
    # the parser does not read. A real count elsewhere carries the scope.
    step = tmp_path / "12-magic-drc"
    (step / "reports").mkdir(parents=True)
    _write_gds(tmp_path / "chip_top.gds", n_shapes=4096)
    (step / "magic-drc.log").write_text(
        'Reading "chip_top".\nLoading DRC CIF style.\n')
    (step / "reports" / "drc.magic.lyrdb").write_text(_DB_NAMED_CELL)
    (tmp_path / "drc_klayout.rpt").write_text(
        "chip_top\nDRC violations found: 12\n")
    res = dvp.audit(tmp_path)
    assert res.passed is True
    assert res.verdict == "PASS"
    assert any(f.rule == "DRC_NO_VERDICT_TOKEN" for f in res.findings)
    assert not any(f.rule == "DRC_STEP_NEVER_REPORTED" for f in res.findings)


def test_deleting_the_database_too_does_not_buy_a_pass(tmp_path):
    # THE RULE ABOVE, TESTED AGAINST ITS OWN STANDARD.
    #
    # The first version of it asked "is there a database here that says
    # UNKNOWN?" — a confession. MEASURED: delete that 161-byte database as well
    # as the already-deleted 0-byte report and the same unfinished step went
    # back to PASS, exit 0. A gate keyed on a tell is defeated by removing the
    # tell, which is the finding this whole progression exists to state.
    #
    # So it asks for PROOF instead: a database that names a cell. There is now
    # no file whose deletion buys a pass — removing one can only remove proof.
    _write_gds(tmp_path / "chip_top.gds", n_shapes=4096)
    magic = tmp_path / "12-magic-drc"
    (magic / "reports").mkdir(parents=True)
    (magic / "magic-drc.log").write_text(
        'Reading "chip_top".\nLoading DRC CIF style.\n')
    # No report. No database. Nothing but the truncated log.
    klay = tmp_path / "14-klayout-drc"
    klay.mkdir()
    (klay / "klayout-drc.log").write_text("chip_top\n53273 DRC violations found\n")
    res = dvp.audit(tmp_path)
    assert res.passed is False
    assert res.verdict == "INCONCLUSIVE"
    assert any(f.rule == "DRC_STEP_NEVER_REPORTED" for f in res.findings)


def test_requiring_proof_only_changes_the_masking_case(tmp_path):
    # The inversion's blast radius, pinned. A LONE unparsed report with no
    # database is INCONCLUSIVE — but it was INCONCLUSIVE before this rule too,
    # via DRC_NO_VERDICT_IN_SCOPE, because nothing in scope stated a count.
    # So requiring proof costs nothing anywhere except where another checker
    # WAS reporting, which is precisely the defect.
    _write_gds(tmp_path / "chip_top.gds", n_shapes=4096)
    (tmp_path / "drc.log").write_text(
        "chip_top :: error log with no count tokens")
    res = dvp.audit(tmp_path)
    assert res.passed is False
    assert res.verdict == "INCONCLUSIVE"
    # Both rules agree on this scope; the step rule reaches it first.
    assert any(f.rule == "DRC_STEP_NEVER_REPORTED" for f in res.findings)


def test_proof_does_not_leak_across_steps(tmp_path):
    # The rule's own helper must not commit the error the rule exists to stop.
    # A database sitting at RUN level is not proof that a particular STEP ran,
    # so a log at `<run>/<step>/x-drc.log` must not be able to reach it. If the
    # ascent were unconditional, the run-level database below would prove the
    # Magic step ran and this scope would go green again.
    _write_gds(tmp_path / "chip_top.gds", n_shapes=4096)
    (tmp_path / "stray.lyrdb").write_text(_DB_NAMED_CELL)   # run level
    magic = tmp_path / "12-magic-drc"
    magic.mkdir()
    (magic / "magic-drc.log").write_text(
        'Reading "chip_top".\nLoading DRC CIF style.\n')
    klay = tmp_path / "14-klayout-drc"
    klay.mkdir()
    (klay / "klayout-drc.log").write_text("chip_top\n53273 DRC violations found\n")
    res = dvp.audit(tmp_path)
    assert res.passed is False
    assert any(f.rule == "DRC_STEP_NEVER_REPORTED" for f in res.findings)


def test_proof_is_reachable_from_inside_a_reports_directory(tmp_path):
    # And the ascent that WAS needed still works: a report inside `reports/`
    # reaches its own step's database one level up.
    _write_gds(tmp_path / "chip_top.gds", n_shapes=4096)
    step = tmp_path / "12-magic-drc"
    (step / "reports").mkdir(parents=True)
    (step / "drc.magic.lyrdb").write_text(_DB_NAMED_CELL)
    (step / "reports" / "drc_summary.rpt").write_text(
        "chip_top :: error summary, no count tokens")
    (tmp_path / "klayout-drc.log").write_text(
        "chip_top\n53273 DRC violations found\n")
    res = dvp.audit(tmp_path)
    assert res.passed is True
    assert not any(f.rule == "DRC_STEP_NEVER_REPORTED" for f in res.findings)


def test_a_finished_checker_does_not_speak_for_an_unfinished_one(tmp_path):
    # THE MASKING CASE, and it is the scope the hygiene loop actually uses: the
    # whole cell, no --under. Two DRC steps. One never loaded a cell; the other
    # finished and reported 53 273 violations. The scope HAS a verdict in it, so
    # DRC_NO_VERDICT_IN_SCOPE cannot help -- and before this rule the answer was
    # PASS, exit 0, with Magic having checked nothing.
    _write_gds(tmp_path / "chip_top.gds", n_shapes=4096)
    magic = tmp_path / "12-magic-drc"
    (magic / "reports").mkdir(parents=True)
    (magic / "magic-drc.log").write_text(
        'Reading "chip_top".\nLoading DRC CIF style.\n')
    (magic / "reports" / "drc.magic.lyrdb").write_text(_DB_NO_CELL)
    klay = tmp_path / "14-klayout-drc"
    klay.mkdir()
    (klay / "klayout-drc.log").write_text(
        "chip_top\n53273 DRC violations found\n")
    res = dvp.audit(tmp_path)
    assert res.passed is False
    assert res.verdict == "INCONCLUSIVE"
    assert any(f.rule == "DRC_STEP_NEVER_REPORTED" for f in res.findings)
    # The finished checker's count is still reported -- it is not suppressed,
    # it simply does not speak for the step that never ran.
    assert any(f.rule == "DRC_NONZERO_COUNT" for f in res.findings)


def test_deleted_empty_report_does_not_escape_the_empty_report_rule(tmp_path):
    # The exact escape, reproduced as a fixture: a run that terminated without
    # reporting, whose 0-byte report was then cleaned up. Only the truncated
    # log survives. Before this rule that was exit 0.
    _write_gds(tmp_path / "chip_top.gds", n_shapes=4096)
    (tmp_path / "magic-drc.log").write_text(
        'Reading "chip_top".\n[INFO] Loading chip_top\n\n'
        'DRC style is now "drc(full)"\nLoading DRC CIF style.\n')
    res = dvp.audit(tmp_path)
    assert res.passed is False
    assert res.verdict == "INCONCLUSIVE"
    assert any(f.rule == "DRC_STEP_NEVER_REPORTED" for f in res.findings)
    # And it is NOT the empty-report rule doing the work -- there is no report.
    assert not any(f.rule == "DRC_REPORT_EMPTY" for f in res.findings)


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
    whose real layout is populated (no false alarm from discovery noise).

    THE FIXTURE IS THE ONE THAT WAS MEASURED. vibe-ic#693 was reproduced by
    dropping ONE 0-component `spm.def` into a `phase3/stage3/pnr_d8/` scratch
    directory of a passing run; that is a DEF beside a real GDS, and it is what
    this test now builds. It used to build a second GDS instead — a fixture
    indistinguishable from the kspm42/spmB defect (a 0-shape sign-off GDS
    beside a populated one), where PASS is exactly the wrong answer. See
    `test_a_populated_sibling_does_not_acquit_an_unnamed_empty_layout` for that
    case, and `_subject_pool` in the program for why a DEF is now dropped from
    a GDS run's pool outright rather than merely out-voted in it.
    """
    _write_gds(tmp_path / "real_top.gds", n_shapes=900)
    scratch = tmp_path / "pnr_d8"
    scratch.mkdir()
    (scratch / "top_design.def").write_text(
        "VERSION 5.8 ;\nDESIGN top_design ;\nCOMPONENTS 0 ;\n"
        "END COMPONENTS\nEND DESIGN\n")
    (tmp_path / "drc.rpt").write_text("DRC complete\n0 violations\n")
    assert dvp.audit(tmp_path).verdict == "PASS"


# ===========================================================================
# THE DENOMINATOR MUST BE PROVEN BY THE ARTEFACT THAT WAS CHECKED
#
# MEASURED (kspm42/spmB): `DRC_CLEAN_EARNED ... "MEASURED: 7232 shape(s) in the
# layout"` over a run whose sign-off GDS was a broken 106-byte stream measuring
# 0 shapes. The 7232 was a DEF's `COMPONENTS + NETS`, lifted by `max()` off a
# pool that mixed 5 GDS and 9 DEF candidates.
# ===========================================================================
def test_a_def_does_not_vouch_for_a_gds_decks_denominator(tmp_path):
    """THE DEFECT, in miniature: an empty sign-off GDS beside a fat DEF.

    The DEF is not a smaller vote than the GDS's zero — it is not a vote at
    all. `COMPONENTS + NETS` is a placement census; it is not read off the
    stream the deck opened and cannot say whether that stream carries
    geometry.
    """
    _write_gds(tmp_path / "top_design.gds", n_shapes=0)
    (tmp_path / "routed.def").write_text(
        "VERSION 5.8 ;\nDESIGN top_design ;\nCOMPONENTS 7232 ;\n"
        "END COMPONENTS\nEND DESIGN\n")
    (tmp_path / "drc.rpt").write_text("DRC complete\n0 violations\n")
    res = dvp.audit(tmp_path)
    assert res.verdict == "INCONCLUSIVE"
    assert res.passed is False
    assert any(f.rule == "DRC_VACUOUS_PASS" for f in res.findings)
    c = res.summary["per_file"][0]
    assert c["layout_subject_kind"] == "layout"
    assert [Path(f).name for f in c["layout_subject_files"]] == ["top_design.gds"]
    assert "7232" not in c["geometry_evidence"]


def test_a_populated_sibling_does_not_acquit_an_unnamed_empty_layout(tmp_path):
    """`max()` IS THE WRONG QUANTIFIER. Two GDS candidates, one empty and one
    populated, and a report that names neither: which one the deck read is
    UNKNOWN, so no measurement acquits it. NOT_MEASURED, never earned."""
    _write_gds(tmp_path / "top_design.gds", n_shapes=0)
    _write_gds(tmp_path / "top_design.filled.gds", n_shapes=900)
    (tmp_path / "drc.rpt").write_text("DRC complete\n0 violations\n")
    res = dvp.audit(tmp_path)
    assert res.verdict == "INCONCLUSIVE"
    assert res.passed is False
    c = res.summary["per_file"][0]
    assert c["layout_subject_unknown"] is True
    assert c["geometry_established"] is False
    assert c["geometry_evidence"].startswith("NOT_MEASURED:")


def test_naming_the_layout_settles_it_in_both_directions(tmp_path):
    """NOT_MEASURED is a statement about a MISSING citation, not a new blanket
    refusal. Name the artefact in the report and the pool is that one artefact:
    the empty one is condemned, the populated one is earned. Same two files,
    same prose, only the citation moves."""
    _write_gds(tmp_path / "top_design.gds", n_shapes=0)
    _write_gds(tmp_path / "top_design.filled.gds", n_shapes=900)
    rpt = tmp_path / "drc.rpt"
    rpt.write_text("DRC complete\nLoading top_design.gds\n0 violations\n")
    assert dvp.audit(tmp_path).verdict == "INCONCLUSIVE"
    rpt.write_text("DRC complete\nLoading top_design.filled.gds\n0 violations\n")
    res = dvp.audit(tmp_path)
    assert res.verdict == "PASS"
    assert any(f.rule == "DRC_CLEAN_EARNED" for f in res.findings)


def test_every_candidate_populated_still_earns_the_clean(tmp_path):
    """REVERSE CONTROL: the universal rule is not a way to refuse every zero.
    Where every candidate that could be the subject holds geometry, the zero is
    still earned — whichever one the deck read, it was not empty.

    GREEN IN BOTH ARMS BY CONSTRUCTION, which is the whole job of a reverse
    control: it asserts the PROPERTY (a real layout still earns its clean) and
    not the mechanism, so it cannot be satisfied by the change it is guarding
    against. The min-vs-max mechanism is pinned by
    `test_a_populated_sibling_does_not_acquit_an_unnamed_empty_layout`, which
    does fail against the pre-fix program.
    """
    _write_gds(tmp_path / "top_design.gds", n_shapes=900)
    _write_gds(tmp_path / "top_design.filled.gds", n_shapes=907)
    (tmp_path / "drc.rpt").write_text("DRC complete\n0 violations\n")
    res = dvp.audit(tmp_path)
    assert res.verdict == "PASS"
    assert res.passed is True
    assert any(f.rule == "DRC_CLEAN_EARNED" for f in res.findings)
    assert res.summary["per_file"][0]["geometry_evidence"].startswith("MEASURED:")


def test_a_def_only_run_is_still_measured_by_its_def(tmp_path):
    """REVERSE CONTROL: the kind rule DROPS DEFs from a GDS run's pool; it does
    not make a DEF unmeasurable. A router in-loop DRC over the routed DEF, with
    no GDS in the tree at all, still has its denominator proven by that DEF —
    and still earns its clean, in either arm."""
    (tmp_path / "routed.def").write_text(
        "VERSION 5.8 ;\nDESIGN top_design ;\nCOMPONENTS 7232 ;\n"
        "END COMPONENTS\nEND DESIGN\n")
    (tmp_path / "drc.rpt").write_text("DRC complete\n0 violations\n")
    res = dvp.audit(tmp_path)
    assert res.verdict == "PASS"
    assert any(f.rule == "DRC_CLEAN_EARNED" for f in res.findings)


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


# ---------------------------------------------------------------------------
# A CHECKER THAT WROTE NO REPORT HAS NOT REPORTED ZERO
# ---------------------------------------------------------------------------
# MEASURED, gf180mcuD, 16-stage non-CoB precheck, step 12 `magic-drc`: Magic
# ran 14:47 at 99.95 % CPU and ended without writing. `drc.magic.rpt` was 0
# bytes; `magic-drc.log` stopped at "Loading DRC CIF style." — before any
# checker output; `drc.magic.lyrdb` named its top cell `UNKNOWN`. The precheck
# image printed "Check for Magic DRC errors clear." and THIS gate, handed the
# same directory plus the design's 4 556 379-shape GDS, returned PASS. A
# completed run of the same deck writes 102 bytes: the cell name and
# `[INFO] COUNT: 0`.
#
# The two tests below are the pair that has to hold together: the empty report
# must block, and the genuine 102-byte zero must still pass. One without the
# other is either a hole or a gate nothing survives.
def test_zero_byte_report_blocks_even_with_geometry(tmp_path):
    """The measured false PASS. Geometry is established and irrelevant: the
    report is 0 bytes, so nothing was reported."""
    _write_gds(tmp_path / "chip_top.gds", n_shapes=512)
    (tmp_path / "drc.magic.rpt").write_bytes(b"")
    # The truncated companion log — DRC-ish, names the layout, no verdict.
    (tmp_path / "magic-drc.log").write_text(
        "magic 8.3\nchip_top.gds\nLoading DRC CIF style.\n")
    res = dvp.audit(tmp_path)
    assert res.passed is False
    assert res.verdict == "INCONCLUSIVE"
    assert any(f.rule == "DRC_REPORT_EMPTY" for f in res.findings)


def test_completed_magic_zero_still_passes(tmp_path):
    """The control: the same deck, same design, a report that FINISHED."""
    _write_gds(tmp_path / "chip_top.gds", n_shapes=512)
    # Both artefacts, exactly as a completed step 12 leaves them: the 102-byte
    # report AND the log that runs past the checker to its own DONE marker.
    (tmp_path / "drc.magic.rpt").write_text(
        "chip_top\n"
        "----------------------------------------\n"
        "[INFO] COUNT: 0\n"
        "[INFO] Should be divided by 3 or 4\n")
    (tmp_path / "magic-drc.log").write_text(
        "magic 8.3\n[INFO] Loading chip_top\nchip_top.gds\n"
        "No errors found.\n[INFO] COUNT: 0\n"
        "[INFO] DRC Checking DONE (reports/drc.magic.rpt)\n[INFO] Saved\n")
    res = dvp.audit(tmp_path)
    assert res.passed is True
    assert res.verdict == "PASS"
    assert not any(f.rule == "DRC_REPORT_EMPTY" for f in res.findings)


def test_zero_byte_report_outranks_skip(tmp_path):
    """A 0-byte report ALONE is INCONCLUSIVE, not SKIP. SKIP is exit 2 and a
    caller may treat it as non-blocking; a run that terminated without
    reporting must block."""
    (tmp_path / "drc.rpt").write_bytes(b"")
    res = dvp.audit(tmp_path)
    assert res.verdict == "INCONCLUSIVE"
    assert dvp.main([str(tmp_path)]) == 1


# ═══════════ AN EMPTY REPORT THE STEP'S OWN TOOL SAYS IT WROTE ══════════════
#
# vibe-ic#2015 item 1, MEASURED on the published cell `spm x gf180mcuD`.
# `detailed_route -output_drc` writes ONE RECORD PER RESIDUAL VIOLATION and
# nothing else, so a clean route's report is zero bytes BY CONSTRUCTION -- and
# under a two-state reading the cleaner the route, the redder this gate got.
# The sibling auditor `eda_report_audit._check_drc` was repaired for this on
# 2026-08-30 against the SAME FILE in the SAME CELL; the runner that ASKS for
# the report has always written "the router wrote an EMPTY report, it found no
# residual violations" into its projection. This gate was the third consumer of
# that one artefact and the last still reading it two ways.
#
# WHAT IS NOT WEAKENED: emptiness never speaks for itself. It is credited only
# where the STEP'S OWN other artefact says the tool ran and says what it ended
# on, so there is still no file whose REMOVAL buys a pass -- the property
# `completion_proof` is keyed on, applied to a second question. The measured
# Magic case (`test_zero_byte_report_blocks_even_with_geometry` above) has no
# such sibling and is unchanged.

#: The runner's canonicalised projection of one detailed_route pass, in the
#: shape `phase3_one_shot_runner.canonicalize_artefacts` writes: a summary the
#: runner wrote, then the router's own transcript. The count is PER-ITERATION
#: and falls as the router converges, so only the LAST is a verdict -- which is
#: why this fixture prints a trajectory and not a single number.
def _router_projection(final: int) -> str:
    return (
        "# OpenROAD detailed_route DRC summary -- emitted by\n"
        "# phase3_one_shot_runner (canonicalize_artefacts step).\n"
        "# Tool: openroad detailed_route (drt)\n"
        "openroad / drt-pass: detailed_route invoked\n"
        "drc source: final [INFO DRT-0199] count\n"
        "chip_top\n"
        "[INFO DRT-0195] Start 0th optimization iteration.\n"
        "    Completing 40% with 31 violations.\n"
        "    Completing 100% with 162 violations.\n"
        "[INFO DRT-0199]   Number of violations = 229.\n"
        "[INFO DRT-0195] Start 1st optimization iteration.\n"
        f"[INFO DRT-0199]   Number of violations = {final}.\n"
        "[INFO DRT-0198] Complete detail routing.\n")


def test_empty_router_report_is_zero_when_its_own_step_says_so(tmp_path):
    """The published cell's shape: a 0-byte `-output_drc` report beside the
    runner's projection of the same route, whose LAST iteration is 0."""
    _write_gds(tmp_path / "chip_top.gds", n_shapes=512)
    pnr = tmp_path / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True)
    (pnr / "routed_router.drc.rpt").write_bytes(b"")
    (pnr / "routed.drc.rpt").write_text(_router_projection(0))
    res = dvp.audit(tmp_path)
    assert res.verdict == "PASS"
    assert res.passed is True
    assert any(f.rule == "DRC_REPORT_EMPTY_IS_ZERO" for f in res.findings)
    assert not any(f.rule == "DRC_REPORT_EMPTY" for f in res.findings)


def test_deleting_the_projection_takes_the_pass_away(tmp_path):
    """THE DIRECTION THAT MATTERS. The rule is keyed on PROOF, so removing a
    file can only ever remove proof -- never buy a pass. Same tree as above
    with the projection deleted."""
    _write_gds(tmp_path / "chip_top.gds", n_shapes=512)
    pnr = tmp_path / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True)
    (pnr / "routed_router.drc.rpt").write_bytes(b"")
    res = dvp.audit(tmp_path)
    assert res.verdict == "INCONCLUSIVE"
    assert res.passed is False
    assert any(f.rule == "DRC_REPORT_EMPTY" for f in res.findings)


def test_an_empty_report_beside_a_dirty_route_is_a_contradiction(tmp_path):
    """A route that ended WITH violations owes a report that names them. An
    empty one does not, and the two artefacts of one step then contradict each
    other -- refused, and the contradiction is named rather than resolved."""
    _write_gds(tmp_path / "chip_top.gds", n_shapes=512)
    pnr = tmp_path / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True)
    (pnr / "routed_router.drc.rpt").write_bytes(b"")
    (pnr / "routed.drc.rpt").write_text(_router_projection(7))
    res = dvp.audit(tmp_path)
    assert res.verdict == "INCONCLUSIVE"
    assert res.passed is False
    assert any(f.rule == "DRC_EMPTY_CONTRADICTS_TOOL" for f in res.findings)


def test_the_projection_does_not_speak_for_another_step(tmp_path):
    """STEP-LOCAL, like `completion_proof`. A clean route in one step must not
    credit an empty report in another -- the cross-step attribution error
    `DRC_STEP_NEVER_REPORTED` exists to refuse."""
    _write_gds(tmp_path / "chip_top.gds", n_shapes=512)
    pnr = tmp_path / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True)
    (pnr / "routed.drc.rpt").write_text(_router_projection(0))
    other = tmp_path / "12-magic-drc"
    other.mkdir()
    (other / "drc.magic.rpt").write_bytes(b"")
    res = dvp.audit(tmp_path)
    assert res.verdict == "INCONCLUSIVE"
    assert res.passed is False
    assert any(f.rule == "DRC_REPORT_EMPTY" for f in res.findings)


def test_a_finished_magic_sibling_does_not_make_an_empty_report_zero(tmp_path):
    """THE EMPTINESS CONVENTION BELONGS TO ONE PRODUCER, NOT TO DRC REPORTS.
    Magic writes a header and `[INFO] COUNT: 0` -- 102 bytes -- when it is
    clean, so a 0-byte Magic report is a run that stopped, not a clean one.
    A completed Magic transcript beside it therefore proves nothing about the
    empty file, and this scope stays refused."""
    _write_gds(tmp_path / "chip_top.gds", n_shapes=512)
    step = tmp_path / "12-magic-drc"
    step.mkdir()
    (step / "drc.magic.rpt").write_bytes(b"")
    (step / "magic-drc.log").write_text(
        "magic 8.3\n[INFO] Loading chip_top\nchip_top.gds\n"
        "No errors found.\n[INFO] COUNT: 0\n"
        "[INFO] DRC Checking DONE (reports/drc.magic.rpt)\n")
    res = dvp.audit(tmp_path)
    assert res.verdict == "INCONCLUSIVE"
    assert res.passed is False
    assert any(f.rule == "DRC_REPORT_EMPTY" for f in res.findings)
