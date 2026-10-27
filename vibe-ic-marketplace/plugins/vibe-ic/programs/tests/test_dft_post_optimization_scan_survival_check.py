#!/usr/bin/env python3
"""Tests for dft_post_optimization_scan_survival_check.py.

Closes vibe-ic's flow_matrix dimension-2 gap on Step 12: the old
files_exist-only gate could not fail on content, so an empty, wrong, or
scan-stripped post_dft_netlist.v all satisfied it. Each test below drives
the real predicate (`assess`), not a hand-simplified restatement of it, and
every FAIL case has a companion that proves the SAME fixture would PASS if
the one thing under test were fixed — the forward/reverse pairing this
codebase's own test-writing discipline requires.
"""
from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PROGRAMS = _HERE.parent
for p in (_PROGRAMS, _HERE):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import dft_post_optimization_scan_survival_check as M  # noqa: E402


def _nl(*lines: str) -> str:
    return "\n".join(lines) + "\n"


_SCAN_NETLIST = _nl(
    "module top(a, b, c);",
    "  SDFFRQD1 _f0_ (.D(a), .Q(b), .CLK(c));",
    "endmodule",
)

_PRE_DFT_NETLIST = _nl(
    "module top(a, b, c);",
    "  DFFRQD1 _f0_ (.D(a), .Q(b), .CLK(c));",
    "endmodule",
)

_GENUINE_POST_DFT = _nl(
    "module top(a, b, c, x, y);",
    "  SDFFRQD1 _f0_ (.D(a), .Q(b), .CLK(c));",
    "  BUF1 _b0_ (.A(x), .Y(y));",
    "endmodule",
)

_NO_SCAN_POST_DFT = _nl(
    "module top(a, b);",
    "  BUF1 _b0_ (.A(a), .Y(b));",
    "endmodule",
)


def _stage(tmp_path: Path, *, scan=None, pre_dft=None, post_dft=None) -> Path:
    dft = tmp_path / "phase2" / "stage2" / "dft"
    synth = tmp_path / "phase2" / "stage2" / "synth"
    dft.mkdir(parents=True, exist_ok=True)
    synth.mkdir(parents=True, exist_ok=True)
    if scan is not None:
        (dft / "scan_netlist.v").write_text(scan)
    if pre_dft is not None:
        (synth / "netlist.v").write_text(pre_dft)
    if post_dft is not None:
        (synth / "post_dft_netlist.v").write_text(post_dft)
    return tmp_path


# ── SKIPPED-CONDITION: no scan_netlist.v to compare against ───────────────

def test_no_scan_netlist_is_skipped_not_a_pass(tmp_path):
    """Step 11 never ran (no DFT declared): the check discloses, not passes
    silently. A design with no scan chain to lose is a different fact from
    one that lost it."""
    _stage(tmp_path)
    r = M.assess(tmp_path)
    assert r["verdict"] == "SKIPPED-CONDITION"
    assert r["rc"] == 2


def test_empty_scan_netlist_is_also_skipped(tmp_path):
    """A zero-byte scan_netlist.v is absence, not evidence of a chain to
    check against — same tier as the file being missing outright."""
    _stage(tmp_path, scan="")
    r = M.assess(tmp_path)
    assert r["verdict"] == "SKIPPED-CONDITION"


# ── FAIL mode 1: post_dft_netlist.v missing or empty ───────────────────────

def test_missing_post_dft_netlist_fails(tmp_path):
    _stage(tmp_path, scan=_SCAN_NETLIST)
    r = M.assess(tmp_path)
    assert r["verdict"] == "FAIL"
    assert r["rc"] == 1
    assert "missing or empty" in r["reason"]


def test_empty_post_dft_netlist_fails(tmp_path):
    _stage(tmp_path, scan=_SCAN_NETLIST, post_dft="")
    r = M.assess(tmp_path)
    assert r["verdict"] == "FAIL"


def test_reverse_a_populated_post_dft_netlist_does_not_fail_on_emptiness(tmp_path):
    """Negative control for mode 1: the ONLY change from the failing case
    above is giving post_dft_netlist.v real content — proves the FAIL was
    earned by emptiness, not by some other property of the fixture."""
    _stage(tmp_path, scan=_SCAN_NETLIST, post_dft=_GENUINE_POST_DFT)
    r = M.assess(tmp_path)
    assert r["verdict"] == "PASS"


# ── FAIL mode 2: post_dft_netlist.v is the pre-DFT netlist copied over ────

