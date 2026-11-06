#!/usr/bin/env python3
"""#1168 — two generators wrote citations that can never resolve.

#1168 counted the 40 citations that #1044's scope widening makes newly visible
and attributed 38 of them to pre-existing debt. 24 of those 38 are not per-run
debt at all: they are two GENERATORS each repeating one unresolvable citation
across every run they produced.

  * `final_report_generate.py` backticked `reports/chip_specific_summary.md` in
    two places regardless of whether the run shipped that file (14 entries).
  * `_lesson_digest.py` backticked `agents/ic-expert-agent.md` in the head of
    every rendered `lessons.md` (10 entries). That path is PLUGIN SOURCE; the
    citation resolver's ladder walks the citing document's directory up to the
    scan root and stops, so no spelling of a plugin path can resolve from a run
    tree.

WHY THIS TEST DOES NOT WAIT FOR #1044
-------------------------------------
The property under test belongs to the GENERATOR, not to the gate: "do not
write a backticked path for a file this tree does not ship". `_EVIDENCE_EXT` on
main is (`.log`, `.rpt`, `.sby`), so a `.md` citation is invisible to today's
gate and both defects would be silently reintroducible until #1044 lands. The
tests below therefore evaluate the gate's OWN citation predicate and OWN
resolution ladder over a set widened with `.md` — the same widening #1044
performs — and pin the generator property now.

PAIRED GUARD
------------
Every positive assertion here has a partner that would fail if the fix were
made vacuous:
  * the addendum-ABSENT arms assert the path is still named in prose, so the
    fix cannot be "delete the sentence";
  * the addendum-PRESENT arm asserts the citation IS emitted, backticked, and
    RESOLVES — so the fix cannot be "never backtick anything";
  * `test_predicate_still_flags_the_pre_fix_text` feeds the literal pre-fix
    strings through the same predicate and requires them to be flagged, so the
    predicate itself is proven able to fail.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROGRAMS))

import _lesson_digest as _ld                           # noqa: E402


# The #1044 widening, applied here so the generator property is pinned on main.








# --------------------------------------------------------------------------- #
# final_report_generate.py
# --------------------------------------------------------------------------- #






# --------------------------------------------------------------------------- #
# _lesson_digest.py
# --------------------------------------------------------------------------- #


def test_digest_head_still_names_the_plugin_source(tmp_path):
    """Paired guard: provenance must remain readable, and must say it is not
    shipped here."""
    run_p = tmp_path / "run"
    run_p.mkdir()
    assert _ld.render_lesson_digest(run_p) > 0
    head = (run_p / "lessons.md").read_text()
    assert "vibe-ic-marketplace/plugins/vibe-ic/agents/ic-expert-agent.md" in head
    assert "NOT shipped in this run tree" in head


# --------------------------------------------------------------------------- #
# the predicate has teeth
# --------------------------------------------------------------------------- #
