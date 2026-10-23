"""Neutral bounded IC-document resume through the existing release owners.

The reports below are source-control inputs, not a native design sign-off.
Existing public format fixtures supply the delegated report evidence; all
document producers and the complete canonical consumer execute normally.
"""
import hashlib
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

import _gds_admission as admission
import _owner_declared as owner
import _tapeout_declaration as declaration
import drc_report_check as drc
import phase3_one_shot_runner as runner
import signoff_metrics_aggregate as metrics
from _ic_release_kit import build_project, DESIGN
from test_antenna_report_check import CLEAN as ANTENNA_CLEAN
from test_general_precheck_drc_input_binding import NATIVE
from test_the_second_drc_engine_the_input_declared_actually_runs import _CLEAN_RPT

PDK = "sky130A"
RELEASE = DESIGN


def _write(project, relative, value):
    path = project / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) if isinstance(value, dict) else value)
    return path


def _sha(path):
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _project(tmp_path, monkeypatch=None, *, native_lvs=False):
    project = build_project(tmp_path / "project", releases=(RELEASE,))
    pdk_name = "procx" if native_lvs else PDK
    _write(project, "input/project.json", {"design": DESIGN, "pdk": pdk_name})
    # The existing public kit supplies a real layout, DEF, second-view netlist,
    # L-documents and product data. Answer the independent declaration reader.
    doc, ignored = declaration.merge_answers(declaration.blank_declaration(), {
        "deliverable": "DIE", "top_cell": RELEASE,
        "die_origin_um": [0, 0], "die_area_um": [0, 0, 240, 160],
        "database_unit_um": 0.001, "seal_ring_required": False,
        "forbidden_layers": [],
    })
    assert not ignored
    owner.attest(doc)
    _write(project, declaration.DECLARATION_REL, doc)
    _write(project, "phase3/librelane_switch.json", {
        "steps": {sid: "direct" for sid in ("9", "26", "31", "34", "37")}})
    pnr = project / "phase3/stage3/pnr"
    gds = pnr / f"{DESIGN}.gds"
    gds.write_bytes((project / f"phase3/stage4/gds/{RELEASE}.gds").read_bytes())
    netlist = _write(project, f"phase2/stage2/synth/{DESIGN}_synth.v",
                     (pnr / f"{DESIGN}_pnr.v").read_text())
    sdc = _write(project, "phase3/stage3/pnr/constraint.sdc",
                 "create_clock -name clk -period 10 [get_ports clk]\n")
    # This minimal PDK object is only the admission's content identity. The
    # real general-precheck technology reader uses the pinned image's PDK.
    liberty = _write(project, "input/neutral.lib", "library(neutral) {}\n")
    lef = _write(project, "input/neutral.lef", "VERSION 5.8 ;\nEND LIBRARY\n")
    pdk = runner.PdkConfig(pdk_name, str(liberty), str(lef), str(lef),
                           None, "neutral", None)
    basis, error = runner._layout_basis(project, DESIGN, pdk, "")
    assert not error, error
    _write(project, "reports/phase3/prestream_gate.json", {
        "verdict": "PASS", "layout_digest": basis,
        "scope": "neutral source-control input admission, not native qualification"})
    admission.admit_gds(project, gds, basis, [pnr / "routed.def", netlist, sdc])

    # Use the actual public technology's declared rule descriptions rather
    # than padding a short Magic instrument transcript to meet a byte floor.
    tech = Path("/foss/pdks") / PDK / "libs.tech/magic" / (PDK + ".tech")
    in_drc, rules = False, set()
    for line in tech.read_text().splitlines():
        if not in_drc:
            in_drc = re.match(r"^drc\b", line.strip()) is not None
            continue
        if re.match(r"^end\b", line.strip()):
            break
        rules.update(re.findall(r'"([^\"]{8,})"', line))
    assert rules
    magic_report = (_CLEAN_RPT.replace("chip_top", DESIGN).replace("gf180mcuD", PDK)
                    + "\n".join("DECK_RULE: " + row for row in sorted(rules)) + "\n")
    # The public RDB format fixture is re-subjected to this neutral unit
    # design. It models an instrument, not an executed design sign-off.
    import xml.etree.ElementTree as ET
    rdb = ET.fromstring((NATIVE / "zero.xml").read_text())
    old_subject = rdb.findtext("top-cell")
    klayout_report = (NATIVE / "zero.xml").read_text().replace(old_subject, DESIGN)
    records = []
    for tool, report_rel, log_rel, text, log in (
        ("klayout", "reports/phase3/drc_signoff.rpt", "reports/phase3/drc_signoff.log",
         klayout_report, (NATIVE / "terminal.log").read_text()),
        ("magic", "reports/phase3/drc_signoff_magic.rpt", "reports/phase3/drc_signoff_magic.log",
         magic_report, "magic DRC: 0 violations\n"),
    ):
        report = _write(project, report_rel, text)
        log_path = _write(project, log_rel, log)
        records.append({"record": "invocation", "measured": True, "tool": tool,
                        "exit_code": 0, "inputs": {str(gds.relative_to(project)): _sha(gds)},
                        "outputs": {str(p.relative_to(project)): _sha(p)
                                    for p in (report, log_path)}})
    _write(project, "provenance.jsonl", "".join(json.dumps(row) + "\n" for row in records))
    _write(project, "reports/phase3/antenna.rpt", ANTENNA_CLEAN)
    _write(project, "reports/phase3/antenna.json", {
        "net_violations": 0, "pin_violations": 0, "routing_incomplete": False})
    _write(project, "reports/phase3/metal_density_layers.json", {
        "layers": {f"met{i}": 0.5 for i in range(1, 6)}})
    for tool, relative in (("openroad", "drc_router.json"),
                           ("magic", "drc_signoff_magic.json"),
                           ("klayout", "drc_signoff.json")):
        _write(project, "reports/phase3/" + relative, {
            "summary": {"real_violation_total": 0, "categories_found": ["spacing", "density"],
                        "producers": [{"producer": tool}]}})
    for report, target in (("drc_signoff.rpt", "drc_signoff.json"),
                           ("drc_signoff_magic.rpt", "drc_signoff_magic.json")):
        raw = "reports/phase3/" + report
        assert drc.run([str(project), "--mode", "drc", "--under", raw,
                        "--require-report", raw, "--json",
                        str(project / "reports/phase3" / target)]) == 0
    _write(project, "reports/phase3/lvs.json", {"summary": {"terminal_verdict": "MATCH"}})
    _write(project, "reports/phase3/gds_xor.json", {
        "verdict": "PASS", "design__xor_difference__count": 0,
        "reference": {"kind": "neutral source-control layout"}})
    _write(project, "reports/phase3/sta/post_route_signoff_corner.json", {
        "setup_worst_slack_ns": 1.25, "hold_worst_slack_ns": 0.5,
        "report": "reports/phase3/sta_spef_multicorner.rpt"})
    _write(project, "reports/phase3/sta_spef_multicorner.rpt",
           "=== SETUP (max) ===\ntns max 0.0\n=== HOLD (min) ===\ntns max 0.0\n")
    _write(project, "reports/phase3/sta_spef_based.rpt",
           "SIGNOFF_CHECK_TYPES_REPORTED recovery max_slew max_capacitance\n")
    if native_lvs:
        # Current open-PDK routing requires the full-GDS LibreLane LVS owner.
        # Drive its actual run_chain/judge producer against the selected public
        # fixture stream; do not substitute the older direct lvs.json PASS.
        assert monkeypatch is not None
        from _native_signoff_fixture import producer
        producer(project, monkeypatch, "lvs", both_lvs=True, gds_path=gds)
        switch = json.loads((project / "phase3/librelane_switch.json").read_text())
        # Preserve every other direct owner selected above.  The producer
        # helper owns only the Step-31 LVS half; allowing its minimal switch
        # fixture to erase Step 9 would falsely demand a LibreLane synthesis
        # handoff, and erasing Step 26 would replace the actual antenna report.
        switch["steps"] = {sid: "direct" for sid in ("9", "26", "34", "37")}
        # Dual keeps the existing direct DRC authority while the LVS half's
        # current contract still consumes the full-GDS LibreLane producer.
        switch["steps"]["31"] = "dual"
        _write(project, "phase3/librelane_switch.json", switch)
    assert metrics.main([str(project)]) == 0
    return project, pdk


