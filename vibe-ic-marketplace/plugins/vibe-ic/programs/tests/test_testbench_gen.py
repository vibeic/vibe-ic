#!/usr/bin/env python3
"""Tests for testbench_gen.py — emits unit TBs from L10_TEST_CASES.

Wave 83 — coverage for previously untested wired program.

#209 — these fixtures used to pass with an EMPTY rtl/ tree, because the
generator emitted a `PASS_PLACEHOLDER` skeleton with the DUT commented out and
so never needed a DUT to exist. That is the defect the #209 sweep found 140
instances of. The generator now instantiates the DUT or emits nothing, so every
fixture that expects a TB supplies one. What these tests assert is otherwise
unchanged; `--top` is now REQUIRED to name a real module (or be resolvable), and
the schema case asserts a LIVE instantiation where it used to assert a commented
one.

Cases:
  1. POSITIVE_PASS — L10 with two cases → two .v TBs in sim/tb/.
  2. POSITIVE_PASS_ALT_KEY — `cases` key fallback works (when `test_cases`
                              is absent).
  3. SKIP_NO_L10 — L10 missing → SKIP exit 0.
  4. POSITIVE_FAIL_BAD_JSON — malformed L10 → exit 1.
  5. EDGE_NON_DICT_ENTRIES — non-dict entries silently skipped.
  6. EDGE_OUTPUT_SCHEMA — emitted .v contains stimulus / expected comments,
                           a `module <name>` declaration, and a LIVE DUT
                           instantiation.
  7. SKIP_NO_RTL (#209) — L10 present but no DUT → nothing emitted, reason
                           printed, exit 0. Never a placeholder.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / \
    "testbench_gen.py"

# Generic synthetic DUT — chip-AGNOSTIC, no chip/vendor/SKU literal.
DUT_MODULE = "test_chip_top"
DUT_RTL = """\
module test_chip_top (
    input        clk,
    input        reset_n,
    input  [7:0] data_in,
    output reg [7:0] data_out
);
  always @(posedge clk or negedge reset_n)
    if (!reset_n) data_out <= 8'h00;
    else          data_out <= data_in;
endmodule
"""


def _run(args: list, timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG)] + args,
        capture_output=True, text=True, timeout=timeout,
    )


def _write_l10(project: Path, body: dict | str) -> None:
    gd = project / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    target = gd / "L10_TEST_CASES.json"
    if isinstance(body, str):
        target.write_text(body)
    else:
        target.write_text(json.dumps(body, indent=2))


def _write_rtl(project: Path, rtl: str = DUT_RTL) -> None:
    rtl_dir = project / "phase2" / "stage1" / "rtl"
    rtl_dir.mkdir(parents=True, exist_ok=True)
    (rtl_dir / "dut.v").write_text(rtl)


def test_positive_pass_two_cases(tmp_path):
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    _write_l10(project, {
        "test_cases": [
            {"name": "tb_get_id", "opcode_hex": "0x01",
             "expected": "byte0=0xA5", "kind": "happy_path",
             "polarity": "positive",
             "stimulus": "issue GET_ID frame"},
            {"name": "tb_bad_crc", "opcode_hex": "0x02",
             "expected": "no response", "kind": "negative",
             "polarity": "negative",
             "stimulus": "issue frame with bad CRC"},
        ]
    })
    _write_rtl(project)
    cp = _run([str(project), "--top", DUT_MODULE])
    assert cp.returncode == 0, cp.stderr
    assert "[PASS] testbench_gen" in cp.stdout
    assert "2 unit TB" in cp.stdout
    tbs = list((project / "phase2" / "stage1" / "sim" / "tb").glob("*.v"))
    assert len(tbs) == 2
    names = sorted(t.name for t in tbs)
    assert names == ["tb_bad_crc.v", "tb_get_id.v"]


def test_positive_pass_alt_cases_key(tmp_path):
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    _write_l10(project, {
        "cases": [
            {"name": "tb_alt", "opcode_hex": "0x10"},
        ]
    })
    _write_rtl(project)
    cp = _run([str(project), "--top", DUT_MODULE])
    assert cp.returncode == 0
    assert "1 unit TB" in cp.stdout
    assert (project / "phase2" / "stage1" / "sim" / "tb" / "tb_alt.v").is_file()


def test_skip_no_l10(tmp_path):
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    cp = _run([str(project)])
    assert cp.returncode == 0
    assert "[SKIP] testbench_gen" in cp.stdout


def test_positive_fail_bad_json(tmp_path):
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    _write_l10(project, "{not valid")
    cp = _run([str(project)])
    assert cp.returncode == 1
    assert "[FAIL]" in cp.stdout


def test_edge_non_dict_entries_skipped(tmp_path):
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    _write_l10(project, {
        "test_cases": [
            "string-not-a-case",
            42,
            {"name": "tb_only_dict", "opcode_hex": "0xAA"},
        ]
    })
    _write_rtl(project)
    cp = _run([str(project), "--top", DUT_MODULE])
    assert cp.returncode == 0
    assert "1 unit TB" in cp.stdout
    files = list((project / "phase2" / "stage1" / "sim" / "tb").glob("*.v"))
    assert [f.name for f in files] == ["tb_only_dict.v"]


def test_edge_output_schema(tmp_path):
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    _write_l10(project, {
        "test_cases": [
            {"name": "tb_schema_check", "opcode_hex": "0x55",
             "expected": "byte0=0xZZ", "kind": "happy_path",
             "stimulus": "stimulate and observe"},
        ]
    })
    _write_rtl(project)
    cp = _run([str(project), "--top", DUT_MODULE])
    assert cp.returncode == 0
    text = (project / "phase2" / "stage1" / "sim" / "tb" / "tb_schema_check.v").read_text()
    assert "module tb_schema_check" in text
    assert "stimulate and observe" in text
    assert "byte0=0xZZ" in text
    # #209 — a LIVE instantiation, not the commented-out one this used to accept.
    assert f"{DUT_MODULE} u_dut (" in text
    assert f"// {DUT_MODULE} u_dut" not in text
    assert "PASS_PLACEHOLDER" not in text


def test_skip_no_rtl_emits_nothing_and_says_why(tmp_path):
    """#209 — L10 present but no RTL to instantiate. The generator must emit
    NOTHING and print the reason, rather than the placeholder it used to write.
    Exit 0: a project that has not reached RTL yet is not a failure, but its
    silence must not be mistaken for coverage."""
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    _write_l10(project, {"test_cases": [{"name": "tb_x", "opcode_hex": "0x01"}]})
    cp = _run([str(project), "--top", DUT_MODULE])
    assert cp.returncode == 0
    assert "[SKIP] testbench_gen: no TB emitted" in cp.stdout
    assert "refused to emit" in cp.stdout
    tb_dir = project / "phase2" / "stage1" / "sim" / "tb"
    assert not tb_dir.exists() or list(tb_dir.glob("*.v")) == []
