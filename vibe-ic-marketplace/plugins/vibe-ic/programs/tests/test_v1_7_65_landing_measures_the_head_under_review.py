#!/usr/bin/env python3
"""The landing-shape gate must measure the branch UNDER REVIEW, not the
reviewer's own checkout.

THE DEFECT (mine, found while reviewing a PR)
=============================================
`head_is_one_commit` hard-coded `base..HEAD`, and `gatekeeper_review` never
forwarded the `--head` it was reviewing. So a review of somebody else's branch
counted the REVIEWER'S working checkout.

Reproduced end to end, and pinned below as the load-bearing test: park the
working tree on a clean one-commit landing, then review a three-commit branch
whose tip carries ONLY the version manifests — this program's exact defect
shape, the one vibe-ic#459 documents four instances of — and the old code
answered

    [PASS] landing_is_one_commit: one commit ahead of <base> — a squashed landing

rc 0. The gate that exists to catch an unsquashed landing certified one, over
a tree nobody was reviewing. It is the false-certificate class this repo keeps
closing: an answer that is indistinguishable from a real clean result and is
about the wrong thing.

The comment sitting above the call site made it worse by describing behaviour
the code did not have — it claimed a synthetic head ref would make the range
uncountable so the gate would skip. Nothing of the sort happened; `head` was
simply discarded. So a reader auditing the wiring would have been reassured by
prose instead of alerted by it.

WHAT IS PINNED HERE
===================
1. the false certificate cannot come back (the load-bearing case);
2. the pre-push default is unchanged, so the gatekeeper's own use is not
   disturbed;
3. an unresolvable head is rc 2 / NOT CHECKED — never a verdict about some
   other branch, and never a pass;
4. batch mode reads the same head, because the batch shape is just as easy to
   measure on the wrong tree;
5. the flag reaches the gate THROUGH `gatekeeper_review`, driven, not read out
   of the source — a source-text assertion passes while the call it names
   raises at runtime, which is how the sibling `--batch` wiring shipped broken.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROGRAMS))
import landing_is_one_commit_check as L  # noqa: E402
import gatekeeper_review as GR  # noqa: E402

_PROG = _PROGRAMS / "landing_is_one_commit_check.py"
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


def _git(d: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(d), *args],
                          capture_output=True, text=True).stdout.strip()


def _the_situation(tmp_path: Path):
    """The exact shape that produced the false certificate.

    working checkout : `clean_land`, ONE squashed commit — innocent
    under review     : `prhead`, THREE commits, tip carries only the manifest
    """
    d = _repo(tmp_path)
    base = _commit(d, "base", {"seed.txt": "x\n"})
    subprocess.run(["git", "-C", str(d), "checkout", "-q", "-b", "prhead"],
                   check=True)
    _commit(d, "fix(x): work", {"programs/a.py": "1\n"})
    _commit(d, "fix(x): more", {"programs/b.py": "1\n"})
    _commit(d, "fix(x): work [v1.2.3]", {_MANIFEST: '{"version":"1.2.3"}\n'})
    subprocess.run(["git", "-C", str(d), "checkout", "-q", base], check=True)
    subprocess.run(["git", "-C", str(d), "checkout", "-q", "-b", "clean_land"],
                   check=True)
    _commit(d, "fix(y): clean landing [v1.2.4]",
            {"programs/c.py": "1\n", _MANIFEST: '{"version":"1.2.4"}\n'})
    return d, base


# ── the load-bearing case ──────────────────────────────────────────────────
def test_reviewing_an_unsquashed_branch_from_a_clean_checkout_FAILS(tmp_path):
    """THE DEFECT. rc 0 here meant 'the reviewer's own branch is tidy'."""
    d, base = _the_situation(tmp_path)
    assert _git(d, "rev-parse", "--abbrev-ref", "HEAD") == "clean_land"
    assert _git(d, "rev-list", "--count", f"{base}..HEAD") == "1"
    assert _git(d, "rev-list", "--count", f"{base}..prhead") == "3"

    ok, n, detail = L.head_is_one_commit(d, base, head="prhead")
    assert not ok and n == 3, detail


