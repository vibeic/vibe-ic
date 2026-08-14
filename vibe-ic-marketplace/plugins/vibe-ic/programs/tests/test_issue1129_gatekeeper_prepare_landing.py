"""vibe-ic#1129 — preparation may fix the mechanical, and NOTHING else.

`gatekeeper-land.sh` refused a batch for three deterministic reasons a program
already owns. Automating them is easy; automating them SAFELY is the whole
problem, because a preparation step inside the landing path is a path for the
gate to edit its own subject — #1029 (the tool dirties the tree it judges) and
#1089 (a mutant leaks into a tracked source file).

So the load-bearing tests here are not "does it regenerate the index". They are
the ones that prove it REFUSES: a tree already dirty before it starts, and a
path outside what its writers declared. Every one drives the real control flow
over a real git repository; the two heavy writers are injected so what is under
test is the orchestration and the boundary rather than two writers that already
have their own suites.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
MOD = PROGRAMS / "gatekeeper_prepare_landing.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


G = _load(MOD, "_gpl_under_test")


def _git(repo: Path, *args: str):
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True)


@pytest.fixture()
def repo(tmp_path):
    """A real git repo with a plugin-shaped skeleton and one commit."""
    r = tmp_path / "repo"
    (r / "vibe-ic-marketplace/plugins/vibe-ic/programs").mkdir(parents=True)
    (r / "vibe-ic-marketplace/plugins/vibe-ic/.claude-plugin").mkdir(parents=True)
    (r / "vibe-ic-marketplace/plugins/vibe-ic/.claude-plugin/plugin.json").write_text(
        '{"version": "1.2.3"}\n', encoding="utf-8")
    (r / "vibe-ic-marketplace/plugins/vibe-ic/programs/INDEX.md").write_text(
        "stale\n", encoding="utf-8")
    (r / "untouched.py").write_text("# not preparation's business\n", encoding="utf-8")
    _git(r, "init", "-q")
    _git(r, "config", "user.email", "t@t")
    _git(r, "config", "user.name", "t")
    _git(r, "add", "-A")
    _git(r, "commit", "-q", "-m", "base commit, deliberately untagged")
    return r


def _index_writer(repo_path: Path):
    rel = "vibe-ic-marketplace/plugins/vibe-ic/programs/INDEX.md"
    (repo_path / rel).write_text("regenerated\n", encoding="utf-8")
    return [rel]


def _version_writer(repo_path: Path, plugin: Path, old):
    rel = "vibe-ic-marketplace/plugins/vibe-ic/.claude-plugin/plugin.json"
    (repo_path / rel).write_text('{"version": "1.2.4"}\n', encoding="utf-8")
    return [rel]


def _run(repo_path, **kw):
    kw.setdefault("do_commit", False)
    kw.setdefault("index_writer", _index_writer)
    kw.setdefault("version_writer", _version_writer)
    kw.setdefault("plugin_root", repo_path / "vibe-ic-marketplace/plugins/vibe-ic")
    return G.prepare(repo_path, **kw)


# ---------------------------------------------------------------------------
# THE BOUNDARY — the half that decides whether this program is safe to exist
# ---------------------------------------------------------------------------
def test_a_path_OUTSIDE_the_declared_set_is_REFUSED(repo):
    """The #1029/#1089 shape, as a rule.

    A writer that scribbles somewhere it never declared must not be forgiven,
    whatever it wrote — this is the one failure mode that would make preparing
    worse than refusing.
    """
    def scribbles(repo_path: Path):
        (repo_path / "untouched.py").write_text("# EDITED\n", encoding="utf-8")
        rel = "vibe-ic-marketplace/plugins/vibe-ic/programs/INDEX.md"
        (repo_path / rel).write_text("regenerated\n", encoding="utf-8")
        return [rel]                      # declares ONLY the index

    rc, notes, _ = _run(repo, index_writer=scribbles)
    assert rc == G.RC_REFUSED, notes
    assert any("OUTSIDE the set its writers declared" in n for n in notes), notes
    assert any("untouched.py" in n for n in notes), notes


def test_the_same_write_INSIDE_the_declared_set_is_allowed(repo):
    """The paired direction. Identical edit to the identical file — the only
    thing that changes is whether the writer DECLARED it, and only that decides."""
    def declares_it(repo_path: Path):
        (repo_path / "untouched.py").write_text("# EDITED\n", encoding="utf-8")
        rel = "vibe-ic-marketplace/plugins/vibe-ic/programs/INDEX.md"
        (repo_path / rel).write_text("regenerated\n", encoding="utf-8")
        return [rel, "untouched.py"]

    rc, notes, declared = _run(repo, index_writer=declares_it)
    assert rc == G.RC_OK, notes
    assert "untouched.py" in declared, declared


def test_an_ALREADY_dirty_tree_is_refused_before_anything_is_written(repo):
    """Attribution. If the tree is dirty before preparation starts, no path it
    finds afterwards can be attributed to it — so the boundary check below
    would be inheriting somebody else's edit and calling it authorised."""
    (repo / "untouched.py").write_text("# somebody else got here first\n",
                                       encoding="utf-8")
    rc, notes, _ = _run(repo)
    assert rc == G.RC_REFUSED, notes
    assert any("already dirty" in n for n in notes), notes
    # and it wrote nothing: the index is still the stale content
    idx = repo / "vibe-ic-marketplace/plugins/vibe-ic/programs/INDEX.md"
    assert idx.read_text() == "stale\n", idx.read_text()


