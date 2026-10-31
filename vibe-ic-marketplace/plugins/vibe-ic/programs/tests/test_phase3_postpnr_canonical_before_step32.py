"""Route dependent canonical outputs survive a later step 32 refusal."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import phase3_one_shot_runner as R
from test_phase3_postpnr_disclosure_and_gds_guard import (
    TOP, OLD_DIE, OLD_UTIL, NEW_DIE, NEW_UTIL, _drive, _plan, _project,
    _repair_producer, _pdk,
)


SPEF = ('*SPEF "IEEE 1481-1998"\n*DESIGN "chip_top"\n'
        + ''.join(f'*D_NET net_{i} 0.1\n*CAP\n1 net_{i} 0.1\n*END\n'
                  for i in range(30)))


def _clock_inputs_and_native_model(project, monkeypatch):
    """Supply Step 16's real input contract; model only the native tool edge.

    The emitter, receipt and read-only consumer remain real. This is a
    publication regression test, not evidence of native IC sign-off.
    """
    import _physical_current as current
    pdk = _pdk(project)
    declared = project / "phase1/generated_docs/L19_CONSTRAINTS_PDK.json"
    declared.parent.mkdir(parents=True, exist_ok=True)
    declared.write_text(json.dumps({"fields": {"pdk_target": pdk.name}}))
    floor = R._pl.pnr_dir(project) / "floorplan.def"
    floor.write_text(f"VERSION 5.8 ;\nDESIGN {TOP} ;\nEND DESIGN\n")
    monkeypatch.setattr(R, "_detect_pdk", lambda *_a, **_k: pdk)
    # The DIE fixture requires IO views too. Keep their actual discovery and
    # digest binding; model just the synthetic PDK's distribution-root lookup.
    pdk_root = Path(pdk.tech_lef).parent
    io = pdk_root / pdk.name / "libs.ref/fixture_io/lef/pad.lef"
    io.parent.mkdir(parents=True, exist_ok=True)
    io.write_text("MACRO input_pad\n  CLASS PAD INPUT ;\nEND input_pad\n")
    monkeypatch.setattr(R, "_padring_pdk_root_and_tree",
                        lambda *_a, **_k: (pdk_root, pdk.name))
    # The extractor in this publication test is the direct producer below.
    switch = project / "phase3/librelane_switch.json"
    settings = json.loads(switch.read_text()) if switch.is_file() else {}
    settings.setdefault("steps", {})["22"] = "direct"
    switch.write_text(json.dumps(settings))

    def native(_project, tool, args, log):
        assert tool == "openroad"
        recipe = Path(args[-1]).read_text()
        decks = re.findall(r"(?m)^read_sdc \{([^}]+)\}$", recipe)
        clocks = R._build_clock_records_from_sdcs(
            [Path(deck).read_text() for deck in decks])
        lines = [f"CLOCK_PLAN_PDK {pdk.name}"]
        lines.extend(f"CLOCK_PLAN_NATIVE {c['name']}|{c['period_ns']}|{c['source']}"
                     for c in clocks.values())
        lines.extend(f"CLOCK_PLAN_SINK_COUNT {name}|0"
                     for name in dict.fromkeys(c['name'] for c in clocks.values()))
        lines.append("CLOCK_PLAN_DONE")
        Path(log).write_text("\n".join(lines) + "\n")
        return 0, {"rc": 0, "argv": [tool, *args]}

    monkeypatch.setattr(current, "run_native", native)


def _step32_failed_project(tmp_path: Path, monkeypatch, *, stale_sdc=False) -> Path:
    # This fixture exercises the legacy enclosing publisher. Default's
    # canonical rows already produced these inputs before entering repair.
    import execution_policy
    original = execution_policy.request
    monkeypatch.setattr(execution_policy, 'request',
                        lambda: dict(original(), mode='ultra'))
    monkeypatch.setattr(execution_policy, 'bootstrap', lambda *a, **k: None)
    monkeypatch.setattr(execution_policy, '_ordinary_runtime', None)
    monkeypatch.setattr(R, '_default_step15_with_backend_receipt',
                        lambda *a, **k: R.step_pnr(*a, **k))
    project = _project(tmp_path, cached_die=OLD_DIE, cached_util=OLD_UTIL)
    pnr = R._pl.pnr_dir(project)
    canonical_sdc = R._pl.constraints_dir(project) / f"{TOP}.sdc"
    if stale_sdc:
        canonical_sdc.write_text(
            "create_clock -name core_clk -period 10 [get_ports clk]\n")
    else:
        canonical_sdc.unlink(missing_ok=True)
    (pnr / "constraint.sdc").write_text(
        "create_clock -name core_clk -period 7 [get_ports clk]\n"
        "set_input_delay 1 -clock core_clk [get_ports data]\n")
    for path in (pnr / "pdn.done", R._pl.cts_dir(project) / "clock_plan.json",
                 R._pl.extracted_dir(project) / f"{TOP}.spef",
                 R._pl.extracted_dir(project) / "parasitic.spef",
                 project / "reports/phase2/sdc_check.json",
                 project / "reports/phase2/gates/spef_extraction.json"):
        path.unlink(missing_ok=True)
    _drive(monkeypatch, project, die=NEW_DIE, util=NEW_UTIL)
    _clock_inputs_and_native_model(project, monkeypatch)
    original_pnr = R.step_pnr

    def route(*args, **kwargs):
        row = original_pnr(*args, **kwargs)
        (pnr / "routed.def").write_bytes((pnr / f"{TOP}.def").read_bytes())
        return row

    monkeypatch.setattr(R, "step_pnr", route)

    def extract(_project, _top, _pdk, _container, output, _notes):
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(SPEF)
        return True

    monkeypatch.setattr(R, "_emit_spef", extract)
    _repair_producer(monkeypatch, project, "direct", "FAIL", "step 32 refused")
    R.main()
    assert _plan(project)["signoff_spef_repair"]["status"] == "FAIL"
    return project


def test_step32_failure_keeps_current_route_artefacts(tmp_path, monkeypatch):
    project = _step32_failed_project(tmp_path, monkeypatch)
    pnr = R._pl.pnr_dir(project)
    route_sha = R._sha256_file(pnr / "routed.def")

    sdc = R._pl.constraints_dir(project) / f"{TOP}.sdc"
    assert "-period 7" in sdc.read_text()
    assert (project / "reports/phase2/sdc_check.json").is_file()
    pdn = (pnr / "pdn.done").read_text()
    assert f"measured_def_sha256: {route_sha}" in pdn
    assert "PDN status: NOT MEASURED" in pdn
    plan = json.loads((R._pl.cts_dir(project) / "clock_plan.json").read_text())
    assert any(clock["period_ns"] == 7 for clock in plan["clocks"])
    spef = R._pl.extracted_dir(project) / f"{TOP}.spef"
    assert spef.read_text() == SPEF
    extraction = json.loads((project / "reports/phase2/gates/spef_extraction.json").read_text())
    assert extraction["summary"]["d_nets"] == 30
    basis = json.loads((project / "reports/phase3/postpnr_canonical_basis.json").read_text())
    assert basis["routed_def_sha256"] == route_sha
    assert basis["spef_sha256"] == R._sha256_file(spef)


def test_step32_failure_refreshes_old_constraint_value(tmp_path, monkeypatch):
    project = _step32_failed_project(tmp_path, monkeypatch, stale_sdc=True)
    sdc = R._pl.constraints_dir(project) / f"{TOP}.sdc"
    assert "-period 7" in sdc.read_text()


def _routed_project(root: Path) -> tuple[Path, Path]:
    pnr = R._pl.pnr_dir(root)
    pnr.mkdir(parents=True, exist_ok=True)
    route = pnr / "routed.def"
    body = "VERSION 5.8 ;\nDESIGN chip_top ;\nDIEAREA ( 0 0 ) ( 1000 1000 ) ;\nEND DESIGN\n"
    route.write_text(body)
    (pnr / f"{TOP}.def").write_text(body)
    (pnr / "constraint.sdc").write_text(
        "create_clock -name core_clk -period 7 [get_ports clk]\n"
        "set_input_delay 1 -clock core_clk [get_ports data]\n")
    return root, route


def test_default_step15_publishes_current_route_before_its_consumer(
        tmp_path, monkeypatch):
    """Preserve the enclosing wrapper's publication checks on its Ultra path.

    Default now checks Floorplan before Placement/Routing; its independent
    per-row order and outputs are tested by test_default_pnr_row_boundaries.
    """
    import execution_policy
    monkeypatch.setattr(execution_policy, 'request', lambda: {'mode': 'ultra'})
    import execution_backend_worker as backend
    import flow_declared_producer_run as declared

    project, route = _routed_project(tmp_path / "project")
    pdk = _pdk(project)
    import _cited_artefacts as cited
    previous = project / cited.REPORT_REL
    previous.parent.mkdir(parents=True)
    previous.write_text(json.dumps({
        "cited_artefacts": {str(route.relative_to(project)): "0" * 64},
    }))
    assert cited.check(project, json.loads(previous.read_text()))[0] == "NOT_MEASURED"

    def extract(_project, _top, _pdk, _container, output, _notes):
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(SPEF)
        return True

    monkeypatch.setattr(R, "_emit_spef", extract)
    monkeypatch.setattr(R, "step_pnr", lambda *a, **k:
                        R.StepResult("pnr", "PASS", detail="route produced",
                                     output_files=[str(route)]))
    seen = []

    def census(_project, step_id):
        current = json.loads(previous.read_text())
        assert current["record"].startswith("in-progress")
        assert cited.check(project, current)[0] == "PASS"
        pdn = (R._pl.pnr_dir(project) / "pdn.done").read_text()
        assert f"measured_def_sha256: {R._sha256_file(route)}" in pdn
        # A missing insertion measurement stays unmeasured; publication
        # supplies the real consumer's input rather than inventing a PASS.
        assert "PDN status: NOT MEASURED" in pdn
        seen.append("producer census")
        return {"verdict": "PRODUCED", "step_id": step_id}

    def consumer(_project, **kwargs):
        assert seen == ["producer census"]
        basis = json.loads((project / "reports/phase3/postpnr_canonical_basis.json")
                           .read_text())
        assert basis["routed_def_sha256"] == R._sha256_file(route)
        seen.append("consumer")
        return {"verdict": "PASS"}

    monkeypatch.setattr(declared, "run_for_step", census)
    monkeypatch.setattr(backend, "execute_current_step", consumer)
    row = R._default_step15_with_backend_receipt(
        project, TOP, pdk, "", NEW_DIE, NEW_UTIL)
    assert row.status == "PASS"
    assert seen == ["producer census", "consumer"]


def test_default_step15_failed_route_never_publishes_success_outputs(
        tmp_path, monkeypatch):
    """The retained enclosing producer must still refuse stale output credit."""
    import execution_policy
    monkeypatch.setattr(execution_policy, 'request', lambda: {'mode': 'ultra'})
    import execution_backend_worker as backend
    import flow_declared_producer_run as declared

    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setattr(R, "step_pnr", lambda *a, **k:
                        R.StepResult("pnr", "FAIL", detail="route refused"))

    def forbidden(*args, **kwargs):
        raise AssertionError("failed route must not publish canonical outputs")

    monkeypatch.setattr(R, "_canonicalize_postpnr_prerequisites", forbidden)
    monkeypatch.setattr(declared, "run_for_step", lambda *a, **k:
                        {"verdict": "INCOMPLETE"})
    monkeypatch.setattr(backend, "execute_current_step", lambda *a, **k:
                        {"verdict": "FAIL"})
    row = R._default_step15_with_backend_receipt(
        project, TOP, _pdk(project), "", NEW_DIE, NEW_UTIL)
    assert row.status == "FAIL"
    assert not (R._pl.pnr_dir(project) / "pdn.done").exists()


def test_same_route_is_byte_idempotent_and_changed_route_reextracts(
        tmp_path, monkeypatch):
    project, route = _routed_project(tmp_path)
    _clock_inputs_and_native_model(project, monkeypatch)
    emitted = []

    def extract(_project, _top, _pdk, _container, output, _notes):
        emitted.append(R._sha256_file(route))
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(SPEF + f"// route {emitted[-1]}\n")
        return True

    monkeypatch.setattr(R, "_emit_spef", extract)
    pdk = _pdk(project)
    first = R._canonicalize_postpnr_prerequisites(project, TOP, pdk, "")
    assert first.status == "NOT_MEASURED", first.detail
    products = [R._pl.constraints_dir(project) / f"{TOP}.sdc",
                project / "reports/phase2/sdc_check.json",
                R._pl.pnr_dir(project) / "pdn.done",
                R._pl.cts_dir(project) / "clock_plan.json",
                R._pl.extracted_dir(project) / f"{TOP}.spef",
                project / "reports/phase2/gates/spef_extraction.json",
                project / "reports/phase3/postpnr_canonical_basis.json"]
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in products}
    again = R._canonicalize_postpnr_prerequisites(project, TOP, pdk, "")
    assert again.status == "NOT_MEASURED" and not again.output_files
    assert emitted == [R._sha256_file(route)]
    assert before == {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in products}

    old_times = (route.stat().st_atime_ns, route.stat().st_mtime_ns)
    new_body = route.read_text().replace("1000 1000", "2000 2000")
    route.write_text(new_body)
    (R._pl.pnr_dir(project) / f"{TOP}.def").write_text(new_body)
    os.utime(route, ns=old_times)
    changed = R._canonicalize_postpnr_prerequisites(project, TOP, pdk, "")
    assert changed.status == "NOT_MEASURED", changed.detail
    assert len(emitted) == 2 and emitted[0] != emitted[1]
    assert products[4].read_bytes() != before[products[4]][0]
    basis = json.loads(products[-1].read_text())
    assert basis["routed_def_sha256"] == emitted[-1]
    assert basis["spef_sha256"] == R._sha256_file(products[4])
    assert "gds" not in " ".join(str(p) for p in changed.output_files)


def test_missing_route_or_extraction_never_claims_spef(tmp_path, monkeypatch):
    project = tmp_path / "project"
    pnr = R._pl.pnr_dir(project)
    pnr.mkdir(parents=True)
    (pnr / "constraint.sdc").write_text(
        "create_clock -name core_clk -period 7 [get_ports clk]\n")
    pdk = _pdk(project)
    missing = R._canonicalize_postpnr_prerequisites(project, TOP, pdk, "")
    assert missing.status == "NOT_MEASURED"
    assert not (project / "reports/phase3/postpnr_canonical_basis.json").exists()
    assert not (R._pl.constraints_dir(project) / f"{TOP}.sdc").exists()

    _, route = _routed_project(project)
    monkeypatch.setattr(R, "_emit_spef", lambda *a, **k: False)
    failed = R._canonicalize_postpnr_prerequisites(project, TOP, pdk, "")
    assert failed.status == "NOT_MEASURED"
    assert not (R._pl.extracted_dir(project) / f"{TOP}.spef").exists()
    assert not (project / "reports/phase2/gates/spef_extraction.json").exists()
    basis = json.loads((project / "reports/phase3/postpnr_canonical_basis.json").read_text())
    assert basis["status"] == "NOT_MEASURED"
    assert basis["routed_def_sha256"] == R._sha256_file(route)
    assert basis["spef_sha256"] is None


def test_same_route_changed_extraction_pdk_reextracts(tmp_path, monkeypatch):
    project, _route = _routed_project(tmp_path)
    pdk = _pdk(project)
    tech = Path(pdk.tech_lef)
    emitted = []

    def extract(_project, _top, _pdk, _container, output, _notes):
        emitted.append(R._sha256_file(tech))
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(SPEF + f"// tech {emitted[-1]}\n")
        return True

    monkeypatch.setattr(R, "_emit_spef", extract)
    R._canonicalize_postpnr_prerequisites(project, TOP, pdk, "")
    R._canonicalize_postpnr_prerequisites(project, TOP, pdk, "")
    assert len(emitted) == 1

    tech.write_text(tech.read_text() + "LAYER M1 TYPE ROUTING ; END M1\n")
    R._canonicalize_postpnr_prerequisites(project, TOP, pdk, "")
    assert len(emitted) == 2
    basis = json.loads((project / "reports/phase3/postpnr_canonical_basis.json").read_text())
    assert basis["extraction_inputs"]["pdk_files"][str(tech)] == emitted[-1]
    assert basis["spef_sha256"] == R._sha256_file(
        R._pl.extracted_dir(project) / f"{TOP}.spef")


def test_same_route_changed_declared_rc_rules_reextracts(tmp_path, monkeypatch):
    project, _route = _routed_project(tmp_path)
    pdk = _pdk(project)
    rules = tmp_path / "nom.rules"
    rules.write_text("model one\n")
    monkeypatch.setattr(R, "_openrcx_ruleset_declaration", lambda *_: {
        "status": "DECLARED", "declaration": [],
        "corners": {"nom": {"path": str(rules), "pattern": "nom_*",
                            "declared_by": "fixture config"}}, "detail": ""})
    emitted = []

    def extract(_project, _top, _pdk, _container, output, _notes):
        emitted.append(R._sha256_file(rules))
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(SPEF + f"// rules {emitted[-1]}\n")
        return True

    monkeypatch.setattr(R, "_emit_spef", extract)
    R._canonicalize_postpnr_prerequisites(project, TOP, pdk, "")
    rules.write_text("model two\n")
    R._canonicalize_postpnr_prerequisites(project, TOP, pdk, "")
    assert len(emitted) == 2 and emitted[0] != emitted[1]
    basis = json.loads((project / "reports/phase3/postpnr_canonical_basis.json").read_text())
    assert basis["extraction_inputs"]["pdk_files"][str(rules)] == emitted[-1]


def test_step22_mode_change_reextracts_same_route(tmp_path, monkeypatch):
    project, _route = _routed_project(tmp_path)
    pdk = _pdk(project)
    mode = ["dual"]
    monkeypatch.setattr(R, "_librelane_signoff_modes", lambda _p: (mode[0], "direct"))
    calls = []

    def extract(_project, _top, _pdk, _container, output, _notes):
        calls.append(mode[0])
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(SPEF + f"// mode {mode[0]}\n")
        return True

    monkeypatch.setattr(R, "_emit_spef", extract)
    R._canonicalize_postpnr_prerequisites(project, TOP, pdk, "")
    mode[0] = "direct"
    R._canonicalize_postpnr_prerequisites(project, TOP, pdk, "")
    assert calls == ["dual", "direct"]
    basis = json.loads((project / "reports/phase3/postpnr_canonical_basis.json").read_text())
    assert basis["extraction_inputs"]["mode"] == "direct"


def test_unmeasured_pdn_and_failed_sdc_do_not_pass_receipt(tmp_path, monkeypatch):
    project, _route = _routed_project(tmp_path)
    monkeypatch.setattr(R, "_emit_spef", lambda _p, _t, _d, _c, out, _n:
                        (out.parent.mkdir(parents=True, exist_ok=True),
                         out.write_text(SPEF), True)[-1])
    pdk = _pdk(project)
    first = R._canonicalize_postpnr_prerequisites(project, TOP, pdk, "")
    basis_path = project / "reports/phase3/postpnr_canonical_basis.json"
    basis = json.loads(basis_path.read_text())
    assert first.status == basis["status"] == "NOT_MEASURED"
    assert basis["outputs"]["pdn"]["status"] == "NOT_MEASURED"
    assert basis["outputs"]["sdc_check"]["status"] == "PASS"

    (R._pl.pnr_dir(project) / "constraint.sdc").write_text(
        "create_clock -period banana [get_ports clk]\n")
    second = R._canonicalize_postpnr_prerequisites(project, TOP, pdk, "")
    basis = json.loads(basis_path.read_text())
    assert second.status == basis["status"] == "FAIL"
    assert basis["outputs"]["sdc_check"]["status"] == "FAIL"
