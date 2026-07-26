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
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROGRAMS))
import gate_host_independence_check as G  # noqa: E402

_REPO = _PROGRAMS.parents[3]


def _repo_with(tmp_path: Path, script_body: str, dirty: bool = False) -> Path:
    r = tmp_path / "r"
    (r / "tools" / "ci").mkdir(parents=True)
    (r / "tools" / "ci" / "repo_hygiene_gates.sh").write_text(script_body)
    subprocess.run(["git", "init", "-q", str(r)], check=True)
    for k, v in (("user.email", "t@t"), ("user.name", "t")):
        subprocess.run(["git", "-C", str(r), "config", k, v], check=True)
    subprocess.run(["git", "-C", str(r), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(r), "commit", "-qm", "base"], check=True)
    if dirty:
        (r / "stray.txt").write_text("x\n")
    return r


def test_a_dirty_checkout_is_refused_not_reported_as_findings(tmp_path):
    """THE ONE THAT BIT ME. The worktree is at HEAD, so every uncommitted edit
    reads as a difference — an in-progress version of this very program made
    the chip-agnostic guard report 1241 files against the worktree's 1240 and
    flagged itself as an unwired checker. Reporting those as host-dependence
    would be a probe that fires on its own author.

    Refused, not filtered: "the comparison could not be made" is its own state.
    """
    r = _repo_with(tmp_path, 'run "x" "$ROOT" python3 -c "print(1)"\n',
                   dirty=True)
    verdict, findings = G.audit(r)
    assert verdict == "DIRTY_CHECKOUT", (verdict, findings)
    assert findings and findings[0]["kind"] == "DIRTY_CHECKOUT"


def test_a_clean_tree_with_a_stable_gate_passes(tmp_path):
    r = _repo_with(tmp_path, 'run "stable" "$ROOT" python3 -c "print(\'PASS 1\')"\n')
    verdict, findings = G.audit(r)
    assert verdict == "PASS", findings


def test_a_gate_that_reads_untracked_state_is_caught(tmp_path):
    """THE POSITIVE CONTROL, reduced. A gate that counts files on DISK sees an
    ignored leftover in the checkout and not in the worktree — which is exactly
    what `cross_layer_reference_check` did with 46 cells against 23.

    The leftover is git-IGNORED on purpose, so the dirty-checkout guard does
    not fire first and mask the very thing being tested.
    """
    r = _repo_with(tmp_path,
                   'run "counter" "$ROOT" python3 counter.py\n')
    # A SCRIPT FILE, not `python3 -c "..."`: the expander splits on whitespace
    # exactly as the real gates need, so a quoted argument containing spaces
    # would be a fixture artefact rather than a property of the subject.
    (r / "counter.py").write_text(
        "import pathlib\n"
        "print('PASS', len(list(pathlib.Path('.').glob('*.dat'))))\n")
    subprocess.run(["git", "-C", str(r), "add", "counter.py"], check=True)
    subprocess.run(["git", "-C", str(r), "commit", "-qm", "counter"], check=True)
    (r / ".gitignore").write_text("*.dat\n")
    subprocess.run(["git", "-C", str(r), "add", ".gitignore"], check=True)
    subprocess.run(["git", "-C", str(r), "commit", "-qm", "ignore"], check=True)
    # ignored => the tree is CLEAN, but the file is on this disk only
    (r / "leftover.dat").write_text("x\n")
    assert not subprocess.run(["git", "-C", str(r), "status", "--porcelain"],
                              capture_output=True, text=True).stdout.strip()

    verdict, findings = G.audit(r)
    assert verdict == "FAIL", (verdict, findings)
    assert findings[0]["kind"] == "HOST_DEPENDENT_VERDICT"
    assert "checkout" in findings[0] and "worktree" in findings[0]


def test_an_empty_gate_list_is_NOT_a_pass(tmp_path):
    """This program's own denominator."""
    r = _repo_with(tmp_path, "# no gates\n")
    verdict, _ = G.audit(r)
    assert verdict == "NOTHING_SCANNED"


