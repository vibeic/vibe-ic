"""#592 — an enum table whose code column is hex had no lift path.

`CTRL_SHADOWED.MODE` in the OpenTitan AES register doc states its encoding as

    | Value | Name    | Description                                    |
    | 0x01  | AES_ECB | 6'b00_0001: Electronic Codebook (ECB) mode.    |

and every existing path yielded ZERO typed `enumerated_values`, so
`l4_regmap_enumerated_values_typed_check` FAILed on a field the document
describes completely. The three misses, each measured in the issue:

  * Tier 2 (pipe-table) hard-requires column 1 to be a BARE BINARY string;
    `0x01` is hex and matches no row.
  * Tier 1 (prose) requires `<binary>[:=]<mnem>` adjacency; the binary here is
    followed by a sentence.
  * the v1.7.72 code-literal lifter requires a fragment to declare exactly ONE
    literal, and each row declares two — the hex code and the col-3 binary.

SELF-CHECKING IS WHY A NUMERIC FIRST COLUMN CAN BE LIFTED AT ALL. Tier 2b
accepts a row only when the DESCRIPTION carries a literal that renders to the
same width-`width` pattern as column 1. The two are independent statements by
the document; requiring them to agree is what stops an arbitrary
`| number | name | text |` table — a register offset map, a pin list — from
being read as an encoding. Under-extraction is the safe direction: a table that
states its code once is simply not lifted here.

MEASURED ON THE REAL TRACKED DOCUMENT, not on a fixture transcribed from the
issue: `benchmark-data/ic/opentitan_aes/phase1/input_doc/aes_registers.txt`
yields 21 lifted rows across three fields (a 3-bit reseed rate, a 3-bit key
length, and the 6-bit MODE). The issue's excerpt names the last MODE mnemonic
`AES_NONE`; the shipped document says `AES_GCM`, and what is asserted below is
what the document says.
"""
from __future__ import annotations

import importlib.util
import pathlib
import re
import sys

import pytest

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
_REPO = _PROGRAMS.parents[3]
_SRC = (_PROGRAMS / "phase1_doc_one_shot_runner.py").read_text(encoding="utf-8")


def _load(name, fn):
    """Import a sibling program by path, and NEVER as a second identity.

    Returning early when the name is already imported is the whole point.
    Unconditionally rebinding `sys.modules[name]` builds a SECOND module
    object for one file, and every module that already did
    `from <name> import X` keeps the FIRST X. The suite then fails an
    identity assertion in a file that has nothing to do with this one.

    MEASURED, before this guard, in one pytest process over three files in
    collection order:

        test_crc_polynomial_width.py           imports phase1_doc_one_shot_runner,
                                               which binds _code_literal.CODE_LITERAL_RE
        test_issue592_hex_enum_table_lift.py   rebinds sys.modules["_code_literal"]
        test_v1_7_72_..._code_literals.py      CL, and l4_regmap_... imported after,
                                               both see the NEW object

    so `test_gate_and_lifter_share_one_reader` failed on
    `RUNNER._CODE_LITERAL_RE is CL.CODE_LITERAL_RE` while the `L4GATE` assert
    one line above passed — the asymmetry that identifies this cause and not
    a drifted regex.
    """
    mod = sys.modules.get(name)
    if mod is not None:
        return mod
    spec = importlib.util.spec_from_file_location(name, _PROGRAMS / fn)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


CL = _load("_code_literal", "_code_literal.py")


def _row_re():
    """The shipped Tier-2b pattern, compiled from the source.

    Read out of the module rather than restated here: a second copy would be a
    second thing to keep in step and would check neither against the code.
    """
    m = re.search(r"_V1_6_592_ENCODING_TABLE_HEXROW_RE = re\.compile\((.*?)\n\)",
                  _SRC, re.S)
    assert m, "the Tier-2b row pattern is gone"
    return eval("re.compile(" + m.group(1) + "\n)", {"re": re})


RE = _row_re()


def _lift(text, width):
    """What Tier 2b would emit: (pattern, mnem) per corroborated row."""
    out = []
    for m in RE.finditer(text):
        desc = (m.group("desc") or "").strip().lstrip("|").strip()
        pat = CL.to_binary_pattern(m.group("code"), width)
        if pat is None or len(pat) != width:
            continue
        if not any(CL.to_binary_pattern(t, width) == pat
                   for t in CL.CODE_LITERAL_RE.findall(desc)):
            continue
        out.append((pat, m.group("mnem")))
    return out


_TABLE = """### CTRL_SHADOWED . MODE
6-bit one-hot field to select AES block cipher mode.
| Value | Name | Description |
| 0x01 | AES_ECB | 6'b00_0001: Electronic Codebook (ECB) mode. |
| 0x02 | AES_CBC | 6'b00_0010: Cipher Block Chaining (CBC) mode. |
| 0x04 | AES_CFB | 6'b00_0100: Cipher Feedback (CFB) mode. |
"""


# ── the shape that had no path ──────────────────────────────────────────────
def test_a_hex_code_column_is_lifted():
    got = _lift(_TABLE, 6)
    assert got == [("000001", "AES_ECB"), ("000010", "AES_CBC"),
                   ("000100", "AES_CFB")], got


def test_a_sized_literal_code_column_is_lifted():
    """`6'b00_0001` in column 1 — the other form the same table can take."""
    t = "| 6'b00_0010 | AES_CBC | 0x02: Cipher Block Chaining. |\n"
    assert _lift(t, 6) == [("000010", "AES_CBC")]


