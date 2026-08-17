#!/usr/bin/env python3
"""The orphan scan knew two venues while the hygiene tier was entered from a
third, so it called a blocking gate unreachable.

MEASURED. v1.10.59 (97d5e57a2) added three true words to
`repo_hygiene_parallel.py`:

    ENFORCEMENT: blocking — incomplete ownership, termination-pending work,
    missing records, or an undecided gate returns rc 2 and stops the hygiene
    tier.

`flow_gate_enforcement_audit` answered:

    ORPHANED — declare an intent, are NOT in the flow definition, and no
    repo-gate suite invokes them either
      repo_hygiene_parallel  (declared blocking)
    [FAIL] 1 NEW gate(s) declare an intent they are not wired for

Both halves of that sentence were checked; the sentence was still false.
`gatekeeper_review.repo_hygiene_gate` runs `repo_hygiene_parallel.py` as the
PRIMARY hygiene entry point (falling back to `tools/ci/repo_hygiene_gates.sh`
only when the coordinator is absent), a non-zero rc makes `GateResult.green`
false, that turns the verdict to REQUEST_CHANGES, and `tools/gatekeeper-land.sh`
will not land on it. The gate had not regressed between 6d70bd74c and HEAD —
only its DECLARATION was new, and a declaration is what makes a program a
candidate for this scan at all. The audit was reading two venues out of three.

WHAT THIS FILE HAS TO PROVE, and why every test is paired: the cheap way to
clear an orphan finding is to make "wired" mean more things until nothing is
ever unwired. A venue widened without a matcher tightened is a scan that has
stopped scanning. So each case below that shows the finding CLEARED is next to
one that shows a planted defect still CAUGHT — a declared gate nobody runs, a
gate merely NAMED IN PROSE by the runner, and a runner that cites its own path.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

_TESTS = Path(__file__).resolve().parent
_PROGRAMS = _TESTS.parent
_PLUGIN = _PROGRAMS.parent


def _audit_mod():
    """A private copy, so a sibling test's `sys.modules` entry cannot decide
    which version of the program this file measures."""
    spec = importlib.util.spec_from_file_location(
        "_fgea_venue3", _PROGRAMS / "flow_gate_enforcement_audit.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_DECLARES_BLOCKING = (
    '"""A gate that means it.\n'
    '\n'
    'ENFORCEMENT: blocking — rc 2 stops the tier.\n'
    '"""\n'
)


def _tree(root: Path, *, extra: dict, runner: str | None = None,
          ci: str | None = None):
    """A synthetic plugin with an EMPTY flow definition, so every program in
    `extra` is absent from venue 1 by construction and the test is about venues
    2 and 3 only.

    `runner` is the body of `gatekeeper_review.py` (venue 3); `ci` is the body
    of a `tools/ci/*.sh` file (venue 2). Passing neither leaves that venue
    genuinely absent, which the report must state rather than silently treat as
    a venue that cleared somebody.
    """
    programs = root / "programs"
    programs.mkdir(parents=True, exist_ok=True)
    for name, body in extra.items():
        (programs / f"{name}.py").write_text(body)
    if runner is not None:
        (programs / "gatekeeper_review.py").write_text(runner)
    if ci is not None:
        ci_dir = root / "tools" / "ci"
        ci_dir.mkdir(parents=True, exist_ok=True)
        (ci_dir / "repo_hygiene_gates.sh").write_text(ci)
    flow = root / "flow.yaml"
    flow.write_text("steps: []\n")
    return flow, programs


def _orphans(m, flow, programs):
    return sorted(o["gate"] for o in m.audit(flow, programs)["orphaned"])


# --------------------------------------------------- (a) the planted defects
# These are the reason the fix cannot be "count more things as wired".

def test_a_declared_gate_that_nothing_runs_is_still_orphaned(tmp_path):
    """THE defect the scan exists to find, with all three venues present and
    none of them naming the gate. If this ever goes quiet, the widening below
    has eaten the scan."""
    m = _audit_mod()
    flow, programs = _tree(
        tmp_path, extra={"lonely_check": _DECLARES_BLOCKING},
        runner='"""Runs some gates."""\nX = "other_check.py"\n',
        ci='python3 "$PG/another_check.py"\n')
    assert _orphans(m, flow, programs) == ["lonely_check"]
    assert m.main(["--flow", str(flow), "--programs", str(programs),
                   "--baseline", str(programs / "nonexistent.json")]) == 1


def test_a_gate_named_only_in_the_runners_prose_is_still_orphaned(tmp_path):
    """The false-negative this widening could have introduced, and the reason
    venue 3 does NOT reuse venue 2's matcher.

    `repo_gate_source` strips COMMENT LINES and is then matched with a bare
    token, which is sound for shell. Python's prose lives in DOCSTRINGS, which
    are not comment lines and survive that stripping — `gatekeeper_review.py`
    documents at length, including paragraphs about gates it deliberately does
    NOT run. Matching Python the shell way would count that documentation as
    wiring and excuse every gate anyone wrote a paragraph about.
    """
    m = _audit_mod()
    runner = (
        '"""Gate runner.\n'
        '\n'
        'This suite deliberately does NOT invoke\n'
        'documented_check.py — see the note in #886 about gates named in\n'
        'prose explaining why they are not wired here.\n'
        '"""\n'
        '# documented_check.py is also mentioned in a comment.\n'
    )
    flow, programs = _tree(
        tmp_path, extra={"documented_check": _DECLARES_BLOCKING},
        runner=runner)
    assert _orphans(m, flow, programs) == ["documented_check"]
    assert m.main(["--flow", str(flow), "--programs", str(programs),
                   "--baseline", str(programs / "nonexistent.json")]) == 1


