"""v1.1.73 — directive-1 enhancement loop on the REAL 80-doc corpus closed the
recurring chip-AGNOSTIC FORMAT gaps the extractors missed:
  GAP1 backtick/bold-wrapped cells (`clk`, **NAME**); GAP2 CJK bilingual headers
  (位址|名稱|R/W|寬度); GAP3 register bit-field tables (Bit|Name|Function); GAP6
  pinout widths [size-1:0] / N-bit -> width_param; GAP7 explicit `pdk:` label (IHP
  SG13G2). All verified on the sha256 / spm / serv / ADC docs.
"""
import sys
from pathlib import Path

PROG_DIR = Path(__file__).resolve().parents[1]
if str(PROG_DIR) not in sys.path:
    sys.path.insert(0, str(PROG_DIR))
import structured_table_extractor as T   # noqa: E402
import pinout_table_extractor as P       # noqa: E402
import parametric_spec_extractor as PS    # noqa: E402


def _ttypes(t):
    return [x["element_type"] for x in T.extract_tables(t)]


def test_cjk_register_map_with_backticks():
    reg = ("| 位址(hex) | 名稱 | R/W | 寬度 | 描述 |\n"
           "| `0x00` | `NAME0` | R | 32 | name reg |\n| `0x04` | `NAME1` | R | 32 | x |\n")
    assert _ttypes(reg) == ["register_map"]
    assert T.extract_tables(reg)[0]["rows"][0]["名稱"] == "NAME0"   # backtick stripped


def test_bit_field_table():
    bf = "| Bit | 名稱 | 功能 |\n| 0 | INIT | start |\n| 1 | NEXT | cont |\n"
    assert _ttypes(bf) == ["bit_field_table"]


def test_cjk_command_table():
    cmd = "| 操作 | 方式 | 描述 |\n| READ | rd | read |\n| WRITE | wr | write |\n"
    assert _ttypes(cmd) == ["command_opcode_table"]


def test_english_regression_unaffected():
    en = "| Register | Address | Access | Reset |\n| CTRL | 0x00 | R/W | 0 |\n"
    assert _ttypes(en) == ["register_map"]
    op = "| Opcode | Operation |\n| 0x1 | ADD |\n"
    assert _ttypes(op) == ["command_opcode_table"]
    fsm = "  state | next state in=0, next state in=1 | output\n  A | A, B | 0\n  B | C, B | 0\n"
    assert _ttypes(fsm) == ["structured_table"]                    # still no mis-fire


def test_cjk_pinout_and_symbolic_width():
    doc = ("| 訊號名 | 寬度 | 方向 | 描述 |\n| `clk` | 1 | input | clk |\n"
           "| `x` | [size-1:0] | input | data |\n| `y` | N-bit | output | out |\n")
    pins = {p["name"]: p for p in P.extract_pinout(doc)}
    assert pins["clk"]["width"] == 1 and pins["clk"]["dir"] == "in"
    assert pins["x"]["width_param"] == "size"
    assert pins["y"]["width_param"] == "N" and pins["y"]["dir"] == "out"


def test_explicit_width_bracket_numeric():
    doc = "| Signal | Width | Dir |\n| d | [7:0] | input |\n"
    assert P.extract_pinout(doc)[0]["width"] == 8


def test_pdk_explicit_label_and_foundries():
    assert PS.extract_pdk_target("- pdk: IHP SG13G2")["pdk"] == "IHP SG13G2"
    assert PS.extract_pdk_target("uses the IHP SG13G2 process")["pdk"].lower().startswith("ihp")
    assert PS.extract_pdk_target("targets sky130A")["pdk"] == "sky130A"   # regression
