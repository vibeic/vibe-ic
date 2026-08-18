"""Tests for arch_dse_pareto.py -- 4 PPA formulas + Pareto dominance filter.

Good fixture: a small knob set with a KNOWN Pareto frontier (hand-computed).
Bad fixtures: malformed / empty / partial input that must degrade gracefully
(report MISSING / SKIP, never crash or over-flag).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / "arch_dse_pareto.py"


def _run(args, stdin_text=None):
    r = subprocess.run(
        [sys.executable, str(PROG), *args],
        input=stdin_text, capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr


def _run_json(args, stdin_text=None):
    code, out, err = _run(args, stdin_text)
    return code, json.loads(out), err


# ---------------------------------------------------------------------------
# Good fixture with a hand-computed Pareto frontier.
#
# Throughput = parallelism * frequency_mhz
# Area       = Sum(count * unit_area) + memory_bits * bit_area
# Power      = activity * cap * vdd^2 * frequency_mhz
# Latency    = depth * (1000 / frequency_mhz)
#
# A_serial : T=500   A=1000  P=0.2*1*0.81*500=81   L=2*2=4
# B_par2   : T=1000  A=2000  P=0.2*2*0.81*500=162  L=4
# C_par4   : T=2000  A=4000  P=0.2*4*0.81*500=324  L=4
# D_dom    : T=400   A=2000  P=0.3*2*1*400=240     L=4*2.5=10
#
# A,B,C form a throughput<->(area,power) trade -> all Pareto.
# D is dominated by A (and B): A has higher T, lower A, lower P, lower L.
# Expected frontier = {A_serial, B_par2, C_par4}.
# ---------------------------------------------------------------------------
GOOD = [
    {"name": "A_serial", "parallelism": 1, "frequency_mhz": 500, "depth": 2,
     "units": [{"count": 1, "unit_area": 1000}],
     "activity": 0.2, "cap": 1.0, "vdd": 0.9},
    {"name": "B_par2", "parallelism": 2, "frequency_mhz": 500, "depth": 2,
     "units": [{"count": 2, "unit_area": 1000}],
     "activity": 0.2, "cap": 2.0, "vdd": 0.9},
    {"name": "C_par4", "parallelism": 4, "frequency_mhz": 500, "depth": 2,
     "units": [{"count": 4, "unit_area": 1000}],
     "activity": 0.2, "cap": 4.0, "vdd": 0.9},
    {"name": "D_dominated", "parallelism": 1, "frequency_mhz": 400, "depth": 4,
     "units": [{"count": 2, "unit_area": 1000}],
     "activity": 0.3, "cap": 2.0, "vdd": 1.0},
]


def _write(tmp_path, obj, name="knobs.json"):
    p = tmp_path / name
    p.write_text(json.dumps(obj))
    return str(p)


def test_help_works():
    code, out, _ = _run(["--help"])
    assert code == 0
    assert "Pareto" in out or "DSE" in out


def test_known_pareto_frontier(tmp_path):
    code, data, _ = _run_json([_write(tmp_path, GOOD)])
    assert code == 0
    assert data["status"] == "OK"
    assert set(data["pareto_frontier"]) == {"A_serial", "B_par2", "C_par4"}
    assert data["num_pareto"] == 3
    assert data["num_candidates"] == 4


def test_formulas_exact(tmp_path):
    """The four formulas must produce exactly the hand-computed numbers."""
    code, data, _ = _run_json([_write(tmp_path, GOOD)])
    by = {c["name"]: c for c in data["candidates"]}
    a = by["A_serial"]
    assert a["throughput"] == 500.0        # 1 * 500
    assert a["area"] == 1000.0             # 1 * 1000
    assert abs(a["power"] - 81.0) < 1e-6   # 0.2 * 1 * 0.81 * 500
    assert abs(a["latency"] - 4.0) < 1e-6  # 2 * (1000/500)
    d = by["D_dominated"]
    assert abs(d["latency"] - 10.0) < 1e-6  # 4 * (1000/400)
    assert abs(d["power"] - 240.0) < 1e-6   # 0.3 * 2 * 1.0 * 400


def test_dominated_point_marked(tmp_path):
    code, data, _ = _run_json([_write(tmp_path, GOOD)])
    by = {c["name"]: c for c in data["candidates"]}
    assert by["D_dominated"]["pareto"] is False
    assert "A_serial" in by["D_dominated"]["dominated_by"]
    assert by["A_serial"]["pareto"] is True
    assert by["A_serial"]["dominated_by"] == []


def test_memory_area_term(tmp_path):
    """Area = logic units + memory_bits * bit_area."""
    spec = [{"name": "mem", "parallelism": 1, "frequency_mhz": 100,
             "units": [{"count": 1, "unit_area": 500}],
             "memory_bits": 1024, "bit_area": 0.5,
             "activity": 0.1, "cap": 1.0, "vdd": 1.0, "depth": 1}]
    code, data, _ = _run_json([_write(tmp_path, spec)])
    assert data["candidates"][0]["area"] == 500 + 1024 * 0.5  # 1012


def test_aggregate_area_units(tmp_path):
    """A pre-summed 'area_units' scalar is accepted in place of 'units'."""
    spec = [{"name": "agg", "parallelism": 1, "frequency_mhz": 100,
             "area_units": 1234.0, "depth": 1}]
    code, data, _ = _run_json([_write(tmp_path, spec)])
    assert data["candidates"][0]["area"] == 1234.0


def test_wrapper_dict_input(tmp_path):
    code, data, _ = _run_json([_write(tmp_path, {"candidates": GOOD})])
    assert data["status"] == "OK"
    assert data["num_candidates"] == 4


def test_stdin_input():
    code, data, _ = _run_json(["-"], stdin_text=json.dumps(GOOD))
    assert code == 0
    assert set(data["pareto_frontier"]) == {"A_serial", "B_par2", "C_par4"}


# ---------------------------------------------------------------------------
# Bad / degraded input -> graceful MISSING, never a crash, never over-flag.
# ---------------------------------------------------------------------------
def test_empty_list_reports_missing(tmp_path):
    code, data, _ = _run_json([_write(tmp_path, [])])
    assert code == 2
    assert data["status"] == "MISSING"
    assert data["pareto_frontier"] == []


def test_malformed_json_graceful():
    code, out, _ = _run(["-"], stdin_text="{not valid json")
    assert code == 2
    data = json.loads(out)
    assert data["status"] == "MISSING"


def test_partial_candidate_does_not_crash(tmp_path):
    """A candidate missing frequency/units must be reported, not crash."""
    spec = [{"name": "sparse"}]
    code, data, _ = _run_json([_write(tmp_path, spec)])
    assert code == 0
    c = data["candidates"][0]
    # No frequency -> throughput/latency 0, area 0, all reported.
    assert c["throughput"] == 0.0
    assert c["area"] == 0.0
    assert c["latency"] == 0.0
    # Single candidate is trivially Pareto-optimal (no one dominates it).
    assert c["pareto"] is True
    assert any("frequency" in n for n in c["notes"])


def test_junk_field_values_coerced(tmp_path):
    """Non-numeric knob values degrade to defaults, never raise."""
    spec = [{"name": "junk", "parallelism": "oops", "frequency_mhz": None,
             "units": "notalist", "activity": [], "cap": {}, "vdd": "x"}]
    code, data, _ = _run_json([_write(tmp_path, spec)])
    assert code == 0
    c = data["candidates"][0]
    assert c["area"] == 0.0
    assert c["power"] == 0.0


def test_single_candidate_is_pareto(tmp_path):
    spec = [{"name": "solo", "parallelism": 1, "frequency_mhz": 100,
             "units": [{"count": 1, "unit_area": 1}], "depth": 1}]
    code, data, _ = _run_json([_write(tmp_path, spec)])
    assert data["num_pareto"] == 1
    assert data["pareto_frontier"] == ["solo"]


def test_deterministic_repeat(tmp_path):
    """Same input -> byte-identical output across runs."""
    path = _write(tmp_path, GOOD)
    _, out1, _ = _run([path])
    _, out2, _ = _run([path])
    assert out1 == out2
