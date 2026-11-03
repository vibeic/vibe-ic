"""A7 post-layout producer: LibreLane Magic.RCX + A4's ngspice resim (T94).

A7 had no deterministic producer (the runner WAIVED it to a skill). The
producer is `analog_a7_post_layout_emit`; MEASURED on vibeic-eda 0.3.77 /
u_hawaii_adc/ldo it extracts five ngspice styles at depth RC (269..1158 R,
85..123 C) and the A7 gate certifies the comparison it writes.

The end-to-end tests drive the shipped `run()` — the real
`librelane_contract.resolve_step_config` / `run_chain`, the real
`magic_extract_spice_emit` audit and A4's real `_run_ngspice` — against a stub
`docker` that only plays the TOOLS: it writes what `librelane.steps run
--id Magic.RCX` writes (state_out.json + the SPICE_RCX file) and prints the
measurement line ngspice prints. Nothing inside vibe-ic is monkeypatched.
"""
from __future__ import annotations

import json
import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest


import _plugin_tree  # noqa: F401 — puts programs/ on sys.path
import _eda_pin as PIN
import _analog_producer_common as PC
import analog_a7_post_layout_emit as A7

PROGRAMS = Path(_plugin_tree.plugin_path("programs"))
from _stated_eda_image import stated_image, state_the_image  # noqa: E402

# STATED, not resolved at import: `PIN.IMAGE_DIGEST` here asked this host's
# docker while the module was collected, so inside the image (no docker) the
# whole file was a collection error. The identity is stated at `_eda_pin`, and
# every read of `PIN.IMAGE_DIGEST` below still goes through it.
IMAGE = stated_image()


@pytest.fixture(autouse=True)
def _stated_identity(monkeypatch):
    state_the_image(monkeypatch)

RCX_RC = """* NGSPICE file created from blk.ext - technology: t
.subckt blk a.n1 b vss a x.t1
X0 a.n1 x.t1 vss vss nfet w=1u l=1u
R0 a a.n1 12.5
R1 x.t1 b 3.0
C0 a.n1 vss 1.2f
C1 b vss 0.4f
.ends
"""
RCX_NONE = """* NGSPICE file created from blk.ext - technology: t
.subckt blk a b vss
X0 a b vss vss nfet w=1u l=1u
.ends
"""

TECH = """tech
  format 35
  t
end
include t-extract
"""
TECH_EXTRACT = """extract
 style ngspice variants (),(lvs),(hrhc)
 cscale 1
end
"""


# ── pure helpers ───────────────────────────────────────────────────────────
def test_styles_come_from_the_technology_and_skip_the_device_only_variant(
        tmp_path):
    (tmp_path / "t.tech").write_text(TECH)
    (tmp_path / "t-extract.tech").write_text(TECH_EXTRACT)
    assert A7.extraction_styles(tmp_path / "t.tech") == [
        "ngspice()", "ngspice(hrhc)"]
    assert A7.extraction_styles(tmp_path / "absent.tech") == []


def test_the_wrapper_keeps_the_declared_port_order_and_splits_no_node():
    text, mapping = A7.post_layout_netlist(
        "blk", ["a", "b", "vss"], RCX_RC, [".lib ../m.lib tt"])
    assert ".subckt blk__rcx a.n1 b vss a x.t1" in text
    assert ".subckt blk a b vss" in text
    # a split node Magic exported is private, never shorted onto its net
    assert mapping["a.n1"] != "a" and mapping["x.t1"].startswith("rcx_int_")
    assert "xrcx rcx_int_0 b vss a rcx_int_4 blk__rcx" in text
    assert text.index(".lib ../m.lib tt") < text.index(".subckt blk__rcx")


def test_a_declared_port_the_extraction_does_not_expose_is_refused():
    with pytest.raises(ValueError, match="A7_RCX_PORT_MISSING"):
        A7.post_layout_netlist("blk", ["a", "b", "vdd"], RCX_RC, [])


