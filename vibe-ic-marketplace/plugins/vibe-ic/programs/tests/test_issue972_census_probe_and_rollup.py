#!/usr/bin/env python3
"""vibe-ic#972 — two defects the empty-tree probe was reporting as one.

RE-MEASURED on ``origin/main`` at ``6525cf05`` before anything was changed, and
the issue's headline symptom did NOT reproduce:

    gate_discloses_denominator_check --population ci   rc 0, PASS,
                                                       0 findings,
                                                       50 probed / 74 declared
    tools/gen_flow_matrix_census.py --check
      launched with cwd inside an EMPTY git repository:
        [PASS] 63x8 census fresh: 504 cells over 8 dimensions; ...
        real 1m50.203s

1m50 is UNDER the probe's 120s bound, so nothing timed out and no
GATE_UNRUNNABLE was raised. The issue was written against a 2m07s measurement;
#978 (``38598e89``) has since changed the program and the number moved.

WHAT IS STILL TRUE, AND IS WHAT THESE TESTS PIN
===============================================
The two DEFECTS the issue names are both real, and neither one is a timing
fact:

(a) THE CENSUS ANSWERED FOR THE WRONG TREE. Look at what that measurement says:
    504 cells over 8 dimensions, from a directory holding one file. Every path
    in the program resolved off ``__file__``, the CI declaration handed it no
    subject at all, and so the answer did not depend on the input. The 110
    seconds were the symptom; a check that cannot be pointed anywhere is the
    defect, and it is the campaign's own subject. It also sat 8% under the
    bound, so any slower host does report it as unrunnable — the issue's
    measurement was not wrong, it was taken on a slower one.

(b) "UNRUNNABLE" WAS COUNTED AS "PASSED WITHOUT DISCLOSING". Both verdict lines
    in ``gate_discloses_denominator_check`` reported ``len(findings)`` under one
    sentence describing one kind, and named no gate. A run whose only finding is
    a GATE_UNRUNNABLE printed "1 gate(s) ... answer PASS over an empty tree
    without disclosing it" — a claim about an output that never existed.

Every fixture here is DISCOVERED: the census's command line is read out of the
tree that really launches it — the CI script through the repo's own parser and
expander, and the landing driver by DRIVING it with its launcher stubbed. A
hand-written copy of either would pass while the real wiring stayed broken.

WHERE THAT LAUNCH LIVES MOVED, and this module did not move with it.
``1e74ab469`` (owner decision, 2026-08-16) withdrew ``run "63x8 census
freshness"`` from ``tools/ci/repo_hygiene_gates.sh`` — the census is a question
about the campaign, not about whether a change breaks anything, and the two
tiers are now separate by construction. The check was not deleted; it is
started by ``gatekeeper_prepare_landing`` and re-checked in the suite. Both
tests below read that one deleted line and asserted there was exactly one of
it, so on ``origin/main`` they failed with ``found 0`` — reporting a wiring
defect that does not exist. The rule they enforce is a property of WHOEVER
STARTS THE CENSUS, so the population is discovered instead of named.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_REPO = _PROGRAMS.parents[3]
_CI_SCRIPT = _REPO / "tools" / "ci" / "repo_hygiene_gates.sh"
_GEN = _REPO / "tools" / "gen_flow_matrix_census.py"

#: The probe's own per-gate budget. The point of (a) is that the census gate no
#: longer needs a meaningful fraction of it; a bound generous enough to survive
#: a loaded host and still be decisive is one tenth of it.
_FAST_S = 12.0


def _gen_module():
    """The generator, imported rather than launched (the freshness test's
    posture — an import of a `__main__` script leaves no bytecode behind and
    costs no interpreter start)."""
    import importlib.util
    if not _GEN.is_file():
        pytest.skip(f"generator not present at {_GEN} (mirror tree)")
    spec = importlib.util.spec_from_file_location("_gen972", str(_GEN))
    mod = importlib.util.module_from_spec(spec)
    prev = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = prev
    return mod












# ── (a) the census answers for the tree it is pointed at ────────────────────









def test_the_default_subject_is_still_this_checkout(tmp_path):
    """No argument keeps the previous behaviour verbatim — the freshness test,
    the host-independence probe and a human all rely on it. A fix that made the
    subject follow the CWD would break every one of them from a different
    directory, so the default is pinned rather than left to be discovered by
    whoever runs pytest from somewhere else."""
    gen = _gen_module()
    state, counts = gen.classify_subject(gen.REPO_ROOT)
    assert state == gen.SUBJECT_OWN, (
        f"this checkout does not classify as its own subject: {state} "
        f"{counts}")
    assert (counts["census_inputs_present"]
            == counts["census_inputs_required"]), counts


def test_a_different_checkout_is_refused_rather_than_answered_about(tmp_path):
    """The third state, and the reason it is not folded into the second.

    The census imports the dimension modules through `sys.path` anchored on
    `__file__`. A tree that HAS a suite is therefore still one this program
    cannot count — and the honest answer is to say so, not to print its own
    numbers under a heading naming somebody else's tree. That substitution is
    what the measured run did.
    """
    gen = _gen_module()
    other = tmp_path / "other-checkout"
    for rel in gen.CENSUS_INPUTS_REL:
        p = other / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("# fixture\n", encoding="utf-8")
    readme = other / gen.README_REL
    readme.parent.mkdir(parents=True, exist_ok=True)
    readme.write_text(f"{gen.BEGIN}\nx\n{gen.END}\n", encoding="utf-8")

    state, counts = gen.classify_subject(other.resolve())
    assert state == gen.SUBJECT_CROSS_TREE, (
        f"a populated OTHER checkout classified as {state}: {counts}")
    lines = "\n".join(gen.subject_refusal_lines(state, other.resolve(), counts))
    assert str(gen.REPO_ROOT) in lines and str(other.resolve()) in lines, (
        f"the refusal must name BOTH trees, or a reader cannot tell which one "
        f"the numbers would have described:\n{lines}")


# ── (b) the roll-up names the kind and the gate ─────────────────────────────
