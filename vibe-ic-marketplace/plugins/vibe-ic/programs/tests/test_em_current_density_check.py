#!/usr/bin/env python3
"""Tests for em_current_density_check.py — REAL EM current-density sign-off.

Covers the four required cases:
  (a) synthetic EM report all under Jmax               → PASS
  (b) one segment over Jmax                            → FAIL (names net/layer/
                                                          density-vs-limit)
  (c) absent EM report                                 → SKIPPED, never PASS
  (d) absent Jmax table                                → SKIPPED, never PASS

Plus the tech-LEF Jmax path and the "report present but nothing maps to a
Jmax layer" §4.05 negative. rc contract: 0 PASS / 1 FAIL / 2 arg / 3 SKIPPED.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / "em_current_density_check.py"

# A per-width Jmax of 2.8 mA/um on met1 (t=0.35um) mirrors sky130 metal.
JMAX = {
    "layers": {
        "met1": {"kind": "routing", "thickness_um": 0.35, "width_um": 0.14,
                 "jmax_mA_per_um": 2.8},
        "met2": {"kind": "routing", "thickness_um": 0.35, "width_um": 0.14,
                 "jmax_A_per_um2": 8.0e-3},
        "via1": {"kind": "cut", "jmax_mA_per_cut": 0.29},
    }
}

# sky130-style tech-LEF fragment (routing + cut layers with DCCURRENTDENSITY).
TECH_LEF = """
LAYER met1
  TYPE ROUTING ;
  DIRECTION HORIZONTAL ;
  WIDTH 0.14 ;
  THICKNESS 0.35 ;
  DCCURRENTDENSITY AVERAGE 2.8 ; # mA/um Iavg_max
END met1

LAYER via1
  TYPE CUT ;
  DCCURRENTDENSITY AVERAGE 0.29 ; # mA per via
