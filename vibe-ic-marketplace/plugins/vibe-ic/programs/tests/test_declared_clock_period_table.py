"""The design DECLARES its clock period in a PDK-keyed table, and the flow
signed off against the runner's 20 ns default instead.

THE DEFECT, MEASURED (spm x gf180mcuD, v1.11.3, host 8HD-6, 2026-08-20)
======================================================================
`benchmark-data/ic/spm/input/docs/L9_constraints_floorplan.md` states the clock
contract the portable way — a placeholder plus a table keyed by std-cell library:

    create_clock [get_ports clk]  -name core_clock  -period <PERIOD>

    | Std-cell library    | `<PERIOD>` (ns) | frequency  |
    |---|---|---|
    | `sky130_fd_sc_hd`   | 10 | 100 MHz   |
    | `sky130_fd_sc_hs`   |  8 | 125 MHz   |
    | `gf180mcu_*`        | 24 | ~41.7 MHz |

`_resolve_clock_spec` looked for a NUMBER ADJACENT TO a `-period` token. The
neighbour here is the literal string `<PERIOD>`; the real numbers are four lines
away in a column the resolver never read — it was not even passed the library
name. Every rung of the ladder missed, and resolution reached the last-resort
default. A full run with all nine L-docs staged emitted:

    $ grep create_clock phase3/stage3/pnr/constraint.sdc
    create_clock -name clk -period 20.0 [get_ports clk]

20 ns against a declared 24 ns is a silent 20 % OVER-constraint, and every setup
verdict the run produced was a verdict about a clock the design never asked for.

WHY THIS IS NOT A RELAXATION
============================
Applying the period the design DECLARES for the library being built is using the
stated constraint. Deleting a constraint so a check stops complaining is the
other thing. The direction is disclosed in the artefact (`VIBEIC_DECLARED_PERIOD`
carries the matched key and the doc file:line), contradictory rows are REFUSED
rather than resolved by list order, and a library the table does not cover falls
through to the pre-existing ladder untouched.

RED / GREEN
===========
Against the base revision (origin/main 69ce9260d) every test here that names
`declared_clock_period` fails at import (no such module) and
`test_resolver_reads_the_declared_table` fails on the value: the resolver there
returns 20.0 for a project whose L9 declares 24. The two negative controls
(`declines_...`, `refuses_contradictory_rows`) assert behaviour that does not
exist there at all.
"""

import importlib
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

dcp = importlib.import_module("declared_clock_period")


# The document shape under test. Written here rather than read from
# benchmark-data so the test states its own premise and cannot silently start
# passing (or failing) because a benchmark doc was edited.
L9 = """# L9 constraints

### 9.1.1 clock definition

```sdc
set_units -time ns
create_clock [get_ports clk]  -name core_clock  -period <PERIOD>
```

### 9.1.2 the `<PERIOD>` for each PDK / library

| Std-cell library | `<PERIOD>` (ns) | frequency |
|---|---|---|
| `sky130_fd_sc_hd` | 10 | 100 MHz |
| `sky130_fd_sc_hs` | 8 | 125 MHz |
| `gf180mcu_*` | 24 | ~41.7 MHz |

### 9.1.3 I/O delay
- some prose that mentions a period but keys nothing
"""


def _docs(tmp_path, text=L9, name="L9_constraints_floorplan.md"):
    d = tmp_path / "input" / "docs"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(text)
    return d


# ── the table parser ─────────────────────────────────────────────────────────

def test_parses_every_row_of_the_keyed_table(tmp_path):
    rows = dcp.parse_period_tables(L9, source="L9")
    assert len(rows) == 3, rows
    assert {r["key"] for r in rows} == {
        "sky130_fd_sc_hd", "sky130_fd_sc_hs", "gf180mcu_*"}
    assert {r["period_ns"] for r in rows} == {10.0, 8.0, 24.0}


def test_the_glob_in_a_family_key_survives_markdown_cleaning():
    """`gf180mcu_*` must not be cleaned to `gf180mcu`.

    A bare `.strip("*")` for markdown emphasis eats the trailing glob and turns
    a family pattern into a literal that matches no library this flow ever
    resolves. Measured: that exact bug made the first cut of the parser find 6
    rows and match none of them.
    """
    assert dcp._clean_key("`gf180mcu_*`") == "gf180mcu_*"
    assert dcp._clean_key("**sky130_fd_sc_hd**") == "sky130_fd_sc_hd"
    assert dcp._clean_key("*x*") == "x"


def test_a_table_that_keys_no_library_is_ignored():
    txt = ("| step | period (ns) |\n|---|---|\n| place | 3 |\n")
    assert dcp.parse_period_tables(txt) == []


