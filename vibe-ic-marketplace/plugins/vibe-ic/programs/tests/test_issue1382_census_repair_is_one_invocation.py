"""#1382 — the repair a failure message names must be the COMPLETE repair.

`gen_flow_matrix_census.py` has two halves: the anchored figures scattered
through prose (`--fix-figures`) and the generated census block in README.md
(the plain run). Each half's failure message used to name only its own half, so
following the instruction verbatim left the tree still failing — and failing
with a message that reads exactly like the one just repaired.

Measured on `24ff9530` before the fix: with the census block stale,
`--fix-figures` exits 0 having rewritten 0 files, and `--check` still exits 1.

These tests are cheap on purpose: they read the program, they do not run the
three-minute census. The behavioural proof lives in the PR body; what has to be
prevented from silently regressing is that a REMEDIATION STRING never again
names a partial repair.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

_REPO = Path(__file__).resolve().parents[5]
_GEN = _REPO / "tools" / "gen_flow_matrix_census.py"


def _source() -> str:
    return _GEN.read_text(encoding="utf-8", errors="replace")


def test_the_generator_offers_a_single_complete_repair_flag():
    """`--fix` exists. Without it there is no invocation that does both."""
    tree = ast.parse(_source())
    flags = {
        a.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and getattr(node.func, "attr", None) == "add_argument"
        for a in node.args
        if isinstance(a, ast.Constant) and isinstance(a.value, str)
    }
    assert "--fix" in flags, (
        "no --fix flag: the repair is still two invocations, and a caller who "
        f"runs one of them is left failing. flags seen: {sorted(flags)}")


def test_fix_figures_returns_early_but_fix_does_not():
    """The whole point: `--fix` must fall THROUGH to the census-block write.

    If `--fix` also returned early it would be a synonym for `--fix-figures`
    and this issue would be unfixed while looking fixed.
    """
    src = _source()
    m = re.search(r"if args\.fix_figures or args\.fix:(.+?)\n    if args\.check_figures",
                  src, re.S)
    assert m, ("the anchor-rewrite branch no longer runs for both flags; "
               "re-read this test before changing it")
    body = m.group(1)
    assert "if args.fix_figures:\n            return 0" in body, (
        "--fix-figures must still return early — its documented behaviour is "
        "'rewrite every anchored figure ... then exit'")
    # ...and there must be no unconditional return that would strand --fix.
    assert not re.search(r"\n        return 0\s*\n", body), (
        "an unconditional return in that branch makes --fix stop after the "
        "anchors, which is the exact half-repair this issue is about")


def test_neither_remediation_message_names_a_partial_repair():
    """A message that names half the repair is worse than no message.

    Both failure paths are checked: the stale-anchor line and the stale-census
    -block line. Each must point at `--fix`.
    """
    src = _source()
    findings = []
    for label, needle in (
            ("stale anchored figures",
             r"anchored figure\(s\) disagree with the tree"),
            ("stale census block",
             r"census block is stale")):
        m = re.search(needle, src)
        assert m, f"the {label} message has moved; re-read this test"
        # the remediation is quoted within ~400 chars of the diagnosis
        window = src[m.start():m.start() + 400]
        cmds = re.findall(r"gen_flow_matrix_census\.py([^`\\\n]*)", window)
        assert cmds, f"the {label} message names no remediation command"
        if not any("--fix" in c and "--fix-figures" not in c.split("--fix")[0]
                   for c in cmds):
            findings.append((label, cmds))
    assert findings == [], (
        "remediation message(s) still name only a partial repair — following "
        f"them leaves the tree failing: {findings}")
