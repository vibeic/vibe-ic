"""R-0915-36: a layer's applicability is DECIDED FROM THE INPUT, not assumed.

MEASURED 2026-09-15 (lane icspm3) on `spm` x gf180mcuD. L24 and L25 were both
emitted as::

    "applicability": "APPLICABLE", "extraction_status": "NOT_YET_EXTRACTED",
    every field null

and their two P0 gates reported, honestly, that there was nothing to certify.
A skeleton in that state has declared NOTHING -- it says the subject matters
and that nobody looked -- so the gates stayed INCOMPLETE, permanently, no
matter what the design was.

`emit_l_doc_skeleton` now asks the input first, for the layers registered in
`_INPUT_SUBJECT_TERMS`. No input document carrying the layer's subject means
the layer is emitted as a DECLARED ABSENCE (`applicability: NOT_APPLICABLE`,
`extraction_status: DECLARED_ABSENT_FROM_INPUT`) carrying the documents it
scanned and the terms it searched. Any input document carrying the subject
leaves the layer exactly as it is today.

THAT SECOND DIRECTION IS THE ONE THAT MATTERS, and spm supplies it live: the
design's own input DOES discuss sign-off -- 8 occurrences of "sign-off", 5 of
DRC, 4 of LVS, 3 of STA, plus antenna and tapeout, across five documents -- so
L24 stays APPLICABLE and `l24_signoff_evidence_backed_check` keeps blocking.
Its skeleton is a real phase-1 extraction gap. L25's subject appears in ZERO
of the nine documents, so L25 becomes the declared absence.

The terms are not invented: each is a word the layer's own
`_extraction_hints_for()` already uses, and that is pinned below so the table
cannot drift from what the layer says it is looking for.

chip-AGNOSTIC: synthetic projects in tmp_path.
"""
from __future__ import annotations

import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import pytest  # noqa: E402

import phase1_post_process as P  # noqa: E402

LAYERS = ("L24", "L25")


def _project(tmp_path, **docs):
    d = tmp_path / "input" / "docs"
    d.mkdir(parents=True, exist_ok=True)
    for name, text in docs.items():
        # kwargs cannot carry a dot, so `spec_md` means `spec.md`. The suffix
        # is load-bearing: the scan reads text documents only, and a file with
        # no suffix would silently give an EMPTY corpus, which is a refusal
        # rather than a declaration -- the first draft of this fixture did
        # exactly that and made both positive cases vacuous.
        stem, _, suffix = name.rpartition("_")
        (d / f"{stem}.{suffix}").write_text(text, encoding="utf-8")
    return tmp_path


def _emit(proj, code):
    return P.emit_l_doc_skeleton(code, "unknown", project_dir=proj)


# ── the terms are the layer's own ────────────────────────────────────────

@pytest.mark.parametrize("code", LAYERS)
def test_the_terms_come_from_the_layers_own_hints(code):
    hints = " ".join(P._extraction_hints_for(code)).lower()
    for term in P._INPUT_SUBJECT_TERMS[code]:
        assert term.lower() in hints, (code, term, hints)


# ── direction 1: no input document carries the subject ───────────────────

@pytest.mark.parametrize("code", LAYERS)
def test_a_subject_no_input_document_carries_is_declared_absent(
        tmp_path, code):
    proj = _project(tmp_path, spec_md="The part multiplies two numbers.\n")
    doc = _emit(proj, code)
    assert doc["applicability"] == "NOT_APPLICABLE"
    assert doc["extraction_status"] == "DECLARED_ABSENT_FROM_INPUT"
    ev = doc["applicability_evidence"]
    assert ev["kind"] == "input-declares-no-subject"
    assert ev["layer"] == code
    assert ev["documents_matching"] == 0
    # PROJECT-RELATIVE, so the claim can be re-run against the same bytes.
    assert ev["documents_scanned"] == ["input/docs/spec.md"], ev
    assert ev["documents_scanned_count"] == 1
    assert (proj / ev["documents_scanned"][0]).is_file()
    assert list(ev["terms_searched"]) == list(P._INPUT_SUBJECT_TERMS[code])


# ── direction 2: an input document that DOES carry it ────────────────────

