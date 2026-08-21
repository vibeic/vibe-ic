#!/usr/bin/env python3
"""Tests for checker_execution_wiring_audit (vibe-ic#381).

Bidirectional by construction: every case that must FIRE is paired with the
same tree made clean, because either assertion alone proves nothing.

Two of these pin bugs this program actually had while it was being written,
and both were the SAME shape — a matcher whose own assumption produced a
confident false accusation:

  * `".git" in path` also swallows `.github/`, emptying the CI haystack, so
    every CI-wired checker was reported as unwired.
  * matching only the QUOTED stem missed the flow definition, which writes
    gate names bare, so 12 wired gates were reported as wired nowhere.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent / "checker_execution_wiring_audit.py"
sys.path.insert(0, str(PROG.parent))
import checker_execution_wiring_audit as M  # noqa: E402


def _tree(root: Path, *, ci="", flow="", skill="", prog="", test="", index=""):
    """Build a minimal repo whose only checker is `sample_check.py`."""
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
    (plugin / "programs" / "tests" / "test_sample.py").write_text(test or "pass\n")
    (plugin / "programs" / "INDEX.md").write_text(index or "# index\n")
    return plugin


def _run(root: Path):
    return M.audit(root / "vibe-ic-marketplace" / "plugins" / "vibe-ic", root)


def test_test_only_checker_is_a_finding(tmp_path):
    """Only its own unit test runs it -> zero coverage of real inputs."""
    _tree(tmp_path, test="import sample_check\n")
    rep = _run(tmp_path)
    assert "sample_check.py" in rep["test_only"]
    assert rep["no_runner_at_all"] == []


def test_same_checker_wired_into_ci_is_clean(tmp_path):
    """The paired half: add a real runner and the finding must disappear."""
    _tree(tmp_path,
          test="import sample_check\n",
          ci="name: CI\njobs:\n  a:\n    steps:\n"
             "      - run: python3 programs/sample_check.py\n")
    rep = _run(tmp_path)
    assert rep["test_only"] == []
    assert rep["no_runner_at_all"] == []


def test_dot_github_is_not_eaten_by_the_dot_git_exclusion(tmp_path):
    """REGRESSION: `".git" in path` also matches `.github/`.

    With a substring exclusion the CI haystack is EMPTY, so a CI-wired
    checker is reported as unwired — a confident finding manufactured by
    the scanner's own filter. Assert the haystack is populated, not merely
    that the verdict is clean, so the reason stays pinned.
    """
    _tree(tmp_path, ci="run: python3 sample_check.py\n")
    hay = M._haystacks(tmp_path / "vibe-ic-marketplace/plugins/vibe-ic", tmp_path)
    assert hay["CI"], "the .github haystack must not be excluded as '.git'"


def test_bare_unquoted_flow_reference_counts(tmp_path):
    """REGRESSION: the flow definition writes gate names BARE.

    A matcher that only accepts the quoted stem or the `.py` filename
    reports wired gates as wired nowhere.
    """
    _tree(tmp_path, test="import sample_check\n",
          flow="steps:\n  - gate: sample_check\n")
    assert _run(tmp_path)["test_only"] == []


def test_catalogue_listing_is_not_a_runner(tmp_path):
    """INDEX.md NAMES checkers and runs none.

    Counting a catalogue would let a checker be 'wired' by being listed —
    the exact paper-only wiring this gate exists to find.
    """
    _tree(tmp_path, test="import sample_check\n",
          index="- sample_check.py — does a thing\n")
    assert "sample_check.py" in _run(tmp_path)["test_only"]


def test_substring_neighbour_does_not_count_as_a_reference(tmp_path):
    """`sample_check_extra` must not satisfy `sample_check`."""
    _tree(tmp_path, test="import sample_check\n",
          ci="run: python3 sample_check_extra.py\n")
    assert "sample_check.py" in _run(tmp_path)["test_only"]


def test_prose_inside_a_program_is_not_a_runner(tmp_path):
    """REGRESSION: a docstring / comment NAMES a checker, it never runs one.

    Adding a docstring to the audit itself that named a recorded checker
    while explaining why it is hard to wire made that entry look wired and
    silently removed it from a register that may only shrink for a real
    reason. Measured over the repo, prose accounted for 20+ entries wrongly
    counted as wired.
    """
    _tree(tmp_path, test="import sample_check\n",
          prog='"""Docs mention sample_check here."""\n'
               "# and a comment: sample_check\n"
               "y = 2\n")
    assert "sample_check.py" in _run(tmp_path)["test_only"]


def test_a_string_literal_invocation_still_counts(tmp_path):
    """The paired half: only BARE-EXPRESSION strings are dropped.

    `subprocess.run([..., "foo_check.py"])` is a real invocation and must
    survive prose-stripping, otherwise the fix trades a false PASS for a
    false accusation.
    """
    _tree(tmp_path, test="import sample_check\n",
          prog='import subprocess\n'
               'subprocess.run(["python3", "sample_check.py"])\n')
    assert _run(tmp_path)["test_only"] == []


def test_yaml_comment_is_not_a_runner(tmp_path):
    """A commented-out gate entry is a gate that does not run."""
    _tree(tmp_path, test="import sample_check\n",
          flow="steps:\n  # - gate: sample_check\n")
    assert "sample_check.py" in _run(tmp_path)["test_only"]


def test_growth_needs_a_reason_and_records_the_previous_size(tmp_path):
    """A wider scope finding pre-existing debt is not a regression — but it
    must be recorded, not assumed, and a one-word excuse is not a reason."""
    _tree(tmp_path)
    bl = tmp_path / "bl.json"
    bl.write_text(json.dumps({"known": []}) + "\n")
    common = [sys.executable, str(PROG), "--repo-root", str(tmp_path),
              "--baseline", str(bl), "--write-baseline"]
    short = subprocess.run(common + ["--scope-expanded", "because"],
                           capture_output=True, text=True)
    assert short.returncode == 1
    assert "needs a real reason" in short.stdout
    ok = subprocess.run(common + [
        "--scope-expanded",
        "comments and docstrings no longer count as runners, so prose-only "
        "references are now correctly reported"], capture_output=True, text=True)
    assert ok.returncode == 0, ok.stdout
    d = json.loads(bl.read_text())
    assert d["known"] == ["sample_check.py"]
    assert d["previous_size"] == 0
    assert "prose-only" in (d["scope_expanded"] or "")


def test_refresh_triage_measures_by_running(tmp_path):
    """Triage must be REGENERABLE, not a one-off someone typed in."""
    _tree(tmp_path)
    (tmp_path / "vibe-ic-marketplace/plugins/vibe-ic/programs/sample_check.py"
     ).write_text("import sys\nprint('needs an input')\nsys.exit(2)\n")
    bl = tmp_path / "bl.json"
    r = subprocess.run(
        [sys.executable, str(PROG), "--repo-root", str(tmp_path),
         "--baseline", str(bl), "--write-baseline", "--refresh-triage"],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stdout
    tri = json.loads(bl.read_text())["triage"]["sample_check.py"]
    assert tri.startswith("rc=2"), tri
    assert "needs an input" in tri


def test_checker_referenced_by_nothing_is_reported_separately(tmp_path):
    _tree(tmp_path)
    rep = _run(tmp_path)
    assert rep["no_runner_at_all"] == ["sample_check.py"]
    assert rep["test_only"] == []


#: vibe-ic#1241. `ci_harness_timeout_ceiling_check` puts the per-call ceiling at
#: harness_bound/3 = 180/3 = 60s. A bound ABOVE it cannot fire before the
#: harness does, and pytest's thread-method timeout then kills the SESSION
#: rather than the test — the invocation ends with no summary line.
#:
#: I wrote this helper at 600s in the SAME PR that fixes a reporting defect in
#: this very audit, which is the honest version of how this class survives.
#: MEASURED, `--durations`: the three tests that use `_cli` are 0.05s each. The
#: module's 31.17s belongs to `test_real_repo_runs_and_is_deterministic`, which
#: is pre-existing and does not go through here. 30s is ~600x the measured worst
#: case for this helper and half the ceiling.
_CLI_S = 30


def _cli(root: Path, *extra):
    """Run the audit as the landing gate runs it, and return the process."""
    argv = list(extra)
    if "--baseline" not in argv:
        # An absent ratchet artefact is not an empty measurement (#1705).
        # These reporting tests need the explicit clean measurement they were
        # always intending to exercise.
        baseline = root / "checker-execution-baseline.json"
        baseline.write_text(json.dumps({"known": []}) + "\n")
        argv.extend(("--baseline", str(baseline)))
    return subprocess.run(
        [sys.executable, str(PROG), "--repo-root", str(root), *argv],
        capture_output=True, text=True, timeout=_CLI_S)


def test_the_zero_is_STATED_not_left_silent(tmp_path):
    """vibe-ic#1130 item 5. `no runner at all` used to print only when it was
    non-zero, so at zero the gate said nothing about that population — and a
    count that appears only when it is non-zero cannot be told apart from a
    check that did not run.

    That is the same defect this program exists to find, one level up: the
    audit that reports "N checkers nothing but a fixture runs" was itself
    reporting one of its own populations conditionally.
    """
    _tree(tmp_path, ci="run: python3 sample_check.py\n")
    r = _cli(tmp_path)
    assert _run(tmp_path)["no_runner_at_all"] == [], "fixture must be the ZERO case"
    assert "no-runner-at-all 0" in r.stdout, r.stdout


def test_the_population_line_states_every_count_at_once(tmp_path):
    """All four numbers on one line, so a reader never has to infer a
    population from the absence of a line about it."""
    _tree(tmp_path, ci="run: python3 sample_check.py\n")
    out = _cli(tmp_path).stdout
    for token in ("test-only", "no-runner-at-all", "skill-only", "baseline"):
        assert token in out, (token, out)


def test_a_NON_zero_no_runner_population_is_still_NAMED(tmp_path):
    """The inverse, without which the two above are satisfied by replacing the
    names with a bare count — which would be a regression dressed as a fix.
    A number tells you how much debt there is; only the name lets anyone pay
    it.

    ASSERTED ON THIS POPULATION'S OWN LINE, not on the name appearing anywhere
    in stdout. The first version of this test checked `"sample_check.py" in
    out` and SURVIVED the mutant that drops these names, because the same
    fixture's checker is also listed under the `[FAIL]` block for a different
    population. A bare substring over whole-process output is satisfied by any
    line that happens to mention the token, which is how an assertion becomes
    decoration.
    """
    _tree(tmp_path)
    assert _run(tmp_path)["no_runner_at_all"] == ["sample_check.py"]
    out = _cli(tmp_path).stdout
    assert "no-runner-at-all 1" in out, out
    assert "(no runner at all) sample_check.py" in out, out


def test_baseline_refuses_to_grow(tmp_path):
    """A checker LOSING its only real runner is a regression, not a fact."""
    _tree(tmp_path)
    bl = tmp_path / "bl.json"
    bl.write_text(json.dumps({"known": []}) + "\n")
    rc = subprocess.run(
        [sys.executable, str(PROG), "--repo-root", str(tmp_path),
         "--baseline", str(bl), "--write-baseline"],
        capture_output=True, text=True)
    assert rc.returncode == 1, rc.stdout
    assert "refusing to GROW" in rc.stdout


def test_baseline_shrink_is_accepted_and_triage_survives(tmp_path):
    """The paired half of the growth refusal, plus: triage is not discarded.

    A register of bare names invites the worst repair — deleting the test so
    the entry disappears — so what was found when an entry was investigated
    has to survive a rewrite.
    """
    _tree(tmp_path, ci="run: python3 sample_check.py\n")
    bl = tmp_path / "bl.json"
    bl.write_text(json.dumps(
        {"known": ["sample_check.py", "gone_check.py"],
         "triage": {"sample_check.py": "why", "gone_check.py": "stale"}}) + "\n")
    rc = subprocess.run(
        [sys.executable, str(PROG), "--repo-root", str(tmp_path),
         "--baseline", str(bl), "--write-baseline"],
        capture_output=True, text=True)
    assert rc.returncode == 0, rc.stdout
    d = json.loads(bl.read_text())
    assert d["known"] == []
    assert d["triage"] == {}


def test_resolved_entry_forces_the_baseline_to_shrink(tmp_path):
    """A recorded entry that gained a runner must FAIL until it is removed,
    so the register can never quietly become permission."""
    _tree(tmp_path, ci="run: python3 sample_check.py\n")
    bl = tmp_path / "bl.json"
    bl.write_text(json.dumps({"known": ["sample_check.py"]}) + "\n")
    rc = subprocess.run(
        [sys.executable, str(PROG), "--repo-root", str(tmp_path),
         "--baseline", str(bl)], capture_output=True, text=True)
    assert rc.returncode == 1, rc.stdout
    assert "now HAVE a real runner" in rc.stdout


def test_real_repo_runs_and_is_deterministic():
    """End-to-end on this repo: two runs must agree."""
    root = PROG.parents[4]
    if not (root / "vibe-ic-marketplace").is_dir():
        pytest.skip("not in the repo layout")
    a = M.audit(PROG.parents[1], root)
    b = M.audit(PROG.parents[1], root)
    assert a == b
    assert a["checkers"] > 100
    # And the answer must be a real measurement, not the all-empty-haystack
    # degenerate one below. See the `.claude/worktrees` regression.
    assert len(a["no_runner_at_all"]) < a["checkers"]


def test_a_checkout_living_under_dot_claude_worktrees_is_not_all_skipped(tmp_path):
    """REGRESSION: the skip set matched the CHECKOUT'S OWN ancestors.

    `_SKIP_PARTS` exists to skip a nested `.claude/worktrees/` copy INSIDE
    the repo. Matched against the ABSOLUTE parts it also matches the repo's
    ancestors, so a checkout at `.../.claude/worktrees/<name>/` has every
    haystack file skipped and the audit reports `no runner at all` for every
    checker in the tree. Measured on a real agent worktree: 494 of 494 — the
    same false-accusation-from-the-matcher's-own-assumption shape as the two
    bugs already pinned above, and it turns this gate into pure noise on the
    checkout shape agents actually run in.

    Paired against the identical tree at a plain path: the two must agree.
    """
    plain = tmp_path / "plain"
    plain.mkdir()
    _tree(plain, ci="run: python3 sample_check.py\n")
    nested = tmp_path / ".claude" / "worktrees" / "agent-1"
    nested.mkdir(parents=True)
    _tree(nested, ci="run: python3 sample_check.py\n")

    a = _run(plain)
    b = _run(nested)
    assert b["no_runner_at_all"] == [], (
        "the checkout's own ancestors must not empty every haystack")
    assert a["test_only"] == b["test_only"]
    assert a["no_runner_at_all"] == b["no_runner_at_all"]


def test_a_nested_worktree_copy_inside_the_repo_is_still_skipped(tmp_path):
    """The paired half — the exclusion must still do its actual job.

    A vendored copy under `.claude/worktrees/` INSIDE the checkout is not a
    runner, and counting it would let a checker look wired by its own stale
    duplicate.
    """
    _tree(tmp_path, ci="name: CI\n")
    stale = tmp_path / ".claude" / "worktrees" / "old" / "tools"
    stale.mkdir(parents=True)
    (stale / "runner.sh").write_text("python3 sample_check.py\n")
    hay = M._haystacks(tmp_path / "vibe-ic-marketplace/plugins/vibe-ic", tmp_path)
    assert not any("worktrees" in p for p in hay["TOOLS"])
    assert _run(tmp_path)["no_runner_at_all"] == ["sample_check.py"]


# ---------------------------------------------------------------------------
# vibe-ic#1130 — the population was a NAME LIST, and a gate could leave it by
# being renamed.
#
# #693 widened `*_check/_audit` to five suffixes after finding a real gate
# outside them. That fixed the instance and left the structure: the population
# is still decided by what a file is CALLED. These tests pin the replacement
# rule — a program the FLOW declares as a gate clause is in the population
# because the flow runs it, whatever its name.
# ---------------------------------------------------------------------------
import fnmatch as _fnmatch


_FLOW = (Path(__file__).resolve().parents[2] / "flow" / "phase1_phase2_phase3.yaml")
_SUFFIXES = ("*_check.py", "*_audit.py", "*_guard.py", "*_lint.py", "*_gate.py")


def test_a_flow_declared_gate_outside_the_filename_glob_is_IN_the_population():
    """The two-arm property. On origin/main these programs are absent from the
    population purely because of what they are called.

    MEASURED on a38902d1: the flow declares 127 gate programs, SEVEN of which
    match none of the five suffixes — four of them BLOCKING (`bsdl_emit` at
    step 11, `fmeda_fault_injection_coverage` at FS1, `phase1_expert_parse_track`
    at D1, `verilator_coverage_measure` at step 4).
    """
    if not _FLOW.is_file():
        pytest.skip("flow yaml not present")
    programs = Path(__file__).resolve().parents[1]
    declared = M.flow_declared_gate_programs(_FLOW)
    outside = sorted(n for n in declared
                     if (programs / n).is_file()
                     and not any(_fnmatch.fnmatch(n, s) for s in _SUFFIXES))
    assert outside, (
        "the flow declares no gate program outside the filename glob, so this "
        "property has no subject on this tree and would pass vacuously")
    population = set(M.checker_population(programs, _FLOW))
    missing = [n for n in outside if n not in population]
    assert not missing, (
        f"{len(missing)} program(s) the FLOW declares as gate clauses are absent "
        f"from the wiring audit's population purely because of their filename: "
        f"{missing}")


def test_the_flow_is_parsed_STRUCTURALLY_not_grepped(tmp_path):
    """vibe-ic#1012: a substring test over the raw YAML counted a program named
    in a COMMENT as wired, so documenting a hold made the held checker
    unmeasurable. Discovery must parse."""
    f = tmp_path / "flow.yaml"
    f.write_text(
        "steps:\n"
        "  - id: 9\n"
        "    # - program_exit_zero: \"commented_out_gate .\"\n"
        "    gate:\n"
        "      all_of:\n"
        "        - program_exit_zero: \"real_gate .\"\n"
        "        - optional_program_exit_zero:\n"
        "            command: \"optional_gate .\"\n"
        "            condition_files_exist: [\"x\"]\n",
        encoding="utf-8")
    got = M.flow_declared_gate_programs(f)
    assert got == {"real_gate.py", "optional_gate.py"}, got


def test_the_population_never_invents_a_program_this_checkout_lacks(tmp_path):
    """A clause naming a program that is not shipped here is a DIFFERENT defect
    (`gate_is_wired` owns it). Adding it to this population would make the audit
    report on a file it never opened."""
    f = tmp_path / "flow.yaml"
    f.write_text(
        "steps:\n  - id: 9\n    gate:\n      all_of:\n"
        "        - program_exit_zero: \"no_such_program_anywhere .\"\n",
        encoding="utf-8")
    programs = Path(__file__).resolve().parents[1]
    assert "no_such_program_anywhere.py" in M.flow_declared_gate_programs(f)
    assert "no_such_program_anywhere.py" not in M.checker_population(programs, f)


# ==========================================================================
# vibe-ic#1347 — an INVOCATION is not a MENTION, and neither is a guess
# ==========================================================================
# The gate could see "this string occurs in this file" and reported "this
# program is invoked". Four checkers nothing has ever run were counted as
# wired, each held up solely by another program's MESSAGE TEXT naming it.
#
# Every case below is paired, per this file's opening note: the mention half
# must FIRE and the invocation half must stay CLEAN, because trading a false
# PASS for a false accusation is not a repair. The v1 attempt at this rule
# required a literal `<stem>.py` and accused ~195 checkers that
# `flow_compliance_check.py` genuinely runs.


def test_a_name_inside_an_error_MESSAGE_is_not_a_runner(tmp_path):
    """THE #1347 DEFECT. `_strip_prose` drops docstrings and comments and keeps
    string literals, because a subprocess argv is a string literal. A sentence
    in an error message is one too, and that was the whole of the gap."""
    _tree(tmp_path, test="import sample_check\n",
          prog='def f():\n'
               '    return "no report on disk; sample_check owns that case."\n')
    assert "sample_check.py" in _run(tmp_path)["test_only"]


def test_implicit_concatenation_reads_as_the_sentence_it_is(tmp_path):
    """`"... that trips " "eda_log_check)"` looks like a bare fragment on its
    own line and is one constant to the parser. Deciding on the RAW tree is
    what makes the sentence visible; deciding on `_strip_prose`'s output
    cannot, because that output is tokenize's — ONE TOKEN PER LINE."""
    _tree(tmp_path, test="import sample_check\n",
          prog='def f():\n'
               '    return ("the long name still works but emits a warning "\n'
               '            "that trips sample_check)")\n')
    assert "sample_check.py" in _run(tmp_path)["test_only"]


