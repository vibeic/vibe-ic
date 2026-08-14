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
@pytest.fixture(scope="module")
def land_sh():
    if not _LAND_SH.is_file():
        pytest.skip(f"{_LAND_SH} absent")
    return _LAND_SH.read_text(encoding="utf-8")


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


#: vibe-ic#1544 — THE SAME LESSON `_STAMP_WRITE_RE` ABOVE ALREADY HAD TO LEARN,
#: applied to the other three landmarks: locate them by what the line DOES, not
#: by how the file happens to spell them somewhere.
#:
#: The stamp landmark got a regex after a literal substring went red the moment
#: the script changed its spelling. The other three were left as raw
#: `str.index` / `str.rindex`, and the failure mode turned out to be worse than
#: `ValueError: substring not found`, because it is SILENT. Measured on
#: `3d13e2c59`:
#:
#:     --emit-fingerprint    @10275  line 184  CODE
#:     --expect-fingerprint  @11699  line 212  COMMENT   <- what index() found
#:     --expect-fingerprint  @22461  line 402  CODE      <- the invocation
#:     plugin_full_audit.py  @12145  line 220  COMMENT
#:     plugin_full_audit.py  @21522  line 386  CODE      <- what rindex() found
#:
#: `3febf5372` (#1029/#1046) added a rationale comment naming
#: `landing_worktree_is_clean_check --expect-fingerprint`, above the invocation.
#: From that commit on, `index()` measured the PROSE, the assertion read
#: `21522 < 11699`, and main has been red on every host since — while the
#: invariant it names was never actually violated (`emit 10275 < last_suite
#: 21522 < expect 22461 < stamp` is exactly the required order).
#:
#: Two further reasons this is resolved by line-kind rather than patched:
#:   * `emit < last_suite` was passing for the WRONG reason — `--emit-fingerprint`
#:     merely happens to have one occurrence today, and a prose mention of it
#:     above the last suite would have flipped that assertion too;
#:   * `rindex("plugin_full_audit.py")` degrades in the SAFE-LOOKING direction —
#:     delete the invocation and it silently falls back to the comment, so
#:     removing the last suite would MOVE the landmark instead of failing.
_COMMENT_LINE = re.compile(r"^[ \t]*#")


def _code_offsets(text: str, needle: str) -> list[int]:
    """Offsets of `needle` on lines that are not wholly a comment.

    A prose mention is not an invocation. In `sh` a line whose first non-blank
    character is `#` runs nothing, so it can never be one of these landmarks.
    """
    out: list[int] = []
    for m in re.finditer(re.escape(needle), text):
        start = text.rfind("\n", 0, m.start()) + 1
        end = text.find("\n", m.start())
        line = text[start:end if end != -1 else len(text)]
        if not _COMMENT_LINE.match(line):
            out.append(m.start())
    return out


def _ordering_violations(text: str) -> list[str]:
    """Every way `text` breaks the order. Empty means the invariant holds.

    Factored out of the test so the CONTROLS below can drive it with a script
    that genuinely violates each edge — a rewritten assertion that cannot be
    made to fail would be worse than the red it replaced.

    EVERY code occurrence is judged, not the first or the last. If a second
    comparison is ever added, "the comparison" stops being a single point and a
    landmark that picked one of them would be choosing which half to guard.
    """
    bad: list[str] = []
    emits = _code_offsets(text, "--emit-fingerprint")
    expects = _code_offsets(text, "--expect-fingerprint")
    suites = _code_offsets(text, "plugin_full_audit.py")
    if not emits:
        bad.append("no CODE line takes the fingerprint (--emit-fingerprint "
                   "appears only in prose, or not at all)")
    if not expects:
        bad.append("no CODE line compares the fingerprint (--expect-fingerprint "
                   "appears only in prose, or not at all) — the tree may move "
                   "under the whole expensive tier and nothing would say so")
    if not suites:
        bad.append("no CODE line runs plugin_full_audit.py, so 'the last suite' "
                   "is not a place in this script")
    if not (emits and expects and suites):
        return bad
    last_suite = max(suites)
    stamp = _stamp_write(text).start()
    if not all(e < last_suite for e in emits):
        bad.append("the fingerprint is taken after the suites ran")
    if not all(x > last_suite for x in expects):
        bad.append("the comparison runs before the last suite, so an edit made "
                   "during it is still invisible — the window this exists to "
                   "close")
    if not all(x < stamp for x in expects):
        bad.append("the comparison runs after the stamp is written, so it "
                   "cannot withhold it")
    return bad


def test_the_comparison_runs_after_the_last_suite_and_before_the_stamp(land_sh):
    """THE WHOLE FIX. Before the last suite it leaves the window open; after
    the stamp it cannot withhold one."""
    assert _ordering_violations(land_sh) == []


# ── the controls: the assertion above must still be REFUSABLE ────────────────
#
# A landmark resolver is exactly the kind of thing that can be "fixed" into
# never failing. These drive `_ordering_violations` with a script that breaks
# each edge on purpose, so a future simplification that stops refusing is
# caught here rather than on the day the tree moves under the gates.

