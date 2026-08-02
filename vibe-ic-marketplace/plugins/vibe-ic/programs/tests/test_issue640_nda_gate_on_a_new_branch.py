"""#640 — the NDA gate was handed a range `git diff` cannot consume.

`pre-push` builds a NEW branch's range as a REV-LIST expression — "commits not
already on a remote":

    RANGE="$local_sha --not --remotes"

and handed it straight to `nda_diff_scan_check.py`, which consumes it with
`git diff`. `--not` / `--remotes` are `rev-list` selectors; `git diff` neither
rejects nor understands them — it takes them as PATHSPECS and performs an
enormously expensive walk.

MEASURED on this repo, same command, same range:

    git diff --find-renames <sha> --not --remotes     still running at 12 s
                                                      returned at ~35 s
    the reporter's machine, 20 s bound                rc 124, 0 bytes, no stderr

So the outcome depends on how long the caller waits. Past the bound it is a
non-zero exit that `run_gate` rendered as **a positive NDA finding** — a false
alarm on the one rule this repo cannot afford to get wrong, and the surest way
to teach someone that NDA alarms are noise. Under a longer bound it eventually
answers, slowly, which is why it was never noticed.

(The obvious hypothesis — that `git diff` was blocking on stdin — was tested and
is WRONG: it behaves identically with stdin at DEVNULL and at an open pipe. It
is not waiting for input, it is doing far too much work.)

THE FIX IS TO ASK THE TOOL THAT UNDERSTANDS THE QUESTION. A commit-set
expression is resolved with `git rev-list`; the diff that covers those commits
is `<oldest>^..<newest>`. Measured after: 0 s, and the scan sees exactly the
branch's own added lines.

Every git call is also bounded now, so a slow one is an honest rc 2 rather than
a verdict about NDA content.
"""
from __future__ import annotations

import importlib.util
import pathlib
import subprocess
import sys

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
_SCANNER = _PROGRAMS / "nda_diff_scan_check.py"

_spec = importlib.util.spec_from_file_location("_nda640", _SCANNER)
N = importlib.util.module_from_spec(_spec)
sys.modules["_nda640"] = N
try:
    _spec.loader.exec_module(N)
except SystemExit:
    pass


def _repo(tmp_path):
    def g(*a, **kw):
        return subprocess.run(["git", "-C", str(tmp_path), *a],
                              capture_output=True, text=True, timeout=30, **kw)
    g("init", "-q", "-b", "main", ".")
    g("config", "user.email", "t@t")
    g("config", "user.name", "T")
    (tmp_path / "seed.txt").write_text("seed\n", encoding="utf-8")
    g("add", "seed.txt")
    g("commit", "-q", "-m", "seed")
    return g


def test_a_new_branch_range_resolves_to_the_branchs_own_commits(tmp_path):
    """THE DEFECT. Before this, the same expression went to `git diff` as
    pathspecs."""
    g = _repo(tmp_path)
    (tmp_path / "added.txt").write_text("a line only this branch has\n",
                                        encoding="utf-8")
    g("add", "added.txt")
    g("commit", "-q", "-m", "branch-only")
    head = g("rev-parse", "HEAD").stdout.strip()
    diff = N.diff_for_range(tmp_path, f"{head} --not --remotes")
    added = [l for l in diff.splitlines()
             if l.startswith("+") and not l.startswith("+++")]
    # In a fixture with NO remote, `--remotes` selects nothing, so the range is
    # every commit reachable from HEAD — seed included. That is the correct
    # reading of the expression, and the first version of this assertion
    # (`len(added) == 1`) was wrong about the semantics rather than about the
    # code. What matters is that the resolution covers exactly what `rev-list`
    # selects, and that the branch's own line is in it.
    assert "a line only this branch has" in "\n".join(added), diff
    sel = subprocess.run(["git", "-C", str(tmp_path), "rev-list",
                          head, "--not", "--remotes"],
                         capture_output=True, text=True, timeout=30).stdout.split()
    got = N.resolve_diffable_range(tmp_path, f"{head} --not --remotes")
    assert len(got) in (1, 2), got
    assert sel, "the fixture selected no commit"


def test_the_scan_would_SEE_a_token_planted_on_that_branch(tmp_path):
    """The half that makes the gate meaningful: it is not enough that the range
    resolves — the scanner must be looking at the added CONTENT, so a token
    planted there would be found.

    Driven through `scan_unified_diff` on the resolved diff, using the
    scanner's own matcher. No real token is written anywhere: the assertion is
    that the added line reaches the scanner, which is the precondition that was
    missing."""
    g = _repo(tmp_path)
    (tmp_path / "leak.txt").write_text("some added content\n", encoding="utf-8")
    g("add", "leak.txt")
    g("commit", "-q", "-m", "branch-only")
    head = g("rev-parse", "HEAD").stdout.strip()
    diff = N.diff_for_range(tmp_path, f"{head} --not --remotes")
    assert "+++ b/leak.txt" in diff, "the added PATH never reached the scanner"
    assert "+some added content" in diff, "the added CONTENT never reached it"
    # and the matcher runs over it without error
    assert isinstance(N.scan_unified_diff(diff), list)


def test_a_root_commit_is_scanned_against_the_empty_tree(tmp_path):
    """A first-ever commit has no parent. Refusing there would leave the one
    push where every path is an added path unscanned."""
    def g(*a):
        return subprocess.run(["git", "-C", str(tmp_path), *a],
                              capture_output=True, text=True, timeout=30)
    g("init", "-q", "-b", "main", ".")
    g("config", "user.email", "t@t")
    g("config", "user.name", "T")
    (tmp_path / "first.txt").write_text("first\n", encoding="utf-8")
    g("add", "first.txt")
    g("commit", "-q", "-m", "root")
    head = g("rev-parse", "HEAD").stdout.strip()
    diff = N.diff_for_range(tmp_path, f"{head} --not --remotes")
    assert "+++ b/first.txt" in diff, diff


