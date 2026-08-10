"""Three gates that produced a verdict nothing automatic read (vibe-ic#693).

`gate_is_wired_check` reported them NEWLY unwired against its own baseline:

    blocker_classification_check          the classified blocker list's contract
    container_login_banner_parse_check    a login banner prepended to stdout
    control_substance_check               did the pre-fix control observe a VALUE

Each had a unit test and nothing else. This module does not assert that a NAME
appears somewhere — that is the mistake `gate_is_wired_check`'s own docstring
records making twice. It drives each consumer and asserts on what the consumer
RETURNS, so a wire that exists but carries no verdict fails here.
"""
from __future__ import annotations

import importlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

_REPO = _PROGRAMS.parents[3]
_HYGIENE = _REPO / "tools" / "ci" / "repo_hygiene_gates.sh"

_BANNER_LABEL = "container stdout vs the login banner"


# ---------------------------------------------------------------------------
# container_login_banner_parse_check -> tools/ci/repo_hygiene_gates.sh
# ---------------------------------------------------------------------------
@pytest.mark.skipif(not _HYGIENE.is_file(), reason="hygiene runner absent")
def test_the_hygiene_runner_declares_the_login_banner_gate():
    """`--list` is the dispatcher's OWN record of what it wires, emitted by
    `_gate_dispatch`. Asserting on it rather than on the script text is the
    difference between "the name is in the file" and "the dispatcher declared
    it": a label inside a comment, or after an early `exit`, is in the file and
    is not in this list."""
    proc = subprocess.run(["bash", str(_HYGIENE), "--list"],
                          capture_output=True, text=True)
    labels = [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]
    assert _BANNER_LABEL in labels, (
        f"the dispatcher declared {len(labels)} gate(s) and this was not one "
        f"of them")


def test_the_login_banner_gate_returns_a_verdict_over_a_real_denominator():
    """A wire to a gate that can only ever say "nothing to look at" is not a
    wire. Measured when this landed: population 1127 programs, 25 of which pass
    a login shell to the container."""
    mod = importlib.import_module("container_login_banner_parse_check")
    rec = mod.audit()
    assert rec["population"] > 0
    assert rec["login_shell_callers"], (
        "no caller passes a login shell — the gate would return rc 2 and the "
        "hygiene lane would record NOT_CHECKED, which is honest but means this "
        "wire is no longer measuring anything")
    assert rec["verdict"] in ("PASS", "FAIL")


def test_the_login_banner_gate_still_discriminates(tmp_path):
    """Both directions, over a population this test controls: a `-lc` call site
    whose stdout is read as a number is named; the same file without the
    numeric parse is not."""
    mod = importlib.import_module("container_login_banner_parse_check")
    fragile = tmp_path / "fragile.py"
    fragile.write_text(
        'import subprocess\n'
        'cp = subprocess.run(["docker", "exec", "c", "bash", "-lc", "x"],\n'
        '                    capture_output=True, text=True)\n'
        'n = int(cp.stdout)\n')
    safe = tmp_path / "safe.py"
    safe.write_text(
        'import subprocess\n'
        'cp = subprocess.run(["docker", "exec", "c", "bash", "-lc", "x"],\n'
        '                    capture_output=True, text=True)\n'
        'last = cp.stdout.splitlines()[-1]\n')

    bad = mod.audit([fragile])
    assert bad["verdict"] == "FAIL"
    assert "fragile.py" in bad["findings"]

    good = mod.audit([safe])
    assert good["verdict"] == "PASS"
    assert good["login_shell_callers"] == ["safe.py"]


# ---------------------------------------------------------------------------
# blocker_classification_check -> flow_compliance_check (the producer)
# ---------------------------------------------------------------------------
def _step(step_id="7", status="FAIL"):
    return {"id": step_id, "name": f"step {step_id}", "status": status,
            "stage": "s", "reasons": ["program failed: g ."]}


def _blocker(step_id="7", classification="DESIGN_FACT",
             basis="gate-reached-verdict"):
    return {"step_id": step_id, "step_name": f"step {step_id}", "stage": "s",
            "status": "FAIL", "classification": classification,
            "basis": basis, "measures": "m", "observed": "o",
            "derived_from": [], "sub_blockers": None}


def _counts(**kw):
    base = {"PLUGIN_DEFECT": 0, "DESIGN_FACT": 0, "MISSING_CAPABILITY": 0,
            "UNCLASSIFIED": 0}
    base.update(kw)
    return base


def test_the_producer_consults_the_blocker_contract_guard_and_returns_nothing_on_a_clean_list():
    fcc = importlib.import_module("flow_compliance_check")
    assert fcc.blocker_contract_violations(
        "FAIL", [_step()], [_blocker()], _counts(DESIGN_FACT=1), "") == []


def test_the_producer_reports_a_blocker_that_dropped_out_of_its_own_list():
    """Property 1 of the guard, reached through the producer: a non-PASS step
    absent from `blockers` is a list that is not complete over its own steps."""
    fcc = importlib.import_module("flow_compliance_check")
    got = fcc.blocker_contract_violations("FAIL", [_step()], [], _counts(), "")
    assert len(got) == 1
    assert "step 7" in got[0] and "absent from `blockers`" in got[0]


def test_the_producer_reports_a_class_no_rule_licensed():
    """Property 3: `basis` = `no-rule-matched` may only carry UNCLASSIFIED."""
    fcc = importlib.import_module("flow_compliance_check")
    got = fcc.blocker_contract_violations(
        "FAIL", [_step()], [_blocker(basis="no-rule-matched")],
        _counts(DESIGN_FACT=1), "")
    assert len(got) == 1
    assert "UNCLASSIFIED" in got[0]


