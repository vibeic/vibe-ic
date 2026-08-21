"""v1.9.16 — the landing gate stamped a tree that never existed.

`landing_worktree_is_clean_check` closed the BEFORE edge: it refuses when a
tracked file is modified at the moment the gate starts. It sits in the cheap
tier. The full tier then runs for minutes, reading the WORKTREE, and the stamp
written at the end names a COMMIT.

Measured on the v1.9.16 run of this repo:

    10:28:14   gate starts, tree clean, the cheap-tier check PASSES
    10:35:50   `mixed_signal_top_lvs_run.py` edited (#597, uncommitted)
    10:37:49   a new test file written
    10:41      targeted tests run; "ALL GATES PASS - stamped 9fd81bb45"

The 16 targeted files were selected from the COMMIT RANGE and executed against a
worktree carrying an unrelated uncommitted change. Both directions are wrong:
the edit could have broken something the batch is then blamed for, or repaired
something the batch would otherwise have failed on.

So the fingerprint is taken at the start and re-checked before the stamp.

THE ORDER IS THE FIX. A comparison that runs anywhere before the last suite
leaves exactly the window it exists to close, and a comparison that runs after
the stamp is written cannot withhold it. Both are asserted below, because the
program can be perfectly correct and wired into a place where it answers
nothing — the failure this repo keeps finding.

WHAT IT DOES NOT COVER, asserted nowhere and therefore stated here: an edit made
AND reverted inside the full tier leaves an identical fingerprint. The window
narrows from the whole expensive tier to an edit undone within it; only running
the gates on a private checkout removes it.
"""
from __future__ import annotations

import importlib.util
import pathlib
import re
import subprocess
import sys

import pytest

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
PROG = _PROGRAMS / "landing_worktree_is_clean_check.py"
_LAND_SH = _PROGRAMS.parents[3] / "tools" / "gatekeeper-land.sh"

RC_OK, RC_DIRTY, RC_CANNOT_MEASURE = 0, 1, 2


def _load():
    spec = importlib.util.spec_from_file_location(
        "landing_worktree_is_clean_check", PROG)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["landing_worktree_is_clean_check"] = mod
    spec.loader.exec_module(mod)
    return mod


M = _load()


def _repo(tmp_path):
    """A real git repo carrying one of the SHIPPED_PATHS."""
    for cmd in (["init", "-q", "-b", "main"],
                ["config", "user.email", "t@t"],
                ["config", "user.name", "t"]):
        subprocess.run(["git", "-C", str(tmp_path), *cmd], check=True,
                       capture_output=True, timeout=60)
    d = tmp_path / "tools"
    d.mkdir()
    (d / "a.sh").write_text("echo a\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "tools/a.sh"],
                   check=True, capture_output=True, timeout=60)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "base"],
                   check=True, capture_output=True, timeout=60)
    return tmp_path


def _run(repo, *extra):
    return subprocess.run([sys.executable, str(PROG), str(repo), *extra],
                          capture_output=True, text=True, timeout=30)


# ── the fingerprint answers "is this the same tree" ──────────────────────────
def test_an_unchanged_tree_fingerprints_the_same(tmp_path):
    r = _repo(tmp_path)
    assert M.fingerprint(r) == M.fingerprint(r)


def test_a_tracked_edit_moves_it(tmp_path):
    """The v1.9.16 case exactly: a tracked file edited while the gates run."""
    r = _repo(tmp_path)
    before = M.fingerprint(r)
    (r / "tools" / "a.sh").write_text("echo b\n", encoding="utf-8")
    assert M.fingerprint(r) != before


def test_an_added_untracked_file_moves_it(tmp_path):
    """pytest can collect a file that appears mid-run, so an addition counts as
    the tree moving even though the cheap-tier check ignores untracked files
    when deciding whether the LANDING is complete."""
    r = _repo(tmp_path)
    before = M.fingerprint(r)
    (r / "tools" / "new.sh").write_text("echo n\n", encoding="utf-8")
    assert M.fingerprint(r) != before


def test_a_new_commit_moves_it(tmp_path):
    """A clean tree at a different HEAD is a different tree."""
    r = _repo(tmp_path)
    before = M.fingerprint(r)
    (r / "tools" / "a.sh").write_text("echo b\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(r), "commit", "-qam", "x"], check=True,
                   capture_output=True, timeout=60)
    assert M.fingerprint(r) != before