def test_the_paired_half_a_real_argv_is_still_a_runner(tmp_path):
    """The invocation half of the two above: the suffix is what makes it an
    argv rather than a sentence."""
    _tree(tmp_path, test="import sample_check\n",
          prog='import subprocess\n'
               'subprocess.run(["python3", "sample_check.py"])\n')
    assert _run(tmp_path)["test_only"] == []
    assert _run(tmp_path)["not_determined"] == []


def test_an_import_is_a_runner(tmp_path):
    _tree(tmp_path, test="import sample_check\n",
          prog="import sample_check\nsample_check.main()\n")
    assert _run(tmp_path)["test_only"] == []


def test_import_module_by_name_is_a_runner(tmp_path):
    """v2/v3 of this rule would have reported `gds_streamout_layermap_check`
    unwired while it is explicitly imported: `import_module("x")` is three
    separate lines in `_strip_prose`'s output, so no multi-token shape can
    ever match it there."""
    _tree(tmp_path, test="import sample_check\n",
          prog='from importlib import import_module\n'
               'import_module("sample_check")\n')
    assert _run(tmp_path)["test_only"] == []


def test_a_dispatcher_that_builds_the_filename_runs_the_names_it_holds(tmp_path):
    """`PROGRAMS_DIR / f"{prog_name}.py"` over a registry of bare names. A
    registry a dispatcher executes IS an execution path — forgetting that is
    what made the first attempt at this rule produce 203 findings of which
    ~195 were false."""
    _tree(tmp_path, test="import sample_check\n",
          prog='from pathlib import Path\n'
               'GATES = ["sample_check"]\n'
               'for g in GATES:\n'
               '    p = Path("programs") / f"{g}.py"\n')
    assert _run(tmp_path)["test_only"] == []
    assert _run(tmp_path)["not_determined"] == []