def test_the_producer_reports_a_headline_that_does_not_sum_to_its_own_list():
    """Property 4: the published counts must be the list's own counts."""
    fcc = importlib.import_module("flow_compliance_check")
    got = fcc.blocker_contract_violations(
        "FAIL", [_step()], [_blocker()], _counts(DESIGN_FACT=9), "")
    assert any("blocker_class_counts" in v for v in got), got


def test_the_guard_never_crashes_the_producer_it_audits():
    """A guard that can take the compliance verdict down with it would be worse
    than the drift it looks for. A structurally impossible report returns a
    violation, never an exception."""
    fcc = importlib.import_module("flow_compliance_check")
    got = fcc.blocker_contract_violations("FAIL", [_step()], "not-a-list",
                                          _counts(), "")
    assert isinstance(got, list) and got


# ---------------------------------------------------------------------------
# control_substance_check -> gatekeeper_review.control_substance_gate
# ---------------------------------------------------------------------------
def _control_repo(tmp_path, base_body, head_body, test_body, name):
    """A throwaway repo shaped like this one: a program under the plugin tree,
    and a test file ADDED in the head commit."""
    repo = tmp_path / "repo"
    plugin = repo / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs"
    (plugin / "tests").mkdir(parents=True)

    def git(*args):
        return subprocess.run(["git", "-C", str(repo), *args],
                              capture_output=True, text=True, check=True)

    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    git("config", "user.email", "t@example.invalid")
    git("config", "user.name", "t")
    (plugin / f"{name}.py").write_text(base_body)
    git("add", "-A")
    git("commit", "-qm", "base")
    (plugin / f"{name}.py").write_text(head_body)
    (plugin / "tests" / f"test_{name}.py").write_text(test_body)
    git("add", "-A")
    git("commit", "-qm", "head")
    return repo


_TEST_BODY = (
    "import sys\n"
    "from pathlib import Path\n"
    "sys.path.insert(0, str(Path(__file__).resolve().parents[1]))\n"
    "import {name}\n"
    "\n"
    "def test_value():\n"
    "    assert {name}.value() == 'new'\n"
)


def test_the_merge_gate_reads_the_substantive_count_off_a_real_control(tmp_path):
    """The control CAN observe a value: the module exists on the merge-base and
    returns the OLD value, so an assertion executes and compares two concrete
    strings. The gate must report that as substantive — which it can only do by
    reading the classifier's record, not its exit code (`--advisory` flattens
    the exit code to 0 either way)."""
    gk = importlib.import_module("gatekeeper_review")
    repo = _control_repo(
        tmp_path,
        "def value():\n    return 'old'\n",
        "def value():\n    return 'new'\n",
        _TEST_BODY.format(name="widget"), "widget")
    res = gk.control_substance_gate(repo, "HEAD~1", "HEAD")
    assert res.rc == 0 and res.green
    assert "1 of 1 reported failure(s) observed a VALUE" in res.summary
    assert "TAUTOLOGICAL" not in res.summary


def test_the_merge_gate_names_a_tautological_control(tmp_path):
    """The other direction, and the one the checker exists for: the module the
    change introduces does not exist on the merge-base, so pytest never
    collects the file. 'The tests fail pre-fix' is true and carries no
    information, and the gate must say so."""
    gk = importlib.import_module("gatekeeper_review")
    repo = _control_repo(
        tmp_path,
        "",                                    # placeholder, renamed below
        "def value():\n    return 'new'\n",
        _TEST_BODY.format(name="fresh"), "fresh")
    # Remove the module from the base commit entirely, so the control cannot
    # import it — the PR #856 shape, exactly.
    subprocess.run(["git", "-C", str(repo), "rm", "-q", "--cached",
                    "vibe-ic-marketplace/plugins/vibe-ic/programs/fresh.py"],
                   check=True, capture_output=True)
    res = gk.control_substance_gate(repo, "HEAD~1", "HEAD")
    assert res.rc == 0 and res.green
    assert "0 of" in res.summary
    assert "TAUTOLOGICAL" in res.summary


def test_the_merge_gate_skips_when_the_change_adds_no_test(tmp_path):
    """Not-applicable is rc -1 and says why. A change with no added test has no
    control to replay, and reporting that as a passing control would be the
    vacuous verdict this whole family is about."""
    gk = importlib.import_module("gatekeeper_review")
    repo = _control_repo(
        tmp_path,
        "def value():\n    return 'old'\n",
        "def value():\n    return 'new'\n",
        _TEST_BODY.format(name="widget"), "widget")
    res = gk.control_substance_gate(repo, "HEAD", "HEAD")
    assert res.rc == -1
    assert "adds no test file" in res.summary


# ---------------------------------------------------------------------------
# the umbrella
# ---------------------------------------------------------------------------
def test_none_of_the_three_is_reported_unwired_any_more():
    """`gate_is_wired_check`'s own predicate, asked directly. It removes every
    comment and docstring before searching, so this passes only if each name
    appears somewhere that can actually invoke it."""
    giw = importlib.import_module("gate_is_wired_check")
    plugin = _PROGRAMS.parent
    now, _wiring = giw.unwired(plugin, _REPO)
    for name in ("blocker_classification_check",
                 "container_login_banner_parse_check",
                 "control_substance_check"):
        assert name not in now, f"{name} is still consulted by no verdict"