def _call(project, pdk, monkeypatch, *, bounded=False):
    monkeypatch.setattr(runner, "_backend_parameter_values", lambda *_: {})
    earlier = []

    def forbidden(*args, **kwargs):
        earlier.append("earlier_or_enclosing")
        raise AssertionError("bounded documentation resume must not replay physical producers")

    for name in ("step_synth", "step_pnr", "step_gds", "step_canonicalize_artefacts",
                 "_phase3_window_enclosing"):
        monkeypatch.setattr(runner, name, forbidden)
    selected = runner._phase3_window_sites("37.5ic", "37.5ic")
    assert selected == ["default_backend"], selected
    if bounded:
        args = SimpleNamespace(entry_step="37.5ic", exit_step="37.5ic", container="",
                               die_um=None, util=None, spare_density=None)
        result = runner._run_phase3_window(project, DESIGN, pdk, args, selected)
    else:
        result = runner._default_pnr_rows(project, DESIGN, pdk, "", ["37.5ic"])
    _write(project, "API_OBSERVATION.json", {
        "selected": selected, "status": result.status if not bounded else result,
        "detail": result.detail if not bounded else "actual bounded window returncode",
        "extras": result.extras if not bounded else {}, "earlier_tool_calls": earlier,
        "scope": "SOURCE_CONTROL_ONLY; no native IC sign-off"})
    assert earlier == []
    return result