def test_import_module_over_a_TABLE_of_names_is_a_dispatcher(tmp_path):
    """`pdk_table_coverage_check` reads `analog_tb_supply_pdk_check.PDK_FLAVORS`
    by looping `importlib.import_module(mod)` over a table. There is no
    filename anywhere, and it is a real execution path."""
    _tree(tmp_path, test="import sample_check\n",
          prog='import importlib\n'
               'TABLE = [("sample_check", "FLAVORS")]\n'
               'for mod, attr in TABLE:\n'
               '    importlib.import_module(mod)\n')
    assert _run(tmp_path)["test_only"] == []


def test_a_SHELL_dispatcher_runs_the_names_it_holds(tmp_path):
    """The same trap one language over. `tools/ci/run_plugin_self_audit.sh`
    holds six gates in a `GATES=(...)` array and runs
    `python3 "$PROGRAMS/${gate}.py"`. Requiring a literal `<stem>.py` there
    accuses every one of them — measured, before this test existed."""
    plugin = _tree(tmp_path, test="import sample_check\n")
    (tmp_path / "tools" / "self_audit.sh").write_text(
        'GATES=(\n'
        '    "sample_check"\n'
        ')\n'
        'for gate in "${GATES[@]}"; do\n'
        '    python3 "$PROGRAMS/${gate}.py" "$PLUGIN_ROOT"\n'
        'done\n')
    assert _run(tmp_path)["test_only"] == []
    assert plugin.is_dir()


