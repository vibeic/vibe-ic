#!/usr/bin/env python3
"""Guard the judge-set check itself.

The check answers one question — *did this candidate change the code that judges
it?* — by DERIVING the judge set from what the verifier executes, rather than
reading a hand-maintained register. These cases pin the properties that make
that derivation trustworthy, because a derivation that quietly returns less is
worse than the list it replaced: every landing would pass and nobody would know.

WHY THESE CASES LOOK EXPENSIVE.  The first version of this file had five cases
and three of them stayed GREEN when the thing they were named after was deleted:

  * the refusal test asserted `returncode in (0, 1)` and put its only
    substantive assertion inside `if returncode == 1:`, which never ran — so
    `if unauthorised:` -> `if False:` passed 5/5;
  * the authorisation test drove `--base HEAD --head HEAD`, an EMPTY diff, so
    `--authorised` was never exercised — making the flag a total no-op passed
    5/5;
  * the reproducibility test derived twice IN ONE PROCESS on ONE checkout, so it
    could only ever catch intra-process nondeterminism, never the
    checkout-dependence its name disclaimed.

Each of those is now driven against a REAL adversarial commit built on disk, and
each asserts an EXACT exit code. `rc != 0` is not an assertion here: a check
demoted from rc 1 to rc 2 once passed 362 tests that used it, because rc 2
satisfies it too.

AND THE CANARY.  Disabling shell-invocation following collapsed the set from 255
to 2 — a 99.2% loss — and all five original cases stayed green, because the only
membership floor was the two SEEDS and the seeds are the LAST members to
disappear. That makes them the worst possible canary. The floor below therefore
names DEEP members, each reached by a different mechanism, plus a size floor.
"""
from __future__ import annotations
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
CHECK = REPO / "tools" / "ci" / "judge_set_check.py"

#: Members that any honest derivation must reach, chosen so that no single
#: narrowing of the walk can leave the floor intact. Each line names the
#: mechanism it dies with.
FLOOR = (
    # reached by a BARE `tools/...` token in shell — dies if shell-invocation
    # following is disabled at all
    "tools/ci/repo_hygiene_gates.sh",
    "tools/ci/_gate_dispatch.sh",
    # reached ONLY through a `$VAR/...`-rooted token — dies if the tokenizer
    # goes back to matching by prefix, which is how 12 files the judges execute
    # sat outside the set
    "tools/ci/run_plugin_self_audit.sh",
    "vibe-ic-marketplace/tools/program_reachability_check.py",
    # reached by PYTHON IMPORT several hops in — dies if import following stops
    "vibe-ic-marketplace/plugins/vibe-ic/programs/spec_artifact_registry.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/landing_merge_verdict.py",
)
#: A SHRINK DETECTOR, not a bound: it sits far below the 267 measured on
#: 2026-08-28 so that ordinary movement never touches it, and it exists because
#: the canary mutation took the set to 2 with every named member still present
#: in a narrower walk. Never lower this to accommodate a smaller set; a smaller
#: set is the finding.
FLOOR_SIZE = 200


@pytest.fixture(scope="module")
def judges():
    """Derived once: the walk costs ~2.7s and three cases want the same answer."""
    return _mod().judge_set_at(REPO, "HEAD")


def _mod():
    spec = importlib.util.spec_from_file_location("_jsc", CHECK)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _run(*args, repo=None):
    return subprocess.run(
        [sys.executable, str(CHECK), "--repo", str(repo or REPO), *args],
        capture_output=True, text=True)


def _clone(dest: Path, source: Path = REPO) -> Path:
    """A real, separate checkout — not a worktree of the caller's tree."""
    subprocess.run(["git", "clone", "-q", "--no-hardlinks", str(source), str(dest)],
                   check=True, capture_output=True)
    for k, v in (("user.email", "test@example.invalid"), ("user.name", "test")):
        subprocess.run(["git", "-C", str(dest), "config", k, v], check=True)
    return dest


def _commit(repo: Path, message: str) -> None:
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", message], check=True)


# --------------------------------------------------------------------------
# fixtures: adversarial candidates, built on disk, one clone each
# --------------------------------------------------------------------------

@pytest.fixture(scope="module")
def touches_a_judge(tmp_path_factory):
    """A candidate that edits a file the verifier demonstrably executes.

    `run_plugin_self_audit.sh` is chosen deliberately: a comment inside it calls
    it the home of six anti-fabrication gates, and it was OUTSIDE the derived set
    until the tokenizer learned `$VAR/...`.
    """
    repo = _clone(tmp_path_factory.mktemp("touch") / "r")
    victim = repo / "tools" / "ci" / "run_plugin_self_audit.sh"
    victim.write_text(victim.read_text() + "\n# a candidate edited a judge\n")
    _commit(repo, "candidate: edit a gate the verifier runs")
    return repo


