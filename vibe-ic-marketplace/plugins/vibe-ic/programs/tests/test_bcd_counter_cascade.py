#!/usr/bin/env python3
"""BCD counter parsing smoke test."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from calendar_counter_synth import _calendar_cascade_order, _field_modulo, parse_calendar


def test_bcd_counter_cascade():
    text = """
    Module name: bcd_counter
    Input ports:
      - input clk
      - input rst_n
    Output ports:
      - output reg [3:0] ls_sec
      - output reg [3:0] ms_sec
      - output reg [3:0] ls_min
      - output reg [3:0] ms_min
      - output reg [3:0] ls_hr
      - output reg [3:0] ms_hr
    Seconds count from 0 to 9 and reach 9. Minutes are 0 to 5 and reach 5. Hours count 0-23.
    When seconds reach 59, minutes increment. When minutes reach 59, hours increment.
    """
    fields = ["ls_sec", "ms_sec", "ls_min", "ms_min", "ls_hr", "ms_hr"]
    order = _calendar_cascade_order(text, fields)
    assert order == fields, order


def test_bcd_field_modulo():
    """Each BCD field must have its range STATED in the text, either by explicit
    name proximity or by BCD heuristics (reach/reaches N, 24-hour, etc.)."""
    text = """
    Increment ls_sec until it reaches 9. Increment ms_sec until it reaches 5.
    Increment ls_min until it reaches 9. Increment ms_min until it reaches 5.
    Increment ls_hr until it reaches 9. Increment ms_hr until it reaches 2.
    24-hour format.
    """
    assert _field_modulo(text, "ls_sec") == 10
    assert _field_modulo(text, "ms_sec") == 6
    assert _field_modulo(text, "ls_min") == 10
    assert _field_modulo(text, "ms_min") == 6
    assert _field_modulo(text, "ls_hr") == 10
    assert _field_modulo(text, "ms_hr") == 3


def test_parse_calendar_bcd():
    """Realistic BCD counter prompt matching cvdp_copilot_bcd_counter_0001 shape."""
    text = """
    Module name: bcd_counter
    Input ports:
      - input clk
      - input rst_n
    Output ports:
      - output reg [3:0] ls_sec
      - output reg [3:0] ms_sec
      - output reg [3:0] ls_min
      - output reg [3:0] ms_min
      - output reg [3:0] ls_hr
      - output reg [3:0] ms_hr
    24-hour clock using BCD counters.
    Display hours in 24-hour format from 00:00:00 to 23:59:59.
    Increment ls_sec until it reaches 9.
    Increment ms_sec until it reaches 5.
    When ms_sec reaches 5 and ls_sec reaches 9, reset both to 0 and increment ls_min.
    Increment ls_min until it reaches 9.
    Increment ms_min until it reaches 5.
    When ms_min reaches 5 and ls_min reaches 9, reset both to 0 and increment ls_hr.
    Increment ls_hr until it reaches 9.
    Increment ms_hr until it reaches 2.
    """
    rec = parse_calendar(text)
    assert rec is not None, "parse_calendar should not return None for BCD counter"
    assert rec["kind"] == "calendar"
    fields = rec["ports"]["fields"]
    field_names = [f[0] for f in fields]
    # order check
    assert field_names == ["ls_sec", "ms_sec", "ls_min", "ms_min", "ls_hr", "ms_hr"]
    # modulo check
    assert fields[0][2] == 10  # ls_sec: 0-9
    assert fields[1][2] == 6   # ms_sec: 0-5
    assert fields[2][2] == 10  # ls_min: 0-9
    assert fields[3][2] == 6   # ms_min: 0-5
    assert fields[4][2] == 10  # ls_hr: 0-9
    assert fields[5][2] == 3   # ms_hr: 0-2 (24-hour BCD)


if __name__ == "__main__":
    test_bcd_counter_cascade()
    test_bcd_field_modulo()
    test_parse_calendar_bcd()
    print("PASS: BCD counter tests")
