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

import evidence_citation_resolves_check as _ecr        # noqa: E402
import _lesson_digest as _ld                           # noqa: E402

_GEN = _PROGRAMS / "final_report_generate.py"

# The #1044 widening, applied here so the generator property is pinned on main.
_WIDENED_EXT = tuple(_ecr._EVIDENCE_EXT) + (".md",)


def _citation_tokens(text: str):
    """Citation-shaped tokens, by the gate's own rules over the widened set."""
    toks = []
    for m in _ecr._CITE_RE.finditer(text):
        tok = m.group(1)
        if not tok.lower().endswith(_WIDENED_EXT):
            continue
        if _ecr._TEMPLATE_RE.search(tok):
            continue
        toks.append(tok)
    return toks


def _unresolved(doc: Path, root: Path, only=None):
    """Citation-shaped tokens in `doc` that do not resolve from `root`."""
    out = []
    for tok in _citation_tokens(doc.read_text(errors="replace")):
        if only is not None and tok != only:
            continue
        if _ecr.resolve_citation(doc, tok, root) is None:
            out.append(tok)
    return out


def _generate(project: Path):
    r = subprocess.run([sys.executable, str(_GEN), str(project), "--no-audit"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    out = project / "reports" / "final_summary.md"
    assert out.is_file(), "generator wrote no final_summary.md"
    return out


# --------------------------------------------------------------------------- #
# final_report_generate.py
# --------------------------------------------------------------------------- #
def test_absent_addendum_is_not_cited_as_a_shipped_artefact(tmp_path):
    doc = _generate(tmp_path)
    assert _unresolved(doc, tmp_path,
                       only="reports/chip_specific_summary.md") == [], (
        "final_summary.md cites reports/chip_specific_summary.md as a shipped "
        "artefact although this run does not ship it")


def test_absent_addendum_is_still_named_in_prose(tmp_path):
    """Paired guard: the fix must not silence the guidance."""
    text = _generate(tmp_path).read_text()
    assert "reports/chip_specific_summary.md" in text
    assert "Author it by hand" in text
    # ...and the Output-#3 pointer still tells the reader where the detail goes.
    assert "chip-specific addendum" in text


def test_present_addendum_is_cited_and_resolves(tmp_path):
    """Paired guard: when the run DOES ship it, it must still be a citation."""
    (tmp_path / "reports").mkdir(parents=True, exist_ok=True)
    (tmp_path / "reports" / "chip_specific_summary.md").write_text("# Chip\n")
    doc = _generate(tmp_path)
    toks = _citation_tokens(doc.read_text())
    assert "reports/chip_specific_summary.md" in toks, (
        "a shipped addendum must still be cited as an artefact")
    assert _ecr.resolve_citation(
        doc, "reports/chip_specific_summary.md", tmp_path) is not None


# --------------------------------------------------------------------------- #
# _lesson_digest.py
# --------------------------------------------------------------------------- #
def test_digest_head_does_not_cite_plugin_source_as_artefact(tmp_path):
    run_p = tmp_path / "run"
    run_p.mkdir()
    n = _ld.render_lesson_digest(run_p)
    assert n > 0, "no lessons rendered; cannot judge the head"
    doc = run_p / "lessons.md"
    dangling = [t for t in _unresolved(doc, tmp_path)
                if t.endswith("ic-expert-agent.md")]
    assert dangling == [], (
        f"rendered lessons.md cites plugin source as a shipped artefact: {dangling}")


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
def test_predicate_still_flags_the_pre_fix_text(tmp_path):
    """The exact strings both generators used BEFORE this fix must be flagged.

    Without this arm the four assertions above could all pass against a
    predicate that flags nothing.
    """
    doc = tmp_path / "reports" / "final_summary.md"
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text(
        "_Per-opcode / per-mode coverage detail belongs in_ "
        "`reports/chip_specific_summary.md` _(this section stays chip-agnostic)._\n"
        "_No `reports/chip_specific_summary.md` present. Author it by hand._\n")
    assert _unresolved(doc, tmp_path,
                       only="reports/chip_specific_summary.md") == [
        "reports/chip_specific_summary.md",
        "reports/chip_specific_summary.md",
    ]

    lessons = tmp_path / "run" / "lessons.md"
    lessons.parent.mkdir(parents=True, exist_ok=True)
    lessons.write_text(
        "Rendered deterministically from the general-pattern `### Skill:` sections\n"
        "of `agents/ic-expert-agent.md`. These are chip-AGNOSTIC patterns captured\n")
    assert _unresolved(lessons, tmp_path,
                       only="agents/ic-expert-agent.md") == [
        "agents/ic-expert-agent.md"]
