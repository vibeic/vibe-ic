#!/usr/bin/env python3
"""vibe-ic#1270 — a SKILL-only disclosure must STATE a measurement, not exist.

`checker_execution_wiring_audit` decided who "carries a written reason" by
MEMBERSHIP alone:

    named = [c for c in so if c in reasons]

so the reason itself was never read. Measured on 2efa6af35, setting a recorded
reason to `""` left the audit byte-identical to the unmutated tree — still
counted in "2 carry a written reason", still printed as "(skill-only, reason
recorded)", still `[PASS]` rc 0. An entry that says nothing is WORSE than no
entry: silence does not misreport itself, a blank claim does.

THREE STATES, and the third is why this is not the bigger change:

    NO entry            -> in neither list, NEVER blocking  (28 of 30 today)
    entry, measurement  -> `disclosed`, reported as before
    entry, gesture      -> `gestured`, and it BLOCKS

`test_silence_is_in_neither_list_and_does_not_block` and its CLI twin are the
pair that stops the cheap repair: making ABSENCE blocking too would satisfy
"a blank reason now fails" while changing a 28-row population, and it fails
here. Every case below is paired with the same tree made clean, because either
assertion alone proves nothing — a gate that cannot pass is as useless as one
that cannot fail.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / "checker_execution_wiring_audit.py"
sys.path.insert(0, str(PROG.parent))
import checker_execution_wiring_audit as M  # noqa: E402

#: A reason long enough to clear `_MIN_DECISION_REASON`, written the way a real
#: entry is: it names what was measured and what would change the answer.
MEASURED = (
    "Measured on the fixture tree: this checker asserts a property over inputs "
    "that only exist once an agent has produced them, so wiring it into CI "
    "would run it against an empty corpus and report a confident clean answer "
    "over nothing. It becomes wireable the moment the corpus is produced by "
    "the flow rather than by an agent."
)

#: Same helper bound as the sibling suite: the harness runs --timeout=180
#: --timeout-method=thread, and #1241 puts the per-call ceiling at 180/3 = 60s.
#: These fixtures are a handful of files; 30s is half the ceiling.
_CLI_S = 30


def _tree(root: Path, reasons=None, checkers=("sample_check.py",)) -> Path:
    """A repo whose only checker(s) are SKILL-only.

    SKILL is the weakest runner there is — the program runs if and only if an
    agent reads that document and chooses to run it — which is exactly the
    population the register describes.
    """
    plugin = root / "vibe-ic-marketplace" / "plugins" / "vibe-ic"
    for d in ("programs/tests", "flow", "skills", "agents", "commands", "tests"):
        (plugin / d).mkdir(parents=True, exist_ok=True)
    (root / ".github" / "workflows").mkdir(parents=True, exist_ok=True)
    (root / "tools").mkdir(parents=True, exist_ok=True)
    for name in checkers:
        (plugin / "programs" / name).write_text("def main():\n    return 0\n")
    (root / ".github" / "workflows" / "ci.yml").write_text("name: CI\n")
    (plugin / "flow" / "flow.yaml").write_text("steps: []\n")
    # the ONLY reference: a skill document an agent may choose to follow
    (plugin / "skills" / "s.md").write_text(
        "Run " + " and ".join(c[:-3] for c in checkers) + " when auditing.\n")
    (plugin / "programs" / "other.py").write_text("x = 1\n")
    (plugin / "programs" / "tests" / "test_sample.py").write_text("pass\n")
    if reasons is not None:
        (plugin / "programs" / M._SKILL_ONLY_NAME).write_text(
            json.dumps({"_comment": "fixture", "reasons": reasons},
                       indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return plugin


def _cli(root: Path):
    """Run the audit as the landing gate runs it.

    `--baseline` is pinned into the fixture on purpose: without it the run
    would read the SHIPPED baseline while auditing a two-file tree, and every
    recorded name would be reported as resolved. That is a different finding
    and it would mask this one.
    """
    bl = root / "bl.json"
    bl.write_text(json.dumps({"known": []}) + "\n")
    return subprocess.run(
        [sys.executable, str(PROG), "--repo-root", str(root),
         "--baseline", str(bl)], capture_output=True, text=True, timeout=_CLI_S)


# ── the classifier ─────────────────────────────────────────────────────────
def test_a_blank_reason_is_a_gesture_not_a_disclosure():
    """The mutation from the issue: keep the key, empty the value."""
    disclosed, gestured = M.classify_disclosures(["a_check.py"], {"a_check.py": ""})
    assert disclosed == []
    assert gestured == ["a_check.py"]


def test_whitespace_is_not_a_measurement_either():
    """`len(reason)` alone would pass this; the register asks for a statement."""
    disclosed, gestured = M.classify_disclosures(
        ["a_check.py"], {"a_check.py": " " * (M._MIN_DECISION_REASON + 50)})
    assert (disclosed, gestured) == ([], ["a_check.py"])


def test_a_measured_reason_IS_a_disclosure():
    """The paired half. Without it the fix is satisfied by refusing everything."""
    disclosed, gestured = M.classify_disclosures(
        ["a_check.py"], {"a_check.py": MEASURED})
    assert (disclosed, gestured) == (["a_check.py"], [])


def test_silence_is_in_neither_list_and_does_not_block():
    """THE ANTI-CHEAP-REPAIR PIN.

    28 of the 30 SKILL-only checkers on 2efa6af35 carry no entry at all.
    Requiring a reason from them is a separate decision with a 28-row blast
    radius; making absence blocking would satisfy "a blank reason now fails"
    and quietly ship that decision instead of this one.
    """
    disclosed, gestured = M.classify_disclosures(
        ["quiet_check.py", "loud_check.py"], {"loud_check.py": MEASURED})
    assert disclosed == ["loud_check.py"]
    assert gestured == [], "a checker with NO entry must never be a finding"


def test_a_non_string_reason_is_a_gesture():
    """`null` in the JSON is a claim with no statement behind it."""
    assert M.classify_disclosures(["a_check.py"], {"a_check.py": None}) == (
        [], ["a_check.py"])


# ── the gate ───────────────────────────────────────────────────────────────
def test_the_audit_BLOCKS_and_NAMES_a_gestured_reason(tmp_path):
    """rc 1, and the name is in the output — a count tells you how much debt
    there is, only the name lets anyone pay it."""
    _tree(tmp_path, reasons={"sample_check.py": ""})
    r = _cli(tmp_path)
    assert r.returncode == 1, r.stdout
    assert "sample_check.py" in r.stdout, r.stdout
    assert "not gesture at one" in r.stdout, r.stdout
    assert "(skill-only, reason recorded) sample_check.py" not in r.stdout, r.stdout


def test_the_SAME_tree_with_a_measured_reason_passes(tmp_path):
    """The paired half: one field changes, the verdict flips back to rc 0 and
    the entry is reported exactly as it was before this fix."""
    _tree(tmp_path, reasons={"sample_check.py": MEASURED})
    r = _cli(tmp_path)
    assert r.returncode == 0, r.stdout
    assert "(skill-only, reason recorded) sample_check.py" in r.stdout, r.stdout
    assert "1 carry a written reason" in r.stdout, r.stdout


def test_the_audit_does_NOT_block_on_a_checker_with_no_entry(tmp_path):
    """The CLI twin of the anti-cheap-repair pin: an empty register over a
    SKILL-only checker is rc 0, and that checker is counted as one that does
    NOT carry a reason rather than as a finding."""
    _tree(tmp_path, reasons={})
    r = _cli(tmp_path)
    assert r.returncode == 0, r.stdout
    assert "0 carry a written reason" in r.stdout, r.stdout
    assert "1 do not" in r.stdout, r.stdout


def test_a_gestured_entry_is_not_counted_as_one_that_carries_a_reason(tmp_path):
    """The reported COUNT is the defect's other half: pre-fix the blank entry
    was counted in "N carry a written reason", so the summary line asserted
    something the register did not contain."""
    _tree(tmp_path, reasons={"sample_check.py": "see the PR"})
    r = _cli(tmp_path)
    assert r.returncode == 1, r.stdout
    assert "0 carry a written reason" in r.stdout, r.stdout
    assert "see the PR" in r.stdout, (
        "the gesture itself must be quoted, or the reader cannot tell a blank "
        "entry from a one-line one without opening the register")


def test_EVERY_gestured_entry_is_named_not_just_counted(tmp_path):
    """Two at once, because a bare count is a regression dressed as a fix: a
    number says how much debt there is, only the name lets anyone pay it. It
    also exercises the plural branch of the summary line, which a one-entry
    fixture can never reach."""
    _tree(tmp_path, checkers=("a_check.py", "b_check.py"),
          reasons={"a_check.py": "", "b_check.py": "too short"})
    r = _cli(tmp_path)
    assert r.returncode == 1, r.stdout
    assert "2 entries below" in r.stdout, r.stdout
    for name in ("a_check.py", "b_check.py"):
        assert f"   {name}: reason must state the MEASUREMENT" in r.stdout, r.stdout


# ── the bar is imported, not invented ──────────────────────────────────────
def test_the_bar_is_the_one_this_file_ALREADY_sets_for_its_other_register():
    """`check_unwired_by_decision` has refused a gesture since #693. Both
    registers answer the identical question — why is this checker not
    machine-wired — so this is one policy applied twice, not a new one."""
    assert M._MIN_DECISION_REASON == 120
    problems = M.check_unwired_by_decision(
        {"machine_runners": {"a_check.py": []}}, {"a_check.py": "short"}, [])
    assert any("not gesture at one" in p for p in problems), problems


def test_the_blast_radius_on_the_shipped_register_is_ZERO():
    """Measured before choosing the bar, and re-measured here so the claim
    cannot go stale: every entry the repo actually ships already clears it, so
    enforcing it changes no verdict on this tree."""
    programs = Path(__file__).resolve().parents[1]
    reasons = M.skill_only_register(programs / M._SKILL_ONLY_NAME)
    assert reasons, "the register must not be empty while entries are claimed"
    _, gestured = M.classify_disclosures(list(reasons), reasons)
    assert gestured == [], (
        f"{gestured} claim a reason without stating one; this test is the "
        f"record that enforcing {M._MIN_DECISION_REASON} chars was a no-op "
        f"when it landed")