_WELL_ORDERED = """\
#!/usr/bin/env bash
# `landing_worktree_is_clean_check --expect-fingerprint` at the end of this
# tier already refuses the stamp; `plugin_full_audit.py` runs INSIDE it.
run "write-guard baseline" python3 "$P/landing_worktree_is_clean_check.py" \\
    --emit-fingerprint "$FP"
run "targeted tests" pytest
run "plugin full audit" python3 "$PROGRAMS/plugin_full_audit.py" "$PLUGIN"
run "the tree did not move" python3 "$P/landing_worktree_is_clean_check.py" \\
    --expect-fingerprint "$FP"
git rev-parse HEAD > "$GITDIR/gatekeeper-stamp"
"""


def test_the_control_script_is_accepted():
    """The positive control. Without it the refusals below prove only that the
    function says no to everything."""
    assert _ordering_violations(_WELL_ORDERED) == []


def test_a_comparison_deleted_down_to_its_prose_mention_is_refused():
    """vibe-ic#1544 ITSELF, as a control.

    The comment naming the flag stays; only the invocation goes. This is the
    state the old `index()` landmark reported as satisfied, and it is the state
    in which nothing checks whether the tree moved.
    """
    gutted = _WELL_ORDERED.replace(
        'run "the tree did not move" python3 "$P/landing_worktree_is_clean_check.py" \\\n'
        '    --expect-fingerprint "$FP"\n', "")
    assert "--expect-fingerprint" in gutted, "the prose mention must survive"
    bad = _ordering_violations(gutted)
    assert any("only in prose" in b for b in bad), bad


def test_a_comparison_moved_before_the_last_suite_is_refused():
    moved = _WELL_ORDERED.replace(
        'run "plugin full audit" python3 "$PROGRAMS/plugin_full_audit.py" "$PLUGIN"\n'
        'run "the tree did not move" python3 "$P/landing_worktree_is_clean_check.py" \\\n'
        '    --expect-fingerprint "$FP"\n',
        'run "the tree did not move" python3 "$P/landing_worktree_is_clean_check.py" \\\n'
        '    --expect-fingerprint "$FP"\n'
        'run "plugin full audit" python3 "$PROGRAMS/plugin_full_audit.py" "$PLUGIN"\n')
    bad = _ordering_violations(moved)
    assert any("before the last suite" in b for b in bad), bad


def test_a_comparison_moved_after_the_stamp_is_refused():
    moved = _WELL_ORDERED.replace(
        'run "the tree did not move" python3 "$P/landing_worktree_is_clean_check.py" \\\n'
        '    --expect-fingerprint "$FP"\n'
        'git rev-parse HEAD > "$GITDIR/gatekeeper-stamp"\n',
        'git rev-parse HEAD > "$GITDIR/gatekeeper-stamp"\n'
        'run "the tree did not move" python3 "$P/landing_worktree_is_clean_check.py" \\\n'
        '    --expect-fingerprint "$FP"\n')
    bad = _ordering_violations(moved)
    assert any("after the stamp" in b for b in bad), bad


def test_a_fingerprint_taken_after_the_last_suite_is_refused():
    moved = _WELL_ORDERED.replace(
        'run "write-guard baseline" python3 "$P/landing_worktree_is_clean_check.py" \\\n'
        '    --emit-fingerprint "$FP"\n'
        'run "targeted tests" pytest\n'
        'run "plugin full audit" python3 "$PROGRAMS/plugin_full_audit.py" "$PLUGIN"\n',
        'run "targeted tests" pytest\n'
        'run "plugin full audit" python3 "$PROGRAMS/plugin_full_audit.py" "$PLUGIN"\n'
        'run "write-guard baseline" python3 "$P/landing_worktree_is_clean_check.py" \\\n'
        '    --emit-fingerprint "$FP"\n')
    bad = _ordering_violations(moved)
    assert any("after the suites ran" in b for b in bad), bad


def test_the_last_suite_landmark_does_not_fall_back_to_its_comment():
    """`rindex` degraded in the safe-looking direction; this pins that it no
    longer can. Delete the invocation and the script must be REFUSED, not
    silently re-anchored on the rationale comment that also names the file."""
    gutted = _WELL_ORDERED.replace(
        'run "plugin full audit" python3 "$PROGRAMS/plugin_full_audit.py" "$PLUGIN"\n',
        "")
    assert "plugin_full_audit.py" in gutted, "the prose mention must survive"
    bad = _ordering_violations(gutted)
    assert any("not a place in this script" in b for b in bad), bad


def test_a_comment_never_supplies_a_landmark():
    """The mechanism, directly: prose-only occurrences contribute nothing."""
    prose = ("# --emit-fingerprint --expect-fingerprint plugin_full_audit.py\n"
             "\t #   indented comments count as comments too\n")
    for needle in ("--emit-fingerprint", "--expect-fingerprint",
                   "plugin_full_audit.py"):
        assert _code_offsets(prose, needle) == [], needle
    # …and a real command line still does, including one with a trailing comment.
    code = 'python3 x.py --expect-fingerprint "$FP"   # the compare\n'
    assert _code_offsets(code, "--expect-fingerprint") == [
        code.index("--expect-fingerprint")]


def test_the_stamp_records_the_commit_and_is_dropped_when_a_gate_failed(land_sh):
    """A stamp that survives a failure is a permanent authorisation to push."""
    assert _stamp_write(land_sh)
    m = _STAMP_REMOVE_RE.search(land_sh)
    assert m, "a failing run leaves the previous stamp in place"
    assert m.start() > _stamp_write(land_sh).start(), (
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
