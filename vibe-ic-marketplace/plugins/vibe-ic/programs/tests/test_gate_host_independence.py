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
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROGRAMS))
import gate_host_independence_check as G  # noqa: E402
import gate_process_attestation as A  # noqa: E402

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

    A SCRIPT FILE, not `python3 -c "..."`: this fixture is about a gate that
    reads the disk, and an inline program would put the subject in the argv.
    Quoted arguments containing spaces are a real property of the declarations
    (`--marker "RULE 0"`) and are covered by their own tests below.
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


def test_pytest_parenthesized_minute_clock_is_not_semantic_output():
    """pytest adds this second duration spelling once the suite exceeds 60s."""
    a = G._verdict_line("108 passed in 64.11s (0:01:04)\n")
    b = G._verdict_line("108 passed in 66.28s (0:01:06)\n")
    assert a == b == "108 passed in <TIME>s"
    assert G._verdict_line("107 passed, 1 failed in 66.28s (0:01:06)") != a


def _script_with(tmp_path, body: str):
    p = tmp_path / "gates.sh"
    p.write_text("#!/usr/bin/env bash\n" + body, encoding="utf-8")
    return p


def test_539_the_exclusion_rule_BITES_on_a_remote_reaching_gate(tmp_path):
    """#539's rule, proved on a fixture that CONTAINS the thing it is about.

    A gate that requires a REMOTE cannot sit inside a two-invocation determinism
    comparison: its two answers can differ for a reason that is not in the
    commit, which is how v1.7.92 went red on a gate whose code is perfectly
    host-independent and green on the identical commit when re-run.

    This half is the NON-VACUITY PROOF for the half below, and it is why the two
    are separate now. They used to be one test that asserted the real script
    still CONTAINED a `--require-remote` gate, so the rule was only ever
    exercised while such a gate happened to exist. When the last one was deleted
    — `sync_image_version --report-upstream --require-remote` went with the image
    anchor it reported on — that test failed for the one reason a rule-checker
    must not: its subject was gone, not broken. A rule whose only exerciser is
    the tree it polices is a rule that stops being checked the moment the tree
    gets cleaner.
    """
    undeclared = _script_with(tmp_path, (
        'run "reaches a registry" "$ROOT" python3 x.py --require-remote\n'))
    gates = G.corpus_gates(undeclared)
    assert [g for g in gates if "--require-remote" in g.cmd], gates
    assert all(g.excluded is None for g in gates), (
        "the parser reported an exclusion nobody declared, so the real-script "
        "assertion below could pass on an unexcluded remote gate")

    declared = _script_with(tmp_path, (
        "# host-independence: EXCLUDE — resolves a tag on a remote registry, so "
        "two invocations can differ for a reason that is not in the commit\n"
        'run "reaches a registry" "$ROOT" python3 x.py --require-remote\n'))
    gates = G.corpus_gates(declared)
    assert gates and gates[0].excluded, gates
    assert len(gates[0].excluded) > 20, gates[0]


def test_539_every_remote_reaching_gate_in_the_real_script_is_EXCLUDED():
    """The same rule over the REAL script. Stated as a PROPERTY of the command,
    never as an expected list of labels — a hand-maintained roster here would be
    the second list this repo keeps removing, and it would not notice a NEW
    remote-reaching gate.

    ZERO is currently the true count, and it is PRINTED rather than passed over:
    "there are none" and "I did not look" must not read the same. The rule itself
    is proved to bite by the fixture test above, so an empty set here is a fact
    about the script and not a hole in the check.
    """
    gates = G.corpus_gates(_REPO / "tools" / "ci" / "repo_hygiene_gates.sh")
    assert gates, "the real script parsed to no gates at all — nothing was read"
    remote = [g for g in gates if "--require-remote" in g.cmd]
    print(f"host-independence: {len(remote)} remote-reaching gate(s) of "
          f"{len(gates)} in repo_hygiene_gates.sh")
    for g in remote:
        assert g.excluded is not None, (
            f"{g.label} reaches a remote and is still probed twice", g)
    for g in gates:
        if g.excluded is not None:
            # An exclusion with no reason is a silent one wearing a label.
            assert len(g.excluded) > 20, g
            assert "no reason given" not in g.excluded, g


