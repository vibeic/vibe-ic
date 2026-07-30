"""test_scan_chain_insert.py — controls for REAL scan-chain insertion.

Every test here is written to FAIL against a specific defect.  The defect this
whole file exists to close, measured on a cell that PASSED:

    phase3/stage3/pnr/spm_pnr.v   ports: clk, p, rst, y, x …
        sin 0   sout 0   shift 0   tck 0   test 0

`fault_atpg_run.py` published `scan_netlist.v` as a BYTE COPY of
`cut_netlist.v` — Fault's combinational ATPG *cut* view, in which every
flip-flop has been replaced by a `<inst>.d` pseudo-PI/PO pair.  Step 12
`opt_clean`ed that into `post_dft_netlist.v`, so the artefact the flow calls
the post-DFT netlist had ZERO flops; and place-and-route read `<top>_synth.v`,
the PRE-DFT netlist, so the tape-out-bound design carried no scan chain at all
while ATPG reported 97 % stuck-at coverage on a netlist that never becomes
silicon.

The mutations each test kills are named in its docstring, because a test that
passes against the defect is a rubber stamp no matter how many assertions it
carries.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import fault_scan_chain_insert as sci          # noqa: E402
import fault_atpg_run as fatpg                 # noqa: E402


# Real `fault chain` stdout, copied verbatim from a measured run
# (spm x sky130A, image ghcr.io/vibeic/vibeic-eda:0.2.45).
CHAIN_LOG = """\
Processing file /work/spm_synth.v…
Processing module spm…
Chaining internal flip-flops…
Internal scan chain successfully constructed. Length: 64
Boundary scan cells successfully chained. Length:  34
Total scan-chain length:  98
Resynthesizing with yosys…
Done.
"""

META_JSON = json.dumps({
    "sin": "sin", "sout": "sout", "shift": "shift",
    "internalCount": 64, "boundaryCount": 34,
    "order": [{"name": "x", "kind": "input", "width": 32, "ordinal": 0},
              {"name": "_442_", "kind": "dff", "width": 1, "ordinal": 0},
              {"name": "_443_", "kind": "dff", "width": 1, "ordinal": 0},
              {"name": "p", "kind": "output", "width": 1, "ordinal": 0}],
})
CHAINED_HEAD = f"/* FAULT METADATA: '{META_JSON}' END FAULT METADATA */\n"


def _mapped_netlist(n_flops: int = 64) -> str:
    """A minimal sky130-mapped netlist with `n_flops` real flop instances."""
    body = "".join(
        f"  sky130_fd_sc_hd__dfxtp_1 _{i:03d}_ (\n"
        f"    .CLK(clk), .D(d[{i}]), .Q(q[{i}])\n  );\n"
        for i in range(n_flops))
    return ("module spm(clk, d, q);\n  input clk;\n"
            "  input [63:0] d;\n  output [63:0] q;\n"
            "  sky130_fd_sc_hd__nand2_1 _g0_ (\n    .A(a), .B(b), .Y(y)\n  );\n"
            + body + "endmodule\n")


class TestChainLengthIsMeasuredNotAsserted:
    """KILLS: "the tool exited 0, therefore the chain is good".

    A chain that leaves flops off it is a chain of untestable silicon.  These
    pin that the verdict comes from comparing three independent measurements —
    the tool's stdout, the artefact's own metadata header, and a flop count
    taken from the INPUT netlist — and never from an exit code.
    """

    def test_log_counts_are_parsed_from_the_tools_own_lines(self):
        assert sci.parse_chain_log(CHAIN_LOG) == {
            "internal": 64, "boundary": 34, "total": 98}

    def test_absent_count_is_none_never_zero(self):
        # 0 is a MEANINGFUL and disastrous chain length.  A parse miss that
        # defaulted to 0 would be indistinguishable from "no flop was chained",
        # and `assess` would then report a real failure as a parse artefact
        # (or worse, a 0-flop design as fine).
        assert sci.parse_chain_log("nothing here") == {
            "internal": None, "boundary": None, "total": None}

    def test_metadata_is_read_out_of_the_artefact(self):
        meta = sci.parse_chain_metadata(CHAINED_HEAD + "module spm(); endmodule")
        assert meta is not None
        assert meta["internalCount"] == 64 and meta["boundaryCount"] == 34
        assert sci.chain_order_counts(meta) == {
            "input": 1, "dff": 2, "output": 1}

    def test_flop_count_comes_from_the_input_netlist(self):
        assert sci.count_flops(_mapped_netlist(64)) == 64
        assert sci.count_flops(_mapped_netlist(7)) == 7

    def test_matching_chain_is_ok(self):
        v = sci.assess(sci.parse_chain_log(CHAIN_LOG),
                       sci.parse_chain_metadata(CHAINED_HEAD), 64)
        assert v["ok"] is True
        assert v["chain_length_matches_flop_count"] is True
        assert v["problems"] == []

    def test_flops_left_off_the_chain_is_not_ok(self):
        """THE defect this whole program exists to prevent."""
        v = sci.assess(sci.parse_chain_log(CHAIN_LOG),
                       sci.parse_chain_metadata(CHAINED_HEAD), 70)
        assert v["ok"] is False
        assert v["chain_length_matches_flop_count"] is False
        assert any("6 flip-flop(s) are NOT on the chain" in p
                   for p in v["problems"]), v["problems"]

    def test_stdout_and_metadata_disagreeing_is_not_ok(self):
        """KILLS: trusting one source when the two contradict each other."""
        log = CHAIN_LOG.replace("Length: 64", "Length: 61")
        v = sci.assess(sci.parse_chain_log(log),
                       sci.parse_chain_metadata(CHAINED_HEAD), 64)
        assert v["ok"] is False
        assert any("disagrees between the tool's stdout" in p
                   for p in v["problems"]), v["problems"]

    def test_no_measurable_length_is_not_ok(self):
        v = sci.assess({"internal": None, "boundary": None, "total": None},
                       None, 64)
        assert v["ok"] is False
        assert v["internal_chain_length"] is None

    def test_zero_flops_counted_cannot_validate_anything(self):
        """KILLS: `internal == input_flops` passing vacuously at 0 == 0."""
        v = sci.assess({"internal": 0, "boundary": 0, "total": 0}, None, 0)
        assert v["ok"] is False
        assert v["chain_length_matches_flop_count"] is False


class TestPrefixIsMeasuredNeverHardcoded:
    """KILLS: hard-coding Fault's `__uuf__` wrapper name into the LEC script.

    `fault chain` resynthesises and wraps the design, so every internal wire is
    renamed `\\<instance>.<name>`.  yosys `equiv_make` matches BY NAME, so LEC
    has to reproduce that prefix on the gold side — but a WRONG prefix does not
    error, it silently drops the compared-point count.  So it is measured, with
    a dominance requirement, and None when it cannot be established.
    """

    def test_dominant_prefix_is_found(self):
        text = ("\n".join(f"  wire \\__uuf__.creg[{i}] ;" for i in range(40))
                + "\n  wire \\__BoundaryScanRegister_input__0__.dout ;\n")
        assert sci.measure_internal_prefix(text) == "__uuf__"

    def test_no_dominant_prefix_yields_none(self):
        text = ("  wire \\aaa.x ;\n  wire \\aaa.y ;\n"
                "  wire \\bbb.x ;\n  wire \\bbb.y ;\n")
        assert sci.measure_internal_prefix(text) is None

    def test_netlist_with_no_dotted_names_yields_none(self):
        assert sci.measure_internal_prefix(_mapped_netlist(4)) is None


class TestLibertyIsNeverSubstituted:
    """KILLS: resolving another foundry's Liberty for an unknown PDK.

    `fault chain` REQUIRES --liberty.  The temptation is a default; a default
    would build a chain out of one library's cells for a design mapped to
    another.  ORGANIC #410 removed exactly that for the ATPG cell model.
    """

    def test_known_pdks_resolve(self):
        for pdk in ("sky130", "gf180", "ihp-sg13g2"):
            lib, note = sci.resolve_liberty(pdk, None)
            assert lib and lib.endswith(".lib"), pdk
            assert pdk in note

    def test_unknown_pdk_resolves_nothing(self):
        lib, note = sci.resolve_liberty("no-such-pdk", None)
        assert lib is None
        assert "no Liberty configured" in note

    def test_explicit_override_wins(self):
        lib, note = sci.resolve_liberty("sky130", "/pdk/mine.lib")
        assert lib == "/pdk/mine.lib" and note == "explicit --liberty"

    def test_liberty_table_keys_are_a_subset_of_the_atpg_pdk_table(self):
        """One PDK vocabulary, not two.  A key here with no `PDK_CONFIG` entry
        would let a design resolve its Liberty from this table and its cell
        model from nowhere."""
        assert set(sci.SCAN_LIBERTY) <= set(fatpg.PDK_CONFIG)


class TestGenericNetlistIsRefused:
    """KILLS: running scan insertion at a point in the flow where the netlist
    is still technology-generic.  Phase 2's `netlist.v` is `$_DFF_P_`/`$_NAND_`
    — `fault chain` cannot build a chain out of those, and a producer that
    tried would either crash or emit nonsense under a name that says scan."""

    def test_generic_netlist_short_circuits_before_docker(self, tmp_path):
        nl = tmp_path / "phase2/stage2/synth/netlist.v"
        nl.parent.mkdir(parents=True)
        nl.write_text("module m(); \\$_DFF_P_ _0_ (.C(c), .D(d), .Q(q)); "
                      "endmodule\n")
        rc, rep = sci.run_chain(tmp_path, "phase2/stage2/synth/netlist.v",
                                "clk", "sky130")
        assert rc == 2
        assert rep["stage"] == "input"
        assert "technology-GENERIC" in rep["error"]
        assert "published" not in rep      # nothing was published


class TestAreaCostIsRecorded:
    """A scan chain costs real area and the flow must be able to say how much
    without re-running anything.  KILLS: reporting insertion as free."""

    def test_histogram_delta(self):
        before = sci.cell_histogram(_mapped_netlist(4))
        after = sci.cell_histogram(
            _mapped_netlist(4)
            + "  sky130_fd_sc_hd__mux2_1 _m0_ (\n    .A0(a), .X(x)\n  );\n")
        assert sum(after.values()) - sum(before.values()) == 1
        assert before["sky130_fd_sc_hd__dfxtp_1"] == 4


class TestDftPortNamesAreKnownNotSniffed:
    """The five DFT ports are `fault chain` OPTION names this program passes.
    KILLS: sniffing them out of the produced netlist, which would make the LEC
    tie-off depend on a guess about the tool's output."""

    def test_ports_match_the_option_defaults(self):
        assert set(sci.FUNCTIONAL_MODE_TIEOFF) == {"sin", "shift", "test", "tck"}
        assert sci.SCAN_OUT_PORT == "sout"
        assert set(sci.DFT_PORTS) == {"sin", "shift", "test", "tck", "sout"}

    def test_functional_mode_drives_every_control_to_zero(self):
        # `test`=1 selects the boundary-scan path and the tck clock source;
        # `shift`=1 selects the scan-in path at every flop.  Either one makes
        # the netlist non-equivalent to its RTL, which is why both are 0 and
        # why lec_run's negative controls tie them to 1 and expect a failure.
        assert set(sci.FUNCTIONAL_MODE_TIEOFF.values()) == {0}