def test_a_shell_that_only_NAMES_a_gate_is_not_a_dispatcher(tmp_path):
    """The paired half: no filename is ever built from the value, so the array
    is a list and not a runner."""
    _tree(tmp_path, test="import sample_check\n")
    (tmp_path / "tools" / "notes.sh").write_text(
        'GATES=(\n'
        '    "sample_check"\n'
        ')\n'
        'echo "the gates we have not wired yet: ${GATES[@]}"\n')
    assert "sample_check.py" in _run(tmp_path)["test_only"]


# ── NOT DETERMINED: the third answer ────────────────────────────────────────
# An accusation this gate cannot support is the same defect it exists to find,
# and so is a clean bill of health it cannot support. Where the shape is
# unreadable it says so instead of picking one.

def test_a_bare_name_outside_a_dispatcher_is_NOT_DETERMINED(tmp_path):
    """#1347's own reproduction: binding a checker's name to an unused
    variable flipped the audit rc=1 -> rc=0. It must no longer BUY a runner —
    and it must not be turned into an accusation either, because a lone
    identifier in a string is a registry key or a log tag and nothing here
    can tell which."""
    _tree(tmp_path, test="import sample_check\n",
          prog='_UNUSED_NAME = "sample_check"\n')
    rep = _run(tmp_path)
    assert rep["not_determined"] == ["sample_check.py"]
    assert "sample_check.py" not in rep["test_only"]
    assert "sample_check.py" not in rep["no_runner_at_all"]
    assert rep["machine_runners"]["sample_check.py"] == []