def test_the_same_call_without_head_still_answers_about_the_checkout(tmp_path):
    """PAIRED HALF #1 — the pre-push use is unchanged, so the gatekeeper's own
    workflow is not disturbed by the repair."""
    d, base = _the_situation(tmp_path)
    ok, n, _ = L.head_is_one_commit(d, base)
    assert ok and n == 1


def test_batch_mode_reads_the_head_under_review_too(tmp_path):
    """PAIRED HALF #2 — a batch is just as easy to measure on the wrong tree.
    `prhead` has a manifest-only tip, which batch mode must reject."""
    d, base = _the_situation(tmp_path)
    ok, _n, detail = L.head_is_one_commit(d, base, batch=True, head="prhead")
    assert not ok
    assert "manifest" in detail.lower(), detail


def test_an_unresolvable_head_is_NOT_CHECKED_not_a_verdict(tmp_path):
    """rc 2. 'I could not look at that ref' must never read as either a pass
    or a block — it is a statement about a branch this program never saw."""
    d, base = _the_situation(tmp_path)
    ok, n, _ = L.head_is_one_commit(d, base, head="NOSUCHREF")
    assert not ok and n == -1
    assert L.main([str(d), "--base", base, "--head", "NOSUCHREF"]) == 2


# ── through the CLI, driven ────────────────────────────────────────────────
def _cli(d: Path, base: str, extra: list, out: Path) -> int:
    r = subprocess.run(
        [sys.executable, str(_PROG), str(d), "--base", base,
         "--json", str(out)] + extra, capture_output=True, text=True)
    return r.returncode


def test_the_CLI_reports_which_head_it_measured(tmp_path):
    """The emitted record must name the ref, or a reader cannot tell which
    tree the verdict is about — which is the whole defect."""
    d, base = _the_situation(tmp_path)
    out = tmp_path / "v.json"
    assert _cli(d, base, ["--head", "prhead"], out) == 1
    rec = json.loads(out.read_text())
    assert rec["head"] == "prhead", rec
    assert rec["commits"] == 3, rec

    assert _cli(d, base, [], out) == 0
    assert json.loads(out.read_text())["head"] == "HEAD"


# ── through gatekeeper_review, driven (not read out of the source) ─────────
def test_the_review_forwards_the_head_it_was_given(tmp_path):
    """The wiring defect lived BETWEEN the review and the checker, so
    exercising the checker alone would not have caught it. This drives the
    review's own gate function on the situation that produced the false
    certificate."""
    d, base = _the_situation(tmp_path)
    assert GR.one_commit_gate(d, base, "prhead").rc == 1
    assert GR.one_commit_gate(d, base, "HEAD").rc == 0


def test_the_review_body_measures_the_reviewed_branch(tmp_path):
    """Through the real `review()`, which is where the head has to survive.

    Deliberately NOT the full CLI: the review scans the plugin root and runs
    the full audit, none of which this test is about, and a sibling test that
    did drive the whole CLI TIMED OUT in CI and reddened main. Pointing
    `plugin_root` at an empty directory makes the unrelated gates trivial
    while the landing gate does exactly what it does in production. The
    argparse hop is covered separately below."""
    d, base = _the_situation(tmp_path)
    root = tmp_path / "tiny-plugin"
    (root / ".claude-plugin").mkdir(parents=True)
    (root / ".claude-plugin" / "plugin.json").write_text('{"version":"1.0.0"}\n')

    v = GR.review(base, "prhead", repo=d, plugin_root=root)
    gates = {g.name: g.rc for g in v.gates}
    assert gates.get("landing_is_one_commit_check") == 1, gates

    v2 = GR.review(base, "HEAD", repo=d, plugin_root=root)
    gates2 = {g.name: g.rc for g in v2.gates}
    assert gates2.get("landing_is_one_commit_check") == 0, gates2


def test_argparse_hands_the_head_to_the_review(tmp_path, monkeypatch):
    """The other hop, driven. The real parser and the real call site; only the
    review body is stood in for, because the test above owns that half."""
    seen = {}

    def _spy(base, head, **kw):
        seen.update(kw, base=base, head=head)
        raise RuntimeError("stop here — the wiring is what is under test")

    monkeypatch.setattr(GR, "review", _spy)
    d, base = _the_situation(tmp_path)
    GR.main(["--repo", str(d), "--base", base, "--head", "prhead"])
    assert seen.get("head") == "prhead", seen
