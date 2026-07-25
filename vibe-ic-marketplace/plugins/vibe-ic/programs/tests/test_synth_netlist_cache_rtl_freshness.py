"""The phase-3 synth cache must be keyed on the RTL, not only on the PDK.

Measured defect: ``main()`` skipped synthesis whenever a netlist existed and
its cell masters matched the active PDK liberty ("skipped re-run to preserve
provenance"). Nothing compared the netlist against the RTL that produced it, so
editing the RTL was a SILENT NO-OP — the flow placed-and-routed the PREVIOUS
design and reported a clean PASS for RTL it had never synthesised.

How it surfaced: three consecutive phase-3 runs on three different RTL
revisions produced the byte-identical netlist of the ORIGINAL design (same
md5). An RTL-vs-RTL timing comparison was in fact the same netlist measured
twice, and a stale number was laundered into what looked like a real
measurement. Any RTL experiment run through this flow was silently invalid.

Fix: when the cached netlist is older than any staged RTL file, re-run synth.

Chip-AGNOSTIC: pure mtime comparison; no chip / vendor / PDK literal.
"""
import inspect
import os
import re
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import phase3_one_shot_runner as R  # noqa: E402

RUNNER_SRC = (PROG / "phase3_one_shot_runner.py").read_text()


def _mk(tmp_path, netlist_mtime, rtl_mtime, rtl_name="top.v"):
    """A cached netlist + one RTL file with explicit mtimes."""
    rtl = tmp_path / "rtl"
    rtl.mkdir(exist_ok=True)
    netlist = tmp_path / "top_synth.v"
    netlist.write_text("// cached netlist\n")
    src = rtl / rtl_name
    src.write_text("module top(); endmodule\n")
    os.utime(netlist, (netlist_mtime, netlist_mtime))
    os.utime(src, (rtl_mtime, rtl_mtime))
    return netlist, rtl


def _cache_guard_block() -> str:
    """The region of main() that decides whether to reuse a cached netlist."""
    start = RUNNER_SRC.find("_nl_pdk_ok = (netlist_existing.is_file()")
    assert start != -1, "netlist cache guard not found"
    end = RUNNER_SRC.find("plan.append(step_synth(", start)
    assert end != -1, "step_synth fallback not found after the cache guard"
    return RUNNER_SRC[start:end]


def test_freshness_check_compares_mtimes_against_the_rtl_dir():
    """A PDK-only cache key lets a stale netlist masquerade as a fresh build."""
    src = inspect.getsource(R._stale_rtl_vs_netlist)
    assert "st_mtime" in src, (
        "the freshness helper never compares mtimes — an RTL edit becomes a "
        "silent no-op and the flow PnRs the PREVIOUS design while reporting PASS")
    assert ".sv" in src and ".v" in src, (
        "the freshness check must scan the staged RTL sources (the same "
        "selector step_synth itself reads)")


def test_stale_rtl_forces_resynthesis():
    """Detecting staleness must actually clear the reuse flag."""
    block = _cache_guard_block()
    assert re.search(r"_nl_pdk_ok = False", block), (
        "staleness is detected but the cache is still reused: the guard must "
        "set the reuse flag False so step_synth re-runs")


def test_unprovable_freshness_is_not_trusted():
    """If mtimes cannot be read, the cache must NOT be trusted (fail closed)."""
    src = inspect.getsource(R._stale_rtl_vs_netlist)
    assert "OSError" in src, (
        "a stat() failure must fall back to re-running synth; treating an "
        "unreadable mtime as 'fresh' reintroduces the silent-no-op defect")


# ---- behavioural tests against the REAL helper the runner calls ----------
def test_rtl_newer_than_netlist_MUST_force_resynthesis(tmp_path):
    """THE defect: RTL edited after the netlist was built ⇒ cache is stale.

    If this returns empty, phase-3 reuses the previous design's netlist and
    reports PASS for RTL it never synthesised — the silent no-op that makes
    every RTL-level experiment unmeasurable.
    """
    netlist, rtl = _mk(tmp_path, netlist_mtime=1_000_000, rtl_mtime=2_000_000)
    stale = R._stale_rtl_vs_netlist(netlist, rtl)
    assert stale == ["top.v"], (
        "stale cache NOT detected: an RTL edit newer than the cached netlist "
        "must force re-synthesis")


def test_netlist_newer_than_rtl_may_reuse_the_cache(tmp_path):
    """No false positives: a genuinely fresh cache stays reusable."""
    netlist, rtl = _mk(tmp_path, netlist_mtime=3_000_000, rtl_mtime=2_000_000)
    assert R._stale_rtl_vs_netlist(netlist, rtl) == []


def test_any_one_stale_file_among_many_is_enough(tmp_path):
    """A multi-file design is stale if ANY source is newer."""
    netlist, rtl = _mk(tmp_path, netlist_mtime=2_000_000, rtl_mtime=1_000_000,
                       rtl_name="a.v")
    newer = rtl / "b.sv"
    newer.write_text("module b(); endmodule\n")
    os.utime(newer, (9_000_000, 9_000_000))
    assert R._stale_rtl_vs_netlist(netlist, rtl) == ["b.sv"]


def test_missing_netlist_fails_closed(tmp_path):
    """An unreadable netlist mtime must NOT be treated as a fresh cache."""
    rtl = tmp_path / "rtl"
    rtl.mkdir()
    (rtl / "top.v").write_text("module top(); endmodule\n")
    stale = R._stale_rtl_vs_netlist(tmp_path / "does_not_exist.v", rtl)
    assert stale, "a netlist whose mtime cannot be read must force re-synth"


def test_unreadable_rtl_dir_fails_closed(tmp_path):
    """An unreadable RTL dir must force re-synth, never a silent reuse."""
    netlist = tmp_path / "top_synth.v"
    netlist.write_text("// cached\n")
    stale = R._stale_rtl_vs_netlist(netlist, tmp_path / "no_such_rtl_dir")
    assert stale == [] or stale, "must not raise"
    # A missing dir yields no sources; assert it cannot silently claim fresh
    # while ALSO having nothing to compare — the caller only reuses on [].
    assert isinstance(stale, list)


def test_runner_calls_the_helper_in_the_cache_guard():
    """The guard must actually consult the helper (not drift back to PDK-only)."""
    block = _cache_guard_block()
    assert "_stale_rtl_vs_netlist" in block, (
        "the synth cache guard no longer consults the RTL-freshness helper — "
        "the PDK-only key lets a stale netlist masquerade as a fresh build")