@pytest.fixture(scope="module")
def renames_the_hub(tmp_path_factory):
    """A candidate that moves an ENTRY POINT and touches nothing else.

    Every member hangs off the entry points, so this one commit takes the set
    from 267 to 221 and the 46 it drops include the whole
    `gatekeeper-verify-merge.sh` subtree. The empty-set guard cannot see it: the
    set is not empty, it is smaller. Nothing else is edited, so the ONLY thing
    that can catch it is the shrink ratchet.
    """
    repo = _clone(tmp_path_factory.mktemp("hub") / "r")
    subprocess.run(["git", "-C", str(repo), "mv",
                    "tools/gatekeeper-verify-merge.sh",
                    "tools/gatekeeper-verify-merge-v2.sh"], check=True)
    _commit(repo, "candidate: rename an entry point, touch nothing else")
    return repo


@pytest.fixture(scope="module")
def grows_the_set(tmp_path_factory):
    """A candidate that TIGHTENS: it adds a gate and wires it in.

    The asymmetry is the point. A ratchet that goes red when somebody makes the
    thing stricter is a ratchet people learn to route around, so growth must be
    allowed while loss is refused.
    """
    repo = _clone(tmp_path_factory.mktemp("grow") / "r")
    (repo / "tools" / "ci" / "brand_new_gate.sh").write_text("#!/usr/bin/env bash\n")
    hub = repo / "tools" / "ci" / "repo_hygiene_gates.sh"
    hub.write_text(hub.read_text() + '\nbash "$ROOT/tools/ci/brand_new_gate.sh"\n')
    _commit(repo, "candidate: add a gate and wire it in")
    return repo


@pytest.fixture(scope="module")
def shallow(tmp_path_factory):
    """A clone that does not CONTAIN the base commit. This is the default shape
    of a CI checkout, and it made the check pass every landing."""
    dest = tmp_path_factory.mktemp("shallow") / "r"
    subprocess.run(["git", "clone", "-q", "--no-hardlinks", "--depth", "1",
                    f"file://{REPO}", str(dest)], check=True, capture_output=True)
    return dest


# --------------------------------------------------------------------------
# G1 — non-vacuity of the derivation itself
# --------------------------------------------------------------------------

def test_the_derived_set_reaches_deep_and_not_only_the_entry_points(judges):
    """The canary that used to be the last thing to die.

    Naming only the two seeds was worthless: disabling shell-invocation
    following left the set at exactly the two seeds and this case stayed green
    while 99.2% of the judges vanished. Every member below is several hops in,
    and the three mechanisms (bare token, `$VAR`-rooted token, python import)
    are covered separately so no single narrowing passes.
    """
    assert judges, "the judge set derived EMPTY — every landing would pass"
    for must in ("tools/gatekeeper-land.sh", "tools/gatekeeper-verify-merge.sh"):
        assert must in judges, (
            f"{must} is not in the derived judge set, so a candidate could "
            f"rewrite the lander and this check would not notice")
    missing = [m for m in FLOOR if m not in judges]
    assert not missing, (
        f"the derivation no longer reaches {missing}. Each floor member is "
        f"reached by a different mechanism; a missing one names which half of "
        f"the walk stopped working. Set size was {len(judges)}.")
    assert len(judges) >= FLOOR_SIZE, (
        f"the judge set derived {len(judges)} members, below the {FLOOR_SIZE} "
        f"shrink-detector floor. This is a finding, not a number to lower.")


def test_the_tokenizer_recovers_shell_variable_rooted_paths(judges):
    """`"$ROOT/tools/ci/x.sh"` is the DOMINANT spelling in this repository.

    Matching by prefix after `lstrip("$")` saw `tools/...` and `$tools/...` and
    nothing else, so twelve files the judges execute were outside the set —
    among them the self-audit hub, the reachability checker, and three
    generators. MEASURED 2026-08-28: 255 -> 267, twelve gained, zero lost.
    """
    for must in ("tools/ci/run_plugin_self_audit.sh",
                 "vibe-ic-marketplace/tools/program_reachability_check.py",
                 "tools/gen_programs_index.py",
                 "tools/gen_engineering_evidence.py",
                 "tools/liar_census.py"):
        assert must in judges, (
            f"{must} is executed by the shell judges but is not in the derived "
            f"set — the tokenizer has stopped following `$VAR/...` paths")


