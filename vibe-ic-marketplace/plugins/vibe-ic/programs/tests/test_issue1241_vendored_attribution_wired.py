"""`vendored_attribution_retained_check` had no runner but its own test. #1241.

REPRODUCED on this PR's head before the wiring, with the gate's own command:

    checker_execution_wiring_audit --repo-root <tree>
    [FAIL] 1 checker(s) that NOTHING but their own test runs — a fixture the
    author wrote proves the logic, never the artefacts:
       vendored_attribution_retained_check.py

A checker exercised only by a fixture its own author wrote is verified against
the author's MODEL of the artefacts, never against the artefacts. It can be
perfectly correct about a world that does not exist — and it is invisible while
being so, because it appears in "N checkers" and contributes a green square.

THE ASSERTION IS `machine_runners`, NOT `test_only`, on purpose. The audit
counts a SKILL document as a runner — an agent following it does execute the
program — and says in its own docstring that this is the weakest form there is.
Asserting only "not in test_only" would be satisfied by adding a skill mention.

WHAT WAS MEASURED BEFORE WIRING, so CI does not learn about a finding by
turning red:

    vendored_attribution_retained_check: 17217 tracked file(s) under
    benchmark-data, 525 declaring an SPDX licence, 11 attribution record(s)
    [PASS] every one of the 525 licence-declaring file(s) is covered
    rc=0

chip-AGNOSTIC: it reasons about the gate wiring, not about any design.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parent.parent
_PLUGIN = _PROGRAMS.parent
_REPO = _PLUGIN.parents[2]
_AUDIT = _PROGRAMS / "checker_execution_wiring_audit.py"
_HYGIENE = _REPO / "tools" / "ci" / "repo_hygiene_gates.sh"

_CHECKER = "vendored_attribution_retained_check.py"

#: vibe-ic#1241's own rule: an inner bound must be under harness_bound/3 = 60s,
#: derived in `test_three_orphan_checkers_have_a_machine_runner` from
#: tools/gatekeeper-land.sh:197 (`pytest ... --timeout=180`). The rule gives 60;
#: this file additionally halved it to 30 for no recorded reason, and 30 is
#: BELOW what the call it bounds actually costs.
#:
#: MEASURED on this tree, `checker_execution_wiring_audit.py --json`, three runs
#: on an idle 32-core host at load 3-6:  28.1 s / 27.8 s / 25.9 s.  The audit's
#: own report says why it grew -- it sweeps 4593 files and the population it
#: reports is now `656 checker-shaped program(s) of 1298`, against the `580 of
#: 1128` the sibling module's note was measured at.
#:
#: A bound of 30 s over a 26-28 s call is not a hang detector; it is a coin
#: flip, and it fires on healthy work. It cost 3 red cases in this file on the
#: full-suite sweep of ae5cc4dbfc -- two of them SETUP errors, so the tests they
#: gate never ran at all. 60 s restores the rule's own value, keeps 2.1x headroom
#: over the slowest measured run, and still fires long before pytest's 180 s
#: takes the whole session down.
_CEILING_S = 60


@pytest.fixture(scope="module")
def audit_report(tmp_path_factory):
    out = tmp_path_factory.mktemp("wiring1241") / "audit.json"
    subprocess.run([sys.executable, str(_AUDIT), "--json", str(out)],
                   capture_output=True, text=True, timeout=_CEILING_S)
    return json.loads(out.read_text())


def test_it_has_a_runner_that_is_not_an_agent_reading_a_document(audit_report):
    runners = audit_report["machine_runners"].get(_CHECKER)
    assert runners is not None, f"{_CHECKER} left the audit's population"
    assert runners, (
        f"{_CHECKER} has no CI / FLOW / PROG / TOOLS runner — only its own "
        f"unit test, or a skill an agent may or may not follow, can reach it")


def test_it_is_no_longer_in_the_test_only_finding(audit_report):
    assert _CHECKER not in audit_report["test_only"]
    assert _CHECKER not in audit_report["no_runner_at_all"]


@pytest.mark.skipif(not _HYGIENE.is_file(), reason="hygiene script absent")
def test_the_hygiene_script_declares_it_as_a_blocking_gate():
    """Declared with `run`, not `run_tolerating_uncheckable`.

    The two differ in exactly the way this issue is about: the tolerating form
    treats rc 2 as non-fatal. This gate answers rc 0 or rc 1 — it has no
    "could not check" state — so declaring it tolerantly would buy nothing and
    would quietly widen what counts as a pass.
    """
    text = _HYGIENE.read_text(encoding="utf-8")
    assert _CHECKER in text, (
        f"{_CHECKER} is not declared in {_HYGIENE.name} at all")
    line = [ln for ln in text.splitlines() if _CHECKER in ln and "run" in ln]
    assert line, f"{_CHECKER} appears but not on a `run` line"
    assert any(ln.lstrip().startswith("run ") for ln in line), (
        f"{_CHECKER} is declared, but not with the blocking `run` form: {line}")


def test_the_audit_returns_a_clean_verdict():
    """The gate itself, by exit code — not by re-deriving its rule here."""
    r = subprocess.run([sys.executable, str(_AUDIT)],
                       capture_output=True, text=True, timeout=_CEILING_S)
    assert r.returncode == 0, r.stdout + r.stderr
