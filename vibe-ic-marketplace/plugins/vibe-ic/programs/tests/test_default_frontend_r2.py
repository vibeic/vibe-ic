"""Production Default inputs and tool handoff, without a mode controller."""
import json
from pathlib import Path
from types import SimpleNamespace
import subprocess

import pytest
import design_one_shot_runner as D
import librelane_contract as LC
import phase3_one_shot_runner as P3
from test_t91_step2_verilator_lint_gate import _design, _runner, put, NEG


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






def _produce(tmp_path, monkeypatch, *, ordinary=False):
    p, rtl, pdk, calls = _synthesis(tmp_path, monkeypatch, ordinary=ordinary)
    stale = p / "phase2/stage2/synth/netlist.v"
    stale.parent.mkdir(parents=True)
    stale.write_text("module old; endmodule\n")
    row = D.step_yosys_synth(p, "top", "unused") if ordinary else P3.step_synth(p, "top", pdk, "unused")
    assert row.status == "PASS", row.detail
    return p, rtl, calls
