#!/usr/bin/env python3
"""The polarity ratchet is wired into the LANDING TIER, not only into a suite.

vibe-ic#712. `prose_polarity_consulted_check.py --ratchet` renders a MEMBERSHIP
verdict against `_OFFENDER_REGISTER`: it fails on an offender that is not
registered — a landing ADDING one — and on a register entry that outlived its
offender. A gate nobody runs at landing time stops a nothing, so the wiring is
pinned here as well as the behaviour.

WHY MEMBERSHIP AND NOT A COUNT, since a count is the obvious thing to wire:
measured across v1.17.51..v1.17.83 the polarity-blind population went
212 -> 213 -> 214 -> 213 -> 214 -> 215, because entries both ENTER and LEAVE. The
number moved DOWN inside a window in which three new offenders arrived, so a
count-based gate would have passed all three and a count-based bisect names the
wrong landing. Only the set names them.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_LAND = _REPO / "tools" / "gatekeeper-land.sh"
_PLUGIN = _REPO / "vibe-ic-marketplace" / "plugins" / "vibe-ic"
_GATE = _PLUGIN / "programs" / "prose_polarity_consulted_check.py"

#: A prose extractor of exactly the shape the scanner is looking for: it
#: `.search`es text and writes the MATCH-DERIVED value into a record, and it
#: never consults the polarity vocabulary. Nothing about it is special — that is
#: the point, it is what an ordinary careless landing looks like.
_SYNTHETIC_OFFENDER = '''\
import re

_TARGET_RE = re.compile(r"target is (\\\\w+)")


def read_target(text, out):
    m = _TARGET_RE.search(text)
    if m:
        out["target"] = m.group(1)
    return out
'''


def _run_gate(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(_GATE), *args],
                          capture_output=True, text=True, timeout=900)


# ── the WIRING: red before it exists ──────────────────────────────────────
def test_the_cheap_tier_runs_the_polarity_ratchet():
    """The landing tier must invoke the gate, in `--ratchet` mode.

    RED before the wiring: this is the assertion that fails on a tree where the
    gate exists and nothing at landing time runs it.
    """
    text = _LAND.read_text(encoding="utf-8")
    lines = [ln for ln in text.splitlines()
             if "prose_polarity_consulted_check.py" in ln]
    assert lines, (
        "tools/gatekeeper-land.sh never invokes prose_polarity_consulted_check.py; "
        "a gate nobody runs at landing time stops nothing")
    # the invocation and its flag may be split across a line continuation
    joined = text.replace("\\\n", " ")
    inv = [ln for ln in joined.splitlines()
           if "prose_polarity_consulted_check.py" in ln]
    assert any("--ratchet" in ln for ln in inv), (
        "the landing tier runs the gate WITHOUT --ratchet. The no-argument mode "
        "compares against a baseline debt file and prints an errand naming a "
        "write flag; a landing gate must name the offender and its owner, never "
        "a flag that banks it.\n" + "\n".join(inv))
    assert any(re.search(r'run\s+"cheap:', ln) for ln in inv), (
        "the invocation is not in the CHEAP tier, which is the list the "
        "pre-push hook and land_gate.sh run")


# ── the BEHAVIOUR, both directions ────────────────────────────────────────
def test_the_ratchet_refuses_a_tree_carrying_an_unregistered_offender(tmp_path):
    """A synthetic tree with one unregistered offender must be REFUSED."""
    root = tmp_path / "plugin"
    (root / "programs").mkdir(parents=True)
    (root / "programs" / "careless_landing.py").write_text(_SYNTHETIC_OFFENDER)
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"_comment": "synthetic", "known": []}))

    r = _run_gate("--root", str(root), "--baseline", str(baseline), "--ratchet")
    assert r.returncode == 1, (
        "an unregistered polarity-blind extractor did not block:\n"
        f"{r.stdout}\n{r.stderr}")
    assert "careless_landing::read_target" in r.stdout, (
        "the refusal must NAME the offender:\n" + r.stdout)
    assert "register" in r.stdout.lower()


def test_the_ratchet_passes_the_tree_that_ships():
    """And it must not refuse everything: the shipped tree is GREEN.

    A gate that cannot pass is not a gate — it is a ban, and this repo has
    already learned to distrust one.
    """
    r = _run_gate("--ratchet")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "[PASS]" in r.stdout


def test_the_refusal_names_no_write_flag():
    """An errand is not a finding (hygiene census #2066, CZH-12).

    The red must name the offender and the owning lane. A red that also prints
    "re-run with --write-baseline" invites the next lane to bank every offender
    that run happened to see as accepted debt.
    """
    root = Path(__file__).parent
    r = _run_gate("--root", str(root), "--ratchet")
    for flag in ("--write-baseline", "--record-shrink"):
        assert flag not in r.stdout, (
            f"the ratchet's output offers {flag}, which banks the finding "
            f"instead of reporting it:\n{r.stdout}")


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__, "-q"]))
