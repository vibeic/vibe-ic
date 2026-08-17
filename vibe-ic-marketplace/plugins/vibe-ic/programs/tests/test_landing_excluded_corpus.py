#!/usr/bin/env python3
"""The landing gate's DECLARED exclusions must be able to go red both ways.

The registry answers "what does the landing gate deliberately not run, and
why". A registry that cannot disagree with the tree is a comment: it would keep
printing PASS while the marker it names was renamed away (so the landing gate
quietly runs what this file says it does not), or while somebody typed the
marker onto a regression test (so the landing gate quietly stops running
something, with no reason, subject or owner on the record).

Both directions are driven here on SCRATCH COPIES of the real modules, so the
control is over the real declaration rather than over a fixture invented to
satisfy it.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from _plugin_tree import plugin_path, repo_path_or_missing

PROG = plugin_path("programs", "landing_excluded_corpus.py")
REPO = PROG.parents[4]

sys.path.insert(0, str(PROG.parent))
import landing_excluded_corpus as REG  # noqa: E402


def _run(*args, repo=None):
    argv = [sys.executable, str(PROG)]
    if repo is not None:
        argv += ["--repo", str(repo)]
    argv += list(args)
    # 55 s, NOT the 180 s harness bound. `ci_harness_timeout_ceiling_check`
    # holds every inner subprocess bound in the targeted subset under a 60 s
    # ceiling, and it is right: an inner bound at or above the harness's own
    # does not fail a test, it outlives the harness and takes the SESSION down.
    # This program is a static `ast` scan of four files and runs in under 2 s.
    return subprocess.run(argv, capture_output=True, text=True, timeout=55)


# ── THE DECLARATION ITSELF ────────────────────────────────────────────────

def test_the_registry_is_not_empty_and_refuses_when_it_would_be():
    """A zero denominator refuses. An empty registry is not 'nothing is
    excluded'; it is a registry nobody can check in either direction."""
    assert REG.entries(), "the registry is empty; see the REFUSED path in main()"
    assert all(e.why.strip() and e.subject.strip() and e.owner.strip()
               for e in REG.entries())


def test_every_declared_node_names_a_tree_some_landing_arm_filters():
    """`run_unselectable_pytest` passes no `-m`, so a marker there is inert."""
    for e in REG.entries():
        assert any(e.path.startswith(p) for p in REG._MARKER_HONOURED), e


def test_the_audit_is_green_on_this_tree():
    r = _run("--audit", repo=REPO)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "[PASS]" in r.stdout, r.stdout
    # The denominator, on the record: a gate that will not say how much it
    # looked at cannot be audited.
    assert "declared exclusion(s)" in r.stdout and "tracked test file" in r.stdout


# ── DIRECTION 1: a declared node that lost its marker ─────────────────────

def test_a_declared_node_without_the_marker_is_a_finding(tmp_path):
    """The landing gate would be RUNNING it while the registry says it is not."""
    scratch = _clone(tmp_path)
    victim = REG.entries()[0]
    target = scratch / victim.path
    text = target.read_text(encoding="utf-8")
    stripped = text.replace(f"@pytest.mark.{REG.MARKER}\n", "", 1)
    assert stripped != text, "the fixture removed nothing; it proves nothing"
    target.write_text(stripped, encoding="utf-8")

    r = _run("--audit", repo=scratch)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "carries no @pytest.mark" in r.stdout, r.stdout


# ── DIRECTION 2: a marked node nobody declared ────────────────────────────

def test_an_undeclared_marked_node_is_a_finding(tmp_path):
    """The direction a silent glob exclusion hides in.

    A regression test can be removed from every landing by typing one
    decorator. Without this half, nothing would ever say so.
    """
    scratch = _clone(tmp_path)
    planted = scratch / "tools" / "test_planted_for_this_control.py"
    planted.write_text(
        "import pytest\n\n\n"
        f"@pytest.mark.{REG.MARKER}\n"
        "def test_planted():\n    assert True\n",
        encoding="utf-8")
    subprocess.run(["git", "-C", str(scratch), "add", "-A"],
                   check=True, capture_output=True)

    r = _run("--audit", repo=scratch)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "is NOT declared here" in r.stdout, r.stdout


# ── THE NUMBER THE SHELL ASSERTS ON ───────────────────────────────────────

def test_expected_items_is_derived_from_parametrize_arity_not_typed():
    """`run_repo_tools_pytest` compares this with pytest's own `N deselected`.

    Seven declared FUNCTIONS under tools/ expand to nine ITEMS, because one is
    parametrized over three fields. A hand-typed 7 would make the shell's
    assertion fail on a correct run, and a hand-typed 9 would stop tracking the
    source the day the parametrize list changes.
    """
    total, notes = REG.expected_items(REPO, "tools/")
    functions = sum(1 for e in REG.entries() if e.path.startswith("tools/"))
    assert total is not None, notes
    assert total > functions, (total, functions, notes)


def test_a_declared_path_absent_from_the_tree_is_skipped_here_and_caught_there(tmp_path):
    """Two questions, two owners, and the split is deliberate.

    `expected_items` is asked by a shell function that is generic over its root
    (the repo-tools gate's own control drives it against a throwaway repo), so
    an absent file must not refuse. `audit()` is asked about THE REPOSITORY, so
    an absent file must be a finding there.
    """
    scratch = _clone(tmp_path)
    (scratch / "tools" / "test_d9_flow_gate_reality.py").unlink()

    total, _notes = REG.expected_items(scratch, "tools/")
    assert total == 0

    r = _run("--audit", repo=scratch)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "does not exist" in r.stdout, r.stdout


# ── THE ENTRY POINT THAT OWNS THEM NOW ────────────────────────────────────

def test_the_named_entry_point_exists_and_asks_the_registry_for_its_list():
    """The campaign tier must not carry a second roster; the two would drift
    and the drift direction is 'the campaign tier quietly stopped running
    something'."""
    entry = repo_path_or_missing("tools", "run_campaign_tier.sh")
    if entry is None or not Path(entry).is_file():
        pytest.skip("tools/run_campaign_tier.sh not resolvable from here")
    body = Path(entry).read_text(encoding="utf-8")
    assert "landing_excluded_corpus.py" in body
    assert "--select-expr" in body and "--paths" in body
    assert "NOTHING SCHEDULES THIS YET" in body, (
        "the entry point must keep saying that nothing calls it; that is an "
        "open owner decision and a reader must not have to infer it")


def _clone(tmp_path: Path) -> Path:
    """A throwaway git repo carrying the real files this registry names."""
    scratch = tmp_path / "repo"
    (scratch / "tools").mkdir(parents=True)
    subprocess.run(["git", "-C", str(scratch), "init", "-q"],
                   check=True, capture_output=True)
    for rel in set(list(REG.paths()) + [
            "vibe-ic-marketplace/plugins/vibe-ic/programs/"
            "landing_excluded_corpus.py"]):
        dst = scratch / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO / rel, dst)
    subprocess.run(["git", "-C", str(scratch), "add", "-A"],
                   check=True, capture_output=True)
    return scratch
