"""Accepted physical source controls for Steps16/31/37.5ip; no native claim."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _physical_current as current
import clock_plan_check as clock_gate
import phase3_one_shot_runner as runner


def put(project, name, text):
    path = project / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


@pytest.fixture
def clock_project(tmp_path, monkeypatch):
    floor = put(tmp_path, "phase3/stage3/pnr/floorplan.def", "DESIGN neutral ;\nEND DESIGN\n")
    sdc = put(tmp_path, "phase2/stage2/constraints/current.sdc",
              "create_clock -name system -period 12 [get_ports tick]\n")
    tech = put(tmp_path, "input/pdk/tech.lef", "VERSION 5.8 ;\nEND LIBRARY\n")
    cell = put(tmp_path, "input/pdk/cell.lef", "MACRO neutral\nEND neutral\n")
    liberty = put(tmp_path, "input/pdk/active.lib", "library(neutral) {}\n")
    pdk = SimpleNamespace(name="open_fixture", tech_lef=str(tech), cell_lef=str(cell),
                          liberty=str(liberty), macro_lefs=[])
    def native(project, tool, args, log):
        Path(log).write_text("CLOCK_PLAN_PDK open_fixture\nCLOCK_PLAN_NATIVE system|12|tick\nCLOCK_PLAN_DONE\n")
        return 0, {"rc": 0, "argv": [tool, *args]}
    monkeypatch.setattr(current, "run_native", native)
    monkeypatch.setattr(runner, "_read_declared_pdk_target", lambda p: pdk.name)
    monkeypatch.setattr(runner, "_detect_pdk", lambda *a: pdk)
    plan = tmp_path / "phase3/stage3/cts/clock_plan.json"
    notes = []
    assert runner.emit_clock_plan(tmp_path, plan, floor, floor.parent, notes) == str(plan), notes
    return tmp_path, plan, sdc


def gate(project):
    return clock_gate.main([str(project), "--json", str(project / "clock_check.json")])


def test_ordinary_clock_producer_is_consumed(clock_project):
    project, plan, _ = clock_project
    assert gate(project) == 0
    assert json.loads(plan.read_text())["current"]["step"] == "16"


@pytest.mark.parametrize("field,value", [("step", "19"), ("stage", "stage4"),
                                       ("tool", "python"), ("design", "other"),
                                       ("pdk", "wrong")])
def test_clock_context_mutation_refuses(clock_project, field, value):
    project, plan, _ = clock_project
    doc = json.loads(plan.read_text())
    doc["current"][field] = value
    plan.write_text(json.dumps(doc))
    assert gate(project) == 1


@pytest.mark.parametrize("mutation", ["sdc", "floorplan", "log", "execution", "values", "removed_producer"])
def test_clock_substantive_reverse(clock_project, mutation):
    project, plan, sdc = clock_project
    doc = json.loads(plan.read_text())
    if mutation == "sdc":
        sdc.write_text(sdc.read_text().replace("12", "15"))
    elif mutation == "floorplan":
        (project / "phase3/stage3/pnr/floorplan.def").write_text("DESIGN other ;\n")
    elif mutation == "log":
        (project / doc["current"]["outputs"]["log"]["path"]).write_text("no execution\n")
    elif mutation == "execution":
        doc["current"]["execution"]["rc"] = 9
    elif mutation == "values":
        doc["clocks"][0]["period_ns"] = 100
    else:
        doc.pop("current")
    plan.write_text(json.dumps(doc))
    assert gate(project) == 1


def test_no_sdc_never_produces_nominal_clock(clock_project):
    project, plan, sdc = clock_project
    sdc.unlink()
    plan.unlink()
    notes = []
    floor = project / "phase3/stage3/pnr/floorplan.def"
    assert runner.emit_clock_plan(project, plan, floor, floor.parent, notes) is None
    assert plan.exists() is False
    assert gate(project) == 1


def test_direct_producer_failure_precedence(tmp_path):
    row = runner.StepResult("drc", "FAIL", 0.0, "measured violation")
    result = current.direct_half(tmp_path, "neutral", SimpleNamespace(), "drc", lambda: row)
    assert result.status == "FAIL"


def test_current_inputs_are_in_scope(tmp_path):
    escaped = tmp_path.parent / "escaped_current.txt"
    escaped.write_text("outside")
    try:
        with pytest.raises(ValueError, match="CURRENT_PATH_ESCAPES"):
            current.entry(tmp_path, escaped)
    finally:
        escaped.unlink()


def test_ip_ordinary_producer_invokes_kit_consumer(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(runner, "_ip_delivery_declared_na", lambda p: (False, "", {}))
    def run(name, argv, t0, **kw):
        calls.append(Path(argv[1]).stem)
        return SimpleNamespace(returncode=0 if len(calls) == 1 else 1, stdout="fixture", stderr=""), None
    monkeypatch.setattr(runner, "_run_producer", run)
    row = runner.step_digital_hardmacro_gen(tmp_path)
    assert calls == ["digital_hardmacro_gen", "digital_hardmacro_check"]
    assert row.status == "FAIL"


def test_kit_gate_refuses_unbound_views(tmp_path):
    import digital_hardmacro_check as kit
    from test_digital_hardmacro_gen import make_project
    make_project(tmp_path)
    hm = tmp_path / "phase3/stage4/hardmacro"
    hm.mkdir()
    put(tmp_path, "phase3/stage4/hardmacro/macro_a.v", "module macro_a(); endmodule\n")
    result = kit.run_audit(tmp_path)
    assert result.passed is False
    assert "IP_KIT_CURRENT_REFUSED" in {f.rule for f in result.findings}


def _step31_control(tmp_path, monkeypatch, control):
    """Actual Default dispatch and consumers; EDA transport is SOURCE_CONTROL.

    The boundary writes invented tool transcripts and their literal digest
    ledger. It proves ordering/current consumption, never native physical DRC.
    """
    import hashlib
    import execution_policy
    import step_preflight
    import _path_layout as layout
    import drc_report_check
    import l24_signoff_evidence_backed_check as l24
    import l24_signoff_requirements_extract as extract
    from test_a_magic_receipt_binds_to_the_layout_it_read import _GOOD, _gds_bytes

    project = tmp_path / "neutral"
    top = "chip_top"
    def_text = "VERSION 5.8 ;\nDESIGN chip_top ;\nEND DESIGN\n"
    put(project, "phase3/stage3/pnr/chip_top.def", def_text)
    put(project, "phase3/stage3/pnr/routed.def", def_text)
    gds = project / "phase3/stage3/pnr/chip_top.gds"
    gds.write_bytes(_gds_bytes(top))
    put(project, "phase3/stage3/pnr/chip_top_pnr.v", "module chip_top(); endmodule\n")
    put(project, "phase2/stage2/synth/netlist_yosys.v", "module chip_top(); endmodule\n")
    put(project, "phase2/stage1/rtl/chip_top.v", "module chip_top(); endmodule\n")
    tech = put(project, "input/pdk/tech.lef", "VERSION 5.8 ;\nLAYER met1\n TYPE ROUTING ;\nEND met1\nEND LIBRARY\n")
    cells = put(project, "input/pdk/cell.lef", "VERSION 5.8 ;\nEND LIBRARY\n")
    deck = put(project, "input/pdk/neutral.lydrc", "# SOURCE_CONTROL deck\n")
    magicrc = put(project, "input/pdk/neutral.magicrc", "# SOURCE_CONTROL tech\n")
    put(project, "reports/phase3/technology_units.json", json.dumps({"pdk": "open_fixture"}))
    put(project, "reports/phase3/antenna.json", json.dumps({"routing_incomplete": False}))
    engines = "KLayout" if control == "no_magic" else "both Magic and KLayout"
    put(project, "input/docs/spec.txt", f"# Physical Verification\nThe design requires DRC clean with {engines}; all declared engines must pass.\n")
    put(project, "phase1/generated_docs/L24_SIGNOFF.json", json.dumps({
        "doc_id": "L24_SIGNOFF", "fields": extract.extract_signoff_requirements(project)}))
    pdk = runner.PdkConfig("open_fixture", str(deck), str(tech), str(cells), None, "neutral", str(deck))
    calls = []
    monkeypatch.setenv("VIBEIC_EXECUTION_MODE", "default")
    monkeypatch.setattr(execution_policy, "request", lambda *a, **kw: {"mode": "default"})
    monkeypatch.setattr(runner, "_to_container_path", lambda path, container: path)
    monkeypatch.setattr(runner, "_tool_in_path", lambda *a: True)
    monkeypatch.setattr(runner, "_pdk_magicrc", lambda *a: str(magicrc))
    def digest(path):
        return "sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest()
    def transport(container, cmd, **kwargs):
        if not cmd.startswith("magic ") and "klayout -b" not in cmd:
            return 0, "SOURCE_CONTROL deck-source probe", ""
        tool = "magic" if cmd.startswith("magic ") else "klayout"
        calls.append(tool)
        if tool == "magic":
            text = _GOOD.replace("ab" * 32, digest(gds)[7:])
            if control == "magic_fail":
                text = (text.replace("total violations: 0", "total violations: 1")
                        .replace("error tiles (drc list count total): 0", "error tiles (drc list count total): 1")
                        .replace("COUNT: 0", "COUNT: 1"))
            report = project / runner._MAGIC_SIGNOFF_DRC_REL
        else:
            count = int(control == "primary_fail")
            item = "<item><category>'met1.short'</category><multiplicity>1</multiplicity></item>" if count else ""
            text = (f"<report-database><generator>drc: script = '{deck}'</generator>"
                    f"<top-cell>chip_top</top-cell><description>KLayout total violations: {count}\n"
                    "spacing width density antenna via enclosure "
                    + "SOURCE_CONTROL " * 200 + f"</description><items>{item}</items></report-database>\n")
            report = project / "phase3/reports/drc.rpt"
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(text)
        log = Path(kwargs["transcript_path"])
        log.write_text(f"SOURCE_CONTROL {tool} transport completed\n")
        outputs = {str(Path(path).relative_to(project)): digest(path)
                   for path in kwargs.get("outputs", [])}
        row = {"record": "invocation", "tool": tool, "measured": True,
               "exit_code": 0, "command": cmd, "scope": "SOURCE_CONTROL",
               "inputs": {str(gds.relative_to(project)): digest(gds)}, "outputs": outputs}
        with (project / "provenance.jsonl").open("a") as stream:
            stream.write(json.dumps(row) + "\n")
        return 0, "SOURCE_CONTROL completed", ""
    monkeypatch.setattr(runner, "_docker_exec", transport)
    if control == "missing_context":
        tech.unlink()
    row = step_preflight.gate(project, "phase3_one_shot_runner", "drc",
                             runner._preflight_refusal("drc"), runner.step_drc,
                             project, top, pdk, "SOURCE_CONTROL")
    if control == "stale_report":
        report = project / runner._MAGIC_SIGNOFF_DRC_REL
        report.write_text(report.read_text() + "\nchanged after invocation\n")
        runner._audit_magic_signoff_drc(project)
    elif control == "stale_gds":
        gds.write_bytes(gds.read_bytes() + b"changed after invocation")
        runner._audit_magic_signoff_drc(project)
    primary = project / "reports/phase3/drc_signoff.json"
    drc_report_check.run([str(project), "--mode", "drc", "--signoff",
                          "--under", "phase3/reports/drc.rpt", "--json", str(primary)])
    put(project, "reports/orchestrator/phase3_one_shot.json", json.dumps({
        "verdict": row.status, "scope": "SOURCE_CONTROL",
        "phase2_synth": layout.phase2_synth_input_identity(project),
        "phase3_inputs": layout.phase3_signoff_input_identity(project)}))
    l24_rc = l24.main(["gate", str(project)])
    magic = project / runner._MAGIC_SIGNOFF_DRC_JSON_REL
    payload = json.loads(magic.read_text()) if magic.is_file() else None
    print("STEP31_CONTROL " + json.dumps({"control": control, "producer": row.status,
          "current": current.read_direct_half(project, "drc")["verdict"],
          "magic_passed": payload.get("passed") if payload else None,
          "magic_rc": row.extras.get("magic_signoff_drc_audit", {}).get("rc"),
          "l24_rc": l24_rc, "calls": calls, "scope": "SOURCE_CONTROL"}, sort_keys=True))
    return row, payload, l24_rc, calls, project


@pytest.mark.parametrize("control", ["clean", "magic_fail", "primary_fail", "missing_context",
                                     "stale_report", "stale_gds", "no_magic"])
def test_default_step31_consumes_both_engines_after_current_publication(tmp_path, monkeypatch, control):
    row, magic, l24_rc, calls, project = _step31_control(tmp_path, monkeypatch, control)
    assert calls == (["klayout"] if control == "no_magic" else ["klayout", "magic"])
    assert row.status == ("FAIL" if control in ("magic_fail", "primary_fail") else
                          "NOT_MEASURED" if control == "missing_context" else "PASS"), row
    if control == "no_magic":
        assert magic is None
    else:
        assert magic["passed"] == (control in ("clean", "primary_fail")), magic["findings"]
    assert l24_rc == (0 if control in ("clean", "no_magic") else 1)
    if control in ("clean", "no_magic", "magic_fail", "primary_fail"):
        assert current.read_direct_half(project, "drc")["verdict"] == "CURRENT"
