"""#514 — an English indefinite article was extracted as amperes, while
a design that honestly had no electrical specs was told it did.

Both directions of the same defect, and the tests are written so that
neither can be fixed at the other's expense:

  * FABRICATION (Direction 1) — `TSTRB = 1. A normal content byte`
    yielded `{value: "1.", unit: "A"}`: the sentence-ending full stop
    was absorbed into the NUMBER, and the first word of the next
    sentence became the UNIT. Four one- and zero-ampere specifications
    were published for a design whose input contains no current value.

  * MISS (Direction 2) — `no_electrical_specs_in_input` was computed
    as `not e_specs`: a statement about the EXTRACTOR published as a
    statement about the INPUT, with nothing able to falsify it.

The tests below deliberately exercise SEVERAL unit letters, not `A`.
A fix that lists `A` as an exception has not understood the defect:
`V`, `s`, `x` and `%` sit in the same alternation and the next
document will find a different one.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pytest

_PROG = Path(__file__).resolve().parents[1]
if str(_PROG) not in sys.path:
    sys.path.insert(0, str(_PROG))

import phase1_doc_one_shot_runner as R          # noqa: E402
from _electrical_mention import (               # noqa: E402
    has_electrical_mention,
    scan_electrical_mentions,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402


# ── Direction 1: a sentence boundary is not part of a number ─────────

# Every entry is `<param> = <n>.<space><Word starting with a unit
# letter>`. The letter that opens the next sentence is a member of the
# unit alternation in each case, so a pattern that reads across the
# sentence boundary mints a measurement from prose.
@pytest.mark.parametrize("line,stolen_unit", [
    ("- TSTRB = 1. A normal content byte that carries data", "A"),
    ("- TKEEP = 0. Verify that the lane is dropped", "V"),
    ("- MODE = 2. Selects the alternate mapping", "s"),
    ("- FIELD = 3. xor of the preceding bytes", "x"),
    ("- LEVEL = 7. Ω is unused in this mode", "Ω"),
])
def test_sentence_boundary_never_supplies_a_unit(line, stolen_unit):
    m = R._RE_BULLET_KV_SPEC.match(line)
    assert m is not None, "the assignment itself should still parse"
    assert m.group("unit") != stolen_unit
    assert not m.group("unit"), (
        f"a word opening the NEXT sentence was read as the unit "
        f"{m.group('unit')!r}")


@pytest.mark.parametrize("line", [
    "- TSTRB = 1. A normal content byte that carries data",
    "- COUNT = 42, and the remainder is discarded",
    "- YEAR = 2002. The standard superseded the earlier revision",
])
def test_number_begins_and_ends_with_a_digit(line):
    m = R._RE_BULLET_KV_SPEC.match(line)
    assert m is not None
    value = m.group("value").strip()
    assert value[-1].isdigit(), (
        f"trailing punctuation was absorbed into the number: {value!r}")


@pytest.mark.parametrize("line,unit", [
    ("- Supply voltage: 3.3 V nominal (I/O rail).", "V"),
    ("- Termination: 100 ohm differential pair", "ohm"),
    ("- Settling time: 200 ns after the strobe", "ns"),
    ("- Sample rate = 5 MS/s in burst mode", "MS/s"),
    ("- Quiescent draw: 26 mA typical", "mA"),
])
def test_a_real_unit_followed_by_qualifying_prose_still_extracts(line, unit):
    """The trailing-prose tolerance is not what was broken and must
    survive: a genuine measurement is routinely followed by a
    qualifier ("nominal", "typical", "differential pair")."""
    m = R._RE_BULLET_KV_SPEC.match(line)
    assert m is not None, "a real measurement must still be captured"
    assert m.group("unit") == unit


@pytest.mark.parametrize("line", [
    "- Level = 1Ampere",             # unit runs into a longer word
    "- JESDV version (0 = 204A, 1 = 204B, 2 = 204C).",   # enumeration
    "- Ratio = 3:1 in the divided domain",
])
def test_a_unit_may_not_abut_an_alphanumeric(line):
    m = R._RE_BULLET_KV_SPEC.match(line)
    if m is None:
        return
    assert not m.group("unit"), (
        f"{m.group('unit')!r} is part of a longer token, not a unit")


def test_a_unitless_number_ending_a_clause_is_still_captured():
    """The tightening must not throw away real facts. A number that
    runs straight into a clause boundary is complete; the remainder is
    prose."""
    m = R._RE_BULLET_KV_SPEC.match(
        "- memsize=1024, sky130_fd_sc_hd, TT corner)")
    assert m is not None
    assert m.group("value").strip() == "1024"
    assert not m.group("unit")


def test_a_decimal_point_is_not_a_clause_boundary():
    """`2.5V` must not be truncated to `2` by treating the decimal
    point as a sentence end."""
    for line in ("- VPP=2.5V, VREFCA, VSS", "- k = 0..7)"):
        m = R._RE_BULLET_KV_SPEC.match(line)
        if m is not None:
            assert m.group("value").strip() not in ("2", "0"), (
                f"number truncated at an internal dot: {line!r}")


# ── Direction 1, at the emitter ──────────────────────────────────────

def _elec(text: str):
    seen: set = set()
    return [s for s, _ev in R._collect_electrical_specs_for_doc(
        "spec.txt", text, seen)]


def test_byte_qualifier_prose_mints_no_electrical_spec():
    doc = (
        "Each byte lane of TDATA is one of three BYTE TYPES:\n"
        "  - DATA byte    : TKEEP = 1, TSTRB = 1. A normal content byte\n"
        "  - POSITION byte: TKEEP = 1, TSTRB = 0. A byte that occupies\n"
        "  - NULL byte    : TKEEP = 0, TSTRB = 0. A byte that has no\n"
    )
    assert _elec(doc) == [], (
        "a byte-qualifier sentence is not an electrical specification")


def test_real_electrical_prose_still_mints_specs():
    """The opposing pressure. Tightening Direction 1 must not silence
    the extractor on documents that really do carry measurements."""
    doc = ("- Core supply: 1.8 V nominal\n"
           "- Quiescent current: 26 mA typical\n")
    specs = _elec(doc)
    got = {(s["name"], s["unit"]) for s in specs}
    assert ("Core supply", "V") in got
    assert ("Quiescent current", "mA") in got


# ── the same property, in the sibling symbol regex ───────────────────

def test_symbol_regex_number_does_not_absorb_a_sentence_end():
    m = R._ELECTRICAL_SPEC_RE.search("The rail is VDD 3. V is the symbol.")
    if m is not None:
        assert m.group(2)[-1].isdigit()


def test_symbol_regex_does_not_join_across_a_line_break():
    """A symbol ending one paragraph and an unrelated quantity opening
    the next are two facts, not one specification."""
    doc = ("...which is referenced to VDD\n"
           "\n"
           "3.3 V is the connector rail for the adjacent interface.\n")
    assert R._ELECTRICAL_SPEC_RE.search(doc) is None


def test_symbol_regex_still_reads_a_real_inline_spec():
    m = R._ELECTRICAL_SPEC_RE.search("Operating point: VDD = 1.8 V typical")
    assert m is not None
    assert (m.group(1), m.group(2), m.group(3)) == ("VDD", "1.8", "V")


# ── Direction 2: the scanner that has to tell the two apart ──────────

@pytest.mark.parametrize("text", [
    "RISC-V Instruction Set Manual, Volume I: User-Level ISA",
    "tools like sv2v can pre-process the source code",
    "the wrapper instantiates sha256.v from the core directory",
    "the current program counter is saved in mepc",
    "max. bandwidth is still likely to apply",
])
def test_prose_is_not_an_electrical_mention(text):
    assert not has_electrical_mention(text), (
        "a symbol or unit buried in a longer word is not a mention")


@pytest.mark.parametrize("text", [
    "All signals are referenced to the 3.3 V I/O rail",
    "The core operates from a 1.8V supply",
    "VDD must be stable before the reset is released",
    "The line is terminated with 78 Ω to ground",
    "Sink current 26 mA maximum",
    "| Parameter | Min. | Typ. | Max. | Unit |",
])
def test_real_electrical_content_is_a_mention(text):
    assert has_electrical_mention(text)


def test_scan_reports_line_numbers_for_citation():
    hits = scan_electrical_mentions("intro\nno numbers here\nVDD = 1.8 V\n")
    assert hits and hits[0][0] == 3


# ── Direction 2, at the emitter: the flag must mean what it says ─────

def _gen_l1(docs: dict) -> dict:
    proj = Path(tempfile.mkdtemp())
    d = proj / "input" / "docs"
    d.mkdir(parents=True)
    for name, body in docs.items():
        (d / name).write_text(body)
    R.gen_l1_datasheet(proj, dict(docs))
    return json.loads(
        (proj / "phase1" / "generated_docs" / "L1_DATASHEET.json").read_text())


def test_flag_is_true_only_when_the_input_really_has_none():
    l1 = _gen_l1({"spec.txt": (
        "A byte-stream interface.\n"
        "  - DATA byte : TKEEP = 1, TSTRB = 1. A normal content byte\n"
        "The current cycle is accepted when both handshakes are high.\n")})
    assert l1["electrical_specs"] == []
    assert l1["no_electrical_specs_in_input"] is True
    assert not l1.get("electrical_specs_unextracted_mentions")


def test_flag_is_false_and_the_miss_is_published_when_the_input_has_some():
    """The claim `no_electrical_specs_in_input` may not be produced by
    the extractor's own silence. When the input carries electrical
    quantities the extractor did not type, the document must say so
    and show its evidence — NOT assert the input was empty."""
    l1 = _gen_l1({"spec.txt": (
        "Signalling levels.\n"
        "The bus is terminated with 78 Ohms and driven from a rail\n"
        "whose nominal value is 3.3 V at the connector.\n")})
    assert l1["electrical_specs"] == []
    assert l1["no_electrical_specs_in_input"] is False
    missed = l1.get("electrical_specs_unextracted_mentions") or []
    assert missed, "the un-extracted mentions must be published"
    assert all(":" in m["evidence"] for m in missed), (
        "each missed mention must cite <file>:<line>")


# ── The gate: it must be able to falsify the claim ───────────────────

_GATE = _PROG / "l1_electrical_specs_typed_depth_check.py"


def _project(doc_text: str, l1: dict) -> Path:
    proj = Path(tempfile.mkdtemp())
    (proj / "input" / "docs").mkdir(parents=True)
    (proj / "input" / "docs" / "spec.txt").write_text(doc_text)
    (proj / "phase1" / "generated_docs").mkdir(parents=True)
    (proj / "phase1" / "generated_docs" / "L1_DATASHEET.json").write_text(
        json.dumps(l1))
    return proj


def _rc(proj: Path):
    r = _pr.run([sys.executable, str(_GATE), str(proj)],
                       capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def test_gate_passes_a_corroborated_absence():
    proj = _project(
        "A CPU core. See the ISA Manual, Volume II, for the encoding.\n"
        "The sv2v tool can pre-process the source.\n",
        {"electrical_specs": [], "no_electrical_specs_in_input": True})
    rc, out = _rc(proj)
    assert rc == 0, out
    assert "corroborated" in out


def test_gate_fails_a_false_absence_claim():
    proj = _project(
        "The bus is terminated with 78 Ohms.\n"
        "The rail is 3.3 V at the connector.\n",
        {"electrical_specs": [], "no_electrical_specs_in_input": True})
    rc, out = _rc(proj)
    assert rc == 1, out
    assert "false claim" in out


def test_gate_quotes_the_literal_it_matched():
    """The old FAIL said "16 electrical mention(s) (e.g. foo.txt:7)"
    and every one of them was the word "Volume". Printing the literal
    makes a false positive visible from the gate's own output."""
    proj = _project("The rail is 3.3 V at the connector.\n",
                    {"electrical_specs": []})
    rc, out = _rc(proj)
    assert rc == 1, out
    assert "3.3 V" in out
