"""The DRV stack x F15 / CAPSCOPE merge notes (root, 2026-09-29), folded.

1. F15's "the DRV bundle's routed DEF must be the DEF STAPostPNR timed" binds
   the step-23 (in-flow) capture only; the FINAL capture binds the shipped
   DEF/GDS through its post-stream derivation (step 32 repair / step 34 fill
   may change the DEF after step 23 timed it).
2. One DEF-identity comparison, shared by the CLI and step 32.
3. The runner names the judge's REFUSED record instead of "receipt unreadable".
4. io_disclosure requires measured > the tool limit: with the design-scope
   0.2 pF margin every IO pin carries limit 0.2 (R-0929-CAP-MARGIN-SCOPE).
"""
import json
import sys
import pytest
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import drv_signoff_judge as drv  # noqa: E402
import test_f15_step23_gates_read_the_tool_arm as F  # noqa: E402
from test_drv_signoff_judge import (_bundle, _file, _violate,  # noqa: E402
                                    _synthetic_scene_profile)  # noqa: F401 (autouse)


def _other_def_bundle(tmp_path):
    project = F.gate_inputs(F.tool_project(tmp_path))
    routed = F._write(project / "phase3/stage3/pnr/routed.def", "DESIGN other ;\n")
    F._write(project / "reports/phase3/sta/drv_signoff_bundle.json", json.dumps({
        "identity": {"artifacts": {"def": {"sha256": F._sha(routed)}}}}))
    return project


def _timed(project, tmp_path, *argv):
    out = tmp_path / "drv.json"
    drv.main([str(project), "--json", str(out), *argv])
    return [r for r in json.loads(out.read_text()).get("not_measured", [])
            if "STAPostPNR timed" in r]


def test_the_final_capture_is_not_bound_to_the_def_step23_timed(tmp_path):
    project = _other_def_bundle(tmp_path)
    assert _timed(project, tmp_path, "--capture-point", "post_stream") == []


def test_an_in_flow_capture_still_is(tmp_path):
    """Control (F15's own rule, both spellings of an in-flow gate)."""
    project = _other_def_bundle(tmp_path)
    assert _timed(project, tmp_path, "--capture-point", "in_flow")
    assert _timed(project, tmp_path / "b")


def test_one_def_identity_comparison(tmp_path):
    layout = _file(tmp_path, "a.def", "DESIGN a ;\n")
    bundle = {"identity": {"artifacts": {"def": {"sha256": layout["sha256"]}}}}
    assert drv.def_identity(bundle, Path(layout["path"])) is None
    assert drv.def_identity(bundle, tmp_path / "missing.def") == "absent"
    assert drv.def_identity(bundle, Path(_file(tmp_path, "b.def", "x\n")["path"])) == "differs"
    assert drv.def_identity({}, Path(layout["path"])) == "differs"


def test_step32_names_its_final_def_through_the_shared_comparison(tmp_path, monkeypatch):
    import librelane_postroute_repair as prr
    import drv_capture_plan
    project = tmp_path / "p"
    bundle = {"identity": {"artifacts": {"def": {"sha256": "0" * 64}}}}
    monkeypatch.setattr(drv_capture_plan, "capture_and_publish", lambda *a, **k: _file(
        project, "reports/phase3/sta/drv_signoff_bundle.json", json.dumps(bundle)))
    monkeypatch.setattr(drv, "judge", lambda b, project=None: {"verdict": "PASS"})
    seen = []
    real = drv.def_identity
    monkeypatch.setattr(drv, "def_identity", lambda b, p: seen.append(p) or real(b, p))
    final = _file(project, "final.def", "DESIGN final ;\n")
    state = _file(project, "state.json", json.dumps({"def": final["path"]}))
    report = {"final": {"sta_state": state["path"]}, "adopted_state": state["path"]}
    prr._step32_drv_signoff(project, report)
    assert seen == [Path(final["path"])]
    assert report["drv_signoff"]["verdict"] == "NOT_MEASURED"
    assert "step 32 final routed DEF differs from judged layout identity" in \
        report["drv_signoff"]["not_measured"]


