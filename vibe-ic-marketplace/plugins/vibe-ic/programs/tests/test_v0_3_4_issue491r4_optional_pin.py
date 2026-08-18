"""v0.3.4 — #491 ROUND-4: row-CONTENT vocabulary axis. After round-3
fixed the header vocabulary, the REAL doc's table still failed the gate
in the OPPOSITE direction: a row whose NAME cell carries a parenthesised
annotation — ``(optional) `i_gpio``` — leaked the annotation into the
identifier (promoted as ``(optional)_`i_gpio```), and the row's
doc-declared OPTIONALITY (annotation + ``optional`` width cell) was not
modelled, so the gate hard-FAILed an RTL top that legitimately omits an
optional pin.

Three rounds, three axes, each one missed by an author-rewritten
fixture: shape (r2) → header vocabulary (r3) → row-content vocabulary
(r4). Per the round-4 reopen doctrine (and #501), the fixture below
embeds the REAL table's rows VERBATIM — every row of both tables,
byte-for-byte from the real input doc — not a same-shape paraphrase.

Pins:
  * name-cell sanitiser: ``(optional) `i_gpio``` → ``i_gpio`` +
    ``optional=True``; alias annotation ``(or `x`)`` stripped from the
    name; generic EN+CJK optionality vocabulary;
  * width cell that IS an optionality word marks the row optional
    (it is not a width);
  * END-TO-END on the real-table doc: runner → L9 carries
    ``optional: true`` → `l9_rtl_pin_consistency_check` PASSes (bare
    exit=0) against an RTL top WITHOUT the optional pin, with an
    advisory WARN naming it;
  * regression guard: a REQUIRED L9 pin missing from RTL still FAILs;
  * the group-header row (``**SRAM port group**`` / bidirectional)
    still never promotes a bogus pin.
"""
import json
import subprocess
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import phase1_doc_one_shot_runner as P1  # noqa: E402

# ── REAL table rows, embedded VERBATIM (all rows of both tables from
#    the real L3 external-interface doc; #491-r4 / #501 doctrine:
#    never paraphrase the discriminating line). ──────────────────────
_DOC = """# 外部介面

## 頂層訊號

| Port group | 寬度 | 方向 | 描述 |
|---|---|---|---|
| `i_clk` | 1-bit | input | 系統時脈;所有資料於上升沿同步 |
| `i_rst` | 1-bit | input | 同步 reset,**active-high**;assert 後一個 cycle SERV 內部歸零 |
| **SRAM port group** | (groupings see below) | bidirectional | 連接外部 SRAM(I-mem + D-mem + RF 共用) |
| `o_gpio` | ≥ 1-bit | output | GPIO 輸出;預設 1 pin,可作為 simple debug bit 或 UART tx |
| (optional) `i_gpio` | optional | input | GPIO 輸入(若 Plugin 採雙向 GPIO) |

### SRAM port group sub-ports(典型實作)

| Sub-port | 寬度 | 方向 | 描述 |
|---|---|---|---|
| `o_sram_addr` | ~10-bit(對應 `memsize = 1024 bytes`,8-bit 每位元組 → 10-bit address) | output | 位址 |
| `o_sram_data` (or `o_sram_wdata`) | 8-bit | output | 寫入資料(typical) |
| `i_sram_data` (or `i_sram_rdata`) | 8-bit | input | 讀取資料(typical) |
| `o_sram_we` | 1-bit | output | 寫入啟用 |
| `o_sram_cyc` | 1-bit | output | 匯流排 cycle 有效 |
"""

# RTL top WITHOUT the doc-optional `i_gpio` (the legal omission the
# round-4 reopen exercised). ORGANIC #610 — uses the CANONICAL spelling of
# each `name (or alt)` port (`o_sram_data` / `i_sram_data`), NOT the alternate
# spelling. The `(or ...)` annotation documents ONE port under an equivalent
# alias, so the corrected L9 carries a single canonical top-level port (not a
# duplicate); a realistic RTL declares that one port, never two redundant
# data ports. (Pre-#610 this fixture declared BOTH spellings to match the old
# alias double-promotion bug.)
_RTL = """module chip_top(
  input  wire i_clk,
  input  wire i_rst,
  output wire o_gpio,
  output wire [9:0] o_sram_addr,
  output wire [7:0] o_sram_data,
  input  wire [7:0] i_sram_data,
  output wire o_sram_we,
  output wire o_sram_cyc
);
  assign o_gpio = 1'b0;
  assign o_sram_addr = 10'h0;
  assign o_sram_data = 8'h0;
  assign o_sram_we = 1'b0;
  assign o_sram_cyc = 1'b0;
endmodule
"""


