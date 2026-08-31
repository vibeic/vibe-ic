#!/usr/bin/env python3
"""A commit's protected manifest must describe the tree that commit ships.

Both directions, because a gate that refuses everything passes its own test:
a commit whose manifest DOES describe its tree must be rc 0, and one whose
manifest was rendered elsewhere must be rc 1 naming the drifted paths.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
REPO = PROGRAMS.parents[3]
sys.path.insert(0, str(PROGRAMS))
import transition_manifest_describes_its_tree_check as C  # noqa: E402

MANIFEST_REL = "tools/ci/protected_landing_transition.json"


def _has_manifest(ref: str) -> bool:
    return subprocess.run(["git", "-C", str(REPO), "cat-file", "-e",
                           f"{ref}:{MANIFEST_REL}"],
                          capture_output=True).returncode == 0


def test_a_bad_ref_is_undetermined_and_names_what_it_could_not_read():
    """`I could not look` is never a finding about the tree."""
    rc, msg = C.check(REPO, "no-such-ref-4b19c")
    assert rc == 2, (rc, msg)
    assert "no-such-ref-4b19c" in msg
    assert "UNDETERMINED" in msg


def test_a_commit_whose_manifest_describes_its_tree_passes():
    """rc 0 MUST be reachable. Without this the check could refuse every input
    and its FAIL cases would prove nothing -- a guard with one direction is not
    a guard. Walks back to the most recent commit that matches, so it does not
    depend on today's main being in any particular state."""
    revs = subprocess.run(
        ["git", "-C", str(REPO), "rev-list", "--first-parent", "-400", "HEAD"],
        capture_output=True, text=True).stdout.split()
    for r in revs:
        if not _has_manifest(r):
            continue
        rc, msg = C.check(REPO, r)
        if rc == 0:
            assert "protected tuple is the manifest's" in msg, msg
            return
    pytest.fail("no commit in the last 400 has a manifest describing its own "
                "tree, so this check cannot be shown to pass anything")


def test_a_manifest_rendered_against_another_tree_is_refused_and_names_the_paths():
    """The defect this exists for, MEASURED on batch 72: it shipped
    `current = reauthorised-at-81cd5321b`, rendered two mains earlier, while its
    own tree matched neither of its own states."""
    revs = subprocess.run(
        ["git", "-C", str(REPO), "rev-list", "--first-parent", "-400", "HEAD"],
        capture_output=True, text=True).stdout.split()
    for r in revs:
        if not _has_manifest(r):
            continue
        rc, msg = C.check(REPO, r)
        if rc == 1:
            assert "describes neither of its own states" in msg, msg
            assert "drifted" in msg, msg
            # the paths themselves must be named, not merely counted
            assert any(line.strip().count("/") for line in msg.splitlines()), msg
            return
    pytest.skip("no commit in the last 400 carries a stale manifest -- the "
                "refusal path is unexercised here, which is not the same as "
                "it being wrong")
