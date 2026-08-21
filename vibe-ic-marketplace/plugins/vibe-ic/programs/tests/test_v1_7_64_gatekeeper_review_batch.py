#!/usr/bin/env python3
"""`gatekeeper_review` can express a BATCH landing (owner directive 2026-07-27).

THE DEFECT, observed while landing one
======================================
The standing directive is to land several PRs under ONE version bump and ONE CI
run. `landing_is_one_commit_check` grew a `--batch` mode for exactly that, and
its FAIL text names the flag as the remedy. But `gatekeeper_review` — the
program whose verdict decides whether a push may happen — had no way to pass
it. Every batch therefore came back REQUEST_CHANGES, blocked by a rule that
does not apply to it, quoting a remedy the reviewer could not act on.

That is worse than an inconvenience. A blocking line that must be read past is
a blocking line that TEACHES the reviewer to read past blocking lines, and the
next one may be real. The flag is plumbed through so a batch is either
expressed and checked, or not a batch.

WHAT `--batch` DOES NOT DO
==========================
It does not relax anything. The underlying batch mode asserts a STRICTLY
STRONGER property than the single-landing rule — no manifest-only commit
anywhere in the range, exactly one version bump, and it must be the tip. The
tests below pin BOTH halves: a real batch passes, and the three ways a batch
can be malformed still fail THROUGH gatekeeper_review, not merely through the
checker it calls.

It is also OPT-IN. Without the flag the single-landing rule is unchanged, so
the `commit --amend`-after-rebase slip that vibe-ic#459 documents still fails
exactly as it did.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROGRAMS))
import gatekeeper_review as GR  # noqa: E402

_MANIFEST = ".claude-plugin/plugin.json"


def _repo(tmp_path: Path) -> Path:
    d = tmp_path / "r"
    d.mkdir()
    subprocess.run(["git", "init", "-q", str(d)], check=True)
    for k, v in (("user.email", "t@t"), ("user.name", "t")):
        subprocess.run(["git", "-C", str(d), "config", k, v], check=True)
    return d


def _commit(d: Path, subject: str, files: dict) -> str:
    for rel, body in files.items():
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)
        subprocess.run(["git", "-C", str(d), "add", rel], check=True)
    subprocess.run(["git", "-C", str(d), "commit", "-qm", subject], check=True)
    return subprocess.run(["git", "-C", str(d), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()


def _batch_of_three(tmp_path: Path):
    """Three landings, the version on the tip — the shape the directive asks
    for."""
    d = _repo(tmp_path)
    base = _commit(d, "base", {"seed.txt": "x\n"})
    _commit(d, "fix(a): w", {"programs/a.py": "1\n"})
    _commit(d, "fix(b): w", {"programs/b.py": "1\n"})
    _commit(d, "fix(c): w [v1.2.3]",
            {"programs/c.py": "1\n", _MANIFEST: '{"version":"1.2.3"}\n'})
    return d, base


# ── the plumbing, both directions ──────────────────────────────────────────
def test_a_real_batch_passes_the_gate_when_declared(tmp_path):
    """THE LOAD-BEARING CASE. Without the flag this same range is a FAIL."""
    d, base = _batch_of_three(tmp_path)
    assert GR.one_commit_gate(d, base, batch=True).rc == 0


def test_the_same_batch_FAILS_when_not_declared(tmp_path):
    """PAIRED HALF. Batch mode is OPT-IN, so a batch cannot happen by
    accident, and the FAIL text still names the flag that would express it."""
    d, base = _batch_of_three(tmp_path)
    res = GR.one_commit_gate(d, base)
    assert res.rc == 1
    assert "--batch" in res.summary, res.summary


def test_declaring_a_batch_does_NOT_excuse_a_stranded_version_commit(tmp_path):
    """The whole reason the flag may exist at all: it must not become a way
    to wave through vibe-ic#459's defect. Reproduced THROUGH the review, not
    only through the checker."""
    d = _repo(tmp_path)
    base = _commit(d, "base", {"seed.txt": "x\n"})
    _commit(d, "fix(a): w", {"programs/a.py": "1\n"})
    _commit(d, "fix(a): w [v1.2.3]", {_MANIFEST: '{"version":"1.2.3"}\n'})
    res = GR.one_commit_gate(d, base, batch=True)
    assert res.rc == 1
    assert "manifest" in res.summary.lower(), res.summary


def test_declaring_a_batch_does_NOT_excuse_two_version_bumps(tmp_path):
    d = _repo(tmp_path)
    base = _commit(d, "base", {"seed.txt": "x\n"})
    _commit(d, "fix(a): w [v1.2.3]",
            {"programs/a.py": "1\n", _MANIFEST: '{"version":"1.2.3"}\n'})
    _commit(d, "fix(b): w [v1.2.4]",
            {"programs/b.py": "1\n", _MANIFEST: '{"version":"1.2.4"}\n'})
    assert GR.one_commit_gate(d, base, batch=True).rc == 1


def test_declaring_a_batch_does_NOT_excuse_a_version_that_is_not_the_tip(
        tmp_path):
    """CI runs on the pushed tip. A version buried mid-batch means green CI
    refers to a tree nobody released."""
    d = _repo(tmp_path)
    base = _commit(d, "base", {"seed.txt": "x\n"})
    _commit(d, "fix(a): w [v1.2.3]",
            {"programs/a.py": "1\n", _MANIFEST: '{"version":"1.2.3"}\n'})
    _commit(d, "fix(b): w", {"programs/b.py": "1\n"})
    res = GR.one_commit_gate(d, base, batch=True)
    assert res.rc == 1
    assert "tip" in res.summary, res.summary


# ── the single-landing rule is untouched ───────────────────────────────────
def test_a_single_squashed_landing_still_passes_without_the_flag(tmp_path):
    d = _repo(tmp_path)
    base = _commit(d, "base", {"seed.txt": "x\n"})
    _commit(d, "fix(x): w [v1.2.3]",
            {"programs/a.py": "1\n", _MANIFEST: '{"version":"1.2.3"}\n'})
    assert GR.one_commit_gate(d, base).rc == 0


def test_the_amend_slip_still_fails_without_the_flag(tmp_path):
    """vibe-ic#459's exact shape. The flag must not have quietly widened the
    default."""
    d = _repo(tmp_path)
    base = _commit(d, "base", {"seed.txt": "x\n"})
    _commit(d, "fix(x): w", {"programs/a.py": "1\n"})
    _commit(d, "fix(x): w [v1.2.3]", {_MANIFEST: '{"version":"1.2.3"}\n'})
    assert GR.one_commit_gate(d, base).rc == 1


def test_nothing_to_land_is_still_not_a_pass_in_either_mode(tmp_path):
    """rc 0 must never mean 'I examined a range with no landing in it'."""
    d = _repo(tmp_path)
    base = _commit(d, "base", {"seed.txt": "x\n"})
    assert GR.one_commit_gate(d, base).rc == 1
    assert GR.one_commit_gate(d, base, batch=True).rc == 1


def test_an_uncountable_range_is_a_SKIP_not_a_pass_in_batch_mode(tmp_path):
    """rc 2 from the checker means NOT CHECKED. It must stay a skip (-1) and
    never be reported as a green gate, in either mode."""
    d = _repo(tmp_path)
    _commit(d, "base", {"seed.txt": "x\n"})
    for batch in (False, True):
        res = GR.one_commit_gate(d, "NOSUCHREF", batch=batch)
        assert res.rc == -1, (batch, res.summary)


# ── the two wiring hops, each DRIVEN, and each cheap ──────────────────────
#
# THE TEST THIS FILE MOST NEEDED, and the one I got wrong TWICE.
#
# Attempt 1 asserted that the SOURCE TEXT contained the call
# `one_commit_gate(repo, base, batch=args.batch)`. It passed while that exact
# line raised `NameError: name 'args' is not defined` — `args` is bound in
# `main()`, the call site is in `review()`. A test that reads the source
# instead of running it certified a program that could not run.
#
# Attempt 2 drove the whole `gatekeeper_review` CLI twice. That is honest, and
# it TIMED OUT in CI (`--timeout` per test, 2-core runner): the review scans
# the plugin root, runs the full audit and the chip-agnostic guard over
# thousands of files, none of which this test is about. A test that cannot
# finish is not a stricter test, it is a red main.
#
# The repair is to keep BOTH hops driven and make each one cheap:
#
#   argparse -> review()   captured at the call site in `main()`, so the real
#                          parser and the real call are exercised;
#   review() -> the gate   driven for real against a TINY plugin_root, which
#                          makes the unrelated heavy gates trivial while the
#                          landing gate does exactly what it does in
#                          production (~0.4s).
#
# Neither hop is asserted from source text, and neither pays for the other's
# work.
def _tiny_plugin_root(tmp_path: Path) -> Path:
    """A plugin root with nothing in it, so the scanning gates cost nothing.
    The landing gate does not read it at all."""
    root = tmp_path / "tiny-plugin"
    (root / ".claude-plugin").mkdir(parents=True)
    (root / ".claude-plugin" / "plugin.json").write_text('{"version":"1.0.0"}\n')
    return root


def _landing_gate_rc(project: Path, base: str, tmp_path: Path,
                     batch: bool) -> int:
    v = GR.review(base, "HEAD", repo=project,
                  plugin_root=_tiny_plugin_root(tmp_path), batch=batch)
    gates = {g.name: g.rc for g in v.gates}
    assert "landing_is_one_commit_check" in gates, gates
    return gates["landing_is_one_commit_check"]


def test_the_flag_reaches_the_gate_through_review(tmp_path):
    """HOP 2, driven. This is the hop the NameError was on."""
    d, base = _batch_of_three(tmp_path)
    assert _landing_gate_rc(d, base, tmp_path / "a", batch=True) == 0
    assert _landing_gate_rc(d, base, tmp_path / "b", batch=False) == 1


def test_the_flag_reaches_review_through_argparse(tmp_path, monkeypatch):
    """HOP 1, driven. The real parser, the real call site in `main()` — only
    the review body is stood in for, because it is hop 2's job and it is
    tested above."""
    seen = {}

    def _spy(base, head, **kw):
        seen.update(kw, base=base, head=head)
        raise RuntimeError("stop here — the wiring is what is under test")

    monkeypatch.setattr(GR, "review", _spy)
    d, base = _batch_of_three(tmp_path)
    for flags, expected in (([], False), (["--batch"], True)):
        seen.clear()
        GR.main(["--repo", str(d), "--base", base, "--head", "HEAD"] + flags)
        assert seen.get("batch") is expected, (flags, seen)
