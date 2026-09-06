#!/usr/bin/env python3
"""#2060 — the docs door reads a port list written as a code block or a signal
table, and the directory name never reaches a published L1 string.

Everything below was MEASURED on live main 6c42686565706a (v1.17.94) on 8HD-6,
over the 18 real prompt-entry design inputs lane cz2052 named (its
`corpus/zeroport_inputs.txt`; the lane record holds the list), BEFORE
any edit:

    18 designs, 60 ports, 9 of them ZERO-port.

Of those nine, exactly ONE declares an interface anywhere in its text —
`binary_to_BCD_0001`, in a ```verilog fence holding
`input logic [7:0] binary_in,  // 8-bit binary input`. The other eight are
lint-review / area-optimisation / benchmark-brief prompts that declare no port
at all, and ZERO is the true count for them. (The claim handed to this lane,
that the nine exit "rc 1 EXTRACTION GAP", does not survive measurement: all
nine exit rc=0, and the four rc=1 runs are the four PORT-RICH designs failing
`l6_fsm_scaffold_actionable_check`. Two disjoint facts about one population.)

ITEM 1 — the grammar. `phase1_port_extract` already owned the shared reader,
and its own region finder defeated its own anti-phantom contract:
`_MODULE_SPAN = r'\bmodule\b.*?\bendmodule\b'` opened a "Verilog region" on the
English WORD "module". Every one of these prompts says "module" in its first
prose sentence and closes a fence with `endmodule`, so the span was the WHOLE
DOCUMENT, `_looks_like_verilog` said yes (there IS a real module header inside
it) and `parse_verilog_ports` ran over running English. Measured on base,
`extract_ports` returned 12 ports for `binary_search_tree_sorting_0001`, six of
them the words `array`, `managing`, `until`, `one` and the internal register
`temp_data` read out of a `mermaid` flowchart. A span now OPENS on a real
module HEADER — `module <name>` followed by `(`, `#(` or `;`.

`extract_code_block_ports` is that grammar as a public reader with EVIDENCE:
every port carries the source line it was read from, so a published port can be
checked against the document that stated it. It needs a direction, an optional
width and an RTL-shaped identifier standing where Verilog declares a port, or a
table row under a header with both a name and a DIRECTION column. A prose
sentence yields nothing; a waveform table (`| Clock Cycle | clk | rst_n |
data_in |`) has no direction column and yields nothing.

ITEM 2 — `cli._stub_l_docs_from_prose` derived `mod_name` from
`docs_dir.parent.name` and put it in `L1.ic_name` and `L1.summary`. #2049 closed
the TOP; the chip NAME kept the directory, and the prompt front door bridges its
input into `<proj>/input/docs/`, so a design that stated no name was published as
a chip called `input`. An input that declares no name has an UNDECLARED one.

Both directions throughout: each mutation restores the exact pre-fix rule and
the rows go red again, and every control names what must NOT move.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
PLUGIN = PROGRAMS.parent
sys.path.insert(0, str(PROGRAMS))
sys.path.insert(0, str(PLUGIN / "tools"))

import phase1_port_extract as PPX              # noqa: E402
from phase1_engine import cli as CLI           # noqa: E402


# ── ITEM 1 — a port list written as a code block ──────────────────────

#: The measured shape of `binary_to_BCD_0001`: a prose sentence that says the
#: word "module", then a ```verilog fence whose declarations carry a numeric
#: width AND a trailing comment. On base the docs door read ZERO ports from it.
_CODE_BLOCK_INPUT = """\
Complete the given partial System Verilog module `binary_to_bcd` to implement
the converter. The design is implemented as combinational logic to ensure an
immediate output when the input changes.

```verilog
    module binary_to_bcd (
        input logic [7:0] binary_in,  // 8-bit binary input
        output logic [11:0] bcd_out   // 12-bit BCD output (3 digits)
        );
    endmodule
```
"""

#: The measured shape of `elastic_buffer_0001`: a BARE ``` fence (no language
#: tag, so the docs door's `_extract_verilog_blocks` never sees it) with
#: SYMBOLIC widths and aligned trailing comments.
_BARE_FENCE_SYMBOLIC = """\
The elastic buffer module matches a pattern against the incoming data and
signals whether the two are equal.

