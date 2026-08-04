#!/usr/bin/env python3
"""Every RTL collector must skip the flow's OWN output, not just one of them.

The tree has four RTL-file collectors with four different exclusion policies:

    rtl_scan_scope.EXCLUDED_DIR_NAMES              has `steps`, `oracle_run`
    gate_utils.EXCLUDED_DIRS                       did NOT
    dispatch_register_default_reset_check.collect_files   no exclusions at all
    break_handler_safety_check.audit               no exclusions at all

`steps/` is the flow's own PUBLICATION VIEW — `step_canonicalize_artefacts`
re-publishes each stage's output under a directory named for the flow STEP, so
one emitted gate-level netlist appears there under two different step names.
`synth` was already excluded in gate_utils, but the publication path does not
contain the token `synth`, so the entry never matched.

The `steps` exclusion was added to rtl_scan_scope alone. The other three kept
reading the netlist, and on a large design that is not a slowdown, it is a HALT:

MEASURED, edge_llm_accel x nangate45 (3.0M cells, 348 MB netlist), all
collectors run over the SAME project at the SAME moment:

    rtl_scan_scope.authoritative_rtl_files      6 files       51,587 bytes
    gate_utils.find_rtl_files                  11 files  696,685,033 bytes  (13,506x)
    collect_files (dispatch_register…)         35 files  1,735,802,924 bytes (33,647x)

    /usr/bin/time, standalone, before -> after
      dispatch_register_default_reset_check  39.01 s 2,328,652 kB PASS -> 0.04 s 13,824 kB PASS
      bram_pdob_combinational_check          44.75 s 1,373,952 kB rc=2 -> 0.04 s 13,824 kB rc=2
      break_handler_safety_check             39.14 s 1,034,344 kB rc=2 -> 0.04 s 14,080 kB rc=2

All three TIMED OUT under the phase-2 umbrella's per-gate budget; the umbrella
FAILed and the flow halted at phase 2, so place-and-route never ran at all.

Note the verdicts are UNCHANGED (PASS->PASS, rc=2->rc=2). This change alters
what these gates READ, never what they conclude.

BIDIRECTIONAL NEGATIVE CONTROL: the first three tests FAIL pre-fix. The rest
pass both ways and pin the blast radius.

SECOND DRIFT, SAME SHAPE (vibe-ic#781 M1). The fix above put the policy in
`gate_utils.EXCLUDED_DIRS`, and `break_handler_safety_check` imported THE NAME
SET while keeping its own `& EXCLUDED_DIRS` comprehension. When the policy grew
a SUFFIX rule (the `<rtl>_out_of_cone/` sidecar), the name set did not change,
so this collector silently stayed out of the contract this file is named after —
measured, three collectors saw `design.v` while it also read a moved-aside
`orphan.v` and reported an ERROR against a file the flow does not compile. Two
causes, one root: a collector that imports DATA instead of calling the POLICY,
and a test that re-implemented the collector instead of driving it. Both are
closed here — `gate_utils.dir_parts_excluded` is the single policy FUNCTION, all
four collectors call it, and every test below drives the real one.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import gate_utils  # noqa: E402
import rtl_scan_scope  # noqa: E402
import dispatch_register_default_reset_check as drc  # noqa: E402
import break_handler_safety_check as bhs  # noqa: E402


BIG = "module big(); endmodule\n" + ("// filler\n" * 200)
SMALL = "module small(input clk); endmodule\n"


@pytest.fixture
def proj(tmp_path):
    """A project shaped like a real post-synthesis run."""
    p = tmp_path / "proj"
    (p / "phase2/stage1/rtl").mkdir(parents=True)
    (p / "phase2/stage1/rtl/design.v").write_text(SMALL)
    # the flow's own outputs, in the two shapes that matter
    (p / "phase2/stage2/synth").mkdir(parents=True)
    (p / "phase2/stage2/synth/netlist.v").write_text(BIG)
    for step in ("9_synthesis_yosys_mapped_netlist",
                 "14_synthesis_handoff_gate_pre_pnr_yosys_script_netl"):
        d = p / "steps/phase2/stage2" / step
        d.mkdir(parents=True)
        (d / "netlist.v").write_text(BIG)
    return p


def _names(files):
    return sorted(Path(f).name for f in files)


# ------------------------------------------------------------- the defect

def test_gate_utils_skips_the_publication_view(proj):
    """FAILS PRE-FIX. `steps/` is the flow's own output, not design RTL."""
    got = gate_utils.find_rtl_files(proj)
    assert not any("steps" in Path(f).parts for f in got), (
        f"gate_utils read the flow's own publication view: {[str(f) for f in got]}")
    assert _names(got) == ["design.v"]


