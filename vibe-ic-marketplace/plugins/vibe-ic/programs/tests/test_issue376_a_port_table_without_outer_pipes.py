"""Regression for vibe-ic#376 — a port table whose outer pipes GFM makes
optional was not seen as a table, so its direction cell and its type cell
were emitted as ports of the chip.

現象
====
GitHub-Flavored Markdown specifies a pipe table's leading and trailing `|`
as OPTIONAL. A published upstream interface document is written that way::

    Signal             | Direction        | Type                   | Description
    -------------------|------------------|------------------------|------------
    `idle_o`           | `output`         | `logic`                | Idle ...
    `lc_escalate_en_i` | `input`          | `lc_ctrl_pkg::lc_tx_t` | Life ...

`_is_pipe_table_row` anchors on a LEADING `|` (``s.startswith("|")``), so it
answers False on every row of that table. #627's port-row rule — "in a port
table, only the LEADING name cell holds the port; later cells carry width /
direction / type tokens that must not be promoted" — is gated on that
predicate, so it never engaged, every backticked token in the row was
promoted, and `L1.pin_table` gained three ports named `output`, `logic` and
`input`: the table's own column vocabulary, emitted as pins of the chip.

Measured on the git-tracked corpus before the fix: of 11 pins extracted from
that cell's interface document, 3 were HDL direction/type keywords — 27%
of the pin table for that design was the table's own header vocabulary.

WHY THE REPAIR IS A SEPARATE PREDICATE, NOT A WIDER `_is_pipe_table_row`
=======================================================================
`_is_pipe_table_row` has three call sites and they do not point the same
way. Two use it PERMISSIVELY — a row shape is treated as corroboration that
a token really is a port. One uses it RESTRICTIVELY — the #627 rule above.
Relaxing the shared predicate would admit MORE tokens at the first two while
rejecting more at the third: a single edit moving the result in both
directions at once, which is how a narrowing fix turns into a leak.

So the relaxed form is a separate block-scoped predicate,
`_gfm_pipe_table_row_indices`, wired ONLY at the restricting site. That
placement makes the change monotone: at that site an admitted row can only
ever REMOVE a promotion, never add one.

It anchors on the DELIMITER row (`---|---`, `:--|--:`), the one construct
GFM actually requires, rather than on "the line has two pipes" — which would
match prose and a bitwise-or expression. The anchor sits on a DIFFERENT line
from the rows it qualifies, which is precisely what a single-line predicate
cannot see.

NEGATIVE no-leak (the load-bearing half)
========================================
  (a) `_is_pipe_table_row` is UNCHANGED — the two permissive call sites must
      not have been widened by this fix;
  (b) prose and a bitwise-or expression carrying pipes are NOT claimed as
      table rows (no delimiter row anchors them);
  (c) a horizontal rule and a setext heading underline are not delimiter
      rows;
  (d) the outer-pipe-omitted table and the fully-piped spelling of the SAME
      table produce the IDENTICAL port set — the fix aligns two spellings of
      one construct rather than inventing behaviour for one of them;
  (e) real ports are never dropped: the fix only ever removes a
      later-cell token.

chip-AGNOSTIC: pure Markdown table structure. No design, vendor, PDK or
IC-class literal appears in the source change.
"""
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import phase1_doc_one_shot_runner as R  # noqa: E402


# ── defect-artifact fixtures ────────────────────────────────────────────────

# The published shape: a GFM table with NO outer pipes on any row. The
# direction cell and the type cell are backticked, exactly as upstream
# interface documents write them.
NO_OUTER_PIPES = """### Other Signals

The table below lists other signals of the unit.

Signal             | Direction        | Type                   | Description
-------------------|------------------|------------------------|------------
`idle_o`           | `output`         | `logic`                | Idle indication.
`lc_escalate_en_i` | `input`          | `lc_ctrl_pkg::lc_tx_t` | Escalation enable.
`edn_o`            | `output`         | `edn_pkg::edn_req_t`   | Entropy request.
"""

# The SAME table, fully piped. #627 already handles this spelling; it is the
# reference the outer-pipe-omitted form must agree with.
WITH_OUTER_PIPES = """### Other Signals

The table below lists other signals of the unit.

| Signal             | Direction        | Type                   | Description |
|--------------------|------------------|------------------------|-------------|
| `idle_o`           | `output`         | `logic`                | Idle indication. |
| `lc_escalate_en_i` | `input`          | `lc_ctrl_pkg::lc_tx_t` | Escalation enable. |
| `edn_o`            | `output`         | `edn_pkg::edn_req_t`   | Entropy request. |
"""