```
module elastic_buffer_pattern_matcher #(
   parameter WIDTH = 8
 )(
   input                         clk      , // clock input
   input                         rst      , // Active high synchronous reset
   input         [WIDTH-1:0]     i_data   , // input data to be matched
   input         [WIDTH-1:0]     i_pattern, // pattern to be matched against
   output logic                  o_match    // output indicating a match
 );
   function automatic check;
      input [WIDTH-1:0] scratch;
      check = 1'b0;
   endfunction
endmodule
```
"""

#: The measured shape of `binary_search_tree_sorting_0001`: a `mermaid` fence
#: naming internal registers, then a real ```verilog fence. `temp_data` is a
#: flowchart node and an internal `reg`; it is NOT a port.
_MERMAID_THEN_VERILOG = """\
The design consists of a single module that sorts an array by managing a tree
until one element is left.

```mermaid
flowchart TD
    X(INIT) --> C(Store input as temp_data)
    C(Store input as temp_data) --> E{root = empty}
```
```verilog
module binary_search_tree_sort #(
    parameter DATA_WIDTH = 32
) (
    input clk,
    input reg [DATA_WIDTH-1:0] data_in, // Input data to be sorted
    input start,
    output reg [DATA_WIDTH-1:0] sorted_out, // Sorted output
    output reg done
);
    reg [DATA_WIDTH-1:0] temp_data; // Temporary data register
endmodule
```
"""

#: The measured shape of `scrambler_0001`: a WAVEFORM table. Its header names
#: signals but has no DIRECTION column, so it is not a signal table.
_WAVEFORM_TABLE = """\
The `scrambler` module scrambles the input data. Observed behavior:

| Clock Cycle | clk    | rst_n | mode | data_in    | data_out   |
|-------------|--------|-------|------|------------|------------|
| 1           | Rising | 0     | 0    | 0xFFFFFFFF | 0x40004000 |
| 2           | Rising | 1     | 0    | 0xEF0B5E84 | 0xEF085E87 |
"""

#: A real signal table: a header with BOTH a name and a direction column.
_SIGNAL_TABLE = """\
The module presents this interface.

