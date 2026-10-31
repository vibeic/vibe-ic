"""Production Default inputs and tool handoff, without a mode controller."""
import json
from pathlib import Path
from types import SimpleNamespace
import subprocess

import pytest
import _plugin_tree  # noqa: F401
import design_one_shot_runner as D
import librelane_contract as LC
import phase3_one_shot_runner as P3
import synth_handoff_netlist_check as H
import lec_equivalence_check as G
from test_t91_step2_verilator_lint_gate import _design, _runner, put, NEG
from test_step9_step14_read_the_pnr_netlist import _clause, _run_clause
from test_f1_lec_subject_is_pnr_input import _gate_arg


def _lint(tmp_path, monkeypatch, *, target="pdkA"):
    project, src, calls, tool = _design(tmp_path, "librelane", NEG, 0, 1)
    # Ordinary Phase 2 has declared inputs but no mode switch.
    (project / "phase3/librelane_switch.json").unlink()
    (project / "input/project.json").unlink()
    put(project / "phase1/generated_docs/L19_CONSTRAINTS_PDK.json",
        {"doc_id": "L19", "fields": {"pdk_target": target}})
    monkeypatch.setattr(LC, "resolve_image", lambda *_: "img")
    monkeypatch.setattr(LC, "pdk_root_resolution", lambda *a, **k:
                        {"path": str(tmp_path / "pdkroot")})
    runner, step = _runner(monkeypatch, tool)
    return project, src, calls, step


def test_step2_default_uses_phase2_declared_pdk_and_normal_gate(tmp_path, monkeypatch):
    project, src, calls, step = _lint(tmp_path, monkeypatch)
    row = step(project)
    assert row is not None and row.status == "PASS", row
    cfg = project / "phase3/librelane/step2/lint_config.json"
    assert json.loads(cfg.read_text())["PDK"] == "pdkA"
    assert "L19" in json.loads(cfg.with_suffix(".provenance.json").read_text())["PDK"]
    assert any("librelane.steps" in c for c in calls)
    gate = json.loads((project / "reports/phase2/lint/verilator_lint_gate.json").read_text())
    assert gate["file_set"]["linted"] == [str(src.resolve())]
    assert row.extras["spec_conformance_tool_ports_rc"] is not None


@pytest.mark.parametrize("damage", ["missing", "conflict", "malformed", "untyped", "switch_conflict"])
def test_step2_bad_pdk_input_refuses_before_native_launch(tmp_path, monkeypatch, damage):
    project, _, calls, step = _lint(tmp_path, monkeypatch)
    target = project / "phase1/generated_docs/L19_CONSTRAINTS_PDK.json"
    if damage == "missing":
        target.unlink()
    elif damage == "conflict":
        put(project / "input/project.json", {"pdk": "otherPDK"})
    elif damage == "malformed":
        target.write_text("{")
    elif damage == "untyped":
        put(target, {"fields": {"pdk_target": {"name": "pdkA"}}})
    else:
        put(project / "phase3/librelane_switch.json", {"pdk": "otherPDK"})
    row = step(project)
    assert row is not None and row.status == "FAIL", row
    assert "LL_PHASE2_PDK" in row.detail
    assert calls == []


def test_step2_project_input_is_an_existing_declared_source(tmp_path, monkeypatch):
    project, _, _, step = _lint(tmp_path, monkeypatch)
    (project / "phase1/generated_docs/L19_CONSTRAINTS_PDK.json").unlink()
    put(project / "input/project.json", {"pdk": "pdkA"})
    assert step(project).status == "PASS"


def test_step2_staged_pdk_cannot_mask_conflicting_l19(tmp_path, monkeypatch):
    project, _, calls, step = _lint(tmp_path, monkeypatch)
    put(project / 'phase1/pdk_staging_read.json', {'adopted_pdk_target': 'otherPDK'})
    assert step(project).status == 'FAIL'
    assert calls == []