def test_the_testbench_must_include_the_block_netlist_exactly_once(tmp_path):
    tb = ".include blk.sp\n.lib ../../m.lib tt\nX1 a b 0 blk\n.end\n"
    out = A7.post_layout_testbench(tb, "blk", "blk_post.sp", tmp_path,
                                   tmp_path / "post_layout")
    assert ".include blk_post.sp" in out
    assert ".lib ../../../m.lib tt" in out
    pre = A7.post_layout_testbench(tb, "blk", None, tmp_path,
                                   tmp_path / "post_layout")
    assert ".include ../blk.sp" in pre
    for bad in ("X1 a b 0 blk\n", ".include blk.sp\n.include blk.sp\n"):
        with pytest.raises(ValueError, match="A7_TB_INCLUDE_AMBIGUOUS"):
            A7.post_layout_testbench(bad, "blk", "p.sp", tmp_path, tmp_path)


# ── the producer, end to end, against a stub docker ───────────────────────
STUB = r'''#!/usr/bin/env python3
import json, os, re, subprocess, sys
a = sys.argv[1:]
j = " ".join(a)
if a[0] == "inspect":
    if "Mounts" in j:
        print(json.dumps([{"Type": "bind", "Source": os.environ["STUB_ROOT"],
                           "Destination": os.environ["STUB_ROOT"]}]))
    else:
        print("sha256:aaaa\trepo@" + os.environ["STUB_DIGEST"])
    sys.exit(0)
if a[0] == "run":
    if "--help" in j:                                   # image capability
        sys.exit(0)
    if "-c" in a and "Config.load" in a[-1]:            # resolve_step_config
        src = re.search(r"p='([^']+)'", a[-1]).group(1)
        out = re.search(r"out='([^']+)'", a[-1]).group(1)
        cfg = json.load(open(src))
        cfg["MAGIC_TECH"] = os.environ["STUB_TECH"]
        open(out, "w").write(json.dumps(cfg))
        sys.exit(0)
    if "librelane.steps" in a:                           # the Magic.RCX step
        folder = a[a.index("-o") + 1]
        state_in = json.load(open(a[a.index("-i") + 1]))
        os.makedirs(folder, exist_ok=True)
        rcx = os.path.join(folder, "blk.rcx.spice")
        open(rcx, "w").write(open(os.environ["STUB_RCX"]).read())
        state_in["spice_rcx"] = rcx
        open(os.path.join(folder, "state_out.json"), "w").write(
            json.dumps(state_in))
        sys.exit(0)
    sys.exit(1)
if a[0] == "exec":
    cmd = a[-1]
    if "--json-measure" in cmd:
        print("unrecognized option"); sys.exit(0)
    if "command -v ngspice" in cmd:
        print("/foss/tools/bin/ngspice"); sys.exit(0)
    if " -b " in cmd:
        deck = cmd.split()[-2].strip("'")
        print("MEAS vout= " + ("1.19" if "_post_" in deck else "1.20"))
        sys.exit(0)
    sys.exit(subprocess.run(["bash", "-c", cmd]).returncode)
sys.exit(0)
'''


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "proj"
    b = project / "phase3" / "analog" / "blk"
    b.mkdir(parents=True)
    tech_dir = tmp_path / "pdkroot" / "tpdk" / "libs.tech" / "magic"
    tech_dir.mkdir(parents=True)
    (tech_dir / "t.tech").write_text(TECH)
    (tech_dir / "t-extract.tech").write_text(TECH_EXTRACT)
    (b / "blk.gds").write_bytes(b"\x00\x06\x00\x02\x02\x58")
    (b / "blk.sp").write_text(
        ".lib ../../../models/m.lib tt\n.subckt blk a b vss\n"
        "X0 a b vss vss nfet w=1u l=1u\n.ends blk\n")
    (b / "layout_provenance.json").write_text(json.dumps({
        "producer": "analog_a5_layout_emit", "result": "OK",
        "pdk_sources": {"magic_tech": str(tech_dir / "t.tech")},
        "netlist_content_sha256": PC.content_digest((b / "blk.sp").read_text())}))
    (b / "tb_blk.sp").write_text(
        ".include blk.sp\nV1 a 0 1.8\nX1 a b 0 blk\n.op\n.end\n")
    (b / "corner_results.json").write_text(json.dumps(
        {"design_content": "structure_and_geometry",
         "corners": [{"simulator_run": True}]}))
    (project / "phase3" / "analog" / "analog_block_list.json").write_text(
        json.dumps({"blocks": [{"name": "blk", "type": "ldo"}]}))
    return project