def test_the_gate_runner_is_not_its_own_proof_of_being_wired(tmp_path):
    """#886 hit this hazard from the other side: widening the population made
    the audit read its own docstring and report ITSELF as an orphan. The mirror
    hazard is a venue that exempts itself. `gatekeeper_review.py` names its own
    path in string literals, so without the self-reference guard it would be
    the one program in the tree that can never be found unreachable."""
    m = _audit_mod()
    runner = (_DECLARES_BLOCKING
              + 'SELF = "vibe-ic/programs/gatekeeper_review.py"\n')
    flow, programs = _tree(tmp_path, extra={}, runner=runner)
    assert _orphans(m, flow, programs) == ["gatekeeper_review"]


# ------------------------------------------------------------ (b) the fix
# The venue is real, and it is matched the way `_invoked` matches a runner.

def test_a_gate_the_runner_actually_invokes_is_not_orphaned(tmp_path):
    """The shape `repo_hygiene_parallel` is in: named by the repo-gate suite's
    PYTHON entry point in a string literal it then executes."""
    m = _audit_mod()
    runner = (
        '"""Gate runner."""\n'
        '_HYGIENE_PARALLEL_REL = (\n'
        '    "vibe-ic-marketplace/plugins/vibe-ic/programs/wired_parallel.py")\n'
        'def gate(repo):\n'
        '    return subprocess.run([sys.executable,\n'
        '                           str(repo / _HYGIENE_PARALLEL_REL)])\n'
    )
    flow, programs = _tree(
        tmp_path, extra={"wired_parallel": _DECLARES_BLOCKING}, runner=runner)
    assert _orphans(m, flow, programs) == []


def test_venue_three_is_reported_absent_rather_than_assumed_clean(tmp_path):
    """An unreachability claim is only as strong as the list of places it
    looked, so the report names them — and a venue that is NOT PRESENT on the
    tree under audit says so. `not present` and `read, did not name it` are
    different facts and folding them together is how a scan starts certifying
    what it never opened."""
    m = _audit_mod()
    flow, programs = _tree(tmp_path, extra={"lonely_check": _DECLARES_BLOCKING})
    venues = {v["venue"]: v["present"]
              for v in m.audit(flow, programs)["orphan_venues"]}
    assert venues["tools/ci/*.sh"] is False
    assert venues["gatekeeper_review.py"] is False
    assert venues["flow definition"] is True

    flow2, programs2 = _tree(
        tmp_path / "b", extra={"lonely_check": _DECLARES_BLOCKING},
        runner='"""r"""\nX = "other.py"\n', ci="echo hi\n")
    venues2 = {v["venue"]: v["present"]
               for v in m.audit(flow2, programs2)["orphan_venues"]}
    assert venues2["tools/ci/*.sh"] is True
    assert venues2["gatekeeper_review.py"] is True


# --------------------------------------------------- (c) on the SHIPPED tree
# The synthetic cases above prove the rule; these prove it lands on the real
# program the incident was about.

def test_the_shipped_hygiene_coordinator_declares_blocking_and_is_wired():
    """Every clause of the claim, read off the shipped files rather than
    asserted: it DECLARES blocking, the flow definition does not mention it,
    no `tools/ci/*.sh` mentions it — and `gatekeeper_review.py` runs it."""
    m = _audit_mod()
    assert m.declared_intent(_PROGRAMS, "repo_hygiene_parallel") == "blocking"
    src_ci = m.repo_gate_source(_PROGRAMS)
    assert src_ci.strip(), "venue 2 must be present on the shipped tree"
    assert not m._invoked_by_suite(src_ci, "repo_hygiene_parallel")
    src_runner = m.repo_gate_runner_source(_PROGRAMS)
    assert src_runner.strip(), "venue 3 must be present on the shipped tree"
    assert m._invoked(src_runner, "repo_hygiene_parallel")


def test_the_shipped_audit_no_longer_calls_the_coordinator_unreachable():
    """The regression itself, end to end on the shipped tree."""
    cp = subprocess.run(
        [sys.executable, str(_PROGRAMS / "flow_gate_enforcement_audit.py")],
        cwd=str(_PLUGIN), capture_output=True, text=True)
    assert "orphan::repo_hygiene_parallel" not in cp.stdout, cp.stdout
    assert "repo_hygiene_parallel" not in cp.stdout, cp.stdout
    assert cp.returncode == 0, cp.stdout + cp.stderr


def test_the_shipped_audit_still_fails_on_a_defect_planted_in_it(tmp_path):
    """THE LOAD-BEARING CASE. A gate that only ever passes has been shown
    nothing. This plants a real orphan into a COPY of the shipped programs
    directory — every real venue present and populated — and requires the
    shipped audit to fail rc 1 on it.

    A copy, not the tree itself: a test that writes into `programs/` and dies
    leaves a planted defect behind for the next reader to debug.
    """
    m = _audit_mod()
    flow = _PLUGIN / "flow" / "phase1_phase2_phase3.yaml"
    assert flow.is_file(), flow
    # Symlink the shipped programs so the audit sees the real declarations,
    # the real runners and the real gatekeeper_review, then add ONE file.
    shadow = tmp_path / "programs"
    shadow.mkdir()
    for p in _PROGRAMS.iterdir():
        (shadow / p.name).symlink_to(p)
    planted = shadow / "planted_orphan_check.py"
    planted.write_text(_DECLARES_BLOCKING)

    rep = m.audit(flow, shadow)
    assert "planted_orphan_check" in [o["gate"] for o in rep["orphaned"]], rep
    assert m.main(["--flow", str(flow), "--programs", str(shadow),
                   "--baseline",
                   str(_PROGRAMS / "flow_gate_enforcement_baseline.json")]) == 1