def test_the_runner_names_the_judges_refusal(tmp_path, monkeypatch):
    import phase3_one_shot_runner as R
    import drv_capture_plan
    monkeypatch.setattr(drv_capture_plan, "capture_and_publish", lambda *a, **k: None)
    out = tmp_path / "reports/phase3/sta/drv_signoff.json"

    def run(cmd, **kw):
        _file(tmp_path, "reports/phase3/sta/drv_signoff.json", json.dumps({
            "name": "DRV(tran/cap/fanout)", "verdict": "REFUSED",
            "refusal": "LL_STA_ARTEFACT_UNBOUND", "reason": "tool arm unreadable"}))
        return SimpleNamespace(returncode=1, stdout="REFUSED DRV", stderr="")
    monkeypatch.setattr(R._pr, "run", run)
    row = R._run_declared_signoff_gate(tmp_path, "drv_signoff", "drv_signoff_judge.py",
                                       str(out.relative_to(tmp_path)), ())
    assert row.status != "PASS"
    assert "DRV judge REFUSED (LL_STA_ARTEFACT_UNBOUND)" in row.detail, row.detail
    assert "unreadable" not in row.detail.split("tool arm unreadable")[0]


def _io_bundle(tmp_path):
    bundle = _bundle(tmp_path)
    io = _file(tmp_path, "io.lib", '''library (io) {
 time_unit : "1ns"; capacitive_load_unit (1, pf);
 nom_process : 1; nom_voltage : 5; nom_temperature : 25;
 default_max_capacitance : 999;
 cell (pad) { pad_cell : true; pin (Y) { direction : output; } }
}''')
    bundle["current"]["liberties"].append({"name": "io", **io})
    bundle["frozen"]["liberties"]["io"] = io["sha256"]
    for key in ("frozen", "current"):
        bundle[key]["scene_liberties"]["typ_nom"].append("io")
    bundle["scenes"][0]["linked_liberties"].append({"name": "io", **io})
    bundle["scenes"][0]["liberty"] = "io"
    bundle["pins"]["u/Y"].update(liberty="io", cell="pad", driver_cell="pad",
                                 cell_class="IO", net_class="IO")
    return bundle


def test_an_io_pin_under_its_tool_limit_is_not_a_disclosure(tmp_path):
    bundle = _io_bundle(tmp_path)
    _violate(bundle, tmp_path, "max_capacitance", value=.1, limit=.2,
             net_class="IO", cell_class="IO")
    bundle["scenes"][0]["counters"]["max_capacitance"] = 0
    scene = bundle["scenes"][0]
    scene["counter_report"] = _file(tmp_path, "counter.log", "".join(
        f"DRV_COUNTER {k} {scene['counters'][k]}\n" for k in drv.KINDS))
    from test_drv_signoff_judge import _report, _refresh_scripts
    scene["report"] = _file(tmp_path, "violators.rpt", _report(
        fanout=2, cap=.1, cap_limit=.2, violators=True))
    _refresh_scripts(bundle, tmp_path)
    result = drv.judge(bundle)
    assert result["io_margin_disclosures"] == [], result["io_margin_disclosures"]
    assert result["verdict"] == "PASS", result["not_measured"] + result["failures"]


def test_an_io_pin_over_its_tool_limit_still_is(tmp_path):
    """Control (DRV standard section 4: listed, not gated)."""
    bundle = _io_bundle(tmp_path)
    _violate(bundle, tmp_path, "max_capacitance", value=.3, limit=.2,
             net_class="IO", cell_class="IO")
    result = drv.judge(bundle)
    assert result["verdict"] == "PASS"
    assert [r["failed_tier"] for r in result["io_margin_disclosures"]] == [
        "IO_STD_CELL_MARGIN_DISCLOSURE"]


# --- review wave 58 MINORs --------------------------------------------------------

def test_the_step23_audit_clause_judges_only_the_final_capture(tmp_path):
    """The flow's own step-23 clause, run as written against an in-flow bundle
    left on disk (it binds no GDS / LVS): never a PASS, and named."""
    import re
    import shlex
    flow = (HERE.parent.parent / "flow/phase1_phase2_phase3.yaml").read_text()
    clause = re.search(r'program_exit_zero: "(drv_signoff_judge [^"]*)"', flow).group(1)
    argv = shlex.split(clause)[1:]
    project = tmp_path / "p"
    bundle = _bundle(tmp_path)
    bundle["identity"]["capture_point"] = "in_flow"
    _file(project, "reports/phase3/sta/drv_signoff_bundle.json", json.dumps(bundle))
    argv = [str(project) if a == "." else
            str(project / a) if a.startswith("reports/") else a for a in argv]
    assert drv.main(argv) == 1
    doc = json.loads((project / "reports/phase3/sta/drv_signoff_verdict.json").read_text())
    assert "gate judges the post_stream capture but the bundle is in_flow" in \
        doc["not_measured"], doc["not_measured"]