| Signal   | Direction | Width | Description        |
|----------|-----------|-------|--------------------|
| `clk`    | input     | 1     | Clock              |
| `rst_n`  | input     | 1     | Active-low reset   |
| `q_out`  | output    | 8     | Registered output  |
"""


def _names(text):
    return [e["name"] for e in PPX.extract_code_block_ports(text)]


def test_a_fenced_port_list_with_widths_and_trailing_comments_is_read():
    """RED before: the docs door's `_RE_VERILOG_PORT_DECL` ends at
    `\\s*,?\\s*$`, so a trailing `// 8-bit binary input` dropped the whole
    declaration and this real design published ZERO ports."""
    assert _names(_CODE_BLOCK_INPUT) == ["binary_in", "bcd_out"]


def test_a_read_port_carries_the_source_line_it_was_read_from():
    """The evidence #2060 asks for: a published port can be checked against
    the document that stated it, not merely believed."""
    for entry in PPX.extract_code_block_ports(_CODE_BLOCK_INPUT):
        assert entry["source_line"] in _CODE_BLOCK_INPUT.replace(
            "\n", "\n").split("\n") or entry["source_line"] in [
                ln.strip() for ln in _CODE_BLOCK_INPUT.splitlines()]
        assert entry["name"] in entry["source_line"]
        assert entry["dir"] in entry["source_line"]
        assert entry["extraction_strategy"] == PPX.CODE_REGION_PORT_STRATEGY


def test_a_bare_fence_with_symbolic_widths_is_read_and_the_width_resolves():
    """A fence with no language tag is still a code block, and `[WIDTH-1:0]`
    resolves against the module's OWN parameter — matching one declaration at a
    time must not cost the width only the region can supply."""
    entries = PPX.extract_code_block_ports(_BARE_FENCE_SYMBOLIC)
    got = {e["name"]: e["width"] for e in entries}
    assert list(got) == ["clk", "rst", "i_data", "i_pattern", "o_match"]
    assert got["i_data"] == 8 and got["i_pattern"] == 8
    assert got["clk"] == 1


def test_a_subprogram_local_declaration_is_not_a_module_port():
    """CONTROL. `input [WIDTH-1:0] scratch;` inside a `function` body is a
    subprogram argument, not a port of the design."""
    assert "scratch" not in _names(_BARE_FENCE_SYMBOLIC)


def test_a_non_verilog_fence_yields_nothing_and_an_internal_reg_is_not_a_port():
    """CONTROL. `temp_data` is a mermaid flowchart node and an internal `reg`.
    Lane cz2052 quoted it among the eight names "with RTL identifier shape"
    that the retired stub found — a reader that returns it is WORSE, not
    better."""
    got = _names(_MERMAID_THEN_VERILOG)
    assert got == ["clk", "data_in", "start", "sorted_out", "done"]
    assert "temp_data" not in got


def test_prose_around_a_code_block_never_yields_a_port():
    """RED before, in this module's OWN region finder: with `_MODULE_SPAN`
    opening on the word "module", the span covered the whole document and
    `array`, `managing`, `until`, `one`, `changes`, `combinational` were
    published as ports of real designs."""
    for text in (_CODE_BLOCK_INPUT, _BARE_FENCE_SYMBOLIC,
                 _MERMAID_THEN_VERILOG):
        for phantom in ("changes", "combinational", "array", "managing",
                        "until", "one", "signals", "whether", "the", "data"):
            assert phantom not in _names(text), (phantom, text[:40])


def test_a_module_named_only_in_prose_is_not_a_port_and_opens_no_region():
    """CONTROL, measured on `dot_product_0012`: "The given design consists of a
    single module: - **`dot_product`:**" states a MODULE NAME. It is the second
    of cz2052's eight identifier-shaped stub names that must be refused."""
    text = ("The given design consists of a single module:\n"
            "- **`dot_product`:** The module computes the dot product of two "
            "input vectors using an FSM computational flow.\n")
    assert PPX.extract_code_block_ports(text) == []


def test_a_signal_table_is_read_and_a_waveform_table_is_not():
    """GRAMMAR, not a token match: the difference between the two is a
    DIRECTION column, and both real inputs are in the measured 18."""
    assert _names(_SIGNAL_TABLE) == ["clk", "rst_n", "q_out"]
    assert PPX.extract_code_block_ports(_WAVEFORM_TABLE) == []


def test_a_width_the_table_does_not_state_is_a_scalar_not_an_unknown():
    """THREE answers, not two. A cell that is not a number is UNKNOWN — the
    document states a width this reader cannot resolve, so it must not invent
    1. But NO width cell at all is a DECLARATION that the port is 1 bit, the
    same contract `parse_verilog_ports` states for a port with no packed
    dimension. Conflating the two lost 162 real port widths across 41 design
    inputs, on rows like `| clk | input |`."""
    two_col = ("| Signal | Direction |\n|---|---|\n"
               "| clk | input |\n| reset_n | input |\n")
    assert {e["name"]: e["width"]
            for e in PPX.extract_code_block_ports(two_col)} == {
                "clk": 1, "reset_n": 1}
    symbolic = ("| Signal | Direction | Width |\n|---|---|---|\n"
                "| irq | input | NUM_INTERRUPTS |\n| clk | input | 1 |\n")
    assert {e["name"]: e["width"]
            for e in PPX.extract_code_block_ports(symbolic)} == {
                "irq": 0, "clk": 1}
    # …and the distinction is exactly which of the two the cell is
    assert PPX._stated_width("") == 1 and PPX._stated_width("   ") == 1
    assert PPX._stated_width("NUM_INTERRUPTS") == 0
    assert PPX._stated_width("8") == 8 and PPX._stated_width("[7:0]") == 8
    # a cell that STATES a number without being only that number — a real row
    # from a real interface table. Refusing it loses a width the document
    # gives, which is the same failure as inventing one, in the other direction.
    assert PPX._stated_width("24-bit (`[23:0]`)") == 24
    assert PPX._stated_width("8 bits") == 8
    # …and a SYMBOLIC bound in the same shape stays UNKNOWN
    assert PPX._stated_width("N-bit (`[DEPTH-1:0]`)") == 0


