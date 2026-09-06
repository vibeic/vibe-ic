"""The plain-text `Input ports:` definition list reaches L9, and the width it
states reaches L1.

MEASURED 2026-09-06 on main v1.17.80: every one of the 50 RTLLM designs halted
in Phase 1 on the extraction-gap gate and 0 of 50 reached the emitter. Bisected
to dd85b42ce (v1.17.69), which made the extraction gap BLOCK on both front
doors. The gap itself is older: the docs front door reads ports from interface
TABLES and inline Verilog declarations only, so the commonest plain-text spec
shape

    Input ports:
        clk: Clock signal.
        data_in[7:0]: 8-bit input data.

reached L9 as `ports: []` at v1.17.60 too — v1.17.69 only made the silence
fatal. Three chained defects, one per test file section below:
  1. `extract_prose_ports` required a markdown BULLET, so it read nothing here.
  2. nothing on the docs branch called it, so L9 stayed empty.
  3. the L9->L1 cross-walk dropped the bus width, so `l1_pin_bus_width_
     actionable_check` then refused a pin L9 had already resolved.
"""
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parent.parent
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import phase1_port_extract as E  # noqa: E402

# The real shape, reduced: tab indent, a bracket range before the colon, a
# column-0 entry in the second list, and a following heading that must NOT be
# read as a port.
SPEC = (
    "Module name:\n"
    "    accu\n"
    "Input ports:\n"
    "\tclk: Clock input for synchronization.\n"
    "\trst_n: Active-low reset signal.\n"
    "\tdata_in[7:0]: 8-bit input data for addition.\n"
    "\n"
    "Output ports:\n"
    "valid_out: Output signal indicating when the sum is ready.\n"
    "\tdata_out[9:0]: 10-bit output data representing the accumulated sum.\n"
    "\n"
    "Implementation:\n"
    "Declare the module accu with the ports above.\n"
    "Note: the accumulator resets to zero.\n"
)


def _by_name(rows):
    return {r["name"]: r for r in rows}


def test_unbulleted_definition_list_under_a_port_heading_is_read():
    got = _by_name(E.extract_prose_ports(SPEC))
    assert set(got) == {"clk", "rst_n", "data_in", "valid_out", "data_out"}, got
    assert got["clk"]["dir"] == "input"
    assert got["data_in"]["dir"] == "input" and got["data_in"]["width"] == 8
    assert got["valid_out"]["dir"] == "output"
    assert got["data_out"]["dir"] == "output" and got["data_out"]["width"] == 10


def test_the_section_ends_with_its_own_definition_run():
    # The load-bearing negative, and it is deliberately NOT rescuable by the
    # TitleCase rule or by the meta stop-list: `timing:` is lowercase and names
    # nothing structural. A section that never ended would make it an output
    # port, because it sits after the output list with only an ordinary
    # sentence between them.
    spec = ("Output ports:\n"
            "\tdata_out[9:0]: 10-bit output data.\n"
            "The accumulator resets to zero when rst_n falls.\n"
            "timing: the output is valid one cycle after the fourth sample.\n")
    got = _by_name(E.extract_prose_ports(spec))
    assert set(got) == {"data_out"}, got


def test_headings_after_a_section_are_not_read_as_ports():
    got = _by_name(E.extract_prose_ports(SPEC))
    assert "Implementation" not in got and "Note" not in got, got
    assert "accu" not in got, got          # the module-name line has no colon


def test_a_real_port_named_reset_survives_the_descriptor_stop_list():
    # `reset`/`clock`/`data` are in the descriptor stop-list because a bullet
    # "- Reset: ..." is a heading, not a signal. Under an explicit port heading
    # they are the signal, and dropping one publishes an interface missing a pin.
    spec = ("Input ports:\n"
            "        clk: Clock signal.\n"
            "        reset: Reset signal to initialize the counter.\n"
            "\nOutput ports:\n"
            "        out [7:0]: 8-bit output.\n")
    got = _by_name(E.extract_prose_ports(spec))
    assert set(got) == {"clk", "reset", "out"}, got
    assert got["out"]["width"] == 8


