"""A backtick says "identifier". It does not say "module". And a citation must
be true of the NAME, not just of the path.

WHAT WAS MEASURED (#1005)
=========================
Re-running the shipped ``phase1_one_shot_runner`` over the 74 published run
roots that carry redistributable input documents (of 107; the other 33 have no
``input/docs/`` and are NO-INPUT, not zero), ``L9.submodules`` holds 80
entries. Nineteen of them name something that is not a module and never could
be, in two distinct shapes:

  PROSE TOKEN IN A SENTENCE (4) -- the bullet walker accepts any backticked
  identifier under a submodule-ish heading, so a config key quoted in a
  measurement sentence (``the minimum pad spacing is `min_distance = 0.1` um``)
  and a top-level PORT quoted in a behaviour sentence (``Checks if
  `priority_override` is non-zero``) both became declared submodules. The same
  shape is how a Verilog reserved word got in: a sentence that quotes ``signed``
  in order to FORBID it.

  A NAME NO DOCUMENT EVER WROTE (15) -- two producers do not extract a name,
  they MINT one. A literal picker maps a spec token found in prose through a
  hand-kept table to a synthesized identifier, and a README walker SLUGIFIES a
  prose bullet into one. Both then cite a source FILE AND LINE that does not
  contain the name they published.

TWO RULES, NEITHER OF THEM A LIST
=================================
A deny list of reserved keywords already existed on ``main`` for the ``signed``
case. It is a maintained list and it did not close the class: re-run today, the
same walker still emits ``min_distance`` and ``priority_override``, which are
not keywords. So neither rule below reads a vocabulary.

  POSITION -- a bullet that DECLARES a submodule leads with the identifier and
  describes it afterwards; a bullet that MENTIONS one puts words in front of
  it. Decidable from the bullet's own structure, and language-agnostic: the
  corpus bullets it rejects are written in English and in Chinese and are
  rejected identically, because the rule never reads the words.

  PROVENANCE -- if an entry cites a document, that document must contain the
  name. This is the repo's own ``evidence_citation_resolves_check`` standard
  applied one level deeper: to the CLAIM, not just to the path. A future table
  that mints names is caught the day it is written.

MEASURED BOTH DIRECTIONS on the same 74 roots: entries 80 -> 61. All 19
removed are false (each opened by hand). ZERO true entries removed and ZERO
entries added -- the honest report is that this is a precision repair with no
recall gain, and the corpus contains no missed declaration of these shapes.

WHAT IS DELIBERATELY NOT GOVERNED
=================================
An entry with NO document citation is not this extractor's output: the
IC-expert dialogue track authors decompositions no input document spells out.
Deleting those would be a second defect of the shape of the first, so
``test_an_uncited_entry_is_left_alone`` pins that they survive.

NEGATIVE CONTROL
================
Every test drives the shipped runner end-to-end, so each fails BEHAVIOURALLY
against the byte-identical pre-fix program rather than raising on a symbol the
pre-fix module does not export.

chip-AGNOSTIC: Markdown list/emphasis punctuation and string containment
against the design's own inputs. No chip, vendor, PDK, process or protocol
literal participates.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
_RUNNER = _PROGRAMS / "phase1_one_shot_runner.py"


# Three DECLARATION shapes (identifier in name position, incl. bold emphasis
# and a multiplicity prefix) and three MENTION shapes (a word precedes the
# span) under the same heading, in the same bullet block.
_INTEGRATION_DOC = """# Integration

## Submodules

- `frontend_rx` — recovers the line clock and deserialises
- **`payload_store`**: holds one frame
- 2x `lane_slice` (one per lane)
- The minimum pad spacing is `pad_pitch = 0.1` um for this build.
- All ports are declared unsigned; do not use the `signed` keyword.
- Rejects the frame if `crc_fail` is asserted.
"""

# A README whose "Modules" section is a FEATURE list. The catalog walker
# slugifies each bullet into an identifier that appears nowhere in the file.
_MINTING_README = """# Widget Core

Widget Core is a small datapath block.

## Modules

