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

# The real corpus the sweep runs over. It was `_hostpaths.require_repo(
# "benchmark-data")` while the published cells were in this repository; they
# are in vibeic/benchmark-data now, so the resolver that knows where to look —
# and, when there is nowhere, says so as a skip rather than an empty sweep — is
# `_published_corpus`.
from _published_corpus import corpus_root, needs_corpus   # noqa: E402
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


def _sweep_labels(root: Path):
    """(old_label, new_label) for one project root, THROUGH THE PRODUCTION
    PATH: resolve+sniff the netlist exactly as `step_dft_lec_chain` does
    (`_dft_atpg_sniff_pdk`), then compare the pre-fix expression
    (`pdk or "generic_unmapped"`) against the landed helper."""
    sniff_nl, pdk = dosr._dft_atpg_sniff_pdk(root, _SYNTH_REL)
    old = pdk or "generic_unmapped"
    new = _label_under_test(pdk, sniff_nl)
    return old, new


def _fire_the_guard(tmp_path_factory, tag: str):
    """Run ONE injected mapped-but-unconfigured root through the production
    path and return `(old, new, fired)`.

    Extracted so the REACHABILITY proof below and the corpus sweep further down
    are the identical measurement rather than two hand-copied ones.
    """
    fire_root = _clean_root(tmp_path_factory, tag)
    _write(fire_root, "netlist.v", UNCONFIGURED_LIB_MAPPED)
    f_old, f_new = _sweep_labels(fire_root)
    fired = [(str(fire_root), f_old, f_new)] if f_old != f_new else []
    return f_old, f_new, fired


def _assert_the_guard_fired(f_old, f_new, fired):
    assert f_old == "generic_unmapped", (
        "precondition failed: the fixture's cell names now resolve to a "
        f"configured PDK ({f_old!r}) — pick a different invented library "
        "so this test keeps measuring the unconfigured-library branch")
    assert len(fired) >= 1, (
        "SWEEP DID NOT FIRE: the mapped-unknown case never entered the "
        "`mapped_unknown_library` branch — the guard's decision point was "
        "not reached, so the sweep proves nothing (exit-0 on 0 comparisons).")
    assert (f_old, f_new) == ("generic_unmapped", "mapped_unknown_library"), \
        f"guard entered the wrong branch: {f_old!r} -> {f_new!r}"


def test_the_guard_decision_point_is_reachable(tmp_path_factory):
    """(b) ON ITS OWN, AND WITHOUT THE PUBLISHED CORPUS.

    Direction (b) of the sweep below — "the guard's decision point is
    REACHABLE through the real `_dft_atpg_sniff_pdk`, not only by calling the
    labelling helper directly" — is a claim about THIS PLUGIN, and its whole
    subject is a root this test writes itself. It is asserted here so it keeps
    being measured in a checkout that holds no published cells; folding it into
    a corpus-gated test would have let the plugin lose its only proof that the
    branch is reachable at all, and lose it silently, the moment the results
    moved out of this repository.
    """
    f_old, f_new, fired = _fire_the_guard(tmp_path_factory, "firereach")
    _assert_the_guard_fired(f_old, f_new, fired)


@needs_corpus
def test_sweep_reaches_its_guard_and_is_false_positive_free(tmp_path_factory):
    """A SWEEP MUST REACH ITS GUARD — and stay quiet on complete designs.

    Two directions, both asserted:

      (a) REAL published corpus — every
          `**/phase2/stage2/synth/netlist.v` under the published benchmark
          corpus is swept through the identical production resolve+sniff+label
          path and MUST keep its old label. A relabel here would be a false
          positive on a legitimately-complete design.

      (b) The guard's decision point is REACHABLE — one injected mapped-but-
          unconfigured root (`UNCONFIGURED_LIB_MAPPED`, a purely invented
          library — see the section header above for why NanGate45 no longer
          serves) flows through the SAME path and its label CHANGES
          `generic_unmapped -> mapped_unknown_library`. `fired >= 1` is the
          proof the sweep actually entered the branch it guards, THROUGH THE
          REAL SNIFF, not by calling the labelling helper directly.

    Precondition asserted inline: `UNCONFIGURED_LIB_MAPPED` must itself sniff
    to no configured PDK, or this test would silently start measuring the
    named-PDK branch again the next time a library gains a PDK_CONFIG row —
    exactly the failure mode that retired the NanGate45 fixture.

    WHY IT IS CORPUS-GATED. (a) can only be asserted over netlists someone
    published; those are in vibeic/benchmark-data now, not in this checkout.
    `assert real_roots` used to be the honest guard against a vacuous sweep and
    it stays exactly as strict — but "there is no corpus to sweep" is not the
    same statement as "the sweep found nothing in the corpus", and only the
    second is a defect. The first is a skip that names the corpus; the second
    still fails here. (b) is ALSO asserted with no corpus at all, one test up.
    """
    corpus = corpus_root()
    real_roots = sorted({p.parents[3] for p in corpus.rglob("netlist.v")
                         if str(p).endswith(_SYNTH_REL)})
    assert real_roots, (
        f"no netlist found to sweep under the published corpus at {corpus} — "
        f"the corpus is present, so this is an empty sweep, not a missing one")

    changed, unchanged = [], []
    for root in real_roots:
        old, new = _sweep_labels(root)
        (changed if old != new else unchanged).append(
            (str(root), old, new))

    # (a) ZERO false positives on real, legitimately-complete designs.
    assert changed == [], \
        f"sweep relabelled a real corpus root (false positive): {changed}"

    # (b) The guard's decision point is REACHABLE. Inject one mapped-but-
    #     unconfigured root and run it through the identical production path.
    f_old, f_new, fired = _fire_the_guard(tmp_path_factory, "sweepfire")
    _assert_the_guard_fired(f_old, f_new, fired)

    # Honest coverage line: what was swept, what stayed quiet, what fired.
    print(f"SWEEP: real_roots={len(real_roots)} unchanged={len(unchanged)} "
          f"false_positives={len(changed)} injected_fired={len(fired)} "
          f"({f_old} -> {f_new} on the invented unconfigured-library root)")