def test_a_table_read_port_quotes_its_row():
    entries = PPX.extract_code_block_ports(_SIGNAL_TABLE)
    for e in entries:
        assert e["extraction_strategy"] == PPX.SIGNAL_TABLE_PORT_STRATEGY
        assert e["source_line"].startswith("|")
        assert e["name"] in e["source_line"]


def test_extract_ports_runs_the_same_one_implementation():
    """The two front doors must not drift the way they drifted on the top
    module vocabulary (#2052). `extract_ports`'s code/table tier IS
    `extract_code_block_ports`, by construction."""
    for text in (_CODE_BLOCK_INPUT, _BARE_FENCE_SYMBOLIC, _SIGNAL_TABLE,
                 _MERMAID_THEN_VERILOG):
        assert [p["name"] for p in PPX.extract_ports(text)] == _names(text)
        for p in PPX.extract_ports(text):
            assert set(p) == {"name", "dir", "width"}


def test_mutation_restoring_the_bare_word_module_span_re_reddens_the_phantoms():
    """MUTATION. The exact pre-#2060 expression. Restore it and running English
    becomes a Verilog region again — the phantoms come straight back, which is
    what makes the rows above a check rather than a description."""
    pre_2060 = re.compile(r'\bmodule\b.*?\bendmodule\b', re.S)
    saved = PPX._MODULE_SPAN
    try:
        PPX._MODULE_SPAN = pre_2060
        mutated = _names(_CODE_BLOCK_INPUT)
        assert "the" in mutated, mutated
        assert "changes" in mutated, mutated
        mutated_bst = _names(_MERMAID_THEN_VERILOG)
        assert "temp_data" in mutated_bst, mutated_bst
    finally:
        PPX._MODULE_SPAN = saved
    # …and the restore really restored: the fixed answer is back.
    assert "the" not in _names(_CODE_BLOCK_INPUT)
    assert "changes" not in _names(_CODE_BLOCK_INPUT)
    assert "temp_data" not in _names(_MERMAID_THEN_VERILOG)


def test_the_mutation_is_reached_and_the_fixed_span_still_reads_real_code():
    """A dead mutation reads as a weak guard. Both spans must MATCH this input
    — the fix is which OFFSET the span opens at, not whether it fires."""
    assert re.compile(r'\bmodule\b.*?\bendmodule\b', re.S).search(
        _CODE_BLOCK_INPUT)
    assert PPX._MODULE_SPAN.search(_CODE_BLOCK_INPUT)
    assert PPX._MODULE_SPAN.search(_CODE_BLOCK_INPUT).group(0).startswith(
        "module binary_to_bcd")


# ── ITEM 2 — the directory name never reaches a published string ──────

_PROSE_NO_NAME = ("Implement a framed serial receiver that raises a done "
                  "flag when a frame completes.\n")
_PROSE_WITH_NAME = ("Module name: framed_rx\n\n"
                    "Implement a framed serial receiver that raises a done "
                    "flag when a frame completes.\n")


def _stub(tmp_path, prose, ic_name=None, parent="zzparent"):
    docs = tmp_path / parent / "docs"
    docs.mkdir(parents=True)
    (docs / "prompt.md").write_text(prose)
    out = tmp_path / parent / "out"
    n = CLI._stub_l_docs_from_prose(docs, out, ic_name=ic_name)
    return out, n