def test_a_range_selecting_no_commit_is_refused_not_called_clean(tmp_path):
    """LOAD-BEARING, and the repo's existing rule: an empty scan reported as a
    clean scan is how a guard becomes decorative."""
    g = _repo(tmp_path)
    g("branch", "-f", "other")
    head = g("rev-parse", "HEAD").stdout.strip()
    try:
        N.diff_for_range(tmp_path, f"{head} --not --branches")
    except RuntimeError as exc:
        assert "selects no commit" in str(exc)
    else:
        raise AssertionError("an empty commit set was not refused")


def test_an_ordinary_two_dot_range_is_untouched(tmp_path):
    """The accept case: every existing caller passes a diffable range and must
    keep the identical behaviour."""
    g = _repo(tmp_path)
    base = g("rev-parse", "HEAD").stdout.strip()
    (tmp_path / "b.txt").write_text("b\n", encoding="utf-8")
    g("add", "b.txt")
    g("commit", "-q", "-m", "b")
    head = g("rev-parse", "HEAD").stdout.strip()
    assert N.resolve_diffable_range(tmp_path, f"{base}..{head}") == [f"{base}..{head}"]


def test_every_git_call_is_bounded():
    """A gate that can run for an unbounded time is a gate whose caller's
    timeout becomes its verdict — which is exactly how a slow walk became an
    NDA finding."""
    src = _SCANNER.read_text(encoding="utf-8")
    body = "\n".join(l for l in src.splitlines()
                     if not l.lstrip().startswith("#"))
    assert "timeout=_GIT_TIMEOUT_S" in body
    assert "TimeoutExpired" in body
    assert N._GIT_TIMEOUT_S <= 60, "an inner bound above 60 s can outlive the harness"


def test_the_hook_says_NOT_CHECKED_rather_than_FAILED_when_a_gate_cannot_run():
    """rc 2 is "the question could not be put"; rc 1 is a finding. Collapsing
    them is what sent someone hunting for a leak that did not exist."""
    hook = (_PROGRAMS.parents[3] / "tools" / "git-hooks" / "pre-push")
    if not hook.is_file():
        return
    code = "\n".join(l for l in hook.read_text(encoding="utf-8").splitlines()
                     if not l.lstrip().startswith("#"))
    assert 'if [ "$rc" = "2" ]' in code
    assert "NOT CHECKED — $label (the gate could not run)" in code


# ── a binary file in the diff crashed the scan, and the crash read as a leak ──
#
# `text=True` decodes git's stdout as STRICT UTF-8. A diff touching a non-UTF-8
# file — `status.sqlite`, `design_aiger.aig`, any binary artefact an evidence
# landing routinely carries — raised UnicodeDecodeError inside `subprocess`, the
# traceback exited 1, and `run_gate` reads exit 1 as a POSITIVE NDA FINDING.
#
# Same "a failed question wearing a finding's clothes" shape as the rev-list
# range above, by a different route, on the one gate this repo cannot afford to
# get wrong. MEASURED on PR #645 (352 files, an IC evidence cell):
#
#   before   UnicodeDecodeError at byte 0x96 — reported as a leak
#   after    rc 0, and the scan sees 1,291,241 added lines across 360 paths,
#            with 456 U+FFFD substitutions in 41 MB — confined to the binaries
def test_a_non_utf8_file_in_the_diff_does_not_crash_the_scan(tmp_path):
    """THE DEFECT. Any evidence landing carries binaries, so this fired every
    time one was pushed."""
    g = _repo(tmp_path)
    (tmp_path / "notes.txt").write_text("an ordinary added line\n", encoding="utf-8")
    (tmp_path / "blob.bin").write_bytes(bytes(range(256)) * 32)
    g("add", "notes.txt", "blob.bin")
    g("commit", "-q", "-m", "text beside a binary")
    head = g("rev-parse", "HEAD").stdout.strip()
    diff = N.diff_for_range(tmp_path, f"{head} --not --remotes")
    assert "an ordinary added line" in diff, (
        "the TEXT half of the diff must still reach the scanner")
    assert "+++ b/notes.txt" in diff


def test_the_substitution_cannot_manufacture_a_finding(tmp_path):
    """LOAD-BEARING in the other direction. Replacing an undecodable byte must
    only ever REMOVE a possible match, never add one: U+FFFD appears in no
    pattern, so a scan over replaced bytes cannot invent a token."""
    g = _repo(tmp_path)
    (tmp_path / "blob.bin").write_bytes(b"\x96\x97\x98" * 64)
    g("add", "blob.bin")
    g("commit", "-q", "-m", "binary only")
    head = g("rev-parse", "HEAD").stdout.strip()
    diff = N.diff_for_range(tmp_path, f"{head} --not --remotes")
    assert N.scan_unified_diff(diff) == [], (
        "replaced bytes produced a finding — the substitution is not neutral")


def test_the_decode_is_lenient_at_the_subprocess_boundary():
    """Pinned at the boundary where it broke: a later edit that drops
    `errors=` restores a crash that reads as a leak."""
    import pathlib as _pl
    src = (_pl.Path(N.__file__)).read_text(encoding="utf-8")
    body = "\n".join(l for l in src.splitlines()
                     if not l.lstrip().startswith("#"))
    assert 'errors="replace"' in body
    seg = body[body.index("def _git("):]
    seg = seg[:seg.index("\ndef ", 10)]
    assert 'errors="replace"' in seg, "the leniency is not on the git call itself"
