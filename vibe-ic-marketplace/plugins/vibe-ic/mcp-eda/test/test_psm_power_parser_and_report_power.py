#!/usr/bin/env python3
"""The power number is in scientific notation, and nobody ran report_power.

TWO FINDINGS, ONE FILE.

(1) `grep -c "report_power" src/index.js` was 0. No eda MCP tool anywhere ran
    OpenSTA's report_power. The P of PPA was never even asked for.

(2) Every number PSM prints is in scientific notation:

        Total power      : 3.50e-05 W

    A naive `([\\d.]+)` capture reads `3.50` and drops `e-05` — a 10^5 error
    arriving as a confident number, which is the exact "W read as mW" hazard.
    MEASURED here: the naive regex returns 3.5 where the truth is 3.5e-05.

lib/psm_report.mjs is whole-line anchored and exponent-aware, the shape
lib/sta_slack.mjs already uses. A number that is not printed is null, and null
means NOT MEASURED — never zero, never a truncated mantissa.

report_power is run OUTSIDE the power-net branch, so the design's power is
measured even when the PSM grid analysis cannot complete. MEASURED live: on a
DEF whose PDN is not connected enough for PSM (status NOT_MEASURED, no IR
number), report_power still returned total 2.63e-05 W with its
internal/switching/leakage split. Verified to work with no clock defined
(rc=0), which this tool cannot supply.

Having two INDEPENDENT power numbers makes a real cross-check possible, which is
what the review found missing everywhere: PSM's "Total power" and report_power's
Total row are compared, and disagreement beyond 1% is reported rather than
silently reconciled. MEASURED live: 2.63e-05 vs 2.63e-05, agree:true.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

MCP_ROOT = Path(__file__).resolve().parents[1]
SRC = (MCP_ROOT / "src" / "index.js").read_text()
PSM_MJS = MCP_ROOT / "src" / "lib" / "psm_report.mjs"
_NODE = shutil.which("node")

REAL_IR = """########## IR report #################
Net              : VDD
Corner           : default
Total power      : 3.50e-05 W
Supply voltage   : 1.80e+00 V
Worstcase voltage: 1.80e+00 V
Average voltage  : 1.80e+00 V
Average IR drop  : 8.95e-06 V
Worstcase IR drop: 2.25e-05 V
Percentage drop  : 0.00 %
######################################"""

REAL_RP = "Total                  2.30e-05   3.32e-06   1.14e-10   2.63e-05 100.0%"


def test_report_power_is_actually_run():
    assert "report_power" in SRC, "no tool runs report_power — the P of PPA is never asked for"
    i = SRC.find('"eda_ir_drop"')
    j = SRC.find("server.tool(", i)
    t = SRC[i:j]
    assert "catch {report_power}" in t, "report_power is not run, or not run defensively"
    assert "REPORT_POWER_BEGIN" in t
    # run OUTSIDE the power-net branch: power and IR drop are different
    # measurements and only one needs a resolvable PDN
    assert t.index("catch {report_power}") < t.index('if {$_vddnet eq ""}'), (
        "report_power is inside the power-net branch, so a design whose PDN "
        "cannot be resolved reports no power either"
    )


def test_the_two_power_numbers_are_cross_checked():
    i = SRC.find('"eda_ir_drop"')
    j = SRC.find("server.tool(", i)
    t = SRC[i:j]
    assert "powerCrossCheck" in t
    assert "power_cross_check" in t
    assert "The two power numbers disagree" in t


@pytest.mark.skipif(_NODE is None, reason="node not installed")
def test_the_parser_keeps_the_exponent_and_refuses_a_degraded_report():
    script = """
import { parseIrReport, parseReportPower } from "@PSM@";
const REAL = @REAL@;
const RP = @RP@;
const naive = (s) => { const m = s.match(/Total power\\s*:\\s*([\\d.]+)/); return m ? parseFloat(m[1]) : null; };
console.log(JSON.stringify({
  naive:    naive(REAL),
  parsed:   parseIrReport(REAL),
  rp:       parseReportPower(RP),
  plants: {
    truncatedNumber: parseIrReport(REAL.replace("3.50e-05 W", "3.50e-")).total_power_w,
    exponentGone:    parseIrReport(REAL.replace("3.50e-05 W", "W")).total_power_w,
    headerOnly:      parseIrReport(REAL.split("Total power")[0]).total_power_w,
    valueIsAWord:    parseIrReport(REAL.replace("3.50e-05", "NaN")).total_power_w,
    prose:           parseIrReport("Total power : could not be determined").total_power_w,
    splitLines:      parseIrReport(REAL.replace("Total power      : 3.50e-05 W",
                                                "Total power      :\\n3.50e-05 W")).total_power_w,
    empty:           parseIrReport("").total_power_w,
    rpTruncated:     parseReportPower("Total                  2.30e-05   3.32e-06"),
  },
}));
"""
    script = (script.replace("@PSM@", PSM_MJS.as_posix())
                    .replace("@REAL@", json.dumps(REAL_IR))
                    .replace("@RP@", json.dumps(REAL_RP)))
    r = subprocess.run([_NODE, "--input-type=module", "-e", script],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    o = json.loads(r.stdout)

    # THE HAZARD, demonstrated: the naive capture is wrong by 10^5
    assert o["naive"] == 3.5, o["naive"]
    assert o["parsed"]["total_power_w"] == 3.5e-05, o["parsed"]

    # the good report parses in full, every field
    assert o["parsed"] == {
        "total_power_w": 3.5e-05, "supply_voltage_v": 1.8,
        "worstcase_voltage_v": 1.8, "average_voltage_v": 1.8,
        "average_ir_drop_v": 8.95e-06, "worst_ir_drop_v": 2.25e-05,
        "percentage_drop_pct": 0.0,
    }, o["parsed"]
    # "Worstcase voltage" and "Worstcase IR drop" share a prefix and must not
    # be confused for one another
    assert o["parsed"]["worstcase_voltage_v"] != o["parsed"]["worst_ir_drop_v"]

    assert o["rp"] == {"internal_w": 2.30e-05, "switching_w": 3.32e-06,
                       "leakage_w": 1.14e-10, "total_w": 2.63e-05}, o["rp"]

    # EVERY degraded report yields NO number rather than a plausible one
    for name, v in o["plants"].items():
        assert v is None, f"a degraded report produced a number: {name} -> {v}"
