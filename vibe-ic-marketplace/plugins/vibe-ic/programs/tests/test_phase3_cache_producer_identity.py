"""The phase-3 synth/PnR/GDS cache must be keyed on the RECIPE, not only on
the design inputs — EXECUTABLE, end-to-end through ``main()``.

THE DEFECT
==========
Every pre-existing key on this cache asks "did the INPUT change?":

  * ``_netlist_matches_liberty``                       — the PDK  (PR-A3)
  * ``_stale_rtl_by_fingerprint`` / ``_stale_rtl_vs_netlist``
                                                       — the RTL  (#289/#349)
  * ``_pnr_cache_valid_for``                           — the die  (#593/#596)

Not one of them asks "did the RECIPE change?". So a landed fix to the synth /
PnR / stream-out recipe is a SILENT NO-OP on any tree that already holds an
artefact: the flow reuses what the OLD code produced and reports PASS for code
that never ran. "We landed the fix, re-run to confirm" becomes structurally
unable to confirm anything.

MEASURED, three independent times in one convergence round:
  * a landed tie-cell fix left two steps failing with the exact message it was
    written to eliminate, until the netlist was moved aside BY HAND;
  * three staged files had to be deleted by hand before fixed emitters ran;
  * "netlist already present ... (skipped re-run to preserve provenance)" was
    followed by PnR reading the PREVIOUS DAY's DEF.

THE MUTATION THESE TESTS CATCH
==============================
Deleting any one of the three ``_producer_cache_valid_for`` call sites in
``main()`` — the #755 "fixed one site is not fixed the class" shape. Each of
the three producing steps has its own test below, so removing the key from any
one of them fails a named test rather than being absorbed by the other two.

A source-string test alone would not catch this: a permanently-True
``_prod_ok`` satisfies "the helper is mentioned in main()". These tests DRIVE
``main()`` and observe whether the step was actually invoked.

chip-AGNOSTIC: plugin version + runner source digest; no design, PDK, vendor
or part identifier anywhere.
"""
from __future__ import annotations

import ast
import inspect
import sys

from pathlib import Path

PROGS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGS))

import phase3_one_shot_runner as R  # noqa: E402

TOP = "chip_top"
DIE, UTIL = "200x200", 0.45


# ── unit level: the key itself ──────────────────────────────────────────────































# ── end-to-end: all THREE call sites, driven through main() ─────────────────























# THE REGRESSION, one test per call site so removing the key from ONE of the
# three fails a named test instead of hiding behind the other two.

















#: The producer KINDS this runner has. Not a count of call sites — see
#: `_producer_kinds`.
_PRODUCER_KINDS = {"synth", "pnr", "gds"}


def _producer_kinds(src: str, fn: str):
    """(kinds, unreadable) — the `kind` literal each `fn(...)` call site names.

    WHY A SET OF KINDS AND NOT A COUNT OF CALL SITES. This guard existed as
    `src.count("_write_producer_identity(") == 3`, and MEASURED on live main
    7903c1972305 (2026-09-03, host load 6.3, pinned image
    sha256:66c33ff2...) that read 4:

        E   AssertionError: each producing call site must stamp on success;
            found 4

    The fourth site is `phase3_one_shot_runner.py:47353`,
    `_write_producer_identity(_pl.pnr_dir(project), "pnr")`, added by
    `551560ba18` (PDN/EM first-pass resize, v1.14.30): when EM sizing forces a
    resize the PnR step is RE-DISPATCHED, so the SAME producer kind is stamped
    a second time. There is no fourth producing KIND — the runner still
    produces synth, pnr and gds — so the defect this tripwire exists to catch
    (#755: "a fourth producing step added without the key") did not happen.
    The guard was counting TEXT OCCURRENCES, which cannot tell a legitimate
    re-stamp from a new unguarded producer.

    Raising 3 to 4 would freeze an instant into a contract: the next
    re-dispatch expires it again, and it would STILL pass a genuinely new
    `_write_producer_identity(..., "drc")` site, because that is also 4.
    Deleting it would leave the #755 shape unguarded. So the population is
    defined by BEHAVIOUR — which producer kinds does `main()` stamp and
    consult — which is blind to re-stamping and loud about a new kind.

    A call site whose kind is not a readable string literal is returned in
    `unreadable` and is a FAILURE, not a silent skip: a guard that cannot read
    a site cannot vouch for it, and a computed kind is exactly how a new
    producer would arrive unseen.
    """
    kinds, unreadable = [], []
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, ast.Call):
            continue
        name = (node.func.id if isinstance(node.func, ast.Name)
                else getattr(node.func, "attr", None))
        if name != fn:
            continue
        kind = node.args[1] if len(node.args) > 1 else None
        for kw in node.keywords:
            if kw.arg == "kind":
                kind = kw.value
        if isinstance(kind, ast.Constant) and isinstance(kind.value, str):
            kinds.append(kind.value)
        else:
            unreadable.append(ast.unparse(node))
    return kinds, unreadable