def test_a_dict_key_control_is_also_NOT_DETERMINED(tmp_path):
    """The issue's control line, `"sample_check": 1,` — same shape, and it
    must land in the same place as the variable binding above."""
    _tree(tmp_path, test="import sample_check\n",
          prog='COUNTS = {"sample_check": 1}\n')
    assert _run(tmp_path)["not_determined"] == ["sample_check.py"]


def test_an_unparseable_source_is_NOT_DETERMINED_not_a_verdict(tmp_path):
    """Nothing was parsed, so nothing there is a shape. Reading the file as
    prose would accuse; reading it as an invocation would absolve."""
    _tree(tmp_path, test="import sample_check\n",
          prog='def broken(:\n    sample_check\n')
    rep = _run(tmp_path)
    assert rep["not_determined"] == ["sample_check.py"]
    assert rep["test_only"] == []


def test_NOT_DETERMINED_never_blocks(tmp_path):
    """It is REPORTED. Blocking on it would state the verdict the gate just
    said it could not reach."""
    _tree(tmp_path, test="import sample_check\n",
          prog='_UNUSED_NAME = "sample_check"\n')
    # Its own empty baseline, so the only thing that could redden this run is
    # the finding under test.
    bl = tmp_path / "baseline.json"
    bl.write_text(json.dumps({"known": []}))
    p = _cli(tmp_path, "--baseline", str(bl))
    assert p.returncode == 0, p.stdout + p.stderr
    assert "not-determined 1" in p.stdout, p.stdout