def _synthesis(tmp_path, monkeypatch, *, ordinary=False):
    from test_librelane_contract_production_defaults import _chip
    p = _chip(tmp_path / "project")
    if not ordinary:
        put(p / "phase3/librelane_switch.json", {"steps": {"9": "librelane"}})
    put(p / "input/project.json", {"pdk": "pdkA"})
    put(p / "phase1/generated_docs/L8_TIMING_WAVEFORM.json", {
        "clock_domains": [{"role": "primary", "source_pin": "clk", "period_ns": 10}]})
    put(p / "phase1/generated_docs/L9_INTEGRATION_SPEC.json", {"top_module": "top"})
    put(p / "phase1/generated_docs/L19_CONSTRAINTS_PDK.json", {
        "fields": {"pdk_target": "pdkA", "die_area_budget_um": "1000x1000"}})
    rtl = p / "phase2/stage1/rtl/top.v"
    rtl.parent.mkdir(parents=True)
    rtl.write_text("module top(input clk, input a, output reg [3:0] q);\n"
                   "always @(posedge clk) q <= {q[2:0], a};\nendmodule\n")
    root = tmp_path / "pdkroot"
    root.mkdir()
    # A synthetic matching Liberty/LEF pair in an existing registry layout;
    # the production area emitter establishes um^2 from their cell footprints.
    lib = root / "sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib"
    lib.parent.mkdir(parents=True)
    masters = ("lib__dffq_1", "lib__buf_1", "lib__tieh", "lib__tiel") + tuple(
        f'lib__extra_{i}' for i in range(4))
    lib.write_text('library (lib) { time_unit : "1ns";\n' + ''.join(
        f'cell ({c}) {{ area : 1; }}\n' for c in masters) + '}\n')
    lef = lib.parent.parent / 'lef/sky130_fd_sc_hd.lef'
    lef.parent.mkdir()
    lef.write_text(''.join(f'MACRO {c}\n  SIZE 1 BY 1 ;\nEND {c}\n'
                          for c in masters))
    pdk = SimpleNamespace(name="pdkA", liberty=str(lib), macro_libs=[], macro_lefs=[], macro_v=[])
    monkeypatch.setattr(LC, "resolve_image", lambda *_: "img")
    monkeypatch.setattr(LC, "pdk_root_resolution", lambda *a, **k: {"path": str(root)})
    monkeypatch.setattr(P3, "_detect_pdk", lambda project, name: pdk if name == "pdkA" else None)
    # The production caller now validates the registry before this fixture's
    # mocked detector. Keep the synthetic fixture target at that same seam.
    assert_resolvable = P3._assert_pdk_name_resolvable
    monkeypatch.setattr(P3, '_assert_pdk_name_resolvable', lambda name:
                        None if name == 'pdkA' else assert_resolvable(name))

    def resolve(project, image, source, output, **kw):
        cfg = json.loads(source.read_text())
        cfg.update({"SYNTH_TIEHI_CELL": "lib__tieh/Z", "SYNTH_TIELO_CELL": "lib__tiel/ZN",
                    "TRISTATE_CELLS": [], "SYNTH_CHECKS_ALLOW_TRISTATE": True,
                    "SYNTH_ELABORATE_ONLY": False, "SYNTH_TIE_UNDEFINED": "low"})
        put(output, cfg)
        return output
    monkeypatch.setattr(LC, "resolve_step_config", resolve)
    calls = []
    def chain(project, image, steps, **kw):
        calls.append([s[0] for s in steps])
        folders = []
        for index, (sid, cfg_path, state_in) in enumerate(steps, 1):
            folder = p / "phase3/librelane" / f"{index:02d}-{sid.lower().replace('.', '-')}"
            folder.mkdir(parents=True)
            cfg = json.loads(cfg_path.read_text())
            put(folder / "config.json", cfg)
            state = {"metrics": {}}
            if sid == 'Yosys.JsonHeader':
                header = folder / 'top.h.json'
                put(header, {'modules': {'top': {'ports': {}}}})
                state['json_h'] = str(header)
            if sid == "Yosys.Synthesis":
                raw = folder / "top.nl.v"
                text = "module top(clk, a, q);\ninput clk; input a; output [3:0] q;\nwire hi, lo;\n"
                text += ''.join(f"lib__dffq_1 r{i} (.CLK(clk), .D(a), .Q(q[{i}]));\n" for i in range(4))
                text += ''.join(f"lib__buf_1 b{i} (.A(a), .Y(n{i}));\n" for i in range(4))
                text += "lib__tieh th (.Z(hi));\nlib__tiel tl (.ZN(lo));\nendmodule\n"
                raw.write_text(text)
                (folder / "fsm_encoding.enc").write_text("# no recoded FSM\n")
                counts = {"lib__dffq_1": 4, "lib__buf_1": 4, "lib__tieh": 1, "lib__tiel": 1}
                state = {"nl": str(raw), "metrics": {"design__instance_unmapped__count": 0,
                         "synthesis__check_error__count": 0, "design__instance__count": 10,
                         "design__instance__area": 10}}
                put(folder / "reports/stat.json", {"modules": {"\\top": {
                    "num_cells": 10, "num_submodules": 0, "area": 10,
                    "num_cells_by_type": counts}}})
                (folder / "reports/stat.rpt").write_text("=== top ===\n   10 10 cells\n" + ''.join(
                    f"       {n} {n} {c}\n" for c, n in counts.items()) +
                    "   Chip area for module '\\top': 10.000000\n"
                    "     of which used for sequential elements: 4.000000\n")
                # Model Yosys.Synthesis's two CHECK reports and run_chain's
                # receipt-bound command/log envelope before sealing the bytes.
                # These remain neutral transport outputs, not native EDA proof.
                from test_step14_native_receipt_contract import _REAL_LIBRELANE_COMMAND
                for name in ("pre_synth_chk.rpt", "chk.rpt"):
                    (folder / "reports" / name).write_text("Found and reported 0 problems.\n")
                put(folder / "extra.json", {})
                (folder / "COMMANDS").write_text(
                    _REAL_LIBRELANE_COMMAND.replace("__FOLDER__", str(folder)) + "\n")
                (folder / "invocation.log").write_text(
                    "Yosys SOFTWARE_FIXTURE\n"
                    "1. Executing DFFLIBMAP pass (mapping DFF/DLATCH cells).\n"
                    "2. Executing ABC pass (technology mapping).\n"
                    "3. Executing SETUNDEF pass (replace undef values).\n"
                    "4. Executing OPT_CLEAN pass (remove unused cells and wires).\n"
                    "5. Executing HILOMAP pass (mapping to constant drivers).\n"
                    "6. Executing INSBUF pass (insert buffer cells for connected wires).\n")
            put(folder / "state_out.json", state)
            if sid == "Yosys.Synthesis":
                fingerprint = {"step": sid, "image": image,
                               "config": LC.digest(cfg_path),
                               "state_files": {str(header): LC.digest(header)},
                               "config_files": LC.config_file_hashes(
                                   json.loads(cfg_path.read_text()), [(root, "/pdk")])}
                put(folder / "input_fingerprint.json", fingerprint)
                put(folder / "pdk_root.json", {
                    "cli_pdk_root": "/pdk",
                    "mounts_under_it": [[str(root), "/pdk"]],
                    "stated_by": "run_chain(pdk_root=...)"})
                receipt = {"input": fingerprint,
                           "sha256": {str(f.relative_to(folder)): LC.digest(f)
                                      for f in folder.rglob('*') if f.is_file()}}
                put(folder / "vibeic_receipt.json", receipt)
            folders.append(folder)
        return folders
    monkeypatch.setattr(LC, "run_chain", chain)
    # A switch to the old generic producer must be observable without starting
    # an unrelated container. All real gate subprocesses remain executable.
    original_run = subprocess.run
    def subprocess_edge(argv, *args, **kwargs):
        if argv and Path(str(argv[0])).name == 'docker':
            raise AssertionError('generic Docker arm selected instead of LibreLane.run_chain')
        return original_run(argv, *args, **kwargs)
    monkeypatch.setattr(subprocess, 'run', subprocess_edge)
    return p, rtl, pdk, calls


def test_phase1_master_role_is_the_librelane_primary_clock(tmp_path, monkeypatch):
    p, _, _, calls = _synthesis(tmp_path, monkeypatch, ordinary=True)
    put(p / "phase1/generated_docs/L8_TIMING_WAVEFORM.json", {
        "clock_domains": [{
            "name": "clk", "source_pin": "clk", "period_ns": 10,
            "domain_kind": "primary", "role": "master",
        }]
    })

    result = D.step_yosys_synth(p, "top", "unused")

    assert result.status == "PASS", result.detail
    assert calls[0][:2] == ["Yosys.JsonHeader", "Yosys.Synthesis"]