def test_dispatch_collector_skips_flow_output(proj):
    """FAILS PRE-FIX. This collector had no exclusion of any kind."""
    got = drc.collect_files(proj)
    assert _names(got) == ["design.v"], (
        f"collect_files read flow output: {[str(f) for f in got]}")


def test_break_handler_collector_skips_flow_output(proj):
    """FAILS PRE-FIX. Same bare-rglob shape, a different file.

    This test used to RE-IMPLEMENT the collector inline with the raw
    `& EXCLUDED_DIRS` name set, so it asserted on a COPY and could never catch
    the collector drifting from the shared policy — which is exactly what
    happened when a SUFFIX rule was added to the policy and this gate, holding
    only the name set, silently missed it. It now drives the real collector, and
    the real audit reports what it actually read."""
    assert _names(bhs.collect_files(proj)) == ["design.v"]
    res = bhs.audit(proj)
    # the fixture has no break signals, so the gate self-skips — but it must
    # have self-skipped on ONE file, not on four, and it says which.
    assert res.summary.get("reason") in ("no_break_signals", None), res.summary
    assert res.summary.get("files_scanned") == ["design.v"], res.summary


def test_the_collectors_now_agree(proj):
    """FAILS PRE-FIX. Four policies was how the one-place fix stayed hidden.

    All FOUR, not two — a pairwise assertion is how the fourth one stayed out of
    the contract it is named in."""
    expect = _names(gate_utils.find_rtl_files(proj))
    assert _names(drc.collect_files(proj)) == expect
    assert _names(bhs.collect_files(proj)) == expect
    assert _names(rtl_scan_scope.authoritative_rtl_files(proj)) == expect


# ------------------------------------- guards (must pass BOTH ways)

def test_real_rtl_is_still_collected(proj):
    """The design's own RTL must never be dropped by an exclusion."""
    for got in (gate_utils.find_rtl_files(proj), drc.collect_files(proj)):
        assert "design.v" in _names(got)


def test_an_explicit_file_argument_is_still_honored(proj):
    """Pointing the gate AT a netlist on purpose must still work."""
    netlist = proj / "phase2/stage2/synth/netlist.v"
    assert drc.collect_files(netlist) == [netlist]


def test_input_is_deliberately_still_in_scope_for_gate_utils(tmp_path):
    """`input` is NOT added: a staged macro stub stays lintable.

    rtl_scan_scope excludes `input` because staged vendor enablement is not the
    design's authoritative RTL. These lint gates legitimately want to see it,
    and it is small. Adding it would be a silent COVERAGE change, not a
    performance fix — this test pins that decision so it is not made by
    accident later.
    """
    p = tmp_path / "proj"
    (p / "input/pdk_local/fakeram").mkdir(parents=True)
    (p / "input/pdk_local/fakeram/fakeram.v").write_text(SMALL)
    assert "fakeram.v" in _names(gate_utils.find_rtl_files(p))


def test_shared_contract_still_excludes_what_it_always_did():
    """The names gate_utils already had must all survive."""
    for name in ("db", "incremental_db", "output_files", "build", "sim",
                 "synth", "formal", "dft", "pnr", "gds", "reports",
                 ".git", "__pycache__", "node_modules"):
        assert name in gate_utils.EXCLUDED_DIRS


def test_added_names_match_the_other_contract():
    """The two names added are exactly the flow-output ones rtl_scan_scope has."""
    for name in ("steps", "oracle_run"):
        assert name in gate_utils.EXCLUDED_DIRS
        assert name in rtl_scan_scope.EXCLUDED_DIR_NAMES