def test_an_input_that_declares_no_name_publishes_undeclared_not_the_directory(
        tmp_path):
    """RED before: `mod_name = … else docs_dir.parent.name`, so this published
    a chip called `zzparent` — and, through the prompt front door's own bridge
    into `<proj>/input/docs/`, a chip called `input`."""
    out, _n = _stub(tmp_path, _PROSE_NO_NAME)
    l1 = json.loads((out / "L1_DATASHEET.json").read_text())
    assert l1["ic_name"] == CLI.NAME_UNDECLARED == "undeclared"
    assert "zzparent" not in l1["summary"]
    assert "undeclared" in l1["summary"]


def test_the_directory_name_reaches_no_published_string_in_any_layer(
        tmp_path):
    """MEMBERSHIP, not one field: the whole stub layer set is searched."""
    out, n = _stub(tmp_path, _PROSE_NO_NAME)
    assert n == 14
    published = sorted(p.name for p in out.glob("L*.json"))
    assert len(published) == 14, published
    for p in out.glob("L*.json"):
        assert "zzparent" not in p.read_text(), p.name


def test_control_an_input_that_declares_a_name_is_unchanged(tmp_path):
    """CONTROL. The fix touches ONLY the fallback branch; a declared name must
    move by zero, in both the name and the summary."""
    out, _n = _stub(tmp_path, _PROSE_WITH_NAME)
    l1 = json.loads((out / "L1_DATASHEET.json").read_text())
    assert l1["ic_name"] == "framed_rx"
    assert l1["summary"] == "Stub L1 for framed_rx (from prose .md)."
    assert "undeclared" not in l1["summary"]


def test_control_an_explicit_ic_name_still_wins(tmp_path):
    """CONTROL. `--ic-name` is authoritative for the CHIP name (CLI > docs,
    #541) and is consulted first; no caller that names its chip is affected."""
    out, _n = _stub(tmp_path, _PROSE_NO_NAME, ic_name="probe_ic")
    l1 = json.loads((out / "L1_DATASHEET.json").read_text())
    assert l1["ic_name"] == "probe_ic"
    # the SUMMARY still refuses to name the directory
    assert "zzparent" not in l1["summary"]


def test_control_the_top_module_refusal_2049_2052_shipped_is_untouched(
        tmp_path):
    """CONTROL. This lane changes the NAME slot only. The top must still be
    the refusal the docs door defines, not a name and not a directory."""
    out, _n = _stub(tmp_path, _PROSE_NO_NAME)
    l9 = json.loads((out / "L9_INTEGRATION_SPEC.json").read_text())
    assert l9["top_module"] is None
    assert l9["top_module_status"] in ("top_undeclared", "docs_door_unavailable")


def test_mutation_restoring_the_directory_fallback_republishes_the_directory(
        tmp_path):
    """MUTATION, cz2049's proof shape. Restore the exact pre-#2060 expression
    and a design staged under `zzparent/` is published as `zzparent` again."""
    saved = CLI.NAME_UNDECLARED
    try:
        # the pre-fix rule is `docs_dir.parent.name`; the constant is the ONE
        # place the fixed rule reads, so re-pointing it at the directory name
        # reproduces the defect exactly.
        CLI.NAME_UNDECLARED = "zzparent"
        out, _n = _stub(tmp_path, _PROSE_NO_NAME, parent="zzparent")
        l1 = json.loads((out / "L1_DATASHEET.json").read_text())
        assert l1["ic_name"] == "zzparent"
        assert "zzparent" in l1["summary"]
    finally:
        CLI.NAME_UNDECLARED = saved


def test_both_mirrors_of_the_engine_carry_the_fix():
    """The engine ships in two trees and they are byte-identical by an existing
    gate; this pins the RULE, so a half-applied re-mirror is caught by content
    and not only by hash."""
    mirrors = [PLUGIN.parent.parent.parent / "tools/phase1_engine/cli.py",
               PLUGIN / "tools/phase1_engine/cli.py"]
    for m in mirrors:
        assert m.is_file(), m
        src = m.read_text()
        assert "NAME_UNDECLARED = \"undeclared\"" in src, m
        assert "else NAME_UNDECLARED" in src, m
        assert "else docs_dir.parent.name" not in src, m