@pytest.mark.parametrize("selected", [None, "pdkA"])
def test_ultra_design_bootstrap_passes_the_normal_resolved_pdk(tmp_path,
                                                               monkeypatch, selected):
    p, _, pdk, _ = _synthesis(tmp_path, monkeypatch, ordinary=True)
    if selected:
        (p / "input/project.json").unlink()
        put(p / "phase1/generated_docs/L19_CONSTRAINTS_PDK.json", {
            "fields": {"pdk_target": "primaryKit", "pdk_target_alternates": ["pdkA"]}})
    observed = {}

    class Execution:
        @staticmethod
        def request():
            return {"mode": "ultra"}

        @staticmethod
        def bootstrap(project, *, parameters):
            observed.update(project=project, parameters=parameters)
            return "runtime"

    result = D._bootstrap_execution_policy(
        Execution, p, top="top", container="unused", ic_class=None,
        skip_analog=True, **({"pdk_name": selected} if selected else {}))
    assert result == "runtime"
    assert observed["project"] == p
    import execution_modes as EM
    import execution_production as EP
    assert observed["parameters"]["pdk"] == EP._pdk_dict(pdk)
    assert observed["parameters"]["pdk"] is not pdk
    assert observed["parameters"]["pdk"]["name"] == pdk.name
    assert observed["parameters"]["pdk"]["liberty"] == pdk.liberty
    assert observed["parameters"]["pdk_name"] == pdk.name
    assert observed["parameters"]["top"] == "top"
    assert "pdk_refusal" not in observed["parameters"]
    # Later fixed frontend rows copy these parameters into Context.objective;
    # prove the exact acceptance-digest boundary that the normal CLI uses.
    json.dumps(observed["parameters"], sort_keys=True)
    step8 = SimpleNamespace(step_id="8", required_gates=("sdc_gate",),
                            objective=observed["parameters"])
    acceptance = EM.Controller.acceptance_contract(
        step8, {"required_output_contract": ["reports/phase2/sdc_check.json"]})
    assert acceptance["objective"]["pdk"]["name"] == pdk.name
    assert EM._hash(acceptance)


def test_selected_secondary_pdk_reaches_the_phase2_producer(tmp_path, monkeypatch):
    p, _, pdk, calls = _synthesis(tmp_path, monkeypatch, ordinary=True)
    (p / "input/project.json").unlink()
    put(p / "phase1/generated_docs/L19_CONSTRAINTS_PDK.json", {
        "fields": {"pdk_target": "primaryKit", "pdk_target_alternates": ["pdkA"],
                   "die_area_budget_um": "1000x1000"}})
    result = D.step_yosys_synth(p, "top", "unused", pdk_name=pdk.name)
    assert result.status == "PASS", result.detail
    assert calls[0] == ["Yosys.JsonHeader", "Yosys.Synthesis",
                        "Checker.YosysUnmappedCells", "Checker.YosysSynthChecks",
                        "Checker.NetlistAssignStatements"]
    cfg = json.loads((p / "phase3/librelane/synthesis_resolved.json").read_text())
    assert cfg["PDK"] == pdk.name
    assert H.bound_handoff(p)["verdict"] == "PASS"


@pytest.mark.parametrize("alternates,expected", [(["pdkA"], "PASS"), ([], "FAIL"),
                                                (["otherKit"], "FAIL")])
def test_native_handoff_accepts_only_a_declared_secondary_target(tmp_path, monkeypatch,
                                                               alternates, expected):
    p, _, _, _ = _synthesis(tmp_path, monkeypatch, ordinary=True)
    result = D.step_yosys_synth(p, "top", "unused")
    assert result.status == "PASS", result.detail
    (p / "input/project.json").unlink()
    put(p / "phase1/generated_docs/L19_CONSTRAINTS_PDK.json", {
        "fields": {"pdk_target": "primaryKit", "pdk_target_alternates": alternates}})
    report = H.bound_handoff(p)
    assert report["verdict"] == expected, report


def test_frontdoor_passes_the_selected_pdk_to_phase2():
    import vibe_ic_one_shot_runner as frontdoor
    common = dict(top_name="top", container="eda", max_rtl_repair_retries=3,
                  lec_max_completed_rungs=None, skip_hardware=True,
                  skip_phase3=False, skip_analog=True, entry_step="9", exit_step="14")
    argv = frontdoor._phase2_runner_argv(Path("/project"), pdk="secondaryKitD", **common)
    assert argv[argv.index("--pdk") + 1] == "secondaryKitD"
    assert "--pdk" not in frontdoor._phase2_runner_argv(Path("/project"), **common)


@pytest.mark.parametrize("primary,alternates,selected,expected", [
    ("primaryKit", ["secondaryKit"], "secondaryKitD", "secondaryKitD"),
    ("primaryKitA", [], "primaryKitB", "LL_PHASE2_PDK_CONFLICT"),
    ("custom_kit_q7", [], "custom_kit_q7", "custom_kit_q7"),
    ("primaryKit", [], "unrelatedKit", "LL_PHASE2_PDK_CONFLICT"),
    ("primaryKit", ["untyped alternate"], "primaryKit", "LL_PHASE2_PDK_INVALID"),
])
def test_selected_pdk_preserves_declaration_refusals(tmp_path, primary, alternates,
                                                   selected, expected):
    put(tmp_path / "phase1/generated_docs/L19_CONSTRAINTS_PDK.json", {
        "fields": {"pdk_target": primary, "pdk_target_alternates": alternates}})
    if expected.startswith("LL_"):
        with pytest.raises(LC.Refusal) as exc:
            LC.phase2_pdk(tmp_path, selected=selected)
        assert exc.value.code == expected
    else:
        assert LC.phase2_pdk(tmp_path, selected=selected)[0] == expected


