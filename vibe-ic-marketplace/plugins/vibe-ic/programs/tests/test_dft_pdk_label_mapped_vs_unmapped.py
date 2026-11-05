"""test_dft_pdk_label_mapped_vs_unmapped.py — the step-11 `pdk_detected` label
must say what was OBSERVED, not what could be NAMED.

THE DEFECT, measured on plugin v1.9.79 before this file existed:

`design_one_shot_runner._dft_atpg_sniff_pdk` returns a bare string, and `""`
collapses three different states into one —

  * recognised and nameable                       -> the PDK name
  * recognised but NOT nameable (SKU in a private
    config, empty in public installs)             -> ""
  * mapped to a library absent from PDK_CONFIG    -> ""

— and every caller wrote `pdk or "generic_unmapped"`.  So a netlist that is
fully technology-mapped is published as

    "pdk_detected": "generic_unmapped"
    "the netlist it was given carries no library-mapped cells"

REPRODUCED ON A PUBLIC PDK (NanGate45), no commercial library involved:

    INV_X1 / NAND2_X1 / AOI21_X1 / DFF_X1, zero `$_*_` primitives
        fault_atpg_run.is_generic_unmapped(...)        -> False   <- IS mapped
        fault_atpg_run.sniff_pdk_over_whole_netlist(..)-> None    -> "unmapped"

Two functions in ONE module give contradictory answers about the same file and
the wrong one reaches the reader.

WHY IT IS NOT MERELY MISLEADING PROSE.  `transition_coverage_check` requires
`pdk_detected == "generic_unmapped"` as part of the attestation that grants the
lenient ENGINE_LIMITED -> SKIPPED-CONDITION outcome.  Its own comment states the
intent: *"a MAPPED netlist with 0 pairs stays a hard ERROR (the producer never
emits ENGINE_LIMITED for it)"*.  The guard exists precisely to stop a mapped
netlist claiming an engine-limitation skip — and the mislabel hands a mapped
netlist exactly that qualification.  Correcting the label therefore TIGHTENS.

BIDIRECTIONAL NEGATIVE CONTROL.  The FORWARD tests do not assert on the mere
existence of the new helper — that would only prove a symbol is new.  They
resolve the label through `_label_under_test`, which falls back to the
PRE-FIX expression (`pdk or "generic_unmapped"`) when the helper is absent, so
against the byte-identical pre-fix file each forward test fails on the WRONG
ANSWER.  The REVERSE tests are written against the pre-fix call signature and
must pass BOTH before and after; they are what stops this repair from being a
filter narrowed until the count reaches zero.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# The real corpus the sweep runs over. It was `_hostpaths.require_repo(
# "benchmark-data")` while the published cells were in this repository; they
# are in vibeic/benchmark-data now, so the resolver that knows where to look —
# and, when there is nowhere, says so as a skip rather than an empty sweep — is
# `_published_corpus`.
import fault_atpg_run as fatpg              # noqa: E402


# ── netlist fixtures ────────────────────────────────────────────────────────
# All PUBLIC vocabularies.  NanGate45 is an open cell library; the commercial
# library this defect was first seen on is never named here.

NANGATE45_MAPPED = """\
module tinytop(clk, rst, d, q);
  input clk, rst, d;
  output q;
  wire n1, n2, n3;
  INV_X1   u1 (.A(d),   .ZN(n1));
  NAND2_X1 u2 (.A1(n1), .A2(rst), .ZN(n2));
  AOI21_X1 u3 (.A(n2),  .B1(d), .B2(rst), .ZN(n3));
  DFF_X1   u4 (.D(n3),  .CK(clk), .Q(q), .QN());
endmodule
"""

GENERIC_UNMAPPED = """\
module tinytop(clk, rst, d, q);
  input clk, rst, d;
  output q;
  wire n1, n2;
  $_NOT_  u1 (.A(d),  .Y(n1));
  $_NAND_ u2 (.A(n1), .B(rst), .Y(n2));
  $_DFF_P_ u3 (.C(clk), .D(n2), .Q(q));
endmodule
"""

# Gate-level but built from Verilog PRIMITIVE gates — NOT library-mapped.
PRIMITIVE_GATES_ONLY = """\
module tinytop(clk, d, q);
  input clk, d;
  output q;
  wire n1, n2;
  not  u1 (n1, d);
  nand u2 (n2, n1, clk);
  buf  u3 (q, n2);
endmodule
"""

SKY130_MAPPED = """\
module tinytop(clk, d, q);
  input clk, d;
  output q;
  wire n1;
  sky130_fd_sc_hd__inv_1  u1 (.A(d), .Y(n1));
  sky130_fd_sc_hd__dfxtp_1 u2 (.CLK(clk), .D(n1), .Q(q));
