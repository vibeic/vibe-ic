r"""ORGANIC #610 [MEDIUM] — a port-table cell declaring one canonical port with
an inline alternate-spelling annotation `\`name\` (or \`alt\`)` (a generic
vendor-doc convention for an equivalent signal name) was double-promoted into
TWO top-level ports by the backticked-interface walker (`_v455_interface_pins`),
which scanned the line with a raw "every backticked identifier is a port" rule.
The GFM emitter correctly collapses it to ONE (alias captured) via its name-cell
sanitizer, so the two paths emitted different name strings, the name-keyed merge
never deduped them, and the redundant alias port cascaded into L9.top_ports —
yielding duplicate write/read (or any aliased) ports.

Fix: in `_v455_interface_pins`, per line, capture each `(or \`alt\`)` / `(或
\`alt\`)` alias group, attach the alt as an ALIAS of the canonical token
immediately preceding it, and EXCLUDE the alt from separate promotion.

POSITIVE (#610): the real rows `\`o_sram_data\` (or \`o_sram_wdata\`)` /
`\`i_sram_data\` (or \`i_sram_rdata\`)` promote ONLY the canonical names; the
alts are captured as aliases, not emitted as separate ports.

NEGATIVE no-leak:
  - per-line scope: a DIFFERENT line that declares the alt as its OWN port
    still promotes it (alias suppression is line-local).
  - a plain port line with no `(or ...)` annotation is unchanged (every
    backtick token still promoted).

chip-AGNOSTIC: generic alias grammar (ASCII + full-width parens), no chip name.
"""
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PLUGIN / "programs"))
import phase1_doc_one_shot_runner as P  # noqa: E402

# A port-context heading is required for the v455 walker to fire.
REAL_DOC = (
    "## External Interface\n\n"
    "| Name | Width | Dir | Description |\n"
    "|--|--|--|--|\n"
    "| `o_sram_data` (or `o_sram_wdata`) | 8-bit | output | write data |\n"
    "| `i_sram_data` (or `i_sram_rdata`) | 8-bit | input  | read data |\n"
)


def test_alias_not_double_promoted():
    pins = P._v455_interface_pins({"L3_external_interface.txt": REAL_DOC})
    names = [p["name"] for p in pins]
    assert "o_sram_data" in names and "i_sram_data" in names
    assert "o_sram_wdata" not in names, "alt spelling must NOT be a 2nd port"
    assert "i_sram_rdata" not in names, "alt spelling must NOT be a 2nd port"
    by = {p["name"]: p for p in pins}
    assert by["o_sram_data"]["aliases"] == ["o_sram_wdata"]
    assert by["i_sram_data"]["aliases"] == ["i_sram_rdata"]


def test_fullwidth_paren_alias():
    doc = ("## Ports\n\n"
           "| Name | Dir |\n|--|--|\n"
           "| `o_data` (或 `o_wdata`) | output |\n")
    pins = P._v455_interface_pins({"d.txt": doc})
    names = [p["name"] for p in pins]
    assert "o_data" in names and "o_wdata" not in names
    assert {p["name"]: p["aliases"] for p in pins}["o_data"] == ["o_wdata"]


def test_per_line_scope_preserves_own_port():
    # NO-LEAK: a different line legitimately declaring the alt as its OWN port
    # still promotes it (the alias suppression is line-local).
    doc = ("## Pins\n\n"
           "Outputs: `o_sram_data` (or `o_sram_wdata`) drive the bus.\n"
           "The `o_sram_wdata` strobe is separately registered here.\n")
    names = [p["name"] for p in P._v455_interface_pins({"d.txt": doc})]
    assert "o_sram_data" in names
    assert "o_sram_wdata" in names, "own-port on another line must still promote"


def test_plain_line_unchanged():
    # NO-LEAK: no `(or ...)` annotation → every backtick token still promoted.
    doc = "## Ports\n\n`clk` and `rst_n` and `data_in` drive it.\n"
    names = sorted(p["name"] for p in P._v455_interface_pins({"d.txt": doc}))
    assert names == ["clk", "data_in", "rst_n"]


def test_regex_matches_or_and_cjk_or():
    assert P._RE_V610_ALIAS_GROUP.search("`a` (or `b`)").group(1) == "b"
    assert P._RE_V610_ALIAS_GROUP.search("`a` (或 `b_alt`)").group(1) == "b_alt"
    # a parenthetical that is NOT an "or"-alias must not match
    assert P._RE_V610_ALIAS_GROUP.search("`a` (optional)") is None
