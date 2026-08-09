#!/usr/bin/env python3
"""Tests for analog_netlist_connectivity_check.py."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / "analog_netlist_connectivity_check.py"

# Every internal net (gate, tail) touched by >=2 pins; all ports used.
GOOD = """\
* current mirror — well connected
.subckt mirror vin vout vdd vss
XMP1 vout gate vdd vdd pfet_03v3 W=20u L=4u
XMP2 gate gate vdd vdd pfet_03v3 W=20u L=4u
XMN1 gate vin vss vss nfet_03v3 W=10u L=2u
XMN2 vout vin vss vss nfet_03v3 W=10u L=2u
.ends
"""

# 'orphan' net touched by exactly one device pin (drain of XMN2), internal.
FLOATING = """\
* floating internal node 'orphan'
.subckt bad vin vout vdd vss
XMP1 vout gate vdd vdd pfet_03v3 W=20u L=4u
XMP2 gate gate vdd vdd pfet_03v3 W=20u L=4u
XMN1 gate vin vss vss nfet_03v3 W=10u L=2u
XMN2 orphan vin vss vss nfet_03v3 W=10u L=2u
.ends
"""

# declared port 'enable' never used by any device.
UNUSED_PORT = """\
* unused declared port 'enable'
.subckt bad2 vin vout enable vdd vss
XMP1 vout gate vdd vdd pfet_03v3 W=20u L=4u
XMN1 gate vin vss vss nfet_03v3 W=10u L=2u
XMN2 vout vin vss vss nfet_03v3 W=10u L=2u
.ends
"""

NO_SUBCKT = """\
* just a stimulus file, no subckt
Vdd vdd 0 DC 3.3
Vin in 0 DC 1.65
.end
"""

# The exact shape the only shipped caller stages next to a block deck: a
# testbench that `.include`s the block and declares no `.subckt` of its own.
TESTBENCH = """\
* testbench — includes the block, declares no subckt
.include blk.sp
Vdd vdd 0 DC 3.3
xdut vin vout vdd vss mirror
.control
tran 1n 1u
.endc
.end
"""

VACUOUS_SENTINEL = "VACUOUS_PASS:"


def _run(tmp_path: Path):
    return subprocess.run(
        [sys.executable, str(PROG), str(tmp_path),
         "--json", str(tmp_path / "r.json")],
        capture_output=True, text=True)


def _write(tmp_path: Path, name: str, content: str):
    d = tmp_path / "analog" / "blk"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(content)


def test_pass_well_connected(tmp_path):
    _write(tmp_path, "blk.sp", GOOD)
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    rep = json.loads((tmp_path / "r.json").read_text())
    assert rep["passed"] is True
    assert rep["summary"]["files_with_subckt"] == 1


def test_fail_floating_node(tmp_path):
    _write(tmp_path, "blk.sp", FLOATING)
    r = _run(tmp_path)
    assert r.returncode == 1
    rep = json.loads((tmp_path / "r.json").read_text())
    assert rep["passed"] is False
    floats = [f for f in rep["findings"] if f["rule"] == "FLOATING_NODE"]
    assert floats and any(f["net"] == "orphan" for f in floats)


def test_fail_unused_port(tmp_path):
    _write(tmp_path, "blk.sp", UNUSED_PORT)
    r = _run(tmp_path)
    assert r.returncode == 1
    rep = json.loads((tmp_path / "r.json").read_text())
    rules = {f["rule"] for f in rep["findings"]}
    assert "UNUSED_PORT" in rules
    assert any(f.get("net") == "enable" for f in rep["findings"])


def test_edge_missing_dir_exit2(tmp_path):
    r = subprocess.run(
        [sys.executable, str(PROG), str(tmp_path / "nope")],
        capture_output=True, text=True)
    assert r.returncode == 2


# ══ the two verdicts that were structurally unreachable ════════════════════
# Both of these FAIL against the pre-fix program, which answered rc 0 / a
# plain [PASS] to each. Everything asserted below is a returned exit code or a
# field of the emitted JSON report — nothing reads the source.

def test_sp_read_but_no_subckt_built_reaches_the_vacuous_tier(tmp_path):
    """A run that opened decks and built ZERO connectivity graphs examined
    nothing. Pre-fix it exited 0 in the PLAIN pass tier: `skipped` answered
    "were there files?", never "was a graph built?"."""
    _write(tmp_path, "stim.sp", NO_SUBCKT)
    r = _run(tmp_path)
    assert r.returncode == 2, (r.returncode, r.stdout, r.stderr)
    rep = json.loads((tmp_path / "r.json").read_text())
    assert rep["summary"]["skipped"] is True
    assert rep["summary"]["reason"] == "no_subckt_in_any_sp"
    assert rep["summary"]["files_checked"] == 1
    assert rep["summary"]["files_with_subckt"] == 0
    rules = {f["rule"] for f in rep["findings"]}
    assert "NO_SUBCKT" in rules and "NO_CONNECTIVITY_GRAPH" in rules
    # the rc-independent disclosure channel the vacuous tier also scans
    assert VACUOUS_SENTINEL in r.stderr


def test_project_with_no_analog_directory_can_say_so(tmp_path):
    """`no_analog_dir` was dead: the resolver ended in an unconditional
    `if project.is_dir(): return project`, and main() had already rejected the
    only input that could make that false. The project below reported
    `no_sp_files` — a reason about a directory it does not have."""
    proj = tmp_path / "digital_only"
    (proj / "phase2" / "stage1" / "rtl").mkdir(parents=True)
    (proj / "phase2" / "stage1" / "rtl" / "top.v").write_text("module t; endmodule\n")
    r = subprocess.run(
        [sys.executable, str(PROG), str(proj), "--json", str(tmp_path / "d.json")],
        capture_output=True, text=True)
    assert r.returncode == 2, (r.returncode, r.stdout, r.stderr)
    rep = json.loads((tmp_path / "d.json").read_text())
    assert rep["summary"]["skipped"] is True
    assert rep["summary"]["reason"] == "no_analog_dir"
    assert "SKIP_NO_ANALOG_DIR" in {f["rule"] for f in rep["findings"]}


# ══ the other direction — the gate did not become always-vacuous ═══════════

def test_clean_graph_beside_a_subcktless_testbench_still_plain_passes(tmp_path):
    """The exact tree the only shipped caller stages (block deck + its
    testbench). One real graph is enough: vacuity is a property of the RUN,
    not of every file in it. Without this, the netlist producer would delete
    every correct deck it emits."""
    _write(tmp_path, "blk.sp", GOOD)
    _write(tmp_path, "tb_blk.sp", TESTBENCH)
    r = _run(tmp_path)
    assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)
    rep = json.loads((tmp_path / "r.json").read_text())
    assert rep["passed"] is True
    assert rep["summary"]["skipped"] is False
    assert rep["summary"]["files_checked"] == 2
    assert rep["summary"]["files_with_subckt"] == 1
    assert VACUOUS_SENTINEL not in r.stderr
    assert "NO_CONNECTIVITY_GRAPH" not in {f["rule"] for f in rep["findings"]}


def test_floating_node_beside_a_subcktless_testbench_still_fails(tmp_path):
    """FAIL still beats VACUOUS: a real defect is not silenced by a
    subckt-free file sitting next to it."""
    _write(tmp_path, "blk.sp", FLOATING)
    _write(tmp_path, "tb_blk.sp", TESTBENCH)
    r = _run(tmp_path)
    assert r.returncode == 1, (r.returncode, r.stdout, r.stderr)
    rep = json.loads((tmp_path / "r.json").read_text())
    assert rep["passed"] is False
    assert rep["summary"]["skipped"] is False
    assert any(f["rule"] == "FLOATING_NODE" and f["net"] == "orphan"
               for f in rep["findings"])


def test_analog_dir_present_but_empty_still_says_no_sp_files(tmp_path):
    """The evidence-based resolver must not swallow the OTHER skip reason:
    an analog directory that exists and holds no deck is `no_sp_files`."""
    (tmp_path / "phase3" / "analog").mkdir(parents=True)
    r = subprocess.run(
        [sys.executable, str(PROG), str(tmp_path), "--json", str(tmp_path / "e.json")],
        capture_output=True, text=True)
    assert r.returncode == 2, (r.returncode, r.stdout, r.stderr)
    rep = json.loads((tmp_path / "e.json").read_text())
    assert rep["summary"]["reason"] == "no_sp_files"
