#!/usr/bin/env python3
"""A place_and_route PASS with no area is INCONCLUSIVE, like one with no slack.

REQUIRED_METRICS.place_and_route declared `slack_ns` and `timing_met` and NOT
`area_um2`. eda_pnr's own verdict is `success: complete && !hasZeroNet`, which
does not mention area either. So an area that failed to parse reached the
manifest as `status:"PASS", area_um2:null` and the INCONCLUSIVE gate — which
exists precisely to stop an unmeasured run being recorded as proven — let it
through. The TIMING half of that manifest entry was protected; the AREA half was
not, and area is half of what place_and_route exists to report.

Both numbers come from the same `report_design_area` line, so absent means that
line was never printed:

    Design area 269 um^2 43% utilization.

The parse was also lossy. `/Design area (\\d+)/` with parseInt reads 269 out of
`Design area 269.53` — it truncates a decimal and cannot see an exponent at all,
the same silent-magnitude hazard the PSM power number carries. Now whole-line
anchored, decimal- and exponent-aware, verified to read the real emit identically
(269 / 43).
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

MCP_ROOT = Path(__file__).resolve().parents[1]
SRC = (MCP_ROOT / "src" / "index.js").read_text()
METRICS_MJS = MCP_ROOT / "src" / "lib" / "manifest_metrics.mjs"
METRICS = METRICS_MJS.read_text()
_NODE = shutil.which("node")


def test_place_and_route_requires_area_as_well_as_timing():
    m = re.search(r"place_and_route:\s*\[(.*?)\]", METRICS, re.S)
    assert m, "place_and_route has no REQUIRED_METRICS entry"
    keys = re.findall(r'key:\s*"(\w+)"', m.group(1))
    for k in ("slack_ns", "timing_met"):
        assert k in keys, f"the timing requirement was dropped: {keys}"
    assert "area_um2" in keys, (
        f"place_and_route requires {keys} — the timing half is protected and the "
        f"area half is not, so a null area keeps its PASS"
    )
    assert "utilization_pct" in keys, keys


def test_the_area_parse_does_not_truncate_or_miss_an_exponent():
    i = SRC.find('"eda_pnr"')
    j = SRC.find("server.tool(", i)
    t = SRC[i:j]
    m = re.search(r"const areaMatch = pnrRun\.output\.match\((.*?)\);", t, re.S)
    assert m, "eda_pnr no longer assigns areaMatch"
    pattern = m.group(1)
    assert "\\d+)/" not in pattern.replace("\\d+\\.?\\d*", ""), (
        f"the truncating area regex is back: {pattern.strip()}")
    assert "[eE]" in pattern, f"the area regex cannot see an exponent: {pattern.strip()}"
    assert "parseInt(areaMatch[1])" not in t, "parseInt truncates a decimal area"
    assert "parseFloat(areaMatch[1])" in t


@pytest.mark.skipif(_NODE is None, reason="node not installed")
def test_the_gate_and_the_regex_behave_on_real_and_degraded_input():
    script = """
import { gateManifestEntry } from "@METRICS@";
const areaRe = /^[ \\t]*Design area[ \\t]+([-+]?(?:\\d+\\.?\\d*|\\.\\d+)(?:[eE][-+]?\\d+)?)[ \\t]*u/mi;
const utilRe = /([-+]?(?:\\d+\\.?\\d*|\\.\\d+)(?:[eE][-+]?\\d+)?)[ \\t]*% utilization/i;
const rd = (s) => { const a = s.match(areaRe), u = s.match(utilRe);
  return {area: a ? parseFloat(a[1]) : null, util: u ? parseFloat(u[1]) : null}; };
const mk = (o) => gateManifestEntry({step:"place_and_route", status:"PASS", tool:"OpenROAD", ...o});
console.log(JSON.stringify({
  nullArea: mk({slack_ns:8.88, timing_met:true, area_um2:null, utilization_pct:null}),
  measured: mk({slack_ns:8.88, timing_met:true, area_um2:269, utilization_pct:43}),
  nullSlack: mk({slack_ns:null, timing_met:null, area_um2:269, utilization_pct:43}),
  real:     rd("Design area 269 um^2 43% utilization."),
  decimal:  rd("Design area 269.53 um^2 43.7% utilization."),
  exponent: rd("Design area 2.6953e+02 um^2 43% utilization."),
  prose:    rd("Design area could not be computed"),
}));
""".replace("@METRICS@", METRICS_MJS.as_posix())
    r = subprocess.run([_NODE, "--input-type=module", "-e", script],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    o = json.loads(r.stdout)

    # a PASS whose area was never measured is not a PASS
    assert o["nullArea"]["status"] == "INCONCLUSIVE", o["nullArea"]
    assert set(o["nullArea"]["missing_metrics"]) == {"area_um2", "utilization_pct"}
    # the timing half must still be protected
    assert o["nullSlack"]["status"] == "INCONCLUSIVE", o["nullSlack"]
    # a fully measured run keeps its PASS
    assert o["measured"]["status"] == "PASS", o["measured"]

    # the real emit reads exactly as before the widening — no behaviour change
    assert o["real"] == {"area": 269, "util": 43}, o["real"]
    # and the cases the old regex got silently wrong now read correctly
    assert o["decimal"] == {"area": 269.53, "util": 43.7}, o["decimal"]
    assert o["exponent"]["area"] == 269.53, o["exponent"]
    # prose is not a measurement
    assert o["prose"] == {"area": None, "util": None}, o["prose"]