def _preflight(tree: Path) -> subprocess.CompletedProcess:
    """Drive the REAL preflight over `tree`, with the env pinned identical."""
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [sys.executable, "-B", str(_PROGRAMS / "attestation_preflight_check.py"),
         str(tree), "--repo", str(tree)],
        capture_output=True, text=True, env=env, timeout=_T)


def test_the_attestation_PREFLIGHTs_subject_is_the_CHECKOUT_not_the_commit(
        tmp_path):
    """THE PREMISE OF ITS EXCLUSION, PROVED BY RUNNING IT — not asserted in a
    comment beside it.

    `attestation preflight` was declared at v1.12.39 without the directive its
    class had carried since v1.9.78, and at v1.13.52 it was the one gate the
    host-independence probe reported over the whole 140-gate probed set. It was
    reported inside the sweep as NON_DETERMINISTIC_VERDICT — `files_seen` is in
    its verdict line and the checkout kept growing under the probe's own drives
    (7531 -> 7579), so the two rounds hashed differently — and in isolation, on
    a quiet tree, as HOST_DEPENDENT_VERDICT on BOTH rounds. The second reading is
    the true one, and this test is why it is not a matter of opinion.

    ONE commit, ONE environment, TWO trees differing only by an IGNORED cache
    directory. If the verdict still moves, the subject is the checkout. Every
    other input the gate has is held equal, so nothing else can be the cause.

    THE EXCLUSION LIVES OR DIES HERE. If this gate is ever changed so that its
    verdict is a property of the COMMIT, these two arms agree, this test goes
    red, and the directive in `repo_hygiene_gates.sh` must be removed rather
    than kept out of habit. An exclusion whose premise nothing re-checks is the
    silently-shrinking population this probe exists to refuse, one gate at a
    time.
    """
    def _tree(name: str) -> Path:
        # THE SAME COMMIT in both trees, `.gitignore` included: the residue has
        # to be ignored rather than merely uncommitted, because an UNTRACKED
        # path is the probe's declared stimulus while an IGNORED one is the
        # thing `git status` cannot see — the 13-of-39 asymmetry this gate was
        # written from.
        r = _repo_with(tmp_path, "# not used by this test\n", name=name)
        (r / ".gitignore").write_text("__pycache__/\n")
        subprocess.run(["git", "-C", str(r), "add", ".gitignore"], check=True)
        subprocess.run(["git", "-C", str(r), "commit", "-qm", "ignore"],
                       check=True)
        return r

    clean, dirty = _tree("clean"), _tree("dirty")
    cache = dirty / "__pycache__"
    cache.mkdir()
    (cache / "m.cpython-310.pyc").write_bytes(b"\x00")
    assert _porcelain(dirty) == [], (
        "the residue must be INVISIBLE to git, or the trees differ in a way "
        "the probe would have refused rather than probed")

    a, b = _preflight(dirty), _preflight(clean)
    assert b.returncode == 0, ("the control arm must PASS, or the comparison "
                               "below proves nothing", b.stdout, b.stderr)
    assert a.returncode == 1, ("the residue arm must REFUSE", a.stdout, a.stderr)
    assert "measure itself" in a.stdout, a.stdout
    assert "attestable" in b.stdout, b.stdout


def test_the_checkout_subject_preflight_is_EXCLUDED_in_the_real_script():
    """And the rule is APPLIED where it matters, stated as a property of the
    command rather than as a roster of labels.

    The test above proves the premise; this one proves the premise is acted on.
    Neither alone is enough: a proved premise nobody applies leaves the probe
    failing on a gate that cannot pass it, and an applied exclusion with no
    proved premise is a gate waved through by a sentence.
    """
    gates = G.corpus_gates(_REPO / "tools" / "ci" / "repo_hygiene_gates.sh")
    assert gates, "the real script parsed to no gates at all — nothing was read"
    preflights = [g for g in gates
                  if "attestation_preflight_check.py" in g.cmd]
    print(f"host-independence: {len(preflights)} checkout-subject preflight "
          f"gate(s) of {len(gates)} in repo_hygiene_gates.sh")
    assert preflights, (
        "no gate invokes attestation_preflight_check.py any more — this rule's "
        "subject is GONE, not broken; delete the rule with the gate")
    for g in preflights:
        assert g.excluded is not None, (
            f"{g.label} reports on the CHECKOUT and is still probed twice; the "
            f"two arms are required to differ and the probe cannot pass it", g)
        assert "CHECKOUT" in g.excluded, g.excluded


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