def test_it_is_stable_across_a_pytest_run(tmp_path):
    """LOAD-BEARING for the untracked half. If tool droppings moved the
    fingerprint, the comparison would fail on every real run and be removed.
    `git status` drops whatever .gitignore covers, which is what keeps
    `__pycache__` out — asserted rather than assumed."""
    r = _repo(tmp_path)
    (r / "tools" / "t.py").write_text("def test_x():\n    assert True\n",
                                      encoding="utf-8")
    subprocess.run(["git", "-C", str(r), "add", "tools/t.py"], check=True,
                   capture_output=True, timeout=60)
    subprocess.run(["git", "-C", str(r), "commit", "-qm", "t"], check=True,
                   capture_output=True, timeout=60)
    (r / ".gitignore").write_text("__pycache__/\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(r), "add", ".gitignore"], check=True,
                   capture_output=True, timeout=60)
    subprocess.run(["git", "-C", str(r), "commit", "-qm", "ignore"], check=True,
                   capture_output=True, timeout=60)
    before = M.fingerprint(r)
    subprocess.run([sys.executable, "-m", "pytest", "-q", "tools/t.py"],
                   cwd=str(r), capture_output=True, timeout=60)
    assert M.fingerprint(r) == before


# ── the CLI refuses rather than passing ──────────────────────────────────────
def test_expect_against_a_matching_fingerprint_passes(tmp_path):
    r = _repo(tmp_path)
    fp = tmp_path / "fp.txt"
    assert _run(r, "--emit-fingerprint", str(fp)).returncode == RC_OK
    assert _run(r, "--expect-fingerprint", str(fp)).returncode == RC_OK


def test_expect_after_the_tree_moved_refuses(tmp_path):
    """A tracked edit that is COMMITTED leaves the tree clean, so the
    cheap-tier rule alone still passes — and the gate would stamp a tree its
    suites never read."""
    r = _repo(tmp_path)
    fp = tmp_path / "fp.txt"
    _run(r, "--emit-fingerprint", str(fp))
    (r / "tools" / "a.sh").write_text("echo moved\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(r), "commit", "-qam", "mid-run"],
                   check=True, capture_output=True, timeout=60)
    assert _run(r).returncode == RC_OK, "the tree is clean, so the old rule passes"
    got = _run(r, "--expect-fingerprint", str(fp))
    assert got.returncode == RC_DIRTY, got.stdout + got.stderr
    assert "MOVED" in got.stderr


def test_a_missing_fingerprint_file_is_not_read_as_agreement(tmp_path):
    """"I could not compare" and "they match" are different claims. Returning 0
    here would restore the hole in the one case where the emit step failed."""
    r = _repo(tmp_path)
    got = _run(r, "--expect-fingerprint", str(tmp_path / "never-written"))
    assert got.returncode == RC_CANNOT_MEASURE, got.stdout + got.stderr


def test_the_pre_existing_dirty_rule_is_unchanged(tmp_path):
    r = _repo(tmp_path)
    (r / "tools" / "a.sh").write_text("echo dirty\n", encoding="utf-8")
    assert _run(r).returncode == RC_DIRTY


# ── the wiring, which is where the value actually is ─────────────────────────
#
# THE TEXT SEARCHED IS THE EXECUTABLE TEXT, NOT THE FILE (vibe-ic#1087 follow-up).
#
# These tests locate invocations by `str.index`, which returns the FIRST match
# anywhere in the file — including inside a comment. `gatekeeper-land.sh` names
# both tokens in its own prose before it runs either of them:
#
#     212  # it. `landing_worktree_is_clean_check --expect-fingerprint` at the …
#     220  # `plugin_full_audit.py` run INSIDE this window but OUTSIDE the …
#     320  run "plugin full audit"       python3 "$PROGRAMS/plugin_full_audit.py"
#     336          --expect-fingerprint "$FP"
#
# so `index("--expect-fingerprint")` returned 212 (a comment) while
# `rindex("plugin_full_audit.py")` returned 320 (the call), and the ordering
# assertion compared prose against an invocation and failed. The SCRIPT was
# correct throughout — 184 < 320 < 336 < stamp — and it is this test that was
# reading the wrong thing.
#
# That is vibe-ic#1012's lesson one level up: "a substring test counted a
# program named in a COMMENT as wired". The remedy already ships in this repo,
# so it is IMPORTED rather than re-implemented — a second copy of "what counts
# as executable" is a second thing to drift.
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))
from gate_is_wired_check import executable_text  # noqa: E402