def test_phase2_pdk_uses_adopted_target_not_staged_family_as_second_declaration(
        tmp_path):
    """The Phase-1 staging record preserves provenance, not two targets."""
    put(tmp_path / "phase1/pdk_staging_read.json", {
        "staged_identifier": "gf180mcu",
        "adopted_pdk_target": "gf180mcuD",
        "adopted_evidence_source": "command_line",
    })
    put(tmp_path / "phase1/generated_docs/L19_CONSTRAINTS_PDK.json", {
        "fields": {
            "pdk_target": "gf180mcuD",
            "pdk_target_alternates": ["gf180mcu"],
        }
    })

    assert LC.phase2_pdk(tmp_path, selected="gf180mcuD")[0] == "gf180mcuD"


@pytest.mark.parametrize("damage", ["missing", "conflict"])
def test_ultra_design_bootstrap_keeps_bad_pdk_fail_closed(tmp_path, monkeypatch,
                                                          damage):
    p, _, _, _ = _synthesis(tmp_path, monkeypatch, ordinary=True)
    if damage == "missing":
        (p / "input/project.json").unlink()
        (p / "phase1/generated_docs/L19_CONSTRAINTS_PDK.json").unlink()
    else:
        put(p / "phase3/librelane_switch.json", {"pdk": "otherPDK"})
    observed = {}

    class Execution:
        @staticmethod
        def request():
            return {"mode": "ultra"}

        @staticmethod
        def bootstrap(project, *, parameters):
            observed.update(parameters)
            return "runtime"

    assert D._bootstrap_execution_policy(
        Execution, p, top="top", container="unused", ic_class=None,
        skip_analog=False) == "runtime"
    assert "pdk" not in observed
    assert observed["pdk_refusal"].startswith(
        "LL_PHASE2_PDK_UNDECLARED" if damage == "missing"
        else "LL_PHASE2_PDK_CONFLICT")


def test_default_design_bootstrap_does_not_resolve_or_probe_pdk(tmp_path,
                                                                monkeypatch):
    observed = {}
    monkeypatch.setattr(D, "_phase2_pdk_config",
                        lambda *_: pytest.fail("Default resolved a PDK"))

    class Execution:
        @staticmethod
        def request():
            return {"mode": "default"}

        @staticmethod
        def bootstrap(project, *, parameters):
            observed.update(parameters)
            return None

    assert D._bootstrap_execution_policy(
        Execution, tmp_path, top="top", container="unused", ic_class=None,
        skip_analog=False) is None
    assert "pdk" not in observed and "pdk_refusal" not in observed


def _produce(tmp_path, monkeypatch, *, ordinary=False):
    p, rtl, pdk, calls = _synthesis(tmp_path, monkeypatch, ordinary=ordinary)
    stale = p / "phase2/stage2/synth/netlist.v"
    stale.parent.mkdir(parents=True)
    stale.write_text("module old; endmodule\n")
    row = D.step_yosys_synth(p, "top", "unused") if ordinary else P3.step_synth(p, "top", pdk, "unused")
    assert row.status == "PASS", row.detail
    return p, rtl, calls


def _staged_synthesis_library(tmp_path, monkeypatch, route):
    """Reuse the production-caller fixture with the canonical staging shape."""
    import shutil

    p, _, pdk, calls = _synthesis(tmp_path, monkeypatch, ordinary=True)
    library = Path(pdk.liberty)
    root = library.parents[4]
    pdk.name = library.parents[3].name
    put(p / "input/project.json", {"pdk": pdk.name})
    doc = json.loads((p / "phase1/generated_docs/L19_CONSTRAINTS_PDK.json").read_text())
    doc["fields"]["pdk_target"] = pdk.name
    put(p / "phase1/generated_docs/L19_CONSTRAINTS_PDK.json", doc)
    monkeypatch.setattr(P3, "_detect_pdk", lambda project, name: pdk if name == pdk.name else None)
    image_root = Path("/image-selected-pdks")
    monkeypatch.setattr(P3, "PDKS_IN_CONTAINER", str(image_root))
    relative = library.relative_to(root)
    staging = {"path": str(root), "source": "resolved", "derivation": {
        "pdk": pdk.name, "image_pdk_root": str(image_root),
        "guest_path": str(image_root / pdk.name), "host_path": str(root / pdk.name)}}
    if route in ("ciel", "declared_ciel"):
        relative = Path("ciel/family/versions/version-id") / relative
    if route == "declared_ciel":
        target = root / relative
        shutil.copytree(root / pdk.name, target.parents[3])
        library = target
        staging = {"path": str(root), "source": "declared"}
    pdk.liberty = str(library if route == "host" else image_root / relative)
    monkeypatch.setattr(LC, "pdk_root_resolution", lambda *a, **k: staging)
    return p, pdk, calls, library, staging, relative


@pytest.mark.parametrize("route", ["ciel", "named", "host", "declared_ciel"])
def test_step9_staged_library_mapping_preserves_selected_bytes(tmp_path, monkeypatch, route):
    p, pdk, calls, library, staging, _ = _staged_synthesis_library(tmp_path, monkeypatch, route)
    expected_hash = LC.digest(library)
    row = D.step_yosys_synth(p, "top", "unused")
    assert row.status == "PASS", row.detail
    assert Path(pdk.liberty) == library
    assert LC.digest(Path(pdk.liberty)) == expected_hash
    cfg = json.loads((p / "phase3/librelane/synth_config.json").read_text())
    root = Path(staging["path"])
    expected = "/pdk/" + str(library.relative_to(root))
    assert cfg["LIB"] == {"*": [expected]}
    assert cfg["PDK"] == pdk.name
    assert "Yosys.Synthesis" in calls[0]
    assert H.bound_handoff(p)["verdict"] == "PASS"
    assert P3.pnr_input_netlist(p, "top")[0].read_bytes() == (p / "phase2/stage2/synth/netlist.v").read_bytes()


@pytest.mark.parametrize("damage", ["missing", "foreign", "staging_conflict"])
def test_step9_staged_library_missing_or_conflicting_assets_refuse_before_tool(
        tmp_path, monkeypatch, damage):
    p, pdk, calls, library, staging, relative = _staged_synthesis_library(tmp_path, monkeypatch, "ciel")
    root = Path(staging["path"])
    if damage == "missing":
        library.unlink()
    elif damage == "foreign":
        relative = Path(*relative.parts[:4], "otherPDK", *relative.parts[5:])
        decoy = root / relative
        decoy.parent.mkdir(parents=True)
        decoy.write_bytes(library.read_bytes())
        pdk.liberty = str(Path(P3.PDKS_IN_CONTAINER) / relative)
    else:
        staging["derivation"]["pdk"] = "otherPDK"
    row = D.step_yosys_synth(p, "top", "unused")
    assert row.status == "FAIL", row
    assert "LL_PDK_LIB_" in row.detail
    assert calls == []
    assert not (p / "phase2/stage2/synth/netlist.v").exists()