def test_different_finding_identities_cannot_cancel_behind_the_same_count(
        tmp_path):
    """The two arms can fail equally while disagreeing about WHAT is wrong.

    Comparing only the final ``1 finding`` line and process rc turns that real
    host-dependent disagreement into PASS.  The finding identity set is part
    of the verdict, not diagnostic decoration.
    """
    r = _repo_with(
        tmp_path,
        'run "identity" "$ROOT" python3 identity.py\n',
        untracked=True)
    (r / "identity.py").write_text(
        "from pathlib import Path\n"
        "if Path('stray.txt').exists():\n"
        "    print('[FAIL] LOCAL_LEFTOVER')\n"
        "else:\n"
        "    print('[FAIL] PUBLISHED_TREE_ONLY')\n"
        "print('[FAIL] 1 finding')\n"
        "raise SystemExit(1)\n")
    subprocess.run(["git", "-C", str(r), "add", "identity.py"], check=True)
    subprocess.run(["git", "-C", str(r), "commit", "-qm", "identity"],
                   check=True)

    res = G.audit(r, timeout=_T)
    assert res.verdict == "FAIL", res
    assert any(f["kind"] == "HOST_DEPENDENT_VERDICT"
               for f in res.findings), res.findings


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
# clock. `_OUTCOME_TIMEOUT_S = 60` in `test_flow_matrix_coverage` is a bound on
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


def test_the_outer_checkout_attestation_replaces_the_duplicate_arm_A(tmp_path):
    """Outer hygiene already ran A; host comparison launches only fresh B."""
    calls = tmp_path / "calls.txt"
    r = _repo_with(tmp_path, 'run "agreeable" "$ROOT" python3 agreeable.py\n',
                   untracked=True)
    (r / "agreeable.py").write_text(
        "from pathlib import Path\n"
        f"p=Path({str(calls)!r})\n"
        "p.write_text(str(int(p.read_text()) + 1) if p.exists() else '1')\n"
        "print('[PASS] 1 item examined')\n")
    subprocess.run(["git", "-C", str(r), "add", "agreeable.py"], check=True)
    subprocess.run(["git", "-C", str(r), "commit", "-qm", "agreeable"],
                   check=True)
    argv = G._expand('python3 agreeable.py', r)
    record = A.process_attestation(
        "agreeable", "[PASS] 1 item examined\n", 0, argv, roots=(r,))
    attestations = tmp_path / "outer.jsonl"
    A.append_private_jsonl(attestations, record)

    res = G.audit(r, timeout=_T, checkout_attestations=attestations)
    assert res.verdict == "PASS", res
    assert calls.read_text() == "1", (
        "the host probe reran checkout Arm A instead of consuming the exact "
        "outer process attestation")


def test_main_reads_the_dispatchers_attestation_channel(tmp_path, monkeypatch):
    """The shell declaration need not expose a run-specific variable.

    ``GATE_DISPATCH_ATTESTATION_FILE`` is a dispatcher-owned environment
    channel, not a loop binding.  Reading it at the program boundary prevents
    declaration readers from classifying this repo-wide gate as per-corpus.
    """
    inherited = tmp_path / "outer.jsonl"
    inherited.write_text("", encoding="utf-8")
    seen = {}

    def fake_parallel(root, jobs, checkout_attestations):
        seen.update(root=root, jobs=jobs,
                    checkout_attestations=checkout_attestations)
        return G.Audit("PASS", [], G.Dirt([], ["stimulus"], [], True),
                       1, 1, [])

    monkeypatch.setenv("GATE_DISPATCH_ATTESTATION_FILE", str(inherited))
    monkeypatch.setattr(G, "parallel_audit", fake_parallel)

    assert G.main([str(tmp_path), "--jobs", "2"]) == 0
    assert seen["checkout_attestations"] == inherited
    assert seen["jobs"] == 2


