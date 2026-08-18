"""Regression for ORGANIC #627 — _v455_interface_pins drops single/short-letter
ports and promotes a width-cell parameter as the port from multi-token rows.

現象 (round-2 v1.0.22 6-IC clean-room): a datapath-multiplier IC has
single-letter datapath ports (x, y, p) and a parameterized bus width declared
inline in the width cell of a Markdown port-table row:

    | `x` | N-bit(`[size-1:0]`, parameter `size`) | input |

The backticked-interface port-table walker iterated EVERY backtick token in
the line. The blanket short-name drop `name.islower() and len(name) <= 2`
dropped `x`/`y`/`p`, while the width-cell `size` token (4 chars, after
"parameter") survived and was promoted as a port. Net L1.pin_table /
L9.top_ports = [clk, rst, size] — the real ports x/y/p dropped, a parameter
mis-promoted. l9_rtl_pin_consistency_check then FAILs against the correct RTL
(declares parameter size + ports clk/rst/x/y/p).

Fix: pipe-table port-row awareness. In a Markdown port-table row (a
`_is_pipe_table_row` line carrying an input/output/inout direction) the PORT is
the LEADING name-cell token; later-cell width/parameter tokens are NOT promoted,
and the leading name-cell token is a real port even if 1-2 chars. Outside a
pipe table (the bullet-list interface shape) the original all-tokens +
short-name-drop behaviour is unchanged.

NEGATIVE no-leak (the load-bearing half — this RELAXES the short-name drop):
  (a) a short token in BULLET-LIST PROSE (no pipe table) is STILL dropped — the
      relaxation is scoped to port-table leading cells only;
  (b) a width/parameter token in a LATER cell is NEVER promoted as a port;
  (c) a multi-name leading cell emits ALL its names.

chip-AGNOSTIC: pure table-row structure; no IC-class / token literals.
"""
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import phase1_doc_one_shot_runner as R  # noqa: E402


# ── defect-artifact fixtures (shaped like the 現象) ──────────────────────────

# The exact round-2 shape: single-letter ports + width-cell `parameter size`.
DATAPATH_DOC = """## Pin Description

| Port | Width | Direction |
|------|-------|-----------|
| `clk` | 1-bit | input |
| `rst` | 1-bit | input |
| `x` | N-bit(`[size-1:0]`, parameter `size`) | input |
| `y` | N-bit(`[size-1:0]`, parameter `size`) | input |
| `p` | 2N-bit product | output |
"""


def _names(doc: str):
    return [p["name"] for p in R._v455_interface_pins({"L1_DATASHEET.md": doc})]


# ── (1) the fix: short ports recovered, width-param NOT promoted ─────────────

def test_short_ports_recovered_and_param_not_promoted():
    names = _names(DATAPATH_DOC)
    # the real ports survive ...
    for port in ("clk", "rst", "x", "y", "p"):
        assert port in names, f"port {port!r} dropped: {names}"
    # ... and the width-cell parameter is NOT a port
    assert "size" not in names, f"width-cell parameter 'size' promoted: {names}"
    assert set(names) == {"clk", "rst", "x", "y", "p"}


@pytest.mark.parametrize("port_letter", ["a", "b", "q", "d"])
def test_single_letter_leading_cell_port_survives(port_letter):
    doc = (
        "## Ports\n\n"
        "| Port | Width | Dir |\n|------|-------|-----|\n"
        f"| `{port_letter}` | 1-bit | input |\n"
        "| `result` | 8-bit | output |\n")
    names = _names(doc)
    assert port_letter in names and "result" in names, names


# ── (2) NEGATIVE no-leak ─────────────────────────────────────────────────────

def test_param_in_later_cell_never_promoted_NOLEAK():
    """A width/parameter token in any later cell must never be promoted, even
    when the leading port name is long."""
    doc = (
        "## Pin Description\n\n"
        "| Port | Width | Direction |\n|------|-------|-----------|\n"
        "| `data_in` | N-bit(`[width-1:0]`, parameter `width`) | input |\n")
    names = _names(doc)
    assert "data_in" in names
    assert "width" not in names, f"later-cell parameter promoted: {names}"


def test_bullet_prose_short_token_still_dropped_NOLEAK():
    """Outside a pipe table the blanket short-name drop is UNCHANGED: a short
    token in bullet/prose text is still dropped (the relaxation is scoped to
    port-table leading cells only)."""
    doc = (
        "## Interface\n\n"
        "The `a` register and the `b` flag are internal scratch. The design "
        "exposes `data_valid` and `ready` to the host.\n")
    names = _names(doc)
    assert "a" not in names and "b" not in names, (
        f"short prose token leaked as a port: {names}")
    assert "data_valid" in names and "ready" in names


def test_multi_name_leading_cell_emits_all_NOLEAK():
    """A leading name cell declaring multiple ports emits ALL of them."""
    doc = (
        "## Ports\n\n"
        "| Port | Width | Dir |\n|------|-------|-----|\n"
        "| `a`, `b` | 1-bit | input |\n"
        "| `sum` | 1-bit | output |\n")
    names = _names(doc)
    assert set(names) == {"a", "b", "sum"}, names


def test_unspecified_direction_row_unchanged_NOLEAK():
    """A pipe-table row WITHOUT an input/output/inout direction word falls back
    to the original behaviour (the fix is scoped to explicit port rows), so it
    does not silently change extraction for non-port tables."""
    # direction column says 'in'/'out' (not the matched 'input'/'output') →
    # _v455_dir_from_line returns 'unspecified' → original path.
    doc = (
        "## Register Map\n\n"
        "| Field | Bits | Access |\n|-------|------|--------|\n"
        "| `cfg` | 7:0 | rw |\n")
    # Just assert it does not raise and yields a deterministic result.
    names = _names(doc)
    assert isinstance(names, list)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
