#!/usr/bin/env python3
"""Tests for programs/level_hysteresis_flag_oracle_check.py.

Fixtures are SYNTHETIC same-genre designs (a water-tank level controller with
thermometer sensors), deliberately NOT copied from any benchmark dataset —
this both keeps licensed prompt text out of the repo and proves the oracle
keys on the structural genre signature, not on one dataset instance.

Covers, per the capture skill's Bucket-A bar:
  * the REAL DEFECT it guards — the literal rise->open polarity that two blind
    campaigns emitted (identical >50% mismatch), the second time while
    ACKNOWLEDGING the captured lesson (ack-fidelity gap);
  * GREEN — the anchor-consistent fall->open polarity passes;
  * §4.05 no-false-block — every ambiguous precondition SKIPs, never blocks:
    no band table / no reset-equivalence sentence / no relative sentence /
    non-unique flag output / anchors that fail to disambiguate;
  * dual-candidate anchor filter unit behaviour;
  * both interface styles (bullet list and embedded module header);
  * honest tool handling (rc=2 when iverilog is absent is exercised upstream
    by the DISCLOSED_TOOL_GAP branch; here we assert the JSON evidence shape).
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
GATE = PROGRAMS / "level_hysteresis_flag_oracle_check.py"

sys.path.insert(0, str(PROGRAMS))
from level_hysteresis_flag_oracle_check import (  # noqa: E402
    parse_interface, parse_band_table, anchor_filter, find_relative_sentence,
)

HAVE_IVERILOG = shutil.which("iverilog") is not None

PROMPT = """
I would like you to implement a module named TopModule with the following
interface. All input and output ports are one bit unless otherwise specified.

 - input  clk
 - input  reset
 - input  lvl (3 bits)
 - output pump2
 - output pump1
 - output pump0
 - output aux

A tank serves several users. Three sensors are placed vertically. When the
water level is above the highest sensor lvl[2], the input flow rate should be
zero. When the level is below the lowest sensor lvl[0], the flow rate should
be at maximum (both the nominal pumps and the auxiliary pump opened). The flow
rate between the sensors is determined by the level and by the level previous
to the last sensor change. If the sensor change indicates that the previous
level was lower than the current level, the flow rate should be increased by
opening the auxiliary pump (controlled by aux).

  Water Level             | Sensors Asserted       | Nominal Pumps to be Asserted
  Above lvl[2]            | lvl[0], lvl[1], lvl[2] | None
  Between lvl[2] and lvl[1] | lvl[0], lvl[1]       | pump0
  Between lvl[1] and lvl[0] | lvl[0]               | pump0, pump1
  Below lvl[0]            | None                   | pump0, pump1, pump2

Also include an active-high synchronous reset that resets the state machine to
a state equivalent to if the water level had been low for a long time (no
sensors asserted, and all four outputs asserted).
"""

# The genre-correct implementation (anchors win: fall->1). Paired direction
# states, Moore decode, held flag.
RTL_CORRECT = """
module TopModule (
  input        clk,
  input        reset,
  input  [2:0] lvl,
  output       pump2,
  output       pump1,
  output       pump0,
  output       aux
);
  localparam A=3'd0, B1=3'd1, B2=3'd2, C1=3'd3, C2=3'd4, D=3'd5;
  reg [2:0] state, next;
  always @(*) begin
    case (state)
      A : next = lvl[0] ? B1 : A;
      B1: next = lvl[1] ? C1 : (lvl[0] ? B1 : A);
      B2: next = lvl[1] ? C1 : (lvl[0] ? B2 : A);
      C1: next = lvl[2] ? D  : (lvl[1] ? C1 : B2);
      C2: next = lvl[2] ? D  : (lvl[1] ? C2 : B2);
      D : next = lvl[2] ? D  : C2;
      default: next = A;
    endcase
  end
  always @(posedge clk) if (reset) state <= A; else state <= next;
  assign pump2 = (state==A);
  assign pump1 = (state==A)||(state==B1)||(state==B2);
  assign pump0 = (state==A)||(state==B1)||(state==B2)||(state==C1)||(state==C2);
  // fall-entered states carry the auxiliary pump (anchor-consistent polarity)
  assign aux   = (state==A)||(state==B2)||(state==C2);
