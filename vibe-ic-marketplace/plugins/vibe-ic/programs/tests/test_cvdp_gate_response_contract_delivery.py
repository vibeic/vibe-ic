"""The scorer-visible CVDP response contract controls delivery formatting."""
import importlib.util
import json
import sys
from pathlib import Path


PLUGIN = Path(__file__).resolve().parent.parent.parent
HARNESS = PLUGIN / "benchmark"
# Import the module-under-test by FILE PATH, never by bare name: in a
# two-tree session a same-named module from the other tree may already sit
# in sys.modules, and a bare import would silently bind these assertions to
# the OTHER tree's code (measured: exactly the 2 prompt-export tests red in
# the two-tree arm). Same hermetic pattern as
# test_gate_never_reinjects_a_harness_staged_module._gate().
_spec = importlib.util.spec_from_file_location(
    "cvdp_gate_response_contract_under_test", HARNESS / "cvdp_gate.py")
G = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(G)


ELEVATOR = "module elevator_control_system; endmodule"
SEVEN_SEG = "module floor_to_seven_segment; endmodule"
BCD = "module Binary2BCD; endmodule"
MEMORY = "module dual_port_memory; endmodule"
PING = """module ping_pong_buffer;
  dual_port_memory memory0();
endmodule"""


def _files(raw):
    return {key: value for item in json.loads(raw)["code"]
            for key, value in item.items()}


def test_two_file_contract_splits_modified_context_and_new_module():
    out = G._emit_or_split(
        ELEVATOR + "\n" + SEVEN_SEG,
        ["rtl/elevator_control_system.sv", "rtl/floor_to_seven_segment.sv"],
        {"rtl/elevator_control_system.sv": "module elevator_control_system; wire old; endmodule"},
    )
    assert set(_files(out)) == {
        "rtl/elevator_control_system.sv", "rtl/floor_to_seven_segment.sv"}


def test_three_file_contract_keeps_new_prompted_module_in_own_slot():
    out = G._emit_or_split(
        ELEVATOR + "\n" + SEVEN_SEG + "\n" + BCD,
        ["rtl/elevator_control_system.sv", "rtl/floor_to_seven_segment.sv",
         "rtl/Binary2BCD.sv"],
        {
            "rtl/elevator_control_system.sv": "module elevator_control_system; wire old; endmodule",
            "rtl/floor_to_seven_segment.sv": "module floor_to_seven_segment; wire old; endmodule",
        },
    )
    assert set(_files(out)) == {
        "rtl/elevator_control_system.sv",
        "rtl/floor_to_seven_segment.sv",
        "rtl/Binary2BCD.sv",
    }


def test_multifile_schema_survives_after_empty_context_slot_is_removed():
    out = G._emit_or_split(
        PING,
        ["rtl/ping_pong_buffer.sv", "rtl/dual_port_memory.sv"],
        {"rtl/dual_port_memory.sv": MEMORY},
    )
    assert _files(out) == {"rtl/ping_pong_buffer.sv": PING}


def test_single_file_contract_drops_only_unchanged_context_siblings():
    changed = "module elevator_control_system; wire fixed; endmodule"
    combined = changed + "\n" + SEVEN_SEG + "\n" + BCD
    out = G._emit_or_split(
        combined, ["rtl/elevator_control_system.sv"], {
            "rtl/elevator_control_system.sv": ELEVATOR,
            "rtl/floor_to_seven_segment.sv": "// layout\n" + SEVEN_SEG,
            "rtl/Binary2BCD.sv": "\n" + BCD,
        })
    assert not out.lstrip().startswith("{")
    assert "module elevator_control_system" in out
    assert "module floor_to_seven_segment" not in out
    assert "module Binary2BCD" not in out


def test_token_change_prevents_context_sibling_pruning():
    changed_sibling = "module floor_to_seven_segment; wire changed; endmodule"
    out = G._emit_or_split(
        ELEVATOR + "\n" + changed_sibling,
        ["rtl/elevator_control_system.sv"], {
            "rtl/elevator_control_system.sv": ELEVATOR,
            "rtl/floor_to_seven_segment.sv": SEVEN_SEG,
        })
    assert "wire changed" in out


def test_unknown_contract_never_guesses_from_multiple_modules():
    blob = ELEVATOR + "\n" + SEVEN_SEG
    assert G._emit_or_split(blob, None, {
        "rtl/elevator_control_system.sv": ELEVATOR}) == blob