def test_a_0b_prefixed_code_column_is_lifted():
    t = "| 0b000100 | AES_CFB | 6'b00_0100: Cipher Feedback. |\n"
    assert _lift(t, 6) == [("000100", "AES_CFB")]


# ── the guard, which is the whole reason this is safe ───────────────────────
def test_a_register_offset_table_is_not_read_as_an_encoding():
    """LOAD-BEARING. `| number | name | text |` is the shape of a register map,
    a pin list, a priority table. Only a row whose description RESTATES the
    code is lifted."""
    t = ("| 0x10 | STATUS_REG | offset of the status register |\n"
         "| 0x14 | CTRL_REG | offset of control |\n")
    assert _lift(t, 6) == []


def test_a_description_naming_a_DIFFERENT_code_is_not_corroboration():
    """A literal that disagrees is worse than none: it says the row means
    something else."""
    t = "| 0x01 | AES_ECB | 6'b00_0010: not this one. |\n"
    assert _lift(t, 6) == []


def test_a_code_too_wide_for_the_field_is_refused():
    t = "| 0xFF | WIDE | 8'b1111_1111: too wide for a 6-bit field. |\n"
    assert _lift(t, 6) == []


def test_the_bare_binary_shape_is_left_to_tier_2():
    """Tier 2 already owns it. Two tiers emitting the same row would double
    the enumeration, and the key set only dedups exact (pattern, mnem) pairs."""
    t = "| 000001 | AES_ECB | 6'b00_0001: ECB. |\n"
    assert _lift(t, 6) == [], "Tier 2b is matching Tier 2's shape as well"


# ── the real document ───────────────────────────────────────────────────────
def test_the_real_opentitan_doc_lifts_the_mode_field():
    """Not a transcription of the issue — the tracked input the runner reads."""
    doc = (_REPO / "benchmark-data/ic/opentitan_aes/phase1/input_doc"
           / "aes_registers.txt")
    if not doc.is_file():
        pytest.skip("the tracked input doc is absent")
    # SCOPED TO THE FIELD, as the runner is — it lifts inside a per-field
    # `window_text`. Scanning the whole document at one width conflates fields:
    # this doc has a second 6-bit table whose `0x01` is `GCM_INIT`, and a
    # document-wide dict lets the later table overwrite the earlier one. The
    # first version of this test did exactly that and reported the wrong
    # mnemonic for a correct extraction.
    text = doc.read_text(errors="replace")
    start = text.index("### CTRL_SHADOWED . MODE")
    end = text.find("###", start + 5)
    got = dict(_lift(text[start:end if end > 0 else len(text)], 6))
    for pat, mnem in (("000001", "AES_ECB"), ("000010", "AES_CBC"),
                      ("000100", "AES_CFB"), ("001000", "AES_OFB"),
                      ("010000", "AES_CTR")):
        assert got.get(pat) == mnem, f"{pat} -> {got.get(pat)!r}, want {mnem}"
    assert len(got) >= 6, f"only {len(got)} MODE rows lifted"


def test_the_real_doc_also_lifts_the_narrower_fields():
    """Three fields in that document use this shape, at two different widths —
    evidence the tier is not tuned to one table."""
    doc = (_REPO / "benchmark-data/ic/opentitan_aes/phase1/input_doc"
           / "aes_registers.txt")
    if not doc.is_file():
        pytest.skip("the tracked input doc is absent")
    text = doc.read_text(errors="replace")
    assert len(_lift(text, 3)) >= 6, "the 3-bit tables stopped lifting"


# ── it is wired, not merely defined ─────────────────────────────────────────
#
# The first version of this asserted the SOURCE STRING
# `_V1_6_592_ENCODING_TABLE_HEXROW_RE.finditer(window_text)` was present.
# Commenting the loop out left that string in the file and the assertion passed
# — the comments-vs-code trap, from the direction where the comment SATISFIES
# the scan instead of breaking it. It drives the real function now.
@pytest.fixture(scope="module")
def runner():
    return _load("phase1_doc_one_shot_runner", "phase1_doc_one_shot_runner.py")


def test_the_tier_is_actually_called(runner):
    """The failure this repo keeps finding: a correct routine nothing invokes."""
    field = {"name": "MODE", "width": 6}
    n = runner._v1_6_512_lift_field_encoding(field, _TABLE)
    got = {(e["pattern"], e["mnem"]) for e in (field.get("encoding") or [])}
    assert n >= 3, f"the lift returned {n}"
    assert ("000001", "AES_ECB") in got, got
    assert ("000100", "AES_CFB") in got, got
    assert any(e.get("extraction_strategy")
               == "field_encoding_table_hexrow_v1_6_592"
               for e in field["encoding"]), (
        "the rows came from another tier, so this one is still unreachable")


def test_the_guard_holds_through_the_real_function(runner):
    """LOAD-BEARING through the real entry point, not just the local probe."""
    field = {"name": "OFFSETS", "width": 6}
    runner._v1_6_512_lift_field_encoding(
        field, "| 0x10 | STATUS_REG | offset of the status register |\n")
    assert not [e for e in (field.get("encoding") or [])
                if e.get("extraction_strategy")
                == "field_encoding_table_hexrow_v1_6_592"]


def test_it_runs_after_tier_2_so_the_bare_binary_rows_win():
    assert (_SRC.index("_V1_6_512_ENCODING_TABLE_ROW_RE.finditer(window_text)")
            < _SRC.index("_V1_6_592_ENCODING_TABLE_HEXROW_RE.finditer(window_text)"))