def test_the_cwd_token_is_preserved(tmp_path):
    """Dropped in a first version, which made every `$PLUGIN`-scoped gate fail
    to open its own relative path IN BOTH TREES and produced 9 identical-error
    "findings". A probe that reports a defect because it could not run the
    subject is worse than no probe."""
    gates = G.corpus_gates(_REPO / "tools" / "ci" / "repo_hygiene_gates.sh")
    assert gates, "no gates parsed from the real CI script"
    assert all(len(g) == 3 for g in gates), gates[:2]
    assert {g[1] for g in gates} <= {"$ROOT", "$PLUGIN"}, {g[1] for g in gates}
    assert any(g[1] == "$PLUGIN" for g in gates), "the $PLUGIN lane is untested"


def test_the_probe_never_probes_ITSELF(tmp_path):
    """SHIPPED AND CAUGHT BY CI. The gate list is unfiltered by design, so it
    contains this program — and running it inside the worktree runs it again,
    which creates another worktree, and so on.

    Locally it was MASKED: the working tree is permanently dirty, so the inner
    invocation returned DIRTY_CHECKOUT immediately and the recursion never
    happened. CI checks out clean, recursed, and hit the per-gate timeout.
    "It passed on my machine" was true and worthless.
    """
    r = _repo_with(
        tmp_path,
        'run "self" "$ROOT" python3 "$PG/gate_host_independence_check.py"\n'
        'run "other" "$ROOT" python3 counter.py\n')
    (r / "counter.py").write_text("print('PASS 0')\n")
    subprocess.run(["git", "-C", str(r), "add", "counter.py"], check=True)
    subprocess.run(["git", "-C", str(r), "commit", "-qm", "c"], check=True)

    # Both are parsed — the skip is at RUN time, so the list stays honest.
    assert len(G.corpus_gates(
        r / "tools" / "ci" / "repo_hygiene_gates.sh")) == 2
    verdict, findings = G.audit(r, timeout=60)
    assert verdict == "PASS", findings


def test_a_gate_that_cannot_be_driven_is_its_own_state_not_a_crash(tmp_path):
    """The other half of the same CI failure: the per-gate timeout was
    UNHANDLED, so a slow gate killed the probe with a traceback instead of
    reporting. A gate that cannot be driven is not host-dependence, and it is
    not a clean result either."""
    r = _repo_with(tmp_path, 'run "slow" "$ROOT" python3 sleeper.py\n')
    (r / "sleeper.py").write_text("import time\ntime.sleep(30)\n")
    subprocess.run(["git", "-C", str(r), "add", "sleeper.py"], check=True)
    subprocess.run(["git", "-C", str(r), "commit", "-qm", "s"], check=True)

    verdict, findings = G.audit(r, timeout=2)
    assert verdict == "FAIL", (verdict, findings)
    assert findings[0]["kind"] == "GATE_UNRUNNABLE", findings
    assert "TimeoutExpired" in findings[0]["detail"], findings


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

    verdict, findings = G.audit(r, timeout=120)
    assert verdict == "PASS", findings


def test_a_real_difference_still_survives_normalisation(tmp_path):
    """The paired half. Absorbing the path must not absorb the verdict: a gate
    whose COUNT differs between the trees is still caught."""
    r = _repo_with(tmp_path, 'run "counter" "$ROOT" python3 counter.py\n')
    (r / ".gitignore").write_text("*.dat\n")
    (r / "counter.py").write_text(
        "import pathlib\n"
        "print('PASS', len(list(pathlib.Path('.').glob('*.dat'))))\n")
    subprocess.run(["git", "-C", str(r), "add", "counter.py", ".gitignore"],
                   check=True)
    subprocess.run(["git", "-C", str(r), "commit", "-qm", "c"], check=True)
    (r / "leftover.dat").write_text("x\n")     # ignored => tree stays clean

    verdict, findings = G.audit(r, timeout=120)
    assert verdict == "FAIL", (verdict, findings)
    assert findings[0]["kind"] == "HOST_DEPENDENT_VERDICT"