def test_a_table_that_states_no_period_is_ignored():
    txt = ("| Std-cell library | site width |\n|---|---|\n| a_lib | 0.46 |\n")
    assert dcp.parse_period_tables(txt) == []


def test_a_non_ns_unit_column_is_scaled_to_ns():
    txt = ("| Std-cell library | period (ps) |\n|---|---|\n| a_lib | 500 |\n")
    rows = dcp.parse_period_tables(txt)
    assert rows and rows[0]["period_ns"] == pytest.approx(0.5)


# ── matching a row to the library this run builds against ────────────────────

@pytest.mark.parametrize("lib,pdk,expect,key", [
    ("gf180mcu_fd_sc_mcu7t5v0", "gf180mcuD", 24.0, "gf180mcu_*"),
    ("sky130_fd_sc_hd", "sky130A", 10.0, "sky130_fd_sc_hd"),
    ("sky130_fd_sc_hs", "sky130A", 8.0, "sky130_fd_sc_hs"),
])
def test_resolves_the_row_for_this_run_s_library(tmp_path, lib, pdk, expect, key):
    rep = dcp.declared_period_ns(dcp.docs_in(_docs(tmp_path)), [lib, pdk])
    assert rep["period_ns"] == expect
    assert rep["matched_key"] == key
    # provenance travels with the number
    assert rep["source"].endswith("L9_constraints_floorplan.md")
    assert rep["line"] and str(expect).rstrip("0").rstrip(".") in rep["note"]


def test_a_family_glob_also_matches_a_bare_pdk_name(tmp_path):
    """`gf180mcu_*` must resolve for a caller that only knows the PDK name.

    The table is keyed by std-cell library; a caller may hold only `gf180mcuD`,
    which has no `_` before the family suffix.
    """
    rep = dcp.declared_period_ns(dcp.docs_in(_docs(tmp_path)), ["gf180mcuD"])
    assert rep["period_ns"] == 24.0


def test_declines_for_a_library_the_table_does_not_cover(tmp_path):
    """NEGATIVE CONTROL — silence must stay silence.

    A library the design keyed nothing for must produce NO period, so the
    caller falls through to the pre-existing ladder. Inventing one from a
    neighbouring row is the failure mode this asserts against.
    """
    rep = dcp.declared_period_ns(dcp.docs_in(_docs(tmp_path)),
                                 ["sg13g2_stdcell", "ihp-sg13g2"])
    assert rep["period_ns"] is None
    assert not rep["ambiguous"]
    # and it says which keys it DID see, so the miss is diagnosable
    assert "gf180mcu_*" in rep["note"]


def test_refuses_contradictory_rows(tmp_path):
    """NEGATIVE CONTROL — two matching rows with different periods is a REFUSAL.

    Picking one by list order is how a run silently signs off against a period
    the design never singled out.
    """
    txt = L9 + ("\n| Std-cell library | period (ns) |\n|---|---|\n"
                "| `gf180mcu_fd_sc_mcu7t5v0` | 30 |\n")
    rep = dcp.declared_period_ns(dcp.docs_in(_docs(tmp_path, txt)),
                                 ["gf180mcu_fd_sc_mcu7t5v0", "gf180mcuD"])
    assert rep["period_ns"] is None
    assert rep["ambiguous"] is True
    assert "24" in rep["note"] and "30" in rep["note"]


def test_no_docs_at_all_is_a_clean_miss(tmp_path):
    rep = dcp.declared_period_ns(dcp.docs_in(tmp_path / "input" / "docs"), ["x"])
    assert rep["period_ns"] is None and rep["rows_seen"] == 0


# ── the library name the caller passes comes from the liberty it resolved ────

@pytest.mark.parametrize("path,expect", [
    ("/foss/pdks/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu7t5v0/lib/"
     "gf180mcu_fd_sc_mcu7t5v0__ss_125C_4v50.lib", "gf180mcu_fd_sc_mcu7t5v0"),
    ("/foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd/lib/"
     "sky130_fd_sc_hd__tt_025C_1v80.lib", "sky130_fd_sc_hd"),
    # no `__` in the file name — fall back to the libs.ref/<library>/ component
    ("/foss/pdks/ihp-sg13g2/libs.ref/sg13g2_stdcell/lib/"
     "sg13g2_stdcell_typ_1p20V_25C.lib", "sg13g2_stdcell"),
    ("", ""),
])
def test_library_name_from_liberty(path, expect):
    assert dcp.library_name_from_liberty(path) == expect


# ── the runner actually uses it ──────────────────────────────────────────────

runner = importlib.import_module("phase3_one_shot_runner")

