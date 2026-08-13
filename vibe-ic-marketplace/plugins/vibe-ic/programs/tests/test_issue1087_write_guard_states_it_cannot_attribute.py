#!/usr/bin/env python3
"""The whole-tier write guard must say that it cannot name a writer. #1087.

THE DEFECT #1087 MEASURED
=========================
The landing tier has two write guards and neither can do the job alone:

  A. `_gate_dispatch.sh`, per gate, CAN attribute — and watches only
     `$GATE_DISPATCH_CORPUS_REL` (`benchmark-data`).
  B. `gatekeeper-land.sh:328`, ONE snapshot/compare pair spanning `run_pytest`
     + ~74 hygiene gates + `plugin_full_audit`, sees the whole tree and names
     PATHS, never a gate.

A write outside the corpus is therefore detected by B and attributable by
neither. #1087 recorded what that cost: a tier write was reported against
`63x8 census freshness`, a gate that provably does not write, because a reader
took the nearest gate name off the log.

WHAT THIS PINS, AND WHAT IT DELIBERATELY DOES NOT
=================================================
It pins that B's output SAYS it cannot attribute. It does not give B the
ability to attribute — that is the larger flow-level change #1087 defers, and
it needs a full-tier zero-false-positive sweep behind it. No verdict changes
here and no new failure is introduced; what is removed is an invitation to a
false accusation.

The disclaimer is conditional ON PURPOSE. The pytest plugin's window IS one
session and its report names it, so printing "cannot attribute" there would be
its own false statement. A blanket disclaimer would trade one wrong sentence
for another.
"""
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parent.parent.parent
PROGRAMS = PLUGIN / "programs"
sys.path.insert(0, str(PROGRAMS))

_spec = importlib.util.spec_from_file_location(
    "_swg1087", PROGRAMS / "suite_write_guard.py")
G = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(G)

#: The load-bearing claim. Kept as a constant so the mutant control below and
#: the assertions cannot drift apart.
CANNOT_ATTRIBUTE = "THIS FINDING NAMES PATHS, NOT A WRITER"



def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo)] + list(args),
                   check=True, capture_output=True)


@pytest.fixture()
def repo(tmp_path):
    r = tmp_path / "r"
    (r / "sub").mkdir(parents=True)
    _git_init = subprocess.run(["git", "init", "-q", str(r)],
                               capture_output=True)
    assert _git_init.returncode == 0
    (r / "sub" / "tracked.txt").write_text("one\n")
    _git(r, "add", "-A")
    _git(r, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "i")
    return r


def _run_cli(repo, tmp_path, mutate):
    """Drive the REAL `--snapshot` / `--compare` path, not `format_report`.

    Asserting on the helper would pin the helper and leave the wiring free: the
    defect #1087 is about what the tier's entry point prints, so the test has to
    go through that entry point.
    """
    base = tmp_path / "base.json"
    assert G._main(["--repo", str(repo), "--snapshot", str(base)]) == G.RC_CLEAN
    mutate(repo)
    return G._main(["--repo", str(repo), "--compare", str(base)])


def test_the_whole_tier_arm_says_it_cannot_name_a_writer(repo, tmp_path, capsys):
    rc = _run_cli(repo, tmp_path,
                  lambda r: (r / "sub" / "tracked.txt").write_text("two\n"))
    out = capsys.readouterr().out
    assert rc == G.RC_WROTE, out
    assert "WROTE INTO THE TREE" in out
    assert CANNOT_ATTRIBUTE in out, out
    # and it must point at the instrument gap rather than just hedging
    assert "vibe-ic#1087" in out
    assert "GATE_DISPATCH_CORPUS_REL" in out


def test_it_still_names_every_offending_path(repo, tmp_path, capsys):
    """The disclaimer must not replace the paths. #1029: 'It must name every
    offending path, not just fail.'"""
    rc = _run_cli(repo, tmp_path,
                  lambda r: (r / "sub" / "tracked.txt").write_text("two\n"))
    out = capsys.readouterr().out
    assert rc == G.RC_WROTE
    assert "sub/tracked.txt" in out, out


def test_a_clean_run_says_nothing_about_attribution(repo, tmp_path, capsys):
    """The sentence is about a FINDING. Printing it on a clean run would make
    every green tier report read as if something had been found and could not
    be blamed."""
    rc = _run_cli(repo, tmp_path, lambda r: None)
    out = capsys.readouterr().out
    assert rc == G.RC_CLEAN, out
    assert CANNOT_ATTRIBUTE not in out


def test_the_pytest_session_arm_does_NOT_claim_it_cannot_attribute():
    """The conditional half, and the reason `can_attribute` is a parameter
    rather than a constant string appended everywhere.

    The in-process plugin's window is ONE pytest session and its report names
    it. Telling a reader that report cannot identify a writer would be a false
    statement in the opposite direction — the session IS the writer.
    """
    result = {"blocking": [{"path": "a/b.json", "status": "M",
                            "what": "content changed", "class": "tracked"}],
              "advisory": [], "findings": []}
    session = G.format_report(result, where="this pytest session")
    tier = G.format_report(result, where="the run against /x",
                           can_attribute=False)
    assert CANNOT_ATTRIBUTE not in session
    assert CANNOT_ATTRIBUTE in tier
    # both still name the path
    assert "a/b.json" in session and "a/b.json" in tier


def test_default_is_attributable_so_a_new_caller_cannot_silently_inherit_a_hedge():
    """`can_attribute` defaults to True. A future caller that genuinely can
    attribute must not have to opt OUT of a disclaimer, and one that cannot
    must say so deliberately."""
    import inspect
    sig = inspect.signature(G.format_report)
    assert sig.parameters["can_attribute"].default is True


def test_the_cli_compare_entry_point_opts_out_deliberately():
    """Source pin on the WIRING, because that is the half a helper test cannot
    see: the tier entry point must pass can_attribute=False. Accepts either
    spelling of the call so a reformat does not break it, and fails loudly when
    neither is present rather than passing with nothing to measure."""
    src = (PROGRAMS / "suite_write_guard.py").read_text(encoding="utf-8")
    spellings = ("can_attribute=False", "can_attribute = False")
    assert any(s in src for s in spellings), (
        f"none of {spellings} appears in suite_write_guard.py, so the tier "
        "entry point is not opting out of attribution it cannot perform")