def _accept_physical_precheck(project, monkeypatch):
    """Fixture boundary: physical prerequisites were accepted already.

    This substitutes only the precheck owner at both call sites.  The document
    producers, their output binding, and the retained release consumer remain
    real and are the integration subject of the tests below.
    """
    import flow_compliance_check as compliance

    report = project / "reports/phase3/tapeout_precheck.json"

    def write_receipt():
        body = {
            "verdict": "PASS", "invoked_as": "producer",
            "scope": ("SOURCE_CONTROL accepted-physical-precondition fixture; "
                      "not native IC qualification"),
            "fixture_boundary": "physical precheck only",
        }
        for relative in ("reports/phase3/general_precheck.json",
                         "reports/phase3/shuttle_precheck.json",
                         "reports/phase3/tapeout_precheck.json"):
            _write(project, relative, body)

    actual_gate = runner._run_declared_signoff_gate

    def accepted_gate(proj, name, program, out_rel, extra_argv):
        if name == "tapeout_precheck":
            write_receipt()
            return runner.StepResult(name, "PASS", 0.0,
                                     "accepted physical-precondition fixture",
                                     [str(project / "reports/phase3/general_precheck.json"),
                                      str(project / "reports/phase3/shuttle_precheck.json"),
                                      str(report)])
        return actual_gate(proj, name, program, out_rel, extra_argv)

    monkeypatch.setattr(runner, "_run_declared_signoff_gate", accepted_gate)
    actual_check = compliance._check_program_exit_zero

    def accepted_check(proj, cmd_str):
        if compliance._gate_name(cmd_str) == "tapeout_precheck":
            write_receipt()
            compliance._record_gate_execution(cmd_str, 0, "PASS",
                                               evidence=json.loads(report.read_text()))
            return compliance._ProgramCheckResult(
                True, "accepted physical-precondition fixture", 0,
                "PASS", "PASS", None)
        return actual_check(proj, cmd_str)

    monkeypatch.setattr(compliance, "_check_program_exit_zero", accepted_check)


def test_default_bounded_ic_release_calls_real_owners(tmp_path, monkeypatch):
    project, pdk = _project(tmp_path, monkeypatch, native_lvs=True)
    _accept_physical_precheck(project, monkeypatch)
    result = _call(project, pdk, monkeypatch, bounded=True)
    assert result == 0


def test_real_document_producers_and_each_release_consumer_execute(tmp_path, monkeypatch):
    project, pdk = _project(tmp_path, monkeypatch, native_lvs=True)
    _accept_physical_precheck(project, monkeypatch)
    _call(project, pdk, monkeypatch)
    receipt = json.loads((project / "reports/phase3/default_steps/37.5ic/backend_result.json").read_text())
    assert receipt["missing_outputs"] == []
    gates = {row["gate"]: row for row in receipt["gate_ledger"]}
    for gate in ("tapeout_precheck", "tapeout_docs_gen", "release_docs_check"):
        assert gates[gate]["rc"] == 0, receipt
        assert gates[gate]["verdict"] == "PASS", receipt
    assert receipt["canonical_step_result"]["output_binding"]["n_step_attributed"] == 9
    assert (project / f"phase3/stage4/documentation/ic/{RELEASE}/documentation_manifest.yaml").is_file()


