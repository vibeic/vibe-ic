#!/usr/bin/env python3
"""vibe-ic#1347 — `checker_execution_wiring_audit` counted a NAME as a runner.

The audit decides whether a checker "has a runner" by asking whether its stem
appears as a token in a haystack file. `_strip_prose` drops comments and
docstrings and KEEPS ordinary string literals, deliberately, because
`subprocess.run([..., "foo_check.py"])` is a real invocation. A checker's own
error message naming a sibling is the same kind of literal, so a SENTENCE
promoted that sibling to "wired" — and appending

    _UNUSED_NAME = "some_check"

to any non-test program was enough to flip that checker's verdict in the
instrument other landings depend on.

Every case here is BIDIRECTIONAL by construction: the tree that must produce a
finding is paired with the same tree made genuinely wired, because either
assertion on its own proves only that the audit is stuck in one answer.

The three rules that were measured and DISCARDED before this one are recorded
in `checker_execution_wiring_audit`'s own block comment; the two that matter
for these tests are pinned as tests rather than prose:

  * a rule requiring a literal `<stem>.py` accuses ~200 wired gates, because
    `flow_compliance_check` holds gate names BARE and builds
    `PROGRAMS_DIR / f"{gate_name}.py"` — `test_a_registry_a_dispatcher_*`;
  * a rule tested against `_strip_prose`'s output can never match
    `import_module("<stem>")`, because for a `.py` source that function returns
    tokenize output, ONE TOKEN PER LINE — `test_a_dynamic_import_by_name_*`.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / "checker_execution_wiring_audit.py"
sys.path.insert(0, str(PROG.parent))
import checker_execution_wiring_audit as M  # noqa: E402


def _tree(root: Path, *, ci="", flow="", skill="", prog="", test="", tools=""):
    """A minimal repo whose only checker is `sample_check.py`.

    `test` always names the checker, so the tree's verdict turns entirely on
    whether the NON-test reference under examination counts as a runner.
    """
    plugin = root / "vibe-ic-marketplace" / "plugins" / "vibe-ic"
    for d in ("programs/tests", "flow", "skills", "agents", "commands", "tests"):
        (plugin / d).mkdir(parents=True, exist_ok=True)
    (root / ".github" / "workflows").mkdir(parents=True, exist_ok=True)
    (root / "tools").mkdir(parents=True, exist_ok=True)
    (plugin / "programs" / "sample_check.py").write_text("def main():\n    return 0\n")
    (root / ".github" / "workflows" / "ci.yml").write_text(ci or "name: CI\n")
    (plugin / "flow" / "flow.yaml").write_text(flow or "steps: []\n")
    (plugin / "skills" / "s.md").write_text(skill or "# skill\n")
    (plugin / "programs" / "other.py").write_text(prog or "x = 1\n")
    (root / "tools" / "runner.sh").write_text(tools or "echo hi\n")
    (plugin / "programs" / "tests" / "test_sample.py").write_text(
        test or "import sample_check\n")
    return plugin


def _wired(root: Path) -> bool:
    """Did the audit find a runner other than the checker's own test?"""
    rep = M.audit(root / "vibe-ic-marketplace" / "plugins" / "vibe-ic", root)
    return "sample_check.py" not in rep["test_only"] + rep["no_runner_at_all"]


# ---------------------------------------------------------------------------
# The defect itself: a sentence in another program's message text.
# ---------------------------------------------------------------------------
def test_a_sibling_message_naming_the_checker_is_not_a_runner(tmp_path):
    _tree(tmp_path, prog=(
        'def fail():\n'
        '    return ("this gate does not judge presence; "\n'
        '            "sample_check owns that")\n'))
    assert not _wired(tmp_path), (
        "a checker named inside another program's MESSAGE was counted as run "
        "by it — the #1347 defect")