def test_step9_phase2_default_publishes_exact_tool_bytes_and_step14_passes(tmp_path, monkeypatch):
    p, _, calls = _produce(tmp_path, monkeypatch, ordinary=True)
    assert calls == [["Yosys.JsonHeader", "Yosys.Synthesis", "Checker.YosysUnmappedCells",
                     "Checker.YosysSynthChecks", "Checker.NetlistAssignStatements"]]
    mapped = p / "phase2/stage2/synth/top_synth.v"
    assert mapped.read_bytes() == (mapped.parent / "netlist.v").read_bytes()
    assert P3.pnr_input_netlist(p, "top")[0].read_bytes() == mapped.read_bytes()
    folder = p / "phase3/librelane/02-yosys-synthesis"
    receipt = json.loads((folder / "vibeic_receipt.json").read_text())
    assert H.critical_synthesis_checks(
        folder, json.loads((folder / "config.json").read_text())) == {
            "pre_synth_chk.rpt": 0, "chk.rpt": 0}
    for report in ("reports/pre_synth_chk.rpt", "reports/chk.rpt"):
        assert receipt["sha256"][report] == LC.digest(folder / report)
    for gate in ("yosys_hilomap_required_check", "yosys_script_template_check",
                 "yosys_tiecell_recipe_order_check"):
        cp = _run_clause(p, _clause("14", gate))
        assert cp.returncode == 0, cp.stdout + cp.stderr
        assert "VACUOUS" not in cp.stdout


def test_step14_maps_guest_pdk_config_material_from_producer_mount(tmp_path, monkeypatch):
    """A host receipt reader must resolve a recorded guest TECH_LEF path."""
    p, _, _ = _produce(tmp_path, monkeypatch, ordinary=True)
    folder = p / "phase3/librelane/02-yosys-synthesis"
    receipt_path = folder / "vibeic_receipt.json"
    receipt = json.loads(receipt_path.read_text())

    pdk_record = json.loads((folder / "pdk_root.json").read_text())
    host_root = Path(pdk_record["mounts_under_it"][0][0])
    resolved_path = p / "phase3/librelane/synthesis_resolved.json"
    resolved = json.loads(resolved_path.read_text())
    guest = "/pdk/pdkA/libs.ref/techlef/tech.nom.tlef"
    resolved["TECH_LEFS"] = {"nom_*": guest}
    put(resolved_path, resolved)
    tech_lef = host_root / "pdkA/libs.ref/techlef/tech.nom.tlef"
    tech_lef.parent.mkdir(parents=True)
    tech_lef.write_text("VERSION 5.8 ;\\n")
    fingerprint = json.loads((folder / "input_fingerprint.json").read_text())
    fingerprint["config"] = LC.digest(resolved_path)
    fingerprint["config_files"] = LC.config_file_hashes(
        resolved, [(host_root, "/pdk")])
    put(folder / "input_fingerprint.json", fingerprint)
    receipt["input"] = fingerprint
    put(folder / "pdk_root.json", {
        "cli_pdk_root": "/pdk",
        "mounts_under_it": [[str(host_root), "/pdk"]],
        "stated_by": "run_chain(pdk_root=...)"})
    receipt["sha256"]["pdk_root.json"] = LC.digest(folder / "pdk_root.json")
    receipt["sha256"]["input_fingerprint.json"] = LC.digest(folder / "input_fingerprint.json")
    put(receipt_path, receipt)
    sidecar = p / "phase2/stage2/synth/synth_inputs.json"
    sidecar_doc = json.loads(sidecar.read_text())
    sidecar_doc["librelane_synthesis"]["receipt_sha256"] = LC.digest(receipt_path)
    put(sidecar, sidecar_doc)

    assert H.bound_handoff(p)["verdict"] == "PASS"

    # Reverse control: a foreign guest mount must remain a hard failure.
    record = json.loads((folder / "pdk_root.json").read_text())
    record["mounts_under_it"] = [[str(host_root), "/foreign"]]
    put(folder / "pdk_root.json", record)
    receipt["sha256"]["pdk_root.json"] = LC.digest(folder / "pdk_root.json")
    put(receipt_path, receipt)
    sidecar_doc["librelane_synthesis"]["receipt_sha256"] = LC.digest(receipt_path)
    put(sidecar, sidecar_doc)
    failed = H.bound_handoff(p)
    assert failed["verdict"] == "FAIL"
    assert any("pdk" in finding.lower() or "mount" in finding.lower()
               for finding in failed["findings"])

    # Changed and missing mapped assets remain hard failures.
    record["mounts_under_it"] = [[str(host_root), "/pdk"]]
    put(folder / "pdk_root.json", record)
    receipt["sha256"]["pdk_root.json"] = LC.digest(folder / "pdk_root.json")
    put(receipt_path, receipt)
    sidecar_doc["librelane_synthesis"]["receipt_sha256"] = LC.digest(receipt_path)
    put(sidecar, sidecar_doc)
    tech_lef.write_text("VERSION 5.8 ; tampered\\n")
    assert H.bound_handoff(p)["verdict"] == "FAIL"
    tech_lef.unlink()
    assert H.bound_handoff(p)["verdict"] == "FAIL"

    # A valid producer may have no extra PDK mount when every recorded
    # config-file key is already host-readable; the shared resolver owns the
    # empty-mount semantics.
    resolved["TECH_LEFS"] = {"nom_*": str(tech_lef)}
    put(resolved_path, resolved)
    tech_lef.write_text("VERSION 5.8 ; host-readable\\n")
    fingerprint["config"] = LC.digest(resolved_path)
    fingerprint["config_files"] = LC.config_file_hashes(resolved, [])
    put(folder / "input_fingerprint.json", fingerprint)
    receipt["input"] = fingerprint
    record["mounts_under_it"] = []
    put(folder / "pdk_root.json", record)
    receipt["sha256"]["pdk_root.json"] = LC.digest(folder / "pdk_root.json")
    receipt["sha256"]["input_fingerprint.json"] = LC.digest(folder / "input_fingerprint.json")
    put(receipt_path, receipt)
    sidecar_doc["librelane_synthesis"]["receipt_sha256"] = LC.digest(receipt_path)
    put(sidecar, sidecar_doc)
    assert H.bound_handoff(p)["verdict"] == "PASS"


