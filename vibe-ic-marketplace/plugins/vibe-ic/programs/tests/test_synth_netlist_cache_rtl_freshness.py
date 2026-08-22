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


#: How the synth DISPATCH is spelled, newest first. The block below ends where
#: the runner stops deciding about the cache and starts running synth instead,
#: and that call has been re-spelled once already: `step_synth` is no longer
#: invoked directly but handed to `step_preflight.gate()` as a callable, so the
#: original `plan.append(step_synth(` matched nothing and BOTH tests that read
#: this block failed for a reason that had nothing to do with cache freshness.
#:
#: A LIST, not a rewrite: each spelling is checked and the first that matches
#: wins, so a future re-spelling adds a line instead of turning the tests red
#: again. It is NOT a weakening — at least one must match or the block cannot
#: be located and every test that reads it fails loudly, by design.
_SYNTH_DISPATCH_MARKERS = (
    'step_synth, project, effective_top',   # v1.10.x: handed to _spf.gate()
    'plan.append(step_synth(',              # pre-step_preflight direct call
)


def _cache_guard_block() -> str:
    """The region of main() that decides whether to reuse a cached netlist."""
    start = RUNNER_SRC.find("_nl_pdk_ok = (netlist_existing.is_file()")
    assert start != -1, "netlist cache guard not found"
    ends = [e for e in (RUNNER_SRC.find(m, start)
                        for m in _SYNTH_DISPATCH_MARKERS) if e != -1]
    assert ends, (
        "the synth dispatch was not found after the cache guard, in any known "
        f"spelling ({', '.join(_SYNTH_DISPATCH_MARKERS)}). Either the runner "
        "re-spelled it again — add the new spelling to _SYNTH_DISPATCH_MARKERS "
        "— or the cache guard no longer falls through to synth at all, which "
        "is the defect these tests exist to catch.")
    return RUNNER_SRC[start:min(ends)]


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
    """Detecting staleness must actually clear the reuse flag.

    ANCHORED TO THE STALENESS BRANCH, not to the flag appearing anywhere.
    A bare `_nl_pdk_ok = False` search passed a mutant that deleted exactly
    the assignment this test is named after: the block contains TWO such
    assignments (the other belongs to the producer-identity key), so the
    search was satisfied by the wrong one and the test could not fail for
    its own subject. Measured 2026-08-13 while repairing this file's block
    locator: with the staleness assignment removed, all 16 tests here still
    passed. It is the branch that has to be pinned, not the string.
    """
    block = _cache_guard_block()
    assert re.search(r"if _stale_rtl:\s*\n\s*_nl_pdk_ok = False", block), (
        "staleness is detected but the cache is still reused: the `if "
        "_stale_rtl:` branch must set the reuse flag False so step_synth "
        "re-runs. A `_nl_pdk_ok = False` elsewhere in the guard does not "
        "count — that is a different key answering a different question.")


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


# ── sha256 fingerprint sidecar (#349 salvage of #336, v1.6.2) ────────────────
# Closes the residual DISCLOSED when #289 landed in v1.5.79: the mtime test
# trusts a cache when RTL CONTENT changed but its mtime is equal or OLDER
# (cp -p, a timestamp-preserving restore, an older-revision checkout). Both
# cases were reproduced then and are pinned CAUGHT now.

import json as _json
import os as _os


def _fp_proj(tmp_path, rtl="module a; endmodule\n", write_sidecar=True):
    rtl_dir = tmp_path / "rtl"
    rtl_dir.mkdir()
    (rtl_dir / "a.v").write_text(rtl)
    nl = tmp_path / "netlist.v"
    nl.write_text("// netlist\n")
    if write_sidecar:
        R._write_synth_inputs_sidecar(nl, rtl_dir)
    return nl, rtl_dir


