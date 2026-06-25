#!/usr/bin/env python3
"""Tests for spec_enumset_extract.extract — PROGRAM-FIRST structural extractor
for CVDP enumerated-mode control maps (enum_set + outside-the-set boundary).

Covers (per the deliverable contract):
  (a) POSITIVE — rounding_0001's real 5-mode literal map VERBATIM -> 5 enum_set
      items + 1 enum_boundary;
  (b) §4.05 NEGATIVE — prose says "mode" but no literal map -> [];
  (c) the default-boundary item is emitted WHEN an outside-the-set behavior is
      stated and NOT when it isn't;
  (d) chip-AGNOSTIC rename invariance.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from spec_enumset_extract import extract  # noqa: E402


def _kinds(items):
    return [it["kind"] for it in items]


def _enum_sets(items):
    return [it for it in items if it["kind"] == "enum_set"]


def _boundaries(items):
    return [it for it in items if it["kind"] == "enum_boundary"]


# ---------------------------------------------------------------------------
# (a) POSITIVE — rounding_0001's real 5-mode literal map, embedded VERBATIM.
# ---------------------------------------------------------------------------
ROUNDING_0001_MODES = """\
- **`rm`**:
  - Data type: `logic [2:0]`
  - Description: Rounding mode selection.
  - Supported Modes:
    - **`RNE` (Round to Nearest, Even)**: `3'b000`
    - **`RTZ` (Round Toward Zero)**: `3'b001`
    - **`RUP` (Round Toward Positive Infinity)**: `3'b010`
    - **`RDN` (Round Toward Negative Infinity)**: `3'b011`
    - **`RMM` (Round to Nearest Maximum Magnitude)**: `3'b100`

### **Behavior**:

2. **Edge Cases**:
   - If `rm` specifies an unsupported mode (i.e., values other than `3'b000` to
     `3'b100`), the design should default to no rounding (equivalent to `RTZ`
     behavior).
"""


def test_rounding_0001_five_modes_plus_boundary():
    items = extract(ROUNDING_0001_MODES)
    sets = _enum_sets(items)
    bounds = _boundaries(items)
    # exactly the 5 supported modes + 1 outside-the-set boundary
    assert len(sets) == 5, _kinds(items)
    assert len(bounds) == 1, _kinds(items)
    # every one of the 5 mode codes is recovered as a member
    codes = {it["coverage_tokens"][0] for it in sets}
    assert codes == {"3'b000", "3'b001", "3'b010", "3'b011", "3'b100"}, codes
    # each enum_set carries the EXACT literal as evidence
    for it in sets:
        assert it["coverage_tokens"][0] in it["evidence"]
        assert it["kind"] == "enum_set"
    # the boundary evidence is the stated outside-the-set behavior prose
    b = bounds[0]
    assert "__OUTSIDE_SET__" in b["coverage_tokens"]
    assert "other than" in b["evidence"].lower()
    assert "default" in b["evidence"].lower()


def test_rounding_0001_modes_carry_named_meaning():
    """The 5 modes are recovered with their named-mode labels (RNE..RMM)."""
    items = extract(ROUNDING_0001_MODES)
    sets = _enum_sets(items)
    names = {tok for it in sets for tok in it["coverage_tokens"]}
    for name in ("RNE", "RTZ", "RUP", "RDN", "RMM"):
        assert name in names, names


# ---------------------------------------------------------------------------
# (b) §4.05 NEGATIVE — prose says "mode" but NO literal map -> [].
# ---------------------------------------------------------------------------
PROSE_NO_LITERALS = """\
The module supports several rounding modes. Each mode rounds the fixed-point
input differently. The selected mode determines whether the value is rounded up,
down, toward zero, or to the nearest even. The design must be combinational and
default to no rounding for any unsupported mode.
"""


def test_negative_prose_mode_no_literal_map_returns_empty():
    assert extract(PROSE_NO_LITERALS) == []


def test_negative_single_value_returns_empty():
    """A single literal value is not an enumerated set (>=3 required)."""
    text = "The reset value is `3'b000` and the design is fully combinational."
    assert extract(text) == []


def test_negative_two_values_returns_empty():
    """Two literal values still fall under the >=3 §4.05 floor."""
    text = ("Mode `2'b00` selects pass-through and mode `2'b01` selects invert. "
            "There are no other modes.")
    assert extract(text) == []


def test_negative_empty_and_blank():
    assert extract("") == []
    assert extract("   \n\t ") == []


# ---------------------------------------------------------------------------
# (c) the default-boundary item is emitted WHEN an outside-the-set behavior is
#     stated and NOT when it isn't.
# ---------------------------------------------------------------------------
MAP_WITH_BOUNDARY = """\
The opcode selects the operation:
- `3'b000`: ADD
- `3'b001`: SUB
- `3'b010`: AND
- `3'b011`: OR
Any other opcode value is invalid and the result must remain zero.
"""

MAP_WITHOUT_BOUNDARY = """\
The opcode selects the operation:
- `3'b000`: ADD
- `3'b001`: SUB
- `3'b010`: AND
- `3'b011`: OR
The output is registered on the rising clock edge.
"""


def test_boundary_emitted_when_outside_set_behavior_stated():
    items = extract(MAP_WITH_BOUNDARY)
    assert len(_enum_sets(items)) == 4, _kinds(items)
    bounds = _boundaries(items)
    assert len(bounds) == 1, _kinds(items)
    assert "invalid" in bounds[0]["evidence"].lower()


def test_boundary_not_emitted_when_no_outside_set_behavior():
    items = extract(MAP_WITHOUT_BOUNDARY)
    assert len(_enum_sets(items)) == 4, _kinds(items)
    assert _boundaries(items) == [], _kinds(items)


def test_boundary_skips_code_comment_and_unrelated_default():
    """A `// default` code comment or a 'default key value' (no selector noun)
    is NOT a stated outside-the-set behavior -> no boundary item."""
    text = """\