def test_step14_rebinds_missing_host_mount_only_by_recorded_runtime_digests(
        tmp_path, monkeypatch):
    """A container consumer may not see the producer's host cache path."""
    import shutil

    p, _, _ = _produce(tmp_path, monkeypatch, ordinary=True)
    folder = p / "phase3/librelane/02-yosys-synthesis"
    receipt_path = folder / "vibeic_receipt.json"
    receipt = json.loads(receipt_path.read_text())
    record = json.loads((folder / "pdk_root.json").read_text())
    producer_root = Path(record["mounts_under_it"][0][0])
    runtime_root = tmp_path / "runtime-pdk"
    shutil.copytree(producer_root, runtime_root)

    # The recorded host path is absent in this consumer namespace; the guest
    # mount is still the producer's declared /pdk root.
    record["mounts_under_it"] = [[str(tmp_path / "unmounted-cache"), "/pdk"]]
    put(folder / "pdk_root.json", record)
    receipt["sha256"]["pdk_root.json"] = LC.digest(folder / "pdk_root.json")
    put(receipt_path, receipt)
    sidecar = p / "phase2/stage2/synth/synth_inputs.json"
    sidecar_doc = json.loads(sidecar.read_text())
    sidecar_doc["librelane_synthesis"]["receipt_sha256"] = LC.digest(receipt_path)
    put(sidecar, sidecar_doc)
    monkeypatch.setenv("PDK_ROOT", str(runtime_root))

    assert H.bound_handoff(p)["verdict"] == "PASS"

    # Reverse control: one changed consumed PDK byte remains foreign/unbound.
    recorded = next(iter(receipt["input"]["config_files"]))
    changed = runtime_root / Path(recorded).relative_to("/pdk")
    changed.write_text(changed.read_text() + "\nchanged\n")
    failed = H.bound_handoff(p)
    assert failed["verdict"] == "FAIL", failed
    assert any("pdk" in finding.lower() or "config material" in finding.lower()
               for finding in failed["findings"])


@pytest.mark.parametrize("damage", ["empty", "malformed", "partial",
                                     "escape", "symlink"])
def test_runtime_pdk_rebinding_refuses_incomplete_or_unsafe_census(
        tmp_path, monkeypatch, damage):
    import copy
    import shutil

    p, _, _ = _produce(tmp_path, monkeypatch, ordinary=True)
    folder = p / "phase3/librelane/02-yosys-synthesis"
    receipt = json.loads((folder / "vibeic_receipt.json").read_text())
    record = json.loads((folder / "pdk_root.json").read_text())
    runtime_root = tmp_path / "runtime-pdk"
    shutil.copytree(record["mounts_under_it"][0][0], runtime_root)
    monkeypatch.setenv("PDK_ROOT", str(runtime_root))

    damaged = copy.deepcopy(receipt)
    files = damaged["input"]["config_files"]
    first = next(iter(files))
    if damage == "empty":
        damaged["input"]["config_files"] = {}
    elif damage == "malformed":
        files[first] = ""
    elif damage == "partial":
        (runtime_root / Path(first).relative_to("/pdk")).unlink()
    elif damage == "escape":
        damaged["input"]["config_files"] = {
            "/pdk/../escape": files[first]}
    else:
        candidate = runtime_root / Path(first).relative_to("/pdk")
        outside = tmp_path / "outside-pdk-file"
        outside.write_bytes(candidate.read_bytes())
        candidate.unlink()
        candidate.symlink_to(outside)

    assert H._runtime_pdk_mount(Path("/pdk"), Path("/pdk"), damaged) is None



def _relocated_native_sources(tmp_path, monkeypatch, *, ciel=False):
    """Existing full handoff consumer, with neutral retained Nix source paths."""
    import importlib.util
    import shutil

    p, _, _ = _produce(tmp_path, monkeypatch, ordinary=True)
    folder = p / 'phase3/librelane/02-yosys-synthesis'
    store = tmp_path / 'store'
    monkeypatch.setattr(H, '_NIX_STORE', store, raising=False)
    revision = 'a' * 40
    package = store / ('b' * 32 + '-pdk-pdkA-' + revision)
    assets = package / 'pdkA'
    assets.mkdir(parents=True)
    liberty = assets / 'model.lib'
    liberty.write_text('library (neutral) { cell (buf) { area : 1; } }\n')
    lef = assets / 'tech.lef'
    lef.write_text('VERSION 5.8 ;\n')
    runtime = tmp_path / 'runtime-sdk'
    (runtime / 'pdkA').mkdir(parents=True)
    for asset in (liberty, lef):
        (runtime / 'pdkA' / asset.name).symlink_to(asset)
    module = store / ('c' * 32 + '-librelane-source') / 'lib/python3.12/site-packages/librelane'
    (module / 'scripts').mkdir(parents=True)
    (module / '__init__.py').write_text('')
    sdc = module / 'scripts/base.sdc'
    sdc.write_text('# neutral installed base SDC\n')
    find_spec = importlib.util.find_spec
    monkeypatch.setattr(importlib.util, 'find_spec', lambda name, *a, **k:
                        SimpleNamespace(origin=str(module / '__init__.py')) if name == 'librelane'
                        else find_spec(name, *a, **k))
    monkeypatch.setenv('PDK_ROOT', str(runtime))
    root = tmp_path / 'absent-sdk'
    old_lib = ((root / 'ciel/family/versions' / revision / 'pdkA/model.lib') if ciel else
               store / ('a' * 32 + '-pdk-pdkA-' + revision) / 'pdkA/model.lib')
    old_sdc = store / ('d' * 32 + '-python-env') / 'lib/python3.12/site-packages/librelane/scripts/base.sdc'
    cfg = json.loads((folder / 'config.json').read_text())
    cfg.update(LIB={'*': [str(old_lib)]}, TECH_LEFS={'nom_*': str(root / 'pdkA/tech.lef')},
               FALLBACK_SDC_FILE=str(old_sdc))
    put(folder / 'config.json', cfg)
    put(p / 'phase3/librelane/synthesis_resolved.json', cfg)
    receipt_path = folder / 'vibeic_receipt.json'
    receipt = json.loads(receipt_path.read_text())
    receipt['input']['config'] = LC.digest(p / 'phase3/librelane/synthesis_resolved.json')
    files = {str(root / 'pdkA/tech.lef'): LC.digest(lef), str(old_lib): LC.digest(liberty),
             str(old_sdc): LC.digest(sdc)}
    files.update({str(v): LC.digest(Path(v)) for v in cfg['VERILOG_FILES']})
    receipt['input']['config_files'] = files
    put(folder / 'input_fingerprint.json', receipt['input'])
    put(folder / 'pdk_root.json', {'cli_pdk_root': str(root),
        'mounts_under_it': [[str(tmp_path / 'absent-host'), str(root)]],
        'stated_by': 'run_chain(pdk_root=...)'})
    for name in ('config.json', 'input_fingerprint.json', 'pdk_root.json'):
        receipt['sha256'][name] = LC.digest(folder / name)
    put(receipt_path, receipt)
    sidecar = p / 'phase2/stage2/synth/synth_inputs.json'
    doc = json.loads(sidecar.read_text())
    doc['librelane_synthesis']['receipt_sha256'] = LC.digest(receipt_path)
    put(sidecar, doc)
    return p, runtime, liberty, lef, sdc, files


