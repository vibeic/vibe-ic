#!/usr/bin/env python3
"""The yosys backend: parse yosys, decide nothing.

Every transcript in this file is a copy of the shape a real run produced, from
`/home/reyerchu/_c_cv_spm_run/phase2/stage2/synth/synth.log` (spm, gf180mcuD,
phase 3 complete). The three numbers that matter are:

    generic block, line 562   232 cells, 174 wires, 268 wire bits, NO area
    mapped  block, line 699   252 cells, 226 wires, 288 wire bits
                              Chip area for module '\\spm': 4703.529600
                                of which used for sequential elements: 1646.568000

The transcript is reproduced here rather than read from that path because a test
that depends on one host's scratch directory reports "no tests ran" somewhere
else — and a run that never started prints the same zero as a run with no
failures. The real file is used in RESULT.md as the provenance for the values.
"""
import pathlib
import sys

import pytest

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))

from _ppa import area as A  # noqa: E402
from _ppa.backends import yosys as Y  # noqa: E402

GENERIC_AND_MAPPED = """
6.28. Printing statistics.

=== spm ===

        +----------Local Count, excluding submodules.
        |
      174 wires
      268 wire bits
        8 public wires
      102 public wire bits
        5 ports
       36 port bits
      232 cells
       58   $_AND_
       57   $_NAND_

7. Executing DFFLIBMAP pass.
  cell DFFHQD1 (noninv, pins=3, area=49.90) is a direct match for $_DFF_P_.

11. Printing statistics.

=== spm ===

        +----------Local Count, excluding submodules.
        |        +-Local Area, excluding submodules.
        |        |
      226        - wires
      288        - wire bits
        7        - public wires
       69        - public wire bits
        5        - ports
       36        - port bits
      252  4703.53 cells
       18  299.376   AND3D1
       33 1.65E+03   DFFHQD1

   Chip area for module '\\spm': 4703.529600
     of which used for sequential elements: 1646.568000 (35.01%)

12. Executing Verilog backend.
"""

OLD_SPELLING = """
=== top ===

   Number of wires:                 12
   Number of wire bits:             40
   Number of cells:                  7
     $_AND_                          7
"""

HIERARCHICAL = """
=== alu ===

       10 wires
       20 cells

   Chip area for module '\\alu': 100.0

=== cpu ===

       30 wires
       60 cells

   Chip area for module '\\cpu': 900.0

=== design hierarchy ===

   Chip area for top module '\\cpu': 1000.0
"""


class TestParsing:
    def test_both_blocks_of_a_real_run_are_found_in_order(self):
        blocks = Y.parse_stat_blocks(GENERIC_AND_MAPPED)
        assert [b.module for b in blocks] == ["spm", "spm"]
        assert blocks[0].counts["cells"] == 232
        assert blocks[0].counts["wires"] == 174
        assert blocks[0].counts["wire_bits"] == 268
        assert blocks[0].chip_area is None      # generic: no area at all
        assert blocks[1].counts["cells"] == 252
        assert blocks[1].counts["wires"] == 226
        assert blocks[1].chip_area == 4703.5296
        assert blocks[1].sequential_area == 1646.568

    def test_the_full_precision_area_line_wins_over_the_rounded_column(self):
        """The table prints 4703.53; the summary line prints 4703.529600.

        Same quantity, different precision, different sha256. Reading the column
        would make a record's identity depend on yosys's column width.
        """
        block = Y.parse_stat_blocks(GENERIC_AND_MAPPED)[1]
        assert block.chip_area == 4703.5296
        assert block.chip_area != 4703.53
        assert "4703.53 cells" in block.text  # the rounded form IS present

    def test_the_old_number_of_x_spelling_is_read_too(self):
        block = Y.parse_stat_blocks(OLD_SPELLING)[0]
        assert block.counts["cells"] == 7
        assert block.counts["wires"] == 12
        assert block.counts["wire_bits"] == 40

    def test_a_missing_row_is_none_and_never_a_zero(self):
        block = Y.parse_stat_blocks("=== t ===\n\n  5 cells\n")[0]
        assert block.counts["cells"] == 5
        assert block.counts["wires"] is None
        assert block.counts["memories"] is None

    def test_an_empty_transcript_has_no_blocks(self):
        assert Y.parse_stat_blocks("") == []
        assert Y.parse_stat_blocks("nothing interesting here") == []