def test_a_writer_that_declares_NOTHING_is_unrunnable_not_a_silent_pass(repo):
    """"Wrote nothing" and "will not say what it wrote" are the same
    observation, and only one of them is safe. This program may not guess."""
    rc, notes, _ = _run(repo, index_writer=lambda p: [])
    assert rc == G.RC_UNRUNNABLE, notes
    assert any("declared no files" in n for n in notes), notes


# ---------------------------------------------------------------------------
# The mechanical work itself
# ---------------------------------------------------------------------------
def test_the_version_is_bumped_only_when_the_tip_carries_no_tag(repo):
    rc, notes, _ = _run(repo)
    assert rc == G.RC_OK, notes
    assert any("1.2.3 -> 1.2.4" in n for n in notes), notes

    _git(repo, "checkout", "--", ".")
    _git(repo, "commit", "-q", "--amend", "-m", "base commit [v9.9.9]")
    rc, notes, _ = _run(repo)
    assert rc == G.RC_OK, notes
    assert any("already carries a [vX.Y.Z] tag" in n for n in notes), notes
    assert not any("->" in n and "version" in n for n in notes), notes


def test_commit_amends_the_tip_and_leaves_the_worktree_CLEAN(repo):
    """The gate this program must leave satisfied is
    `landing_worktree_is_clean_check`. Preparing and then handing the gate a
    dirty tree would trade one mechanical refusal for another."""
    rc, notes, _ = _run(repo, do_commit=True)
    assert rc == G.RC_OK, notes
    assert not G.dirty_paths(repo), G.dirty_paths(repo)
    subject = _git(repo, "log", "-1", "--format=%s").stdout
    assert G._VERSION_TAG.search(subject), subject
    assert "[v1.2.4]" in subject, subject
    assert _git(repo, "rev-list", "--count", "HEAD").stdout.strip() == "1", \
        "amend must not add a commit"


def test_commit_amends_an_ALREADY_TAGGED_tip_without_adding_a_commit(repo):
    """The other half of the commit branch, and it was UNPINNED until a mutant
    said so: the fixture's tip is untagged, so only the `else` arm ran and
    breaking the already-tagged arm killed no test.

    A batch whose tip already carries its tag is the COMMON case on a re-run —
    prepare, gate fails on something real, fix it, prepare again — so the arm
    that was untested is the one the operator hits most.
    """
    _git(repo, "commit", "-q", "--amend", "-m", "base commit [v9.9.9]")
    before_n = _git(repo, "rev-list", "--count", "HEAD").stdout.strip()
    rc, notes, _ = _run(repo, do_commit=True)
    assert rc == G.RC_OK, notes
    assert not G.dirty_paths(repo), G.dirty_paths(repo)
    subject = _git(repo, "log", "-1", "--format=%s").stdout
    assert "[v9.9.9]" in subject, subject
    assert subject.count("[v") == 1, f"a second tag was appended: {subject}"
    assert _git(repo, "rev-list", "--count", "HEAD").stdout.strip() == before_n, \
        "amend must not add a commit"


def test_untracked_paths_are_not_treated_as_dirty(repo):
    """Scope matched to `landing_worktree_is_clean_check`, which excludes `??`.
    Widening it here would refuse preparation over somebody's scratch notes."""
    (repo / "scratch_notes.txt").write_text("notes\n", encoding="utf-8")
    assert not G.dirty_paths(repo), G.dirty_paths(repo)
    rc, notes, _ = _run(repo)
    assert rc == G.RC_OK, notes