@pytest.fixture
def legacy_tail_transport(monkeypatch):
    """Use the imported raw-transport driver's own mode and runtime isolation."""
    from test_r0929_tail_continues import diagnostic_transport_mode
    diagnostic_transport_mode.__wrapped__(monkeypatch)


@pytest.mark.parametrize("status", ["PASS", "WAIVED", "FAIL"])
def test_step32_lets_an_owner_waived_row_reach_stream_out(tmp_path, monkeypatch,
                                                       status, legacy_tail_transport):
    """R-0930-TAIL-TEST-MIGRATION: judge usable inputs, retain upstream status.

    The old AST assertion required a removed status-only chain stop. Drive
    main() instead: waived and failed rows both permit measurement, and neither
    can admit a release. Adjacent missing-route controls retain the stop rule.
    """
    import phase3_one_shot_runner as R
    import test_r0929_tail_continues as tail
    project = tail._project(tmp_path, cached_die=tail.OLD_DIE, cached_util=tail.OLD_UTIL)
    if status == "PASS":
        # The integration subject is Step32 -> stream scheduling, not a chip
        # pad-ring claim.  Use the real delivery declaration reader to select
        # a legal HARDMACRO stream, whose current contract owes no pad ring;
        # DIE/pad evidence remains covered by the dedicated D31/D32 controls.
        from _delivery_declaration import declare_delivery
        declare_delivery(project, "HARDMACRO")
        assert not R._chip_path_requests_pad_ring(project)
    driven = tail._drive(monkeypatch, project, die=tail.NEW_DIE, util=tail.NEW_UTIL)
    if status == "PASS":
        # The legacy transport fixture predates the stream-substance guard and
        # writes an ASCII sentinel named .gds.  Preserve the same actual
        # Step32 -> step_gds scheduling boundary, but make its positive product
        # a real minimal GDSII stream so the current admission consumer can
        # inspect and retain it.
        from _gdsii import write_gdsii

        def valid_gds(proj, top, pdk, container):
            driven.called.append("gds")
            gds = R._pl.pnr_dir(proj) / f"{top}.gds"
            write_gdsii(gds, cell=top)
            return R.StepResult("gds", "PASS", 0.0,
                                "valid source-control GDSII derived from new DEF",
                                [str(gds)])

        monkeypatch.setattr(R, "step_gds", valid_gds)
        # This focused test ends at the stream/admission consumer.  Legacy
        # pre-audit packaging is a later subject and quarantines an IP stream
        # because no chip handoff is owed; it must not erase the product whose
        # Step32 scheduling this case asserts.
        monkeypatch.setattr(R, "run_pre_audit_producers", lambda *a, **k: [])
    tail._stage_fill(monkeypatch, project, driven)
    row = tail._repair_producer(monkeypatch, project, "librelane", status,
                                "current measured Step-32 row")
    # Current typed rows require an explicit owner record, even in a
    # synthetic fixture. This is a control input, not a real run waiver.
    repair_row = R.StepResult(row, status, 0.0, "current measured Step-32 row",
                             waiver_rows=([R._V.WaiverRow(
                                 id="synthetic-step32", owner="reyerchu",
                                 reason="synthetic owner deviation control, approved 2026-09-30"
                             ).to_dict()] if status == "WAIVED" else []))
    def measured_repair(proj, *args, **kwargs):
        # A successful Step-32 owner leaves one unambiguous shipped route.
        # The old fixture's top DEF and routed DEF predate that invariant.
        if status == "PASS":
            pnr = R._pl.pnr_dir(proj)
            (pnr / "routed.def").write_bytes((pnr / f"{tail.TOP}.def").read_bytes())
        return repair_row

    monkeypatch.setattr(R, "step_postroute_repair_librelane", measured_repair)
    rc = R.main()
    rows = tail._plan(project)
    assert rows[row]["status"] == status
    for step in ("gds", "drc", "lvs"):
        assert step in driven.called, rows.get(step)
        assert "sign-off skipped" not in rows[step]["detail"]
    gds = R._pl.pnr_dir(project) / f"{tail.TOP}.gds"
    assert gds.is_file() and rows["gds"]["status"] == "PASS"
    # Isolate the actual aggregate consumer from unrelated synthetic fixture
    # rows: a measured tail PASS cannot erase its Step-32 FAIL or owner waiver.
    verdict = R._aggregate_verdict([repair_row, R.StepResult("gds", "PASS", 0.0, "measured")])
    if status == "PASS":
        assert R._ga.admitted_gds(project, gds)
        assert verdict == "PASS"
    else:
        assert not R._ga.admitted_gds(project, gds)
        assert R._ga.measurement_stream_current(project)
        receipt = json.loads((project / "reports/phase3/layout_receipts.json").read_text())
        assert receipt["release_scope"] == "MEASUREMENT_ONLY"
        assert receipt["release_verdict"] == "NOT_ELIGIBLE_FOR_RELEASE"
        assert f"step 32 ({row} {status})" in receipt["upstream_failed_gate"]
        assert not list(R._pl.foundry_handoff_dir(project).glob("*.gds"))
    if status == "FAIL":
        assert rc != 0, "measured FAIL must keep the overall run failing"
        assert verdict == "FAIL"
    elif status == "WAIVED":
        assert verdict != "PASS"