@pytest.mark.parametrize('ciel', [False, True])
def test_native_handoff_rebinds_same_nix_or_ciel_sources(tmp_path, monkeypatch, ciel):
    p, _, liberty, lef, sdc, files = _relocated_native_sources(tmp_path, monkeypatch, ciel=ciel)
    report = H.bound_handoff(p)
    assert report['verdict'] == 'PASS', report
    assert set(report['consumed_config_files']) == set(files)
    paths = {v['path'] for v in report['consumed_config_files'].values()}
    assert {str(liberty), str(lef), str(sdc)} <= paths
    assert {k: v['sha256'] for k, v in report['consumed_config_files'].items()} == files


@pytest.mark.parametrize('damage', ['liberty', 'base_sdc', 'wrong_sdk', 'foreign_revision',
                                     'unqualified_copy', 'escape_pdk', 'escape_sdc'])
def test_native_handoff_relocated_sources_refuse_before_tool(tmp_path, monkeypatch, damage):
    import shutil
    p, runtime, liberty, lef, sdc, _ = _relocated_native_sources(tmp_path, monkeypatch)
    if damage in ('liberty', 'base_sdc'):
        changed = liberty if damage == 'liberty' else sdc
        changed.write_text(changed.read_text() + '# changed consumed byte\n')
    elif damage in ('wrong_sdk', 'foreign_revision'):
        old = liberty.parent.parent
        target = old.with_name('e' * 32 + '-pdk-' +
                               ('otherPDK-' + 'a' * 40 if damage == 'wrong_sdk'
                                else 'pdkA-' + 'f' * 40))
        shutil.copytree(old, target)
        if damage == 'wrong_sdk':
            (target / 'pdkA').rename(target / 'otherPDK')
        for link in (runtime / 'pdkA').iterdir():
            link.unlink()
            link.symlink_to(target / ('otherPDK' if damage == 'wrong_sdk' else 'pdkA') / link.name)
    elif damage == 'unqualified_copy':
        for link in (runtime / 'pdkA').iterdir():
            content = link.read_bytes()
            link.unlink()
            link.write_bytes(content)
    else:
        link = runtime / 'pdkA/tech.lef' if damage == 'escape_pdk' else sdc
        outside = tmp_path / 'foreign-file'
        outside.write_bytes(link.read_bytes())
        link.unlink()
        link.symlink_to(outside)
    monkeypatch.setattr(LC, 'run_chain', lambda *a, **k: pytest.fail('native tool dispatched'))
    report = H.bound_handoff(p)
    assert report['verdict'] == 'FAIL', report
    assert report['reason_class'] == 'tool_handoff_invalid'
    assert 'consumed_config_files' not in report


def test_step9_default_keeps_existing_phase2_coupling_gate(tmp_path, monkeypatch):
    p, _, _, calls = _synthesis(tmp_path, monkeypatch, ordinary=True)
    monkeypatch.setattr(D, '_chip_top_coupling_refusals', lambda *_: [
        {'trigger_parameter': 'mode', 'required_parameter': 'width',
         'reason': 'UNSTATED', 'message': 'width is not declared'}])
    row = D.step_yosys_synth(p, 'top', 'unused')
    assert row.status == 'FAIL' and 'COUPLED PARAMETER NOT STATED' in row.detail
    assert calls == []


def test_step9_failed_rerun_invalidates_previous_publication(tmp_path, monkeypatch):
    p, _, _ = _produce(tmp_path, monkeypatch)
    assert H.bound_handoff(p)['verdict'] == 'PASS'
    def unavailable(*args, **kwargs):
        raise LC.Refusal('LL_STEP_ERROR', 'controlled failed current tool call')
    monkeypatch.setattr(LC, 'run_chain', unavailable)
    pdk = P3._detect_pdk(p, 'pdkA')
    assert P3.step_synth(p, 'top', pdk, 'unused').status != 'PASS'
    assert H.bound_handoff(p)['verdict'] == 'FAIL'
    assert _run_clause(p, _clause('14', 'yosys_hilomap_required_check')).returncode == 1


@pytest.mark.parametrize("damage", ["canonical", "mapped", "raw", "rtl", "receipt", "config", "stat", "header", "pretool", "bypass",
                                    "pre_check", "final_check", "missing_pre_check", "missing_final_check"])