def test_missing_seal_precheck_blocks_document_publication(tmp_path, monkeypatch):
    """The new physical-input negative is additional to the release positive."""
    project, pdk = _project(tmp_path)
    result = _call(project, pdk, monkeypatch)
    assert result.status != "PASS", result.detail
    receipt = json.loads(
        (project / "reports/phase3/default_steps/37.5ic/backend_result.json").read_text())
    assert receipt["verdict"] == "FAIL"
    assert "General.SealRing" in receipt["detail"], receipt
    assert receipt["canonical_step_result"] is None
    assert (project / "reports/phase3/tapeout_precheck.json").is_file()
    assert not (project / "reports/orchestrator/producers/ic_release_docs_gen.log").exists()
    assert not (project / f"phase3/stage4/documentation/ic/{RELEASE}/documentation_manifest.yaml").exists()


@pytest.mark.parametrize("change", ["missing_metrics", "changed_metrics", "unadmitted_gds",
                                    "producer_refusal", "consumer_refusal"])
def test_current_release_obligations_remain_blocking(tmp_path, monkeypatch, change):
    project, pdk = _project(tmp_path, monkeypatch, native_lvs=True)
    _accept_physical_precheck(project, monkeypatch)
    if change == "missing_metrics":
        (project / "phase3/final/metrics.json").unlink()
    elif change == "changed_metrics":
        _write(project, "reports/phase3/sta/post_route_signoff_corner.json", {
            "setup_worst_slack_ns": -0.5, "hold_worst_slack_ns": 0.5,
            "report": "reports/phase3/sta_spef_multicorner.rpt"})
    elif change == "unadmitted_gds":
        gds = project / f"phase3/stage3/pnr/{DESIGN}.gds"
        gds.write_bytes(gds.read_bytes() + b"changed after admission")
    elif change == "producer_refusal":
        _write(project, "reports/phase3/power.json", {
            "program": "eda_report_audit:power", "passed": True, "summary": {}})
    else:
        actual_run = runner._pr.run

        def instrument(argv, *args, **kwargs):
            result = actual_run(argv, *args, **kwargs)
            if (isinstance(argv, (list, tuple)) and len(argv) > 1
                    and Path(str(argv[1])).name == "ic_release_docs_gen.py"
                    and result.returncode == 0):
                # The real producer returned zero; the real retained full
                # consumer must reject the now-missing product document.
                (project / f"phase3/stage4/documentation/ic/{RELEASE}/PRELIMINARY_DATASHEET.md").unlink()
            return result

        monkeypatch.setattr(runner._pr, "run", instrument)
    result = _call(project, pdk, monkeypatch)
    assert result.status != "PASS", result.detail
    receipt = json.loads((project / "reports/phase3/default_steps/37.5ic/backend_result.json").read_text())
    if change == "consumer_refusal":
        assert receipt["canonical_step_result"]["status"] == "FAIL", receipt
        assert any(row["gate"] == "release_docs_check" and row["rc"] == 1
                   for row in receipt["gate_ledger"]), receipt
        assert (project / "reports/orchestrator/producers/ic_release_docs_gen.log").is_file()
    else:
        assert not (project / f"phase3/stage4/documentation/ic/{RELEASE}/documentation_manifest.yaml").is_file()


@pytest.mark.parametrize("route", ["HARDMACRO", "UNKNOWN"])
def test_delivery_condition_uses_the_existing_typed_reader(tmp_path, monkeypatch, route):
    project = tmp_path / "project"
    project.mkdir()
    if route == "HARDMACRO":
        doc, _ = declaration.merge_answers(declaration.blank_declaration(), {"deliverable": route})
        owner.attest(doc)
        _write(project, declaration.DECLARATION_REL, doc)
        _write(project, "input/submission_template/NO_TEMPLATE.txt", "IP route\n")
    monkeypatch.setattr(runner, "_backend_parameter_values", lambda *_: {})
    pdk = SimpleNamespace(name=PDK)
    result = runner._default_pnr_rows(project, DESIGN, pdk, "", ["37.5ic"])
    row = result.extras["canonical_steps"][0]
    assert row["status"] == ("NOT_APPLICABLE" if route == "HARDMACRO" else "NOT_MEASURED")
    assert not (project / "reports/phase3/tapeout_precheck.json").exists()


