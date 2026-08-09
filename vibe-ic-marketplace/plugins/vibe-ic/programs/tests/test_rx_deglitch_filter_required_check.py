#!/usr/bin/env python3
"""Tests for rx_deglitch_filter_required_check.py (Wave 22)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = (
    Path(__file__).resolve().parent.parent / "rx_deglitch_filter_required_check.py"
)


def _run(tmp_path: Path):
    return subprocess.run(
        [sys.executable, str(PROG), str(tmp_path)],
        capture_output=True,
        text=True,
    )


def _write_rtl(tmp_path: Path, name: str, body: str) -> None:
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / name).write_text(body)


def test_3ff_2of2_pass(tmp_path):
    # Vendor PASS-oracle pattern: 3 sync stages + AND-based 2-of-2.
    _write_rtl(
        tmp_path,
        "top.sv",
        """
module top(
  input  wire clk,
  inout  wire id_bus,
  output wire id_bus_low_n
);
  wire id_bus_rx;
  reg  id_bus_rx_syn1;
  reg  id_bus_rx_syn2;
  reg  id_bus_rx_syn3;
  always @(posedge clk) begin
    id_bus_rx_syn1 <= id_bus_rx;
    id_bus_rx_syn2 <= id_bus_rx_syn1;
    id_bus_rx_syn3 <= id_bus_rx_syn2;
  end
  assign id_bus_low_n = id_bus_rx_syn3 & id_bus_rx_syn2;
  assign id_bus = 1'bz;
endmodule
""",
    )
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout
    assert "PASS" in r.stdout, r.stdout


def test_2ff_only_fail(tmp_path):
    # The 27th-attempt anti-pattern: 2-FF synchronizer fed straight
    # into the consumer with only a self-RX OR mask, no deglitch.
    _write_rtl(
        tmp_path,
        "top.sv",
        """
module top(
  input  wire clk,
  inout  wire id_bus
);
  reg id_ff1, id_ff2;
  always @(posedge clk) begin
    id_ff1 <= id_bus;
    id_ff2 <= id_ff1;
  end
  wire id_in = id_ff2;
  assign id_bus = 1'bz;
endmodule
""",
    )
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout
    assert "RX_SYNC_CHAIN_TOO_SHORT" in r.stdout


def test_3ff_no_filter_warn(tmp_path):
    # 3 stages, but consumer reads the last FF directly — no AND/OR
    # combination. Emits WARN, returns 0.
    _write_rtl(
        tmp_path,
        "top.sv",
        """
module top(
  input  wire clk,
  inout  wire bus_pad
);
  reg s1, s2, s3;
  always @(posedge clk) begin
    s1 <= bus_pad;
    s2 <= s1;
    s3 <= s2;
  end
  wire bus_in = s3;
  assign bus_pad = 1'bz;
endmodule
""",
    )
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout
    assert "WARN" in r.stdout
    assert "RX_DEGLITCH_FILTER_MISSING" in r.stdout


def test_3ff_or_filter_pass(tmp_path):
    # 3 stages + OR-based 2-of-2 also counts.
    _write_rtl(
        tmp_path,
        "top.sv",
        """
module top(
  input  wire clk,
  inout  wire kline
);
  reg s1, s2, s3;
  always @(posedge clk) begin
    s1 <= kline;
    s2 <= s1;
    s3 <= s2;
  end
  assign kline_low_evt = s3 | s2;
  assign kline = 1'bz;
endmodule
""",
    )
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout
    assert "PASS" in r.stdout


def test_no_rx_path_skip(tmp_path):
    # No inout / no rx-phy file → SKIP.
    _write_rtl(
        tmp_path,
        "alu.sv",
        """
module alu(input wire [7:0] a, output wire [7:0] y);
  assign y = a + 1;
endmodule
""",
    )
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "SKIP" in r.stdout


def test_with_waiver_pass(tmp_path):
    # 2-FF chain (would FAIL) silenced by valid waiver.
    _write_rtl(
        tmp_path,
        "top.sv",
        """