def test_explicit_attestation_path_overrides_the_dispatcher_channel(
        tmp_path, monkeypatch):
    inherited = tmp_path / "inherited.jsonl"
    explicit = tmp_path / "explicit.jsonl"
    inherited.write_text("", encoding="utf-8")
    explicit.write_text("", encoding="utf-8")
    seen = {}

    def fake_parallel(root, jobs, checkout_attestations):
        seen["checkout_attestations"] = checkout_attestations
        return G.Audit("PASS", [], G.Dirt([], ["stimulus"], [], True),
                       1, 1, [])

    monkeypatch.setenv("GATE_DISPATCH_ATTESTATION_FILE", str(inherited))
    monkeypatch.setattr(G, "parallel_audit", fake_parallel)

    assert G.main([str(tmp_path), "--jobs", "2",
                   "--checkout-attestations", str(explicit)]) == 0
    assert seen["checkout_attestations"] == explicit


def test_a_missing_checkout_attestation_is_a_named_refusal(tmp_path):
    r = _repo_with(tmp_path, 'run "x" "$ROOT" python3 x.py\n',
                   untracked=True)
    (r / "x.py").write_text("print('[PASS] 1 item examined')\n")
    subprocess.run(["git", "-C", str(r), "add", "x.py"], check=True)
    subprocess.run(["git", "-C", str(r), "commit", "-qm", "x"], check=True)
    att = tmp_path / "outer.jsonl"
    A.append_private_jsonl(att, A.process_attestation(
        "some other gate", "[PASS] 1 item examined\n", 0,
        ["python3", "other.py"], roots=(r,)))

    res = G.audit(r, timeout=_T, checkout_attestations=att)
    assert res.verdict == "FAIL", res
    assert any(f["kind"] == "CHECKOUT_ATTESTATION_MISSING"
               for f in res.findings), res.findings


def test_reused_and_fresh_arms_preserve_the_same_stdout_stderr_order(tmp_path):
    """The outer ``2>&1 | tee`` stream and fresh arm are one instrument.

    With piped Python output, stderr is unbuffered while stdout flushes at
    exit.  Capturing them separately and concatenating stdout first reverses
    the observed order and manufactures a one-round disagreement.
    """
    r = _repo_with(tmp_path, 'run "mixed" "$ROOT" python3 mixed.py\n',
                   untracked=True)
    (r / "mixed.py").write_text(
        "import sys\n"
        "print('[PASS] 1 item examined')\n"
        "print('diagnostic on stderr', file=sys.stderr)\n")
    subprocess.run(["git", "-C", str(r), "add", "mixed.py"], check=True)
    subprocess.run(["git", "-C", str(r), "commit", "-qm", "mixed"],
                   check=True)
    argv = G._expand("python3 mixed.py", r)
    proc = subprocess.run(
        argv, cwd=r, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, check=False)
    att = tmp_path / "outer.jsonl"
    A.append_private_jsonl(att, A.process_attestation(
        "mixed", proc.stdout, proc.returncode, argv, roots=(r,)))

    res = G.audit(r, timeout=_T, checkout_attestations=att)
    assert res.verdict == "PASS", res
    assert not res.findings, res.findings


# ── one ruler for both arms (#gate-host-independence, 2026-08-25) ────────────
# Arm A can be a PRECOMPUTED record written by `_gate_dispatch.sh`, which
# normalises against `$ROOT`, `$wd` AND `$VIBE_IC_BENCHMARK_DATA`. This probe
# normalised against only the two trees, so a gate that NAMES the corpus in its
# verdict produced `<TREE>/ic` on one side and `/corpus/ic` on the other from
# the SAME bytes — a disagreement manufactured entirely by the comparison.
#
# MEASURED on v1.11.77 with the corpus bound at /corpus: inside the hygiene run
# the probe reported `6 of 92 ... NON_DETERMINISTIC_VERDICT`, all six being
# corpus-naming gates (one of them `rc=0 PASS` on all four drives); driving both
# arms from this probe, one normaliser for both, returned `[PASS] all 92`.
#
# Both tests below FAIL against the pre-fix module (roots=(repo_root, wt)) —
# that is this pair's mutation control.

_DISPATCH_LINE = ("[NOT CHECKED] cross_layer_reference_check --corpus: no "
                  "published cell under /corpus/ic carries phase1/generated_docs")


