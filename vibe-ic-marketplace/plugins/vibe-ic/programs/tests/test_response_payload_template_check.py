#!/usr/bin/env python3
"""Tests for response_payload_template_check.py

THE PROPERTY THESE PIN — the program advertises three verdicts (0 PASS,
1 findings, 2 not-checked) and could only ever emit one of them.  Every finding
it could produce was severity ``WARN`` while ``pass`` was ``not any(ERROR)``,
whose only producer was the IO error, so on any readable RTL directory the
exit-1 verdict was structurally unreachable: it printed findings under
``"pass": true``.  Both directions are driven here — the failing tier must be
reachable, AND the passing tier must survive, because a gate that can only say
FAIL is the same defect pointed the other way.

Every fixture is synthetic and chip-agnostic: no design, PDK or part number.
"""
from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / "response_payload_template_check.py"


def _run(args, **kw):
    return subprocess.run([sys.executable, str(PROG)] + args,
                          capture_output=True, text=True, **kw)


def _report(rtl_dir: Path):
    r = _run(["--rtl-dir", str(rtl_dir)])
    assert "Traceback" not in r.stderr, r.stderr[-800:]
    return r, json.loads(r.stdout)


def _rtl(tmp_path: Path, **files: str) -> Path:
    d = tmp_path / "rtl"
    d.mkdir(exist_ok=True)
    for name, body in files.items():
        (d / name.replace("__", ".")).write_text(body)
    return d


# A command dispatcher whose whole reply packet is literals, in a file that
# never sources a payload byte from anything. Nothing here names a device.
_ALL_CONSTANT_REPLY = """\
module dispatcher(input clk, input [7:0] cmd_op, output reg send);
  reg [7:0] rsp_buf [0:3];
  always @(posedge clk) begin
    case (cmd_op)
      8'hA0: begin
        rsp_buf[0] <= 8'h00;
        rsp_buf[1] <= 8'h00;
        rsp_buf[2] <= 8'h00;
        send <= 1'b1;
      end
    endcase
  end
endmodule
"""

# The same shape with the data path actually wired.
_DYNAMIC_REPLY = """\
module dispatcher(input clk, input [7:0] cmd_op,
                  input [7:0] status_reg, input [7:0] arg_byte);
  reg [7:0] rsp_buf [0:3];
  always @(posedge clk) begin
    case (cmd_op)
      8'hA0: begin
        rsp_buf[0] <= status_reg;
        rsp_buf[1] <= arg_byte;
      end
    endcase
  end
endmodule
"""

# One handler is entirely literal, but the module DOES wire a dynamic byte for
# another opcode — the advisory case, deliberately kept out of the ERROR tier.
_MIXED_REPLY = """\
module dispatcher(input clk, input [7:0] cmd_op, input [7:0] status_reg);
  reg [7:0] rsp_buf [0:3];
  always @(posedge clk) begin
    case (cmd_op)
      8'hA0: begin
        rsp_buf[0] <= status_reg;
        rsp_buf[1] <= status_reg;
      end
      8'hB0: begin
        rsp_buf[0] <= 8'h00;
        rsp_buf[1] <= 8'h00;
      end
    endcase
  end
endmodule
"""


def test_help():
    r = _run(["--help"])
    assert r.returncode == 0


# ── direction 1: the FAIL verdict is reachable ──────────────────────────────

def test_all_constant_reply_with_no_dynamic_path_is_a_fail(tmp_path):
    """THE regression. A dispatcher that assembles its entire reply from
    literals, in a file that never writes a dynamic payload byte, is the
    maximum-severity input this rule has. It used to exit 0 with the findings
    printed under `"pass": true`."""
    rtl = _rtl(tmp_path, dispatcher__v=_ALL_CONSTANT_REPLY)
    r, report = _report(rtl)
    assert r.returncode == 1, (
        f"the failing verdict is still unreachable: rc={r.returncode}\n"
        f"{r.stdout[:600]}")
    assert report["summary"]["pass"] is False
    errors = [f for f in report["findings"] if f["severity"] == "ERROR"]
    assert errors, report["findings"]
    assert errors[0]["category"] == "RESPONSE_PAYLOAD_NEVER_DYNAMIC"
    assert report["summary"]["error_findings"] == 1
    assert report["summary"]["denominator"]["examined"] == 3


