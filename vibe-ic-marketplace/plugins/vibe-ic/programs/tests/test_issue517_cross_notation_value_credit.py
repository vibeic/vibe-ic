#!/usr/bin/env python3
"""vibe-ic#517 — a hex quantity correctly transcoded into a different NOTATION
is still the same quantity, and must not be counted as a missing token by
``phase1_doc_input_completeness_check.py``.

Real campaign reproduction (ibex): the input parameter table writes
``0x1A110000``; Phase 1 renders the same value into L9's
``instantiation_template`` as ``32'h1A110000`` — the only literal form that
would actually compile in a Verilog instantiation. ``32'h1A110000`` does not
contain the substring ``0x1A110000``, so the flat substring search counted a
CORRECT transcoding as a loss and reported a 100%-captured document at 87.0%.
The gate is deliberately unwaivable (forbidden waiver prefix
``phase1_input_vs_generated_*``), so a false FAIL has no escape hatch and a
false PASS has no backstop — both directions are pinned here.

The fix compares VALUES, not spellings, under two discipline rules:

  (1) BASE-TAGGED ONLY — the L-doc literal must declare a base (``0x`` or a
      Verilog ``'h``/``'d``/``'b``/``'o``, any width, any ``_`` grouping). A
      BARE decimal integer is NOT eligible: JSON is full of incidental
      integers and crediting against them is the value-soup false-PASS shape.

  (2) MAGNITUDE FLOOR — only values of >= ``_VALUE_CREDIT_MIN_HEX_DIGITS``
      canonical hex digits (>= 0x100) are eligible. SHORT values (1-2 hex
      digits, 0x00-0xFF) still require an exact substring match, because that
      band saturates every design document and an equal value elsewhere is
      weak evidence of the same fact.

chip-AGNOSTIC: synthetic docs with invented signal names and generic numeric
notation; no chip, vendor, SKU or document literal anywhere.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parents[1] / \
    "phase1_doc_input_completeness_check.py"
REPORT = Path("reports/phase1/phase1_input_vs_generated_completeness.json")

# >= _MIN_TOKENS (10) all-caps design tokens so the doc is audited, never
# SKIP_LOW_TOKENS. All of them are captured verbatim in the L doc.
_DESIGN_TERMS = [
    "AUTHCTRL", "IDBUS", "CRCPOLY", "TXFIFO", "RXFIFO", "STATUSREG",
    "CMDREG", "WAKEPIN", "SLEEPCTL", "PARITYERR", "TIMEOUTCNT",
]


def _mk_project(tmp_path: Path, doc_text: str, l_doc_payload) -> Path:
    proj = tmp_path / "proj"
    (proj / "phase1" / "input_doc").mkdir(parents=True)
    (proj / "phase1" / "input_doc" / "integration.txt").write_text(doc_text)
    gd = proj / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L9_INTEGRATION_SPEC.json").write_text(
        json.dumps({"ic_name": "dut", "content": list(_DESIGN_TERMS),
                    **l_doc_payload}))
    return proj


def _run(proj: Path):
    r = subprocess.run([sys.executable, str(PROG), str(proj)],
                       capture_output=True, text=True)
    rep_path = proj / REPORT
    rep = json.loads(rep_path.read_text()) if rep_path.is_file() else None
    return r, rep


def _doc(extra: str) -> str:
    body = " ".join(f"Signal {t} is defined." for t in _DESIGN_TERMS)
    return "Integration guide.\n" + body + "\n" + extra


# ── direction 1: the correct transcoding must be CREDITED ───────────────────

@pytest.mark.parametrize("l_literal", [
    "32'h1A110000",     # sized Verilog hex — the ibex reproduction
    "'h1A110000",       # unsized Verilog hex
    "32'H1A110000",     # uppercase base tag
    "32'sh1A110000",    # signed Verilog hex
    "32'h1A11_0000",    # underscore-grouped digits
    "0x1a110000",       # same value, different case
    "0x01A110000",      # same value, leading zero
])
def test_same_value_other_notation_is_captured(tmp_path, l_literal):
    """The input writes `0x1A110000`; the L doc renders the SAME VALUE under a
    different base-tagged notation. That is a correct transcoding, not a loss."""
    proj = _mk_project(
        tmp_path,
        _doc("Parameter DebugBaseAddr defaults to 0x1A110000 at reset."),
        {"instantiation_template": f".DebugBaseAddr ( {l_literal} )"})
    r, rep = _run(proj)
    assert rep is not None
    assert rep["tokens_missing_everywhere_list"] == [], \
        f"{l_literal} did not credit 0x1A110000"
    assert rep["verdict"] == "PASS"
    assert r.returncode == 0
    assert "0x1A110000" in rep["notation_captured_tokens"]


def test_non_hex_base_tags_credit_the_same_value(tmp_path):
    """The rule is about NOTATION generally, not a list of hex spellings: a
    base-tagged decimal / octal / binary literal of the SAME value counts too.

    The literals are COMPUTED from the value rather than hand-written, so the
    test can never drift into asserting a different quantity (the first draft
    of this test hand-computed the decimal wrong and the gate correctly
    refused it — which is the behaviour `test_different_value_does_not_credit`
    pins deliberately)."""
    value = 0x1A110000
    for l_literal in (f"32'd{value:d}", f"32'o{value:o}", f"32'b{value:b}"):
        proj = _mk_project(
            tmp_path / l_literal.replace("'", "_"),
            _doc("Parameter DebugBaseAddr defaults to 0x1A110000 at reset."),
            {"reset_value": l_literal})
        _r, rep = _run(proj)
        assert rep is not None
        assert rep["tokens_missing_everywhere_list"] == [], \
            f"{l_literal} did not credit 0x1A110000"


# ── direction 2: NO-LEAK — a genuinely absent value must STAY missing ───────

def test_absent_value_still_missing(tmp_path):
    """NO-LEAK: a hex address that appears in NO notation anywhere in any L doc
    is still a missing design token. This is the #516 shape (register-table
    addresses dropped before L4) and it must keep FAILing."""
    proj = _mk_project(
        tmp_path,
        _doc("The counter register lives at 0x1A110000 and is decoded by the "
             "core."),
        {"instantiation_template": ".OtherAddr ( 32'hDEADBEEF )"})
    r, rep = _run(proj)
    assert rep is not None
    assert "0x1A110000" in rep["tokens_missing_everywhere_list"], \
        "a genuinely absent address was wrongly credited"
    assert rep["verdict"] == "FAIL"
    assert r.returncode == 1


def test_different_value_does_not_credit(tmp_path):
    """NO-LEAK: value equality is required. A NEIGHBOURING address that differs
    by one digit must not credit the token."""
    proj = _mk_project(
        tmp_path,
        _doc("Parameter DebugBaseAddr defaults to 0x1A110000 at reset."),
        {"instantiation_template": ".DebugBaseAddr ( 32'h1A110001 )"})
    _r, rep = _run(proj)
    assert rep is not None
    assert "0x1A110000" in rep["tokens_missing_everywhere_list"], \
        "an off-by-one value was wrongly credited"


def test_bare_decimal_does_not_credit(tmp_path):
    """NO-LEAK / anti-value-soup: an UNTAGGED decimal integer is not a numeric
    literal the flow deliberately emitted — it is any incidental JSON number
    (a count, a width, an index). It must NOT credit a hex token, even when the
    magnitudes are EXACTLY equal.

    The decimal is computed from the value so the equality is real: a
    hand-written constant that silently differs would make this test vacuous
    (it would pass for the wrong reason, since a different value is refused
    anyway) and it would then catch no loosening at all."""
    proj = _mk_project(
        tmp_path,
        _doc("Parameter DebugBaseAddr defaults to 0x1A110000 at reset."),
        {"unrelated_capacity_bytes": 0x1A110000})
    _r, rep = _run(proj)
    assert rep is not None
    assert "0x1A110000" in rep["tokens_missing_everywhere_list"], \
        "a bare decimal integer wrongly credited a hex token (value soup)"


# ── direction 3: the magnitude floor — short values stay strict ─────────────

def test_short_value_is_not_value_credited(tmp_path):
    """The 0x00-0xFF band is the small-integer band that saturates every design
    document, so an equal value elsewhere is weak evidence of the same fact.
    A 2-hex-digit token must NOT be credited by a same-valued literal; it still
    requires an exact substring match."""
    proj = _mk_project(
        tmp_path,
        _doc("The status field resets to 0x20 on power-up."),
        {"unrelated_field_width": "8'h20"})
    _r, rep = _run(proj)
    assert rep is not None
    assert "0x20" in rep["tokens_missing_everywhere_list"], \
        "a short (<3 canonical digit) value was wrongly value-credited"


def test_zero_value_is_not_value_credited(tmp_path):
    """Value 0 is the most collision-prone value there is — `'h0` / `0x00` /
    `32'h0` appear in unrelated roles all over a real L doc. `0x0000`
    canonicalises to a single digit and must stay below the floor."""
    proj = _mk_project(
        tmp_path,
        _doc("The address map places the first slave at 0x0000 in the window."),
        {"unrelated_range": "0x00 - 0x07"})
    _r, rep = _run(proj)
    assert rep is not None
    assert "0x0000" in rep["tokens_missing_everywhere_list"], \
        "value 0 was wrongly value-credited"


def test_three_digit_value_is_at_the_floor(tmp_path):
    """The floor is inclusive at 3 canonical hex digits: 0x324 IS eligible, so
    a same-valued base-tagged literal credits it. This pins the boundary from
    the permitted side, so a future off-by-one in the floor is caught."""
    proj = _mk_project(
        tmp_path,
        _doc("The counter register sits at offset 0x324 in the block."),
        {"offset_literal": "12'h324"})
    _r, rep = _run(proj)
    assert rep is not None
    assert rep["tokens_missing_everywhere_list"] == [], \
        "a 3-canonical-digit value was not credited at the floor"
    assert "0x324" in rep["notation_captured_tokens"]


# ── direction 4: verbatim capture is unchanged ─────────────────────────────

def test_verbatim_match_still_attributed_to_program(tmp_path):
    """A token present VERBATIM must still be credited by the substring path
    and reported as `program`, never re-labelled as a notation credit — the
    value pass runs only after the substring search has failed."""
    proj = _mk_project(
        tmp_path,
        _doc("Parameter DebugBaseAddr defaults to 0x1A110000 at reset."),
        {"base_addr": "0x1A110000"})
    _r, rep = _run(proj)
    assert rep is not None
    assert rep["tokens_missing_everywhere_list"] == []
    assert rep["notation_captured_tokens"] == [], \
        "a verbatim hit was wrongly attributed to the notation credit"


if __name__ == "__main__":
    sys.exit(subprocess.call([sys.executable, "-m", "pytest", "-q",
                              str(Path(__file__))]))