#: The functions `main()` may consult the producer key THROUGH.
#:
#: vibe-ic#2166 moved the PnR and GDS reuse decisions out of `main()` into
#: `_cached_stage_decision`, because `main()` is not reachable from a test with
#: a prepared directory and so nothing about those decisions could be asserted
#: except by reading the source — the shape #2157 measured the cost of. The
#: `kind` LITERAL is still written at the call site in `main()`, so this guard
#: still reads it there and still fails on a producing kind that arrives with
#: no reuse consult. What moved is the NAME of the function the literal is
#: handed to, not the property. Both names are listed so a re-inline of either
#: call site is covered by the same population.
_CONSULTING_CALLS = ("_producer_cache_valid_for", "_cached_stage_decision")


def _consulted_kinds(src: str):
    """(kinds, unreadable) unioned over every consulting call `main()` makes."""
    kinds, unreadable = [], []
    for fn in _CONSULTING_CALLS:
        k, u = _producer_kinds(src, fn)
        kinds += k
        unreadable += u
    return kinds, unreadable


def test_all_three_call_sites_are_wired():
    """Tripwire for a fourth producing KIND being added without the key —
    the #755 shape ('fixed one site' vs 'fixed the class').

    Every kind the runner STAMPS must also be a kind it CONSULTS on reuse, and
    the two sets must be exactly the kinds this runner produces. A kind
    stamped but never consulted is an artefact nothing revalidates; a kind
    consulted but never stamped can never be reused at all.
    """
    src = inspect.getsource(R.main)
    stamped, stamp_bad = _producer_kinds(src, "_write_producer_identity")
    consulted, consult_bad = _consulted_kinds(src)

    assert not stamp_bad and not consult_bad, (
        "a producer call site names a kind this guard cannot read, so it "
        f"cannot vouch for it: {stamp_bad + consult_bad}")
    assert set(stamped) == _PRODUCER_KINDS, (
        f"the runner stamps producer kinds {sorted(set(stamped))}; the "
        f"guarded set is {sorted(_PRODUCER_KINDS)}. A new producing kind must "
        f"arrive WITH its cache key, not after it")
    assert set(consulted) == _PRODUCER_KINDS, (
        f"the runner consults producer kinds {sorted(set(consulted))}; the "
        f"guarded set is {sorted(_PRODUCER_KINDS)}. A reuse decision made "
        f"without the producer key is the #755 shape")


def test_the_kind_guard_still_refuses_a_new_unguarded_producer():
    """CONTROL, the direction that must stay RED.

    The counting form could not tell these two apart. This one must: a new
    KIND is a defect, a second stamp of an existing kind is the PDN/EM
    re-dispatch and is not.
    """
    src = inspect.getsource(R.main)

    # (a) a genuinely new producing kind, stamped and never consulted
    grown = src + (
        "\n\ndef _synthetic_new_producer(project):\n"
        "    _write_producer_identity(_pl.drc_dir(project), 'drc')\n")
    kinds, bad = _producer_kinds(grown, "_write_producer_identity")
    assert not bad
    assert set(kinds) != _PRODUCER_KINDS, (
        "a fourth producing KIND did not move the guarded set — the tripwire "
        "would not have caught the #755 shape it exists for")

    # (b) the measured legitimate case: the SAME kind stamped twice
    restamped = src + (
        "\n\ndef _synthetic_redispatch(project):\n"
        "    _write_producer_identity(_pl.gds_dir(project), 'gds')\n")
    kinds, bad = _producer_kinds(restamped, "_write_producer_identity")
    assert not bad
    assert set(kinds) == _PRODUCER_KINDS, (
        "a re-dispatch that stamps an existing kind a second time moved the "
        "guarded set; that is the false red this guard was rebuilt to stop")

    # (c) a kind the guard cannot read is a refusal, never a silent pass
    computed = src + (
        "\n\ndef _synthetic_computed_kind(project, kind):\n"
        "    _write_producer_identity(_pl.pnr_dir(project), kind)\n")
    _kinds, bad = _producer_kinds(computed, "_write_producer_identity")
    assert bad, (
        "a call site whose kind is a variable was read as if it named none; "
        "that is how a new producer arrives unseen")
