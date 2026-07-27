"""Unit tests for PROACTIVE Design-for-ECO (Step 18).

Docker-free. Covers:
  * spare-density computation + clamp (runner helpers)
  * spare count / type-distribution / grid-spread (runner helpers)
  * spare_cell_coverage_check PASS/FAIL on synthetic spare_cells.json
    (good distribution vs clustered vs untied vs below-density)
  * spare_cell_preservation_check PASS when the spare set is stable and
    keep-tagged, FAIL when a spare is missing or has lost its keep attr.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).parent.parent
sys.path.insert(0, str(PROGRAMS))

import phase3_one_shot_runner as runner  # noqa: E402
import spare_cell_coverage_check as cov  # noqa: E402
import spare_cell_preservation_check as pres  # noqa: E402

COV_SCRIPT = PROGRAMS / "spare_cell_coverage_check.py"
PRES_SCRIPT = PROGRAMS / "spare_cell_preservation_check.py"
assert COV_SCRIPT.exists() and PRES_SCRIPT.exists()


# ──────────────────────────────────────────────────────────────────
# 1) spare-density computation + clamp
# ──────────────────────────────────────────────────────────────────
def test_density_default_when_none():
    d, warn = runner._compute_spare_density(None)
    assert d == runner._DEFAULT_SPARE_DENSITY
    assert warn is None


def test_density_passthrough_in_range():
    d, warn = runner._compute_spare_density(0.05)
    assert d == 0.05
    assert warn is None


def test_density_clamps_high():
    d, warn = runner._compute_spare_density(0.5)
    assert d == runner._SPARE_DENSITY_MAX == 0.2
    assert warn and "ceiling" in warn


def test_density_clamps_negative():
    d, warn = runner._compute_spare_density(-0.3)
    assert d == 0.0
    assert warn and "< 0" in warn


def test_density_non_numeric_falls_back():
    d, warn = runner._compute_spare_density("abc")
    assert d == runner._DEFAULT_SPARE_DENSITY
    assert warn and "not numeric" in warn


# ──────────────────────────────────────────────────────────────────
# 2) count / distribution / grid helpers
# ──────────────────────────────────────────────────────────────────
def test_count_from_density():
    assert runner._spare_count_from_density(1000, 0.02) == 20
    # at least 1 spare when density>0 and there is logic
    assert runner._spare_count_from_density(10, 0.02) == 1
    # zero when no logic or zero density
    assert runner._spare_count_from_density(0, 0.02) == 0
    assert runner._spare_count_from_density(1000, 0.0) == 0


def test_type_distribution_sums_to_count():
    for n in (1, 7, 20, 33, 100):
        dist = runner._spare_type_distribution(n)
        assert sum(dist.values()) == n
        # only known classes appear
        known = {c for c, _ in runner._SPARE_CELL_MIX}
        assert set(dist).issubset(known)


def test_grid_positions_are_distributed():
    pos = runner._spare_grid_positions(16, 10, 10, 210, 210)
    assert len(pos) == 16
    # a 16-cell grid must occupy many distinct positions (not clustered)
    assert len({p for p in pos}) >= 10
    # all inside the core box
    for x, y in pos:
        assert 10 <= x <= 210 and 10 <= y <= 210


def test_build_plan_shape():
    plan = runner._build_spare_cells_plan(
        placed_cells=1000, density=0.02,
        core_box=(10, 10, 210, 210),
        liberty_path="", container="", has_pad_ring=True)
    assert plan["count"] == 20
    # #563 r2 — tied_off is now an HONEST claim: False at plan level;
    # step_pnr flips it True only when the PDK exposes a tie-low cell and
    # the postfix tie-off TCL is actually emitted.
    assert plan["tied_off"] is False
    assert len(plan["instances"]) == 20
    assert sum(plan["types"].values()) == 20
    # pad ring → 2 spare pads reserved
    assert len(plan["spare_pads"]) == 2
    # every instance carries keep:true
    assert all(i["keep"] is True for i in plan["instances"])


def test_count_placed_cells_from_netlist():
    netlist = (
        "module top(input a, output y);\n"
        "  wire n1, n2;\n"
        "  INVX1 u1 (.A(a), .Y(n1));\n"
        "  NAND2X1 u2 (.A(n1), .B(a), .Y(n2));\n"
        "  DFFX1 u3 (.D(n2), .CK(a), .Q(y));\n"
        "  assign y = n2;\n"
        "endmodule\n"
    )
    assert runner._count_placed_cells_from_netlist(netlist) == 3
    assert runner._count_placed_cells_from_netlist("") == 0


# ──────────────────────────────────────────────────────────────────
# helpers to synthesise a spare_cells.json
# ──────────────────────────────────────────────────────────────────
def _good_plan(n=20, density=0.02, tied=True, distributed=True):
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
    r = cov.evaluate_coverage(_good_plan(), None, target_density=0.02)
    assert r["verdict"] == "PASS", r["reasons"]
    assert r["density_ok"] and r["distribution_ok"] and r["tie_off_ok"]


def test_coverage_fail_clustered():
    r = cov.evaluate_coverage(_good_plan(distributed=False), None, 0.02)
    assert r["verdict"] == "FAIL"
    assert not r["distribution_ok"]
    assert any("cluster" in x for x in r["reasons"])


def test_coverage_fail_untied():
    r = cov.evaluate_coverage(_good_plan(tied=False), None, 0.02)
    assert r["verdict"] == "FAIL"
    assert not r["tie_off_ok"]


def test_coverage_fail_below_density():
    # actual density below target
    plan = _good_plan(n=5, density=0.005)
    r = cov.evaluate_coverage(plan, None, target_density=0.02)
    assert r["verdict"] == "FAIL"
    assert not r["density_ok"]


def test_coverage_check_cli_pass(tmp_path):
    proj = _write_project(tmp_path, _good_plan())
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


def test_preservation_pass_stable_and_tagged():
    plan = _good_plan(n=6)
    texts = _final_texts_all_present_and_tagged(plan)
    r = pres.evaluate_preservation(plan, texts)
    assert r["verdict"] == "PASS", r
    assert r["inserted"] == 6 and r["survived"] == 6
    assert r["removed"] == [] and r["all_keep_attr_intact"]


def test_preservation_fail_missing_spare():
    plan = _good_plan(n=6)
    texts = _final_texts_all_present_and_tagged(plan)
    # Drop the last spare entirely from both artefacts (optimizer stripped it).
    gone = plan["instances"][-1]["name"]
    texts = {k: v.replace(f"  - {gone} sky130_fd_sc_hd__inv_1 + FIXED ( 100 100 ) N ;\n", "")
                  .replace(f"set_dont_touch {gone}", "")
             for k, v in texts.items()}
    # ensure the name truly absent
    for v in texts.values():
        assert gone not in v
    r = pres.evaluate_preservation(plan, texts)
    assert r["verdict"] == "FAIL"
    assert any(x["name"] == gone for x in r["removed"])


def test_preservation_fail_lost_keep_attr():
    plan = _good_plan(n=6)
    # Build artefacts where names are present but NOT keep-tagged, while
    # the artefact set IS keep-capable (some other dont_touch token).
    names = [i["name"] for i in plan["instances"]]
    # PLACED (not FIXED) and no set_dont_touch on the spare → untagged.
    def_text = "\n".join(
        [f"  - {nm} sky130_fd_sc_hd__inv_1 + PLACED ( 100 100 ) N ;"
         for nm in names]
        # an unrelated dont_touch directive makes the set "keep-capable"
        + ["set_dont_touch some_other_inst"])
    r = pres.evaluate_preservation(plan, {"def": def_text})
    assert r["verdict"] == "FAIL"
    assert not r["all_keep_attr_intact"]
    assert len(r["untagged"]) == len(names)


def test_preservation_gds_only_survival_no_tag_required():
    # A GDS-only artefact has no keep/dont_touch concept; survival alone
    # (name present) must PASS without a tag check.
    plan = _good_plan(n=4)
    names = [i["name"] for i in plan["instances"]]
    gds_text = "HEADER 600\n" + "\n".join(f"SNAME {nm}" for nm in names)
    r = pres.evaluate_preservation(plan, {"gds": gds_text})
    assert r["keep_check_applied"] is False
    assert r["verdict"] == "PASS", r
    assert r["removed"] == []


def test_preservation_cli_pass(tmp_path):
    plan = _good_plan(n=5)
    proj = _write_project(tmp_path, plan)
    # write a final routed.def + post-pnr netlist that preserve+tag spares
    pnr = proj / "phase3/stage3/pnr"
    names = [i["name"] for i in plan["instances"]]
    (pnr / "routed.def").write_text(
        "DESIGN top ;\n" + "\n".join(
            f"  - {nm} inv + FIXED ( 0 0 ) N ;" for nm in names))
    (pnr / "top_pnr.v").write_text(
        "\n".join(f"set_dont_touch {nm}" for nm in names))
    cp = subprocess.run(
        [sys.executable, str(PRES_SCRIPT), str(proj),
         "--json", str(tmp_path / "p.json")],
        capture_output=True, text=True)
    assert cp.returncode == 0, cp.stdout + cp.stderr
    rep = json.loads((tmp_path / "p.json").read_text())
    assert rep["verdict"] == "PASS"
    # canonical report also emitted
    assert (proj / "reports/spare_preservation.json").is_file()


def test_preservation_cli_fail_removed(tmp_path):
    plan = _good_plan(n=5)
    proj = _write_project(tmp_path, plan)
    pnr = proj / "phase3/stage3/pnr"
    names = [i["name"] for i in plan["instances"]]
    # routed.def is MISSING one spare (optimizer stripped it).
    keep = names[:-1]
    (pnr / "routed.def").write_text(
        "DESIGN top ;\n" + "\n".join(
            f"  - {nm} inv + FIXED ( 0 0 ) N ;" for nm in keep))
    (pnr / "top_pnr.v").write_text(
        "\n".join(f"set_dont_touch {nm}" for nm in keep))
    cp = subprocess.run(
        [sys.executable, str(PRES_SCRIPT), str(proj)],
        capture_output=True, text=True)
    assert cp.returncode == 1
    assert '"verdict": "FAIL"' in cp.stdout
    assert names[-1] in cp.stdout


def test_preservation_cli_no_artefacts(tmp_path):
    proj = _write_project(tmp_path, _good_plan(n=3))
    # no routed.def / netlist / gds at all
    cp = subprocess.run(
        [sys.executable, str(PRES_SCRIPT), str(proj)],
        capture_output=True, text=True)
    assert cp.returncode == 1
    assert "no final" in cp.stdout


# ──────────────────────────────────────────────────────────────────
# 6) d5 — STALE ARTEFACT: a preservation verdict must belong to THIS run
#
# `_collect_final_artefacts` resolves "the final artefact" by NAME
# (filled.def > routed.def > <top>.def, *_pnr.v, *.gds). On a RESUMED project
# a previous run's artefacts are still on disk, and the runner's spare names
# are deterministic — so they MATCH. Measured on the base tree: a project
# whose `filled.def` predates `spare_cells.json` by design returned
# `verdict: PASS, survived: 2`, rc=0 — a survival certificate for a spare set
# THIS run never established.
# ──────────────────────────────────────────────────────────────────
def _def_body(names):
    return ("DESIGN top ;\nCOMPONENTS ;\n"
            + "".join(f"  - {nm} inv + FIXED ( 0 0 ) N ;\n" for nm in names)
            + "END COMPONENTS\nEND DESIGN\n")


def test_d5_stale_final_def_is_refused_not_certified(tmp_path):
    """THE d5 DISCRIMINATOR. filled.def older than spare_cells.json => FAIL
    with STALE_ARTEFACT, naming the artefact and both mtimes."""
    import os
    plan = _good_plan(n=2)
    proj = _write_project(tmp_path, plan)
    pnr = proj / "phase3/stage3/pnr"
    names = [i["name"] for i in plan["instances"]]
    filled = pnr / "filled.def"
    filled.write_text(_def_body(names))
    spare_mtime = (pnr / "spare_cells.json").stat().st_mtime
    os.utime(filled, (spare_mtime - 3600, spare_mtime - 3600))
    cp = subprocess.run([sys.executable, str(PRES_SCRIPT), str(proj)],
                        capture_output=True, text=True)
    assert cp.returncode == 1, cp.stdout
    rpt = json.loads(cp.stdout)
    assert rpt["verdict"] == "FAIL", rpt
    assert rpt["stale_artefacts"], rpt
    assert "phase3/stage3/pnr/filled.def" in json.dumps(rpt), rpt
    assert "STALE_ARTEFACT" in " ".join(rpt["reasons"]), rpt


def test_d5_stale_guard_direction1_fresh_run_still_passes(tmp_path):
    """DIRECTION-1 GUARD. The same project with the DEF written AFTER the
    spare record is a legitimate run and must still PASS — the guard must not
    trade a false clean for a false alarm."""
    import os
    plan = _good_plan(n=2)
    proj = _write_project(tmp_path, plan)
    pnr = proj / "phase3/stage3/pnr"
    names = [i["name"] for i in plan["instances"]]
    filled = pnr / "filled.def"
    filled.write_text(_def_body(names))
    spare_mtime = (pnr / "spare_cells.json").stat().st_mtime
    os.utime(filled, (spare_mtime + 60, spare_mtime + 60))
    cp = subprocess.run([sys.executable, str(PRES_SCRIPT), str(proj)],
                        capture_output=True, text=True)
    assert cp.returncode == 0, cp.stdout
    rpt = json.loads(cp.stdout)
    assert rpt["verdict"] == "PASS" and rpt["survived"] == 2, rpt


def test_d5_stale_guard_direction1_same_mtime_passes(tmp_path):
    """DIRECTION-1 GUARD. Equality is NOT staleness — a same-timestamp write
    (coarse filesystem granularity, or a runner that emits both in one step)
    must not be condemned. Only strictly-older fails."""
    import os
    plan = _good_plan(n=2)
    proj = _write_project(tmp_path, plan)
    pnr = proj / "phase3/stage3/pnr"
    names = [i["name"] for i in plan["instances"]]
    filled = pnr / "filled.def"
    filled.write_text(_def_body(names))
    st = (pnr / "spare_cells.json").stat()
    os.utime(filled, ns=(st.st_mtime_ns, st.st_mtime_ns))
    cp = subprocess.run([sys.executable, str(PRES_SCRIPT), str(proj)],
                        capture_output=True, text=True)
    assert cp.returncode == 0, cp.stdout
    assert json.loads(cp.stdout)["verdict"] == "PASS"


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