def test_the_not_determined_count_is_STATED_even_at_zero(tmp_path):
    """#1130 again, for the population this change adds: a count that appears
    only when it is non-zero cannot be told apart from a check that did not
    run."""
    _tree(tmp_path, test="import sample_check\n")
    p = _cli(tmp_path)
    assert "not-determined 0" in p.stdout, p.stdout


def test_a_mention_is_not_promoted_by_a_SECOND_mention(tmp_path):
    """Two files naming it in prose is still nothing running it."""
    plugin = _tree(tmp_path, test="import sample_check\n",
                   prog='X = "see sample_check for the other half"\n')
    (plugin / "programs" / "third.py").write_text(
        'Y = "sample_check also owns this failure mode"\n')
    assert "sample_check.py" in _run(tmp_path)["test_only"]


def test_the_1347_findings_are_pinned_in_the_baseline():
    """REGRESSION PIN. These three are held up by nothing but another
    program's message text; each takes a project/RTL directory, so
    `repo_hygiene_gates.sh` is the wrong home (it runs repo-wide and none of
    them can answer without a design) and `flow_compliance_check.py`'s
    registry is the right one. Until that per-design wiring lands they are
    recorded, WITH the measurement that decided each, and the register may
    only shrink."""
    bl = PROG.parent / "checker_execution_wiring_baseline.json"
    if not bl.is_file():
        pytest.skip("no baseline in this checkout")
    data = json.loads(bl.read_text())
    known, triage = set(data["known"]), data.get("triage") or {}
    for name in ("agent_report_presence_check.py", "eda_log_check.py",
                 "sv_compat_check.py"):
        assert name in known, f"{name} lost its #1347 record"
        assert "1347" in (triage.get(name) or ""), \
            f"{name} is recorded without the measurement that decided it"
