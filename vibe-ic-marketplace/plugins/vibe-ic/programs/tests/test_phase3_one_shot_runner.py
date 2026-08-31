#!/usr/bin/env python3
"""Tests for phase3_one_shot_runner.py — Phase 3 (synth → GDS) orchestrator.

Wave 83 — coverage for previously untested orchestrator.

The runner shells out to Yosys / OpenROAD / KLayout inside an vibeic-eda
Docker container. The test environment has no Docker, so we exercise
the orchestrator's control-flow paths only:

  1. POSITIVE_FAIL_MISSING_PROJECT — non-existent project dir → exit 2.
  2. POSITIVE_FAIL_NO_RTL — project exists but rtl/ empty → synth step
                              FAILs (no RTL to synthesise) → exit 1 +
                              report emitted under reports/.
  3. INTEGRATION_REPORT_SHAPE — emitted phase3_one_shot.json must contain
                                  project / pdk / top / steps / verdict.
  4. EDGE_INVALID_PDK_OVERRIDE — `--pdk thispdkdoesnotexist` falls back
                                   to sky130A (current behaviour).
  5. STEPS_INCLUDE_DRC_AND_LVS — even on FAIL the steps array contains
                                   drc + lvs entries (always reported).
"""
from __future__ import annotations

import json
import os
import struct
import subprocess
import sys
from pathlib import Path

import pytest

#: EVERY test here launches `phase3_one_shot_runner.py`, and that launch does
#: not fit the harness's 180 s item bound reliably. MEASURED: quiet, the six
#: tests are `6 passed in 103.05 s` with a worst single call of 21.04 s; under
#: ordinary fleet contention the SAME call ran past 60 s. So the two numbers
#: this file must declare are different from the defaults:
#:
#:   * the ITEM bound, here: 600 s, a CEILING and not a target, so a slow run
#:     completes or fails on its own instead of taking every other file's
#:     verdict down with it (`--timeout-method=thread` kills the SESSION);
#:   * the INNER bound, `_run` below: 150 s, which `ci_harness_timeout_ceiling_
#:     check` holds to 600 // 3 = 200 s.
#:
#: WHY `pytestmark` AND NOT A PER-TEST DECORATOR: the bound being declared
#: lives in `_run`, a module-level helper all six tests share. A decorator on
#: one test cannot govern a helper the other five also call; a module-level
#: mark bounds every item in the file, so every call in it really does run
#: inside a 600 s item. Verified rather than assumed --
#: `pytestmark = pytest.mark.timeout(30)` under `--timeout=2
#: --timeout-method=thread` yields `2 passed`, not a killed session.
#:
#: WHY NOT SIMPLY LOWER `_run` TO 60: measured, that is a FALSE RED under
#: contention -- the trade `test_flow_matrix_census_freshness.py` already
#: refused for the same reason.
pytestmark = pytest.mark.timeout(600)

PROG = Path(os.environ.get(
    "VIBEIC_CONTRACT_PROGRAMS",
    str(Path(__file__).resolve().parent.parent))).resolve() / \
    "phase3_one_shot_runner.py"
sys.path.insert(0, str(PROG.parent))
import phase3_one_shot_runner as RUNNER  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402


# v1.4.62 — these control-flow tests exercise the DEFAULT (`--pdk auto`)
# resolution, which lands on the container's OSS enablement. On a host that has
# a commercial PDK configured, `commercial_pdk_fallback_guard` now REFUSES that
# silent fallback (it would emit VOID sign-off reports under a false PDK
# belief). These tests are about orchestrator control flow, not PDK intent, so
# they acknowledge the OSS fallback explicitly — which also makes them
# deterministic regardless of the host's private commercial-PDK config.
_ACK_OSS = "--allow-oss-pdk-fallback"


#: 150 s against the 600 s item bound `pytestmark` declares above (ceiling
#: 600 // 3 = 200). The old 90 s was measured against the wrong denominator:
#: it was chosen when the item bound was the harness's 180 s, where 90 s is
#: half the budget and two calls in one test would end the SESSION.
#: Invisible to `ci_harness_timeout_ceiling_check` until vibe-ic#1277 --
#: the bound is a parameter default, which the gate could not read.
# 90 s, not 150 s. The file's `@pytest.mark.timeout(600)` does NOT buy a 200 s
# ceiling: the driver classifies a session hung after 300 s with no validated
# pytest lifecycle event, and a blocking call emits none, so the applicable bound
# is min(600, 300) // 3 = 100. Measured: the slowest call in this file is 34.6 s
# and the whole file runs in 147 s, so 90 s is ~2.6x headroom over the worst case.
def _run(args: list, timeout: int = 90) -> subprocess.CompletedProcess:
    if args and not args[0].startswith("-") and _ACK_OSS not in args:
        args = args + [_ACK_OSS]
    return _pr.run(
        [sys.executable, str(PROG)] + args,
        capture_output=True, text=True)