module top(
  input  wire clk,
  inout  wire id_bus
);
  reg id_ff1, id_ff2;
  always @(posedge clk) begin
    id_ff1 <= id_bus;
    id_ff2 <= id_ff1;
  end
  wire id_in = id_ff2;
  assign id_bus = 1'bz;
endmodule
""",
    )
    (tmp_path / "waivers.json").write_text(json.dumps({
        "rx_deglitch_intentionally_omitted":
            "On-chip pad already has analog Schmitt trigger + RC "
            "filter equivalent to ≥3-stage deglitch per pad spec.",
    }))
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "PASS_WITH_WAIVER" in r.stdout


# ---------------------------------------------------------------------------
# Multi-RX-path aggregation.
#
# The umbrella dispatches this gate ONCE per PROJECT over an rtl/ tree that
# normally holds more than one pad. Until the aggregation fix the project
# verdict was the verdict of whichever (file, seed) produced the LONGEST
# chain, so the greenest pad in the design answered for every other pad and
# the FAIL verdict (`RX_SYNC_CHAIN_TOO_SHORT`) was unreachable for the exact
# shape this gate exists to catch. Both directions are asserted on returned
# exit codes and on the emitted JSON — never on the text of the source.
# ---------------------------------------------------------------------------

def _run_json(tmp_path: Path):
    """Run the gate and return (CompletedProcess, parsed json report)."""
    out = tmp_path / "report.json"
    r = subprocess.run(
        [sys.executable, str(PROG), str(tmp_path), "--json", str(out)],
        capture_output=True,
        text=True,
    )
    return r, json.loads(out.read_text())


# A compliant single-wire pad: 3-stage synchroniser + 2-of-2 AND vote.
_COMPLIANT_PAD = """
module aux_pad_block(
  input  wire clk,
  inout  wire aux_pad,
  output wire aux_stable
);
  reg a1, a2, a3;
  always @(posedge clk) begin
    a1 <= aux_pad;
    a2 <= a1;
    a3 <= a2;
  end
  assign aux_stable = a3 & a2;
  assign aux_pad = 1'bz;
endmodule
"""

# A second compliant pad, so the PASS direction is also multi-path.
_COMPLIANT_PAD_2 = """
module alt_pad_block(
  input  wire clk,
  inout  wire alt_pad,
  output wire alt_stable
);
  reg b1, b2, b3;
  always @(posedge clk) begin
    b1 <= alt_pad;
    b2 <= b1;
    b3 <= b2;
  end
  assign alt_stable = b3 | b2;
  assign alt_pad = 1'bz;
endmodule
"""

# The anti-pattern: a 2-FF synchroniser whose output goes straight to the
# bit decoder. No third stage, no vote.
_TWO_FF_PAD = """
module bus_wrapper(
  input  wire clk,
  inout  wire serial_pad,
  output wire rx_bit
);
  reg rx_ff1, rx_ff2;
  always @(posedge clk) begin
    rx_ff1 <= serial_pad;
    rx_ff2 <= rx_ff1;
  end
  assign rx_bit = rx_ff2;
  assign serial_pad = 1'bz;
