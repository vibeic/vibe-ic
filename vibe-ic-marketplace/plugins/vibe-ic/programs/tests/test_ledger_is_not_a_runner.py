"""The acknowledgement ledger cannot buy the green it acknowledges.

MEASURED 2026-08-21, by tripping it. `tools/ci/gate_red_since.json` gained its
first rows, one of which reads

    "closed_loop_edge_check, ppa_pr_scope_check and slot_pad_budget_check are
     consulted by no automatic verdict, so the tree looks identical whether
     they would pass or fail."

`gate_is_wired_check` enumerates wiring sources with `tools/ci/*`, so it read
that sentence, found all three names, and counted them WIRED: `unwired` fell
from 61 to 58 and the gate turned PASS. Isolated to that single file on an
otherwise clean tree at 6dfe15a32.

The ledger's own `_doc` promises "there is nothing a row can silence and no
green a row can buy". It was exactly wrong and in the worst direction — the
acknowledgement silenced the finding it acknowledged, so the more honestly a
row described its red, the more certainly it hid it. `executable_text` already
holds this rule for comments inside programs; these tests hold it for the
register.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))
import gate_is_wired_check as G  # noqa: E402
import gate_red_since_check as R  # noqa: E402

REPO = PROGRAMS.parents[3]


def test_the_excluded_path_is_the_ledger_its_owner_declares():
    """Named from the owner's constant rather than retyped, so moving the
    ledger cannot leave this exclusion pointing at nothing — which would
    restore the defect silently."""
    assert R.LEDGER_REL in G._NOT_A_RUNNER


def test_the_shipped_ledger_is_not_read_as_a_wiring_source():
    texts = G._texts(REPO / "vibe-ic-marketplace" / "plugins" / "vibe-ic",
                     REPO, G._EXECUTABLE_GLOBS, G._REPO_GLOBS)
    read = {Path(p).resolve() for p, _ in texts}
    assert (REPO / R.LEDGER_REL).resolve() not in read


def test_a_row_naming_a_gate_does_not_make_that_gate_wired(tmp_path):
    """The regression itself, staged: a ledger that names a program must not
    put that program's name into the corpus the wiring scan searches."""
    repo = tmp_path
    (repo / "tools" / "ci").mkdir(parents=True)
    (repo / R.LEDGER_REL).write_text(json.dumps({"acknowledged": [{
        "gate": "gates are wired to something",
        "since": "0" * 40, "max_commits": 10,
        "why": "totally_invented_check is consulted by no automatic verdict"}]}),
        encoding="utf-8")
    plugin = repo / "plugin"
    (plugin / "programs").mkdir(parents=True)
    texts = G._texts(plugin, repo, (), G._REPO_GLOBS)
    blob = "\n".join(t for _, t in texts)
    assert "totally_invented_check" not in blob, (
        "the ledger's text reached the wiring scan, so acknowledging a red is "
        "again a way to silence it")


def test_other_files_under_tools_ci_are_still_read(tmp_path):
    """The direction that keeps the exclusion honest. `tools/ci/*` is where
    several gates have their ONLY caller — narrowing it too far would hide real
    wiring and shrink the baseline, which is the same defect facing the other
    way."""
    repo = tmp_path
    (repo / "tools" / "ci").mkdir(parents=True)
    (repo / R.LEDGER_REL).write_text("{}", encoding="utf-8")
    (repo / "tools" / "ci" / "some_runner.sh").write_text(
        'python3 "$PG/really_wired_check.py"\n', encoding="utf-8")
    plugin = repo / "plugin"
    (plugin / "programs").mkdir(parents=True)
    blob = "\n".join(t for _, t in G._texts(plugin, repo, (), G._REPO_GLOBS))
    assert "really_wired_check" in blob