# ---------------------------------------------------------------------------
# Agreement with the consumers this exists to satisfy
# ---------------------------------------------------------------------------
def test_the_tag_pattern_matches_the_consumers(tmp_path):
    """`landing_is_one_commit_check` is the gate that reads this tag. If the two
    patterns ever disagree, preparation writes a tag the gate does not accept
    and the hour it was meant to save is spent anyway."""
    consumer = PROGRAMS / "landing_is_one_commit_check.py"
    if not consumer.is_file():
        pytest.skip("consumer not present")
    c = _load(consumer, "_gpl_consumer")
    for subject in ("fix: a thing [v1.2.3]", "chore [v10.20.30] tail"):
        assert bool(G._VERSION_TAG.search(subject)) is \
               bool(c._VERSION_RE.search(subject)), subject
    for subject in ("fix: no tag here", "v1.2.3 without brackets"):
        assert bool(G._VERSION_TAG.search(subject)) is \
               bool(c._VERSION_RE.search(subject)), subject


def test_the_real_program_runs_against_this_repo_and_honours_its_boundary():
    """Driven against the REAL tree with the REAL writers, because a fixture
    that only ever exercises stand-ins would not notice the day a writer starts
    scribbling outside what it declares."""
    # <repo>/vibe-ic-marketplace/plugins/vibe-ic/programs -> parents[3] is <repo>.
    # Spelled by INDEX so a wrong count cannot make this test skip silently:
    # the first version of this line was `.parent.parent.parent`, one short,
    # and the test reported `skipped` rather than running against the real tree.
    repo_root = PROGRAMS.parents[3]
    assert (repo_root / ".git").exists(), (
        f"repo root resolved to {repo_root}, which is not a git checkout — "
        f"this test must RUN against the real tree, not skip past it")
    if G.dirty_paths(repo_root):
        pytest.skip("tree already dirty — this test needs a clean tree to attribute")
    rc, notes, declared = G.prepare(repo_root, do_commit=False)
    try:
        assert rc == G.RC_OK, notes
        assert any("boundary honoured" in n for n in notes), notes
        for p in G.dirty_paths(repo_root):
            assert p in declared, (p, declared)
    finally:
        subprocess.run(["git", "-C", str(repo_root), "checkout", "--",
                        *(G.dirty_paths(repo_root) or ["."])],
                       capture_output=True, text=True)


# ---------------------------------------------------------------------------
# THE WIRING — the half that decides whether any of the above is REACHABLE
# ---------------------------------------------------------------------------
# Everything above drives `gatekeeper_prepare_landing.py` directly. None of it
# touches `tools/gatekeeper-land.sh`, which is the only thing that ever invokes
# the program in production. Measured on this branch: delete `--prepare` from
# that script, commit, and the ten tests above stay GREEN (10 passed either
# way; script md5 ef10a54d… vs 206c60a8…). `--prepare` appeared in ZERO tests
# across `programs/tests/`, so `PREPARE=0`, `--prepare) PREPARE=1` and the
# `if [ "$PREPARE" = "1" ]` block were a capability the suite could not see.
#
# That is the #1241-row-1 shape — a program verified against its author's model
# and never against the path that invokes it — and it is worse here than usual
# because this code runs INSIDE the landing path, where a repair that silently
# never ran is indistinguishable from a repair that ran and found nothing.
#
# WHY THESE DRIVE THE SCRIPT INSTEAD OF GREPPING IT. A test asserting the file
# CONTAINS "--prepare" would pass on a dispatch that is present and broken —
# the same class of defect it was written to close. So both tests below execute
# the real script and read an observable result.
#
# WHY REFUSAL IS THE OBSERVABLE. A successful preparation returns to the script
# and the ~1h gate tier begins, which no test may sit through. A REFUSAL exits
# before the cheap tier, so it is bounded by construction — measured at 0s for
# both arms. It is also the arm that matters: this dispatch's job is to stop a
# landing whose preparation could not be attributed.
#
# AND WHY IT ASSERTS THE PROGRAM'S OWN WORDS. The script prints "preparation
# REFUSED" whenever python3 exits non-zero — including when the program is
# MISSING. Asserting only on the script's message would therefore accept a
# broken dispatch. Asserting on the program's own refusal text is what proves
# the real program ran and answered.
_LAND_SH = PROGRAMS.parents[3] / "tools" / "gatekeeper-land.sh"


