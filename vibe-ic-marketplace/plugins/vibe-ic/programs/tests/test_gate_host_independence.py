#!/usr/bin/env python3
"""The same commit must give the same verdict, whoever runs it.

`gate_discloses_denominator_check` catches a gate that PASSes over an empty
tree without saying so. It does NOT catch the other half of the class: a gate
that examines the WRONG POPULATION and reports confidently about it. Four gates
have done that — and two of them were the author's, inside the fix for the
previous one.

The probe runs every CI gate twice at the same commit, once in the working
checkout and once in a throwaway `git worktree` (tracked files only), and
requires the verdict line to be identical.

PROVEN BOTH WAYS BEFORE LANDING, which is what separates it from a guess:
  negative  the gates fixed at v1.6.90/91 agree exactly, and a clean tree
            gives 26 of 26 identical
  positive  restoring `cross_layer_reference_check`'s pre-fix disk-walking
            `corpus_cells` makes the checkout report an extra finding while the
            worktree says PASS

WHAT #539 CHANGED, AND THE MEASUREMENT THAT DROVE IT
====================================================
The probe needs the two sides to DIFFER: the checkout's leftovers are the
stimulus, the fresh worktree is the control. It used to refuse on any output
from `git status --porcelain`, which threw the stimulus away. One toy gate that
counts files on disk, three trees at one commit, BEFORE:

    checkout w/ an UNTRACKED leftover   DIRTY_CHECKOUT   defect MISSED
    a fresh worktree of that commit     PASS             defect MISSED
    checkout w/ an IGNORED leftover     FAIL             defect CAUGHT

Row 2 is the pre-push "run it in a clean worktree instead" habit; it printed
`[PASS] all N corpus-scanning gate(s) give the same verdict` over a gate that
demonstrably reads local state. Row 3 caught it only because an ignored file is
invisible to `git status`, so the refusal never fired on it. AFTER: row 1 is
FAIL, row 2 is NO_STIMULUS (rc 2, not a pass), row 3 is unchanged.

Every test below that carries a `#539` marker was run against the pre-#539
module and FAILS there — the mutation control for this file.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROGRAMS))
import gate_host_independence_check as G  # noqa: E402

_REPO = _PROGRAMS.parents[3]

#: Every gate these fixtures wire returns instantly, so this bound can never be
#: reached by a healthy run — it exists so a hung one dies well inside CI's
#: 180s per-test harness budget (#542) instead of taking the subset with it.
#: The one test that deliberately drives a slow gate sets its own smaller bound.
_T = 30


def _repo_with(tmp_path: Path, script_body: str, *,
               tracked_edit: bool = False, untracked: bool = False,
               name: str = "r") -> Path:
    """A throwaway repo wiring `script_body` as its hygiene script.

    `tracked_edit` and `untracked` are SEPARATE because #539 is exactly that
    distinction: one invalidates the comparison, the other IS the comparison.
    """
    r = tmp_path / name
    (r / "tools" / "ci").mkdir(parents=True)
    (r / "tools" / "ci" / "repo_hygiene_gates.sh").write_text(script_body)
    subprocess.run(["git", "init", "-q", str(r)], check=True)
    for k, v in (("user.email", "t@t"), ("user.name", "t")):
        subprocess.run(["git", "-C", str(r), "config", k, v], check=True)
    subprocess.run(["git", "-C", str(r), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(r), "commit", "-qm", "base"], check=True)
    if tracked_edit:
        (r / "tools" / "ci" / "repo_hygiene_gates.sh").write_text(
            script_body + "# an uncommitted edit to a TRACKED file\n")
    if untracked:
        (r / "stray.txt").write_text("x\n")
    return r


def _counter_repo(tmp_path: Path, *, ignore_dat: bool, name: str = "r") -> Path:
    """A repo whose ONE gate counts `*.dat` files on disk.

    The reduced form of `cross_layer_reference_check`'s 46-cells-against-23:
    a gate whose verdict is a function of what is lying on this disk rather
    than of what the commit carries.

    A SCRIPT FILE, not `python3 -c "..."`: the expander splits on whitespace
    exactly as the real gates need, so a quoted argument containing spaces
    would be a fixture artefact rather than a property of the subject.
    """
    r = _repo_with(tmp_path, 'run "counter" "$ROOT" python3 counter.py\n',
                   name=name)
    (r / "counter.py").write_text(
        "import pathlib\n"
        "print('PASS', len(list(pathlib.Path('.').glob('*.dat'))))\n")
    add = ["counter.py"]
    if ignore_dat:
        (r / ".gitignore").write_text("*.dat\n")
        add.append(".gitignore")
    subprocess.run(["git", "-C", str(r), "add", *add], check=True)
    subprocess.run(["git", "-C", str(r), "commit", "-qm", "counter"], check=True)
    return r


def _porcelain(p: Path) -> list:
    out = subprocess.run(["git", "-C", str(p), "status", "--porcelain"],
                         capture_output=True, text=True).stdout
    return [x for x in out.splitlines() if x.strip()]


# --------------------------------------------------------------------------
# what invalidates the comparison, and what does not
# --------------------------------------------------------------------------
def test_a_modified_TRACKED_file_is_refused_not_reported_as_findings(tmp_path):
    """THE ONE THAT BIT ME. The worktree is at HEAD, so an uncommitted edit
    reads as a difference — an in-progress version of this very program made
    the chip-agnostic guard report 1241 files against the worktree's 1240 and
    flagged itself as an unwired checker. Reporting those as host-dependence
    would be a probe that fires on its own author.

    Refused, not filtered: "the comparison could not be made" is its own state.
    """
    r = _repo_with(tmp_path, 'run "x" "$ROOT" python3 -c "print(1)"\n',
                   tracked_edit=True)
    res = G.audit(r, timeout=_T)
    assert res.verdict == "DIRTY_CHECKOUT", res
    assert res.findings and res.findings[0]["kind"] == "DIRTY_CHECKOUT"
    assert res.probed == 0, "nothing ran, and the record must say so"


def test_539_an_UNTRACKED_leftover_no_longer_blocks_the_probe(tmp_path):
    """#539. The maintainer's tree is dirty BY CONSTRUCTION — 207 untracked
    benchmark artefacts, build logs and run directories — so the old refusal
    made this probe structurally unable to run in the one tree these leftovers
    accumulate in. It refused the stimulus.

    Untracked paths are not an obstacle to the comparison: they are present
    here and absent from a worktree at HEAD, which is the condition being
    probed.
    """
    r = _repo_with(tmp_path, 'run "x" "$ROOT" python3 -c "print(1)"\n',
                   untracked=True)
    assert len(_porcelain(r)) == 1
    res = G.audit(r, timeout=_T)
    assert res.verdict == "PASS", res
    assert res.probed == 1


def test_539_a_gate_reading_an_UNTRACKED_leftover_is_CAUGHT(tmp_path):
    """#539, the coverage this issue is about. Same defect as the ignored-file
    positive control below, in the shape the maintainer's tree actually has —
    and the shape the probe used to refuse to look at."""
    r = _counter_repo(tmp_path, ignore_dat=False)
    (r / "leftover.dat").write_text("x\n")          # UNTRACKED, visible
    assert len(_porcelain(r)) == 1

    res = G.audit(r, timeout=_T)
    assert res.verdict == "FAIL", res
    assert res.findings[0]["kind"] == "HOST_DEPENDENT_VERDICT"
    assert "checkout" in res.findings[0] and "worktree" in res.findings[0]


def test_a_gate_that_reads_an_IGNORED_leftover_is_caught(tmp_path):
    """THE POSITIVE CONTROL, reduced. A gate that counts files on DISK sees an
    ignored leftover in the checkout and not in the worktree — which is exactly
    what `cross_layer_reference_check` did with 46 cells against 23.

    Before #539 this was the ONLY shape the probe could catch, and only because
    an ignored file is invisible to `git status --porcelain` so the refusal
    never fired on it. It must keep working.
    """
    r = _counter_repo(tmp_path, ignore_dat=True)
    (r / "leftover.dat").write_text("x\n")          # IGNORED => tree "clean"
    assert not _porcelain(r)

    res = G.audit(r, timeout=_T)
    assert res.verdict == "FAIL", res
    assert res.findings[0]["kind"] == "HOST_DEPENDENT_VERDICT"


# --------------------------------------------------------------------------
# #539 — the comparison must disclose whether it could have detected anything
# --------------------------------------------------------------------------
def test_539_two_identical_trees_are_NOT_CHECKED_rather_than_a_pass(tmp_path):
    """#539. With no leftover on either side the checkout and the worktree hold
    the same bytes, so every gate agrees BY CONSTRUCTION. That is arithmetic,
    not evidence, and it used to print the same green sentence as a real run.

    rc 2 / NOT_CHECKED rather than rc 1: nothing is wrong with the tree or the
    gates, and a permanently red gate is a gate that gets skipped.
    """
    r = _counter_repo(tmp_path, ignore_dat=False)
    assert not _porcelain(r)
    res = G.audit(r, timeout=_T)
    assert res.verdict == "NO_STIMULUS", res
    assert res.findings == []
    assert res.dirt.stimulus == 0


def test_539_the_clean_worktree_ROUTE_reports_NOT_CHECKED_not_PASS(tmp_path):
    """#539, THE ONE THAT OVERTURNS THE WORKAROUND.

    The pre-push habit was `git worktree add --detach <path> HEAD` followed by
    running this probe against that path — 554s per push — on the reasoning
    that a clean tree is what the probe wants. It is not: a fresh worktree
    carries no leftover either, so the probe compares two pristine trees and
    reports PASS over a gate that demonstrably reads local state. The defect is
    RIGHT THERE in the checkout the worktree was made from, and this run cannot
    see it.

    A habit whose absence is indistinguishable from its presence is not
    coverage. After #539 the route announces itself: NO_STIMULUS, rc 2, NOT
    CHECKED. The gate that says nothing now says that it says nothing.
    """
    r = _counter_repo(tmp_path, ignore_dat=False)
    (r / "leftover.dat").write_text("x\n")          # the defect is in `r`
    assert G.audit(r, timeout=_T).verdict == "FAIL", "the defect is real"

    wt = tmp_path / "second_route"
    subprocess.run(["git", "-C", str(r), "worktree", "add", "-q", "--detach",
                    str(wt), "HEAD"], check=True)
    assert not list(wt.glob("*.dat")), "a fresh worktree carries no leftover"

    res = G.audit(wt, timeout=_T)
    assert res.verdict == "NO_STIMULUS", res
    assert res.verdict != "PASS", "the route must not certify what it cannot see"


def test_539_the_stimulus_is_reported_ON_THE_PASS_LINE(tmp_path, capsys):
    """A PASS must say how much it looked at (#447), applied to this probe's
    own input rather than to the gates it drives.

    Driven through `main` and asserted against the PRINTED sentence. A first
    version asserted `res.dirt.describe()` instead — which passes while the
    verdict line says nothing at all, and a disclosure a reader never sees is
    not a disclosure. Deleting `{stim}` from the PASS line survived that test
    and dies against this one.
    """
    r = _repo_with(tmp_path, 'run "x" "$ROOT" python3 -c "print(1)"\n',
                   untracked=True)
    res = G.audit(r, timeout=_T)
    assert res.verdict == "PASS" and res.dirt.stimulus == 1, res

    assert G.main([str(r)]) == 0
    line = [ln for ln in capsys.readouterr().err.splitlines()
            if ln.startswith("[PASS]")]
    assert len(line) == 1, line
    assert "1 untracked" in line[0], line
    assert "1 probed" in line[0] and "1 declared" in line[0], line


def test_539_the_cli_says_NOT_CHECKED_and_exits_2_with_no_stimulus(tmp_path,
                                                                  capsys):
    """Driven through `main`, not through `audit`: the exit code and the
    sentence are what a reader and `_gate_dispatch.sh` actually consume, and a
    verdict that never reaches either is not a verdict."""
    r = _counter_repo(tmp_path, ignore_dat=False)
    out = tmp_path / "rec.json"
    rc = G.main([str(r), "--json", str(out)])
    err = capsys.readouterr().err
    assert rc == 2, err
    assert "NO_STIMULUS" in err and "not a pass" in err
    doc = json.loads(out.read_text())
    assert doc["verdict"] == "NO_STIMULUS"
    assert doc["stimulus"] == {"untracked": 0, "ignored": 0,
                               "ignored_reported": True}


# --------------------------------------------------------------------------
# denominators: declared vs probed
# --------------------------------------------------------------------------
def test_an_empty_gate_list_is_NOT_a_pass(tmp_path):
    """This program's own denominator."""
    r = _repo_with(tmp_path, "# no gates\n")
    assert G.audit(r, timeout=_T).verdict == "NOTHING_SCANNED"


def test_the_cwd_token_is_preserved(tmp_path):
    """Dropped in a first version, which made every `$PLUGIN`-scoped gate fail
    to open its own relative path IN BOTH TREES and produced 9 identical-error
    "findings". A probe that reports a defect because it could not run the
    subject is worse than no probe."""
    gates = G.corpus_gates(_REPO / "tools" / "ci" / "repo_hygiene_gates.sh")
    assert gates, "no gates parsed from the real CI script"
    assert {g.cwd_token for g in gates} <= {"$ROOT", "$PLUGIN"}
    assert any(g.cwd_token == "$PLUGIN" for g in gates), "the $PLUGIN lane is untested"
    assert all(g.cmd and not g.cmd.lstrip().startswith("#") for g in gates)


def test_pytest_wall_clock_is_not_mistaken_for_a_different_verdict():
    """Both arms passed the same 108 tests; 15.44s vs 16.26s is not RED."""
    a = G._verdict_line("108 passed in 15.44s\n")
    b = G._verdict_line("108 passed in 16.26s\n")
    assert a == b == "108 passed in <TIME>s"
    assert G._verdict_line("107 passed, 1 failed in 15.44s") != a


def test_539_a_gate_that_needs_the_network_is_EXCLUDED_in_the_real_script():
    """#539. The rule, asserted over the REAL script rather than a fixture: a
    gate that requires a REMOTE cannot be inside a two-invocation determinism
    comparison, because its two answers can differ for a reason that is not in
    the commit. v1.7.92 went red exactly that way.

    Stated as a PROPERTY of the command, not as an expected list of labels — a
    hand-maintained roster here would be the second list this repo keeps
    removing, and it would not notice a NEW remote-reaching gate. This is what
    makes the exclusion by rule rather than by luck.

    A first version only checked "every exclusion states a reason", which
    passes over a script with no exclusions at all — the vacuous shape this
    module exists to refuse.
    """
    gates = G.corpus_gates(_REPO / "tools" / "ci" / "repo_hygiene_gates.sh")
    remote = [g for g in gates if "--require-remote" in g.cmd]
    assert remote, ("no remote-reaching gate found in the real script — this "
                    "assertion would otherwise pass over nothing")
    for g in remote:
        assert g.excluded is not None, (
            f"{g.label} reaches a remote and is still probed twice", g)
    for g in gates:
        if g.excluded is not None:
            # An exclusion with no reason is a silent one wearing a label.
            assert len(g.excluded) > 20, g
            assert "no reason given" not in g.excluded, g


def test_539_the_probe_ITSELF_leaves_the_numerator_and_is_NAMED(tmp_path):
    """SHIPPED AND CAUGHT BY CI. The gate list is unfiltered by design, so it
    contains this program — and running it inside the worktree runs it again,
    which creates another worktree, and so on.

    Locally it was MASKED: the working tree is permanently dirty, so the inner
    invocation returned DIRTY_CHECKOUT immediately and the recursion never
    happened. CI checks out clean, recursed, and hit the per-gate timeout.
    "It passed on my machine" was true and worthless.

    #539 adds the second half: the skip was a bare `continue` while the verdict
    line went on to say "all <declared> gate(s)". It is recorded now.
    """
    r = _repo_with(
        tmp_path,
        'run "self" "$ROOT" python3 "$PG/gate_host_independence_check.py"\n'
        'run "other" "$ROOT" python3 counter.py\n')
    (r / "counter.py").write_text("print('PASS 0')\n")
    subprocess.run(["git", "-C", str(r), "add", "counter.py"], check=True)
    subprocess.run(["git", "-C", str(r), "commit", "-qm", "c"], check=True)
    (r / "leftover.txt").write_text("x\n")          # stimulus, so not NO_STIMULUS

    # Both are parsed — the skip is at RUN time, so the list stays honest.
    assert len(G.corpus_gates(
        r / "tools" / "ci" / "repo_hygiene_gates.sh")) == 2
    res = G.audit(r, timeout=_T)
    assert res.verdict == "PASS", res
    assert res.declared == 2 and res.probed == 1
    assert [lbl for lbl, _ in res.not_probed] == ["self"]
    assert "recurse" in res.not_probed[0][1]


# --------------------------------------------------------------------------
# #539 — exclusion BY DECLARATION rather than by luck
# --------------------------------------------------------------------------
_EXCLUDE_LINE = ("# host-independence: EXCLUDE — reaches a remote service, so "
                 "two invocations can differ for a reason not in the commit\n")


def test_539_a_declared_gate_leaves_the_numerator_but_not_the_denominator(
        tmp_path, capsys):
    """#539. `sync_image_version --check --require-remote` makes an HTTPS call
    to a registry, and this probe requires two invocations to agree — which is
    how v1.7.92 went red on a gate whose code is perfectly host-independent and
    green on the identical commit when re-run.

    The subject here is a gate that would otherwise be caught: excluding it
    must change the VERDICT, so the test cannot pass by the directive being
    ignored.
    """
    r = _counter_repo(tmp_path, ignore_dat=False)
    (r / "tools" / "ci" / "repo_hygiene_gates.sh").write_text(
        _EXCLUDE_LINE + 'run "counter" "$ROOT" python3 counter.py\n')
    subprocess.run(["git", "-C", str(r), "commit", "-qam", "declare"],
                   check=True)
    (r / "leftover.dat").write_text("x\n")          # would be a finding

    res = G.audit(r, timeout=_T)
    assert res.verdict == "PASS", res
    assert res.declared == 1, "an exclusion must not shrink the population"
    assert res.probed == 0
    assert res.not_probed[0][0] == "counter"
    assert "EXCLUDED by declaration" in res.not_probed[0][1]

    G.main([str(r)])
    assert "[NOT PROBED] counter" in capsys.readouterr().err


def test_539_a_DETACHED_directive_does_not_exclude(tmp_path):
    """FAIL-SAFE BY SHAPE. The directive binds to the line immediately below
    it. If it drifts — a line inserted, the gate moved — the gate is PROBED
    again. The failure mode is a returning flake, which is visible; a directive
    that kept excluding from a distance would be a silent hole that reads
    exactly like a deliberate decision.
    """
    r = _counter_repo(tmp_path, ignore_dat=False)
    (r / "tools" / "ci" / "repo_hygiene_gates.sh").write_text(
        _EXCLUDE_LINE + "\n"          # <- one blank line detaches it
        'run "counter" "$ROOT" python3 counter.py\n')
    subprocess.run(["git", "-C", str(r), "commit", "-qam", "detached"],
                   check=True)
    (r / "leftover.dat").write_text("x\n")

    gates = G.corpus_gates(r / "tools" / "ci" / "repo_hygiene_gates.sh")
    assert gates[0].excluded is None, gates
    assert G.audit(r, timeout=_T).verdict == "FAIL"


def test_539_the_directive_is_not_passed_to_the_gate_as_argv(tmp_path):
    """The marker is a standalone line, above the gate, precisely so that the
    OTHER reader of this script — `gate_discloses_denominator_check`, which
    carries a verbatim copy of the same regex — cannot pick it up as part of
    the command and hand it to the gate. Two readers of one script must not
    disagree about what the script says."""
    r = _counter_repo(tmp_path, ignore_dat=False)
    (r / "tools" / "ci" / "repo_hygiene_gates.sh").write_text(
        _EXCLUDE_LINE + 'run "counter" "$ROOT" python3 counter.py\n')
    gates = G.corpus_gates(r / "tools" / "ci" / "repo_hygiene_gates.sh")
    assert gates[0].cmd == "python3 counter.py", gates

    sys.path.insert(0, str(_PROGRAMS))
    import gate_discloses_denominator_check as D  # noqa: E402
    other = D.parse_gates(r / "tools" / "ci" / "repo_hygiene_gates.sh")
    assert len(other) == 1 and "#" not in str(other[0]), other


# --------------------------------------------------------------------------
# the probe's own failure modes
# --------------------------------------------------------------------------
def test_a_gate_that_cannot_be_driven_is_its_own_state_not_a_crash(tmp_path):
    """The other half of a CI failure: the per-gate timeout was UNHANDLED, so a
    slow gate killed the probe with a traceback instead of reporting. A gate
    that cannot be driven is not host-dependence, and it is not a clean result
    either."""
    r = _repo_with(tmp_path, 'run "slow" "$ROOT" python3 sleeper.py\n')
    (r / "sleeper.py").write_text("import time\ntime.sleep(30)\n")
    subprocess.run(["git", "-C", str(r), "add", "sleeper.py"], check=True)
    subprocess.run(["git", "-C", str(r), "commit", "-qm", "s"], check=True)

    res = G.audit(r, timeout=2)
    assert res.verdict == "FAIL", res
    assert res.findings[0]["kind"] == "GATE_UNRUNNABLE", res.findings
    assert "TimeoutExpired" in res.findings[0]["detail"], res.findings


def test_a_gate_that_echoes_its_own_root_is_not_host_dependent(tmp_path):
    """CAUGHT BY THIS PROBE'S FIRST GENUINE RUN, in CI, against itself.

    `marketplace_version_sync_check` prints the manifest PATHS it read. Both
    trees said "PASS: 2 manifest(s), 2 plugin entr(ies) — all versions in
    sync"; only the embedded root differed
    (`/home/runner/work/...` vs `/tmp/hostindep-.../wt/...`). The probe called
    that HOST_DEPENDENT and turned CI red.

    A comparison that reports a difference which is not one is the same defect
    class this probe exists to find — in the probe itself. Locally it could
    not show: the working tree is always dirty, so the probe never ran.
    """
    r = _repo_with(tmp_path, 'run "echoer" "$ROOT" python3 echoer.py\n')
    (r / "echoer.py").write_text(
        "import pathlib\n"
        "print('PASS: read', pathlib.Path('.').resolve())\n")
    subprocess.run(["git", "-C", str(r), "add", "echoer.py"], check=True)
    subprocess.run(["git", "-C", str(r), "commit", "-qm", "e"], check=True)
    (r / "leftover.txt").write_text("x\n")          # stimulus present

    res = G.audit(r, timeout=_T)
    assert res.verdict == "PASS", res


def test_a_real_difference_still_survives_normalisation(tmp_path):
    """The paired half. Absorbing the path must not absorb the verdict: a gate
    whose COUNT differs between the trees is still caught."""
    r = _counter_repo(tmp_path, ignore_dat=True)
    (r / "leftover.dat").write_text("x\n")     # ignored => tree stays clean

    res = G.audit(r, timeout=_T)
    assert res.verdict == "FAIL", res
    assert res.findings[0]["kind"] == "HOST_DEPENDENT_VERDICT"


# ==========================================================================
# 2026-08-04 — THE SCRATCH WORKTREE MUST NOT OUTLIVE THE PROBE
# ==========================================================================
# One parallel-agent session left NINETEEN `/tmp/hostindep-*/wt` trees, each
# still registered as a worktree of the repository every agent shares. The
# `finally` that removes them is correct and does not run on `SIGKILL`.

def _scratch_added_by(root: Path, run) -> set:
    """The `hostindep-*` directories `run` ADDS to `root`.

    A difference of two globs is only a measurement of `run` when `run` is the
    only writer of the namespace being globbed. Against the real `/tmp` it is
    not: a peer's directory created between the two globs lands in the
    difference and is attributed to `run`.
    """
    before = set(root.glob(G._SCRATCH_PREFIX + "*"))
    run()
    return set(root.glob(G._SCRATCH_PREFIX + "*")) - before


def test_a_clean_run_leaves_no_scratch_behind(tmp_path):
    """The easy half, and the one a `finally` already satisfied. Kept as the
    control: without it, a reaper that removes everything unconditionally
    would pass the kill test below and destroy live peers in production.

    OBSERVED IN A PRIVATE ROOT, for the reason `_legacy_leftover` gives below
    about planting: the real `/tmp` is shared with every other agent's probe,
    so `after - before` there counts a PEER's directory as this run's leak.
    Measured 2026-08-13 — with a sibling process creating and removing
    `hostindep-*` in the observed root, this test failed while the other 24
    passed; with no peer, 25 passed. The assertion is unchanged in strength: a
    leak by `audit` still lands in this root, which the guard below drives.
    It fired for real before that: it reddened two tests of an unrelated
    PR's verification and then did not reproduce, which is what a shared
    namespace does to a difference-of-two-globs measurement.
    """
    priv = tmp_path / "tmproot"
    priv.mkdir()
    r = _repo_with(tmp_path, 'run "x" "$ROOT" python3 -c "print(1)"\n')

    leaked = _scratch_added_by(priv, lambda: G.audit(r, timeout=_T,
                                                     tmp_root=priv))
    assert leaked == set(), "a clean run left scratch behind: %s" % (leaked,)

    # PAIRED GUARD. An observation scoped to a root nothing writes to passes by
    # being blind, which is the same green as a clean run. Plant one and the
    # SAME expression must see it.
    planted = _scratch_added_by(
        priv, lambda: (priv / (G._SCRATCH_PREFIX + "planted")).mkdir())
    assert len(planted) == 1, (
        "the scoped observation cannot see a leak planted in the very root it "
        "watches, so the assertion above proves nothing: %s" % (planted,))


def test_a_SIGKILLED_run_is_cleaned_up_by_the_NEXT_run(tmp_path):
    """The leak, and the repair, both driven.

    A child is killed while it holds a reserved scratch directory containing a
    real `git worktree` of a real repository — the exact state found on this
    host 19 times. Nothing of the child's code runs after the kill. The next
    call to the sweeper must remove the directory AND drop the registration,
    or the repo keeps the entry forever (`git worktree prune` cannot clear one
    whose directory still exists).

    PLANTED AND OBSERVED IN A PRIVATE ROOT (#1263), for the reason
    `_legacy_leftover` below already gives: the real `/tmp` is shared with
    every other agent's probe, and `reap` sweeps a WHOLE NAMESPACE, not one
    path. A DEAD owner's directory is therefore reapable by anybody, so a
    concurrent copy of this very test removes THIS copy's plant, and the two
    assertions below stop agreeing — `leaked.exists()` is false because a peer
    removed it, while `rep["reaped"]` is empty because the peer, not this
    sweep, did the removing.

    Measured 2026-08-15 on clean main (1adbf3444), four concurrent copies of
    this one test, 3 of 4 failed, in the two distinct shapes the shared
    namespace produces:

        copy 2  plant fo4896uu   assert 'fo4896uu' in []   <- copy 1 took it
        copy 3  plant hf0yimb2   assert 'hf0yimb2' in []   <- copy 1 took it
        copy 1  plant nnx7zy2c   reaped ['fo4896uu', 'hf0yimb2'] -- it had
                reaped the other two copies' plants, and lost its own a
                different way: a peer's `rmtree` had already unlinked the
                `.owner.lock`, so this sweep saw a sidecar-less directory,
                and with peers alive (`reap_unlocked=False`) KEPT it as
                unattributable while the peer finished deleting it
        copy 4  passed

    The assertion is unchanged in strength. In a root only this test writes to,
    nobody else CAN reap the plant, so "the directory is gone" and "this sweep
    reaped it" are once again the same fact — which is the fact the test claims
    to measure. Two things are deliberately NOT changed: `peers` is left to the
    real `peer_probes_running()`, so on a busy host this still runs with
    `reap_unlocked=False` and proves a LOCKED directory whose owner is dead is
    reaped even while the unattributable ones are deferred; and
    `test_a_LIVE_peers_scratch_is_never_reaped` below keeps using the real
    `/tmp`, because its plant is HELD — a locked directory is precisely the one
    no peer may touch, so a shared namespace cannot alter its verdict.
    """
    import os
    import signal
    import time

    priv = tmp_path / "tmproot"
    priv.mkdir()
    r = _repo_with(tmp_path, 'run "x" "$ROOT" python3 -c "print(1)"\n')
    child = subprocess.Popen(
        [sys.executable, "-c",
         "import subprocess, sys, time\n"
         "sys.path.insert(0, %r)\n"
         "import _crash_safe_scratch as S\n"
         "res, _ = S.reserve(%r, root=%r)\n"
         "wt = res.path / 'wt'\n"
         "subprocess.run(['git','-C',%r,'worktree','add','-q','--detach',"
         "str(wt),'HEAD'], check=True)\n"
         "print(res.path, flush=True)\n"
         "time.sleep(600)\n"
         % (str(_PROGRAMS), G._SCRATCH_PREFIX, str(priv), str(r))],
        stdout=subprocess.PIPE, text=True, start_new_session=True)
    leaked = Path(child.stdout.readline().strip())
    assert (leaked / "wt").is_dir(), "the fixture never created the worktree"
    listed = subprocess.run(["git", "-C", str(r), "worktree", "list"],
                            capture_output=True, text=True, timeout=_T).stdout
    assert str(leaked) in listed, (
        "the fixture's worktree is not registered, so this test cannot show "
        "the registration being dropped:\n" + listed)

    os.killpg(os.getpgid(child.pid), signal.SIGKILL)
    child.wait(timeout=_T)
    time.sleep(0.2)
    assert (leaked / "wt").is_dir(), (
        "the kill itself removed the tree — then the leak this test is about "
        "cannot be reproduced and nothing below is being measured")

    rep = G.sweep_abandoned_scratch(r, tmp_root=priv)
    assert not leaked.exists(), (
        "a killed probe's scratch survived the next run: %s" % (rep,))
    assert str(leaked) in rep["reaped"], (
        "the directory is gone but THIS sweep does not claim to have removed "
        "it — in a private root nothing else can have, so the sweeper is not "
        "reporting the work it did: %s" % (rep,))
    listed = subprocess.run(["git", "-C", str(r), "worktree", "list"],
                            capture_output=True, text=True, timeout=_T).stdout
    assert str(leaked) not in listed, (
        "the directory went but the git registration stayed, which is the "
        "half `git worktree prune` cannot fix on its own:\n" + listed)


def test_a_LIVE_peers_scratch_is_never_reaped(tmp_path):
    """Several agents run in this repo at once. A sweep that cannot tell a
    dead owner from a live one would delete a running probe's worktree — an
    invisible leak traded for an invisible corruption."""
    import time
    r = _repo_with(tmp_path, 'run "x" "$ROOT" python3 -c "print(1)"\n')
    child = subprocess.Popen(
        [sys.executable, "-c",
         "import sys, time\n"
         "sys.path.insert(0, %r)\n"
         "import _crash_safe_scratch as S\n"
         "res, _ = S.reserve(%r)\n"
         "print(res.path, flush=True)\n"
         "time.sleep(600)\n" % (str(_PROGRAMS), G._SCRATCH_PREFIX)],
        stdout=subprocess.PIPE, text=True)
    held = Path(child.stdout.readline().strip())
    try:
        rep = G.sweep_abandoned_scratch(r)
        assert held.exists(), (
            "a LIVE peer's scratch was reaped: %s" % (rep,))
        assert str(held) in rep["live_peers"], (
            "the live peer was skipped silently; a skip nobody can see is how "
            "a sweep starts eating real work: %s" % (rep,))
    finally:
        child.kill()
        child.wait(timeout=_T)
        time.sleep(0.1)
        G.sweep_abandoned_scratch(r)


def test_the_sweep_runs_even_when_the_probe_refuses(tmp_path):
    """A checkout too dirty to compare is exactly the state a maintainer's
    tree is in while the leftovers accumulate. A reaper wired only into the
    happy path would almost never run."""
    r = _repo_with(tmp_path, 'run "x" "$ROOT" python3 -c "print(1)"\n',
                   tracked_edit=True)
    res = G.audit(r, timeout=_T)
    assert res.verdict == "DIRTY_CHECKOUT", res
    assert res.scratch is not None and "reaped" in res.scratch, (
        "the refusing path reports no sweep at all: %s" % (res.scratch,))


def _legacy_leftover(root: Path, name: str) -> Path:
    """A sidecar-less scratch directory a day old — what a PRE-LOCK build
    leaves. In a PRIVATE tmp root, never the real `/tmp`: a test that planted
    one there would be creating and deleting directories other agents' probes
    are reading, which is this file's own subject."""
    import os
    d = root / (G._SCRATCH_PREFIX + name)
    d.mkdir(parents=True, exist_ok=True)
    old = time.time() - 86400
    os.utime(d, (old, old))
    return d


def test_the_sweep_defers_the_unattributable_ones_while_a_peer_is_alive(
        tmp_path):
    """TRANSITION SAFETY. A peer running the PRE-LOCK build leaves a scratch
    directory with no sidecar, which this reaper can only judge by age and a
    `/proc` scan. Several agents demonstrably run against one host, so while
    ANY peer probe is alive the unlockable directories are kept rather than
    guessed at — a leak is recoverable, deleting a live agent's worktree
    mid-probe is not."""
    r = _repo_with(tmp_path, 'run "x" "$ROOT" python3 -c "print(1)"\n')
    tmp = tmp_path / "scratchroot"
    tmp.mkdir()
    legacy = _legacy_leftover(tmp, "legacyprobe")
    rep = G.sweep_abandoned_scratch(r, tmp_root=tmp, peers=[999999])
    assert legacy.exists(), (
        "an unattributable directory was deleted while a peer probe was "
        "alive: %s" % (rep,))
    assert any("may be alive" in k["why"] for k in rep["kept"]
               if k["path"] == str(legacy)), rep


def test_with_no_peer_alive_the_unattributable_ones_are_reaped(tmp_path):
    """The paired half: the deferral must be a deferral, not a permanent
    exemption, or the pre-lock leaks would never be cleaned up at all."""
    r = _repo_with(tmp_path, 'run "x" "$ROOT" python3 -c "print(1)"\n')
    tmp = tmp_path / "scratchroot"
    tmp.mkdir()
    legacy = _legacy_leftover(tmp, "legacyprobe")
    rep = G.sweep_abandoned_scratch(r, tmp_root=tmp, peers=[])
    assert not legacy.exists(), (
        "with no peer alive, a day-old sidecar-less leftover was still kept — "
        "the pre-lock leaks would never be cleaned up: %s" % (rep,))


def test_the_peer_detector_sees_a_real_process():
    """The seam above is only honest if the DEFAULT it stands in for works.

    A real process whose argv names this program must be found, and the
    detector must not count the pytest process itself — a detector that always
    answered "a peer is alive" would silently disable the legacy sweep
    forever, which looks exactly like a reaper that has nothing to do.
    """
    held = subprocess.Popen(
        [sys.executable, "-c",
         "import time; time.sleep(60)  # gate_host_independence_check.py"],
        stdout=subprocess.DEVNULL)
    try:
        for _ in range(200):
            if held.pid in G.peer_probes_running():
                break
            time.sleep(0.05)
        else:
            pytest.fail("a live process naming this program was not detected, "
                        "so the transition guard would never engage")
    finally:
        held.kill()
        held.wait(timeout=_T)
    for _ in range(200):
        if held.pid not in G.peer_probes_running():
            return
        time.sleep(0.05)
    pytest.fail("a DEAD process is still reported as a live peer, which would "
                "disable the legacy sweep permanently")


# --------------------------------------------------------------------------
# A DIFFERENCE THAT DOES NOT REPRODUCE IS NOT EVIDENCE (vibe-ic#1029 class)
#
# Measured on `3febf537`: this probe reported
#
#   [HOST_DEPENDENT_VERDICT] 63x8 census freshness
#       checkout: rc=1 AssertionError: the outcome run for
#                 test_matrix_d7_outputs_list_complete.py did not finish within 60s
#       worktree: rc=0 [PASS] 63x8 census fresh: 504 cells over 8 dimensions
#
# The two arms did not disagree about the SUBJECT. One arm ran out of wall
# clock. `_OUTCOME_TIMEOUT_S = 60` in `test_matrix_63x8_coverage` is a bound on
# an inner pytest, and this probe drives 66 gates twice, so the checkout arm is
# the one under load. Whether it fires depends on the machine, which is why the
# same tool reported 6/6 clean on one run and 5/6 on the next.
#
# `TimeoutExpired` raised at THIS level is already handled — it becomes
# GATE_UNRUNNABLE. The gap is a gate that enforces its own deadline and
# therefore RETURNS rc=1 with a message: indistinguishable, to a single
# comparison, from a real verdict.
#
# The discriminator is not the text of the message — this file's own header
# rejects deciding a tier by grepping prose. It is REPRODUCIBILITY: a gate that
# reads local state disagrees every time; a gate that ran out of clock does not.
# --------------------------------------------------------------------------

def _flapping_repo(tmp_path: Path, marker: Path, *, name: str = "r") -> Path:
    """A gate whose FIRST invocation misses a deadline and whose later ones do not.

    The marker lives OUTSIDE the repo on purpose: a counter file inside it
    would be a leftover of the fixture and would change what the probe is
    being shown.
    """
    r = _repo_with(tmp_path, 'run "flaky" "$ROOT" python3 flaky.py\n',
                   untracked=True, name=name)
    (r / "flaky.py").write_text(
        "import pathlib, sys\n"
        f"m = pathlib.Path({str(marker)!r})\n"
        "n = int(m.read_text()) if m.is_file() else 0\n"
        "m.write_text(str(n + 1))\n"
        "if n == 0:\n"
        "    print('AssertionError: the outcome run did not finish within 60s')\n"
        "    sys.exit(1)\n"
        "print('PASS (1 item examined)')\n")
    subprocess.run(["git", "-C", str(r), "add", "flaky.py"], check=True)
    subprocess.run(["git", "-C", str(r), "commit", "-qm", "flaky"], check=True)
    return r


def test_a_ONE_OFF_disagreement_is_not_reported_as_host_dependence(tmp_path):
    """THE DEFECT. A gate that misses its own deadline once is not reading
    local state, and must not be reported as if it were."""
    marker = tmp_path / "counter.txt"
    r = _flapping_repo(tmp_path, marker)
    res = G.audit(r, timeout=_T)

    kinds = [f["kind"] for f in res.findings]
    assert "HOST_DEPENDENT_VERDICT" not in kinds, (
        "a one-off disagreement was reported as host dependence: "
        f"{res.findings}")


def test_a_ONE_OFF_disagreement_is_NAMED_rather_than_silently_dropped(tmp_path):
    """...and it is not swallowed either. A gate that cannot reproduce its own
    verdict is not usable evidence; it is a different defect, not no defect."""
    marker = tmp_path / "counter.txt"
    r = _flapping_repo(tmp_path, marker)
    res = G.audit(r, timeout=_T)

    kinds = [f["kind"] for f in res.findings]
    assert "NON_DETERMINISTIC_VERDICT" in kinds, res.findings
    assert res.verdict == "FAIL", (
        "an unreproducible verdict must not be folded into a pass — that is "
        "weakening the assertion to get green")
    f = [x for x in res.findings if x["kind"] == "NON_DETERMINISTIC_VERDICT"][0]
    assert "flaky" == f["gate"], f
    # both observations are carried, so a reader can see WHICH way it flapped
    assert "did not finish within 60s" in (f["checkout"] + f["worktree"]), f
    assert "second" in json.dumps(f).lower() or "reran" in json.dumps(f).lower()


def test_a_STABLE_disagreement_is_still_host_dependence(tmp_path):
    """THE PAIRED GUARD. The fix must not buy its green by making the probe
    unable to fire: a gate that really does read local state disagrees on
    EVERY round, and must still be caught."""
    r = _counter_repo(tmp_path, ignore_dat=True)
    (r / "leftover.dat").write_text("x\n")          # ignored: invisible stimulus
    res = G.audit(r, timeout=_T)

    kinds = [f["kind"] for f in res.findings]
    assert "HOST_DEPENDENT_VERDICT" in kinds, res.findings
    assert res.verdict == "FAIL", res


def test_the_reproduce_step_costs_nothing_when_the_arms_AGREE(tmp_path):
    """A gate that agrees is driven exactly twice, not four times.

    The probe already takes ~44 min over 66 gates; paying the re-drive on the
    agreeing majority would be a real cost for no information.
    """
    marker = tmp_path / "calls.txt"
    r = _repo_with(tmp_path, 'run "agreeable" "$ROOT" python3 agreeable.py\n',
                   untracked=True)
    (r / "agreeable.py").write_text(
        "import pathlib\n"
        f"m = pathlib.Path({str(marker)!r})\n"
        "n = int(m.read_text()) if m.is_file() else 0\n"
        "m.write_text(str(n + 1))\n"
        "print('PASS (1 item examined)')\n")
    subprocess.run(["git", "-C", str(r), "add", "agreeable.py"], check=True)
    subprocess.run(["git", "-C", str(r), "commit", "-qm", "a"], check=True)

    G.audit(r, timeout=_T)
    assert marker.read_text() == "2", (
        f"an agreeing gate was driven {marker.read_text()} times, not 2")