The operation is chosen by op_select:
- `2'b00`: pass
- `2'b01`: invert
- `2'b10`: shift
The internal key has a default value of `0xAA` and is configurable.
"""
    items = extract(text)
    assert len(_enum_sets(items)) == 3, _kinds(items)
    # "default value of 0xAA" is about the KEY, not about an outside-the-set
    # code, so no boundary is charged.
    assert _boundaries(items) == [], _kinds(items)


# ---------------------------------------------------------------------------
# (d) chip-AGNOSTIC rename check — renaming the modes/signals must not change
#     the recovered structure (the extractor keys on the literal-map SHAPE, not
#     any problem-id / chip / signal name).
# ---------------------------------------------------------------------------
def test_chip_agnostic_rename_invariance():
    base = """\
The control map selects the operation:
- **`MODE_A`**: `3'b000`
- **`MODE_B`**: `3'b001`
- **`MODE_C`**: `3'b010`
- **`MODE_D`**: `3'b011`
Any other value defaults to no operation.
"""
    renamed = (base
               .replace("MODE_A", "ROUND_NEAR")
               .replace("MODE_B", "ROUND_ZERO")
               .replace("MODE_C", "ROUND_UP")
               .replace("MODE_D", "ROUND_DOWN")
               .replace("control map", "rounding selector"))
    a = extract(base)
    b = extract(renamed)
    # same number of enum_set + enum_boundary items regardless of names
    assert len(_enum_sets(a)) == len(_enum_sets(b)) == 4
    assert len(_boundaries(a)) == len(_boundaries(b)) == 1
    # same set of CODE literals (the literal-map shape is invariant under rename)
    codes_a = {it["coverage_tokens"][0] for it in _enum_sets(a)}
    codes_b = {it["coverage_tokens"][0] for it in _enum_sets(b)}
    assert codes_a == codes_b == {"3'b000", "3'b001", "3'b010", "3'b011"}


def test_pipe_table_and_param_and_case_shapes_all_recover():
    """The three other literal-map shapes (pipe table / parameter decl / case
    label) each recover their members — shape-keyed, chip-AGNOSTIC."""
    pipe = """\
| **Type** | **Value** |
|----------|-----------|
| IDLE     | `0x07`    |
| START    | `0xFB`    |
| STOP     | `0xFD`    |
| ERR      | `0xFE`    |
"""
    param = """\
    localparam IDLE    = 3'b000,
               GRANT_1 = 3'b001,
               GRANT_2 = 3'b010,
               CLEAR   = 3'b011;
"""
    case = """\
        case (speed)
          3'd1 : duty <= 8'd64;
          3'd2 : duty <= 8'd128;
          3'd3 : duty <= 8'd192;
          3'd4 : duty <= 8'd255;
        endcase
"""
    assert len(_enum_sets(extract(pipe))) == 4
    assert len(_enum_sets(extract(param))) == 4
    assert len(_enum_sets(extract(case))) == 4


def test_returns_plain_dicts_with_checklistitem_shape():
    """extract() returns dicts carrying the ChecklistItem-shaped fields so they
    merge into spec_coverage_check's checklist."""
    items = extract(MAP_WITH_BOUNDARY)
    assert items, "expected non-empty"
    for it in items:
        assert set(["kind", "requirement", "evidence", "coverage_tokens",
                    "provenance", "block_eligible"]).issubset(it.keys())
        assert it["kind"] in ("enum_set", "enum_boundary")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
