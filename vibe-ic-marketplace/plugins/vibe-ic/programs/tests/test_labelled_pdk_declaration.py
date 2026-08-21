"""A PDK identifier is what a document DECLARES, not a name we recognise.

`_extract_pdk_target_with_provenance` had two evidence sources and both
decided "is this a PDK identifier?" by testing the token against a CLOSED
NAME LIST — `_OPEN_PDK_TOKEN_RE` (the open PDKs) or `_FOUNDRY_CTX_RE`
(six commercial foundry names). That model can only extract a PDK whose
name is already in the list, so a design that stages its OWN commercial
enablement keeps `pdk_target = None` however plainly it declares its
process, and `l19_pdk_floorplan_contract_check` L19-3 blocks on the null.

These tests pin the THIRD source: a labelled declaration
(`^<label> : <value>`) is read as the design's own statement of its
process, with no name list involved.

Every fixture name here is synthetic. The rules under test encode field
LABELS ("pdk", "process", "technology", "foundry"), which are properties
of documents; no vendor, foundry, SKU or part literal appears.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import phase1_doc_one_shot_runner as R  # noqa: E402


def _mkproject(tmp_path: Path, files: dict) -> Path:
    for rel, text in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return tmp_path


# --------------------------------------------------------------------------
# The declaration is read, and it needs no name list.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("line,expected", [
    ("PDK: AcmeFab AF180X (180nm BCD)", "AcmeFab AF180X"),
    ("**PDK source**: AcmeFab AF180X-R2 / R3 (180nm BCD, 1.8V/5V)",
     "AcmeFab AF180X-R2"),
    ("Technology node : Zenith Micro ZM55 55nm LP", "Zenith Micro ZM55 55nm LP"),
    ("- Process: Borealis BX28 (28nm FDSOI)", "Borealis BX28"),
    ("Design kit = Cygnet CG65 65nm", "Cygnet CG65 65nm"),
])
def test_labelled_declaration_is_adopted(line, expected):
    """A labelled field naming a process is the design's declaration.

    None of these vendor names is in `_FOUNDRY_CTX_RE`; that is the point.
    """
    got = None
    for m in R._PDK_DECL_RE.finditer(line + "\n"):
        got = R._pdk_declared_value_token(m.group(1))
        if got:
            break
    assert got == expected


def test_declaration_is_not_reachable_by_the_name_list():
    """Guard the premise: the fixtures really do defeat the old model."""
    line = "**PDK source**: AcmeFab AF180X-R2 (180nm BCD)\n"
    assert R._OPEN_PDK_TOKEN_RE.search(line) is None
    assert not list(R._FOUNDRY_CTX_RE.finditer(line))


# --------------------------------------------------------------------------
# A MENTION is not a declaration. This is the whole safety property.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("text,why", [
    ("Structural shape modelled on the sky130A and gf180mcuD technology\n"
     "files shipped in the eda image, 180nm-class.\n",
     "a provenance comment naming ANOTHER pdk is a mention, not a declaration"),
    ("The board was fabricated on a mature 180nm process at a partner.\n",
     "running prose naming a node is not a declaration"),
    ("See the appendix where PDK source: AcmeFab AF180X (180nm) is tabulated.\n",
     "a label mid-sentence is prose, not a field"),
])
def test_mention_is_not_adopted(text, why):
    for m in R._PDK_DECL_RE.finditer(text):
        assert R._pdk_declared_value_token(m.group(1)) is None, why


# --------------------------------------------------------------------------
# The #457 guards still apply, to the DECLARED VALUE.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("line,why", [
    ("**PDK source**: not yet selected; a 180nm process is the intent.",
     "#457 (a) negation-aware deny"),
    ("PDK: AcmeFab BCD-Ultra", "#457 (b) dual-evidence: no numeric node"),
    ("Process node: TBD", "a placeholder declares nothing"),
    ("Process: 180nm", "a bare node with no identifier is not a target"),
])
def test_declared_value_still_obeys_the_457_guards(line, why):
    for m in R._PDK_DECL_RE.finditer(line + "\n"):
        assert R._pdk_declared_value_token(m.group(1)) is None, why


# --------------------------------------------------------------------------
# End to end through the extractor, including the ORDERING contract.
# --------------------------------------------------------------------------

def test_declaration_under_the_staged_pdk_root_is_found(tmp_path):
    """The bridge/README of a staged PDK is read by NEITHER old source.

    Prose scans `phase1/input_doc` / `input/docs`; the staged-path source
    scans `input/pdk*/` but keeps only enablement SUFFIXES. A document
    under the staged PDK root falls between them.
    """
    proj = _mkproject(tmp_path, {
        "input/pdk/BRIDGE.md":
            "# bridge map\n\n**PDK source**: AcmeFab AF180X-R2 (180nm BCD)\n",
        "input/pdk/liberty/cells_typ.lib": "library (cells_typ) {\n}\n",
        "input/docs/overview.md": "This part talks to a host over one wire.\n",
    })
    tok, snippet, src, line = R._extract_pdk_target_with_provenance(proj)
    assert tok == "AcmeFab AF180X-R2"
    assert src == "input/pdk/BRIDGE.md"
    assert line == 3
    assert "PDK source" in snippet


def test_no_declaration_still_yields_none(tmp_path):
    """The negative control: without a declaration nothing is invented."""
    proj = _mkproject(tmp_path, {
        "input/pdk/BRIDGE.md":
            "# bridge map\n\nModelled on files shipped in the eda image.\n",
        "input/pdk/liberty/cells_typ.lib": "library (cells_typ) {\n}\n",
    })
    assert R._extract_pdk_target_with_provenance(proj) == (
        None, None, None, None)


def test_prose_still_wins_over_the_new_source(tmp_path):
    """ORDERING CONTRACT: the new source runs only after prose yields
    nothing, so no answer the existing tiers can produce changes."""
    proj = _mkproject(tmp_path, {
        "input/docs/spec.md": "Target process: sky130A for this tapeout.\n",
        "input/pdk/BRIDGE.md":
            "**PDK source**: AcmeFab AF180X-R2 (180nm BCD)\n",
    })
    tok, _snippet, src, _line = R._extract_pdk_target_with_provenance(proj)
    assert tok == "sky130a"
    assert src == "input/docs/spec.md"


def test_l19_target_becomes_traceable_to_the_designs_own_inputs(tmp_path):
    """The value is adopted from a design file, so the L19-2 traceability
    check — which independently re-derives it — can substantiate it."""
    proj = _mkproject(tmp_path, {
        "input/pdk/BRIDGE.md":
            "**PDK source**: AcmeFab AF180X-R2 (180nm BCD)\n",
    })
    tok, _s, src, _l = R._extract_pdk_target_with_provenance(proj)
    assert tok
    corpus_text = (proj / src).read_text()
    norm = lambda s: "".join(c for c in s.lower() if c.isalnum())  # noqa: E731
    assert norm(tok) in norm(corpus_text)


def test_declaration_scan_is_deterministic(tmp_path):
    """Two files could both declare; the sorted scan makes the winner
    stable across runs."""
    proj = _mkproject(tmp_path, {
        "input/pdk/a_bridge.md": "**PDK source**: AcmeFab AF180X (180nm)\n",
        "input/pdk/z_bridge.md": "**PDK source**: Borealis BX28 (28nm)\n",
    })
    first = R._labelled_pdk_declaration(proj)
    for _ in range(3):
        assert R._labelled_pdk_declaration(proj) == first
    assert first[0] == "AcmeFab AF180X"


def test_json_l19_consumer_shape_is_unchanged(tmp_path):
    """The extractor's return contract (tok, snippet, source_rel, line)
    is what the L19 emitter destructures; a staged-path answer still
    reports line=None as its discriminator."""
    proj = _mkproject(tmp_path, {
        "input/pdk/liberty/sky130a_cells.lib": "library (x) {}\n",
    })
    tok, snippet, src, line = R._extract_pdk_target_with_provenance(proj)
    assert tok == "sky130a"
    assert line is None
    assert snippet == src
    json.dumps({"pdk_target": tok, "source": src, "line": line})