endmodule
"""


def test_noncompliant_pad_fails_even_beside_a_compliant_one(tmp_path):
    """DIRECTION 1 — the FAIL verdict is reachable.

    Fails against the unfixed program, which returns 0 and prints PASS
    naming aux_pad_block.sv: the longest chain in the project (3) won the
    single-verdict selection and the 2-FF pad next door was never scored.
    """
    _write_rtl(tmp_path, "aux_pad_block.sv", _COMPLIANT_PAD)
    _write_rtl(tmp_path, "bus_wrapper.sv", _TWO_FF_PAD)

    r, rep = _run_json(tmp_path)

    assert r.returncode == 1, r.stdout
    assert rep["passed"] is False
    assert len(rep["failures"]) == 1, rep["failures"]
    assert "RX_SYNC_CHAIN_TOO_SHORT" in rep["failures"][0]
    assert "bus_wrapper.sv" in rep["failures"][0]

    # The compliant pad is still scored and still credited — the gate got
    # stricter about the worst path, it did not go blind to the good one.
    verdicts = {p["wrapper_file"].split("/")[-1]: p["verdict"]
                for p in rep["summary"]["rx_paths"]}
    assert verdicts == {"aux_pad_block.sv": "PASS",
                        "bus_wrapper.sv": "FAIL"}, verdicts


def test_all_compliant_rx_paths_still_pass(tmp_path):
    """DIRECTION 2 — the PASS verdict is still reachable.

    Two pads, both with 3 stages and a vote. Worst-of aggregation must
    still be able to say PASS, otherwise the gate would just be an
    always-FAIL dressed up as a fix.
    """
    _write_rtl(tmp_path, "aux_pad_block.sv", _COMPLIANT_PAD)
    _write_rtl(tmp_path, "alt_pad_block.sv", _COMPLIANT_PAD_2)

    r, rep = _run_json(tmp_path)

    assert r.returncode == 0, r.stdout
    assert rep["passed"] is True
    assert rep["failures"] == []
    assert rep["warnings"] == []
    assert "PASS" in r.stdout
    paths = rep["summary"]["rx_paths"]
    assert len(paths) == 2, paths
    assert {p["verdict"] for p in paths} == {"PASS"}, paths


def test_warn_path_beside_a_compliant_path_stays_warn_not_fail(tmp_path):
    """The middle verdict survives worst-of: a 3-stage chain with no vote
    is still non-blocking (rc 0) even though it is now the governing path.
    """
    _write_rtl(tmp_path, "aux_pad_block.sv", _COMPLIANT_PAD)
    _write_rtl(
        tmp_path,
        "slow_pad_block.sv",
        """
module slow_pad_block(
  input  wire clk,
  inout  wire slow_pad,
  output wire slow_bit
);
  reg c1, c2, c3;
  always @(posedge clk) begin
    c1 <= slow_pad;
    c2 <= c1;
    c3 <= c2;
  end
  assign slow_bit = c3;
  assign slow_pad = 1'bz;
endmodule
""",
    )

    r, rep = _run_json(tmp_path)

    assert r.returncode == 0, r.stdout
    assert rep["failures"] == []
    assert len(rep["warnings"]) == 1, rep["warnings"]
    assert "RX_DEGLITCH_FILTER_MISSING" in rep["warnings"][0]
    assert rep["summary"]["verdict"] == "WARN"


def test_generic_input_port_does_not_mint_a_failure(tmp_path):
    """Blast-radius guard. Worst-of scores the pads this gate names, not
    every `*_in` port that happens to feed two flops: a config input with
    a 2-deep register chain must not turn a compliant wrapper red.
    """
    _write_rtl(
        tmp_path,
        "wrapper_top.sv",
        """
module wrapper_top(
  input  wire clk,
  input  wire cfg_in,
  inout  wire serial_pad,
  output wire rx_stable
);
  reg s1, s2, s3;
  always @(posedge clk) begin
    s1 <= serial_pad;
    s2 <= s1;
    s3 <= s2;
  end
  assign rx_stable = s3 & s2;
  reg cfg_r1, cfg_r2;
  always @(posedge clk) begin
    cfg_r1 <= cfg_in;
    cfg_r2 <= cfg_r1;
  end
  assign serial_pad = 1'bz;
endmodule
""",
    )

    r, rep = _run_json(tmp_path)

    assert r.returncode == 0, r.stdout
    assert rep["failures"] == []
    paths = rep["summary"]["rx_paths"]
    assert [p["rx_seed"] for p in paths] == ["serial_pad"], paths
    assert paths[0]["seed_route"] == "inout_pad"