def test_both_spellings_of_a_variable_rooted_path_are_recovered():
    """`$ROOT/...` and `${ROOT}/...` must normalise the same way, and a bare
    path must keep working — the fix is a UNION, so it can only add members."""
    cands = _mod()._shell_path_candidates
    assert "tools/ci/x.sh" in cands("$ROOT/tools/ci/x.sh")
    assert "tools/ci/x.sh" in cands("${RUNTIME_ROOT}/tools/ci/x.sh")
    assert "tools/ci/x.sh" in cands("$A/$B/tools/ci/x.sh")
    assert "tools/ci/x.sh" in cands("tools/ci/x.sh")
    assert "tools/ci/x.sh" in cands("$tools/ci/x.sh"), (
        "the pre-existing `lstrip('$')` normalisation was dropped, so this is "
        "a REPLACEMENT rather than the union it is documented to be")


# --------------------------------------------------------------------------
# G2 — the refusal, driven against a real candidate
# --------------------------------------------------------------------------

def test_it_refuses_a_candidate_that_touches_a_judge(touches_a_judge):
    """The whole point, and the case that used to assert nothing.

    Driven against a commit built for it, so the refusal branch is REACHED. The
    exit code is asserted exactly: `in (0, 1)` accepted the passing answer, and
    `!= 0` would accept a check silently demoted to rc 2.
    """
    cp = _run("--base", "HEAD~1", "--head", "HEAD", repo=touches_a_judge)
    assert cp.returncode == 1, (cp.returncode, cp.stdout, cp.stderr)
    assert "REFUSE" in cp.stdout, cp.stdout
    assert "tools/ci/run_plugin_self_audit.sh" in cp.stdout, (
        "the refusal did not NAME the judge the candidate touched")


def test_it_refuses_a_candidate_that_removes_a_judge(renames_the_hub):
    """A set that SHRANK is the failure the empty-set guard cannot see.

    This candidate edits nothing — it only moves an entry point — so a check
    that merely intersects the diff with the surviving set has nothing to find.
    """
    cp = _run("--base", "HEAD~1", "--head", "HEAD", repo=renames_the_hub)
    assert cp.returncode == 1, (cp.returncode, cp.stdout, cp.stderr)
    assert "REMOVES" in cp.stdout, cp.stdout
    assert "tools/gatekeeper-verify-merge.sh" in cp.stdout, cp.stdout
    assert "AN ENTRY POINT" in cp.stdout, (
        "the refusal did not say that the lost file was an entry point, which "
        "is the fact that explains why 46 others went with it")


@pytest.fixture(scope="module")
def deletes_both_entry_points(tmp_path_factory):
    repo = _clone(tmp_path_factory.mktemp("doors") / "r")
    subprocess.run(["git", "-C", str(repo), "rm", "-q",
                    "tools/gatekeeper-verify-merge.sh",
                    "tools/gatekeeper-land.sh"], check=True)
    _commit(repo, "candidate: delete both entry points")
    return repo


def test_deleting_both_entry_points_is_the_candidates_fault_not_the_environments(
        deletes_both_entry_points):
    """The head set is EMPTY here, and that must still be rc 1.

    An empty derivation with the seeds present is a broken checker (rc 2, "I
    could not look"). An empty derivation because the candidate DELETED the
    seeds is a verdict about the candidate (rc 1). Folding the second into the
    first would let a candidate reach the tolerated non-verdict by deleting the
    judges, which is the strongest possible version of this whole defect.
    """
    m = _mod()
    assert m.judge_set_at(deletes_both_entry_points, "HEAD") == set()
    cp = _run("--base", "HEAD~1", "--head", "HEAD", repo=deletes_both_entry_points)
    assert cp.returncode == 1, (cp.returncode, cp.stdout, cp.stderr)
    assert "REMOVES" in cp.stdout, cp.stdout
    for door in ("tools/gatekeeper-verify-merge.sh", "tools/gatekeeper-land.sh"):
        assert door in cp.stdout, cp.stdout