def test_the_verdict_and_the_exit_code_agree(tmp_path):
    """`pass: false` with rc 0 is the shape this program shipped. The two
    channels are read by different consumers, so they are asserted together."""
    rtl = _rtl(tmp_path, dispatcher__v=_ALL_CONSTANT_REPLY)
    r, report = _report(rtl)
    assert (report["summary"]["pass"] is False) == (r.returncode == 1)


# ── direction 2: the PASS verdict still exists (not an always-fail gate) ────

def test_a_dispatcher_with_a_dynamic_payload_passes(tmp_path):
    """The other half of the property. A reply whose bytes come from a
    register and an echoed argument is correct by this rule, and must stay
    rc 0 — a gate that can only emit FAIL is the same defect inverted."""
    rtl = _rtl(tmp_path, dispatcher__v=_DYNAMIC_REPLY)
    r, report = _report(rtl)
    assert r.returncode == 0, r.stdout[:600]
    assert report["summary"]["pass"] is True
    assert [f for f in report["findings"] if f["severity"] == "ERROR"] == []
    assert report["summary"]["denominator"]["examined"] == 2


def test_a_constant_handler_beside_a_wired_one_stays_advisory(tmp_path):
    """The ERROR tier is BOUNDED. A fixed status/ID reply for one opcode, in a
    module that does source other bytes dynamically, is a judgement call and
    stays a WARN at rc 0 — this is what stops the fix from reddening every
    design that has a constant byte in it."""
    rtl = _rtl(tmp_path, dispatcher__v=_MIXED_REPLY)
    r, report = _report(rtl)
    assert r.returncode == 0, r.stdout[:600]
    assert report["summary"]["pass"] is True
    assert {f["severity"] for f in report["findings"]} == {"WARN"}
    assert len([f for f in report["findings"]
                if f["category"] == "MOSTLY_HARDCODED_RESPONSE"]) == 1
    # Deliberately asserted on the findings, not on a summary key this change
    # added: this is the INVARIANT control, and it must hold against the
    # unfixed program too, or it cannot witness that the fix left the advisory
    # tier where it was.


# ── the third verdict: examined nothing is not a pass ───────────────────────

def test_examined_nothing_is_rc2_not_pass(tmp_path):
    """A directory with no response buffer used to exit 0 — a PASS certifying
    a rule that never ran. rc 2 is this repo's NOT-CHECKED code and the
    `VACUOUS_PASS:` sentinel is the second consumer channel."""
    rtl = _rtl(tmp_path, top__v="module top(input clk);\nendmodule\n")
    r, report = _report(rtl)
    assert r.returncode == 2, r.stdout[:600]
    assert report["summary"]["skipped"] is True
    assert report["summary"]["denominator"]["examined"] == 0
    assert any(line.lstrip().startswith("VACUOUS_PASS")
               for line in r.stderr.splitlines()), r.stderr


def test_missing_directory_is_an_input_error_not_a_verdict(tmp_path):
    r = _run(["--rtl-dir", str(tmp_path / "nope")])
    assert r.returncode == 2
    report = json.loads(r.stdout)
    assert report["summary"]["pass"] is False
    assert [f["category"] for f in report["findings"]] == ["IO"]


def test_the_program_no_longer_calls_itself_advisory_only(tmp_path):
    """#496 published `advisory_only: true` as a machine-readable statement
    that this checker could not return non-zero. It can now, and the field is
    kept rather than deleted so a consumer reading it is told so."""
    rtl = _rtl(tmp_path, dispatcher__v=_ALL_CONSTANT_REPLY)
    _r, report = _report(rtl)
    assert report["summary"]["advisory_only"] is False