@pytest.mark.parametrize("code,carrier", [
    ("L25", "Qualification: AEC-Q100 grade 1, mission-profile 15 years.\n"),
    ("L25", "Reliability targets are stated in section 4.\n"),
    ("L25", "NBTI and HCI aging margins apply over the temperature range.\n"),
    ("L24", "Sign-off requires DRC and LVS clean before tapeout.\n"),
    ("L24", "STA must close at the target corner.\n"),
    ("L24", "The antenna checklist is part of the signoff gate list.\n"),
])
def test_an_input_document_that_carries_the_subject_keeps_it_applicable(
        tmp_path, code, carrier):
    proj = _project(tmp_path, a_md="It multiplies.\n", b_md=carrier)
    doc = _emit(proj, code)
    assert doc["applicability"] == "APPLICABLE", (code, carrier)
    assert "applicability_evidence" not in doc
    # R-0915-38 then EXTRACTS the layers that have an extractor, so the status
    # a present subject earns depends on whether one exists -- APPLICABLE is
    # what this case is about, and it holds either way.
    assert doc["extraction_status"] in (
        "NOT_YET_EXTRACTED", "EXTRACTED"), doc["extraction_status"]
    import phase1_post_process as _P
    expected = "EXTRACTED" if code in _P._LAYER_EXTRACTORS \
        else "NOT_YET_EXTRACTED"
    assert doc["extraction_status"] == expected, (code, carrier)


def test_the_two_layers_are_decided_independently(tmp_path):
    """The spm shape, reproduced: one layer's subject present, the other's
    absent, in the SAME input."""
    proj = _project(tmp_path, plan_md=(
        "Verification plan\n\nSign-off: DRC, LVS, STA and antenna checks "
        "must be clean before tapeout.\n"))
    assert _emit(proj, "L24")["applicability"] == "APPLICABLE"
    assert _emit(proj, "L25")["applicability"] == "NOT_APPLICABLE"


# ── the refusals ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("code", LAYERS)
def test_a_design_with_no_input_documents_is_not_a_declaration(
        tmp_path, code):
    """An empty corpus is a scan with no denominator, not a design saying it
    has no sign-off requirements."""
    (tmp_path / "input" / "docs").mkdir(parents=True)
    doc = _emit(tmp_path, code)
    assert doc["applicability"] == "APPLICABLE"
    assert P._input_carries_subject(code, tmp_path) is None


@pytest.mark.parametrize("code", LAYERS)
def test_no_project_is_not_a_declaration(code):
    assert P._input_carries_subject(code, None) is None
    assert _emit(None, code)["applicability"] == "APPLICABLE"


@pytest.mark.parametrize("code", LAYERS)
def test_a_binary_only_corpus_is_not_a_declaration(tmp_path, code):
    """Only readable text documents count as a corpus to have scanned."""
    d = tmp_path / "input" / "docs"
    d.mkdir(parents=True)
    (d / "layout.gds").write_bytes(b"\x00\x01\x02")
    assert P._input_carries_subject(code, tmp_path) is None


@pytest.mark.parametrize("decoy", [
    "The state machine holds status bits.\n",
    "Installation notes follow.\n",
    "A constant is stated in the table.\n",
])
def test_a_word_merely_CONTAINING_a_term_is_not_the_subject(tmp_path, decoy):
    """WORD-BOUNDED, and this is load-bearing: a plain substring test makes
    L24's "STA" fire inside "state", "status", "stated" and "installation",
    so nearly every design would look as though it discussed sign-off and no
    layer would ever reach a declared absence. Caught by this file before the
    change shipped."""
    proj = _project(tmp_path, spec_md=decoy)
    assert P._input_carries_subject("L24", proj) is not None, decoy
    assert _emit(proj, "L24")["applicability"] == "NOT_APPLICABLE"


def test_an_unregistered_layer_is_untouched(tmp_path):
    """Every other layer keeps the APPLICABLE skeleton it has today."""
    proj = _project(tmp_path, spec_md="It multiplies.\n")
    # L20 gained the narrowly scoped, source-table extractor in #3443.  It is
    # still an APPLICABLE, unextracted skeleton for this unrelated input; only
    # L21/L22 remain wholly unregistered here (L23 was already registered).
    assert "L20" in P._LAYER_EXTRACTORS
    l20 = _emit(proj, "L20")
    assert l20["applicability"] == "APPLICABLE"
    assert l20["extraction_status"] == "NOT_YET_EXTRACTED"
    for code in ("L21", "L22"):
        assert code not in P._INPUT_SUBJECT_TERMS
        assert code not in P._LAYER_EXTRACTORS
        doc = _emit(proj, code)
        assert doc["applicability"] == "APPLICABLE", code
        assert doc["extraction_status"] == "NOT_YET_EXTRACTED", code