class TestBlockSelection:
    def test_a_non_yosys_banner_is_not_a_statistics_block(self):
        """From the real log:

            === STAGED-MACRO vs BEHAVIOURAL PATH [INFO] ===

        is printed by the flow, not by yosys. Counting it as a module makes a
        single-module design look ambiguous and forces a refusal that has no
        cause. A statistics block prints at least one count row or an area line.
        """
        text = ("\n=== STAGED-MACRO vs BEHAVIOURAL PATH [INFO] ===\n"
                "the flow said something here\n" + GENERIC_AND_MAPPED)
        blocks = Y.parse_stat_blocks(text)
        assert len(blocks) == 3
        assert blocks[0].is_statistics is False
        block, reason = Y.select_block(blocks)
        assert block is not None
        assert block.counts["cells"] == 252
        assert "spm" in reason

    def test_mapped_is_preferred_and_the_reason_says_so(self):
        block, reason = Y.select_block(
            Y.parse_stat_blocks(GENERIC_AND_MAPPED), "spm")
        assert block.chip_area == 4703.5296
        assert "technology-mapped" in reason

    def test_generic_can_be_asked_for_explicitly(self):
        block, reason = Y.select_block(
            Y.parse_stat_blocks(GENERIC_AND_MAPPED), "spm", kind="generic")
        assert block.counts["cells"] == 232
        assert block.chip_area is None
        assert "generic" in reason

    def test_asking_for_mapped_when_only_generic_exists_refuses(self):
        """It does NOT fall back.

        Falling back would answer a question about the mapped netlist with a
        generic number — 232 cells reported where the caller asked for the 252.
        """
        generic_only = GENERIC_AND_MAPPED[:GENERIC_AND_MAPPED.index(
            "11. Printing statistics.")]
        block, reason = Y.select_block(
            Y.parse_stat_blocks(generic_only), "spm", kind="mapped")
        assert block is None
        assert "no technology-mapped" in reason
        assert "not a substitute" in reason

    def test_several_modules_with_no_top_is_refused_not_guessed(self):
        block, reason = Y.select_block(Y.parse_stat_blocks(HIERARCHICAL))
        assert block is None
        assert "more than one module" in reason
        assert "alu" in reason and "cpu" in reason

    def test_naming_the_top_resolves_the_hierarchy(self):
        block, _ = Y.select_block(Y.parse_stat_blocks(HIERARCHICAL), "cpu")
        assert block.chip_area == 900.0
        block, _ = Y.select_block(Y.parse_stat_blocks(HIERARCHICAL), "alu")
        assert block.chip_area == 100.0

    def test_a_top_that_is_not_in_the_transcript_refuses_and_names_what_is(self):
        block, reason = Y.select_block(Y.parse_stat_blocks(HIERARCHICAL), "dsp")
        assert block is None
        assert "alu" in reason and "cpu" in reason

    def test_an_absent_transcript_and_an_unreadable_one_differ(self):
        _, empty = Y.select_block(Y.parse_stat_blocks(""))
        _, banner = Y.select_block(Y.parse_stat_blocks("=== nope ===\nprose\n"))
        assert empty != banner
        assert "no `=== module ===` statistics block" in empty
        assert "none of them is a statistics block" in banner

    def test_an_unknown_kind_is_a_programming_error_not_a_guess(self):
        with pytest.raises(ValueError):
            Y.select_block(Y.parse_stat_blocks(GENERIC_AND_MAPPED), kind="best")


