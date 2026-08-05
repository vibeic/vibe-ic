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

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import fault_atpg_run as fatpg              # noqa: E402
import design_one_shot_runner as dosr       # noqa: E402


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


def _clean_root(tmp_path_factory, tag: str) -> Path:
    """A temp root whose PATH cannot itself decide the thing under test.

    pytest's `tmp_path` embeds the TEST NAME in the directory, so a test named
    `..._sky130_...` would inject a live library token into every path built
    under it.  The name is controlled here and then ASSERTED token-free, so the
    harness can never be the thing answering the question.
    """
    root = tmp_path_factory.mktemp("nlroot") / tag
    root.mkdir(parents=True, exist_ok=True)
    tokens = [p for ps in (fatpg.pdk_cell_prefixes() or {}).values() for p in ps]
    low = str(root).lower()
    for t in tokens:
        assert t.lower() not in low, f"temp root {root} carries library token {t!r}"
    assert not re.search(r"_x\d|_ff_|_ss_|_tt_", low), f"temp root {root} carries a corner/cell token"
    return root


def _write(root: Path, name: str, text: str) -> Path:
    p = root / "phase2" / "stage2" / "synth"
    p.mkdir(parents=True, exist_ok=True)
    f = p / name
    f.write_text(text)
    return f


def _label_under_test(pdk, netlist: Path | None):
    """Resolve the published `pdk_detected` label.

    Uses the fixed helper when present; otherwise reproduces the PRE-FIX
    expression verbatim.  This is what makes the forward tests fail against the
    pre-fix file on the WRONG ANSWER rather than on a missing attribute.
    """
    fn = getattr(dosr, "_dft_atpg_pdk_label", None)
    if fn is None:
        return pdk or "generic_unmapped"          # the pre-fix expression
    return fn(pdk, netlist)


# ════════════════════════════════════════════════════════════════════════════
# FORWARD — must FAIL against the byte-identical pre-fix file
# ════════════════════════════════════════════════════════════════════════════

def test_fwd_mapped_public_library_is_not_called_unmapped(tmp_path_factory):
    """A fully technology-mapped NanGate45 netlist must not be published as
    carrying no library-mapped cells.  PRE-FIX: label == 'generic_unmapped'."""
    root = _clean_root(tmp_path_factory, "mappedpub")
    nl = _write(root, "tinytop_synth.v", NANGATE45_MAPPED)
    assert fatpg.is_generic_unmapped(NANGATE45_MAPPED) is False, \
        "precondition: this netlist IS mapped by the module's own oracle"
    assert _label_under_test("", nl) != "generic_unmapped"


def test_fwd_mapped_public_library_gets_the_named_state(tmp_path_factory):
    """The label must name the state that was actually observed."""
    root = _clean_root(tmp_path_factory, "mappedstate")
    nl = _write(root, "tinytop_synth.v", NANGATE45_MAPPED)
    assert _label_under_test("", nl) == "mapped_unknown_library"


def test_fwd_positive_predicate_exists_and_is_positive():
    """`netlist_is_library_mapped` must answer the POSITIVE question, and must
    not be satisfied by the mere absence of a PDK name."""
    assert fatpg.netlist_is_library_mapped(NANGATE45_MAPPED) is True
    assert fatpg.netlist_is_library_mapped(GENERIC_UNMAPPED) is False


def test_fwd_gap_prose_stops_demanding_what_it_already_has(tmp_path_factory):
    """PRE-FIX the disclosed-skip prose told the reader a 'library-MAPPED
    netlist is required' — about a library-mapped netlist — and blamed the OSS
    engine.  It must instead name the unconfigured-library gap."""
    root = _clean_root(tmp_path_factory, "gapprose")
    nl = _write(root, "tinytop_synth.v", NANGATE45_MAPPED)
    label = _label_under_test("", nl)
    try:
        prose = dosr._dft_atpg_gap_reason("", label)
    except TypeError:                       # pre-fix: single-arg signature
        prose = dosr._dft_atpg_gap_reason("")
    assert "IS technology-mapped" in prose
    assert "generic/UDP DFF forms" not in prose