@pytest.fixture()
def landing_repo(tmp_path):
    """A scratch repo carrying the REAL script and the REAL program, dirty.

    Copies rather than stubs: mutate either file in this repository and these
    tests move, which is the binding that was missing. Only
    `gatekeeper_prepare_landing.py` is needed beside the script — its module
    imports are stdlib, and `gatekeeper_assign_version` is loaded lazily AFTER
    the dirty check these tests stop at.
    """
    assert _LAND_SH.is_file(), f"{_LAND_SH} not found — resolve the repo root"
    r = tmp_path / "landing"
    prog = r / "vibe-ic-marketplace/plugins/vibe-ic/programs"
    prog.mkdir(parents=True)
    (r / "tools").mkdir()
    (r / "vibe-ic-marketplace/plugins/vibe-ic/.claude-plugin").mkdir(parents=True)
    (r / "tools/gatekeeper-land.sh").write_bytes(_LAND_SH.read_bytes())
    (prog / "gatekeeper_prepare_landing.py").write_bytes(MOD.read_bytes())
    (r / "vibe-ic-marketplace/plugins/vibe-ic/.claude-plugin/plugin.json").write_text(
        '{"version": "1.2.3"}\n', encoding="utf-8")
    (prog / "INDEX.md").write_text("stale\n", encoding="utf-8")
    _git(r, "init", "-q")
    _git(r, "config", "user.email", "t@t")
    _git(r, "config", "user.name", "t")
    _git(r, "add", "-A")
    _git(r, "commit", "-q", "-m", "base")
    # DIRTY on purpose: preparation must refuse, fast and deterministically.
    (prog / "INDEX.md").write_text("stale\ndirtied\n", encoding="utf-8")
    return r


def _land(repo: Path, *args: str):
    # 55s, under the 60s inner-bound ceiling the 180s harness implies. Measured
    # at 0s; the bound is insurance against a hang, not a budget.
    return subprocess.run(["bash", "tools/gatekeeper-land.sh", *args],
                          cwd=str(repo), capture_output=True, text=True,
                          timeout=55)


def test_the_prepare_flag_REACHES_the_real_program_and_its_refusal_stops_the_landing(
        landing_repo):
    """`--prepare` must invoke the real program and honour a REFUSAL."""
    out = _land(landing_repo, "--prepare")
    blob = out.stdout + out.stderr

    assert "--- prepare" in blob, (
        "`--prepare` was accepted but the preparation block never ran — the "
        f"dispatch in gatekeeper-land.sh is not wired.\n{blob}")
    # The PROGRAM's own words, not the script's. A missing or unimportable
    # program also makes python3 exit non-zero and the script print its own
    # "preparation REFUSED", so only this line distinguishes "the real program
    # ran and refused" from "the dispatch points at nothing".
    assert "already dirty before preparation" in blob, (
        "the script reported a refusal, but the refusal did not come from "
        "gatekeeper_prepare_landing — the dispatch may point at nothing.\n"
        f"{blob}")
    assert "preparation REFUSED" in blob, (
        f"the program refused and the script did not act on it.\n{blob}")
    assert out.returncode == 1, (
        f"a refused preparation must stop the landing, got rc={out.returncode}"
        f"\n{blob}")
    # The whole point of #1129: do not spend the hour after a mechanical refusal.
    assert "cheap tier" not in blob, (
        "preparation was refused and the gate tier started anyway — the early "
        f"exit is what makes this worth wiring.\n{blob}")


def test_WITHOUT_the_flag_preparation_does_not_run(landing_repo):
    """The flag must GATE the block, not merely accompany it.

    Without this arm the test above would still pass on a script that ran
    preparation unconditionally — which would silently change what every
    existing invocation of this script does.
    """
    out = _land(landing_repo)
    blob = out.stdout + out.stderr
    assert "--- prepare" not in blob, (
        "preparation ran without `--prepare`; the flag does not gate the "
        f"block, so every existing invocation just changed behaviour.\n{blob}")
    assert "already dirty before preparation" not in blob, (
        f"gatekeeper_prepare_landing ran without `--prepare`.\n{blob}")
    assert "cheap tier" in blob, (
        f"without preparation the script must proceed to the gates.\n{blob}")