GF_LIB = ("/foss/pdks/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu7t5v0/lib/"
          "gf180mcu_fd_sc_mcu7t5v0__ss_125C_4v50.lib")
SKY_LIB = ("/foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd/lib/"
           "sky130_fd_sc_hd__tt_025C_1v80.lib")


def test_resolver_reads_the_declared_table(tmp_path):
    """THE DEFECT. Base revision returns 20.0 here; the design declares 24."""
    _docs(tmp_path)
    period, port = runner._resolve_clock_spec(
        tmp_path, top="spm", pdk_name="gf180mcuD", liberty_path=GF_LIB)
    assert period == 24.0, (
        f"resolved {period} ns for a design whose L9 declares 24 ns for this "
        "library")
    assert port == "clk"


def test_the_same_docs_give_a_different_library_its_own_row(tmp_path):
    _docs(tmp_path)
    period, _ = runner._resolve_clock_spec(
        tmp_path, top="spm", pdk_name="sky130A", liberty_path=SKY_LIB)
    assert period == 10.0


def test_without_pdk_information_the_legacy_ladder_is_unchanged(tmp_path):
    """REGRESSION GUARD — a caller that passes no library must behave exactly
    as it did before this change, so no existing flow moves."""
    _docs(tmp_path)
    period, _ = runner._resolve_clock_spec(tmp_path, top="spm")
    assert period == 20.0


def test_a_staged_sdc_still_outranks_the_declared_table(tmp_path):
    """A real staged SDC is upstream-verified ground truth and must still win.

    If the table could override a design-staged `create_clock`, this change
    would be overriding the design, not reading it.
    """
    _docs(tmp_path)
    c = tmp_path / "input" / "constraints"
    c.mkdir(parents=True, exist_ok=True)
    (c / "spm.sdc").write_text("create_clock -name clk -period 12.5 "
                               "[get_ports clk]\n")
    period, _ = runner._resolve_clock_spec(
        tmp_path, top="spm", pdk_name="gf180mcuD", liberty_path=GF_LIB)
    assert period == 12.5


def test_the_sdc_discloses_that_the_period_is_the_design_s_own(tmp_path):
    _docs(tmp_path)
    note = runner._declared_period_disclosure(tmp_path, "gf180mcuD", GF_LIB)
    assert "VIBEIC_DECLARED_PERIOD" in note
    assert "gf180mcu_*" in note                      # the matched key
    assert "L9_constraints_floorplan.md" in note     # the source doc
    assert note.endswith("\n") and note.lstrip().startswith("#")
    for line in note.splitlines():
        assert line.startswith("#"), f"not an SDC comment: {line!r}"


def test_the_disclosure_reports_a_refusal_too(tmp_path):
    txt = L9 + ("\n| Std-cell library | period (ns) |\n|---|---|\n"
                "| `gf180mcu_fd_sc_mcu7t5v0` | 30 |\n")
    _docs(tmp_path, txt)
    note = runner._declared_period_disclosure(tmp_path, "gf180mcuD", GF_LIB)
    assert "REFUSED" in note
    for line in note.splitlines():
        assert line.startswith("#")


def test_no_chip_pdk_or_vendor_literal_in_the_program():
    """The program must be chip/PDK-AGNOSTIC: every name it matches on comes
    from the caller or from the design's own document."""
    src = (PROGRAMS / "declared_clock_period.py").read_text()
    # Docstrings quote a real table as the worked example; strip them before
    # asserting, the same way the repo's own source guard treats prose.
    import ast
    tree = ast.parse(src)
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)):
            d = ast.get_docstring(node, clean=False)
            if d:
                docstrings.add(d)
    code = src
    for d in docstrings:
        code = code.replace(d, "")
    lowered = code.lower()
    for lit in ("sky130", "gf180", "sg13g2", "nangate", "asap7", "spm"):
        assert lit not in lowered, f"chip/PDK literal {lit!r} in executable code"


# ── the SAME document declares the I/O delay as a DERIVATION, not a number ───
#
# L9 9.1.3 states "I/O delay: 20 % of the clock period (e.g. 10 ns -> 2 ns)".
# The auto-SDC emitted the literal `2` at EVERY period — a number that
# satisfies the declaration at exactly one period and at no other. At the
# 24 ns this design declares for its own library the declared delay is 4.8 ns,
# so the fixed 2 UNDER-constrained every I/O path by 2.8 ns. A declared
# RELATIONSHIP read as if it were a declared VALUE.

L9_IO = L9.replace(
    "- some prose that mentions a period but keys nothing",
    "- `set_input_delay` / `set_output_delay`: use **20% of the clock period** "
    "as the default (e.g. `sky130_fd_sc_hd` 10 ns -> 2 ns I/O delay)")