def test_the_corpus_pointer_is_in_the_comparison_vocabulary(monkeypatch,
                                                            tmp_path):
    """The dispatch's third --root must be one this probe also erases."""
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    monkeypatch.setenv("VIBE_IC_BENCHMARK_DATA", str(corpus))
    roots = G._compare_roots(tmp_path / "repo", tmp_path / "wt")
    assert corpus in roots, "the corpus pointer is not part of the comparison"
    line = f"[NOT CHECKED] no published cell under {corpus}/ic carries x"
    assert str(corpus) not in G._norm(line, tmp_path / "repo", tmp_path / "wt")


def test_two_arms_normalised_by_the_two_writers_agree(monkeypatch, tmp_path):
    """The real shape: the dispatch record and this probe's own drive.

    The dispatch erases the corpus root; the probe must reach the same
    `semantic_sha256` for byte-identical output, or every corpus-naming gate
    reads as non-deterministic.
    """
    repo, wt, corpus = tmp_path / "repo", tmp_path / "wt", tmp_path / "corpus"
    for d in (repo, wt, corpus):
        d.mkdir()
    out = f"[NOT CHECKED] no published cell under {corpus}/ic carries docs"
    monkeypatch.setenv("VIBE_IC_BENCHMARK_DATA", str(corpus))

    dispatch = A.semantic_record(out, 2, roots=(repo, wt, corpus))   # Arm A
    probe = A.semantic_record(out, 2, roots=G._compare_roots(repo, wt))
    assert probe["semantic_sha256"] == dispatch["semantic_sha256"]

    # ...and the vocabulary that caused it still disagrees, so this test is
    # measuring the fix rather than an accident of the fixture.
    old = A.semantic_record(out, 2, roots=(repo, wt))
    assert old["semantic_sha256"] != dispatch["semantic_sha256"]


def test_an_unset_pointer_leaves_the_vocabulary_unchanged(monkeypatch,
                                                          tmp_path):
    """No corpus bound is not an empty corpus root: a blank must not be added,
    or `_replace_roots` would be handed "" and the guard is what stops it."""
    monkeypatch.delenv("VIBE_IC_BENCHMARK_DATA", raising=False)
    assert G._compare_roots(tmp_path / "a", tmp_path / "b") == (
        tmp_path / "a", tmp_path / "b")
    monkeypatch.setenv("VIBE_IC_BENCHMARK_DATA", "   ")
    assert G._compare_roots(tmp_path / "a", tmp_path / "b") == (
        tmp_path / "a", tmp_path / "b")


# --------------------------------------------------------------------------
# THE ARGV IS RECONSTRUCTED THE WAY THE SHELL BUILDS IT, AND NORMALISED WITH
# THE RULER THE PRODUCER USED
#
# Both were measured on 58514abe8, isolated, 3 runs of 3: three declared gates
# reported `CHECKOUT_ATTESTATION_WRONG_COMMAND` while both sides held the
# identical command. Two of them carry a quoted multi-word argument; the third
# is the first probed gate to combine cwd `$PLUGIN` with an absolute `$PG/`
# path. Neither declaration is wrong — the probe's reconstruction was.
# --------------------------------------------------------------------------
def _attest_the_dispatcher_way(path: Path, label: str, output: str,
                               argv: list, root: Path, wd: Path) -> None:
    """Arm A exactly as `_gate_dispatch.sh` writes it: `--root ROOT --root wd`."""
    A.append_private_jsonl(path, A.process_attestation(
        label, output, 0, argv, roots=(root, wd)))


def test_a_quoted_multiword_argument_stays_ONE_argument(tmp_path):
    r = _repo_with(
        tmp_path,
        'run "marked" "$ROOT" python3 marked.py --marker "RULE 0"\n',
        untracked=True)
    (r / "marked.py").write_text("print('[PASS] 1 item examined')\n")
    subprocess.run(["git", "-C", str(r), "add", "marked.py"], check=True)
    subprocess.run(["git", "-C", str(r), "commit", "-qm", "marked"], check=True)

    real = ["python3", "marked.py", "--marker", "RULE 0"]
    assert G._expand('python3 marked.py --marker "RULE 0"', r) == real, (
        "the reconstruction split a quoted argument the shell keeps whole")

    att = tmp_path / "outer.jsonl"
    _attest_the_dispatcher_way(att, "marked", "[PASS] 1 item examined\n",
                               real, r, r)
    res = G.audit(r, timeout=_T, checkout_attestations=att)
    assert res.verdict == "PASS", res.findings


