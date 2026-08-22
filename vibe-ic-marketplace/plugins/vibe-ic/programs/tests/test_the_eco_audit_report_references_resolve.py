#!/usr/bin/env python3
"""`ppa-eco-axis-audit/RESULT.md` cites things; this checks they exist.

WHY THIS EXISTS, measured rather than supposed
==============================================
Three times while writing that report a reference went stale and nothing said so:

  1. the base branch it was cut from was DELETED on the remote, so six commands
     in it stopped being runnable -- found only when one of them failed;
  2. a commit's own message claimed to be "THE ONE COMMIT ... that changes
     caller-visible behaviour" after two more such commits existed;
  3. a rename left the document citing `next/honest-tripwire-framing`, a ref
     that had just been deleted -- a reader following it gets `unknown
     revision`, which reads as repo damage rather than a document that moved on.

Every one was caught by a command failing or a deliberate sweep. None was caught
by the document, because prose has no referential integrity: a name in a sentence
is not a name anything resolves. Shas and paths CAN be resolved, so they are.

WHAT THIS DOES NOT CHECK, and cannot
====================================
Case 2 above is a claim about MEANING ("this is the only one") and no resolver
catches it. That class stays a reading problem. This file narrows the surface to
the part a machine can hold, and says so rather than implying full coverage.

A BRANCH NAME IS ALLOWED TO DIE. Branches are deleted as a matter of course --
the base branch here was deleted because it LANDED, which is success. So a name
that no longer resolves is only a defect when the document presents it as live.
The rule is therefore: a cited branch must resolve, OR the document must say near
it that it is gone. That is checkable, and it is what the report already does for
the base.
"""
import pathlib
import re
import subprocess
import sys

import pytest

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
_ROOT_WITNESS = "vibe-ic-marketplace"


def _repo_root():
    """The repo root, or a FAILURE -- never a silent skip. See the sibling
    file `test_ppa_eco_axis_bites_in_the_search_lane.py` for why the anchor is
    checked: a stale path calculation would make every row here skip and report
    NOT OBSERVED about a tree it never looked at."""
    root = _PROGRAMS.parents[3]
    assert (root / _ROOT_WITNESS).is_dir(), (
        f"repo-root anchor resolved to {root}, which carries no "
        f"`{_ROOT_WITNESS}` -- the path arithmetic is stale")
    return root


def _report():
    p = _repo_root() / "ppa-eco-axis-audit" / "RESULT.md"
    if not p.is_file():
        pytest.skip(f"{p} is not in this checkout; NOT OBSERVED")
    return p


def _git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args],
                          capture_output=True, text=True)


def test_every_sha_the_report_cites_resolves_to_a_commit():
    """A 9-hex token in the prose that names no object is a dead citation."""
    root = _repo_root()
    text = _report().read_text(encoding="utf-8")
    shas = sorted(set(re.findall(r"\b[0-9a-f]{9}\b", text)))
    assert shas, "no shas cited at all; this row would pass vacuously"
    dead = [s for s in shas
            if _git(root, "cat-file", "-e", f"{s}^{{commit}}").returncode]
    assert not dead, (
        f"{len(dead)} of {len(shas)} cited sha(s) resolve to no commit in this "
        f"repository: {dead}")


def test_every_repo_path_the_report_cites_exists():
    """A path in backticks that is not there sends a reader hunting."""
    root = _repo_root()
    text = _report().read_text(encoding="utf-8")
    paths = sorted(set(re.findall(
        r"`((?:vibe-ic-marketplace|tools|ppa-[a-z-]+|docs)/[A-Za-z0-9._/-]+)`",
        text)))
    assert paths, "no repo paths cited at all; this row would pass vacuously"
    missing = [p for p in paths if not (root / p).exists()]
    assert not missing, (
        f"{len(missing)} of {len(paths)} cited path(s) do not exist: {missing}")


def test_a_cited_branch_either_resolves_or_is_said_to_be_gone():
    """The rule that lets a branch die honestly.

    Branches are deleted as a matter of course -- the base branch of this work
    was deleted because it LANDED. So a dead name is only a defect when the
    document presents it as live. Each cited branch must therefore resolve, or
    carry a nearby word saying it does not.
    """
    root = _repo_root()
    text = _report().read_text(encoding="utf-8")
    lines = text.splitlines()
    cited = sorted(set(re.findall(
        r"`((?:next|jeco2|land|fix|capture|agent|ptmo)/[A-Za-z0-9._/-]+)`",
        text)))
    assert cited, "no branch names cited at all; this row would pass vacuously"

    remote = _git(root, "ls-remote", "--heads", "origin").stdout
    unexplained = []
    for name in cited:
        if f"refs/heads/{name}\n" in remote or f"refs/heads/{name}\t" in remote:
            continue
        if _git(root, "rev-parse", "--verify", name).returncode == 0:
            continue
        # gone -- is the document honest about it within a few lines?
        idx = [i for i, l in enumerate(lines) if f"`{name}`" in l]
        near = " ".join(" ".join(lines[max(0, i - 3):i + 4]) for i in idx)
        if re.search(r"delet|no longer|gone|has been removed|was deleted",
                     near, re.I):
            continue
        unexplained.append(name)
    assert not unexplained, (
        f"{unexplained} do not resolve and the report does not say so near "
        f"where it cites them; a reader following one gets `unknown revision`, "
        f"which reads as repo damage rather than a name that moved on")
