"""#2121 — a multi-ref push was gated by whichever ref the loop saw LAST.

`tools/git-hooks/pre-push` read git's ref lines in a `while` loop and assigned
`PUSH_RANGE` / `PUSH_BASE` / `PUSH_TO_MAIN` / `PUSH_HEAD` / `PUSH_DEST_REF` once
per ref, then ran the gate set ONCE, AFTER the loop.  So a push carrying several
refs — `git push origin a b`, `git push origin branch main`, `git push --all` —
was judged entirely by its last ref, and every other ref reached the remote
ungated.

REPRODUCED ON `94617408759e` BEFORE ANYTHING WAS CHANGED, on the real hook, with
the stdin git gives it.  A synthetic repo in the shipped layout, `next/x` whose
only difference from `main` is a swept 1.0.0 -> 1.0.1 version bump (which
`branch_version_bump_guard` refuses) and `next/y` carrying an ordinary commit::

    next/x alone                        rc 1   gate named
    next/y alone                        rc 0
    next/x THEN next/y, ONE push        rc 0   <- the offending ref slips past
    next/y THEN next/x, ONE push        rc 1   gate named

Both orders are damage and neither is the safe one:

  * a BRANCH bundled behind `main` is judged by MAIN's rules, so it is asked for
    a `gatekeeper-land.sh` stamp no contributor can mint;
  * `main` bundled behind a branch is judged by the BRANCH's rules, so the stamp
    is never demanded and the version gate is deferred to a gatekeeper who is
    not in this push.

SECOND LAYER, in the same block.  The stamp comparison read
`HEAD_SHA="$(git rev-parse HEAD)"` — the WORKING TREE's commit.  In
`git push origin next/x main` the working tree is on `next/x` while the ref
under judgement is `main` at another commit, so the stamp was compared against a
commit nobody was publishing — refusing a stamped main tip, and accepting an
unstamped one whenever HEAD happened to carry the stamp.

WHAT EACH ARM IS FOR
--------------------
  * `test_the_gates_run_inside_a_per_ref_loop`      — the wiring. RED on main.
  * `test_END_TO_END_the_offending_ref_is_refused_when_it_is_not_last` — the
    behaviour, driven through the real hook. RED on main.
  * `test_END_TO_END_the_other_order_is_refused_too` — the same two refs the
    other way round, which main already refused: without it the arm above could
    be passing because the fixture refuses everything.
  * `test_END_TO_END_a_clean_ref_alone_still_passes` — the no-over-refusal arm.
    A hook that refuses ordinary work is a hook that gets `--no-verify`'d.
  * `test_MUTANT_gating_only_the_last_record_lets_it_through` — the mutation
    arm. Take the SHIPPED hook, narrow the loop to the LAST record only (which
    is exactly the pre-fix behaviour), and the same fixture pushes clean.
  * `test_the_stamp_names_the_ref_being_pushed_not_the_checked_out_HEAD` and its
    `test_MUTANT_...` partner — the second layer, both directions.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr                    # noqa: E402

_PROGRAMS = Path(__file__).resolve().parents[1]


def _find_hook() -> Path:
    for parent in Path(__file__).resolve().parents:
        cand = parent / "tools" / "git-hooks" / "pre-push"
        if cand.is_file():
            return cand
    raise AssertionError("tools/git-hooks/pre-push not found above this test")


HOOK = _find_hook()

#: The `run_gate` label the end-to-end arms attribute their refusal to. One
#: spelling, so the driving arms and the mutation arm cannot drift apart.
GATE_LABEL = "branch carries no version bump"
#: The sentence the stamp comparison prints when it names the wrong commit.
STAMP_MISMATCH = "the gatekeeper stamp is for a different commit"


def _hook_code() -> str:
    """The hook with COMMENTS STRIPPED.  The comments name the defect and the
    variables to explain the change, so a substring search over the whole file
    passes on a hook that only TALKS about gating every ref."""
    return "\n".join(l for l in HOOK.read_text(encoding="utf-8").splitlines()
                     if not l.lstrip().startswith("#"))


# ── the fixture: the shipped layout, in miniature ───────────────────────────

def _write_tree(root: Path, version: str) -> None:
    """The SHIPPED shape: a nested plugin, TWO marketplace manifests and the
    three prose sites — the six places `gatekeeper_assign_version --write`
    writes, which is what `branch_version_bump_guard` reads."""
    plug = root / "vibe-ic-marketplace" / "plugins" / "vibe-ic"
    (root / ".claude-plugin").mkdir(parents=True, exist_ok=True)
    (root / "vibe-ic-marketplace" / ".claude-plugin").mkdir(
        parents=True, exist_ok=True)
    (plug / ".claude-plugin").mkdir(parents=True, exist_ok=True)
    (plug / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": "vibe-ic", "version": version}) + "\n",
        encoding="utf-8")
    (root / ".claude-plugin" / "marketplace.json").write_text(
        json.dumps({"name": "m", "plugins": [
            {"name": "vibe-ic",
             "source": "./vibe-ic-marketplace/plugins/vibe-ic",
             "version": version}]}) + "\n", encoding="utf-8")
    (root / "vibe-ic-marketplace" / ".claude-plugin" / "marketplace.json"
     ).write_text(json.dumps({"name": "m", "plugins": [
         {"name": "vibe-ic", "source": "./plugins/vibe-ic",
          "version": version}]}) + "\n", encoding="utf-8")
    (root / "README.md").write_text(
        f"[![Plugin v{version}](x)](y)\n\nsome prose\n", encoding="utf-8")
    (root / "vibe-ic-marketplace" / "README.md").write_text(
        f"| Plugin version | **{version}** |\n", encoding="utf-8")
    (plug / "README.md").write_text(
        f"the vibe-ic plugin (**v{version}**)\n", encoding="utf-8")


def _git(root: Path, *a: str) -> subprocess.CompletedProcess:
    return _pr.run(["git", "-C", str(root), *a], capture_output=True, text=True)


def _link_real_programs(root: Path) -> None:
    """The hook resolves its gates under the tree it is run in, so the REAL
    programs are symlinked in rather than stubbed: a fixture with stub gates
    would prove the loop shape and nothing about the gates it runs."""
    link = root / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs"
    if link.is_symlink() or link.exists():
        link.unlink()
    link.symlink_to(_PROGRAMS)


def _fixture(tmp_path: Path) -> Path:
    """`main`, plus `next/x` (a swept version bump — must be REFUSED) and
    `next/y` (an ordinary commit — must PASS)."""
    root = tmp_path / "e2e"
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q", ".")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    _write_tree(root, "1.0.0")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "seed")
    _git(root, "branch", "-M", "main")

    _git(root, "checkout", "-q", "-B", "next/x", "main")
    _write_tree(root, "1.0.1")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m",
         "fix(x): a real change that swept a version bump in")

    _git(root, "checkout", "-q", "-B", "next/y", "main")
    (root / "clean.txt").write_text("an ordinary change\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m",
         "fix(y): an ordinary change that claims no version")

    _link_real_programs(root)
    return root


def _sha(root: Path, ref: str) -> str:
    return _git(root, "rev-parse", ref).stdout.strip()


def _drive(hook: Path, root: Path, refs) -> subprocess.CompletedProcess:
    """Invoke a pre-push hook the way git does: argv = <remote> <url>, and ONE
    LINE PER REF on stdin — which is the input shape this whole file is about."""
    stdin = "".join(
        f"{ref} {local} {ref} {remote}\n" for ref, local, remote in refs)
    return _pr.run(["bash", str(hook), "origin", str(root)],
                   input=stdin, capture_output=True, text=True, cwd=str(root))


def _refs_x_then_y(root: Path):
    main = _sha(root, "main")
    return [("refs/heads/next/x", _sha(root, "next/x"), main),
            ("refs/heads/next/y", _sha(root, "next/y"), main)]


# ── the wiring ─────────────────────────────────────────────────────────────

def test_the_gates_run_inside_a_per_ref_loop():
    """THE DEFECT: the gate set sat AFTER the ref loop, at top level, reading
    whatever the last iteration left behind.  RED on `94617408759e`."""
    code = _hook_code()
    assert "PUSH_REFS+=(" in code, (
        "the ref loop still assigns the gate inputs directly instead of "
        "recording one entry per ref")
    assert "for _push_ref_record in" in code, (
        "there is no per-ref gate loop, so the gates still run once for the "
        "whole push")
    loop = code[code.index("for _push_ref_record in"):]
    body = loop[:loop.index("\ndone")]
    for gate in ("nda_diff_scan_check.py",
                 "version_bump_monotonic_check.py",
                 "agent_checkin_scope_guard.py",
                 "branch_version_bump_guard.py",
                 "git_prohibition_guard.py",
                 "gatekeeper-stamp"):
        assert gate in body, (
            f"{gate} runs outside the per-ref loop, so it still judges one ref "
            "on behalf of all of them")


def test_the_ref_independent_gate_stays_outside_the_loop():
    """The complement, and it is not decoration: `marketplace_version_sync_check`
    takes no range, no base and no destination — it asks whether the working
    tree's two manifests agree.  Running it per ref would repeat one answer N
    times, and it must still run when the push publishes no new commit at all."""
    code = _hook_code()
    loop = code[code.index("for _push_ref_record in"):]
    body = loop[:loop.index("\ndone")]
    assert "marketplace_version_sync_check.py" not in body
    assert "marketplace_version_sync_check.py" in loop[loop.index("\ndone"):]


def test_the_gates_are_not_moved_into_a_function():
    """LOAD-BEARING.  The `ERR` trap installed at the top of the hook reports a
    command that ABORTS it (vibe-ic#1254), and this file runs deliberately
    WITHOUT `set -E`, so that trap does not reach inside functions.  Gating per
    ref by calling a function would have silently disarmed it."""
    code = _hook_code()
    assert "set -E" not in code, (
        "the hook enabled errtrace; if that is intended it needs its own "
        "argument, because `run_gate` captures its own rc by design")
    loop = code[code.index("for _push_ref_record in"):]
    body = loop[:loop.index("\ndone")]
    assert "() {" not in body, (
        "the per-ref gates are inside a function definition, which puts them "
        "out of reach of the ERR trap")


# ── the behaviour, driven ──────────────────────────────────────────────────

def test_END_TO_END_the_offending_ref_is_refused_when_it_is_not_last(tmp_path):
    """THE DEFECT, MEASURED.  rc 0 on `94617408759e`."""
    root = _fixture(tmp_path)
    r = _drive(HOOK, root, _refs_x_then_y(root))
    assert r.returncode != 0, (
        "a ref carrying a version bump reached the remote because a clean ref "
        "was pushed after it:\n" + (r.stderr or r.stdout)[-2000:])
    assert GATE_LABEL in r.stderr, (
        "the push was refused, but not by the gate this arm is about:\n"
        + r.stderr[-2000:])
    assert "refs/heads/next/x" in r.stderr, (
        "the hook refused the push without naming WHICH ref is at fault, which "
        "is the one thing the reader acts on:\n" + r.stderr[-2000:])


def test_END_TO_END_the_other_order_is_refused_too(tmp_path):
    """THE CONTROL for the arm above.  This order was already refused before the
    change; without it, a fixture that refuses everything would look like a
    passing test."""
    root = _fixture(tmp_path)
    refs = list(reversed(_refs_x_then_y(root)))
    r = _drive(HOOK, root, refs)
    assert r.returncode != 0 and GATE_LABEL in r.stderr, r.stderr[-2000:]


def test_END_TO_END_a_clean_ref_alone_still_passes(tmp_path):
    """NO OVER-REFUSAL.  The ordinary single-ref push is the case that must not
    change, and a per-ref loop that refused it would be worse than the defect."""
    root = _fixture(tmp_path)
    main = _sha(root, "main")
    r = _drive(HOOK, root,
               [("refs/heads/next/y", _sha(root, "next/y"), main)])
    assert r.returncode == 0, (
        "an ordinary branch push was refused:\n" + (r.stderr or r.stdout)[-2000:])


def test_END_TO_END_two_clean_refs_both_pass(tmp_path):
    """The other no-over-refusal direction: gating BOTH refs must not invent a
    finding against either of them."""
    root = _fixture(tmp_path)
    main = _sha(root, "main")
    _git(root, "checkout", "-q", "-B", "next/z", "next/y")
    (root / "clean2.txt").write_text("another ordinary change\n",
                                     encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "fix(z): another ordinary change")
    r = _drive(HOOK, root,
               [("refs/heads/next/y", _sha(root, "next/y"), main),
                ("refs/heads/next/z", _sha(root, "next/z"), main)])
    assert r.returncode == 0, (
        "two clean refs in one push were refused:\n"
        + (r.stderr or r.stdout)[-2000:])


def _mutant(tmp_path: Path, old: str, new: str, name: str) -> Path:
    """The SHIPPED hook with ONE substring replaced.  PREMISE FIRST: an arm that
    changes nothing proves nothing, so the replacement is asserted to have
    happened exactly once."""
    src = HOOK.read_text(encoding="utf-8")
    assert src.count(old) == 1, (
        f"expected exactly one occurrence of {old!r}, found {src.count(old)}")
    out = tmp_path / name
    out.write_text(src.replace(old, new, 1), encoding="utf-8")
    return out


def test_MUTANT_gating_only_the_last_record_lets_it_through(tmp_path):
    """THE MUTATION ARM.  Narrow the per-ref loop to the LAST record — which is
    precisely what the pre-fix hook did — and the identical fixture pushes
    clean, so the arm above is measuring this loop and not something else."""
    root = _fixture(tmp_path)
    mutant = _mutant(
        tmp_path,
        'for _push_ref_record in ${PUSH_REFS[@]+"${PUSH_REFS[@]}"}; do',
        'for _push_ref_record in ${PUSH_REFS[@]+"${PUSH_REFS[@]: -1}"}; do',
        "pre-push-last-ref-only")
    m = _drive(mutant, root, _refs_x_then_y(root))
    assert GATE_LABEL not in m.stderr, (
        "the mutant still named the gate, so the loop is not the line doing "
        "the work:\n" + m.stderr[-2000:])
    assert m.returncode == 0, (
        "the mutant refused for some OTHER reason, so the end-to-end arm is "
        "not attributable to the loop:\n" + (m.stderr or m.stdout)[-2000:])


# ── second layer: the stamp names the ref, not the working tree ─────────────

def _stamp(root: Path, sha: str) -> None:
    gd = Path(_git(root, "rev-parse", "--absolute-git-dir").stdout.strip())
    (gd / "gatekeeper-stamp").write_text(sha + "\ncadence=FULL\n",
                                         encoding="utf-8")


def _push_main_from_another_branch(hook: Path, root: Path):
    """`git push origin main` with the working tree on `next/y`.  The stamp
    names MAIN's commit, which is the commit being published."""
    _git(root, "checkout", "-q", "next/y")
    main = _sha(root, "main")
    _stamp(root, main)
    # a `main` that publishes a commit, so the ref reaches the gates at all
    return _drive(hook, root,
                  [("refs/heads/main", main, "0" * 40)]), main


def test_the_stamp_names_the_ref_being_pushed_not_the_checked_out_HEAD(tmp_path):
    """The stamp is minted for the commit that is being published.  Comparing
    it to `git rev-parse HEAD` asks about the working tree instead."""
    root = _fixture(tmp_path)
    r, _main = _push_main_from_another_branch(HOOK, root)
    assert STAMP_MISMATCH not in r.stderr, (
        "a stamp naming the commit actually being pushed was rejected because "
        "the working tree is on another branch:\n" + r.stderr[-2000:])


def test_MUTANT_reading_HEAD_instead_rejects_the_correct_stamp(tmp_path):
    """THE MUTATION ARM for the layer above: put `git rev-parse HEAD` back and
    the SAME correct stamp is refused."""
    root = _fixture(tmp_path)
    mutant = _mutant(tmp_path,
                     'HEAD_SHA="${PUSH_HEAD:-$(git rev-parse HEAD)}"',
                     'HEAD_SHA="$(git rev-parse HEAD)"',
                     "pre-push-head-sha")
    r, _main = _push_main_from_another_branch(mutant, root)
    assert STAMP_MISMATCH in r.stderr, (
        "the mutant accepted the stamp too, so this layer's arm is not "
        "measuring that line:\n" + r.stderr[-2000:])