def test_the_same_program_actually_invoking_it_is_a_runner(tmp_path):
    """The paired half. Same file, same name, now in an invocation shape."""
    _tree(tmp_path, prog=(
        'import subprocess, sys\n'
        'def run(root):\n'
        '    return subprocess.run([sys.executable,\n'
        '                           str(root / "sample_check.py")])\n'))
    assert _wired(tmp_path)


# ---------------------------------------------------------------------------
# The issue's two controls: binding the name to something nothing reads.
# ---------------------------------------------------------------------------
def test_binding_the_name_to_an_unused_variable_is_not_a_runner(tmp_path):
    _tree(tmp_path, prog='_UNUSED_NAME = "sample_check"\n')
    assert not _wired(tmp_path), (
        "a #1241 row could close by assigning the checker's name to a "
        "variable nothing reads")


def test_a_dict_key_in_a_program_that_dispatches_nothing_is_not_a_runner(tmp_path):
    """The second control — the shape of a waiver / skip-path register.

    `gate_skip_routing_check` keys its unrouted-skip inventory by gate name;
    that register describes gates, it does not run them.
    """
    _tree(tmp_path, prog='INVENTORY = {"sample_check": 1}\n')
    assert not _wired(tmp_path)


# ---------------------------------------------------------------------------
# The rule that a literal-`.py` predicate got wrong: a registry a dispatcher
# executes IS an execution path.
# ---------------------------------------------------------------------------
def test_a_registry_a_dispatcher_executes_is_a_runner(tmp_path):
    _tree(tmp_path, prog=(
        'import subprocess, sys\n'
        'from pathlib import Path\n'
        'GATES = ("sample_check",)\n'
        'def run(programs):\n'
        '    for g in GATES:\n'
        '        subprocess.run([sys.executable,\n'
        '                        str(Path(programs) / f"{g}.py")])\n'))
    assert _wired(tmp_path), (
        "a bare name in a registry whose file builds `f\"{name}.py\"` and runs "
        "it must stay wired — that is ~500 per-design gates in "
        "flow_compliance_check")


def test_the_same_registry_with_no_dispatch_is_not_a_runner(tmp_path):
    """The paired half. Identical registry, nothing that builds a filename."""
    _tree(tmp_path, prog='GATES = ("sample_check",)\n')
    assert not _wired(tmp_path)


# ---------------------------------------------------------------------------
# The rule that a `_strip_prose`-based predicate could never satisfy.
# ---------------------------------------------------------------------------
def test_a_dynamic_import_by_name_is_a_runner(tmp_path):
    _tree(tmp_path, prog=(
        'from importlib import import_module\n'
        'def load():\n'
        '    return import_module("sample_check")\n'))
    assert _wired(tmp_path), (
        "`import_module(\"sample_check\")` is an invocation; a predicate run "
        "against tokenize output (one token per line) can never see it")


def test_a_plain_import_is_a_runner(tmp_path):
    _tree(tmp_path, prog="import sample_check\n")
    assert _wired(tmp_path)


def test_a_step_named_after_the_checker_is_not_a_runner(tmp_path):
    """`design_one_shot_runner` holds `StepResult("otp_image_check", ...)` and
    runs `otp_image_nonzero_check.py`. The STEP wears the name; the PROGRAM is
    a different file, and nothing invokes it.
    """
    _tree(tmp_path, prog=(
        'import subprocess, sys\n'
        'def step(root):\n'
        '    subprocess.run([sys.executable, str(root / "sample_check_extra.py")])\n'
        '    return ("sample_check", "PASS")\n'))
    assert not _wired(tmp_path)


# ---------------------------------------------------------------------------
# The kinds where a bare name still IS a reference. Tightening these would be a
# different decision; these two pin that it was not taken by accident.
# ---------------------------------------------------------------------------
def test_a_bare_flow_reference_still_counts(tmp_path):
    """REGRESSION on the METHOD NOTE: the flow definition writes names BARE."""
    _tree(tmp_path, flow="steps:\n  - gate: sample_check\n")
    assert _wired(tmp_path)


