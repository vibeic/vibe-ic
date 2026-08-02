"""#636 — a required gate the documented contributor flow could not pass.

`tools/git-hooks/pre-push` read `_remote_ref` and discarded it, so
`refs/heads/main` and `refs/heads/feat/anything` were gated identically. The
version, however, is assigned AT MERGE by the gatekeeper — the landed history
shows it plainly, some commits carrying `[vX.Y.Z]` and some not — so a
contributor pushing a version-less branch hit

    [FAIL] version_bump_monotonic_check: version not bumped: current 1.9.51 == previous 1.9.51

which is correct about the branch and wrong about the flow: bumping would claim
a number that is not theirs to assign, and two concurrent branches would claim
the same one. Unsatisfiable in principle.

THREE LAYERS, and only the first was reported. Each was found by actually
running the hook against a version-less branch rather than by reading it:

  1. the version gate applied off-main;
  2. `git log --format='%B' "$PUSH_RANGE"` — for a NEW branch `PUSH_RANGE` is
     `<sha> --not --remotes`, three git arguments in one string. Quoted, git
     exits 128 and killed the hook on EVERY new-branch push. Pre-existing on
     `origin/main`, and reproduced directly:
         quoted   rc=128
         unquoted rc=0
  3. the expensive tier's stamp, written by `gatekeeper-land.sh`, demanded the
     LANDING procedure from someone who is not landing.

THE OFF-MAIN DEFERRAL IS NOT A SKIP. `--version-by-gatekeeper` already existed
with exactly the right semantics and had simply never been plumbed into this
hook:

    case                        default   --version-by-gatekeeper
    no change (cur == prev)      FAIL       PASS   <- the documented path
    bump      (cur >  prev)      PASS       PASS
    BACKWARDS (cur <  prev)      FAIL       FAIL   <- still refused everywhere

MEASURED END TO END on a real version-less branch, by feeding the hook the
stdin git gives it:

    -> refs/heads/feat/x   rc 0    7 run_gate calls
    -> refs/heads/main     rc 1    7 run_gate calls
                                   FAILED version bumped monotonically
                                   FAILED the full suites have not been run

Seven in BOTH directions — the cheap tier is untouched off-main. That was
counted, not assumed: the risk in this change is trading an unsatisfiable gate
for an unguarded one.
"""
from __future__ import annotations

import pathlib
import subprocess
import sys

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
_REPO = _PROGRAMS.parents[3]
_HOOK = _REPO / "tools" / "git-hooks" / "pre-push"
_PJSON = _REPO / "vibe-ic-marketplace/plugins/vibe-ic/.claude-plugin/plugin.json"


def _hook_src() -> str:
    return _HOOK.read_text(encoding="utf-8")


def _code_lines() -> str:
    """The hook without its comments — a rule stated only in prose is not a
    rule, and an assertion that matches the comment explaining a defect would
    pass on a file that reintroduced it."""
    return "\n".join(l for l in _hook_src().splitlines()
                     if not l.lstrip().startswith("#"))


# ── the destination is read, not discarded ─────────────────────────────────
def test_the_destination_ref_decides_which_gates_apply():
    """THE DEFECT: `_remote_ref` was read into the loop and never used."""
    code = _code_lines()
    assert "PUSH_TO_MAIN" in code
    assert 'refs/heads/main) PUSH_TO_MAIN=1' in code
    assert '_remote_ref' in code


def test_the_version_gate_defers_off_main_rather_than_skipping():
    """LOAD-BEARING. Dropping the gate off-main would trade an unsatisfiable
    gate for an unguarded one — a branch REGRESSING the version would then
    push. The deferral keeps that refusal."""
    code = _code_lines()
    assert "--version-by-gatekeeper" in code
    seg = code[code.index("PUSH_TO_MAIN:-1"):]
    seg = seg[:seg.index("agent_checkin_scope_guard")]
    assert "version_bump_monotonic_check.py" in seg
    assert seg.count("version_bump_monotonic_check.py") == 2, (
        "both branches must run the checker; one of them running nothing is a "
        "skip wearing a conditional")


def test_the_stamp_tier_is_main_only():
    """The stamp is written by the LANDING tool. Demanding it of a contributor
    branch demands the landing procedure from someone who is not landing."""
    code = _code_lines()
    assert 'if [ -n "${PUSH_RANGE:-}" ] && [ "${PUSH_TO_MAIN:-1}" = "1" ]' in code


def test_an_unset_destination_defaults_to_the_STRICT_side():
    """Fail-safe. `${PUSH_TO_MAIN:-1}` means an unparsed or absent destination
    is treated as a push to main and gets the full enforcement, rather than
    silently taking the relaxed path."""
    code = _code_lines()
    assert "${PUSH_TO_MAIN:-1}" in code
    assert "${PUSH_TO_MAIN:-0}" not in code


# ── the range that killed every new-branch push ────────────────────────────
def test_the_push_range_is_passed_to_git_unquoted():
    """Layer 2, pre-existing. For a new branch the range is
    `<sha> --not --remotes`; quoted, git receives one token and exits 128."""
    code = _code_lines()
    assert "git log --format='%B' $PUSH_RANGE" in code
    assert 'git log --format=\'%B\' "$PUSH_RANGE"' not in code


def test_a_multi_token_range_really_does_break_git_when_quoted():
    """The claim above, MEASURED rather than asserted from memory — otherwise
    this file pins a spelling whose reason nobody can check."""
    head = subprocess.run(["git", "-C", str(_REPO), "rev-parse", "HEAD"],
                          capture_output=True, text=True, timeout=30)
    if head.returncode != 0:
        return
    rng = f"{head.stdout.strip()} --not --remotes"
    quoted = subprocess.run(["git", "-C", str(_REPO), "log", "--format=%B", rng],
                            capture_output=True, text=True, timeout=30)
    split = subprocess.run(["git", "-C", str(_REPO), "log", "--format=%B",
                            *rng.split()], capture_output=True, text=True,
                           timeout=30)
    assert quoted.returncode != 0, "the quoted form no longer breaks git"
    assert split.returncode == 0, split.stderr[-200:]


# ── the deferral's own behaviour, driven for real ──────────────────────────
def test_the_checker_passes_unchanged_and_still_refuses_a_REGRESSION():
    """The off-main flag is only safe because a BACKWARDS version still fails.
    Driven on the real checker with explicit versions.

    NOT via a synthetic `--plugin-json` in a tmp dir: the checker resolves the
    PREVIOUS version from that same path at `--base`, so a tmp file has no
    history and the run is an honest rc 2 rather than the comparison this means
    to test. The first version of this test asserted 1 and got 2 — the checker
    was right and the fixture was wrong."""
    prog = _PROGRAMS / "version_bump_monotonic_check.py"
    if not prog.is_file():
        return

    def run(cur, prev, *extra):
        return subprocess.run(
            [sys.executable, str(prog), "--current", cur, "--previous", prev,
             *extra],
            capture_output=True, text=True, timeout=55, cwd=str(_REPO)).returncode

    assert run("1.9.51", "1.9.51") == 1, "unchanged must fail WITHOUT the flag"
    assert run("1.9.51", "1.9.51", "--version-by-gatekeeper") == 0, (
        "unchanged must pass WITH it — this is the documented contributor path")
    assert run("1.9.50", "1.9.51", "--version-by-gatekeeper") == 1, (
        "a version REGRESSION must still be refused, flag or not")
    assert run("1.9.52", "1.9.51") == 0, "a real bump still passes"
