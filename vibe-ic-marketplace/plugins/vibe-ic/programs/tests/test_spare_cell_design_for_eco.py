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
    r = cov.evaluate_coverage(_good_plan(), target_density=0.02)
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


def test_d5_runner_write_order_project_is_not_condemned(tmp_path):
    """DIRECTION-1 GUARD, and the regression that killed the mtime rule.

    Every artefact the OpenROAD tcl writes is STRICTLY OLDER than
    spare_cells.json on a correct single-pass run, because the same
    `step_pnr` serialises the record afterwards. A gate that reads that as
    staleness FAILs every project the runner produces. Measured: rc=0,
    PASS, 4/4 survived, and the cross-artefact check actually ran
    (status == COMPARED) rather than being skipped into a green."""
    plan = _good_plan(n=4)
    names = [i["name"] for i in plan["instances"]]
    proj = _runner_order_project(tmp_path, plan, names)
    cp = subprocess.run([sys.executable, str(PRES_SCRIPT), str(proj)],
                        capture_output=True, text=True)
    assert cp.returncode == 0, cp.stdout
    rpt = json.loads(cp.stdout)
    assert rpt["verdict"] == "PASS", rpt
    assert rpt["survived"] == rpt["inserted"] == 4, rpt
    assert rpt["artefact_agreement"]["status"] == "COMPARED", rpt
    assert rpt["artefact_agreement"]["disagreements"] == [], rpt


def test_d5_leftover_fill_def_cannot_vouch_for_a_stripped_spare(tmp_path):
    """THE d5 DISCRIMINATOR. A resumed project: run N's filled.def names all
    four spares, run N+1's SHIPPED netlist and routed.def lost `spare_inv_3`.
    The base gate returned PASS/4-survived/rc=0 on exactly this tree because
    survival is a union over artefacts. The gate must now name the
    disagreement, both files, and the spare that separates them."""
    plan = _good_plan(n=4)
    names = [i["name"] for i in plan["instances"]]
    proj = _runner_order_project(tmp_path, plan, names[:3], filled=names)
    cp = subprocess.run([sys.executable, str(PRES_SCRIPT), str(proj)],
                        capture_output=True, text=True)
    assert cp.returncode == 1, cp.stdout
    rpt = json.loads(cp.stdout)
    assert rpt["verdict"] == "FAIL", rpt
    dis = rpt["artefact_agreement"]["disagreements"]
    assert dis == [{"present_in": "def", "absent_from": "netlist",
                    "spares": [names[3]]}], rpt
    joined = " ".join(rpt["reasons"])
    assert "RECORD_ARTEFACT_MISMATCH" in joined, rpt
    assert "phase3/stage3/pnr/filled.def" in joined, rpt
    assert "phase3/stage3/pnr/top_pnr.v" in joined, rpt
    assert names[3] in joined, rpt


def test_d5_removed_spare_is_still_named_not_masked(tmp_path):
    """The cross-artefact rule ADDS a failure mode; it must not short-circuit
    past `evaluate_preservation`. With a spare stripped from EVERY artefact
    the artefacts agree — and the gate must still report the removal by name,
    which is the defect class it exists for."""
    plan = _good_plan(n=4)
    names = [i["name"] for i in plan["instances"]]
    proj = _runner_order_project(tmp_path, plan, names[:3])
    cp = subprocess.run([sys.executable, str(PRES_SCRIPT), str(proj)],
                        capture_output=True, text=True)
    assert cp.returncode == 1, cp.stdout
    rpt = json.loads(cp.stdout)
    assert rpt["verdict"] == "FAIL", rpt
    assert [r["name"] for r in rpt["removed"]] == [names[3]], rpt
    assert rpt["artefact_agreement"]["disagreements"] == [], rpt


def test_d5_unreadable_artefact_is_excluded_and_disclosed(tmp_path):
    """UNMEASURED IS NOT ZERO. A binary / truncated / unreadable artefact
    names zero spares for reasons that are not preservation. It must be
    excluded from the comparison with its read status recorded — not counted
    as 'every spare is missing from this file'."""
    plan = _good_plan(n=4)
    names = [i["name"] for i in plan["instances"]]
    proj = _runner_order_project(tmp_path, plan, names)
    (proj / "phase3/stage3/pnr/top_pnr.v").write_bytes(b"\x00" * 64)
    cp = subprocess.run([sys.executable, str(PRES_SCRIPT), str(proj)],
                        capture_output=True, text=True)
    assert cp.returncode == 0, cp.stdout
    rpt = json.loads(cp.stdout)
    agree = rpt["artefact_agreement"]
    assert agree["disagreements"] == [], rpt
    assert agree["status"] == "SINGLE_WITNESS", rpt
    assert agree["excluded"]["netlist"]["read"] == "BINARY_SKIPPED", rpt
    assert rpt["artefact_read_status"]["netlist"] == "BINARY_SKIPPED", rpt


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


