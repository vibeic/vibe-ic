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
import re
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import phase3_one_shot_runner as R  # noqa: E402

RUNNER_SRC = (PROG / "phase3_one_shot_runner.py").read_text()




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
    '_recorded("synth", step_synth), project,',  # recorded preflight dispatch
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




# ---- behavioural tests against the REAL helper the runner calls ----------










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