@pytest.fixture
def stub(tmp_path, monkeypatch):
    d = tmp_path / "bin"
    d.mkdir()
    (d / "docker").write_text(STUB)
    (d / "docker").chmod(0o755)
    monkeypatch.setenv("PATH", f"{d}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("STUB_ROOT", str(tmp_path))
    monkeypatch.setenv("STUB_DIGEST", PIN.IMAGE_DIGEST)
    monkeypatch.setenv("STUB_TECH",
                       str(tmp_path / "pdkroot/tpdk/libs.tech/magic/t.tech"))
    monkeypatch.setenv("VIBEIC_DESIGNS_HOST_ROOT", str(tmp_path))
    import analog_real_corner_sweep as ARS
    ARS._NGSPICE_CACHE.clear()
    ARS._JSON_MEASURE_SUPPORT.clear()
    ARS._CONTAINER_PATH_CACHE.clear()
    return tmp_path


def _rcx(tmp_path, text):
    p = tmp_path / "rcx.spice"
    p.write_text(text)
    os.environ["STUB_RCX"] = str(p)


def test_the_producer_writes_a_comparison_the_a7_gate_certifies(stub):
    project = _project(stub)
    _rcx(stub, RCX_RC)
    assert A7.run(project, "blk", "vibeic-eda", IMAGE) == 0
    bdir = project / "phase3/analog/blk"
    doc = json.loads((bdir / "pre_vs_post.json").read_text())
    assert [s["name"] for s in doc["specs"]] == ["vout@ngspice()",
                                                 "vout@ngspice(hrhc)"]
    assert all((s["pre_value"], s["post_value"]) == (1.20, 1.19)
               for s in doc["specs"])
    assert (project / doc["_provenance"]["extracted_netlist"]).is_file()
    gds = bdir / "blk.gds"
    expected_layout_sha = hashlib.sha256(gds.read_bytes()).hexdigest()
    assert doc["_provenance"]["layout_path"] == \
        "phase3/analog/blk/blk.gds"
    assert doc["_provenance"]["layout_sha256"] == expected_layout_sha
    rec = json.loads((bdir / "a7_post_layout.json").read_text())
    assert [c["depth"] for c in rec["corners"]] == ["RC", "RC"]
    assert rec["layout_sha256"] == expected_layout_sha
    # nothing the resimulation wrote lands beside the A3 deck
    assert sorted(p.name for p in bdir.iterdir() if p.is_file()) == sorted([
        "a7_post_layout.json", "blk.gds", "blk.sp", "corner_results.json",
        "layout_provenance.json", "pre_vs_post.json", "tb_blk.sp"])
    # every extraction ran through the contract, one step dir per style
    assert len(list((project / "phase3/librelane/analog/blk").glob(
        "a7_*/01-magic-rcx/vibeic_receipt.json"))) == 2
    cp = subprocess.run([sys.executable,
                         str(PROGRAMS / "analog_a7_post_layout_resim_check.py"),
                         str(project), "--block", "blk"],
                        capture_output=True, text=True)
    assert cp.returncode == 0, cp.stdout + cp.stderr


def test_a7_gate_rejects_current_layout_mutation(stub):
    """The fixed producer record cannot certify bytes changed after A7."""
    project = _project(stub)
    _rcx(stub, RCX_RC)
    assert A7.run(project, "blk", "vibeic-eda", IMAGE) == 0
    gds = project / "phase3/analog/blk/blk.gds"
    gds.write_bytes(gds.read_bytes() + b"MUTATION_AFTER_A7")
    cp = subprocess.run(
        [sys.executable, str(PROGRAMS /
         "analog_a7_post_layout_resim_check.py"), str(project),
         "--block", "blk"], capture_output=True, text=True)
    assert cp.returncode == 1, cp.stdout + cp.stderr
    assert "A7_LAYOUT_MUTATED" in (cp.stdout + cp.stderr)


def test_a7_gate_rejects_a_producer_record_without_layout_binding(stub):
    project = _project(stub)
    _rcx(stub, RCX_RC)
    assert A7.run(project, "blk", "vibeic-eda", IMAGE) == 0
    record_path = project / "phase3/analog/blk/a7_post_layout.json"
    record = json.loads(record_path.read_text())
    del record["layout_sha256"]
    record_path.write_text(json.dumps(record))
    cp = subprocess.run(
        [sys.executable, str(PROGRAMS /
         "analog_a7_post_layout_resim_check.py"), str(project),
         "--block", "blk"], capture_output=True, text=True)
    assert cp.returncode == 1, cp.stdout + cp.stderr
    assert "A7_LAYOUT_PROVENANCE_INVALID" in (cp.stdout + cp.stderr)


def test_rcx_inventory_accepts_only_the_layouts_declared_grid_snap(stub):
    """A5's Magic grid is 0.01 um; a 2.25326 um cap draws as 2.25 um.

    The extracted device still has the same model, count and physical shape
    within half the attested grid. A farther change remains a mismatch.
    """
    project = _project(stub)
    bdir = project / "phase3/analog/blk"
    net = bdir / "blk.sp"
    net.write_text(net.read_text().replace(
        ".ends blk\n", "Xcap a b cap_cmim w=10u l=2.25326u\n.ends blk\n"))
    lay = bdir / "layout_provenance.json"
    provenance = json.loads(lay.read_text())
    provenance.update(lambda_per_um=100,
                      netlist_content_sha256=PC.content_digest(net.read_text()))
    lay.write_text(json.dumps(provenance))
    _rcx(stub, RCX_RC.replace(
        ".ends\n", "Xcap a b cap_cmim w=10u l=2.25u\n.ends\n"))

    assert A7.run(project, "blk", "vibeic-eda", IMAGE, ["ngspice()"]) == 0
    record = json.loads((bdir / "a7_post_layout.json").read_text())
    assert record["corners"][0]["device_inventory"]["result"] == "MATCH"
    assert record["corners"][0]["device_inventory"]["layout_grid_um"] == 0.01

    a3 = A7.device_instances(net.read_text(), "blk")
    farther = A7.device_instances(RCX_RC.replace(
        ".ends\n", "Xcap a b cap_cmim w=10u l=2.26u\n.ends\n"), "blk")
    assert A7.device_inventory(a3, farther, set(),
                               layout_grid_m=1e-8)["result"] == "MISMATCH"


def test_a_parasitic_free_extraction_is_refused_and_writes_no_comparison(
        stub):
    project = _project(stub)
    _rcx(stub, RCX_NONE)
    assert A7.run(project, "blk", "vibeic-eda", IMAGE) == 1
    bdir = project / "phase3/analog/blk"
    assert not (bdir / "pre_vs_post.json").exists()
    rec = json.loads((bdir / "a7_post_layout.json").read_text())
    assert rec["rule"] == "A7_RCX_PARASITIC_FREE"


def test_an_absent_layout_is_an_honest_gap(stub):
    project = _project(stub)
    (project / "phase3/analog/blk/blk.gds").unlink()
    assert A7.run(project, "blk", "vibeic-eda", IMAGE) == 2


def test_the_runner_invokes_the_producer_by_default_and_direct_is_opt_out(
        tmp_path, monkeypatch):
    import analog_one_shot_runner as R
    project = _project(tmp_path)
    calls = []
    real_run = R._pr.run

    class _CP:
        returncode, stdout, stderr = 2, "", "HONEST_GAP: x"

    def fake_run(cmd, *a, **k):
        if any(str(x).endswith("analog_a7_post_layout_emit.py") for x in cmd):
            calls.append(cmd)
            return _CP()
        return real_run(cmd, *a, **k)

    monkeypatch.setattr(R._pr, "run", fake_run)
    monkeypatch.setattr(R._pin, "container_image_digest",
                        lambda c: (PIN.IMAGE_DIGEST, ""))
    R.step_for_block(project, {"name": "blk", "type": "ldo"},
                     "A7_post_layout_resim", None)
    assert len(calls) == 1
    assert calls[0][calls[0].index("--image") + 1].endswith(PIN.IMAGE_DIGEST)
    assert "@" in calls[0][calls[0].index("--image") + 1]
    (project / "phase3/librelane_switch.json").write_text(
        json.dumps({"steps": {"A7": "direct"}}))
    R.step_for_block(project, {"name": "blk", "type": "ldo"},
                     "A7_post_layout_resim", None)
    assert len(calls) == 1
    (project / "phase3/librelane_switch.json").write_text(
        json.dumps({"steps": {"A7": "librelane"}}))
    R.step_for_block(project, {"name": "blk", "type": "ldo"},
                     "A7_post_layout_resim", None)
    assert len(calls) == 2
    assert calls[-1][calls[-1].index("--image") + 1].endswith(PIN.IMAGE_DIGEST)
    assert "@" in calls[-1][calls[-1].index("--image") + 1]


# Neutral API mocks: the real producer runs, while every tool boundary is replaced.
@pytest.fixture
def metrics_mock_project(tmp_path, monkeypatch):
    import librelane_contract as lc
    import analog_real_corner_sweep as ars
    import _designs_root as dr
    project = _project(tmp_path)
    monkeypatch.setattr(dr, "resolve_host_root", lambda *args: project)
    monkeypatch.setattr(ars, "_container_path", lambda container, root, path: str(path))
    def resolve(project, image, src, target, **kw):
        target.write_text(src.read_text())
        return target
    def extract(project, image, steps, **kw):
        folder = project / "mock_rcx" / Path(steps[0][1]).stem
        folder.mkdir(parents=True, exist_ok=True)
        rcx = folder / "view.sp"
        rcx.write_text(RCX_RC)
        (folder / "state_out.json").write_text(json.dumps({"spice_rcx": str(rcx)}))
        return [folder]
    monkeypatch.setattr(lc, "resolve_step_config", resolve)
    monkeypatch.setattr(lc, "run_chain", extract)
    monkeypatch.setattr(ars, "_docker", lambda *a, **kw: pytest.fail("unmocked Docker tool boundary"))
    monkeypatch.setattr(ars, "_run_ngspice", lambda *a, **kw: (True, {"gain": 10.0}, "neutral mock", {"rc": 0}))
    return project


def _a7_metrics(project):
    return json.loads((project / "reports" / "metrics" / "a7.json").read_text())


def test_a7_metrics_emits_real_terminal_counts(metrics_mock_project):
    project = metrics_mock_project
    assert A7.run(project, "blk", "mock", IMAGE, ["ngspice()", "ngspice(hrhc)"]) == 0
    row = _a7_metrics(project)
    assert row == {"a7__flow__block": "blk", "a7__flow__producer_result": "PRODUCED",
                   "a7__flow__rule": None, "a7__flow__reason_class": None,
                   "a7__flow__pair_count": 2, "a7__flow__measured_style_count": 2,
                   "a7__flow__completed_style_count": 2}
    rec = json.loads((project / "phase3/analog/blk/a7_post_layout.json").read_text())
    assert rec["result"] == "PRODUCED" and rec["compared_specs_count"] == 2


@pytest.mark.parametrize("terminal", ["refused", "unmeasured", "stopped"], ids=["refused", "unmeasured", "stopped"])
def test_a7_metrics_clears_prior_invocation_counts(metrics_mock_project, monkeypatch, terminal):
    import analog_real_corner_sweep as ars
    project = metrics_mock_project
    assert A7.run(project, "blk", "mock", IMAGE, ["ngspice()"]) == 0
    before = _a7_metrics(project)
    assert before["a7__flow__producer_result"] == "PRODUCED" and before["a7__flow__pair_count"] == 1
    if terminal == "refused":
        (project / "phase3/analog/blk/blk.gds").unlink()
        expected_rc, expected_result, rule = 2, "NOT_PRODUCED", "A7_INPUT_ABSENT"
    elif terminal == "unmeasured":
        (project / "phase3/analog/blk/tb_blk.sp").write_text(".include blk.sp\n.meas op absent find v(a)\n.end\n")
        monkeypatch.setattr(ars, "_run_ngspice", lambda *a, **kw: (True, {}, "neutral mock", {"rc": 0}))
        expected_rc, expected_result, rule = A7.EX_BUDGET_EXHAUSTED, "NOT_MEASURED", "A7_PRE_MEASUREMENT_ABSENT"
    else:
        monkeypatch.setattr(ars, "_run_ngspice", lambda *a, **kw: (False, {}, "neutral mock", {"rc": 1, "stopped": True}))
        expected_rc, expected_result, rule = A7.EX_BUDGET_EXHAUSTED, "NOT_MEASURED", "A7_SIMULATION_STOPPED_EXTERNALLY"
    assert A7.run(project, "blk", "mock", IMAGE, ["ngspice()"]) == expected_rc
    row = _a7_metrics(project)
    assert row["a7__flow__block"] == "blk" and row["a7__flow__producer_result"] == expected_result
    assert row["a7__flow__rule"] == rule
    expected_count = 0 if terminal == "unmeasured" else None
    assert row["a7__flow__pair_count"] == expected_count
    assert row["a7__flow__measured_style_count"] == expected_count
    assert row["a7__flow__completed_style_count"] == (1 if terminal == "unmeasured" else None)


def test_a7_metrics_sink_failure_preserves_producer_rc(metrics_mock_project, capsys):
    project = metrics_mock_project
    (project / "reports").write_text("a regular file refuses the metrics directory")
    assert A7.run(project, "blk", "mock", IMAGE, ["ngspice()"]) == 0
    captured = capsys.readouterr()
    assert "[step_metrics] EMIT FAILED" in captured.err
    rec = json.loads((project / "phase3/analog/blk/a7_post_layout.json").read_text())
    assert rec["result"] == "PRODUCED" and rec["compared_specs_count"] == 1


def test_a7_metrics_partial_measured_fail_keeps_precedence(metrics_mock_project, monkeypatch):
    import analog_real_corner_sweep as ars
    project = metrics_mock_project
    (project / "phase3/analog/blk/tb_blk.sp").write_text(".include blk.sp\n.meas op absent find v(a)\n.end\n")
    responses = iter([(True, {"gain": 10.0}, "pre mock", {"rc": 0}),
                      (True, {"gain": 15.0}, "post mock", {"rc": 0})])
    monkeypatch.setattr(ars, "_run_ngspice", lambda *a, **kw: next(responses))
    assert A7.run(project, "blk", "mock", IMAGE, ["ngspice()"]) == 1
    row = _a7_metrics(project)
    assert row["a7__flow__producer_result"] == "REFUSED"
    assert row["a7__flow__rule"] == "A7_POSTSIM_DELTA_TOO_BIG"
    assert row["a7__flow__pair_count"] == 1
    assert row["a7__flow__completed_style_count"] == row["a7__flow__measured_style_count"] == 1
