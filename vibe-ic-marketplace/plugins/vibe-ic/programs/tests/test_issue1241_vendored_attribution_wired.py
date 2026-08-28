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
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

_PROGRAMS = Path(__file__).resolve().parent.parent
_PLUGIN = _PROGRAMS.parent
_REPO = _PLUGIN.parents[2]
_AUDIT = _PROGRAMS / "checker_execution_wiring_audit.py"
_HYGIENE = _REPO / "tools" / "ci" / "repo_hygiene_gates.sh"

_CHECKER = "vendored_attribution_retained_check.py"

@pytest.fixture(scope="module")
def audit_report(tmp_path_factory):
    out = tmp_path_factory.mktemp("wiring1241") / "audit.json"
    _pr.run([sys.executable, str(_AUDIT), "--json", str(out)],
                   capture_output=True, text=True)
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


# THE GLOBAL ASSERTION THAT USED TO SIT HERE IS GONE, and this note is why.
#
# It was `test_the_audit_returns_a_clean_verdict`: run
# `checker_execution_wiring_audit` with no arguments and require rc 0. This
# file is about ONE checker, and that assertion is about EVERY checker in the
# tree, so this file went red whenever anybody anywhere added an unwired one —
# naming programs that have nothing to do with its subject. Measured
# 2026-08-28: four such checkers reddened this file and
# `test_three_orphan_checkers_have_a_machine_runner.py`, and the four were
# `attestation_preflight_check`, `generated_test_list_min_guard`,
# `landing_noop_verdict_check` and `page_states_one_figure_twice_check` —
# none of them the subject of either file.
#
# IT PROTECTED NOTHING THE GATE DOES NOT. `tools/ci/repo_hygiene_gates.sh:908`
# already runs that audit through the BLOCKING `run` wrapper:
#
#     run "checker execution wiring"  "$ROOT" python3 "$PG/checker_execution_wiring_audit.py"
#
# CHECKED BEFORE CUTTING, because "it is already wired" is exactly the claim
# that is worth being wrong about:
#   * same argv — the gate passes no `--repo-root` and no `--baseline`, and so
#     did the deleted test, so both resolve the same root and read the same
#     baseline over the same population;
#   * always runs — no `gate_scope` narrows it (an unscoped gate is never
#     skipped) and no `uncheckable_until` precedes it, so its rc 1 is fatal;
#   * runs in the landing lane — `tools/gatekeeper-land.sh:1587` invokes that
#     script.
#
# What is KEPT is every assertion this file owns about its own subject,
# including `test_it_is_no_longer_in_the_test_only_finding`, which asks the
# audit the question this file is actually about and stays red if THIS
# checker regresses.

