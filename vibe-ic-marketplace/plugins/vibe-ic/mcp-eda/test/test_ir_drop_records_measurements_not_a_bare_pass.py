#!/usr/bin/env python3
"""The ir_drop step must record measurements, and a PASS without them is INCONCLUSIVE.

THE MEASURED BUG. src/lib/manifest_metrics.mjs declared REQUIRED_METRICS for
sta, sta_mcorner, synthesis, place_and_route, gds_generation, dft, cocotb,
extraction and drc — and had NO entry for `ir_drop`. gateManifestEntry returns
early on an undeclared step (`if (!specs) return []`), so index.js wrote

    writeManifest(dir, {step:"ir_drop", status:"PASS", tool:"OpenROAD PSM"})

— a bare PASS with zero measurements, permanently. That file's own doctrine says
silence means "no metric has been declared for this step yet", never "this step
is exempt", so this was an undeclared hole in the gate built for exactly this
failure.

AND THERE WAS NOTHING TO RECORD. OpenROAD PSM prints seven numbers:

    Total power      : 3.50e-05 W
    Supply voltage   : 1.80e+00 V
    Worstcase voltage: 1.80e+00 V
    Average voltage  : 1.80e+00 V
    Average IR drop  : 8.95e-06 V
    Worstcase IR drop: 2.25e-05 V
    Percentage drop  : 0.00 %

eda_ir_drop parsed NONE of them. Its only regexes were two advisory
instance-count probes; every other check was a substring test for a marker the
MCP had echoed itself. `grep -c "report_power" src/index.js` was 0. The P of PPA
was emitted by the tool, sat in the log, and was discarded.

Every one of those values is in scientific notation, so lib/psm_report.mjs is
whole-line anchored and exponent-aware — a naive `([\\d.]+)` reads `3.50` out of
`3.50e-05 W` and delivers a 10^5 error as a confident number.

FALSIFIED (192.168.1.121, sky130A, OpenROAD 26Q3-1887-g24ea077e76):
  measured run   pdn_pnr.def -> success:true, measured:true,
                 total_power_w 2.63e-05, worst_ir_drop_v 1.65e-05 -> manifest PASS
  caught PSM err mcp_pnr.def -> measured:false, numbers null, and a reason saying
                 PSM raised a connectivity error so no IR report was produced
  the bare entry main used to write -> INCONCLUSIVE, missing_metrics
                 [worst_ir_drop_v, total_power_w]
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


def _tool(name: str) -> str:
    """The whole tool body: from its name to the next server.tool( registration."""
    i = SRC.find(f'"{name}"')
    assert i > 0, f"tool {name} not found"
    j = SRC.find("server.tool(", i)
    return SRC[i:j if j > 0 else len(SRC)]


def test_ir_drop_has_a_required_metrics_entry():
    m = re.search(r"^\s*ir_drop:\s*\[([^\]]*)\]", METRICS, re.M)
    assert m, (
        "REQUIRED_METRICS has no ir_drop entry — gateManifestEntry returns early "
        "and a bare PASS with zero measurements is recorded permanently"
    )
    keys = re.findall(r'key:\s*"(\w+)"', m.group(1))
    assert "worst_ir_drop_v" in keys, f"ir_drop requires {keys}, not its namesake quantity"
    assert "total_power_w" in keys, f"ir_drop requires {keys}, not the power number"


def test_ir_drop_parses_the_psm_report_instead_of_echoing_markers():
    t = _tool("eda_ir_drop")
    assert "parseIrReport(result.output)" in t, "the PSM report is still not parsed"
    assert "measured: irMeasured" in t
    assert "not_measured_reason" in t
    # the numbers reach both the response and the manifest
    assert t.count("...ir,") >= 2, "the parsed metrics do not reach both the response and the manifest"


@pytest.mark.skipif(_NODE is None, reason="node not installed")
def test_the_gate_turns_main_s_own_bare_entry_into_inconclusive():
    """The falsifier uses the EXACT entry index.js wrote on c0b66577e."""
    script = """
import { gateManifestEntry } from "%s";
const out = {
  bare:      gateManifestEntry({step:"ir_drop", status:"PASS", tool:"OpenROAD PSM"}),
  truncated: gateManifestEntry({step:"ir_drop", status:"PASS", tool:"OpenROAD PSM",
                                net:"VDD", total_power_w:null, worst_ir_drop_v:null}),
  measured:  gateManifestEntry({step:"ir_drop", status:"PASS", tool:"OpenROAD PSM",
                                net:"VDD", total_power_w:2.63e-05, worst_ir_drop_v:1.65e-05}),
  zero:      gateManifestEntry({step:"ir_drop", status:"PASS", tool:"OpenROAD PSM",
                                net:"VDD", total_power_w:0, worst_ir_drop_v:0}),
};
console.log(JSON.stringify(out));
""" % METRICS_MJS.as_posix()
    r = subprocess.run([_NODE, "--input-type=module", "-e", script],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)

    # a PASS that measured nothing is not a PASS
    assert out["bare"]["status"] == "INCONCLUSIVE", out["bare"]
    assert set(out["bare"]["missing_metrics"]) == {"worst_ir_drop_v", "total_power_w"}
    assert out["truncated"]["status"] == "INCONCLUSIVE", out["truncated"]
    # a run that DID measure keeps its PASS — the gate must not just fail everything
    assert out["measured"]["status"] == "PASS", out["measured"]
    # and a measured ZERO is a measurement, not an absence
    assert out["zero"]["status"] == "PASS", out["zero"]