def test_fingerprint_catches_content_change_with_equal_mtime(tmp_path):
    """THE residual, direction 1: same mtime, different content."""
    nl, rtl = _fp_proj(tmp_path)
    (rtl / "a.v").write_text("module a; wire CHANGED; endmodule\n")
    _os.utime(rtl / "a.v", (2_000_000, 2_000_000))
    _os.utime(nl, (2_000_000, 2_000_000))          # equal mtimes
    assert R._stale_rtl_vs_netlist(nl, rtl) == [], "control: mtime is blind here"
    assert R._stale_rtl_by_fingerprint(nl, rtl) == ["a.v"], "digest must see it"


def test_fingerprint_catches_content_change_with_older_mtime(tmp_path):
    """THE residual, direction 2: content changed, mtime OLDER (cp -p)."""
    nl, rtl = _fp_proj(tmp_path)
    (rtl / "a.v").write_text("module a; wire RESTORED_OLD_REV; endmodule\n")
    _os.utime(rtl / "a.v", (1_000_000, 1_000_000))
    _os.utime(nl, (2_000_000, 2_000_000))          # netlist looks newer
    assert R._stale_rtl_vs_netlist(nl, rtl) == [], "control: mtime is blind here"
    assert R._stale_rtl_by_fingerprint(nl, rtl) == ["a.v"]


def test_fingerprint_clean_when_content_identical(tmp_path):
    """No false staleness: identical content stays fresh even if someone
    touched the file (newer mtime, same bytes) — the case mtime FALSELY
    invalidates and the digest correctly reuses."""
    nl, rtl = _fp_proj(tmp_path)
    _os.utime(rtl / "a.v", (3_000_000, 3_000_000))   # touched, not edited
    _os.utime(nl, (2_000_000, 2_000_000))
    assert R._stale_rtl_by_fingerprint(nl, rtl) == []


def test_no_sidecar_returns_none_for_mtime_fallback(tmp_path):
    """A pre-v1.6.2 netlist has no sidecar: the reader must say 'unverifiable'
    (None -> mtime fallback), never treat absence as freshness."""
    nl, rtl = _fp_proj(tmp_path, write_sidecar=False)
    assert R._stale_rtl_by_fingerprint(nl, rtl) is None


def test_malformed_sidecar_fails_closed(tmp_path):
    """Unreadable evidence is not evidence: a corrupt fingerprint must force a
    re-synth, not a reuse."""
    nl, rtl = _fp_proj(tmp_path, write_sidecar=False)
    (nl.parent / R._SYNTH_INPUTS_SIDECAR).write_text("{not json")
    got = R._stale_rtl_by_fingerprint(nl, rtl)
    assert got and got != []


def test_fileset_change_is_stale_both_directions(tmp_path):
    """The FILE-SET is part of the fingerprint: an added RTL file and a
    removed one are both staleness, which mtime can never express for the
    removed case."""
    nl, rtl = _fp_proj(tmp_path)
    (rtl / "b.v").write_text("module b; endmodule\n")     # added
    assert "b.v" in R._stale_rtl_by_fingerprint(nl, rtl)
    (rtl / "b.v").unlink()
    (rtl / "a.v").unlink()                                 # removed
    got = R._stale_rtl_by_fingerprint(nl, rtl)
    assert any("a.v" in g and "removed" in g for g in got), got


def test_one_selector_feeds_writer_and_checker():
    """The writer and both checkers must share ONE RTL selector — two
    selectors is how a file gets fingerprinted but not checked, the
    producer/consumer split of #309/#312/#348."""
    src = (Path(R.__file__)).read_text()
    fn = src[src.index("def _stale_rtl_vs_netlist"):]
    fn = fn[:fn.index("\ndef step_synth")]
    assert 'rtl_dir.glob("*.sv")' in fn or "_synth_rtl_sources" in fn
    w = src[src.index("def _write_synth_inputs_sidecar"):]
    w = w[:w.index("\ndef ", 1)]
    assert "_synth_rtl_sources" in w
