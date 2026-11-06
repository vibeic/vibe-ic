"""Unit tests for PROACTIVE Design-for-ECO (Step 18).

Docker-free. Covers:
  * spare-density computation + clamp (runner helpers)
  * spare count / type-distribution / grid-spread (runner helpers)
  * spare_cell_coverage_check PASS/FAIL on synthetic spare_cells.json
    (good distribution vs clustered vs untied vs below-density)
  * spare_cell_preservation_check PASS when the spare set is stable and
    keep-tagged, FAIL when a spare is missing or has lost its keep attr.
"""
import contextlib
import io
import json
import os
import subprocess
import sys
from pathlib import Path


PROGRAMS = Path(__file__).parent.parent
sys.path.insert(0, str(PROGRAMS))

import spare_cell_coverage_check as cov  # noqa: E402

COV_SCRIPT = PROGRAMS / "spare_cell_coverage_check.py"


# ──────────────────────────────────────────────────────────────────
# 1) spare-density computation + clamp
# ──────────────────────────────────────────────────────────────────


# ──────────────────────────────────────────────────────────────────
# 2) count / distribution / grid helpers
# ──────────────────────────────────────────────────────────────────


# ──────────────────────────────────────────────────────────────────
# helpers to synthesise a spare_cells.json
# ──────────────────────────────────────────────────────────────────
def _good_plan(n=20, density=0.02, tied=True, distributed=True,
               enumerated=False):
    instances = []
    for i in range(n):
        if distributed:
            x, y = 10 + (i % 5) * 30, 10 + (i // 5) * 30
        else:
            x, y = 50, 50  # all clustered at one point
        instances.append({
            "name": f"spare_inv_{i}", "type": "inverter",
            "cell": "sky130_fd_sc_hd__inv_1",
            "llx": x, "lly": y, "keep": True,
        })
    return {
        "count": n,
        "density": density,
        "target_density": density,
        "actual_density": density,
        "placed_cells_est": int(round(n / density)) if density else 0,
        "types": {"inverter": n},
        "tied_off": tied,
        # the per-pin enumeration the insertion step prints (U6); step 18's
        # coverage gate proves the tie-off from it
        **({"tie_off": {"tied_off": tied, "inputs": [
            {"inst": i["name"], "pin": "I", "use": "SIGNAL",
             "net": f"spare_tielo_{i['name']}"} for i in instances]}}
           if enumerated else {}),
        "instances": instances,
        "spare_pads": [],
    }


def _write_project(tmp_path, plan):
    pnr = tmp_path / "phase3/stage3/pnr"
    pnr.mkdir(parents=True)
    (pnr / "spare_cells.json").write_text(json.dumps(plan))
    return tmp_path


# ──────────────────────────────────────────────────────────────────
# 3) coverage-check PASS / FAIL
# ──────────────────────────────────────────────────────────────────
def test_coverage_pass_good_plan():
    r = cov.evaluate_coverage(_good_plan(enumerated=True), target_density=0.02)
    assert r["verdict"] == "PASS", r["reasons"]
    assert r["density_ok"] and r["distribution_ok"] and r["tie_off_ok"]


def test_coverage_fail_clustered():
    r = cov.evaluate_coverage(_good_plan(distributed=False), 0.02)
    assert r["verdict"] == "FAIL"
    assert not r["distribution_ok"]
    assert any("cluster" in x for x in r["reasons"])


def test_coverage_fail_untied():
    r = cov.evaluate_coverage(_good_plan(tied=False), 0.02)
    assert r["verdict"] == "FAIL"
    assert not r["tie_off_ok"]


def test_coverage_fail_below_density():
    # actual density below target
    plan = _good_plan(n=5, density=0.005)
    r = cov.evaluate_coverage(plan, target_density=0.02)
    assert r["verdict"] == "FAIL"
    assert not r["density_ok"]


def test_coverage_check_cli_pass(tmp_path):
    proj = _write_project(tmp_path, _good_plan(enumerated=True))
    cp = subprocess.run(
        [sys.executable, str(COV_SCRIPT), str(proj),
         "--json", str(tmp_path / "out.json")],
        capture_output=True, text=True)
    assert cp.returncode == 0, cp.stdout + cp.stderr
    rep = json.loads((tmp_path / "out.json").read_text())
    assert rep["verdict"] == "PASS"


def test_coverage_check_cli_fail_clustered(tmp_path):
    proj = _write_project(tmp_path, _good_plan(distributed=False))
    cp = subprocess.run(
        [sys.executable, str(COV_SCRIPT), str(proj)],
        capture_output=True, text=True)
    assert cp.returncode == 1
    assert '"verdict": "FAIL"' in cp.stdout


def test_coverage_check_cli_missing_json(tmp_path):
    (tmp_path / "phase3/stage3/pnr").mkdir(parents=True)
    cp = subprocess.run(
        [sys.executable, str(COV_SCRIPT), str(tmp_path)],
        capture_output=True, text=True)
    assert cp.returncode == 1
    assert "not found" in cp.stdout


# ──────────────────────────────────────────────────────────────────
# 4) preservation-check PASS / FAIL
# ──────────────────────────────────────────────────────────────────
def _final_texts_all_present_and_tagged(plan):
    """Build a final DEF + netlist + dont_touch directive text where
    every spare survives and is keep-tagged."""
    names = [i["name"] for i in plan["instances"]]
    def_lines = ["VERSION 5.8 ;", "DESIGN top ;", f"COMPONENTS {len(names)} ;"]
    for nm in names:
        def_lines.append(f"  - {nm} sky130_fd_sc_hd__inv_1 + FIXED ( 100 100 ) N ;")
    def_lines.append("END COMPONENTS")
    netlist = "\n".join(
        f"set_dont_touch {nm}" for nm in names)
    return {"def": "\n".join(def_lines), "netlist": netlist}


# ──────────────────────────────────────────────────────────────────
# 6) d5 — MIXED PROVENANCE: a preservation verdict must not be carried by
#    an artefact that does not describe the netlist being shipped.
#
# `_collect_final_artefacts` resolves "the final artefact" by NAME
# (filled.def > routed.def > <top>.def, *_pnr.v, *.gds). On a RESUMED project
# a previous run's artefacts are still on disk, and the runner's spare names
# are deterministic — so they MATCH. Because a spare "survives" iff it is
# named in AT LEAST ONE artefact, that leftover file alone certifies the set.
# Measured on the base tree: filled.def from run N naming all 4 spares, the
# shipped <top>_pnr.v and routed.def of run N+1 missing `spare_inv_3`
# -> `verdict: PASS, survived: 4`, rc=0. A false clean.
#
# The discriminator is CONTENT, not mtime. An earlier revision of this gate
# FAILed any artefact older than spare_cells.json; the production runner
# writes routed.def / <top>.def / <top>_pnr.v from the OpenROAD tcl and only
# then serialises spare_cells.json from Python in the SAME step, so that rule
# false-FAILed every correct single-pass run — hence
# `test_d5_runner_write_order_project_is_not_condemned` below, which builds
# the fixture in the runner's exact order.
# ──────────────────────────────────────────────────────────────────
def _def_body(names):
    return ("DESIGN top ;\nCOMPONENTS ;\n"
            + "".join(f"  - {nm} inv + FIXED ( 0 0 ) N ;\n" for nm in names)
            + "END COMPONENTS\nEND DESIGN\n")


def _v_body(names):
    return ("module top ();\n"
            + "".join(f"  (* keep *) inv {nm} (.A(a), .Y(y));\n"
                      for nm in names)
            + "endmodule\n")


def _runner_order_project(tmp_path, plan, shipped, filled=None):
    """Build a project in the PRODUCTION RUNNER's write order:
    the OpenROAD tcl emits routed.def + <top>.def + <top>_pnr.v, then the
    SAME `step_pnr` serialises spare_cells.json, then step 34 metal fill
    writes filled.def.

    `shipped` are the spare names present in the OpenROAD-written artefacts;
    `filled` (default: same as shipped) are those in filled.def, so a caller
    can model a leftover fill DEF from a previous run."""
    import os
    import time
    pnr = tmp_path / "phase3/stage3/pnr"
    pnr.mkdir(parents=True, exist_ok=True)
    t0 = time.time() - 3000.0
    (pnr / "routed.def").write_text(_def_body(shipped))
    (pnr / "top.def").write_text(_def_body(shipped))
    (pnr / "top_pnr.v").write_text(_v_body(shipped))
    for fname in ("routed.def", "top.def", "top_pnr.v"):
        os.utime(pnr / fname, (t0, t0))
    (pnr / "spare_cells.json").write_text(json.dumps(plan))
    os.utime(pnr / "spare_cells.json", (t0 + 60, t0 + 60))
    fill_names = shipped if filled is None else filled
    (pnr / "filled.def").write_text(_def_body(fill_names) + "# FILLWIRES\n")
    os.utime(pnr / "filled.def", (t0 + 180, t0 + 180))
    return tmp_path


def _cap_truncating_only_the_fill_def(project):
    """A scan cap that truncates `filled.def` and nothing else.

    The point of the fixture is ONE partial witness beside a fully-read one; a
    cap that truncates both makes every claim partial and measures nothing.
    """
    pnr = Path(project) / "phase3/stage3/pnr"
    netlist = (pnr / "top_pnr.v").stat().st_size
    filled = (pnr / "filled.def").stat().st_size
    assert netlist < filled, (netlist, filled)
    return filled - 1


def test_d5_step18_no_longer_wires_the_preservation_gate(tmp_path):
    """The flow-side half of the same defect. Step 18 (spare INSERTION) must
    not name `spare_cell_preservation_check` in its gate or its `programs:`
    array: at insertion time the only artefacts that gate can resolve are
    steps 21/34's, which are step 18's DESCENDANTS — an unsatisfiable
    dependency and, on a resumed project, a stale read. Step 34 (metal fill)
    must still wire it, since its closure contains every pass a spare has to
    survive."""
    import yaml
    flow = (PROGRAMS.parent / "flow" / "phase1_phase2_phase3.yaml")
    steps = {str(s["id"]): s
             for s in yaml.safe_load(flow.read_text())["steps"]}

    def gate_blob(sid):
        return json.dumps(steps[sid].get("gate") or {})

    assert "spare_cell_preservation_check" not in gate_blob("18")
    assert "spare_cell_preservation_check" not in (
        steps["18"].get("programs") or [])
    assert "spare_cell_coverage_check" in gate_blob("18")
    assert "spare_cell_preservation_check" in gate_blob("34")
    assert "spare_cell_preservation_check" in (
        steps["34"].get("programs") or [])