def test_sanitizer_strips_optional_annotation():
    name, optional, aliases = P1._v0_3_4_sanitize_pin_name_cell(
        "(optional) `i_gpio`")
    assert name == "i_gpio"
    assert optional is True
    assert aliases == []


def test_sanitizer_extracts_or_alias():
    name, optional, aliases = P1._v0_3_4_sanitize_pin_name_cell(
        "`o_sram_data` (or `o_sram_wdata`)")
    assert name == "o_sram_data"
    assert optional is False
    assert aliases == ["o_sram_wdata"]


def test_sanitizer_cjk_optionality():
    name, optional, _ = P1._v0_3_4_sanitize_pin_name_cell("(可選) `i_irq`")
    assert name == "i_irq" and optional is True


def test_walker_emits_clean_optional_pin_from_real_rows():
    recs = list(P1._v0_3_2_emit_pins_from_gfm_tables(_DOC))
    by_name = {r["name"]: r for r in recs}
    assert "i_gpio" in by_name, by_name.keys()
    assert by_name["i_gpio"].get("optional") is True
    # No annotation residue survives into any identifier.
    for n in by_name:
        assert "(" not in n and "`" not in n, n
    # required pins carry no optional flag
    assert not by_name["i_clk"].get("optional")
    assert not by_name["o_sram_we"].get("optional")


def test_group_header_row_promotes_no_bogus_pin(tmp_path):
    recs = list(P1._v0_3_2_emit_pins_from_gfm_tables(_DOC))
    names = {r["name"] for r in recs}
    assert not any("SRAM" in n and " " in n for n in names), names


def test_e2e_real_rows_optional_pin_gate_passes(tmp_path):
    # round-4 reopen acceptance shape: real-table doc → runner → L9
    # carries doc-optional pin → gate bare exit=0 against an RTL top
    # that legally omits it.
    (tmp_path / "input" / "docs").mkdir(parents=True)
    (tmp_path / "input" / "docs" / "external_interface.md").write_text(_DOC)
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "chip_top.v").write_text(_RTL)
    r1 = subprocess.run(
        [sys.executable, str(PROGRAMS / "phase1_doc_one_shot_runner.py"),
         str(tmp_path)], capture_output=True, text=True, timeout=60)
    assert r1.returncode == 0, r1.stdout[-1500:] + r1.stderr[-500:]
    l9 = json.loads((tmp_path / "phase1" / "generated_docs"
                     / "L9_INTEGRATION_SPEC.json").read_text())
    opt = {p["name"]: p.get("optional")
           for p in (l9.get("top_ports") or [])}
    assert opt.get("i_gpio") is True, opt
    r2 = subprocess.run(
        [sys.executable, str(PROGRAMS / "l9_rtl_pin_consistency_check.py"),
         str(tmp_path)], capture_output=True, text=True, timeout=60)
    assert r2.returncode == 0, r2.stdout + r2.stderr
    assert "i_gpio" in r2.stdout and "WARN" in r2.stdout, r2.stdout


def test_e2e_required_pin_missing_still_fails(tmp_path):
    # regression guard: optionality must NOT soften REQUIRED pins —
    # drop a required output from the RTL and the gate still FAILs.
    (tmp_path / "input" / "docs").mkdir(parents=True)
    (tmp_path / "input" / "docs" / "external_interface.md").write_text(_DOC)
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "chip_top.v").write_text(
        _RTL.replace("  output wire o_sram_we,\n", ""))
    r1 = subprocess.run(
        [sys.executable, str(PROGRAMS / "phase1_doc_one_shot_runner.py"),
         str(tmp_path)], capture_output=True, text=True, timeout=60)
    assert r1.returncode == 0, r1.stdout[-1500:] + r1.stderr[-500:]
    r2 = subprocess.run(
        [sys.executable, str(PROGRAMS / "l9_rtl_pin_consistency_check.py"),
         str(tmp_path)], capture_output=True, text=True, timeout=60)
    assert r2.returncode == 1, r2.stdout + r2.stderr
    assert "o_sram_we" in r2.stdout, r2.stdout
