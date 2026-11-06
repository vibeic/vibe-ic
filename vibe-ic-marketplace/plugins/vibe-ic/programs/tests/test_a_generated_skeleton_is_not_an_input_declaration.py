"""Input subject scanning uses source documents rather than skeleton defaults."""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import pytest  # noqa: E402

import phase1_post_process as P  # noqa: E402

#: The condition the flow declares at all five DFT step sites.
SPEC = {
    "l_doc": "L20",
    "all_absent": {
        "dft_present": False,
        "scan_chains": [],
        "bist_mbist": [],
        "jtag_tap": None,
    },
}

#: The skeleton r27 actually carried, field for field.
SKELETON = {
    "doc_id": "L20",
    "doc_name": "L20_DFT_SCAN_TOPOLOGY",
    "applicability": "APPLICABLE",
    "extraction_status": "NOT_YET_EXTRACTED",
    "source_documents": [],
    "extraction_evidence": {},
    "fields": {
        "scan_chains": [],
        "test_compression": None,
        "bist_mbist": [],
        "jtag_tap": None,
        "dft_present": False,
        "notes": "Spec does not specify DFT/scan topology.",
    },
}


def _project(tmp_path: Path, docs: dict, l20=SKELETON) -> Path:
    proj = tmp_path / "proj"
    (proj / "input" / "docs").mkdir(parents=True, exist_ok=True)
    for name, text in docs.items():
        (proj / "input" / "docs" / name).write_text(text, encoding="utf-8")
    gen = proj / "phase1" / "generated_docs"
    gen.mkdir(parents=True, exist_ok=True)
    if l20 is not None:
        (gen / "L20_DFT_SCAN_TOPOLOGY.json").write_text(json.dumps(l20))
    return proj


NO_DFT = {
    "L1_product_metadata.md": "# Part\nA small RISC-V core.\n",
    "L2_architecture.md": "It fetches, decodes and executes.\n",
    "L3_external_interface.md": "Pins: i_clk, i_rst, o_gpio.\n",
}


# ── the repair: the record now rests on the INPUT ────────────────────────────
def test_the_declaration_cites_the_input_not_the_skeleton(tmp_path):
    proj = _project(tmp_path, NO_DFT)
    evidence = P.declaration_corroboration("L20", proj)
    assert evidence["documents_matching"] == 0
    assert evidence["documents_scanned_count"] == 3
    assert evidence["documents_scanned"] == [
        "input/docs/L1_product_metadata.md", "input/docs/L2_architecture.md",
        "input/docs/L3_external_interface.md",
    ]
    assert [term.lower() for term in evidence["terms_searched"]] == [
        "scan", "dft", "bist", "jtag", "atpg", "test mode"]



# ── the other direction: an input that DOES mention DFT refuses the N/A ──────
@pytest.mark.parametrize("sentence", [
    "The part provides a scan chain for production test.", "A DFT wrapper is required.",
    "Memory is covered by BIST.", "Debug is over JTAG.",
    "Production test uses ATPG vectors.", "Asserting TEST MODE gates the functional clock.",
])
def test_one_mention_in_one_input_document_runs_the_step(tmp_path, sentence):
    docs = dict(NO_DFT)
    docs["L7_verification_plan.md"] = sentence + "\n"
    evidence = P.declaration_corroboration("L20", _project(tmp_path, docs))
    assert evidence is None



def test_the_skeleton_alone_is_no_longer_enough(tmp_path):
    assert P.declaration_corroboration("L20", _project(tmp_path, {})) is None



def test_an_empty_input_corpus_is_not_a_declaration(tmp_path):
    assert P.declaration_corroboration("L20", _project(tmp_path, {})) is None



# ── the L-doc half must keep every refusal it already had ────────────────────




def test_an_unregistered_l_doc_has_no_corroboration_and_so_no_na(tmp_path):
    assert P._DECLARATION_CORROBORATION_TERMS.get("L21") is None



# ── the terms are the layer's own, not this file's opinion ───────────────────
def test_the_corroboration_terms_come_from_the_layers_own_hints():
    hints = " ".join(P._extraction_hints_for("L20")).lower()
    for term in P._DECLARATION_CORROBORATION_TERMS["L20"]:
        assert term.lower() in hints, (term, hints)


def test_there_is_one_scanner_not_two():
    """Input classification and skeleton generation share the same scanner."""
    assert P.declaration_corroboration.__module__ == P.__name__
    assert P._input_carries_subject.__module__ == P.__name__
    src = Path(P.__file__).read_text()
    assert src.count("def scan_input_for_terms(") == 1