def test_a_RECORD_FOR_A_DIFFERENT_COMMAND_IS_STILL_REFUSED(tmp_path):
    """The control for the test above: the check must still be able to say no."""
    r = _repo_with(
        tmp_path,
        'run "marked" "$ROOT" python3 marked.py --marker "RULE 0"\n',
        untracked=True)
    (r / "marked.py").write_text("print('[PASS] 1 item examined')\n")
    subprocess.run(["git", "-C", str(r), "add", "marked.py"], check=True)
    subprocess.run(["git", "-C", str(r), "commit", "-qm", "marked"], check=True)

    att = tmp_path / "outer.jsonl"
    _attest_the_dispatcher_way(
        att, "marked", "[PASS] 1 item examined\n",
        ["python3", "marked.py", "--marker", "RULE 0", "--and-one-more"], r, r)
    res = G.audit(r, timeout=_T, checkout_attestations=att)
    assert res.verdict == "FAIL", res
    assert [f["kind"] for f in res.findings] == [
        "CHECKOUT_ATTESTATION_WRONG_COMMAND"], res.findings


def _plugin_scoped_repo(tmp_path: Path) -> Path:
    r = tmp_path / "p"
    plug = r / "vibe-ic-marketplace" / "plugins" / "vibe-ic"
    (plug / "programs").mkdir(parents=True)
    (r / "tools" / "ci").mkdir(parents=True)
    (r / "tools" / "ci" / "repo_hygiene_gates.sh").write_text(
        'run "plugin-scoped" "$PLUGIN" python3 "$PG/subject_check.py"\n')
    (plug / "programs" / "subject_check.py").write_text(
        "print('[PASS] 1 item examined')\n")
    subprocess.run(["git", "init", "-q", str(r)], check=True)
    for k, v in (("user.email", "t@t"), ("user.name", "t")):
        subprocess.run(["git", "-C", str(r), "config", k, v], check=True)
    subprocess.run(["git", "-C", str(r), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(r), "commit", "-qm", "base"], check=True)
    (r / "stray.txt").write_text("x\n")
    return r


def test_a_PLUGIN_scoped_gates_absolute_argv_is_not_a_wrong_command(tmp_path):
    r = _plugin_scoped_repo(tmp_path)
    plug = r / "vibe-ic-marketplace" / "plugins" / "vibe-ic"
    real = ["python3", str(plug / "programs" / "subject_check.py")]
    assert G._expand('python3 "$PG/subject_check.py"', r) == real

    # NOT VACUOUS: the two vocabularies really do disagree about these bytes,
    # which is the whole defect. `<TREE>/programs/x.py` against
    # `<TREE>/vibe-ic-marketplace/plugins/vibe-ic/programs/x.py`.
    assert (A.argv_sha256(real, roots=(r, plug))
            != A.argv_sha256(real, roots=(r,))), (
        "fixture no longer exercises the two-ruler case")

    att = tmp_path / "outer.jsonl"
    _attest_the_dispatcher_way(att, "plugin-scoped",
                               "[PASS] 1 item examined\n", real, r, plug)
    res = G.audit(r, timeout=_T, checkout_attestations=att)
    assert res.verdict == "PASS", res.findings


def test_a_declaration_the_shell_cannot_split_is_NAMED_not_a_crash(tmp_path):
    r = _repo_with(tmp_path, 'run "ragged" "$ROOT" python3 ragged.py --m "x\n',
                   untracked=True)
    (r / "ragged.py").write_text("print('[PASS] 1 item examined')\n")
    subprocess.run(["git", "-C", str(r), "add", "ragged.py"], check=True)
    subprocess.run(["git", "-C", str(r), "commit", "-qm", "ragged"], check=True)

    res = G.audit(r, timeout=_T)
    assert res.verdict == "FAIL", res
    assert [f["kind"] for f in res.findings] == ["GATE_UNRUNNABLE"], res.findings