def test_post_dft_identical_to_pre_dft_fails(tmp_path):
    """The exact substitution bug the flow_matrix waiver named: Step 12's
    old files_exist-only gate could not tell a resynthesized netlist from
    the untouched pre-DFT one copied over verbatim."""
    _stage(tmp_path, scan=_SCAN_NETLIST, pre_dft=_PRE_DFT_NETLIST,
           post_dft=_PRE_DFT_NETLIST)
    r = M.assess(tmp_path)
    assert r["verdict"] == "FAIL"
    assert "byte-identical to the PRE-DFT netlist" in r["reason"]


def test_reverse_a_post_dft_netlist_that_merely_resembles_pre_dft_does_not_fail(
    tmp_path,
):
    """Negative control for mode 2: same pre-DFT content, but post-DFT now
    differs by even one real edit (the scan flop). Proves the FAIL above was
    earned by byte-identity, not merely by both files existing."""
    _stage(tmp_path, scan=_SCAN_NETLIST, pre_dft=_PRE_DFT_NETLIST,
           post_dft=_GENUINE_POST_DFT)
    r = M.assess(tmp_path)
    assert r["verdict"] == "PASS"


def test_no_pre_dft_netlist_staged_does_not_block_the_other_checks(tmp_path):
    """netlist.v (Step 9's output) is read defensively, not required: a
    project missing it entirely must still be judged on modes 1 and 3."""
    _stage(tmp_path, scan=_SCAN_NETLIST, post_dft=_GENUINE_POST_DFT)
    r = M.assess(tmp_path)
    assert r["verdict"] == "PASS"


# ── FAIL mode 3: scan chain vanished (post_dft has zero DFF-family cells) ──

def test_scan_chain_lost_fails(tmp_path):
    """scan_netlist.v proves DFT insertion ran; post_dft_netlist.v having
    zero DFF-family instances means Step 12 discarded the scan chain — the
    third substitution the old gate could not see."""
    _stage(tmp_path, scan=_SCAN_NETLIST, post_dft=_NO_SCAN_POST_DFT)
    r = M.assess(tmp_path)
    assert r["verdict"] == "FAIL"
    assert "did not survive" in r["reason"]
    assert r["scan_netlist_dff_count"] == 1
    assert r["post_dft_netlist_dff_count"] == 0


def test_reverse_a_post_dft_netlist_that_keeps_its_scan_flop_passes(tmp_path):
    """Negative control for mode 3: identical fixture, but post_dft_netlist.v
    now retains the scan flop alongside its buffering. Proves the FAIL above
    was earned by the flop count, not by the presence of the BUF1 cell."""
    _stage(tmp_path, scan=_SCAN_NETLIST, post_dft=_GENUINE_POST_DFT)
    r = M.assess(tmp_path)
    assert r["verdict"] == "PASS"
    assert r["post_dft_netlist_dff_count"] == 1


# ── real production data (not synthetic) — must not false-positive ────────

def test_real_ihp_sg13g2_spm_run_passes(tmp_path):
    """A real, successful spm x ihp-sg13g2 run (99 scan flops end to end,
    resynthesis preserved every one). Guards against the check being
    correct only on hand-built fixtures. Host-local, optional: the run tree
    is not shipped, so this reads its location from an env var and skips
    cleanly (not a FAIL) wherever that var is unset or the tree is absent.
    """
    import os
    run_env = os.environ.get("VIBE_IC_REAL_SPM_IHP_SG13G2_RUN")
    if not run_env:
        import pytest
        pytest.skip("VIBE_IC_REAL_SPM_IHP_SG13G2_RUN not set — no real run "
                    "tree location on this host")
    run = Path(run_env)
    if not run.is_dir():
        import pytest
        pytest.skip(f"real run tree not present at {run}")
    r = M.assess(run)
    assert r["verdict"] == "PASS", r["reason"]
    assert r["scan_netlist_dff_count"] == r["post_dft_netlist_dff_count"]
    assert r["scan_netlist_dff_count"] > 0


def test_cli_exit_codes_match_the_assess_rc(tmp_path):
    """The CLI entry point returns exactly the rc assess() computed — no
    second, drifting verdict->exit-code mapping."""
    _stage(tmp_path, scan=_SCAN_NETLIST, post_dft=_NO_SCAN_POST_DFT)
    rc = M.main([str(tmp_path)])
    assert rc == 1

    _stage(tmp_path, scan=_SCAN_NETLIST, post_dft=_GENUINE_POST_DFT)
    rc = M.main([str(tmp_path)])
    assert rc == 0