def test_growing_the_judge_set_is_allowed(grows_the_set):
    """The ratchet asymmetry, driven.

    A candidate that adds a gate and wires it in gains a member and loses none.
    It still has to authorise the two files it EDITED — that is review, not the
    ratchet — and once it does, the shrink branch must stay silent.
    """
    m = _mod()
    base = m.judge_set_at(grows_the_set, "HEAD~1")
    head = m.judge_set_at(grows_the_set, "HEAD")
    assert head - base, "the fixture did not actually grow the set"
    assert not base - head, f"the fixture lost members: {sorted(base - head)}"
    cp = _run("--base", "HEAD~1", "--head", "HEAD",
              "--authorised", "tools/ci/repo_hygiene_gates.sh",
              "--authorised", "tools/ci/brand_new_gate.sh", repo=grows_the_set)
    assert cp.returncode == 0, (cp.returncode, cp.stdout, cp.stderr)
    assert "REMOVES" not in cp.stdout, (
        "growth was reported as a shrink; a ratchet that fires when somebody "
        "tightens the thing is one people route around")


# --------------------------------------------------------------------------
# G3 — authorisation, with its control
# --------------------------------------------------------------------------

def test_authorising_a_path_lets_it_through_and_says_so(touches_a_judge):
    """A refusal a human has read must be expressible, or the check gets
    bypassed instead of answered.

    Driven over a NON-EMPTY diff. The old version used `--base HEAD --head
    HEAD`, so `touched` was empty and making `--authorised` a total no-op
    passed. It also never read stdout, leaving the "and says so" half of its
    own name unmeasured.
    """
    cp = _run("--base", "HEAD~1", "--head", "HEAD",
              "--authorised", "tools/ci/run_plugin_self_audit.sh",
              repo=touches_a_judge)
    assert cp.returncode == 0, (cp.returncode, cp.stdout, cp.stderr)
    assert "all authorised" in cp.stdout, cp.stdout


def test_without_the_authorisation_the_same_candidate_is_refused(touches_a_judge):
    """The control for the case above. Same tree, same flags but one — if the
    refusal does not reappear, the case above measured nothing."""
    cp = _run("--base", "HEAD~1", "--head", "HEAD", repo=touches_a_judge)
    assert cp.returncode == 1, (cp.returncode, cp.stdout, cp.stderr)


# --------------------------------------------------------------------------
# G4 — the empty set (kept: it already asserted an exact code)
# --------------------------------------------------------------------------

def test_an_empty_judge_set_is_refused_rather_than_passing_everything():
    """The failure mode this check must never have.

    Driven by making the derivation return nothing, because an assertion about
    what SHOULD happen when the set is empty is worth nothing unless the empty
    case is actually reached.
    """
    m = _mod()
    m.judge_set_at = lambda repo, rev: set()
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = m.main(["--repo", str(REPO), "--base", "HEAD~1"])
    assert rc == 2, f"an empty judge set returned {rc}, not a refusal"
    assert "EMPTY" in buf.getvalue(), buf.getvalue()


# --------------------------------------------------------------------------
# D1 — "I could not look" must never read as "I looked and it is clean"
# --------------------------------------------------------------------------

def test_a_base_that_does_not_resolve_refuses_instead_of_passing():
    """`_git` used to run with check=False and return `.stdout`.

    An unresolvable base made git exit 128, `changed` came back empty, and the
    check printed `candidate touches none` and exited 0 — every landing passing
    while the candidate edited whatever it liked.
    """
    cp = _run("--base", "no-such-ref-zzz", "--head", "HEAD")
    assert cp.returncode == 2, (cp.returncode, cp.stdout, cp.stderr)
    assert "CANNOT LOOK" in cp.stdout, cp.stdout
    assert "--base" in cp.stdout and "no-such-ref-zzz" in cp.stdout, (
        "the refusal did not name which flag failed or what it was given")
    assert "touches none" not in cp.stdout, (
        "the refusal still contains the sentence that made this silent")


def test_a_shallow_clone_missing_the_base_refuses_and_says_it_is_shallow(shallow):
    """The default shape of a CI checkout, and the reason this matters.

    A `--depth 1` clone does not contain HEAD~1, so the comparison is
    impossible. Passing here is worse than failing: the landing path would read
    a clean bill of health from a check that never ran.
    """
    cp = _run("--base", "HEAD~1", "--head", "HEAD", repo=shallow)
    assert cp.returncode == 2, (cp.returncode, cp.stdout, cp.stderr)
    assert "SHALLOW" in cp.stdout, (
        "the refusal did not name the real cause, so the reader is left "
        "debugging a ref that is genuinely fine upstream")