def test_fwd_mapped_netlist_cannot_claim_the_engine_limited_leniency(tmp_path_factory):
    """THE TIGHTENING, and the proof this check can FAIL.

    `transition_coverage_check` grants ENGINE_LIMITED -> SKIPPED-CONDITION only
    on `pdk_detected == 'generic_unmapped'`, so that a MAPPED netlist cannot
    claim it.  With the honest label a mapped netlist is REFUSED that skip.
    """
    tcc = pytest.importorskip("transition_coverage_check")
    root = _clean_root(tmp_path_factory, "leniency")
    nl = _write(root, "tinytop_synth.v", NANGATE45_MAPPED)
    blob = {"verdict": "ENGINE_LIMITED", "engine_limited": True,
            "capability_flag": "cap:at_speed_timing_graded_atpg",
            "sequential_evidence": {"verdict": "SEQ_PRESENT"},
            "pdk_detected": _label_under_test("", nl)}
    out = tcc.evaluate(blob)
    assert out.get("verdict") != "SKIPPED-CONDITION", \
        "a MAPPED netlist must not be granted the engine-limited skip"


# ════════════════════════════════════════════════════════════════════════════
# REVERSE — written against the PRE-FIX signature; must pass BEFORE and AFTER
# ════════════════════════════════════════════════════════════════════════════

def test_rev_genuinely_generic_netlist_stays_unmapped(tmp_path_factory):
    """The case the label was always right about must STILL be right.  This is
    the control against narrowing the filter until the count hits zero."""
    root = _clean_root(tmp_path_factory, "genericstays")
    nl = _write(root, "tinytop_synth.v", GENERIC_UNMAPPED)
    assert _label_under_test("", nl) == "generic_unmapped"


def test_rev_named_pdk_is_passed_through_unchanged(tmp_path_factory):
    """A sniff that DID name a PDK must be published verbatim."""
    root = _clean_root(tmp_path_factory, "namedpdk")
    nl = _write(root, "tinytop_synth.v", SKY130_MAPPED)
    assert _label_under_test("sky130", nl) == "sky130"


def test_rev_absent_netlist_falls_back_safely():
    """No netlist to read -> the pre-existing label.  Fail-SAFE, never
    fail-open: the repair must never INVENT a mapped claim."""
    assert _label_under_test("", None) == "generic_unmapped"


def test_rev_unreadable_netlist_falls_back_safely(tmp_path_factory):
    """A path that is a DIRECTORY, not a file."""
    root = _clean_root(tmp_path_factory, "unreadable")
    d = root / "phase2" / "stage2" / "synth" / "tinytop_synth.v"
    d.mkdir(parents=True, exist_ok=True)
    assert _label_under_test("", d) == "generic_unmapped"


def test_rev_empty_netlist_falls_back_safely(tmp_path_factory):
    root = _clean_root(tmp_path_factory, "emptynl")
    nl = _write(root, "tinytop_synth.v", "")
    assert _label_under_test("", nl) == "generic_unmapped"


def test_rev_primitive_gate_netlist_is_not_library_mapped(tmp_path_factory):
    """`not`/`nand`/`buf` are LANGUAGE primitives, not standard cells.  A
    netlist built from them must not be promoted to 'mapped'."""
    root = _clean_root(tmp_path_factory, "primgates")
    nl = _write(root, "tinytop_synth.v", PRIMITIVE_GATES_ONLY)
    assert _label_under_test("", nl) == "generic_unmapped"


def test_rev_is_generic_unmapped_is_unchanged():
    """The pre-existing oracle keeps its exact contract."""
    assert fatpg.is_generic_unmapped(GENERIC_UNMAPPED) is True
    assert fatpg.is_generic_unmapped(NANGATE45_MAPPED) is False
    assert fatpg.is_generic_unmapped("") is False


def test_rev_gap_prose_for_a_named_pdk_is_unchanged():
    """Single-argument callers keep the exact pre-fix prose."""
    prose = dosr._dft_atpg_gap_reason("sky130")
    assert "generic/UDP DFF forms" in prose
    assert "sky130" in prose


def test_rev_gap_prose_for_a_genuinely_generic_netlist_is_unchanged():
    prose = dosr._dft_atpg_gap_reason("", "generic_unmapped")  \
        if _accepts_two(dosr._dft_atpg_gap_reason) else dosr._dft_atpg_gap_reason("")
    assert "generic/UDP DFF forms" in prose
    assert "generic_unmapped" in prose


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


def _accepts_two(fn) -> bool:
    import inspect
    try:
        return len(inspect.signature(fn).parameters) >= 2
    except (TypeError, ValueError):
        return False