def test_scan_cell_reconciliation_detects_missing_d23_or_d24_cell():
    import dft_post_optimization_scan_survival_check as gate
    mapped = 'module top(input d, output q);\n dff u0 (.D(d), .Q(q));\n dff u1 (.D(d), .Q(q));\n endmodule\n'
    replaced = 'module top(input d, output q);\n sdff u0 (.D(d), .Q(q));\n sdff u1 (.D(d), .Q(q));\n endmodule\n'
    one_missing = 'module top(input d, output q);\n sdff u0 (.D(d), .Q(q));\n endmodule\n'
    cells = [{'instance': 'u0', 'cell': 'sdff'}, {'instance': 'u1', 'cell': 'sdff'}]
    result = gate.reconcile_scan_cell_list(mapped, replaced, replaced, cells, top='top')
    assert result['verdict'] == 'PASS' and result['flow109_acceptance'] == 'NOT_MEASURED'
    assert gate.reconcile_scan_cell_list(mapped, replaced, replaced, cells[:1], top='top')['reason'] == 'D23_SCAN_CELL_LIST_MISMATCH'
    assert gate.reconcile_scan_cell_list(mapped, replaced, one_missing, cells, top='top')['reason'] == 'D24_SCAN_CELL_LIST_MISMATCH'
    assert gate.reconcile_scan_cell_list(mapped, mapped, mapped, cells, top='top')['verdict'] == 'NOT_MEASURED'
    compact = replaced.replace('\n', ' ')
    assert gate.reconcile_scan_cell_list(mapped, compact, compact, cells, top='top')['verdict'] == 'PASS'


def test_yosys_normalization_ignores_format_and_rejects_invalid():
    first = 'module unit(input a, output q); assign q = a; endmodule\n'
    formatted = 'module unit ( input a , output q );\n  assign q=a ;\nendmodule\n'
    changed = 'module unit(input a, output q); assign q = ~a; endmodule\n'
    a = M.normalized_netlist_digest(first, top='unit')
    b = M.normalized_netlist_digest(formatted, top='unit')
    c = M.normalized_netlist_digest(changed, top='unit')
    bad = M.normalized_netlist_digest('not verilog', top='unit')
    assert a['status'] == b['status'] == c['status'] == 'MEASURED'
    assert a['input_sha256'] != b['input_sha256']
    assert a['normalized_sha256'] == b['normalized_sha256']
    assert a['normalized_sha256'] != c['normalized_sha256']
    assert a['flow109_acceptance'] == 'NOT_MEASURED'
    assert bad == {'status': 'NOT_MEASURED', 'reason': 'NETLIST_FORMAT_INVALID'}


def test_normalized_preroute_chain_reports_changed_point_without_d23():
    good = 'module unit(input a, output q); assign q = a; endmodule\n'
    fmt = 'module unit (input a, output q);\nassign q=a; endmodule\n'
    changed = 'module unit(input a, output q); assign q = ~a; endmodule\n'
    points = {'D24': good, 'D25': fmt, 'D26': good, 'D30': fmt}
    ok = M.compare_normalized_preroute_netlists(points, top='unit', requires_scan=True)
    assert ok['status'] == 'PASS' and ok['flow109_acceptance'] == 'NOT_MEASURED'
    bad = M.compare_normalized_preroute_netlists({**points, 'D26': changed}, top='unit', requires_scan=True)
    assert bad['status'] == 'FAIL' and bad['mismatch'] == ['D26']
    invalid = M.compare_normalized_preroute_netlists({**points, 'D26': 'not verilog'}, top='unit', requires_scan=True)
    assert invalid['status'] == 'NOT_MEASURED' and invalid['point'] == 'D26'
    no_scan = {'D22': good, 'D25': fmt, 'D26': good, 'D30': fmt}
    assert M.compare_normalized_preroute_netlists(no_scan, top='unit', requires_scan=False)['status'] == 'PASS'
    # D23 may legally differ: it is not a point in the D24-starting chain.
    d23_equivalent = 'module unit(input a, output q); wire n; assign n=~a; assign q=~n; endmodule\n'
    prior = M.normalized_netlist_digest(d23_equivalent, top='unit')
    assert prior['normalized_sha256'] != ok['points']['D24']['normalized_sha256']
    assert ok['status'] == 'PASS'
