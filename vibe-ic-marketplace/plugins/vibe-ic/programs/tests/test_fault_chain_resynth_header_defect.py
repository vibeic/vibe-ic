"""test_fault_chain_resynth_header_defect.py — name the failure where
`fault chain` BUILDS a scan chain and then throws it away.

`fault chain` composes the scan wrapper's module HEADER from the design's own
ports plus the scan pins, but declares the chain reset in the BODY under the
fixed name `rst`. A design whose reset is called anything else leaves `rst`
declared-but-unlisted, and fault's INTERNAL yosys re-synthesis rejects the
netlist fault itself just wrote — so `scan_netlist.v`, a declared step-11
output, is never published.

MEASURED (opentitan_aes x sky130A, ghcr.io/vibeic/vibeic-eda:0.2.54, reset
`rst_ni`): the tool's own lines were

    Internal scan chain successfully constructed. Length: 66
    Boundary scan cells successfully chained. Length:  105
    Total scan-chain length:  171
    Resynthesizing with yosys...
    chained.v.chain-intermediate.v:10209: ERROR: Module port `\\rst' is not
    declared in module header.

Before this classifier the report carried only "`fault chain` produced no scan
netlist" plus a log tail — indistinguishable, to a blind run, from a design
that legitimately has no chain to build. The chain length lines prove it is
the opposite: the chain was sound and discarded.

chip-AGNOSTIC: the classifier is a pure string check on the tool's own error.
"""
import sys
from pathlib import Path

PROG_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG_DIR))

import fault_scan_chain_insert as fsci  # noqa: E402


# Verbatim tail of the real run (opentitan_aes x sky130A).
_REAL_LOG = (
    "Processing file /work/phase2/stage2/synth/aes_cipher_control_synth.v…\n"
    "Processing module aes_cipher_control…\n"
    "Chaining internal flip-flops…\n"
    "Internal scan chain successfully constructed. Length: 66\n"
    "Boundary scan cells successfully chained. Length:  105\n"
    "Total scan-chain length:  171\n"
    "Resynthesizing with yosys…\n"
    "/work/phase2/stage2/dft/scan_chain_work/chained.v.chain-intermediate.v"
    ":10209: ERROR: Module port `\\rst' is not declared in module header.\n"
    "A yosys error has occurred.\n")


def test_real_log_is_classified_as_the_header_port_defect():
    assert fsci.chain_resynth_missing_header_ports(_REAL_LOG) == ["rst"]


def test_classifier_is_quiet_on_unrelated_failures():
    """NEGATIVE CONTROL — a classifier that fires on everything names nothing.
    None of these is the header defect."""
    for other in (
        "",
        "error: unknown option `--skip-boundary'",
        "Processing module foo…\nNo flip-flops found; nothing to chain.\n",
        "ERROR: Module `\\sky130_fd_sc_hd__dfrtp_1' referenced in module "
        "`\\top' in cell `\\_1112_' is not part of the design.\n",
    ):
        assert fsci.chain_resynth_missing_header_ports(other) == [], other


def test_multiple_missing_ports_are_all_named_once_each_in_order():
    log = ("ERROR: Module port `\\rst' is not declared in module header.\n"
           "ERROR: Module port `\\scan_en' is not declared in module header.\n"
           "ERROR: Module port `\\rst' is not declared in module header.\n")
    assert fsci.chain_resynth_missing_header_ports(log) == ["rst", "scan_en"]


def test_unescaped_port_name_is_also_matched():
    """yosys prints the name escaped or plain depending on the identifier;
    the classifier must not depend on the backslash."""
    log = "ERROR: Module port `rst' is not declared in module header.\n"
    assert fsci.chain_resynth_missing_header_ports(log) == ["rst"]


def test_error_text_says_built_then_discarded_not_just_absent():
    """The whole point: the emitted reason must distinguish 'the chain was
    constructed and thrown away' from 'there was no chain'."""
    ports = fsci.chain_resynth_missing_header_ports(_REAL_LOG)
    assert ports, "precondition"
    # The classifier feeds run_chain's err_report; assert the vocabulary that
    # makes the report self-explaining is present in the module source, so a
    # future edit cannot quietly drop it back to a generic message.
    src = (PROG_DIR / "fault_scan_chain_insert.py").read_text()
    assert "chain_built_then_discarded" in src
    assert "upstream `fault chain` wrapper defect" in src