def test_a_titlecase_descriptor_bullet_is_still_rejected():
    # The stop-list is relaxed inside a section, NOT removed: a TitleCase
    # English word heading a descriptor is still not a port.
    # `Latency` is NOT in the meta stop-list, so only the TitleCase rule can
    # reject it — which is what makes this a control for that rule and not for
    # the stop-list next to it.
    spec = ("Input ports:\n"
            "        clk: Clock signal.\n"
            "        Latency: one cycle from sample to output.\n")
    got = _by_name(E.extract_prose_ports(spec))
    assert set(got) == {"clk"}, got


def test_bulleted_lists_outside_any_section_are_unchanged():
    # The pre-existing channel: a bullet with an explicit direction in the
    # description, no section header anywhere.
    spec = "- `foo`: 4-bit input bus\n- `bar`: 2-bit output\n"
    got = _by_name(E.extract_prose_ports(spec))
    assert got["foo"]["dir"] == "input" and got["foo"]["width"] == 4
    assert got["bar"]["dir"] == "output" and got["bar"]["width"] == 2


# ---- the docs front door: L9 fill, and only when it is empty ---------------

def _runner():
    import phase1_doc_one_shot_runner as D
    return D


def test_l9_prose_fallback_fills_an_empty_port_list():
    D = _runner()
    ports = []
    content = {"ports": ports, "top_ports": ports, "top_module_pins": ports}
    D._czl9_prose_port_fallback(content, {"design_description.md": SPEC})
    assert [p["name"] for p in ports] == [
        "clk", "rst_n", "data_in", "valid_out", "data_out"], ports
    # the row shape must match the prompt door's own backfill, `mode` included:
    # a row carrying only `dir` counts as "structured" for that backfill's
    # not-structured guard and would suppress the richer producer.
    assert ports[0]["mode"] == "input" and ports[0]["direction"] == "input"
    assert ports[-1]["mode"] == "output" and ports[-1]["width"] == 10
    # one list object behind three keys — the fill must reach all of them
    assert content["ports"] is ports and content["top_ports"] is ports
    assert content["top_module_pins"] is ports


def test_l9_prose_fallback_never_touches_a_populated_port_list():
    # STRICTLY ADDITIVE is the whole safety argument: it runs only in the state
    # the gate calls an extraction gap, so it cannot overwrite a real interface.
    D = _runner()
    ports = [{"name": "already_here", "dir": "input", "width": 1}]
    content = {"ports": ports, "top_ports": ports, "top_module_pins": ports}
    D._czl9_prose_port_fallback(content, {"design_description.md": SPEC})
    assert ports == [{"name": "already_here", "dir": "input", "width": 1}]


def test_l9_prose_fallback_stays_silent_when_the_input_declares_nothing():
    D = _runner()
    ports = []
    content = {"ports": ports, "top_ports": ports, "top_module_pins": ports}
    D._czl9_prose_port_fallback(
        content, {"d.md": "A block that adds two numbers together."})
    assert ports == []
    assert "top_module_pins_source" not in content


# ---- the L9 -> L1 cross-walk carries the width ----------------------------

def test_crosswalk_carries_the_bus_width_into_l1():
    D = _runner()
    l1 = {}
    D._v1_6_555_crosswalk_l9_ports_to_l1_pin_table(l1, [
        {"name": "clk", "direction": "input", "width": 1},
        {"name": "data_in", "direction": "input", "width": 8},
        {"name": "bus", "direction": "output", "msb": 9, "lsb": 0},
        {"name": "unknown_width", "direction": "output"},
    ])
    rows = {r["name"]: r for r in l1["pin_table"]}
    assert rows["data_in"]["width"] == 8
    assert rows["data_in"]["msb"] == 7 and rows["data_in"]["lsb"] == 0
    assert rows["bus"]["width"] == 10
    # an unstated width stays the honest absence the gate is entitled to refuse
    assert "width" not in rows["unknown_width"]
