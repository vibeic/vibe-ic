"""The merge gate grades the PRE-FIX control instead of taking its word.

`control_substance_check` reads the control run's own pytest report and counts
how many reported failures OBSERVED A VALUE, as against merely noticing that
something was absent. It shipped with nothing but its own unit test running it
— the shape it exists to name — so nothing ever handed it a control.

`gatekeeper_review` is the only program in this repo that judges a base..head
CHANGE, so it is where the grading belongs. These tests drive the real gate
function and assert on the GateResult it returns.

The evidence is produced by RUNNING pytest, not by hand-writing XML: the whole
point of the checker is that pytest already distinguishes a collection error
from an executed assertion, and a hand-typed fixture could be tuned to whatever
the classifier happens to do.
"""
from __future__ import annotations

import importlib
import os
import subprocess
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

_GK = importlib.import_module("gatekeeper_review")


#: Bound for the pytest-in-a-subprocess below. Derived from the harness it
#: runs under: `ci_harness_timeout_ceiling_check` reads
#: tools/gatekeeper-land.sh:197 (`--timeout=180 --timeout-method=thread`) and
#: permits one blocking call at most 180 // 3 = 60 s. A 300 s bound cannot
#: fire — pytest kills the SESSION at 180 s, so `--maxfail` stops counting and
#: every other file in the subset silently loses its verdict.
#: MEASURED on this tree with `pytest --durations=0`: the two tests that spend
#: this call cost 0.23 s and 0.19 s END TO END, so 60 s is >250x headroom.
_CEILING_S = 60


def _control_report(tmp_path: Path, name: str, body: str) -> Path:
    """Run pytest over `body` and return its --junitxml, as the control does."""
    d = tmp_path / name
    d.mkdir()
    (d / f"test_{name}.py").write_text(body)
    xml = tmp_path / f"{name}.xml"
    env = dict(os.environ, PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")
    subprocess.run([sys.executable, "-m", "pytest", str(d), "-q",
                    "-p", "no:cacheprovider", f"--junitxml={xml}"],
                   capture_output=True, text=True, timeout=_CEILING_S, env=env,
                   cwd=str(tmp_path))
    assert xml.is_file(), "the control produced no report to grade"
    return xml


#: The PR #856 shape: a new test file importing the module the fix introduces.
#: On clean main it cannot do anything but fail at COLLECTION, which is true of
#: every new file ever written.
_TAUTOLOGICAL = ("import module_the_fix_introduces  # noqa: F401\n"
                 "\n\n"
                 "def test_it():\n"
                 "    assert module_the_fix_introduces.f() == 1\n")

#: A control that executed an assertion over a value and the value was wrong.
_SUBSTANTIVE = ("def _observed():\n"
                "    return 2\n"
                "\n\n"
                "def test_it():\n"
                "    assert _observed() == 3\n")


def test_a_control_that_collected_nothing_BLOCKS(tmp_path):
    xml = _control_report(tmp_path, "taut", _TAUTOLOGICAL)
    g = _GK.control_substance_gate(str(xml), None, [])
    assert g.rc == 1
    assert g.green is False
    assert "TAUTOLOGICAL" in g.summary


def test_a_control_that_observed_a_wrong_value_passes(tmp_path):
    xml = _control_report(tmp_path, "subst", _SUBSTANTIVE)
    g = _GK.control_substance_gate(str(xml), None, [])
    assert g.rc == 0
    assert g.green is True


def test_no_evidence_over_a_diff_that_changes_tests_is_a_LOUD_skip():
    """Non-blocking by policy, never silent.

    Blocking here would refuse every landing from day one over evidence the
    workflow does not yet produce, and a gate that must be bypassed to work is
    a gate that gets bypassed for real reasons too — the reasoning
    `ci_ran_at_all_check` already carries in this same program. What it must
    not do is look like "not applicable".
    """
    files = ["vibe-ic-marketplace/plugins/vibe-ic/programs/tests/test_a.py",
             "vibe-ic-marketplace/plugins/vibe-ic/programs/tests/test_b.py"]
    g = _GK.control_substance_gate(None, None, files)
    assert g.rc == -1
    assert g.green is True
    assert "NO CONTROL EVIDENCE SUPPLIED" in g.summary
    assert "2 test file(s)" in g.summary


def test_no_evidence_over_a_diff_with_no_test_change_is_not_applicable():
    g = _GK.control_substance_gate(None, None, ["README.md"])
    assert g.rc == -1
    assert "not applicable" in g.summary


def test_unreadable_evidence_is_an_ERROR_not_a_pass(tmp_path):
    """"I could not read the control" must not reach a reader as "the control
    was fine" — the vacuous-pass shape, one artefact over."""
    missing = tmp_path / "never-written.xml"
    g = _GK.control_substance_gate(str(missing), None, [])
    assert g.rc == 2
    assert g.green is False


def test_the_gate_is_part_of_the_reviews_roster(tmp_path):
    """It is not enough that the function exists: `review()` must call it.

    Asserted through the verdict's own gate list, which is what the JSON report
    and the printed roster are built from.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@t"],
                   check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "t"],
                   check=True)
    (repo / "README.md").write_text("a\n")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "base"], check=True)
    base = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    (repo / "README.md").write_text("b\n")
    subprocess.run(["git", "-C", str(repo), "commit", "-qam", "head"],
                   check=True)
    head = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()

    empty_script = tmp_path / "noop_hygiene.sh"
    empty_script.write_text("#!/usr/bin/env bash\nexit 0\n")
    v = _GK.review(base, head, repo=repo, plugin_root=_PROGRAMS.parent,
                   hygiene_script=empty_script)
    assert "control_substance_check" in {g.name for g in v.gates}