def test_reads_the_declared_io_delay_fraction(tmp_path):
    rep = dcp.declared_io_delay_fraction(dcp.docs_in(_docs(tmp_path, L9_IO)))
    assert rep["fraction"] == pytest.approx(0.2)
    assert rep["percent"] == 20.0
    assert rep["source"].endswith("L9_constraints_floorplan.md")


def test_no_declared_fraction_is_a_clean_miss(tmp_path):
    """NEGATIVE CONTROL — the doc without the 9.1.3 statement must yield
    nothing, so the caller keeps the historical literal."""
    rep = dcp.declared_io_delay_fraction(dcp.docs_in(_docs(tmp_path, L9)))
    assert rep["fraction"] is None and not rep["ambiguous"]


def test_two_different_declared_fractions_are_refused(tmp_path):
    txt = L9_IO + "\n\n- input delay: 30% of the clock period\n"
    rep = dcp.declared_io_delay_fraction(dcp.docs_in(_docs(tmp_path, txt)))
    assert rep["fraction"] is None and rep["ambiguous"] is True


# ── vibe-ic#712: a DENIED derivation is not a declaration ────────────────────
#
# The statement this reader is built for carries an I/O token, a period token
# and one percentage inside one window. So does a sentence that RETRACTS it,
# and before the polarity consult the two were indistinguishable — the retracted
# 20 % landed in the emitted SDC as a mandate, citing the design's own document
# as the authority. That is #706 and #711 in a third field.

L9_IO_DENIED = L9.replace(
    "- some prose that mentions a period but keys nothing",
    "- `set_input_delay` / `set_output_delay`: the I/O delay is NOT 20% of the "
    "clock period for this revision; the interface is source-synchronous")


def test_a_denied_io_delay_derivation_is_not_declared(tmp_path):
    rep = dcp.declared_io_delay_fraction(dcp.docs_in(_docs(tmp_path,
                                                           L9_IO_DENIED)))
    assert rep["fraction"] is None and not rep["ambiguous"]


def test_a_denied_derivation_is_REFUSED_not_merely_missing(tmp_path):
    """"No statement was made" and "the statement was retracted" are opposite
    findings. A silent drop would give a caller that keeps its historical
    literal no way to tell which one happened."""
    denied = dcp.declared_io_delay_fraction(
        dcp.docs_in(_docs(tmp_path / "a", L9_IO_DENIED)))
    absent = dcp.declared_io_delay_fraction(
        dcp.docs_in(_docs(tmp_path / "b", L9)))
    # One entry per I/O token the statement carries (`set_input_delay`,
    # `set_output_delay`, the `9.1.3 I/O delay` heading and the bullet's own
    # `I/O delay`), each citing the line a reader can go and look at.
    assert denied["denied"] and absent["denied"] == []
    assert all("L9_constraints_floorplan.md:" in e for e in denied["denied"])
    assert "REFUSED" in str(denied["note"])
    assert "REFUSED" not in str(absent["note"])
    assert denied["note"] != absent["note"]


def test_a_denial_does_not_suppress_a_statement_in_another_sentence(tmp_path):
    """NEGATIVE CONTROL. The reach is `_prose_polarity.sentence_scope`, so a
    denial in a NEIGHBOURING statement must not retract this one — the silent
    direction, where the reader publishes less than it read and nothing
    reddens."""
    txt = L9_IO + "\n\n- The clock tree is not built by this flow.\n"
    rep = dcp.declared_io_delay_fraction(dcp.docs_in(_docs(tmp_path, txt)))
    assert rep["fraction"] == pytest.approx(0.2)


def test_a_worked_example_number_is_not_mistaken_for_the_fraction(tmp_path):
    """The declaration's own example contains `10 ns -> 2 ns`. Only the
    PERCENTAGE may be read; a bare ns figure in the same sentence must not
    become the fraction."""
    rep = dcp.declared_io_delay_fraction(dcp.docs_in(_docs(tmp_path, L9_IO)))
    assert rep["fraction"] == pytest.approx(0.2)


def test_the_sdc_computes_the_io_delay_from_the_resolved_period(tmp_path):
    _docs(tmp_path, L9_IO)
    io_ns, note = runner._declared_io_delay_ns(tmp_path, 24.0)
    assert io_ns == pytest.approx(4.8)
    assert "VIBEIC_DECLARED_IO_DELAY" in note
    for line in note.splitlines():
        assert line.startswith("#")