# --------------------------------------------------------------------------
# THE POINTER ARM — a verdict that is a function of an invisible env pointer
# --------------------------------------------------------------------------
def _pointer_repo(tmp_path: Path, body: str, *, name: str = "r") -> Path:
    """A repo whose ONE gate reads `VIBE_IC_BENCHMARK_DATA` and nothing else.

    The reduced form of the 63x8 census checker, which returned rc 0 with the
    corpus withheld and rc 1 `census block is stale` with it bound, at one commit,
    in one tree — a verdict decided by a variable that appears in no argv.

    `untracked=True` because the two-tree half of this probe reports NO_STIMULUS
    over two identical trees, and a fixture that landed there would be measuring
    the wrong refusal.
    """
    r = _repo_with(tmp_path, 'run "ptr" "$ROOT" python3 ptr.py\n',
                   untracked=True, name=name)
    (r / "ptr.py").write_text(body)
    subprocess.run(["git", "-C", str(r), "add", "ptr.py"], check=True)
    subprocess.run(["git", "-C", str(r), "commit", "-qm", "ptr"], check=True)
    return r


#: PASS with the pointer withheld, FAIL with it bound. The census defect, reduced.
_FLIPS = (
    "import os, sys\n"
    "bound = bool(os.environ.get('VIBE_IC_BENCHMARK_DATA'))\n"
    "print('FAIL stale' if bound else 'PASS fresh')\n"
    "sys.exit(1 if bound else 0)\n"
)

#: Reports DIFFERENTLY with and without the corpus and stays a PASS. This is the
#: honest shape every corpus-reading gate has, and the arm must not fire on it.
_REPORTS_DIFFERENTLY = (
    "import os\n"
    "bound = bool(os.environ.get('VIBE_IC_BENCHMARK_DATA'))\n"
    "print('PASS 4 cell(s)' if bound else 'PASS 0 cell(s), corpus not offered')\n"
)

#: PASS with the corpus, NOT_CHECKED (rc 2) without it. Also honest — it SAYS it
#: could not look — and rc 2 is never half of a flip.
_DECLINES_WITHOUT_CORPUS = (
    "import os, sys\n"
    "bound = bool(os.environ.get('VIBE_IC_BENCHMARK_DATA'))\n"
    "print('PASS 4 cell(s)' if bound else 'NOT_CHECKED: no corpus offered')\n"
    "sys.exit(0 if bound else 2)\n"
)


def test_a_verdict_that_flips_with_the_env_pointer_is_CAUGHT(tmp_path,
                                                             monkeypatch):
    """THE DEFECT THIS ARM WAS ADDED FOR, and the two-tree half cannot see it.

    Both existing arms inherit this process's environment, so this gate agrees
    with itself perfectly across a working checkout and a fresh worktree. Without
    the pointer arm the probe prints `[PASS] ... give the same verdict` over a
    gate whose answer is decided by a variable nobody can see in its argv.
    """
    monkeypatch.setenv(G.POINTER_ENV, str(tmp_path / "corpus"))
    r = _pointer_repo(tmp_path, _FLIPS)
    res = G.audit(r, timeout=_T, tmp_root=tmp_path, pointer_arm=True)
    assert res.verdict == "FAIL", res
    kinds = {f["kind"] for f in res.findings}
    assert kinds == {"ENV_POINTER_DEPENDENT_VERDICT"}, res.findings
    detail = res.findings[0]["detail"]
    assert "PASS" in detail and "FAIL" in detail and G.POINTER_ENV in detail
    assert res.pointer["probed"] == 1, res.pointer


def test_the_two_tree_half_alone_calls_that_gate_HOST_INDEPENDENT(tmp_path,
                                                                  monkeypatch):
    """The NEGATIVE CONTROL, and it is the reason the arm exists at all.

    With the pointer arm switched off, the identical fixture PASSES — both arms
    read the same environment, so they agree by construction. A test that cannot
    fail against the pre-fix code proves nothing, so this pins what the pre-fix
    code actually said.
    """
    monkeypatch.setenv(G.POINTER_ENV, str(tmp_path / "corpus"))
    monkeypatch.setattr(G, "pointer_arm_finding",
                        lambda *a, **k: None)   # the code before the arm
    r = _pointer_repo(tmp_path, _FLIPS)
    res = G.audit(r, timeout=_T, tmp_root=tmp_path, pointer_arm=True)
    assert res.verdict == "PASS", res
    assert res.findings == [], res.findings