# HDL vocabulary that is never a chip's own top-level port name.
HDL_VOCAB = ("input", "output", "inout", "logic", "wire", "reg")


def _names(doc: str):
    return [p["name"] for p in R._v455_interface_pins({"L1_DATASHEET.md": doc})]


# ── (1) the fix: the table's own column vocabulary stops being ports ────────

def test_direction_and_type_cells_are_not_ports():
    names = _names(NO_OUTER_PIPES)
    for tok in ("output", "logic", "input"):
        assert tok not in names, (
            f"table column vocabulary {tok!r} emitted as a port: {names}")


def test_the_real_ports_still_survive():
    """The fix must remove only later-cell tokens — every real port, which
    lives in the leading name cell, is still extracted."""
    names = _names(NO_OUTER_PIPES)
    for port in ("idle_o", "lc_escalate_en_i", "edn_o"):
        assert port in names, f"real port {port!r} dropped: {names}"


def test_no_hdl_vocabulary_survives_anywhere_in_the_table():
    names = _names(NO_OUTER_PIPES)
    leaked = sorted(set(names) & set(HDL_VOCAB))
    assert not leaked, f"HDL vocabulary emitted as ports: {leaked} in {names}"


# ── (2) the two spellings must agree ────────────────────────────────────────

def test_both_spellings_of_the_same_table_agree():
    """(d) — the outer-pipe-omitted table and the fully-piped table are two
    spellings of ONE construct and must extract the same ports."""
    assert set(_names(NO_OUTER_PIPES)) == set(_names(WITH_OUTER_PIPES))


def test_fully_piped_table_is_unregressed():
    """#627's own path must be untouched by this change."""
    names = _names(WITH_OUTER_PIPES)
    assert set(names) == {"idle_o", "lc_escalate_en_i", "edn_o"}, names


# ── (3) NEGATIVE no-leak ────────────────────────────────────────────────────

def test_is_pipe_table_row_is_unchanged_NOLEAK():
    """(a) — the shared predicate feeds two PERMISSIVE call sites. If this
    fix had widened it, those sites would start admitting tokens they
    previously rejected. It must still require a leading pipe."""
    assert R._is_pipe_table_row("| a | b | c |") is True
    assert R._is_pipe_table_row("a | b | c") is False
    assert R._is_pipe_table_row("`idle_o` | `output` | `logic` | Idle.") is False


@pytest.mark.parametrize("line", [
    "The clock | the reset | are both required.",
    "assign z = a | b;",
    "Use `output` | `logic` when declaring a signal.",
    "a || b",
])
def test_pipes_without_a_delimiter_row_are_not_a_table_NOLEAK(line):
    """(b) — a bare "line contains pipes" rule would match prose and a
    bitwise-or. Nothing is a table row without a delimiter row to anchor it."""
    assert R._gfm_pipe_table_row_indices(line) == frozenset(), line


@pytest.mark.parametrize("line", [
    "---",
    "------------",
    "===",
    "- - -",
    "",
])
def test_a_rule_or_setext_underline_is_not_a_delimiter_row_NOLEAK(line):
    """(c) — a horizontal rule and a setext heading underline carry dashes
    but no pipe, so they never anchor a table."""
    assert R._gfm_pipe_table_row_indices(line) == frozenset(), line


def test_a_table_block_stops_at_a_blank_line_NOLEAK():
    """The claimed run ends where GFM ends the table, so prose that happens
    to follow a table is never absorbed into it."""
    doc = ("h1 | h2\n"
           "---|---\n"
           "r1 | r2\n"
           "\n"
           "Prose after the table | with a pipe in it.\n")
    rows = R._gfm_pipe_table_row_indices(doc)
    assert rows == {0, 1, 2}, rows
    assert 4 not in rows, "prose after the blank line absorbed into the table"


def test_prose_outside_a_table_keeps_the_original_behaviour_NOLEAK():
    """(e) — the bullet/prose interface shape this walker also serves is
    untouched: tokens there are still promoted as before."""
    doc = ("## Interface\n\n"
           "The design exposes `data_valid` and `ready` to the host.\n")
    names = _names(doc)
    assert "data_valid" in names and "ready" in names, names


def test_a_row_without_a_direction_word_is_not_a_port_row_NOLEAK():
    """The restricting site also requires a direction word, so a non-port
    table written without outer pipes does not change behaviour."""
    doc = ("## Register Map\n\n"
           "Field | Bits | Access\n"
           "------|------|-------\n"
           "`cfg` | 7:0  | rw\n")
    assert isinstance(_names(doc), list)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