def test_a_bare_skill_reference_still_counts(tmp_path):
    """#693 counts a skill document deliberately: an agent follows it and runs
    the program. That decision is unchanged here."""
    _tree(tmp_path, skill="# skill\n\nRun sample_check on the project.\n")
    assert _wired(tmp_path)


# ---------------------------------------------------------------------------
# TOOLS is program source too.
# ---------------------------------------------------------------------------
def test_a_shell_message_naming_the_checker_is_not_a_runner(tmp_path):
    _tree(tmp_path, tools='echo "sample_check should have caught this"\n')
    assert not _wired(tmp_path)


def test_a_shell_invocation_is_a_runner(tmp_path):
    _tree(tmp_path, tools='python3 "$PG/sample_check.py" "$ROOT"\n')
    assert _wired(tmp_path)


# ---------------------------------------------------------------------------
# Backward compatibility of the predicate's public entry point.
# ---------------------------------------------------------------------------
def test_runners_without_an_index_is_bare_token_membership(tmp_path):
    """`runners(..., invocations=None)` must behave exactly as before #1347, so
    any caller that has not been taught about the index is not silently
    switched onto a stricter rule."""
    plugin = _tree(tmp_path, prog='_UNUSED_NAME = "sample_check"\n')
    hay = M._tokenise(M._haystacks(plugin, tmp_path))
    self_path = str(plugin / "programs" / "sample_check.py")
    assert "PROG" in M.runners("sample_check", hay, self_path)
    idx = M.invocation_index(plugin, tmp_path)
    assert "PROG" not in M.runners("sample_check", hay, self_path, idx)


# ---------------------------------------------------------------------------
# The disclosure the tightening produced, pinned so deleting it is loud.
# ---------------------------------------------------------------------------
_FOUND_BY_1347 = ("agent_report_presence_check.py",
                  "eda_log_check.py",
                  "sv_compat_check.py")


def test_the_three_it_found_are_recorded_with_a_measured_triage():
    """They were never wired; the instrument reported them as wired. `known`
    may only SHRINK, so recording them is a debt that has to be paid by wiring
    them — see each entry's triage for what that needs."""
    bl = json.loads((PROG.parent / "checker_execution_wiring_baseline.json")
                    .read_text(encoding="utf-8"))
    for name in _FOUND_BY_1347:
        assert name in bl["known"], f"{name} left the register without a repair"
        reason = bl["triage"].get(name, "")
        assert len(reason) >= 120 and "1347" in reason, (
            f"{name}'s entry must carry the measurement that put it there")


# ---------------------------------------------------------------------------
# The register the tightening had to WRITE, and what that write erased.
# ---------------------------------------------------------------------------
def test_write_baseline_keeps_the_hand_written_comment(tmp_path):
    """`_comment` carries the REMOVAL LOG — the only record of why an entry
    left a register that may only SHRINK.

    Recording the three findings meant running `--write-baseline`, and that
    path regenerated `_comment` from a constant, deleting the log with no
    message. It is the same defect the code already guards against for
    `unwired_by_decision` ("a separate claim ... a --write-baseline must not
    silently drop it"), on the one field that had been left out.
    """
    plugin = _tree(tmp_path, prog='_UNUSED_NAME = "sample_check"\n')
    bl = tmp_path / "baseline.json"
    kept = ("Checkers nothing but their own test runs. REMOVAL LOG: "
            "some_check.py removed at v9.9.9 because the flow wired it.")
    bl.write_text(json.dumps({"_comment": kept,
                              "known": ["sample_check.py"],
                              "triage": {},
                              "unwired_by_decision": {}}))
    rc = M.main(["--repo-root", str(tmp_path), "--baseline", str(bl),
                 "--write-baseline"])
    assert rc == 0
    after = json.loads(bl.read_text())
    assert after["_comment"] == kept, (
        "the rewrite regenerated `_comment` and took the REMOVAL LOG with it")
    assert after["known"] == ["sample_check.py"]