def test_build_takes_the_io_class_from_the_scenes_pad_libs(tmp_path, monkeypatch):
    """Review wave 58 (MINOR): the PAD_LIBS wiring inside build() was tested
    only through its helpers, so dropping it (M1: _pad_cells without the IO
    library paths; M2: no _pad_lib_paths extend) left every test green. An IO
    fill cell carries the IO library's default fanout 1 but no pad_cell
    attribute: only PAD_LIBS makes it IO, and the core limit stays 4."""
    import drv_capture_plan as plan
    from test_drv_signoff_judge import _librelane_final_sta, _stage_receipts
    project, adopted = _librelane_final_sta(tmp_path, monkeypatch)
    (project / "phase3/stage3/pnr/routed.def").write_bytes(
        Path(json.loads(adopted.read_text())["def"]).read_bytes())
    root = tmp_path / "installed"
    _file(root, "synthetic/libs.ref/io/lib/io_typ.lib",
          'library (io) { time_unit : "1ns"; capacitive_load_unit (1,pf); '
          'default_max_fanout : 1; cell (iofill) { pin (Y) { direction : output; } } }')
    env = next((project / "phase3/librelane/32-cand01/04-openroad-stapostpnr/nom_typ")
               .glob("_env_*.tcl"))
    env.write_text(env.read_text() + 'set ::env(PAD_LIBS) '
                   '"/pdk/synthetic/libs.ref/io/lib/io_typ.lib"\n')
    _stage_receipts(project)
    for name in ("placement_repair", "cts", "post_grt_repair"):
        receipt = project / f"reports/phase3/drv_stages/{name}.json"
        doc = json.loads(receipt.read_text())
        Path(doc["fanout_limit_report"]["path"]).write_text(
            "max fanout\n\nPin u/Y\nmax fanout 4\nfanout 1\n-----------\nSlack 3 (MET)\n\n"
            "Pin f/Y\nmax fanout 1\nfanout 1\n-----------\nSlack 0 (MET)\n")
        Path(doc["pin_cell_report"]["path"]).write_text(
            "pin_cell\tu/Y\tlogic\npin_cell\tf/Y\tiofill\n")
        for field in ("fanout_limit_report", "pin_cell_report"):
            doc[field]["sha256"] = drv._sha(Path(doc[field]["path"]))
        receipt.write_text(json.dumps(doc))
    rows = {row["name"]: row for row in plan.build(project)["stages"]}
    for name in ("placement_repair", "cts", "post_grt_repair"):
        assert (rows[name]["fanout_check_limit"], rows[name]["io_fanout_limit"]) == \
            (4.0, 1.0), rows[name]
