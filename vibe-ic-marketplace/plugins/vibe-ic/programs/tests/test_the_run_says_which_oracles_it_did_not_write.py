"""A delivered oracle, a generated one and an empty scaffold must not look alike.

R-0915-89(ii). `testbench_gen.authored_oracle_preserved` has refused to
regenerate over a delivered oracle since v1.15.45 — correctly — and records each
one it kept in the producer's IN-MEMORY `report`, which reached no file.

MEASURED on two real runs of the same design (subservient x gf180mcuD, lane
icsub2):

  r18 (b3_proj)  the testbench-author role's TEN delivered oracles were staged,
                 preserved, and EXECUTED — `l10_execution.json` recorded
                 `sim_executed: true` ten times. Nothing in the run said the
                 oracles had been delivered rather than written by the flow.
  r27 (c3_proj)  the flow wrote ONE real oracle (boot latency) and NINE
                 substance floors. Nothing in the run said that either.

So a reader of either run could not tell a delivered oracle from a generated one
from a scaffold that asserts only "no output remains X/Z after reset" — which is
precisely the distinction r27's 1-of-10 turned on, and the one R-0915-87(2) made
the Step-4 waiver gate refuse over. The gate now refuses; this makes the run
DISCLOSE, so the refusal can be read back to a cause.

DERIVED FROM THE FILES, NOT FROM A LEDGER. Each testbench already declares what
it is — the floor carries `ORACLE_NONE_MARKER`, the producer's own output
carries `ORACLE_GENERATED_MARKER`, and a file carrying NEITHER is authored. That
is the SAME three-way test `authored_oracle_preserved` makes, so the disclosure
and the never-regenerate rule cannot disagree about one file.

chip-AGNOSTIC: synthetic testbench directories in tmp_path.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import testbench_gen as T  # noqa: E402

AUTHORED = """\
// ---------------------------------------------------------------------------
// AUTHORED L10 CASE ORACLE — the testbench-author role.
// CASE      : {case}
// ORACLE    : {oracle}
// CITATION  : {citation}
// ---------------------------------------------------------------------------
module {case}; endmodule
"""


def _tb_dir(project: Path) -> Path:
    d = project / "phase2" / "stage1" / "sim" / "tb"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write(project: Path, case: str, kind: str, **kw) -> Path:
    d = _tb_dir(project)
    f = d / f"{case}.v"
    if kind == "floor":
        f.write_text(f"// {T.ORACLE_NONE_MARKER}\nmodule {case}; endmodule\n")
    elif kind == "generated":
        f.write_text(T.stamp_generated(f"module {case}; endmodule\n",
                                       kw.get("emitter", "_emit_case_x")))
    else:
        f.write_text(AUTHORED.format(
            case=case, oracle=kw.get("oracle", "vectors match"),
            citation=kw.get("citation",
                            "input/docs/L7_verification_plan.md §7.1.2")))
    return f


# ── the three sources are told apart ────────────────────────────────────────
def test_the_three_sources_are_told_apart(tmp_path):
    p = tmp_path / "proj"
    _write(p, "rv32i_40", "authored")
    _write(p, "reset_n_cycle_instruction", "generated",
           emitter="_emit_case_boot_latency_oracle")
    _write(p, "blinky_hex", "floor")
    prov = T.oracle_provenance(p)
    by = {c["case"]: c for c in prov["cases"]}
    assert by["rv32i_40"]["source"] == T.ORACLE_SOURCE_AUTHORED
    assert by["reset_n_cycle_instruction"]["source"] == T.ORACLE_SOURCE_GENERATED
    assert by["blinky_hex"]["source"] == T.ORACLE_SOURCE_FLOOR
    assert prov["counts"] == {T.ORACLE_SOURCE_AUTHORED: 1,
                              T.ORACLE_SOURCE_GENERATED: 1,
                              T.ORACLE_SOURCE_FLOOR: 1}


def test_r27s_shape_is_published_as_what_it_was(tmp_path):
    """r27: nine scaffolds and one generated oracle. The run said none of it."""
    p = tmp_path / "proj"
    for case in ("blinky_hex", "hello_hex", "rv32i_40", "zifencei",
                 "plugin_m_mul_div", "plugin_c_16_bit_compressed",
                 "plugin_zicsr_csr_access_timer_irq", "reset_assert_sram",
                 "i_rst_glitch_instruction_fetch_race"):
        _write(p, case, "floor")
    _write(p, "reset_n_cycle_instruction", "generated",
           emitter="_emit_case_boot_latency_oracle")
    prov = T.oracle_provenance(p)
    assert prov["counts"] == {T.ORACLE_SOURCE_FLOOR: 9,
                              T.ORACLE_SOURCE_GENERATED: 1}


def test_r18s_shape_is_published_as_delivered(tmp_path):
    """r18: ten delivered oracles, preserved and executed, and the run was
    silent about every one of them."""
    p = tmp_path / "proj"
    for case in ("blinky_hex", "hello_hex", "rv32i_40", "zifencei"):
        _write(p, case, "authored")
    prov = T.oracle_provenance(p)
    assert prov["counts"] == {T.ORACLE_SOURCE_AUTHORED: 4}
    assert prov["authored_uncited"] == []


# ── the citation is the FILE's own claim, read back ─────────────────────────
def test_the_citation_is_read_back_from_the_file(tmp_path):
    p = tmp_path / "proj"
    _write(p, "rv32i_40", "authored",
           citation="input/docs/L7_verification_plan.md §7.1.2 row RV32I",
           oracle="37 self-checking vectors covering 40 instructions")
    row = T.oracle_provenance(p)["cases"][0]
    assert row["citation"] == ("input/docs/L7_verification_plan.md §7.1.2 "
                               "row RV32I")
    assert row["oracle"].startswith("37 self-checking vectors")


def test_an_authored_oracle_with_no_citation_is_disclosed_not_counted(tmp_path):
    """MEASURED on r18: its `reset_n_cycle_instruction.v` is the boot-latency
    oracle with the GENERATED stamp stripped, so it reads as authored and cites
    no input line. An uncited oracle must be NAMED, never quietly counted as
    provenanced."""
    p = tmp_path / "proj"
    f = _tb_dir(p) / "reset_n_cycle_instruction.v"
    f.write_text("// Auto-generated CPU-core BOOT-LATENCY oracle TB\n"
                 "module reset_n_cycle_instruction; endmodule\n")
    prov = T.oracle_provenance(p)
    row = prov["cases"][0]
    assert row["source"] == T.ORACLE_SOURCE_AUTHORED
    assert row["citation"] is None and row["uncited"] is True
    assert prov["authored_uncited"] == ["reset_n_cycle_instruction"]


# ── the disclosure agrees with the never-regenerate rule ────────────────────
def test_the_disclosure_and_the_preserve_rule_agree(tmp_path):
    """They make the same three-way test, so they cannot disagree about a file.
    A file the disclosure calls AUTHORED is exactly a file
    `authored_oracle_preserved` refuses to overwrite, and vice versa."""
    p = tmp_path / "proj"
    _write(p, "authored_one", "authored")
    _write(p, "generated_one", "generated")
    _write(p, "floor_one", "floor")
    out = _tb_dir(p)
    for row in T.oracle_provenance(p)["cases"]:
        kept = T.authored_oracle_preserved(out, row["case"], None)
        if row["source"] == T.ORACLE_SOURCE_AUTHORED:
            assert kept is not None, row["case"]
        else:
            assert kept is None, row["case"]


# ── fail-soft, never fail-open ─────────────────────────────────────────────
def test_no_testbench_directory_publishes_an_empty_census(tmp_path):
    prov = T.oracle_provenance(tmp_path / "nothing")
    assert prov["cases"] == [] and prov["counts"] == {}
    assert prov["schema"] == "vibeic.l10_oracle_provenance.v1"


def test_an_unreadable_testbench_is_named_not_skipped(tmp_path):
    p = tmp_path / "proj"
    f = _write(p, "broken", "floor")
    f.write_bytes(b"\xff\xfe\x00\x01")
    row = T.oracle_provenance(p)["cases"][0]
    assert row["case"] == "broken"
    # binary garbage carries no marker, so it reads as authored-and-uncited —
    # disclosed either way, never dropped from the census.
    assert row["source"] in (T.ORACLE_SOURCE_AUTHORED, "UNREADABLE")


# ── and the run publishes it ────────────────────────────────────────────────