@pytest.fixture(scope="module")
def land_sh():
    """`gatekeeper-land.sh` with its comments removed.

    Comment REMOVAL, not line removal: `executable_text` truncates each line at
    its `#` and keeps the line, so every surviving token stays in its original
    relative order and the position comparisons below remain meaningful.
    """
    if not _LAND_SH.is_file():
        pytest.skip(f"{_LAND_SH} absent")
    return executable_text(_LAND_SH, _LAND_SH.read_text(encoding="utf-8"))


def test_the_fixture_hides_a_token_that_appears_only_in_prose():
    """The premise, asserted rather than assumed.

    If `executable_text` ever stopped stripping shell comments this fixture
    would silently revert to searching prose, and every ordering test above
    would go back to being satisfied by a mention. Pinned on a synthetic input
    so it cannot drift with the real script's wording.
    """
    sample = "# a comment naming --expect-fingerprint\nrun --emit-fingerprint\n"
    stripped = executable_text(pathlib.Path("x.sh"), sample)
    assert "--expect-fingerprint" not in stripped, stripped
    assert "--emit-fingerprint" in stripped, stripped


def test_the_landing_gate_takes_a_fingerprint_and_compares_it(land_sh):
    assert "--emit-fingerprint" in land_sh
    assert "--expect-fingerprint" in land_sh


#: WHERE the stamp is written, located by what the line DOES rather than by how
#: it is spelled.
#:
#: This assertion used to carry the literal `git rev-parse HEAD >
#: "$ROOT/.git/gatekeeper-stamp"` and went red — with `ValueError: substring
#: not found`, which says nothing about the invariant — the moment the script
#: stopped using that spelling. It had to: in a `git worktree` `.git` is a FILE
#: (a `gitdir:` pointer), so the redirect died with "Not a directory", no stamp
#: was ever written, and the hook then refused the push for want of one. The
#: script now resolves `$(git rev-parse --absolute-git-dir)`, which is the
#: PER-WORKTREE git dir.
#:
#: So the pattern pins the two things that are actually load-bearing — the
#: value written is the commit, and the file it lands in is the stamp — and is
#: indifferent to the expression in between, which is the part that legitimately
#: changed and may change again.
_STAMP_WRITE_RE = re.compile(
    r'git\s+rev-parse\s+HEAD\s*>\s*"?(?P<path>[^"\n]*?gatekeeper-stamp)"?')
_STAMP_REMOVE_RE = re.compile(r'rm\s+-f\s+"?(?P<path>[^"\n]*?gatekeeper-stamp)"?')


def _stamp_write(text: str):
    m = _STAMP_WRITE_RE.search(text)
    assert m, ("nothing in the landing script writes `git rev-parse HEAD` into "
               "a gatekeeper-stamp file — the expensive tier is then enforced "
               "by nothing, because the pre-push hook has no stamp to compare")
    return m


#: WHERE the last suite finishes, located by what the line DOES.
#:
#: This used to be `land_sh.rindex("plugin_full_audit.py")`, and that literal
#: was doing two jobs: naming the last suite, and assuming the suites run one
#: after another so that the LAST ONE DECLARED is the last one to finish.
#:
#: Both premises moved. `plugin_full_audit.py` was run twice per round — once
#: here and once as `repo_hygiene_gates.sh`'s own declared gate, byte-identical
#: output, ~21 s — and the duplicate here was removed; and the independent full
#: tier stages now run CONCURRENTLY, so declaration order is no longer
#: completion order. Against a concurrent tier the honest anchor is the point
#: where every lane has been WAITED FOR, which is the last `lane_join`: after
#: it, and only after it, has every suite finished reading the tree.
#:
#: The fallback keeps this test meaningful for a tree that has not adopted the
#: lanes — including the fixture scripts and any older checkout — by falling
#: back to the last hygiene-suite invocation, which is the last suite declared
#: in the sequential shape.
def _last_suite(text: str) -> int:
    for token in ("lane_join", "repo_hygiene_gates.sh", "plugin_full_audit.py"):
        if token in text:
            return text.rindex(token)
    raise AssertionError(
        "gatekeeper-land.sh names no suite this test can anchor on — the "
        "fingerprint comparison then has nothing to be ordered against")