def test_step9_changed_or_bypassed_tool_output_blocks_gates_and_pnr(tmp_path, monkeypatch, damage):
    p, rtl, _ = _produce(tmp_path, monkeypatch)
    folder = p / "phase3/librelane/02-yosys-synthesis"
    files = {"canonical": p / "phase2/stage2/synth/netlist.v",
             "mapped": p / "phase2/stage2/synth/top_synth.v", "raw": folder / "top.nl.v",
             "rtl": rtl, "receipt": folder / "vibeic_receipt.json",
             "config": folder / "config.json", "stat": folder / "reports/stat.json",
             "header": p / 'phase3/librelane/01-yosys-jsonheader/top.h.json',
             "pre_check": folder / "reports/pre_synth_chk.rpt",
             "final_check": folder / "reports/chk.rpt"}
    if damage in files:
        with files[damage].open('a') as f:
            f.write("\n ")  # valid bytes, different identity (timestamps are irrelevant)
    elif damage in ("missing_pre_check", "missing_final_check"):
        files[damage.removeprefix("missing_")].unlink()
    elif damage == "pretool":
        (p / "phase2/stage2/synth/netlist.v").write_text("module old; endmodule\n")
    else:
        sidecar = p / "phase2/stage2/synth/synth_inputs.json"
        doc = json.loads(sidecar.read_text())
        doc.pop("librelane_synthesis", None)
        put(sidecar, doc)
    # A valid older recipe must not mask a changed tool product.
    (p / "phase2/stage2/synth/old.ys").write_text(
        "read_verilog -sv old.v\nsynth -flatten\ntechmap\n"
        "hilomap -hicell hi Z -locell lo Z\nwrite_verilog old_unrelated.v\n")
    for gate in ("yosys_hilomap_required_check", "yosys_script_template_check"):
        cp = _run_clause(p, _clause("14", gate))
        assert cp.returncode == 1, cp.stdout + cp.stderr
    row = P3.step_pnr(p, "top", None, "unused", "1000x1000", 0.5)
    assert row.status == "FAIL" and "LL_SYNTH_HANDOFF_INVALID" in row.detail
    assert D.step_lec_equivalence(p, "top", "unused")[-1].status == "FAIL"


@pytest.mark.parametrize("damaged", ["COMMANDS", "invocation.log"])
def test_step14_recipe_consumer_rejects_changed_native_envelope(tmp_path, monkeypatch, damaged):
    p, _, _ = _produce(tmp_path, monkeypatch)
    source = p / "phase3/librelane/02-yosys-synthesis" / damaged
    source.write_text(source.read_text() + "\n ")
    # The two product checks stay current. The separately declared advisory
    # recipe-order check must disclose NOT_CHECKED for the stale witness.
    for gate in ("yosys_hilomap_required_check", "yosys_script_template_check"):
        cp = _run_clause(p, _clause("14", gate))
        assert cp.returncode == 0, cp.stdout + cp.stderr
    cp = _run_clause(p, _clause("14", "yosys_tiecell_recipe_order_check"))
    assert cp.returncode == 2, cp.stdout + cp.stderr
    report = json.loads((p / "reports/phase2/gates/yosys_tiecell_recipe_order_verdict.json").read_text())
    assert report["verdict"] == "NOT_CHECKED"
    assert any(f"digest mismatch: {damaged}" in row.get("reason", "")
               for row in report["findings"])
    assert H.bound_handoff(p)["verdict"] == "PASS"


def test_step9_consumers_refuse_changed_canonical_bytes(tmp_path, monkeypatch):
    p, _, _ = _produce(tmp_path, monkeypatch)
    with (p / 'phase2/stage2/synth/netlist.v').open('a') as stream:
        stream.write('\n ')
    with pytest.raises(ValueError, match='LL_SYNTH_HANDOFF_INVALID'):
        P3.pnr_input_netlist(p, 'top')
    assert D.step_lec_equivalence(p, 'top', 'unused')[-1].status == 'FAIL'
    import flow_compliance_check as F
    (p / 'phase2/stage2/synth/old.ys').write_text(
        'read_verilog -sv old.v\nsynth -flatten\ntechmap\n'
        'hilomap -hicell hi Z -locell lo Z\nwrite_verilog old_unrelated.v\n')
    assert F._run_yosys_gates(p)[0] is False


def test_step13_default_keeps_native_proof_of_current_handoff(tmp_path, monkeypatch):
    p, _, _ = _produce(tmp_path, monkeypatch)
    original_run = subprocess.run
    lec_runs = []
    def native(argv, *args, **kwargs):
        if len(argv) > 1 and str(argv[1]).endswith('lec_run.py'):
            lec_runs.append(argv)
            mapped = p / _gate_arg(argv)
            put(p / 'reports/lec.json', {
                'verdict': 'PASS', 'equivalent': True, 'compared_points': 4,
                'non_equivalent_points': 0, 'unproven_points': 0,
                'proof_identity': {'top': 'top', 'gate_netlist': {
                    'path': _gate_arg(argv), 'sha256': 'sha256:' + LC.digest(mapped)}}})
            (p / 'reports/lec.rpt').write_text('Equivalence successfully proven!\nProved 4 $equiv cells.\n')
            return SimpleNamespace(returncode=0, stdout='', stderr='')
        return original_run(argv, *args, **kwargs)
    monkeypatch.setattr(subprocess, 'run', native)
    assert LC.selected_mode(p, "13") == "direct"
    rows = D.step_lec_equivalence(p, "top", "unused")
    assert rows[-1].status == "PASS", rows[-1].detail
    assert len(lec_runs) == 1 and _gate_arg(lec_runs[0]) == "phase2/stage2/synth/top_synth.v"
    assert not (p / "reports/lec_eqy.json").exists()
    assert G.main([str(p)]) == 0


@pytest.mark.parametrize('damage', ['zero_points', 'different_netlist'])
def test_step13_native_gate_rejects_vacuous_or_wrong_subject(tmp_path, monkeypatch, damage):
    test_step13_default_keeps_native_proof_of_current_handoff(tmp_path, monkeypatch)
    p = tmp_path / 'project'
    path = p / 'reports/lec.json'
    doc = json.loads(path.read_text())
    if damage == 'zero_points':
        doc['compared_points'] = 0
        (p / 'reports/lec.rpt').write_text('Equivalence successfully proven!\nProved 0 $equiv cells.\n')
    else:
        doc['proof_identity']['gate_netlist']['sha256'] = 'sha256:' + '0' * 64
    put(path, doc)
    assert G.main([str(p)]) == 1