endmodule
"""

# The REAL DEFECT: identical structure, literal rise->1 polarity on the flag.
RTL_WRONG = RTL_CORRECT.replace(
    "assign aux   = (state==A)||(state==B2)||(state==C2);",
    "assign aux   = (state==A)||(state==B1)||(state==C1);")


def run(prompt: str, rtl: str, top="TopModule", json_out=None):
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        (td / "p.txt").write_text(prompt)
        (td / "r.sv").write_text(rtl)
        args = [sys.executable, str(GATE), "--prompt", str(td / "p.txt"),
                "--rtl", str(td / "r.sv"), "--top", top]
        jp = td / "ev.json"
        args += ["--json", str(jp)]
        c = subprocess.run(args, capture_output=True, text=True, timeout=60)
        ev = json.loads(jp.read_text()) if jp.is_file() else {}
        return c.returncode, c.stdout + c.stderr, ev


# ---------------- unit level: parsing + the dual-candidate filter ----------

def test_parse_interface_bullet_list():
    iface = parse_interface(PROMPT)
    assert iface["lvl"] == ("input", 3)
    assert iface["aux"] == ("output", 1)


def test_parse_interface_module_header_fallback():
    hdr = "Build it.\n\nmodule TopModule (\n  input clk,\n  input reset,\n" \
          "  input [2:0] lvl,\n  output reg pump0,\n  output aux\n);\n"
    iface = parse_interface(hdr)
    assert iface["lvl"] == ("input", 3)
    assert iface["pump0"] == ("output", 1)


def test_parse_band_table_thermometer():
    t = parse_band_table(PROMPT)
    assert t is not None and t["vector"] == "lvl"
    assert [len(r["sensors"]) for r in t["rows"]] == [0, 1, 2, 3]
    assert t["rows"][0]["outputs"] == {"pump0", "pump1", "pump2"}
    assert t["rows"][3]["outputs"] == set()


def test_anchor_filter_disambiguates_to_fall_one():
    ok_rise, _ = anchor_filter(True, 4, True, True)
    ok_fall, _ = anchor_filter(False, 4, True, True)
    assert not ok_rise and ok_fall  # exactly one survivor


def test_relative_sentence_literal_reading_extracted():
    rel = find_relative_sentence(PROMPT, frozenset({"aux"}))
    assert rel is not None and rel["literal_rise_is_one"] is True


# ---------------- the REAL DEFECT (needs iverilog) --------------------------

@pytest.mark.skipif(not HAVE_IVERILOG, reason="iverilog absent")
def test_real_defect_literal_polarity_blocks():
    rc, out, ev = run(PROMPT, RTL_WRONG)
    assert rc == 1
    assert ev["verdict"] == "BLOCK"
    assert ev["surviving_polarity"] == "fall->1"
    kinds = {m["kind"] for m in ev["mismatches"]}
    assert "hysteresis-flag-polarity" in kinds
    # dual-track evidence present: candidates, walk, mismatches
    assert ev["candidates"] and ev["walk"]


@pytest.mark.skipif(not HAVE_IVERILOG, reason="iverilog absent")
def test_correct_polarity_passes():
    rc, out, ev = run(PROMPT, RTL_CORRECT)
    assert rc == 0
    assert ev["verdict"] == "PASS"


# ---------------- §4.05: ambiguity SKIPs, never blocks ----------------------

def test_skip_without_band_table():
    p = PROMPT.split("  Water Level")[0]  # strip the table
    rc, out, ev = run(p, RTL_WRONG)
    assert rc == 0 and ev["verdict"] == "SKIP"


def test_skip_without_reset_equivalence():
    p = PROMPT.replace("all four outputs asserted", "the usual outputs set")
    rc, out, ev = run(p, RTL_WRONG)
    assert rc == 0 and ev["verdict"] == "SKIP"


def test_skip_without_relative_sentence():
    # NB: the fixture wraps lines, so kill the DIRECTION WORD (which the
    # detector requires) rather than a phrase that may span a line break.
    p = PROMPT.replace("lower than", "beyond")
    rc, out, ev = run(p, RTL_WRONG)
    assert rc == 0 and ev["verdict"] == "SKIP"


def test_skip_when_flag_not_unique():
    # a second table-unlisted output makes the flag ambiguous
    p = PROMPT.replace(" - output aux", " - output aux\n - output aux2")
    rtl = RTL_WRONG.replace("output       aux\n", "output       aux,\n  output aux2\n") \
                   .replace("endmodule", "  assign aux2 = 1'b0;\nendmodule")
    rc, out, ev = run(p, rtl)
    assert rc == 0 and ev["verdict"] == "SKIP"
    assert "not unique" in ev.get("skip_reason", "")


def test_skip_when_anchors_do_not_disambiguate():
    # remove the top-zero sentence AND the bottom bracket: keep reset-equivalence
    # but flip it so both candidates survive is hard to fabricate; instead drop
    # top-zero and weaken nothing else — bottom alone still disambiguates, so
    # fabricate the truly ambiguous case: no top sentence and no reset line.
    p = PROMPT.replace("the input flow rate should be\nzero", "the inflow is small")
    p = p.replace("all four outputs asserted", "the outputs set accordingly")
    rc, out, ev = run(p, RTL_WRONG)
    assert rc == 0 and ev["verdict"] == "SKIP"


def test_missing_rtl_is_usage_error():
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        (td / "p.txt").write_text(PROMPT)
        c = subprocess.run([sys.executable, str(GATE), "--prompt",
                            str(td / "p.txt"), "--rtl", str(td / "nope.sv")],
                           capture_output=True, text=True)
        assert c.returncode == 2


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
