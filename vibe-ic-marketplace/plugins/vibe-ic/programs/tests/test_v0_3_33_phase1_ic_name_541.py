"""ORGANIC #541 — phase1 docs-mode honours --ic-name (CLI > docs heuristic)
and never lets a block-diagram SVG/PNG label or stem become the ic_name.

Named so `pytest -k "phase1 and (ic_name or icname)"` selects it.
"""
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import phase1_doc_one_shot_runner as R  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_override():
    R._CLI_IC_NAME_OVERRIDE = None
    yield
    R._CLI_IC_NAME_OVERRIDE = None


def test_phase1_cli_ic_name_overrides_docs_heuristic():
    # (a) docs would yield AES, but --ic-name bar is authoritative
    R._CLI_IC_NAME_OVERRIDE = "bar"
    got = R._ic_name_from_docs(
        {"spec.md": "implementation of AES",
         "foo_diagram.svg": "GHASH"}, None)
    assert got == "bar"


def test_phase1_ic_name_excludes_svg_stem_and_labels():
    # (b) without --ic-name, a .svg block-diagram label must NOT seed the
    # ic_name (the GHASH.svg → 'GHASH' bug); prose .md still works.
    assert R._ic_name_from_docs(
        {"block_diagram.svg": "implementation of GHASH"}, None) == "UNKNOWN_IC"
    assert R._ic_name_from_docs(
        {"spec.md": "implementation of GHASH"}, None) == "GHASH"


def test_phase1_ic_name_asset_key_detector():
    assert R._is_ic_name_asset_key("GHASH.svg")
    assert R._is_ic_name_asset_key("x.PNG")
    assert R._is_ic_name_asset_key("aes_block__svg.txt")  # picture-key form
    assert not R._is_ic_name_asset_key("datasheet.md")
    assert not R._is_ic_name_asset_key("L1_DATASHEET.json")


def test_phase1_ic_name_png_diagram_excluded():
    # a PNG screenshot of a register map must not become the chip name
    assert R._ic_name_from_docs(
        {"regmap.png": "implementation of CTRL"}, None) == "UNKNOWN_IC"