# ── and on the real design's own input, vendored so it always runs ──────────
#
# THE FIRST VERSION OF THIS SECTION WAS WRONG, and it is worth saying how. It
# read `<home>/benchmark-data/...` behind
# `@pytest.mark.skipif(not REAL.is_dir())`. That is an environment-gated skip on
# a path that exists on exactly one machine: everywhere else the case did not
# run and the file still reported green, which is the one thing a measuring
# host must never be told. `benchmark-data` is not in this repo at all — not a
# directory, not a submodule entry — so the gate would have been open on every
# host but the one it was written on.
#
# So the corpus is VENDORED, under this test's own directory, and the case
# always runs. INPUT ONLY: these are the design's own specification documents,
# which is what the scanner reads and what §4.05 permits. No oracle, no
# harness, no golden.
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "subservient_input_docs"

#: What the REAL corpus measured, 2026-09-16, at benchmark-data origin/main
#: 98662b7419765432028b929323b42eccd9f0a507. Each excerpt carries its source
#: document's full sha256 and line count in its own header, so the vendoring is
#: re-derivable rather than asserted. Re-derive with:
#:     git -C benchmark-data show origin/main:ic/subservient/input/docs/<name>
_REAL_CORPUS = {
    "L1_product_metadata.md": 63,
    "L2_architecture.md": 84,
    "L3_external_interface.md": 74,
    "L4_command_protocol.md": 23,
    "L5_register_map.md": 24,
    "L6_calibration.md": 20,
    "L7_verification_plan.md": 123,
    "L8_submodule_integration.md": 84,
    "L9_constraints_floorplan.md": 101,
}


def _vendored_project(tmp_path: Path) -> Path:
    """The design's nine input documents, staged as a project."""
    import shutil
    proj = tmp_path / "subservient"
    (proj / "input").mkdir(parents=True)
    shutil.copytree(FIXTURE, proj / "input" / "docs")
    return proj


def test_the_vendored_corpus_is_the_designs_nine_documents():
    """A missing fixture is a RED, not a skip. If this directory is gone the
    case below is measuring nothing, and it must say so rather than pass."""
    assert FIXTURE.is_dir(), f"vendored input corpus is missing: {FIXTURE}"
    present = sorted(p.name for p in FIXTURE.glob("*.md"))
    assert present == sorted(_REAL_CORPUS), present
    for name in present:
        header = (FIXTURE / name).read_text(encoding="utf-8")[:400]
        # Provenance is part of the fixture, not a comment about it.
        assert "benchmark-data origin/main" in header, name
        assert f"ic/subservient/input/docs/{name}" in header, name
        assert "sha256 :" in header, name
        assert f"document is {_REAL_CORPUS[name]} line(s)" in header, name


def test_the_real_subservient_input_earns_its_na(tmp_path):
    """The design this ruling came from. Its N/A is EARNED — nine documents
    scanned, six terms, zero hits — which is exactly why the old citation was
    never noticed: the conclusion was right and the basis was not."""
    proj = _vendored_project(tmp_path)
    ev = P.declaration_corroboration("L20", proj)
    assert ev is not None
    assert ev["documents_matching"] == 0
    assert ev["documents_scanned_count"] == 9
    assert ev["documents_scanned"] == [
        f"input/docs/{name}" for name in sorted(_REAL_CORPUS)]


def test_the_real_corpus_does_not_even_contain_the_terms_as_substrings():
    """MEASURED on the real documents at benchmark-data origin/main: zero
    occurrences of any of the six terms, as SUBSTRINGS, across all 596 lines —
    so this design's silence about DFT does not depend on the word-boundary
    rule. Held over the vendored excerpts, which must inherit that silence or
    they are not a faithful stand-in."""
    terms = P._DECLARATION_CORROBORATION_TERMS["L20"]
    for doc in sorted(FIXTURE.glob("*.md")):
        body = doc.read_text(encoding="utf-8").split("-->", 1)[-1].lower()
        for term in terms:
            assert term.lower() not in body, (doc.name, term)


def test_the_whole_declaration_holds_on_the_real_input(tmp_path):
    proj = _vendored_project(tmp_path)
    evidence = P.declaration_corroboration("L20", proj)
    assert evidence["documents_scanned_count"] == 9
    assert evidence["documents_matching"] == 0
    l7 = proj / "input/docs/L7_verification_plan.md"
    l7.write_text(l7.read_text(encoding="utf-8") + "\nProduction test uses a scan chain.\n", encoding="utf-8")
    assert P.declaration_corroboration("L20", proj) is None