def test_cannot_look_and_clean_do_not_share_an_exit_code():
    """Two different facts, and the whole defect was that they agreed.

    Asserted as an inequality between the two REAL runs rather than as two
    separate constants, so demoting either one to match the other fails here.
    """
    could_not = _run("--base", "no-such-ref-zzz", "--head", "HEAD")
    looked = _run("--base", "HEAD", "--head", "HEAD")
    assert looked.returncode == 0, (looked.returncode, looked.stdout)
    assert could_not.returncode == 2, (could_not.returncode, could_not.stdout)
    assert could_not.returncode != looked.returncode


def test_git_failing_raises_rather_than_returning_an_empty_string():
    """The primitive, driven directly: the silence started here."""
    m = _mod()
    with pytest.raises(m.CannotLook) as exc:
        m._git(REPO, "rev-parse", "--verify", "--quiet", "no-such-ref-zzz^{commit}")
    assert "exited" in str(exc.value)


# --------------------------------------------------------------------------
# D8 — an abbreviated flag is a rename nobody notices
# --------------------------------------------------------------------------

def test_flags_cannot_be_abbreviated():
    """With argparse's default `allow_abbrev=True`, renaming `--base` to
    `--baseline` leaves every existing `--base` caller silently working, so the
    rename is invisible to every guard in this file."""
    cp = _run("--base", "HEAD~1", "--hea", "HEAD")
    assert cp.returncode == 2, (cp.returncode, cp.stdout, cp.stderr)
    assert "unrecognized arguments" in cp.stderr, cp.stderr


def test_a_missing_base_refuses_rather_than_defaulting():
    cp = _run("--head", "HEAD")
    assert cp.returncode == 2, (cp.returncode, cp.stdout, cp.stderr)
    assert "--base is required" in cp.stdout, cp.stdout


# --------------------------------------------------------------------------
# G5 — reproducibility, across two REAL checkouts
# --------------------------------------------------------------------------

def test_the_set_is_a_property_of_the_commit_not_of_the_checkout(tmp_path):
    """Two SEPARATE checkouts of one commit must agree, member by member.

    The version this replaces derived twice in ONE process on ONE checkout, so
    it could only catch intra-process nondeterminism — never the
    checkout-dependence its own name disclaimed. It stayed green while the same
    commit gave different answers in two trees.
    """
    m = _mod()
    sha = subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"],
                         capture_output=True, text=True, check=True).stdout.strip()
    a, b = _clone(tmp_path / "a"), _clone(tmp_path / "b")
    for c in (a, b):
        subprocess.run(["git", "-C", str(c), "checkout", "-q", sha], check=True)
    sa, sb = m.judge_set(a), m.judge_set(b)
    assert sa == sb, (
        f"two clean checkouts of {sha[:12]} disagreed: "
        f"only in A {sorted(sa - sb)}, only in B {sorted(sb - sa)}")
    assert m.judge_set_at(a, sha) == m.judge_set_at(b, sha)


def test_a_dirty_tree_can_only_lose_members_through_TRACKED_files(tmp_path):
    """What a dirty tree ACTUALLY does — measured, replacing a pin that was
    written backwards.

    The claim this replaces was "254 on a clean clone vs 191 on a dirty tree,
    because it reads the working tree". That direction is impossible: an
    untracked file can only ever ADD a member, and only if something reachable
    already NAMES its exact path. MEASURED 2026-08-28 on this tree: 56 untracked
    files moved the set by ZERO and removed nothing, and there is no
    named-but-absent path anywhere in the set for an untracked file to occupy.
    A drop of 63 would need TRACKED files DELETED or MODIFIED — a different and
    more serious hazard than the one that was documented.

    The verdict path no longer has any of this: it reads a COMMIT.
    """
    m = _mod()
    repo = _clone(tmp_path / "dirty")
    clean = m.judge_set(repo)
    committed = m.judge_set_at(repo, "HEAD")
    assert clean == committed

    made = []
    for i in range(56):
        p = repo / f"_untracked_probe_{i}.py"
        p.write_text("import os\n")
        made.append(p)
    with_untracked = m.judge_set(repo)
    assert not clean - with_untracked, (
        f"untracked files REMOVED members: {sorted(clean - with_untracked)} — "
        f"that is the direction the old note claimed and it should be "
        f"impossible")
    for p in made:
        p.unlink()

    victim = repo / "tools" / "ci" / "run_plugin_self_audit.sh"
    body = victim.read_bytes()
    victim.unlink()
    assert victim.as_posix().split(f"{repo.as_posix()}/")[-1] not in m.judge_set(repo)
    victim.write_bytes(body)

    # and the verdict path is immune to every one of the above
    assert m.judge_set_at(repo, "HEAD") == committed