def test_the_emitted_sdc_carries_both_declared_constraints(tmp_path):
    _docs(tmp_path, L9_IO)
    out = runner._build_auto_silicon_sdc(
        tmp_path, top="spm", liberty_path=GF_LIB, pdk_name="gf180mcuD")
    text = out[0] if isinstance(out, tuple) else out
    assert "create_clock -name clk -period 24.0" in text
    assert "set_input_delay  4.8 -clock clk" in text
    assert "set_output_delay 4.8 -clock clk" in text
    assert "VIBEIC_DECLARED_PERIOD" in text and "VIBEIC_DECLARED_IO_DELAY" in text


def test_a_design_that_declares_nothing_gets_the_historical_literal(tmp_path):
    """REGRESSION GUARD — the fleet must not move.

    A project with no declaration must emit the same `2` it always has, and no
    disclosure line. This is what keeps every design that predates this change
    byte-identical.
    """
    out = runner._build_auto_silicon_sdc(tmp_path, top="spm")
    text = out[0] if isinstance(out, tuple) else out
    assert "set_input_delay  2 -clock clk" in text
    assert "set_output_delay 2 -clock clk" in text
    assert "VIBEIC_DECLARED_IO_DELAY" not in text
    assert "VIBEIC_DECLARED_PERIOD" not in text
    assert "-period 20.0" in text


def test_the_io_delay_does_not_fire_without_a_period(tmp_path):
    _docs(tmp_path, L9_IO)
    io_ns, note = runner._declared_io_delay_ns(tmp_path, 0)
    assert io_ns is None and note == ""


# ── vibe-ic#712 — the scan must not read a COMMENTED-OUT statement ──────────
_IO_STMT = ("- `set_input_delay` / `set_output_delay`: use **20% of the clock "
            "period** as the default")


def test_a_commented_out_io_delay_statement_is_not_a_declaration(tmp_path):
    """`<!-- ... -->` is the comment form these documents have.

    The commented paragraph carries an I/O token, a period token and exactly
    one percentage inside one window, so before the strip it read as a live
    20 % mandate — and that value lands in the emitted SDC. This is #706/#711
    in the document lane.
    """
    txt = L9.replace("- some prose that mentions a period but keys nothing",
                     "<!--\n" + _IO_STMT + "\n-->")
    rep = dcp.declared_io_delay_fraction(dcp.docs_in(_docs(tmp_path, txt)))
    assert rep["fraction"] is None, rep
    assert not rep["denied"], (
        "a COMMENTED-OUT statement is not a DENIED statement — it was never "
        "made, so it must not be counted as a retraction either")


def test_the_strip_does_not_eat_a_line_that_merely_contains_a_url(tmp_path):
    """THE REGRESSION GUARD FOR THE STRIPPER CHOICE.

    `_design_module_set.strip_comments` — the HDL stripper this repo uses
    elsewhere — removes `//[^\\n]*`. Applied to a DESIGN DOCUMENT it would take
    everything after the `//` of a URL, so a real declaration sharing that line
    would be silently dropped. Under-reading a declaration is the same defect
    as over-reading one, pointed the other way. This pins that the document
    lane uses `<!-- -->` and NOT the HDL stripper.
    """
    txt = L9.replace(
        "- some prose that mentions a period but keys nothing",
        "- see https://spec.example/timing#io — " + _IO_STMT)
    rep = dcp.declared_io_delay_fraction(dcp.docs_in(_docs(tmp_path, txt)))
    assert rep["fraction"] == pytest.approx(0.2), (
        "the declaration after a URL was lost — the stripper is eating `//`")


def test_stripping_preserves_line_numbers_and_citations(tmp_path):
    """Offsets are replaced one-for-one, so the reported line still points at
    the statement. A stripper that DELETED the comment would move every line
    after it and the citation would name the wrong one."""
    txt = L9.replace("- some prose that mentions a period but keys nothing",
                     "<!-- retired note\nspanning two lines -->\n" + _IO_STMT)
    rep = dcp.declared_io_delay_fraction(dcp.docs_in(_docs(tmp_path, txt)))
    assert rep["fraction"] == pytest.approx(0.2), rep
    # The citation is the line of the I/O TOKEN, which this document puts on the
    # `### 9.1.3 I/O delay` heading — the file's own comment records that the
    # heading is the match site and the bullet supplies the percentage. What
    # this test pins is that the line still points at a line carrying the token
    # in the UNSTRIPPED text: a stripper that DELETED the two comment lines
    # would shift every line after them and the citation would name the wrong
    # one.
    lines = txt.split("\n")
    cited = lines[rep["line"] - 1]
    assert "I/O delay" in cited, (
        f"line {rep['line']} is {cited!r} — the strip shifted the offsets")