class TestRecords:
    def test_positive_the_mapped_block_yields_five_measured_records(self):
        recs = Y.records_from_stat(GENERIC_AND_MAPPED, stage="synth_mapped",
                                   top="spm", kind="mapped", path="synth.log")
        by = {r["metric"]: r for r in recs}
        assert by["area.proxy.cell_count"]["value"] == 252
        assert by["area.proxy.wire_count"]["value"] == 226
        assert by["area.proxy.wire_bit_count"]["value"] == 288
        assert by["area.synth.cell_area"]["value"] == 4703.5296
        assert by["area.synth.sequential_area"]["value"] == 1646.568
        assert all(r["status"] == A.MEASURED for r in recs)

    def test_a_backend_can_never_emit_a_physical_record(self):
        """§4: a backend parses; it does not decide what a number means.

        Enforced structurally — every record leaves through `proxy_record`,
        which raises on a physical metric name.
        """
        for text in (GENERIC_AND_MAPPED, OLD_SPELLING, HIERARCHICAL, "", "junk"):
            for kind in (None, "mapped", "generic"):
                recs = Y.records_from_stat(text, stage="s", kind=kind,
                                           top="spm")
                for r in recs:
                    assert r["metric_class"] in A.PROXY_CLASSES
                    assert r["eligible_for_physical_ppa"] is False
        assert A.filter_physical(
            Y.records_from_stat(GENERIC_AND_MAPPED, stage="s", top="spm")) == []

    def test_the_generic_block_has_no_area_and_says_why(self):
        """Not an omitted row, not a 0 — INVALID with the cause."""
        recs = Y.records_from_stat(GENERIC_AND_MAPPED, stage="synth_generic",
                                   top="spm", kind="generic")
        by = {r["metric"]: r for r in recs}
        assert by["area.synth.cell_area"]["status"] == A.INVALID
        assert "no `Chip area for module` line" in by["area.synth.cell_area"][
            "reason"]
        assert "value" not in by["area.synth.cell_area"]
        assert by["area.proxy.cell_count"]["value"] == 232

    def test_an_unreadable_transcript_produces_invalid_rows_not_silence(self):
        """Rule 9: "I could not read it" must not look like "it was clean"."""
        recs = Y.records_from_stat("", stage="synth_mapped")
        assert len(recs) == 5
        assert all(r["status"] == A.INVALID for r in recs)
        assert all(r["reason"] for r in recs)
        assert all("value" not in r for r in recs)

    def test_a_record_names_the_transcript_it_parsed(self):
        recs = Y.records_from_stat(GENERIC_AND_MAPPED, stage="synth_mapped",
                                   top="spm", path="phase2/synth.log",
                                   tool_version="yosys 0.44")
        src = recs[0]["source"]
        assert src["path"] == "phase2/synth.log"
        assert src["sha256"] == Y.sha256_of_text(GENERIC_AND_MAPPED)
        assert src["tool"] == "yosys"
        assert src["tool_version"] == "yosys 0.44"
        assert "selection" in src  # which block, recorded as provenance

    def test_a_stage_is_required_because_an_unscoped_count_is_not_comparable(
            self):
        with pytest.raises(ValueError):
            Y.records_from_stat(GENERIC_AND_MAPPED, stage="")

    def test_two_stages_of_one_run_are_not_comparable_to_each_other(self):
        """The generic and mapped blocks are different stages of one run.

        252 vs 232 cells is not an 8% regression; they are different quantities.
        """
        gen = Y.records_from_stat(GENERIC_AND_MAPPED, stage="synth_generic",
                                  top="spm", kind="generic")
        mapd = Y.records_from_stat(GENERIC_AND_MAPPED, stage="synth_mapped",
                                   top="spm", kind="mapped")
        g = [r for r in gen if r["metric"] == "area.proxy.cell_count"][0]
        m = [r for r in mapd if r["metric"] == "area.proxy.cell_count"][0]
        assert A.compare(g, m)["code"] == A.C_SCOPE_MISMATCH


class TestReductionRecord:
    def _counts(self, cells, stage="synth_mapped"):
        return A.proxy_record(
            "area.proxy.cell_count", A.MEASURED, value=cells,
            scope={"stage": stage, "tool": "yosys"},
            source={"path": "x.log", "tool": "yosys", "parser": "t"})

    def test_a_reduction_is_derived_and_states_its_formula(self):
        rec = Y.reduction_record(self._counts(252), self._counts(200))
        assert rec["metric"] == "area.proxy.cell_count_reduction_pct"
        assert rec["status"] == A.DERIVED
        assert rec["value"] == pytest.approx(20.634921, abs=1e-6)
        assert "100*(baseline-candidate)/baseline" in rec["formula"]
        assert rec["metric_class"] == A.RTL_PROXY

    def test_growth_is_returned_verbatim_as_a_negative(self):
        """A measured anti-reduction is a fact, not an error."""
        rec = Y.reduction_record(self._counts(200), self._counts(252))
        assert rec["value"] < 0

    def test_a_reduction_over_different_stages_is_not_a_reduction(self):
        rec = Y.reduction_record(self._counts(232, "synth_generic"),
                                 self._counts(252, "synth_mapped"))
        assert rec["status"] == A.NOT_MEASURED
        assert "different scopes" in rec["reason"]
        assert "value" not in rec

    def test_a_reduction_over_an_unmeasured_count_is_not_a_number(self):
        nm = A.proxy_record("area.proxy.cell_count", A.NOT_MEASURED,
                            reason="synthesis did not run",
                            scope={"stage": "synth_mapped"})
        rec = Y.reduction_record(self._counts(252), nm)
        assert rec["status"] == A.NOT_MEASURED
        assert "value" not in rec

    def test_a_zero_baseline_cannot_anchor_a_percentage(self):
        rec = Y.reduction_record(self._counts(0), self._counts(0))
        assert rec["status"] == A.NOT_MEASURED

    def test_no_reduction_metric_exists_for_an_area(self):
        """There is deliberately no `area.synth.cell_area_reduction_pct`.

        A percentage off a pre-placement area reads as an area saving and is
        not one; the lane refuses to mint the name.
        """
        a = A.proxy_record("area.synth.cell_area", A.MEASURED, value=4703.5296,
                           scope={"stage": "synth_mapped"},
                           source={"path": "x", "tool": "yosys", "parser": "t"})
        with pytest.raises(ValueError):
            Y.reduction_record(a, a)
