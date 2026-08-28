"""A one-token edit that switches a refusal off must not pass unnoticed.

Measured 2026-08-28, closing the 68x9 campaign: a wafer-sort yield gate whose
refusal arm was disabled with `if False and measured + 1e-9 < target:` lets a
12.5% yield pass a 90% target, and **0 of 612 matrix cells change colour**.
Every structure stays intact — the file, the flag, the edge, the declaration —
and only the decision changes.

The can-fail arm below is that exact mutation, read out of the mutant tree the
campaign produced, not a paraphrase of it.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import verdict_arm_disabled_by_a_constant_check as G

_PROGRAMS = Path(G.__file__).resolve().parent
_ROOT = _PROGRAMS.parents[3]


def _findings(src: str):
    found, reason = G.audit_source(src, "sample_check.py")
    assert reason is None, reason
    return found


# ---------------------------------------------------------------- can FAIL --
def test_the_campaign_mutation_is_reported():
    """`if False and <the real comparison>:` — the shape that escaped everything."""
    src = ("def main(measured, target):\n"
           "    if False and measured + 1e-9 < target:\n"
           "        return 1\n"
           "    return 0\n")
    found = _findings(src)
    assert len(found) == 1, found
    assert found[0]["shape"] == "and False"
    assert "never run" in found[0]["why"]


def test_an_always_true_arm_is_reported_too():
    """The mirror: a refusal nothing can avoid says as little as one nothing reaches."""
    src = ("def main(x):\n"
           "    if True or x.is_broken():\n"
           "        return 1\n"
           "    return 0\n")
    assert _findings(src)[0]["shape"] == "or True"


def test_a_constant_false_block_is_reported():
    assert _findings("def main():\n    if False:\n        return 1\n    return 0\n")


# ---------------------------------------------------------------- can PASS --
def test_the_default_value_idiom_is_not_a_dead_arm():
    """`(w or 1) > 1` decides a VALUE. Judging it reports 260 sites of nothing."""
    src = ("def main(ports):\n"
           "    return [d for d, w in ports if d == 'output' and (w or 1) > 1]\n")
    assert _findings(src) == []


def test_a_default_inside_a_call_argument_is_not_a_dead_arm():
    src = ("import re\n"
           "def main(text, start):\n"
           "    if re.match(r'\\\\w', text[start:start + 1] or ' '):\n"
           "        return 1\n"
           "    return 0\n")
    assert _findings(src) == []


def test_a_real_verdict_arm_is_clean():
    src = ("def main(measured, target):\n"
           "    if measured + 1e-9 < target:\n"
           "        return 1\n"
           "    return 0\n")
    assert _findings(src) == []


# ------------------------------------------------------------- fail-safe ----
def test_an_unparseable_module_is_unanalysable_not_clean():
    found, reason = G.audit_source("def main(:\n", "broken_check.py")
    assert found == [] and reason and "unparseable" in reason


# ------------------------------------------------------------ corpus sweep --
def test_the_repo_sweeps_clean():
    out = subprocess.run(
        [sys.executable, str(_PROGRAMS / "verdict_arm_disabled_by_a_constant_check.py"),
         "--root", str(_ROOT), "--strict"],
        capture_output=True, text=True)
    assert out.returncode == 0, out.stdout[-3000:]
