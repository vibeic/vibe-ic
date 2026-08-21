"""BIDIRECTIONAL control for the SECOND way `fault chain` builds a scan chain
and then throws it away.

THE QUESTION the step's record exists to answer: why is there no scan
netlist? WHAT IT ACTUALLY REPORTED (pre-fix): "`fault chain` produced no scan
netlist" — TRUE and ADJACENT. It restates the missing artefact instead of
naming the cause, and reads identically to a design with no flip-flops to
chain. MEASURED on a design whose OTP macro is staged as LEF + Liberty with no
Verilog view: the chain was CONSTRUCTED (271 internal + 3 boundary = 274
cells) and then discarded, because fault's internal yosys re-synthesis was
handed no model for the macro the netlist instantiates.

`fault_scan_chain_insert.py` already carried this exact classifier shape for a
DIFFERENT cause (`chain_resynth_missing_header_ports`, the body-vs-header
`rst` defect); this adds the sibling for the unresolved-module cause.

chip-AGNOSTIC: pure string-in/list-out on yosys' own error text. The macro
name used below is `sky130_fd_sc_hd__dfrtp_1` — a PUBLIC sky130A standard
cell, the same name the plugin's own shipped header-defect test uses. No
vendor, SKU, process node or part number.
"""
from __future__ import annotations

import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import fault_scan_chain_insert as fsci  # noqa: E402

# The real run's log, with the vendor part number replaced by a PUBLIC sky130A
# cell name. Structure, spacing and the `.original` suffix are verbatim.
_REAL_LOG = (
    "Processing file /work/phase2/stage2/synth/chip_top_asic_synth.v…\n"
    "Processing module chip_top_asic…\n"
    "Chaining internal flip-flops…\n"
    "Internal scan chain successfully constructed. Length: 271\n"
    "Boundary scan cells successfully chained. Length:  3\n"
    "Total scan-chain length:  274\n"
    "Resynthesizing with yosys…\n"
    "\n"
    "Generating LALR tables\n"
    "WARNING: 183 shift/reduce conflicts\n"
    "ERROR: Module `\\sky130_fd_sc_hd__dfrtp_1' referenced in module "
    "`\\chip_top_asic.original' in cell `\\u_mem.u_mem' is not part of the "
    "design.\n"
    "A yosys error has occurred.\n")

# The OTHER built-then-discarded cause. Must stay classified as ITSELF.
_HEADER_LOG = (
    "Internal scan chain successfully constructed. Length: 66\n"
    "Boundary scan cells successfully chained. Length:  105\n"
    "Total scan-chain length:  171\n"
    "Resynthesizing with yosys…\n"
    "chained.v.chain-intermediate.v:10209: ERROR: Module port `\\rst' is not "
    "declared in module header.\n"
    "A yosys error has occurred.\n")

_fn = fsci.chain_resynth_unresolved_modules
_tot = fsci.chain_reported_total_length


def test_forward_names_the_unresolved_module():
    assert _fn(_REAL_LOG) == ["sky130_fd_sc_hd__dfrtp_1"]


def test_forward_recovers_the_constructed_chain_length():
    """Licenses the BUILT-then-discarded claim — the length must come from
    the tool's own output, not be assumed."""
    assert _tot(_REAL_LOG) == 274


def test_forward_run_chain_wires_the_classifier_into_the_report():
    src = Path(fsci.__file__).read_text(encoding="utf-8", errors="replace")
    assert "chain_resynth_unresolved_modules" in src
    assert "chain_built_then_discarded" in src
    for phrase in ("MISSING INPUT", "cut_netlist", "physical_cell_stubs",
                   "NOT repeatable"):
        assert phrase in src, (
            f"the emitted reason must carry {phrase!r} so the next reader "
            "is not sent to the wrong place")


def test_reverse_r1_quiet_on_unrelated_logs():
    """A classifier that fires on everything names nothing."""
    for other in (
        "",
        None,
        "error: unknown option `--skip-boundary'",
        "Processing module foo…\nNo flip-flops found; nothing to chain.\n",
        "ERROR: Module port `\\rst' is not declared in module header.\n",
        "ERROR: syntax error\n",
        "Total scan-chain length:  274\nA yosys error has occurred.\n",
    ):
        assert _fn(other) == [], other


def test_reverse_r2_the_two_causes_stay_separable():
    """The pre-existing header-port classifier must still fire on its own
    log (this fix must not shadow it), and vice versa — because the header
    branch is checked FIRST in run_chain, ordering is preserved."""
    hdr = fsci.chain_resynth_missing_header_ports
    assert hdr(_HEADER_LOG) == ["rst"]
    assert _fn(_HEADER_LOG) == []
    assert hdr(_REAL_LOG) == []


def test_reverse_r3_honest_built_then_discarded():
    no_build = ("Processing module top…\n"
                "ERROR: Module `\\sky130_fd_sc_hd__dfrtp_1' referenced in "
                "module `\\top' in cell `\\u0' is not part of the design.\n")
    assert _fn(no_build) == ["sky130_fd_sc_hd__dfrtp_1"], (
        "the module is still named when no chain was built")
    assert _tot(no_build) is None, (
        "with no chain-length line the length must be None, so run_chain "
        "must NOT claim the chain was built and discarded")


def test_reverse_r4_multiple_modules_named_once_each_in_order():
    multi = (_REAL_LOG
             + "ERROR: Module `\\sky130_fd_sc_hd__buf_2' referenced in module "
               "`\\top' in cell `\\u1' is not part of the design.\n"
             + "ERROR: Module `\\sky130_fd_sc_hd__dfrtp_1' referenced in "
               "module `\\top' in cell `\\u2' is not part of the design.\n")
    assert _fn(multi) == ["sky130_fd_sc_hd__dfrtp_1", "sky130_fd_sc_hd__buf_2"]


def test_reverse_r4_no_dependence_on_backslash_escaping():
    plain = ("ERROR: Module `top_cell' referenced in module `wrapper' in "
             "cell `u0' is not part of the design.\n")
    assert _fn(plain) == ["top_cell"]


def test_reverse_r4_repeated_length_lines_last_one_wins():
    assert _tot("Total scan-chain length:  10\n"
               "Total scan-chain length:  274\n") == 274