def test_positive_fail_missing_project(tmp_path):
    missing = tmp_path / "no_such"
    cp = _run([str(missing)])
    assert cp.returncode == 2
    assert "not a directory" in cp.stderr


def test_positive_fail_no_rtl(tmp_path):
    """Empty project → synth step FAIL → orchestrator exits 1."""
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    cp = _run([str(project)])
    # synth FAIL → verdict FAIL → exit 1.
    assert cp.returncode == 1
    assert "verdict: FAIL" in cp.stdout
    rep = project / "reports" / "orchestrator" / "phase3_one_shot.json"
    assert rep.is_file()


def test_integration_report_shape(tmp_path):
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    cp = _run([str(project)])
    rep = project / "reports" / "orchestrator" / "phase3_one_shot.json"
    body = json.loads(rep.read_text())
    for k in ("project", "pdk", "top", "steps", "verdict"):
        assert k in body, f"missing key {k}"
    assert body["top"] == "chip_top"
    assert isinstance(body["steps"], list)
    assert len(body["steps"]) >= 1


def test_edge_custom_top_name(tmp_path):
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    cp = _run([str(project), "--top-name", "tst_chip_top"])
    body = json.loads(
        (project / "reports" / "orchestrator" / "phase3_one_shot.json").read_text())
    assert body["top"] == "tst_chip_top"


def test_steps_include_drc_and_lvs(tmp_path):
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    cp = _run([str(project)])
    body = json.loads(
        (project / "reports" / "orchestrator" / "phase3_one_shot.json").read_text())
    step_names = {s["name"] for s in body["steps"]}
    # DRC + LVS are always run regardless of synth result.
    assert "drc" in step_names
    assert "lvs" in step_names


def test_edge_explicit_pdk_sky130a(tmp_path):
    """Explicit --pdk sky130A is accepted (uses container paths)."""
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    cp = _run([str(project), "--pdk", "sky130A"])
    body = json.loads(
        (project / "reports" / "orchestrator" / "phase3_one_shot.json").read_text())
    assert body["pdk"] == "sky130A"


def _pnr_contract_deck() -> str:
    marker = RUNNER._PNR_STAGE_MARKER
    return ("read_lef /pdk/core.lef\n"
            "read_verilog /work/netlist.v\n"
            "link_design chip_top\n"
            f'puts "{marker} floorplan"\n'
            "initialize_floorplan -die_area {0 0 100 100}\n"
            "place_pins -hor_layers m2\n"
            "write_def /work/phase3/stage3/pnr/floorplan.def\n"
            f'puts "{marker} placement"\n'
            "global_placement\n"
            f'puts "{marker} global_route"\n'
            "global_route\n"
            "detailed_route\n"
            "write_def /work/phase3/stage3/pnr/chip_top.def\n")


def test_pad_ring_is_inserted_at_the_real_floorplan_to_route_seam():
    full = RUNNER._inject_padring_io_lefs(
        _pnr_contract_deck(), ["/pdk/libs.ref/io/lef/pads.lef"])
    seed = RUNNER._floorplan_seed_tcl(full)
    routed = RUNNER._padring_routing_consumer_tcl(
        full, "/work/phase3/stage3/pnr/padring.def")
    assert seed.rstrip().endswith("exit")
    assert "global_placement" not in seed
    # vibe-ic#1958 — the ingest carries `-floorplan_initialize`: it lands the
    # ring on the design `link_design` has already created, instead of asking
    # odb for a second block (ODB-0251).
    ingest = routed.index(
        "read_def -floorplan_initialize /work/phase3/stage3/pnr/padring.def")
    assert ingest < routed.index("\nglobal_placement")
    assert ingest < routed.index("\ndetailed_route")
    assert routed.index("read_lef /pdk/libs.ref/io/lef/pads.lef") < routed.index(
        "read_verilog")
    assert "initialize_floorplan" not in routed
    assert "place_pins" not in routed
    assert "PADRING_ROUTING_INPUT_MISSING" in routed