def test_a_gate_that_merely_REPORTS_differently_is_not_a_finding(tmp_path,
                                                                 monkeypatch):
    """THE FALSE-POSITIVE CONTROL. Different words are not a different verdict.

    Every corpus-reading gate says something different with and without a corpus.
    Requiring its OUTPUT to be identical would report all of them, which is how a
    check that fires on legitimate code gets deleted rather than landed.
    """
    monkeypatch.setenv(G.POINTER_ENV, str(tmp_path / "corpus"))
    r = _pointer_repo(tmp_path, _REPORTS_DIFFERENTLY)
    res = G.audit(r, timeout=_T, tmp_root=tmp_path, pointer_arm=True)
    assert [f for f in res.findings
            if f["kind"] == "ENV_POINTER_DEPENDENT_VERDICT"] == [], res.findings
    assert res.pointer["probed"] == 1, res.pointer


def test_a_gate_that_DECLINES_without_the_corpus_is_not_a_flip(tmp_path,
                                                               monkeypatch):
    """rc 2 is the disclosed third state, never half of a PASS/FAIL flip.

    A gate that says "I could not look" without a corpus and PASSes with one has
    told the reader exactly which environment it was in. That is the shape this
    whole family is repaired TOWARDS; reporting it as the defect would punish the
    fix.
    """
    monkeypatch.setenv(G.POINTER_ENV, str(tmp_path / "corpus"))
    r = _pointer_repo(tmp_path, _DECLINES_WITHOUT_CORPUS)
    res = G.audit(r, timeout=_T, tmp_root=tmp_path, pointer_arm=True)
    assert [f for f in res.findings
            if f["kind"] == "ENV_POINTER_DEPENDENT_VERDICT"] == [], res.findings


def test_with_no_pointer_bound_the_arm_is_NOT_CHECKED_and_says_so(
        tmp_path, monkeypatch, capsys):
    """No corpus named means no second environment, and that is not coverage.

    The arm can only toggle bound -> withheld: building a "present" environment
    out of nothing would mean inventing a corpus. So the run reports a pointer
    denominator of zero and the verdict line names it, rather than printing the
    same sentence a fully-probed run prints.
    """
    monkeypatch.delenv(G.POINTER_ENV, raising=False)
    r = _pointer_repo(tmp_path, _FLIPS)
    res = G.audit(r, timeout=_T, tmp_root=tmp_path, pointer_arm=True)
    assert res.verdict == "PASS", res
    assert res.pointer == {"bound": "", "probed": 0, "not_probed": []}, res.pointer
    G.main([str(r)])
    err = capsys.readouterr().err
    assert f"{G.POINTER_ENV} arm NOT CHECKED" in err, err


def test_the_pointer_arm_restores_the_environment_it_toggled(tmp_path,
                                                             monkeypatch):
    """A probe that leaked a changed environment would BE the defect it hunts.

    Every gate declared after the one being toggled would be driven under the
    wrong environment, and the probe would report their difference as theirs.
    """
    monkeypatch.setenv(G.POINTER_ENV, str(tmp_path / "corpus"))
    r = _pointer_repo(tmp_path, _FLIPS)
    G.audit(r, timeout=_T, tmp_root=tmp_path, pointer_arm=True)
    assert os.environ.get(G.POINTER_ENV) == str(tmp_path / "corpus")


def test_the_pointer_denominator_is_published_in_the_machine_record(tmp_path,
                                                                    monkeypatch):
    """A consumer that cannot read the denominator has to infer it, and will."""
    monkeypatch.setenv(G.POINTER_ENV, str(tmp_path / "corpus"))
    r = _pointer_repo(tmp_path, _REPORTS_DIFFERENTLY)
    doc = G._audit_doc(G.audit(r, timeout=_T, tmp_root=tmp_path, pointer_arm=True))
    assert doc["pointer_arm"]["probed"] == 1, doc["pointer_arm"]
    assert doc["pointer_arm"]["bound"] == str(tmp_path / "corpus")
