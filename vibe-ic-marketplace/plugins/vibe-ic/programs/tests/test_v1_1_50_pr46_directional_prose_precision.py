"""Step-2.7 §4.05 precision hardening of PR #46's directional-prose port
extractor (gatekeeper remediation). The extractor populates L1 pin_table ONLY as
a post-cross-walk FALLBACK (when pin_table is still empty), and it DRIVES the
blind RTL author — so a PHANTOM pin (a non-port colon-bullet harvested as a port)
actively MISLEADS the author with a wrong signal name AND suppresses the honest
'no ports → guess' fallback. Step-2.7 reproduced four phantom classes; each is
pinned here. (no-cheat + the zero-regression callsite guard were CLEAN — the
fallback never touches a non-empty pin_table.)
"""
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROGRAMS))
import phase1_doc_one_shot_runner as P  # noqa: E402


def _names(doc):
    return {e["name"] for e in P._l1_directional_prose_port_extract(doc)}


def test_config_attribute_bullets_are_not_ports():
    # Width/Latency/Throughput/Protocol/Frequency/Endianness are config/attribute
    # values, never a top-level I/O port — must not become phantom pins.
    doc = ("Inputs:\n- Latency: 3 cycles\n- Throughput: 1/clk\n- Width: configurable\n"
           "- Endianness: little\n- Protocol: AXI\n- Frequency: 50MHz")
    assert _names(doc) == set()


def test_reset_enable_valid_still_extract_as_ports():
    # the attribute stop-list must NOT swallow common real port names.
    got = _names("Inputs:\n- reset: active-low\n- enable: gate\n- valid: strobe")
    assert got == {"reset", "enable", "valid"}


def test_documentation_section_heading_opens_no_port_block():
    # a heading with non-port trailing words is a doc section, not a port list.
    for doc in ("Output format:\n- json: emit JSON\n- csv: emit CSV",
                "Input validation:\n- range: reject\n- parity: check",
                "Output stage description:\n- foo: bar",
                "Input requirements:\n- spec: must hold"):
        assert _names(doc) == set(), doc


def test_genuine_port_list_headings_still_open_a_block():
    assert len(_names("Inputs:\n- clk: clock\n- rst_n: reset")) == 2
    assert len(_names("Output ports:\n- dout: data out")) == 1
    assert len(_names("Output(s):\n- result: the out")) == 1
    # bold/underscore-wrapped headings with the colon INSIDE the emphasis
    # (`**Inputs:**`) — a very common markdown form — must still open a block
    # (the precision-tightening tail must accept the colon on either side).
    assert _names("**Inputs:**\n- clk_in: clock\n- rst_n: reset") == {"clk_in", "rst_n"}
    assert _names("__Outputs:__\n- dout: data out") == {"dout"}
    assert _names("**Output format:**\n- json: x\n- csv: y") == set()  # phantom still rejected
    # parenthetical width default still applies a width
    w = [e["width"] for e in P._l1_directional_prose_port_extract(
        "Inputs (1-bit width each):\n- sel: pick\n- mode_in: mode")]
    assert w == ["1", "1"]


def test_register_map_bullets_are_not_ports():
    assert _names("Inputs:\n- CTRL: control register\n- STATUS: status register") == set()
    assert _names("Inputs:\n- BASE: memory map base address") == set()


def test_register_guard_does_not_false_negative_a_real_port():
    # a real PORT whose DESCRIPTION merely mentions a register in a sentence must
    # still extract — the guard fires only on the short `[adj] register` LABEL.
    assert _names("Outputs:\n- data_out: drives the shift register on each clock") == {"data_out"}
    assert _names("Outputs:\n- q_reg: data register output port for the block") == {"q_reg"}


def test_parameterized_width_range_is_none_not_junk():
    pins = P._l1_directional_prose_port_extract("Inputs:\n- data_bus [WIDTH-1:0]: the bus")
    assert len(pins) == 1
    assert pins[0]["name"] == "data_bus"
    assert pins[0]["width"] is None       # not the junk string "[WIDTH-1:0]"


def test_numeric_width_still_computed():
    pins = P._l1_directional_prose_port_extract("Inputs:\n- [7:0] din: data in")
    assert pins == [{"name": "din", "mode": "input", "width": "8", "description": "data in"}]


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
