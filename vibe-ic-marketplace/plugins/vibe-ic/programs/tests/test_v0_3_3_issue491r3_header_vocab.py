"""v0.3.3 — #491 ROUND-3: the multi-table walker's header classifier
only knew ENGLISH single-word vocabulary — a real interface doc whose
main port table is headed `Port group | 寬度 | 方向 | 描述` (multi-word
group name column + CJK width/direction/description) classified to None
and the walker emitted ZERO rows, reproducing the original gate FAIL on
real input while the round-2 synthetic (English-headed) fixture stayed
green.

Pins (closing the round-2 self-test gap with the REAL header
vocabulary):
  * classifier maps `Port group | 寬度 | 方向 | 描述` (and bare CJK
    名稱/方向 forms) to roles;
  * END-TO-END from input docs: a dual-table markdown whose MAIN table
    uses the real CJK + `Port group` header vocabulary and whose SUB
    table uses English headers → the REAL phase1 runner promotes ALL
    rows from BOTH tables into L9 → the REAL
    l9_rtl_pin_consistency_check PASSes against a matching RTL top;
  * English-only docs unchanged (round-2 fixture still green —
    separate file);
  * non-port CJK tables (no direction column) still classify None.
"""
import json
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import phase1_doc_one_shot_runner as P1  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

_DOC = """# 外部介面

## 頂層訊號

| Port group | 寬度 | 方向 | 描述 |
|---|---|---|---|
| i_clk | 1-bit | input | 系統時脈 |
| i_rst | 1-bit | input | 同步reset |
| o_gpio | >=1-bit | output | GPIO |

## 記憶體區塊子埠

| Port | Width | Direction | Description |
|---|---|---|---|
| mem_addr | 8 | input | address |
| mem_rdata | 32 | output | read data |
"""

_RTL = """module chip_top(
  input  wire i_clk,
  input  wire i_rst,
  output wire o_gpio,
  input  wire [7:0] mem_addr,
  output wire [31:0] mem_rdata
);
  assign o_gpio = 1'b0;
  assign mem_rdata = 32'h0;
endmodule
"""


def test_classifier_accepts_real_cjk_group_header():
    roles = P1._v0_3_2_classify_pin_header(
        ["Port group", "寬度", "方向", "描述"])
    assert roles is not None
    assert roles["name"] == 0 and roles["direction"] == 2
    assert roles.get("width") == 1 and roles.get("description") == 3


def test_classifier_accepts_bare_cjk_headers():
    roles = P1._v0_3_2_classify_pin_header(["名稱", "方向"])
    assert roles is not None and roles["name"] == 0


def test_non_port_cjk_table_still_none():
    # a CJK table WITHOUT a direction column is not a port table
    assert P1._v0_3_2_classify_pin_header(["名稱", "寬度", "描述"]) is None


def test_walker_emits_rows_from_real_vocab_doc():
    tables = list(P1._v0_3_2_iter_gfm_pin_tables(_DOC))
    assert len(tables) == 2, "BOTH tables (CJK-headed + English) collected"
    names = set()
    for roles, rows, _hdr_idx in tables:
        for cells in rows:
            names.add(cells[roles["name"]].strip("` "))
    assert {"i_clk", "i_rst", "o_gpio", "mem_addr", "mem_rdata"} <= names


def test_e2e_real_vocab_docs_to_l9_gate_pass(tmp_path):
    # field acceptance shape: real-vocab input docs, NO pre-stuffed L1 →
    # runner → L9 carries all rows → real gate PASS (bare exit=0).
    (tmp_path / "input" / "docs").mkdir(parents=True)
    (tmp_path / "input" / "docs" / "external_interface.md").write_text(_DOC)
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "chip_top.v").write_text(_RTL)
    r1 = _pr.run(
        [sys.executable, str(PROGRAMS / "phase1_doc_one_shot_runner.py"),
         str(tmp_path)], capture_output=True, text=True)
    assert r1.returncode == 0, r1.stdout[-1500:] + r1.stderr[-500:]
    l9 = json.loads((tmp_path / "phase1" / "generated_docs"
                     / "L9_INTEGRATION_SPEC.json").read_text())
    flat = json.dumps(l9)
    for p in ("i_clk", "i_rst", "o_gpio", "mem_addr", "mem_rdata"):
        assert p in flat, f"{p} missing from L9"
    r2 = _pr.run(
        [sys.executable, str(PROGRAMS / "l9_rtl_pin_consistency_check.py"),
         str(tmp_path)], capture_output=True, text=True)
    assert r2.returncode == 0, r2.stdout + r2.stderr
