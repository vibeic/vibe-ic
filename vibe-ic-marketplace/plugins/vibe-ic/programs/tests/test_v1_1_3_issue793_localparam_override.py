"""ORGANIC #793 — latency_conformance_check crashed (rc=2 "Cannot override
localparam") when a module declares a derived `localparam` INSIDE its `#(...)`
parameter port list.

CVDP round-10 blind: crossbar_switch_0001. The shared parse_module_params bare
`(\\w+)=` capture grabs localparam names; build_measurement_tb emitted
`#(.NAME(VAL))` for ALL resolved names incl localparams → iverilog forbids
overriding a localparam → elaboration crash on functionally-correct RTL before
any latency measurement.

FIX: module_localparam_names() tags the localparam names; build_measurement_tb's
override list excludes exactly those, while their resolved VALUES stay in the
params map (net-width substitution + --expect arithmetic). §4.05 no-leak: a
header with no localparams is byte-for-byte unchanged; genuine latency
mismatches still hard-block.

chip-AGNOSTIC: SV param-port grammar; no chip literal.
"""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import latency_conformance_check as L  # noqa: E402

_IV = shutil.which("iverilog") and shutil.which("vvp")

_RTL = """\
module crossbar_switch #(parameter WIDTH=8, localparam DEPTH=4,
                         localparam TOTAL=WIDTH*DEPTH) (
  input clk, input rst_n, input start, output reg done
);
  always @(posedge clk or negedge rst_n)
    if(!rst_n) done<=1'b0; else done<=start;
endmodule
"""

# a genuine 2-cycle variant (§4.05 no-leak: must still MISMATCH vs --expect 1).
_RTL_2CYC = """\
module crossbar_switch #(parameter WIDTH=8, localparam DEPTH=4,
                         localparam TOTAL=WIDTH*DEPTH) (
  input clk, input rst_n, input start, output reg done
);
  reg s1;
  always @(posedge clk or negedge rst_n)
    if(!rst_n) begin s1<=0; done<=0; end
    else begin s1<=start; done<=s1; end
endmodule
"""


# ── UNIT: localparam tagging + override exclusion ───────────────────────────
def test_793_module_localparam_names_tags_localparams():
    names = L.module_localparam_names(_RTL, "crossbar_switch")
    assert names == {"DEPTH", "TOTAL"}


def test_793_resolve_params_keeps_localparam_values():
    # the VALUE must remain in the map (widths + --expect arithmetic).
    p = L.resolve_params(_RTL, "crossbar_switch", {})
    assert p.get("WIDTH") == 8 and p.get("DEPTH") == 4 and p.get("TOTAL") == 32


def test_793_tb_excludes_localparams_from_override_but_keeps_param():
    from latency_conformance_check import PortInfo
    params = {"WIDTH": 8, "DEPTH": 4, "TOTAL": 32}
    clk = PortInfo("clk", "input", "", "")
    rst = PortInfo("rst_n", "input", "", "")
    ev = PortInfo("start", "input", "", "")
    out = PortInfo("done", "output", "", "")
    # OLD behavior (no localparam exclusion) WOULD override the localparam.
    old = L.build_measurement_tb("crossbar_switch", clk, [rst], ev, out, [],
                                 {"rst_n": True}, -1, 64, params=params)
    assert ".DEPTH(" in old and ".TOTAL(" in old        # the crash trigger
    # FIXED: localparams excluded; the REAL parameter WIDTH still overridden.
    new = L.build_measurement_tb("crossbar_switch", clk, [rst], ev, out, [],
                                 {"rst_n": True}, -1, 64, params=params,
                                 localparams={"DEPTH", "TOTAL"})
    assert ".DEPTH(" not in new and ".TOTAL(" not in new
    assert ".WIDTH(8)" in new


# ── END-TO-END: the affected shape no longer crashes; no-leak still blocks ──
def _run(tmp_path, rtl, expect):
    f = tmp_path / "crossbar_switch.v"
    f.write_text(rtl)
    jp = tmp_path / "r.json"
    r = subprocess.run(
        [sys.executable, str(PROGRAMS / "latency_conformance_check.py"),
         "--rtl", str(f), "--top", "crossbar_switch", "--event", "start",
         "--output", "done", "--expect", str(expect), "--json", str(jp)],
        capture_output=True, text=True)
    import json
    return r.returncode, json.loads(jp.read_text())


@pytest.mark.skipif(not _IV, reason="iverilog/vvp unavailable")
def test_793_endtoend_localparam_no_longer_crashes(tmp_path):
    rc, rep = _run(tmp_path, _RTL, 1)
    assert rc == 0, rep            # was rc=2 "Cannot override localparam"
    assert rep["verdict"] == "PASS"
    assert rep.get("localparams") == ["DEPTH", "TOTAL"]


@pytest.mark.skipif(not _IV, reason="iverilog/vvp unavailable")
def test_793_noleak_genuine_2cycle_still_mismatches(tmp_path):
    rc, rep = _run(tmp_path, _RTL_2CYC, 1)
    assert rc == 1, rep           # genuine 2-cycle vs expect 1 still hard-blocks
    assert rep["verdict"] == "MISMATCH"


@pytest.mark.skipif(not _IV, reason="iverilog/vvp unavailable")
def test_793_noleak_genuine_2cycle_passes_vs_expect2(tmp_path):
    rc, rep = _run(tmp_path, _RTL_2CYC, 2)
    assert rc == 0, rep           # the real latency (2) is faithfully measured


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
