"""A file path in a document must not be read as a port declaration.

MEASURED DEFECT (pre-fix). The L1 pin-table narrative line-scan anchors on
`_PIN_TABLE_LINE_RE = \\b(input|output|inout|bidir|power|ground)\\b`, searched
over the RAW line. `/` is a word boundary, so a document that cites a file
under `input/…` matched `\\binput\\b` INSIDE the path. The line then promoted
every capitalised token on it to a port with `mode=input`.

That path is not exotic — `input/pdk/…` is the path THIS FLOW MANDATES for a
project-staged PDK, and `input/docs/…` for its design documents. So any
document that cites its own staged inputs in the ordinary way poisons the pin
table.

Measured on a CPU cell whose L1/L9 cite their staged PDK and whose L3 explains
that the PDK ships no IO library: `PDK`, `STD` and `IO` were emitted into
`L1.pin_table` as phantom input ports (13 entries where the design has 10), and
`l9_rtl_pin_consistency_check` then correctly FAILed the design for declaring a
pin — `io` — that its RTL top does not have. The document was right; the
extractor was wrong; and the failure pointed at the design.

Fix: mask whitespace-delimited path-like tokens before the direction anchor is
searched and before names are tokenised. A directory name is never a port
direction; a path fragment is never a port name.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]


def _p1():
    key = "p1_pathpin"
    if key in sys.modules:
        return sys.modules[key]
    spec = importlib.util.spec_from_file_location(
        key, PROGRAMS / "phase1_doc_one_shot_runner.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules[key] = m
    assert spec.loader is not None
    spec.loader.exec_module(m)
    return m


def test_the_path_mask_drops_only_path_tokens() -> None:
    """The mask is the whole mechanism, so pin it directly."""
    rx = _p1()._PATHLIKE_TOKEN_RE
    assert rx.sub(" ", "| Metal stack | STD flavor | `input/pdk/lef/a/b.lef` |") \
        == "| Metal stack | STD flavor |   |"
    # A plain port name, a bus range and a backticked identifier survive.
    for keep in ("i_clk", "o_bus[7:0]", "`i_rst`", "VDD", "inout"):
        assert rx.sub(" ", keep) == keep, keep


def test_direction_anchor_no_longer_fires_inside_a_path() -> None:
    p1 = _p1()
    line = "  - input/pdk/lef/vendor_lef_dir/STD/libx_5lm_tech.lef"
    # Pre-fix this matched; post-fix the anchor must see nothing.
    assert p1._PIN_TABLE_LINE_RE.search(line) is not None, (
        "the raw line does contain the token — that is the defect")
    masked = p1._PATHLIKE_TOKEN_RE.sub(" ", line)
    assert p1._PIN_TABLE_LINE_RE.search(masked) is None


def test_a_real_direction_word_outside_a_path_still_anchors() -> None:
    """The mask must not disarm the extractor: a genuine pin-table row whose
    direction column says `input` is untouched."""
    p1 = _p1()
    line = "| i_clk | input | 1 | system clock |"
    masked = p1._PATHLIKE_TOKEN_RE.sub(" ", line)
    m = p1._PIN_TABLE_LINE_RE.search(masked)
    assert m is not None and m.group(1).lower() == "input"


def test_a_row_citing_a_path_keeps_its_own_direction_column() -> None:
    """A pin-table row that BOTH declares a direction and cites a file keeps
    the direction — only the path is masked."""
    p1 = _p1()
    line = "| o_gpio | output | 1 | see docs/interface/gpio.md |"
    masked = p1._PATHLIKE_TOKEN_RE.sub(" ", line)
    m = p1._PIN_TABLE_LINE_RE.search(masked)
    assert m is not None and m.group(1).lower() == "output"
    assert "gpio.md" not in masked and "o_gpio" in masked


_DOC_L1 = """---
layer: L1
sources:
  - input/pdk/lef/vendor_lef_dir/STD/libx_5lm_tech.lef
---

# L1 — Product metadata

| item | value | source |
|---|---|---|
| Target PDK | commercial process, library family `libx` | `input/pdk/liberty/libx_typ.lib` |
| Metal stack | 5 layers, STD top-metal flavor | `input/pdk/lef/vendor_lef_dir/STD/libx_5lm_tech.lef` |
"""

_DOC_L3 = """---
layer: L3
sources:
  - input/pdk/lef/vendor_lef_dir/libx_macro.lef (no IO/pad macro exists in this PDK copy)
---

# L3 — External interface

## 3.1 Top-level ports

| signal | width | direction | description |
|---|---|---|---|
| `i_clk` | 1-bit | input | system clock |
| `i_rst` | 1-bit | input | synchronous reset, active-high |
| `o_gpio` | 1-bit | output | general purpose output |

> This PDK copy ships no IO library — see `input/pdk/lef/vendor_lef_dir/libx_macro.lef`
"""


def test_end_to_end_no_phantom_pin_from_a_cited_path(tmp_path: Path) -> None:
    """The behavioural control: emit L1 from documents that cite their own
    staged inputs the way this flow mandates, and assert the pin table holds
    ONLY the ports the interface table declares."""
    p1 = _p1()
    proj = tmp_path / "proj"
    (proj / "phase1" / "generated_docs").mkdir(parents=True)
    extracted = {"L1_product_metadata.md": _DOC_L1,
                 "L3_external_interface.md": _DOC_L3}
    p1.gen_l1_datasheet(proj, extracted)

    import json
    doc = json.loads(
        (proj / "phase1" / "generated_docs" / "L1_DATASHEET.json").read_text())
    names = {p["name"] for p in (doc.get("pin_table") or [])}

    # The path fragments and the prose acronym must NOT be ports.
    for phantom in ("STD", "IO", "PDK"):
        assert phantom not in names, (
            f"{phantom!r} was harvested as a port from a cited file path; "
            f"pin_table = {sorted(names)}")
    # The real ports must survive — the mask must not disarm the extractor.
    assert {"i_clk", "i_rst", "o_gpio"} <= names, sorted(names)


def test_capitalised_words_beside_a_path_are_not_harvested_as_names() -> None:
    """The names are tokenised from the SAME masked line, so a capitalised
    path fragment can never become a port name."""
    p1 = _p1()
    import re
    line = ("| Metal stack | 5 layers, STD top-metal flavor | "
            "`input/pdk/lef/vendor/STD/libx_5lm_tech.lef` |")
    masked = p1._PATHLIKE_TOKEN_RE.sub(" ", line)
    tokens = [t for t in re.split(r"[\s\t\|,]+", masked.strip()) if t]
    # `STD` in the prose column survives tokenisation (the deny-lists and
    # `_is_real_port_token` are what judge it) — but the path's own `STD`
    # segment is gone, and with the anchor gone the line is never scanned.
    assert not any("/" in t for t in tokens)
    assert p1._PIN_TABLE_LINE_RE.search(masked) is None
