#!/usr/bin/env python3
"""A tool that runs a checker must not report success over its verdict.

WHY THIS FILE EXISTS. `ppa-crosslayer/tools/head_to_head.py` writes a record
into the published corpus, runs `ppa_head_to_head_check.py` on it, PRINTS the
return code, and then `return 0` -- unconditionally. Its `ppa-e2e` twin did the
same, and there the plumbing made it starker still: `main` computes
`max(a or 0, b or 0)`, so the worst-rc machinery existed and was being fed a
hardcoded success.

SCOPED HONESTLY, because the first draft of this file overstated it. The
verdict is NOT thrown away: those tools pass `--json <tag>_report.json`, and
those reports carry `"ok": false` with the refusal -- h2h_A_report.json was
read to check. The defect is the EXIT STATUS alone. That still matters, because
an exit code is what an orchestrator reads, and a build step reporting success
having just been told rc 1 misreports to its caller whatever it wrote to disk.
Saying "the gate was ignored" would have been the more dramatic claim and the
false one.

WHAT IS PINNED. Every campaign tool that invokes a `*_check.py` program through
`subprocess` must let that program's `returncode` reach its own exit status --
or be LISTED below with a reason. A ledger and not a blanket rule, for the same
argument as the STA-stamp ledger: a blanket rule would have shipped red against
the call sites that legitimately tolerate a code, and a silence would let the
next discarded verdict in.

WHAT THIS DOES *NOT* CLAIM. It is a STRUCTURAL check over source: it proves the
`returncode` reaches a `return`/`raise`, and nothing more. It does NOT prove the
exit status is right in every branch, and it does not run any of these tools --
the behavioural half needs the campaign run trees and a container image, neither
of which a unit test has. Stated because a structural test that implies more
than it measures is the defect this lane keeps finding.

chip-AGNOSTIC: no design, PDK, vendor, node or codename literal.
"""
import ast
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[5]

#: The campaign tool trees. Absent on a plugin-only checkout, which is a SKIP
#: and not a pass.
TOOL_DIRS = (REPO / "docs" / "campaigns" / "ppa-crosslayer", REPO / "docs" / "campaigns" / "ppa-e2e")

#: Call sites that may hold a checker's `returncode` without routing it to the
#: exit status. EVERY entry states WHY, and an entry that turns out to
#: propagate after all is refused as stale by `test_the_ledger_has_no_stale_
#: entries` -- so this list cannot quietly become a parking space.
TOLERATED = {
    "analyze.py": (
        "it collects rc into a `fails` list and reports that list; the rc "
        "reaches a verdict by a different route than `return`"),
    "readjudicate.py": (
        "it raises SystemExit on a non-zero producer rc, and records the "
        "second invocation's code as `_exit_code_observed` in its report"),
    "build_arm.py": (
        "it is a BUILDER, not a publisher of a comparison: it reads the "
        "feasibility report it just produced and writes the adjudication "
        "forward as data -- `feasibility_verdict` and the per-axis statuses "
        "land in assembly.json, so a downstream reader gets the real verdict "
        "rather than an exit code that hid it"),
}

_CHECKER = "_check.py"


def _tool_files():
    for d in TOOL_DIRS:
        if not d.is_dir():
            continue
        for f in sorted(d.rglob("*.py")):
            yield f


def _invocations(tree):
    """(function_node, variable_name) for each `x = subprocess.run([... _check.py ...])`."""
    out = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for node in ast.walk(fn):
            if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
                continue
            call = node.value
            f = call.func
            name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", None)
            if name != "run":
                continue
            if _CHECKER not in ast.unparse(call):
                continue
            for t in node.targets:
                if isinstance(t, ast.Name):
                    out.append((fn, t.id))
    return out


def _exits_with(node):
    """The expression a `return` or `raise` carries, or None.

    `ast.Return` holds it on `.value` and `ast.Raise` on `.exc`. The first
    draft of this file read `.value` for both, so every `raise` reached raised
    AttributeError instead of answering -- and it surfaced only under the
    negative control, as a CRASH standing in for the assertion. A structural
    test that cannot read its own subject must not be counted as having
    checked it.
    """
    if isinstance(node, ast.Return):
        return node.value
    if isinstance(node, ast.Raise):
        return node.exc
    return None


def _verdict_is_consumed(fn, var):
    """Does `<var>.returncode` reach a return / raise / recorded verdict?"""
    exits = [n for n in ast.walk(fn)
             if isinstance(n, (ast.Return, ast.Raise)) and _exits_with(n) is not None]
    for node in exits:
        if f"{var}.returncode" in ast.unparse(_exits_with(node)):
            return True
    # `rc = r.returncode` then `return rc` / `raise SystemExit(rc)` -- one hop.
    for node in ast.walk(fn):
        if not isinstance(node, ast.Assign) or node.value is None:
            continue
        if f"{var}.returncode" not in ast.unparse(node.value):
            continue
        for t in node.targets:
            if not isinstance(t, ast.Name):
                continue
            for ex in exits:
                if t.id in ast.unparse(_exits_with(ex)):
                    return True
    return False


def _offenders():
    bad = []
    for f in _tool_files():
        try:
            tree = ast.parse(f.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for fn, var in _invocations(tree):
            if f.name in TOLERATED:
                continue
            if not _verdict_is_consumed(fn, var):
                bad.append(f"{f.relative_to(REPO)}::{fn.name} (`{var}`)")
    return bad


def test_the_premise_there_are_campaign_tools_that_run_a_checker():
    """Without this the guard below passes by finding nothing to look at."""
    if not any(d.is_dir() for d in TOOL_DIRS):
        pytest.skip("neither campaign tool tree is present in this checkout")
    seen = []
    for f in _tool_files():
        try:
            tree = ast.parse(f.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        seen.extend(f.name for _ in _invocations(tree))
    assert seen, (
        "no campaign tool invokes a `*_check.py` through subprocess any more. "
        "If that is a real change this guard is now vacuous and must be "
        "rewritten rather than left green over an empty population.")


def test_no_publisher_discards_the_verdict_of_the_checker_it_ran():
    if not any(d.is_dir() for d in TOOL_DIRS):
        pytest.skip("neither campaign tool tree is present in this checkout")
    bad = _offenders()
    assert not bad, (
        "these tools run a checker and never route its `returncode` to their "
        "own exit status, so they report SUCCESS to their caller over a "
        "refusal. (The checker's own --json report may still record the "
        "verdict; the defect being pinned here is the exit status.) " +
        repr(bad))


def test_the_ledger_has_no_stale_entries():
    """An entry that now propagates must be REMOVED, not left standing.

    Without this the tolerated list becomes a parking space: a call site is
    repaired, the exemption stays, and the next regression at that site is
    pre-forgiven.
    """
    if not any(d.is_dir() for d in TOOL_DIRS):
        pytest.skip("neither campaign tool tree is present in this checkout")
    stale = []
    for f in _tool_files():
        if f.name not in TOLERATED:
            continue
        try:
            tree = ast.parse(f.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        invs = _invocations(tree)
        if invs and all(_verdict_is_consumed(fn, v) for fn, v in invs):
            stale.append(f.name)
    assert not stale, (
        "these are listed as tolerated but now route the verdict to their exit "
        "status; drop the entry so the site is guarded again: " + repr(stale))


def test_every_ledger_entry_states_a_reason():
    for name, why in TOLERATED.items():
        assert why and len(why) > 30, (
            f"{name} is exempted without a real reason; an unexplained "
            "exemption is indistinguishable from an oversight")