endmodule
"""








# ════════════════════════════════════════════════════════════════════════════
# FORWARD — must FAIL against the byte-identical pre-fix file
# ════════════════════════════════════════════════════════════════════════════





def test_fwd_positive_predicate_exists_and_is_positive():
    """`netlist_is_library_mapped` must answer the POSITIVE question, and must
    not be satisfied by the mere absence of a PDK name."""
    assert fatpg.netlist_is_library_mapped(NANGATE45_MAPPED) is True
    assert fatpg.netlist_is_library_mapped(GENERIC_UNMAPPED) is False






# ════════════════════════════════════════════════════════════════════════════
# REVERSE — written against the PRE-FIX signature; must pass BEFORE and AFTER
# ════════════════════════════════════════════════════════════════════════════













def test_rev_is_generic_unmapped_is_unchanged():
    """The pre-existing oracle keeps its exact contract."""
    assert fatpg.is_generic_unmapped(GENERIC_UNMAPPED) is True
    assert fatpg.is_generic_unmapped(NANGATE45_MAPPED) is False
    assert fatpg.is_generic_unmapped("") is False






def test_rev_generic_netlist_still_earns_the_engine_limited_leniency():
    """THE LOAD-BEARING REVERSE CASE.  A genuinely generic netlist must STILL
    be granted the documented ENGINE_LIMITED skip.  If this ever goes red the
    repair has swallowed the real behaviour underneath it."""
    tcc = pytest.importorskip("transition_coverage_check")
    blob = {"verdict": "ENGINE_LIMITED", "engine_limited": True,
            "capability_flag": "cap:at_speed_timing_graded_atpg",
            "sequential_evidence": {"verdict": "SEQ_PRESENT"},
            "pdk_detected": "generic_unmapped"}
    assert tcc.evaluate(blob).get("verdict") == "SKIPPED-CONDITION"


def test_rev_instantiated_modules_contract_is_unchanged():
    """The over-inclusive helper this builds on keeps its documented shape."""
    got = fatpg.instantiated_modules(NANGATE45_MAPPED)
    assert {"INV_X1", "NAND2_X1", "AOI21_X1", "DFF_X1"} <= got




# ════════════════════════════════════════════════════════════════════════════
# SWEEP — the guard's decision point must be REACHABLE through the REAL
# production path (`_dft_atpg_sniff_pdk`), not only through `_label_under_test`
# called directly with a hand-set `pdk=""`. Every forward test above proves the
# LABELLING function is correct in isolation; none of them proves the sniff
# ever actually HANDS it an unnameable-but-mapped netlist in production.
#
# NanGate45 CANNOT BE THE FIXTURE FOR THIS ANYMORE. MEASURED 2026-08-06: an
# earlier draft of this sweep used `NANGATE45_MAPPED` here too, and it stopped
# proving anything the same day this file's own core fix landed — v1.9.86
# ("a fully mapped NanGate45 netlist was labelled `unmapped`, so scan insertion
# refused") taught `PDK_CONFIG` NanGate45's `dff_cells` so the SCAN-INSERTION
# side could resolve a real Liberty for it. That is the correct, complementary
# fix — but it means `_dft_atpg_sniff_pdk` now NAMES NanGate45:
#
#     sniff('nangate45 DFF_X1/...') -> pdk == 'nangate45'   (was '' before v1.9.86)
#
# so the `mapped_unknown_library` branch this sweep exists to reach is no
# longer reachable with that fixture at all — `old == new == 'nangate45'`,
# which is a DIFFERENT branch of this same function (`test_rev_named_pdk_is_
# passed_through_unchanged`), not evidence the guard is broken. The fixture
# below uses a purely invented cell-naming convention that resolves to none of
# the four configured libraries (`fatpg.PDK_CONFIG` — gf180 / sky130 /
# ihp-sg13g2 / nangate45), so it stays in the branch this test is about
# regardless of which PDK gains config next.

_SYNTH_REL = "phase2/stage2/synth/netlist.v"

UNCONFIGURED_LIB_MAPPED = """\
module tinytop(clk, rst, d, q);
  input clk, rst, d;
  output q;
  wire n1, n2, n3;
  ACME_INV_1   u1 (.A(d),   .Y(n1));
  ACME_NAND2_1 u2 (.A(n1),  .B(rst), .Y(n2));
  ACME_AOI21_1 u3 (.A(n2),  .B(d), .C(rst), .Y(n3));
  ACME_DFF_1   u4 (.D(n3),  .CLK(clk), .Q(q));
endmodule
"""