def test_the_comparison_runs_after_the_last_suite_and_before_the_stamp(land_sh):
    """THE WHOLE FIX. Before the last suite it leaves the window open; after
    the stamp it cannot withhold one."""
    emit = land_sh.index("--emit-fingerprint")
    expect = land_sh.index("--expect-fingerprint")
    last_suite = _last_suite(land_sh)
    stamp = _stamp_write(land_sh).start()
    assert emit < last_suite, "the fingerprint is taken after the suites ran"
    assert last_suite < expect, (
        "the comparison runs before the last suite, so an edit made during it "
        "is still invisible — the window this exists to close")
    assert expect < stamp, (
        "the comparison runs after the stamp is written, so it cannot withhold "
        "it")


def test_the_stamp_records_the_commit_and_is_dropped_when_a_gate_failed(land_sh):
    """A stamp that survives a failure is a permanent authorisation to push."""
    stamp = _stamp_write(land_sh)
    removals = list(_STAMP_REMOVE_RE.finditer(land_sh))
    assert removals, "a failing run leaves the previous stamp in place"
    assert any(m.start() > stamp.start() for m in removals), (
        "the removal is written before the success branch — read the order")


def test_the_writer_and_the_hook_name_the_STAMP_THE_SAME_WAY(land_sh):
    """The invariant the literal was standing in for.

    The stamp is only enforcement if the tool that WRITES it and the hook that
    READS it resolve the same path. They drifted once already — the script used
    `$ROOT/.git` while the hook used the same expression — and the symptom was
    a push refused for want of a stamp that had been written somewhere else.
    Two spellings of one path is the two-hand-maintained-lists shape this repo
    keeps removing; so the two are compared, not each pinned to a constant.
    """
    hook = _PROGRAMS.parents[3] / "tools" / "git-hooks" / "pre-push"
    if not hook.is_file():
        pytest.skip(f"{hook} absent")
    hook_text = hook.read_text(encoding="utf-8")
    reader = re.search(r'STAMP="(?P<path>[^"\n]*gatekeeper-stamp)"', hook_text)
    assert reader, "the pre-push hook no longer resolves a stamp path"
    assert _stamp_write(land_sh).group("path") == reader.group("path"), (
        "the landing script writes the stamp somewhere the hook does not look")


def test_the_stamp_path_expression_RESOLVES_and_is_per_worktree(land_sh, tmp_path):
    """RUN the expression, do not read it.

    Both halves failed in the field and neither is visible in the text:

      * `$ROOT/.git/gatekeeper-stamp` is not a writable path in a worktree at
        all, because `.git` is a file there — the redirect fails and no stamp
        exists;
      * a stamp shared between two worktrees would let gates run in one
        authorise a push from the other, which sits at a different commit.
    """
    expr = _stamp_write(land_sh).group("path")
    (tmp_path / "main").mkdir()
    r = _repo(tmp_path / "main")
    wt = tmp_path / "wt"
    subprocess.run(["git", "-C", str(r), "worktree", "add", "-q", "--detach",
                    str(wt), "HEAD"], check=True, capture_output=True,
                   timeout=60)

    def _resolve(where):
        out = subprocess.run(["bash", "-c", f'ROOT="{where}"; printf "%s" "{expr}"'],
                             cwd=str(where), capture_output=True, text=True,
                             timeout=60)
        assert out.returncode == 0, out.stderr
        return out.stdout.strip()

    a, b = _resolve(r), _resolve(wt)
    for got in (a, b):
        assert got.endswith("gatekeeper-stamp"), got
        assert pathlib.Path(got).parent.is_dir(), (
            f"{got} cannot be written — its parent is not a directory. This is "
            f"the worktree failure verbatim: `.git` is a FILE there.")
    assert a != b, (
        "both worktrees resolve to the SAME stamp file, so gates run in one "
        "would authorise a push from the other")


def test_the_fingerprint_path_is_per_run(land_sh):
    """Two gates in one checkout must not read each other's fingerprint. A
    fixed path would make the second run compare against the first's tree."""
    assert "mktemp" in land_sh.split("--emit-fingerprint")[0][-600:], (
        "the fingerprint file is not per-run")
