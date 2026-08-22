"""The three checkers nothing but their own test ran now have a MACHINE runner.

REPRODUCED ON 221689eb (pristine origin/main), with the gate's own command:

    checker_execution_wiring_audit: 580 checker-shaped program(s) of 1128
    [FAIL] 3 checker(s) that NOTHING but their own test runs — a fixture the
    author wrote proves the logic, never the artefacts:
       blocker_classification_check.py
       container_login_banner_parse_check.py
       control_substance_check.py
    EXIT=1

`machine_runners` is the assertion and not `test_only`, deliberately: the audit
counts a SKILL document as a runner (an agent following it does execute the
program) and says in its own docstring that this is the weakest form there is.
Adding a line to a skill would empty `test_only` and satisfy nothing. CI / the
flow / another program / a repo tool are the runners that fire without an agent
choosing to, and those are what this pins.

Everything here is read out of the audit's own `--json` record and the hygiene
script's own `--summary-json`, so nothing depends on how the wiring is spelt.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
_PLUGIN = _PROGRAMS.parent
_REPO = _PLUGIN.parents[2]
_AUDIT = _PROGRAMS / "checker_execution_wiring_audit.py"
_HYGIENE = _REPO / "tools" / "ci" / "repo_hygiene_gates.sh"

#: Bound for every blocking call below. NOT a round number:
#: `ci_harness_timeout_ceiling_check` (BLOCKING, wired in
#: tools/ci/repo_hygiene_gates.sh) resolves the harness bound from
#: tools/gatekeeper-land.sh:197 — `pytest -q --maxfail=10 --timeout=180
#: --timeout-method=thread` — and permits any ONE blocking call at most
#: 180 // 3 = 60 s. A larger inner bound can never fire: pytest reaches 180 s
#: first and takes the whole SESSION down, so every other file in the subset
#: loses its verdict too. The landed values were 600/600/300.
#: MEASURED on this tree, `pytest --durations=0` over this file:
#:   audit_report fixture (line ~47)      13.89 s
#:   the second audit run (line ~70)      13.74 s
#:   `--list` over the hygiene script      0.04 s
#: Worst case 13.89 s against 60 s is 4.3x headroom, and the bound is now a
#: hang detector that can actually fire.
_CEILING_S = 60

_ORPHANED = ("blocker_classification_check.py",
             "container_login_banner_parse_check.py",
             "control_substance_check.py")


@pytest.fixture(scope="module")
def audit_report(tmp_path_factory):
    out = tmp_path_factory.mktemp("wiring") / "audit.json"
    subprocess.run([sys.executable, str(_AUDIT), "--json", str(out)],
                   capture_output=True, text=True, timeout=_CEILING_S)
    return json.loads(out.read_text())


@pytest.mark.parametrize("checker", _ORPHANED)
def test_it_has_a_runner_that_is_not_an_agent_reading_a_document(
        checker, audit_report):
    runners = audit_report["machine_runners"].get(checker)
    assert runners is not None, f"{checker} left the audit's population"
    assert runners, (
        f"{checker} has no CI / FLOW / PROG / TOOLS runner — only its own unit "
        f"test, or a skill an agent may or may not follow, can reach it")


@pytest.mark.parametrize("checker", _ORPHANED)
def test_it_is_no_longer_in_the_test_only_finding(checker, audit_report):
    assert checker not in audit_report["test_only"]
    assert checker not in audit_report["no_runner_at_all"]


def test_the_audit_returns_a_clean_verdict(audit_report, tmp_path):
    """The gate itself, by exit code — not by re-deriving its rule here."""
    r = subprocess.run([sys.executable, str(_AUDIT)],
                       capture_output=True, text=True, timeout=_CEILING_S)
    assert r.returncode == 0, r.stdout + r.stderr


@pytest.mark.skipif(not _HYGIENE.is_file(), reason="hygiene script absent")
def test_the_two_tree_scoped_checkers_are_declared_gates(tmp_path):
    """`--list` declares without executing, and the record names every gate.

    Read from the dispatcher's own emitted summary rather than from the script
    text, because the record is what `gatekeeper_review` consumes to decide
    what it consulted.
    """
    summary = tmp_path / "summary.json"
    subprocess.run(["bash", str(_HYGIENE), "--list",
                    "--summary-json", str(summary)],
                   capture_output=True, text=True, timeout=_CEILING_S)
    doc = json.loads(summary.read_text())
    labels = {g["label"] for g in doc["gates"]}
    assert "container login-banner parses" in labels
    assert "blocker list contract on committed reports" in labels
    assert doc["declared"] == len(doc["gates"])