END via1
"""

CSV_HEADER = ("Node0 Layer,Node0 X location,Node0 Y location,"
              "Node1 Layer,Node1 X location,Node1 Y location,Current\n")


def _run(*args) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(PROG), *[str(a) for a in args]]
    return subprocess.run(cmd, capture_output=True, text=True)


def _write(path: Path, data) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data if isinstance(data, str) else json.dumps(data))
    return path


def _jmax(tmp_path) -> Path:
    return _write(tmp_path / "jmax.json", JMAX)


def _csv(tmp_path, rows) -> Path:
    body = CSV_HEADER + "".join(
        f"{l},0,0,{l},1,0,{c}\n" for (l, c) in rows)
    return _write(tmp_path / "em_segments.csv", body)


# --------------------------------------------------------------- (a) PASS

def test_all_under_jmax_pass(tmp_path):
    # met1 Jmax per-width = 2.8mA/um = 2.8e-3 A/um. width=0.14um →
    # limit current ~= 3.92e-4 A. Currents here are ~1e-5 A → far under.
    csv = _csv(tmp_path, [("met1", 1.0e-5), ("met1", 3.0e-5), ("met2", 2.0e-5)])
    r = _run(csv, "--jmax", _jmax(tmp_path), "--json", tmp_path / "o.json")
    assert r.returncode == 0, r.stdout
    rep = json.loads((tmp_path / "o.json").read_text())
    assert rep["verdict"] == "PASS"
    assert rep["pass"] is True
    assert rep["summary"]["segments_screened"] == 3
    assert rep["summary"]["worst_case_lifetime_ratio"] is not None


def test_all_under_jmax_pass_via_tech_lef(tmp_path):
    csv = _csv(tmp_path, [("met1", 1.0e-5), ("met1", 2.0e-5)])
    lef = _write(tmp_path / "tech.lef", TECH_LEF)
    r = _run(csv, "--tech-lef", lef, "--json", tmp_path / "o.json")
    assert r.returncode == 0, r.stdout
    rep = json.loads((tmp_path / "o.json").read_text())
    assert rep["verdict"] == "PASS"
    assert "met1" in rep["summary"]["jmax_layers"]


# --------------------------------------------------------------- (b) FAIL

def test_one_segment_over_jmax_fail(tmp_path):
    # met1 limit current ≈ 2.8e-3 * 0.14 = 3.92e-4 A. 5e-4 A is over.
    csv = _csv(tmp_path, [("met1", 1.0e-5), ("met1", 5.0e-4), ("met2", 2.0e-5)])
    r = _run(csv, "--jmax", _jmax(tmp_path), "--net", "VPWR",
             "--json", tmp_path / "o.json")
    assert r.returncode == 1, r.stdout
    rep = json.loads((tmp_path / "o.json").read_text())
    assert rep["verdict"] == "FAIL"
    assert rep["pass"] is False
    assert rep["offender_count"] >= 1
    off = rep["offenders"][0]
    # must name net + layer + density-vs-limit
    assert off["net"] == "VPWR"
    assert off["layer"] == "met1"
    assert off["utilization"] >= (1.0 - rep["margin"])
    assert off["limit"] > 0 and off["value"] >= off["limit"] * (1.0 - rep["margin"])
    msg = " ".join(f["message"] for f in rep["findings"]
                   if f["rule"] == "EM_CURRENT_DENSITY_OVER_JMAX")
    assert "met1" in msg and "VPWR" in msg and "Jmax" in msg


# ------------------------------------------- (c) §4.05: absent EM report

def test_absent_em_report_skipped_not_pass(tmp_path):
    missing = tmp_path / "does_not_exist"  # nothing discovered
    r = _run(missing, "--jmax", _jmax(tmp_path), "--json", tmp_path / "o.json")
    assert r.returncode == 3, r.stdout          # SKIPPED, never PASS
    assert r.returncode != 0
    rep = json.loads((tmp_path / "o.json").read_text())
    assert rep["verdict"] == "SKIPPED"
    assert rep["pass"] is False
    assert rep["skip_reason"] == "em_report_absent"


def test_empty_dir_em_report_skipped(tmp_path):
    empty = tmp_path / "reports"
    empty.mkdir()
    r = _run(empty, "--jmax", _jmax(tmp_path))
    assert r.returncode == 3, r.stdout
    assert '"verdict": "SKIPPED"' in r.stdout
    assert '"pass": false' in r.stdout


# ------------------------------------------- (d) §4.05: absent Jmax table

def test_absent_jmax_table_skipped_not_pass(tmp_path):
    csv = _csv(tmp_path, [("met1", 1.0e-5)])   # a real, all-under report
    r = _run(csv, "--json", tmp_path / "o.json")  # NO --jmax / --tech-lef
    assert r.returncode == 3, r.stdout          # SKIPPED (no reference), not PASS
    assert r.returncode != 0
    rep = json.loads((tmp_path / "o.json").read_text())
    assert rep["verdict"] == "SKIPPED"
    assert rep["pass"] is False
    assert rep["skip_reason"] == "jmax_reference_absent"


def test_jmax_path_missing_file_skipped(tmp_path):
    csv = _csv(tmp_path, [("met1", 1.0e-5)])
    r = _run(csv, "--jmax", tmp_path / "nope.json")
    assert r.returncode == 3, r.stdout
    assert '"verdict": "SKIPPED"' in r.stdout


def test_lef_without_current_density_skipped(tmp_path):
    csv = _csv(tmp_path, [("met1", 1.0e-5)])
    lef = _write(tmp_path / "bare.lef",
                 "LAYER met1\n  TYPE ROUTING ;\n  WIDTH 0.14 ;\nEND met1\n")
    r = _run(csv, "--tech-lef", lef)
    assert r.returncode == 3, r.stdout   # no DCCURRENTDENSITY → no reference


# --------------------------- §4.05: report+jmax present but nothing maps

def test_report_present_but_no_layer_match_skipped(tmp_path):
    # Segments only on met9, Jmax only knows met1/met2/via1 → cannot judge.
    csv = _csv(tmp_path, [("met9", 1.0e-5), ("met9", 2.0e-5)])
    r = _run(csv, "--jmax", _jmax(tmp_path), "--json", tmp_path / "o.json")
    assert r.returncode == 3, r.stdout
    rep = json.loads((tmp_path / "o.json").read_text())
    assert rep["verdict"] == "SKIPPED"
    assert rep["pass"] is False
    assert rep["skip_reason"] == "no_segment_maps_to_jmax_reference"


# --------------------------- extra: via/cut per-cut screening + JSON input

def test_via_cut_over_limit_fail_json_segments(tmp_path):
    # via1 per-cut limit = 0.29mA = 2.9e-4 A; 4e-4 A over.
    seg = _write(tmp_path / "em.json", {
        "power_nets": ["VPWR"],
        "segments": [
            {"net": "VPWR", "layer0": "met1", "layer1": "via1",
             "current_A": 4.0e-4},
        ],
    })
    r = _run(seg, "--jmax", _jmax(tmp_path), "--json", tmp_path / "o.json")
    assert r.returncode == 1, r.stdout
    rep = json.loads((tmp_path / "o.json").read_text())
    assert rep["verdict"] == "FAIL"
    assert rep["offenders"][0]["basis"] == "per_cut"


def test_margin_makes_marginal_segment_fail(tmp_path):
    # Choose a current at ~85% of Jmax; margin 0.2 requires <80% → FAIL.
    # met1 limit current = 2.8e-3 * 0.14 = 3.92e-4 A; 85% = 3.332e-4 A.
    csv = _csv(tmp_path, [("met1", 3.332e-4)])
    r = _run(csv, "--jmax", _jmax(tmp_path), "--margin", "0.2",
             "--json", tmp_path / "o.json")
    assert r.returncode == 1, r.stdout
    rep = json.loads((tmp_path / "o.json").read_text())
    assert rep["verdict"] == "FAIL"
    # same segment PASSES with margin 0.0 (still strictly under Jmax)
    r2 = _run(csv, "--jmax", _jmax(tmp_path), "--margin", "0.0")
    assert r2.returncode == 0, r2.stdout


def test_bad_margin_arg_error(tmp_path):
    csv = _csv(tmp_path, [("met1", 1.0e-5)])
    r = _run(csv, "--jmax", _jmax(tmp_path), "--margin", "1.5")
    assert r.returncode == 2


# ===========================================================================
# The per-cut verdict on the REAL report shape.
#
# The producer (OpenROAD PSM `-em_outfile`) writes a via segment as its two
# METAL endpoints and never names the cut layer, so the per-cut FAIL branch
# could not fire on any report the caller actually produces — every via
# segment fell out `unscreened` and the run still printed PASS. These cases
# drive the program through that exact report shape, in BOTH directions.
#
# Synthetic 3-layer stack, chip-agnostic:  lyr1 | cut12 | lyr2 | cut23 | lyr3
#   routing lyr* : 2.8 mA/um over a 0.14um width → 3.92e-4 A limit current
#   cut12        : 0.29 mA/cut → 2.9e-4 A ;  cut23 : 0.10 mA/cut → 1.0e-4 A
# ===========================================================================

def _stack_lef(*, with_cut12=True, with_cut23=False) -> str:
    def routing(n):
        return (f"LAYER {n}\n  TYPE ROUTING ;\n  WIDTH 0.14 ;\n"
                f"  THICKNESS 0.35 ;\n  DCCURRENTDENSITY AVERAGE 2.8 ;\n"
                f"END {n}\n\n")

    def cut(n, ma):
        return (f"LAYER {n}\n  TYPE CUT ;\n"
                f"  DCCURRENTDENSITY AVERAGE {ma} ;\nEND {n}\n\n")

    text = routing("lyr1")
    if with_cut12:
        text += cut("cut12", 0.29)
    text += routing("lyr2")
    if with_cut23:
        text += cut("cut23", 0.10) + routing("lyr3")
    return text


def _producer_csv(tmp_path, rows, *, cuts_column=False) -> Path:
    """An em_segments.csv in the shape the real producer emits: the two node
    LAYER columns are both METAL, no width column, no net column, and the cut
    layer of a via segment appears nowhere."""
    head = ("Node0 Layer,Node0 X location,Node0 Y location,"
            "Node1 Layer,Node1 X location,Node1 Y location,Current")
    head += ",Cuts\n" if cuts_column else "\n"
    body = ""
    for row in rows:
        l0, l1, cur = row[0], row[1], row[2]
        body += f"{l0},0,0,{l1},1,0,{cur}"
        body += f",{row[3]}\n" if cuts_column else "\n"
    return _write(tmp_path / "em_segments.csv", head + body)


def test_via_over_jmax_fails_from_producer_shaped_report(tmp_path):
    """DIRECTION 1 — the missing verdict.

    A via carrying 3.1x its cut Jmax, written the only way the producer knows
    how to write it (lyr1 -> lyr2, cut unnamed), must FAIL. The benign
    same-layer row is what made the unfixed program answer PASS: it screened
    that one, dropped the via, and called the run green."""
    csv = _producer_csv(tmp_path, [("lyr1", "lyr1", 1.0e-5),
                                   ("lyr1", "lyr2", 9.0e-4)])
    lef = _write(tmp_path / "stack.lef", _stack_lef())
    r = _run(csv, "--tech-lef", lef, "--net", "PWR", "--json", tmp_path / "o.json")
    assert r.returncode == 1, r.stdout
    rep = json.loads((tmp_path / "o.json").read_text())
    assert rep["verdict"] == "FAIL"
    assert rep["pass"] is False
    assert rep["offender_count"] == 1
    off = rep["offenders"][0]
    assert off["basis"] == "per_cut"
    assert off["layer"] == "cut12"           # resolved from the stack
    assert off["endpoints"] == "lyr1->lyr2"  # ...for endpoints that name no cut
    assert off["limit_A_per_cut"] == 2.9e-4
    assert off["utilization"] >= (1.0 - rep["margin"])
    assert rep["summary"]["segments_unscreened"] == 0
    msg = " ".join(f["message"] for f in rep["findings"]
                   if f["rule"] == "EM_CURRENT_DENSITY_OVER_JMAX")
    assert "cut12" in msg and "PWR" in msg and "Jmax/cut" in msg


def test_via_under_jmax_still_passes_from_producer_shaped_report(tmp_path):
    """DIRECTION 2 — the other verdict is still reachable.

    Same stack, same report shape, a via at 3.4% of its cut Jmax: PASS, and
    the via was genuinely SCREENED (per_cut basis, nothing unscreened) rather
    than passing by being ignored."""
    csv = _producer_csv(tmp_path, [("lyr1", "lyr1", 1.0e-5),
                                   ("lyr1", "lyr2", 1.0e-5),
                                   ("lyr2", "lyr2", 2.0e-5)])
    lef = _write(tmp_path / "stack.lef", _stack_lef())
    r = _run(csv, "--tech-lef", lef, "--json", tmp_path / "o.json")
    assert r.returncode == 0, r.stdout
    rep = json.loads((tmp_path / "o.json").read_text())
    assert rep["verdict"] == "PASS"
    assert rep["pass"] is True
    summ = rep["summary"]
    assert summ["segments_total"] == 3
    assert summ["segments_screened"] == 3
    assert summ["segments_unscreened"] == 0
    assert summ["screened_by_basis"]["per_cut"] == 1
    assert "cut12" in summ["per_layer"]


def test_stacked_via_takes_the_most_restrictive_cut(tmp_path):
    """A lyr1->lyr3 stacked via crosses BOTH cuts, so the tighter one governs:
    1.2e-4 A is under cut12's 2.9e-4 but over cut23's 1.0e-4."""
    csv = _producer_csv(tmp_path, [("lyr1", "lyr3", 1.2e-4)])
    lef = _write(tmp_path / "stack.lef",
                 _stack_lef(with_cut23=True))
    r = _run(csv, "--tech-lef", lef, "--json", tmp_path / "o.json")
    assert r.returncode == 1, r.stdout
    rep = json.loads((tmp_path / "o.json").read_text())
    off = rep["offenders"][0]
    assert off["layer"] == "cut23"
    assert off["cut_candidates"] == ["cut12", "cut23"]


def test_reported_cut_count_divides_the_current_both_ways(tmp_path):
    """A via ARRAY is not N times over its limit. 9.0e-4 A through 8 cuts is
    1.125e-4 A/cut → PASS; the identical current with no cut count declared
    is screened against ONE cut (conservative) → FAIL."""
    lef = _write(tmp_path / "stack.lef", _stack_lef())
    arrayed = _producer_csv(tmp_path / "a", [("lyr1", "lyr2", 9.0e-4, 8)],
                            cuts_column=True)
    r = _run(arrayed, "--tech-lef", lef, "--json", tmp_path / "a.json")
    assert r.returncode == 0, r.stdout
    rep = json.loads((tmp_path / "a.json").read_text())
    assert rep["verdict"] == "PASS"
    assert rep["summary"]["screened_by_basis"]["per_cut"] == 1

    single = _producer_csv(tmp_path / "b", [("lyr1", "lyr2", 9.0e-4)])
    r2 = _run(single, "--tech-lef", lef)
    assert r2.returncode == 1, r2.stdout


def test_no_cut_between_endpoints_stays_unscreened_not_guessed(tmp_path):
    """Guard against over-reach: when the reference places NO cut between the
    two endpoints, the program must not invent a limit — the segment stays
    unscreened and (being the only one) the run SKIPs, never PASSes."""
    csv = _producer_csv(tmp_path, [("lyr1", "lyr2", 9.0e-4)])
    lef = _write(tmp_path / "stack.lef", _stack_lef(with_cut12=False))
    r = _run(csv, "--tech-lef", lef, "--json", tmp_path / "o.json")
    assert r.returncode == 3, r.stdout
    rep = json.loads((tmp_path / "o.json").read_text())
    assert rep["verdict"] == "SKIPPED"
    assert rep["pass"] is False
    assert rep["summary"]["unscreened_reasons"] == {
        "via_cut_layer_not_in_jmax_reference": 1}


def test_jmax_json_between_pair_resolves_the_cut(tmp_path):
    """jmax JSON path: an explicit `between` pair resolves the cut even when
    the layers are listed out of stack order."""
    jm = _write(tmp_path / "jmax.json", {"layers": {
        "lyr1": {"kind": "routing", "thickness_um": 0.35, "width_um": 0.14,
                 "jmax_mA_per_um": 2.8},
        "lyr2": {"kind": "routing", "thickness_um": 0.35, "width_um": 0.14,
                 "jmax_mA_per_um": 2.8},
        "cutx": {"kind": "cut", "jmax_mA_per_cut": 0.29,
                 "between": ["lyr1", "lyr2"]},
    }})
    csv = _producer_csv(tmp_path, [("lyr1", "lyr2", 9.0e-4)])
    r = _run(csv, "--jmax", jm, "--json", tmp_path / "o.json")
    assert r.returncode == 1, r.stdout
    rep = json.loads((tmp_path / "o.json").read_text())
    assert rep["offenders"][0]["layer"] == "cutx"


def test_jmax_json_layer_order_is_the_stack(tmp_path):
    """jmax JSON path: with no `between`, the order the layers are listed in
    is the bottom-up stack, as in a tech LEF."""
    jm = _write(tmp_path / "jmax.json", {"layers": {
        "lyr1": {"kind": "routing", "thickness_um": 0.35, "width_um": 0.14,
                 "jmax_mA_per_um": 2.8},
        "cutx": {"kind": "cut", "jmax_mA_per_cut": 0.29},
        "lyr2": {"kind": "routing", "thickness_um": 0.35, "width_um": 0.14,
                 "jmax_mA_per_um": 2.8},
    }})
    over = _producer_csv(tmp_path / "a", [("lyr1", "lyr2", 9.0e-4)])
    assert _run(over, "--jmax", jm).returncode == 1
    under = _producer_csv(tmp_path / "b", [("lyr1", "lyr2", 1.0e-5)])
    r = _run(under, "--jmax", jm, "--json", tmp_path / "o.json")
    assert r.returncode == 0, r.stdout
    assert json.loads((tmp_path / "o.json").read_text())[
        "summary"]["segments_unscreened"] == 0


def test_segment_named_on_a_cut_layer_is_screened_per_cut(tmp_path):
    """A report that names the cut layer on BOTH endpoints is a via too — it
    used to fall out as `layer_is_not_routing`."""
    seg = _write(tmp_path / "em.json", {"segments": [
        {"net": "PWR", "layer0": "cut12", "layer1": "cut12",
         "current_A": 9.0e-4}]})
    lef = _write(tmp_path / "stack.lef", _stack_lef())
    r = _run(seg, "--tech-lef", lef, "--json", tmp_path / "o.json")
    assert r.returncode == 1, r.stdout
    rep = json.loads((tmp_path / "o.json").read_text())
    assert rep["offenders"][0]["basis"] == "per_cut"
    assert rep["offenders"][0]["layer"] == "cut12"