def _run_with_scan_cap(project, cap):
    """Run the gate in-process with MAX_SCAN_BYTES lowered.

    The production cap is 256 MiB; a fill DEF above it is the size class this
    module's #471/#684 notes are about, and building one in a test is not an
    option. Lowering the cap makes the SAME code path reachable on a small
    fixture, which is the only honest way to exercise it.
    """
    import importlib
    mod = importlib.import_module("spare_cell_preservation_check")
    out = Path(project) / "_scan_cap_report.json"
    saved = mod.MAX_SCAN_BYTES
    buf = io.StringIO()
    try:
        mod.MAX_SCAN_BYTES = cap
        with contextlib.redirect_stdout(buf):
            rc = mod.main([str(project), "--json", str(out)])
    finally:
        mod.MAX_SCAN_BYTES = saved
    return rc, json.loads(out.read_text())


def test_d5_a_truncated_leftover_def_cannot_vouch_for_a_stripped_spare(tmp_path):
    """THE SIZE-CAP HOLE, closed. A truncated artefact used to be dropped from
    the cross-artefact comparison outright while `audit` still fed its text to
    `evaluate_preservation`, where survival is a UNION over all texts. So a
    leftover `filled.def` larger than MAX_SCAN_BYTES — the multi-GB fill DEF
    this module's own #471/#684 notes worry about — was distrusted for
    DISAGREEMENT and still trusted for VOUCHING, which restores the exact
    false clean the rule was built to catch.

    MEASURED before the repair, same mixed-provenance tree, cap lowered to
    model that file: rc 0, verdict PASS, survived 4/4, `disagreements []`,
    `status SINGLE_WITNESS`. At the production cap the identical tree gives
    rc 1 and names the separating spare.

    A prefix read is sound about PRESENCE and says nothing about ABSENCE, so a
    truncated artefact may appear on the `present_in` side of a disagreement
    and never on the `absent_from` side.
    """
    plan = _good_plan(n=4)
    names = [i["name"] for i in plan["instances"]]
    proj = _runner_order_project(tmp_path, plan, names[:3], filled=names)
    rc, rpt = _run_with_scan_cap(proj, _cap_truncating_only_the_fill_def(proj))
    assert rc == 1, rpt
    assert rpt["artefact_read_status"]["def"] == "TRUNCATED", rpt
    assert rpt["artefact_agreement"]["status"] == "COMPARED_PARTIAL", rpt
    assert rpt["artefact_agreement"]["disagreements"] == [
        {"present_in": "def", "absent_from": "netlist",
         "spares": [names[3]]}], rpt


def test_d5_a_truncated_artefact_never_testifies_to_absence(tmp_path):
    """NO FALSE ALARM, the other direction. The truncated file's SILENCE is
    not evidence: a spare the shipped netlist names and the truncated tail
    never reached must not be reported as a disagreement."""
    plan = _good_plan(n=4)
    names = [i["name"] for i in plan["instances"]]
    proj = _runner_order_project(tmp_path, plan, names)
    rc, rpt = _run_with_scan_cap(proj, _cap_truncating_only_the_fill_def(proj))
    assert rc == 0, rpt
    assert rpt["artefact_read_status"]["def"] == "TRUNCATED", rpt
    assert rpt["artefact_agreement"]["disagreements"] == [], rpt
    assert rpt["artefact_agreement"]["status"] == "COMPARED_PARTIAL", rpt
    assert rpt["verdict"] == "PASS", rpt


def test_d5_agreement_ignores_spare_pads(tmp_path):
    """NO FALSE ALARM on the one recorded-name class whose presence is
    emitter-dependent. A spare PAD is an IO-ring reservation: the runner
    records `spare_pad_in_0` / `spare_pad_out_0` in the plan, and whether a
    DEF or a gate netlist names them is not evidence about preservation. They
    stay out of the cross-artefact comparison (their survival is still judged
    by `evaluate_preservation` as before)."""
    plan = _good_plan(n=4)
    names = [i["name"] for i in plan["instances"]]
    plan["spare_pads"] = [{"name": "spare_pad_in_0", "kind": "input",
                           "keep": True}]
    proj = _runner_order_project(tmp_path, plan, names)
    # The pad name is present ONLY in the DEF — an asymmetry that must not
    # be read as mixed provenance.
    fdef = proj / "phase3/stage3/pnr/filled.def"
    fdef.write_text(fdef.read_text().replace(
        "END COMPONENTS",
        "  - spare_pad_in_0 pad + FIXED ( 0 0 ) N ;\nEND COMPONENTS"))
    cp = subprocess.run([sys.executable, str(PRES_SCRIPT), str(proj)],
                        capture_output=True, text=True)
    rpt = json.loads(cp.stdout)
    assert rpt["artefact_agreement"]["disagreements"] == [], rpt
    assert rpt["artefact_agreement"]["recorded_spare_instances"] == 4, rpt


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