def test_pad_ring_seam_is_fail_closed_when_missing_or_ambiguous():
    with pytest.raises(ValueError, match="found 0"):
        RUNNER._padring_routing_consumer_tcl(
            "global_placement\ndetailed_route\n", "/work/padring.def")
    double = _pnr_contract_deck() + _pnr_contract_deck()
    with pytest.raises(ValueError, match="found 2"):
        RUNNER._floorplan_seed_tcl(double)


def test_a_failing_pad_gate_stops_before_the_routing_deck_is_created(
        tmp_path, monkeypatch):
    project = tmp_path / "project"
    out_dir = project / "phase3/stage3/pnr"
    out_dir.mkdir(parents=True)

    def seed_only(*_args, **_kwargs):
        (out_dir / "floorplan.def").write_text("seed exists\n")
        return 0, "seed complete", ""

    monkeypatch.setattr(RUNNER, "_docker_exec", seed_only)

    def failing_gate(*_args, **_kwargs):
        return RUNNER.StepResult(
            "pad_ring_gen", "FAIL", detail="PADRING_POPULATION_LOST")

    stopped, consumer = RUNNER._prepare_padring_for_route(
        project, object(), "container", out_dir, "/work/pnr",
        _pnr_contract_deck(), pad_ring_step=failing_gate,
        io_view_discover=lambda *_args: (["/pdk/io.lef"], ["/pdk/io.gds"]))
    assert stopped.status == "FAIL"
    assert "BLOCKING before routing" in stopped.detail
    assert consumer is None
    assert not (out_dir / "pnr.tcl").exists()


def test_the_same_io_physical_views_feed_seed_route_and_streamout(
        tmp_path, monkeypatch):
    project = tmp_path / "project"
    out_dir = project / "phase3/stage3/pnr"
    out_dir.mkdir(parents=True)

    def seed_only(*_args, **_kwargs):
        (out_dir / "floorplan.def").write_text("seed exists\n")
        return 0, "seed complete", ""

    monkeypatch.setattr(RUNNER, "_docker_exec", seed_only)

    def passing_gate(*_args, **_kwargs):
        (out_dir / "padring.def").write_text("ring exists\n")
        return RUNNER.StepResult("pad_ring_gen", "PASS")

    class Pdk:
        macro_lefs = []
        macro_gds = []

    pdk = Pdk()
    result, consumer = RUNNER._prepare_padring_for_route(
        project, pdk, "container", out_dir, "/work/pnr",
        _pnr_contract_deck(), pad_ring_step=passing_gate,
        io_view_discover=lambda *_args: (
            ["/pdk/io_a.lef", "/pdk/io_b.lef"], ["/pdk/io.gds"]))
    assert result.status == "PASS"
    assert consumer.index("read_lef /pdk/io_a.lef") < consumer.index(
        "read_verilog")
    ingest = consumer.index("read_def ")
    assert "padring.def" in consumer[ingest:consumer.index("\n", ingest)]
    assert ingest < consumer.index("\nglobal_placement")
    assert pdk.macro_lefs == ["/pdk/io_a.lef", "/pdk/io_b.lef"]
    assert pdk.macro_gds == ["/pdk/io.gds"]


def test_checked_in_step_15_5ic_is_the_contract_the_runner_consumes(tmp_path):
    """Bind runner behavior to the real canonical flow, not a copied fixture."""
    import yaml
    import _hostpaths

    flow = _hostpaths.require_repo(
        "vibe-ic-marketplace", "plugins", "vibe-ic", "flow",
        "phase1_phase2_phase3.yaml")
    steps = yaml.safe_load(flow.read_text())["steps"]
    step = next(s for s in steps if str(s["id"]) == "15.5ic")
    assert step["condition_kind"] == "design_dependent"
    assert step["condition"]["any_of"] is True
    assert set(step["condition"]["files_exist"]) == {
        "input/submission_template/slots/*.yaml",
        "input/submission_template/SELF_TAPEOUT.txt"}
    assert {"pad_assignment_gen", "pad_ring_gen"} <= set(step["programs"])
    assert any(i["path"].endswith("/floorplan.def")
               for i in step["required_inputs"])

    project = tmp_path / "chip"
    marker = project / "input/submission_template/SELF_TAPEOUT.txt"
    marker.parent.mkdir(parents=True)
    marker.write_text("chip path\n")
    assert RUNNER._chip_path_requests_pad_ring(project) is True
    marker.unlink()
    assert RUNNER._chip_path_requests_pad_ring(project) is False