def test_ultra_retains_its_existing_enclosing_route(monkeypatch):
    import execution_policy
    monkeypatch.setattr(execution_policy, "request", lambda: {"mode": "ultra"})
    assert runner._phase3_window_sites("37.5ic", "37.5ic") == ["enclosing_phase3"]


@pytest.mark.parametrize("change", ["current", "changed_pdk", "changed_gds", "refused_restore"])
def test_default_ic_release_admission_precedes_instrument_view_restoration(
        tmp_path, monkeypatch, change):
    """Real release entry/admission/restore; stop before document/PV consumers."""
    import copy

    project, pdk = _project(tmp_path)
    gds = project / f"phase3/stage3/pnr/{DESIGN}.gds"
    macro = _write(project, "input/recorded_macro.lef",
                   "MACRO recorded_macro\n CLASS BLOCK ;\n SIZE 1 BY 1 ;\nEND recorded_macro\n")
    _write(project, runner.PHYSICAL_VIEW_INVENTORY_REL, {
        "read_lef_paths": [pdk.tech_lef, pdk.cell_lef, str(macro)]})
    basis, error = runner._layout_basis(project, DESIGN, pdk, "")
    assert not error and admission.admitted_gds(project, gds, basis)
    restored_pdk = copy.deepcopy(pdk)
    restored = runner._restore_recorded_physical_views(project, restored_pdk, "")
    restored_basis, error = runner._layout_basis(project, DESIGN, restored_pdk, "")
    assert not error and restored["macro_lefs"] == [str(macro)]
    assert restored_basis != basis
    assert not admission.admitted_gds(project, gds, restored_basis)
    preserved = {str(path.relative_to(project)): path.read_bytes() for path in
                 [*runner._layout_basis_paths(project, DESIGN), gds,
                  admission.admission_path(project), macro]}
    if change == "changed_pdk":
        Path(pdk.liberty).write_text("library(changed_source_material) {}\n")
    elif change == "changed_gds":
        gds.write_bytes(gds.read_bytes() + b"changed after admission")
    elif change == "refused_restore":
        _write(project, "reports/pdk_via_patch_legalization.json", {
            "status": "APPLIED", "derived_tech_lef": "input/absent_recorded.lef",
            "derived_sha256": "0" * 64})
    monkeypatch.setattr(runner, "_STEP_PDK_HASH_CACHE", {})
    reached = []

    def metrics_frontier(*args, **kwargs):
        assert str(macro) in pdk.macro_lefs
        reached.append(args[1])
        return runner.StepResult("signoff_metrics_aggregate", "NOT_MEASURED", 0.0,
                                 "SOURCE_CONTROL_METRICS_FRONTIER; no physical sign-off",
                                 reason_class="not_executed")

    monkeypatch.setattr(runner, "_run_declared_signoff_gate", metrics_frontier)
    result = runner._default_ic_release_docs(project, DESIGN, pdk, "")
    _write(project, "IC_RELEASE_BASIS_OBSERVATION.json", {
        "change": change, "fresh_basis": basis, "restored_basis": restored_basis,
        "result": result, "calls": reached, "macro_lefs": pdk.macro_lefs,
        "scope": "real admission/restore source frontier only; not document or physical PASS"})
    if change == "current":
        assert reached == ["signoff_metrics_aggregate"], result
        assert result["verdict"] == "NOT_MEASURED"
        assert result["detail"].startswith("SOURCE_CONTROL_METRICS_FRONTIER")
        for relative, payload in preserved.items():
            assert (project / relative).read_bytes() == payload
    else:
        assert reached == [] and result["verdict"] == "NOT_MEASURED", result
        assert ("via-legalized tech LEF" if change == "refused_restore" else
                "unadmitted current layout") in result["detail"]
