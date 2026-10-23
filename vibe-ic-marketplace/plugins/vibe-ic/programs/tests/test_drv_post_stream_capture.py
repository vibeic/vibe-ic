"""R-0929-DRV-IDENTITY: the FINAL, post-stream DRV capture.

Only the capture taken after stream-out and LVS counts toward IC PASS.  It
binds the streamed GDS and the LVS netlist, and the judge proves -- by
re-hashing the files the flow recorded -- that the GDS was streamed from the
judged DEF and that LVS compared that DEF's layout against the judged STA
netlist.  A missing record is NOT_MEASURED; a link to another DEF or netlist is
FAIL.  In-flow captures are unchanged (identity "bound at" this capture).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parent.parent
_TESTS = Path(__file__).resolve().parent
for _p in (str(_PROGRAMS), str(_TESTS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import drv_capture_plan as capture_plan  # noqa: E402
import drv_signoff_judge as drv  # noqa: E402
from test_drv_signoff_judge import (_bundle, _file,  # noqa: E402
                                    _synthetic_scene_profile)  # noqa: F401 (autouse)


def _streamed(tmp_path, *, lvs_status="PASS", gds_def=None, lvs_def=None,
              lvs_netlist_body=None, records=True, verdict_inputs=None):
    """A clean judged bundle whose layout was streamed and LVS-compared, with
    the records the flow writes (GDS admission, LVS inputs, LVS verdict)."""
    bundle = _bundle(tmp_path)
    identity = bundle["identity"]
    project = Path(identity["project"])
    judged_def = Path(identity["artifacts"]["def"]["path"])
    sta_netlist = Path(identity["artifacts"]["sta_netlist"]["path"])
    for name in ("lvs_netlist", "gds_netlist"):     # nothing bound yet
        identity[name] = None
        identity["artifacts"].pop(name, None)
    for rel in ("reports/phase3/gds_admission.json", "reports/phase3/lvs_inputs.json",
                "reports/phase3/lvs_verdict.json"):
        (project / rel).unlink(missing_ok=True)      # this test writes its own
    if records:
        gds = _file(project, "phase3/stage3/pnr/top.gds", "GDSII STREAM\n")
        _file(project, "reports/phase3/gds_admission.json", json.dumps({
            "gds_relpath": "phase3/stage3/pnr/top.gds", "gds_sha256": gds["sha256"],
            "basis_inputs": {"phase3/stage3/pnr/routed.def":
                             gds_def or drv._sha(judged_def)}}))
        schematic = (Path(_file(project, "other_pnr.v", lvs_netlist_body)["path"])
                     if lvs_netlist_body else sta_netlist)
        inputs = _file(project, "reports/phase3/lvs_inputs.json", json.dumps({
            "layout_def": {"path": str(judged_def),
                           "sha256": lvs_def or drv._sha(judged_def)},
            "schematic_netlist": {"path": str(schematic), "sha256": drv._sha(schematic)}}))
        # step 31's verdict names the inputs record of its own compare
        _file(project, "reports/phase3/lvs_verdict.json", json.dumps({
            "status": lvs_status, "compare_performed": True,
            "lvs_inputs": verdict_inputs if verdict_inputs is not None else inputs}))
    bundle["identity"] = capture_plan.post_stream_identity(
        project, {"identity": identity})["identity"]
    return project, bundle


def test_the_final_capture_binds_gds_and_lvs_and_can_pass(tmp_path):
    _, bundle = _streamed(tmp_path)
    identity = bundle["identity"]
    assert identity["capture_point"] == "post_stream" and "bound_at" not in identity
    assert identity["lvs_netlist"] == identity["sta_netlist"] == identity["gds_netlist"]
    assert identity["derivation"]["gds"]["streamed_from_def_sha256"] == \
        identity["artifacts"]["def"]["sha256"]
    result = drv.judge(bundle)
    assert result["final_signoff_capture"] is True
    assert result["verdict"] == "PASS", result["not_measured"] + result["failures"]


def test_a_gds_streamed_from_another_def_fails(tmp_path):
    _, bundle = _streamed(tmp_path, gds_def="f" * 64)
    assert "streamed GDS derives from a DEF other than the judged DEF" in \
        drv.judge(bundle)["failures"]


def test_lvs_of_another_layout_or_netlist_fails(tmp_path):
    _, bundle = _streamed(tmp_path, lvs_def="e" * 64)
    assert "LVS compared a layout DEF other than the judged DEF" in \
        drv.judge(bundle)["failures"]
    _, bundle = _streamed(tmp_path / "n", lvs_netlist_body="module other; endmodule\n")
    result = drv.judge(bundle)
    assert "LVS compared a netlist other than the judged STA netlist" in result["failures"]
    assert "STA/LVS/GDS netlist identity mismatch" in result["failures"]


def test_an_lvs_that_did_not_match_is_not_measured(tmp_path):
    _, bundle = _streamed(tmp_path, lvs_status="FAIL")
    result = drv.judge(bundle)
    assert result["verdict"] == "NOT_MEASURED"
    assert any(n.startswith("LVS did not prove the layout matches")
               for n in result["not_measured"])


def test_without_the_flows_records_the_final_capture_is_not_measured(tmp_path):
    _, bundle = _streamed(tmp_path, records=False)
    result = drv.judge(bundle)
    assert result["verdict"] == "NOT_MEASURED"
    assert {"post-stream GDS admission record absent", "post-stream LVS record absent",
            "lvs_netlist sha256 absent", "gds_netlist sha256 absent"} <= set(result["not_measured"])


def test_a_changed_gds_after_admission_is_not_evidence(tmp_path):
    project, bundle = _streamed(tmp_path)
    (project / "phase3/stage3/pnr/top.gds").write_text("ANOTHER STREAM\n")
    assert any("streamed GDS: sha256 changed" in n for n in drv.judge(bundle)["not_measured"])


# --- the flow -------------------------------------------------------------------

def test_the_post_gds_drv_row_declares_the_final_capture():
    import phase3_one_shot_runner as R
    post = [g for g in R._DECLARED_SIGNOFF_GATES if g[0] == "drv_signoff"]
    pre = [g for g in R._PRESTREAM_GATES if g[0] == "drv_signoff"]
    assert [tuple(g[3]) for g in post] == [("--capture-point", "post_stream")]
    assert [tuple(g[3]) for g in pre] == [()]            # in-flow


def test_the_drv_gate_takes_the_capture_its_row_declares(tmp_path, monkeypatch):
    import phase3_one_shot_runner as R
    seen = []

    def capture(project, *, final_state=None, capture_point="in_flow"):
        seen.append(capture_point)
        raise ValueError("stop after the capture request")

    monkeypatch.setattr(capture_plan, "capture_and_publish", capture)
    for argv in (("--capture-point", "post_stream"), ()):
        row = R._run_declared_signoff_gate(
            tmp_path, "drv_signoff", "drv_signoff_judge.py",
            "reports/phase3/sta/drv_signoff.json", argv)
        assert row.status != "PASS"
    assert seen == ["post_stream", "in_flow"]


def test_the_final_gate_refuses_an_in_flow_bundle(tmp_path):
    _, bundle = _streamed(tmp_path)
    source = tmp_path / "bundle.json"
    out = tmp_path / "out.json"
    source.write_text(json.dumps(bundle))
    drv.main([str(source), "--json", str(out), "--capture-point", "in_flow"])
    assert any("gate judges the in_flow capture but the bundle is post_stream" in n
               for n in json.loads(out.read_text())["not_measured"])


def test_step_lvs_records_the_layout_and_netlist_it_compares(tmp_path, monkeypatch):
    import phase3_one_shot_runner as R
    from test_v0_2_97_issue477_lvs_incomplete import _pdk, _proj
    project = _proj(tmp_path, def_bytes=b"")          # stops at the 0-byte guard
    stale = project / "reports/phase3/lvs_inputs.json"
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_text('{"stale": true}')
    monkeypatch.setattr(R, "_docker_exec", lambda c, cmd, timeout=0, **_: (0, "", ""))
    monkeypatch.setattr(R, "_to_container_path", lambda s, c: s)
    R.step_lvs(project, "chip_top", _pdk(), "x", _direct=True)
    doc = json.loads(stale.read_text())
    layout = project / "phase3/stage3/pnr/chip_top.def"
    assert doc["layout_def"] == {"path": str(layout.resolve()), "sha256": drv._sha(layout)}
    assert Path(doc["schematic_netlist"]["path"]).is_file()
    assert doc["schematic_netlist"]["sha256"] == drv._sha(Path(doc["schematic_netlist"]["path"]))


def test_an_lvs_that_stops_early_leaves_no_earlier_record(tmp_path, monkeypatch):
    import phase3_one_shot_runner as R
    from test_v0_2_97_issue477_lvs_incomplete import _pdk, _proj
    project = _proj(tmp_path)
    (project / "phase3/stage3/pnr/chip_top.def").unlink()   # "LVS inputs missing"
    stale = project / "reports/phase3/lvs_inputs.json"
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_text('{"layout_def": {"sha256": "old"}}')
    monkeypatch.setattr(R, "_docker_exec", lambda c, cmd, timeout=0, **_: (0, "", ""))
    monkeypatch.setattr(R, "_to_container_path", lambda s, c: s)
    R.step_lvs(project, "chip_top", _pdk(), "x")
    assert not stale.exists()


# --- review wave 58 DRVSTACK integrity probes P1 / P3 ----------------------------

def test_p1_a_stale_pass_verdict_of_another_layout_never_passes(tmp_path):
    """Fresh lvs_inputs for the judged DEF + a PASS verdict left by an earlier
    compare of another layout (its own inputs record): not a proof."""
    stale = {"path": str(tmp_path / "old_lvs_inputs.json"), "sha256": "c" * 64}
    _, bundle = _streamed(tmp_path, verdict_inputs=stale)
    result = drv.judge(bundle)
    assert result["verdict"] != "PASS"
    assert "LVS verdict is not bound to the recorded LVS inputs" in result["not_measured"]


def test_a_verdict_that_names_no_inputs_record_never_passes(tmp_path):
    _, bundle = _streamed(tmp_path, verdict_inputs={})
    assert drv.judge(bundle)["verdict"] != "PASS"


def test_p3_the_judge_reads_the_record_not_the_bundles_copy(tmp_path):
    """The inputs record says LVS compared another DEF; the bundle's copied
    field claims the judged DEF.  The record decides."""
    _, bundle = _streamed(tmp_path, lvs_def="e" * 64)
    lvs = bundle["identity"]["derivation"]["lvs"]
    lvs["layout_def_sha256"] = bundle["identity"]["artifacts"]["def"]["sha256"]
    assert "LVS compared a layout DEF other than the judged DEF" in \
        drv.judge(bundle)["failures"]


def test_the_admission_record_not_the_bundle_names_the_streamed_def(tmp_path):
    _, bundle = _streamed(tmp_path, gds_def="f" * 64)
    gds = bundle["identity"]["derivation"]["gds"]
    gds["streamed_from_def_sha256"] = bundle["identity"]["artifacts"]["def"]["sha256"]
    assert "streamed GDS derives from a DEF other than the judged DEF" in \
        drv.judge(bundle)["failures"]


def test_the_schematic_is_bound_by_the_bytes_lvs_recorded(tmp_path):
    """A netlist rewritten after LVS is not the netlist LVS compared."""
    project, bundle = _streamed(tmp_path)
    inputs = json.loads((project / "reports/phase3/lvs_inputs.json").read_text())
    Path(inputs["schematic_netlist"]["path"]).write_text("module rewritten; endmodule\n")
    bundle["identity"] = capture_plan.post_stream_identity(
        project, {"identity": bundle["identity"]})["identity"]
    assert bundle["identity"]["lvs_netlist"] == inputs["schematic_netlist"]["sha256"]
    assert drv.judge(bundle)["verdict"] != "PASS"


def test_step31_start_clears_both_lvs_records_in_librelane_mode(tmp_path, monkeypatch):
    """The LibreLane half returns from the dispatch and writes no inputs
    record: a direct-mode record from an earlier run must not survive."""
    import phase3_one_shot_runner as R
    from test_v0_2_97_issue477_lvs_incomplete import _pdk, _proj
    project = _proj(tmp_path)
    for rel in ("reports/phase3/lvs_inputs.json", "reports/phase3/lvs_verdict.json"):
        _file(project, rel, '{"stale": true}')
    seen = {}

    def librelane_half(p, top, pdk, half, publish):
        seen["records"] = [(p / "reports/phase3" / n).exists()
                           for n in ("lvs_inputs.json", "lvs_verdict.json")]
        return R.StepResult(half, "PASS", 0.0, "tool half")
    monkeypatch.setattr(R, "_step31_librelane", librelane_half)
    monkeypatch.setattr(R, "_vacuous_on_unrouted", lambda *a: None)
    import librelane_contract
    monkeypatch.setattr(librelane_contract, "selected_mode", lambda p, s: "librelane")
    R.step_lvs(project, "chip_top", _pdk(), "x")
    assert seen["records"] == [False, False]


def test_step_lvs_verdict_names_its_own_inputs_record(tmp_path, monkeypatch):
    import phase3_one_shot_runner as R
    from test_v0_2_97_issue477_lvs_incomplete import _pdk, _proj
    project = _proj(tmp_path, def_bytes=b"")          # stops at the 0-byte guard
    monkeypatch.setattr(R, "_docker_exec", lambda c, cmd, timeout=0, **_: (0, "", ""))
    monkeypatch.setattr(R, "_to_container_path", lambda s, c: s)
    R.step_lvs(project, "chip_top", _pdk(), "x", _direct=True)
    inputs = project / "reports/phase3/lvs_inputs.json"
    verdict = json.loads((project / "reports/phase3/lvs_verdict.json").read_text())
    assert verdict["lvs_inputs"]["sha256"] == drv._sha(inputs)