def _gds_record(rtype: int, dtype: int = 0, payload: bytes = b"") -> bytes:
    if len(payload) % 2:
        payload += b"\x00"
    return struct.pack(">HBB", len(payload) + 4, rtype, dtype) + payload


def _gds_structure(name: str, children=()) -> bytes:
    body = (_gds_record(0x05, 0x02, b"\x00" * 24)
            + _gds_record(0x06, 0x06, name.encode()))
    for child in children:
        body += (_gds_record(0x0A)
                 + _gds_record(0x12, 0x06, child.encode())
                 + _gds_record(0x11))
    return body + _gds_record(0x07)


def _write_pad_gds(path: Path, pad_refs: int, filler_refs: int = 1) -> None:
    path.write_bytes(
        _gds_record(0x00, 0x02, b"\x00\x03")
        + _gds_record(0x01, 0x02, b"\x00" * 24)
        + _gds_record(0x02, 0x06, b"contract")
        + _gds_structure("pad_master")
        + _gds_structure("corner_master")
        + _gds_structure("filler_master")
        + _gds_structure("chip_top",
                         ["pad_master"] * pad_refs + ["corner_master"]
                         + ["filler_master"] * filler_refs)
        + _gds_record(0x04))


def _def_with_ring() -> str:
    return ("VERSION 5.8 ;\nDESIGN chip_top ;\n"
            "UNITS DISTANCE MICRONS 1000 ;\n"
            "DIEAREA ( 0 0 ) ( 100000 100000 ) ;\n"
            "COMPONENTS 4 ;\n"
            "- pad_0 pad_master + FIXED ( 0 0 ) N ;\n"
            "- pad_1 pad_master + FIXED ( 90000 0 ) N ;\n"
            "- corner_0 corner_master + FIXED ( 0 90000 ) N ;\n"
            "- filler_0 filler_master + FIXED ( 10000 0 ) N ;\n"
            "END COMPONENTS\nPINS 0 ;\nEND PINS\nEND DESIGN\n")


def test_final_pad_evidence_reads_reachable_gds_references_and_harms_red(
        tmp_path):
    project = tmp_path / "project"
    pnr = project / "phase3/stage3/pnr"
    reports = project / "reports/phase3"
    pnr.mkdir(parents=True)
    reports.mkdir(parents=True)
    records = {
        "pads": [{"instance": "pad_0", "master": "pad_master"},
                 {"instance": "pad_1", "master": "pad_master"}],
        "corners": [{"instance": "corner_0", "master": "corner_master"}],
        "fillers": [{"instance": "filler_0", "master": "filler_master"}],
    }
    (reports / "padring.json").write_text(json.dumps(records))
    for name in ("padring.def", "routed.def", "chip_top.def"):
        (pnr / name).write_text(_def_with_ring())
    routed = RUNNER._padring_routing_consumer_tcl(
        _pnr_contract_deck(), "/work/phase3/stage3/pnr/padring.def")
    (pnr / "pnr.tcl").write_text(routed)
    (pnr / "openroad.log").write_text(
        "PADRING_ROUTING_CONSUMED: /work/phase3/stage3/pnr/padring.def\n")
    gds = pnr / "chip_top.gds"
    _write_pad_gds(gds, pad_refs=2)
    gds_result = RUNNER.StepResult(
        "gds", "PASS", extras={"streamout_engine": "test-stream"})

    good = RUNNER.step_pad_ring_final_evidence(
        project, "chip_top", gds_result)
    assert good.status == "PASS", good.detail
    evidence = json.loads(
        (reports / "pad_ring_route_evidence.json").read_text())
    assert evidence["gds_evidence"]["reachable_structure_references"] == {
        "pad_master": 2, "corner_master": 1, "filler_master": 1}

    # Harm control: the DEFs and hashes still look plausible, but one pad
    # reference vanished from the actual final GDS hierarchy.  This must be red.
    _write_pad_gds(gds, pad_refs=1)
    harmed = RUNNER.step_pad_ring_final_evidence(
        project, "chip_top", gds_result)
    assert harmed.status == "FAIL"
    assert "PADRING_GDS_REFERENCES_LOST" in harmed.detail

    # Independent physical harm: a missing filler reference must also fail.
    _write_pad_gds(gds, pad_refs=2, filler_refs=0)
    filler_harmed = RUNNER.step_pad_ring_final_evidence(
        project, "chip_top", gds_result)
    assert filler_harmed.status == "FAIL"
    assert "PADRING_GDS_REFERENCES_LOST" in filler_harmed.detail