- Rolling window accumulation mode,
- Streaming passthrough mode, and
- Register-based data interface
"""


def _run_phase1(tmp_path: Path, docs: dict) -> dict:
    d = tmp_path / "input" / "docs"
    d.mkdir(parents=True, exist_ok=True)
    for name, body in docs.items():
        (d / name).write_text(body, encoding="utf-8")
    # ~3s measured; 60s is the harness ceiling, so this call's own timeout
    # fires and fails the test rather than the harness killing the session.
    proc = subprocess.run([sys.executable, str(_RUNNER), str(tmp_path)],
                          capture_output=True, text=True, timeout=60)
    l9 = tmp_path / "phase1" / "generated_docs" / "L9_INTEGRATION_SPEC.json"
    assert l9.is_file(), (
        "Phase 1 emitted no L9 (rc=%s)\n%s"
        % (proc.returncode, proc.stdout[-3000:]))
    return json.loads(l9.read_text())


def _names(l9: dict) -> list:
    return [str(s.get("name")) for s in (l9.get("submodules") or [])
            if isinstance(s, dict)]


# ── RULE 1: position ─────────────────────────────────────────────────────────
def test_an_identifier_quoted_inside_a_sentence_is_not_a_submodule(tmp_path):
    """NEGATIVE CONTROL — fails BEHAVIOURALLY pre-fix.

    All three are backticked legal identifiers under a `Submodules` heading;
    all three are quoted INSIDE a sentence about something else."""
    names = _names(_run_phase1(tmp_path, {"L8_integration.md": _INTEGRATION_DOC}))
    for mention in ("pad_pitch", "signed", "crc_fail"):
        assert mention not in names, (
            "%r is quoted inside a sentence, not declared, yet reached "
            "L9.submodules: %r" % (mention, names))


def test_an_identifier_in_name_position_is_still_a_submodule(tmp_path):
    """TIGHTENING GUARD — the rule must not cost the declarations it exists
    to accept, including the emphasised and multiplicity-prefixed forms."""
    names = _names(_run_phase1(tmp_path, {"L8_integration.md": _INTEGRATION_DOC}))
    for declared in ("frontend_rx", "payload_store", "lane_slice"):
        assert declared in names, (
            "declared submodule %r was rejected: %r" % (declared, names))


def test_the_keyword_case_is_closed_by_position_not_by_the_keyword(tmp_path):
    """The reserved word and the non-reserved config key are rejected for the
    SAME reason, which is what makes this a rule rather than a list.

    (The pre-existing keyword deny list is left in place; it is not this
    change's to remove. This pins that the class no longer depends on it.)"""
    names = _names(_run_phase1(tmp_path, {"L8_integration.md": _INTEGRATION_DOC}))
    assert "signed" not in names and "pad_pitch" not in names, names


# ── RULE 2: provenance ───────────────────────────────────────────────────────
def test_a_name_absent_from_the_document_it_cites_is_dropped(tmp_path):
    """NEGATIVE CONTROL — fails BEHAVIOURALLY pre-fix.

    Each emitted name is a slug of a prose bullet; none of the three occurs
    anywhere in the README they all cite."""
    l9 = _run_phase1(tmp_path, {"README.md": _MINTING_README})
    for name in _names(l9):
        assert name.lower() in _MINTING_README.lower(), (
            "L9 published submodule %r citing README.md, which does not "
            "contain it" % (name,))


def test_the_drop_is_recorded_rather_than_silent(tmp_path):
    """A removal nobody can see is its own defect. Each drop names the
    citation it failed."""
    l9 = _run_phase1(tmp_path, {"README.md": _MINTING_README})
    dropped = l9.get("submodules_dropped_uncited") or []
    assert dropped, "entries were removed with no record of why"
    for d in dropped:
        assert d.get("name") and d.get("cited_document") and d.get("reason"), d


def test_the_result_discloses_how_much_it_examined(tmp_path):
    """A pass must say how much it looked at -- the house rule. The
    disclosure is written whether or not anything was dropped."""
    for docs in ({"README.md": _MINTING_README},
                 {"L8_integration.md": _INTEGRATION_DOC}):
        l9 = _run_phase1(tmp_path / str(abs(hash(tuple(docs)))), docs)
        prov = l9.get("submodule_name_provenance")
        assert isinstance(prov, dict), l9.keys()
        for k in ("entries_total", "entries_with_document_citation",
                  "entries_dropped", "rule"):
            assert k in prov, (k, prov)
        assert prov["entries_dropped"] <= prov["entries_total"], prov


def test_an_uncited_entry_is_left_alone(tmp_path):
    """SCOPE GUARD — the rule governs EXTRACTION, so an entry that cites no
    document is out of its reach. Silently deleting authored decompositions
    would be the same defect as publishing invented ones."""
    l9 = _run_phase1(tmp_path, {"L8_integration.md": _INTEGRATION_DOC})
    l9["submodules"].append({"name": "authored_block", "instances": 1})
    p = (tmp_path / "phase1" / "generated_docs" / "L9_INTEGRATION_SPEC.json")
    p.write_text(json.dumps(l9), encoding="utf-8")
    sys.path.insert(0, str(_PROGRAMS))
    import phase1_doc_one_shot_runner as R  # noqa: E402
    n = R._post_emit_l9_drop_uninstantiated_submodule_names(
        tmp_path, {"L8_integration.md": _INTEGRATION_DOC})
    after = _names(json.loads(p.read_text()))
    assert n == 0, n
    assert "authored_block" in after, after


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
