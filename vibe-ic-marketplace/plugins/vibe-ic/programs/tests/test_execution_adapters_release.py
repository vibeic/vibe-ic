from __future__ import annotations

import json
import os
from pathlib import Path
import sys

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import execution_policy as policy
from execution_adapters_release import ALL_IDS, EXTERNAL_IDS, SOFTWARE_IDS, UNAVAILABLE_IDS, register_release_adapters, validate
from execution_provider_catalog import RELEASE_IDS, coverage_rows, current_source_identity
import execution_release_worker as release_worker
from execution_release_worker import _call, _canonical_gate_invocations, execute as execute_release
from execution_release_rows import ROWS
from programs.tests import test_execution_receipt_chain as receipt_chain

BASE = current_source_identity()


@pytest.fixture(autouse=True)
def _canonical_issued_transport(monkeypatch):
    """Give production Controller tests the real isolated issuer boundary."""
    monkeypatch.setattr(policy, '_ordinary_runtime', None)
    for name in (policy.ENV, policy._CAPABILITY_FD_ENV,
                 'VIBEIC_EXECUTION_AUTH_SOCKET'):
        # The issuer writes locators directly, including initially absent keys.
        # Record the pre-state before teardown closes the issued descriptor.
        monkeypatch.setenv(name, os.environ.get(name, ''))
        monkeypatch.delenv(name)
    yield
    for proc, fd, channel in receipt_chain._launchers:
        try:
            channel.close()
        except OSError:
            pass
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.terminate()
            proc.wait(timeout=5)
        try:
            os.close(fd)
        except OSError:
            pass
    receipt_chain._launchers.clear()






def _spec(step):
    return next(row for row in coverage_rows() if row["step_id"] == step)


def test_complete_release_coverage_and_no_fake_external_producers():
    assert len(RELEASE_IDS) == 14
    assert set(EXTERNAL_IDS) == {"40", "41", "42", "43", "44"}
    assert len(SOFTWARE_IDS) == 8
    assert set(UNAVAILABLE_IDS) == {"39"}
    assert set(ALL_IDS) == set(RELEASE_IDS)
    registry = register_release_adapters(source_sha=BASE, available=False)
    assert {a.step_id for a in registry._adapters.values()} == set(RELEASE_IDS)
    assert all(a.qualified is False for a in registry._adapters.values())
    assert all(_spec(s)["disposition"] == "external" for s in EXTERNAL_IDS)


def test_release_argv_binds_hardmacro_identity_and_declared_producer():
    registry = register_release_adapters(
        source_sha=BASE, available=False,
        parameters={"pdk_name": "gf180mcuD", "pdk_root": "/pdk",
                    "design_name": "macro_top", "module_role": "hardmacro"})
    adapter = registry.adapters("37.5ip")[0]
    argv = adapter.components[0].argv
    params = json.loads(argv[argv.index("--params-json") + 1])
    assert params["pdk_name"] == "gf180mcuD"
    assert params["pdk_root"] == "/pdk"
    assert params["design_name"] == "macro_top"
    assert params["source_sha"] == BASE
    assert "step_ip_release_docs_gen" in adapter.qualification_evidence


def test_375ip_condition_boundary_uses_route_and_owner_declaration():
    unknown = register_release_adapters(step_ids=('37.5ip',), source_sha=BASE, path="IP")
    assert unknown.adapters("37.5ip")[0].applicability == "unknown"
    die = register_release_adapters(step_ids=('37.5ip',), source_sha=BASE, path="IP", route_receipt={"marker": "slots"},
                                    declaration={"answers": {"deliverable": "DIE"},
                                                 "answer_provenance": {"deliverable": {
                                                     "answered_by": "owner", "citation": "owner fixture"}}})
    assert die.adapters("37.5ip")[0].applicability == "inapplicable"
    ip = register_release_adapters(step_ids=('37.5ip',), source_sha=BASE, path="IP", route_receipt={"marker": "slots"},
                                   declaration={"answers": {"deliverable": "HARDMACRO"}})
    assert ip.adapters("37.5ip")[0].applicability == "applicable"


def test_375ic_and_step39_keep_canonical_condition_semantics():
    ic = register_release_adapters(source_sha=BASE, path="IC", route_receipt={"marker": "SELF_TAPEOUT"},
                                   declaration={"answers": {"deliverable": "DIE"}})
    assert ic.adapters("37.5ic")[0].applicability == "applicable"
    hardmacro = register_release_adapters(source_sha=BASE, path="IC", route_receipt={"marker": "SELF_TAPEOUT"},
                                          declaration={"answers": {"deliverable": "HARDMACRO"}})
    assert hardmacro.adapters("37.5ic")[0].applicability == "inapplicable"
    assert _spec("39")["applicability"]["IP"].startswith("applicable")
    step39 = next(a for a in register_release_adapters(source_sha=BASE)._adapters.values()
                  if a.step_id == "39")
    assert step39.available is False and step39.availability_reason == "FPGA_HARDWARE_ABSENT_NOT_MEASURED"




def test_375ip_worker_calls_declared_hardmacro_producer_and_stays_unmeasured(tmp_path):
    # This is an explicit empty source-bound fixture.  The worker must invoke
    # the declared hardmacro producer and preserve its capability/refusal
    # receipt; it must never manufacture native views from missing EDA inputs.
    inputs = tmp_path / "inputs"
    outputs = tmp_path / "outputs"
    (inputs / "project").mkdir(parents=True)
    (inputs / "project" / "source.txt").write_text("source-bound fixture\n")
    report = execute_release(inputs, outputs, step_id="37.5ip", params={
        "input_contract": ROWS["37.5ip"]["canonical"]["required_inputs"],
        "pdk_name": "gf180mcuD",
        "source_sha": BASE,
        "design_name": "fixture",
        "module_role": "hardmacro",
    })
    producers = {r.get("program") for r in report["producer"]}
    assert "phase3_one_shot_runner._write_ip_release_docs_context" in producers
    assert "digital_hardmacro_gen.run" in producers
    assert report["native_receipts"] == []
    assert report["qualification"] in {"NOT_MEASURED", "FAIL"}


def test_375ip_worker_passes_declared_pdk_name_to_hardmacro_producer(
        tmp_path, monkeypatch):
    import digital_hardmacro_gen as hardmacro
    import phase3_one_shot_runner as runner

    monkeypatch.setattr(
        runner, "step_ip_release_docs_gen",
        lambda *_args, **_kwargs: runner.StepResult(
            "ip_release_docs_gen", "PASS"))
    seen = {}

    def fake_run(project, pdk_root, full_lef, pinonly, container="",
                 cell_lef="", metal_prefix="met", pdk_name=None):
        seen.update(project=project, pdk_root=pdk_root,
                    pdk_name=pdk_name)
        return (hardmacro.RC_REFUSED,
                hardmacro.Record(status="REFUSED",
                                 reason="bounded producer fixture"))

    monkeypatch.setattr(hardmacro, "run", fake_run)
    records = release_worker.produce("37.5ip", tmp_path, {
        "pdk_name": "gf180mcuD",
        "pdk_root": "/mounted/pdks",
    })

    assert seen == {
        "project": tmp_path,
        "pdk_root": "/mounted/pdks",
        "pdk_name": "gf180mcuD",
    }
    produced = next(row for row in records
                    if row.get("program") == "digital_hardmacro_gen.run")
    assert produced["status"] == "REFUSED"


def test_375ip_worker_does_not_invent_missing_pdk_identity(
        tmp_path, monkeypatch):
    import digital_hardmacro_gen as hardmacro
    import phase3_one_shot_runner as runner

    monkeypatch.setattr(
        runner, "step_ip_release_docs_gen",
        lambda *_args, **_kwargs: runner.StepResult(
            "ip_release_docs_gen", "PASS"))
    seen = {}

    def refusing_run(_project, _pdk_root, _full_lef, _pinonly,
                     _container="", _cell_lef="", _metal_prefix="met",
                     pdk_name=None):
        seen["pdk_name"] = pdk_name
        raise hardmacro.PdkBindingRefusal(
            "PDK_NAME_ABSENT",
            "the caller must supply the canonical pdk_name")

    monkeypatch.setattr(hardmacro, "run", refusing_run)
    records = release_worker.produce("37.5ip", tmp_path, {
        "pdk_root": "/mounted/pdks",
    })

    assert seen["pdk_name"] is None
    refused = next(row for row in records
                   if row.get("program") == "digital_hardmacro_gen.run")
    assert refused["verdict"] == "NOT_MEASURED"
    assert "PDK_NAME_ABSENT" in refused["reason"]












def test_release_external_rows_are_visible_classifications_without_runtime_success():
    registry = register_release_adapters(source_sha=BASE, available=False)
    for step in EXTERNAL_IDS:
        adapter = registry.adapters(step)[0]
        assert adapter.role == "complementary"
        assert adapter.available is False
        assert adapter.availability_reason == "EXTERNAL_HANDOFF_ONLY"


def test_canonical_release_gate_argv_preserves_duplicate_and_mode_arguments(tmp_path):
    invocations = _canonical_gate_invocations("14", tmp_path)
    commands = [item["command"] for item in invocations]
    assert commands[:2] == [
        "flow_step_output_content_check . --mode netlist",
        "flow_step_output_content_check . --mode stage_analog",
    ]
    assert commands.count("flow_step_output_content_check . --mode netlist") == 1
    assert "flow_compliance_check . --stage-id stage_analog --strict --json reports/analog/stage_analog_compliance.json" in commands
    assert "tapeout_signoff_check . --mode tapeout --json reports/audit/tapeout_signoff.json" in [
        item["command"] for item in _canonical_gate_invocations("38", tmp_path)]
    assert "digital_hardmacro_check . --json reports/phase3/digital_hardmacro.json" in [
        item["command"] for item in _canonical_gate_invocations("37.5ip", tmp_path)]
    assert "release_docs_check . --arm ip --json reports/phase3/release_docs.json" in [
        item["command"] for item in _canonical_gate_invocations("37.5ip", tmp_path)]
    assert "release_docs_check . --arm ic --json reports/phase3/release_docs_ic.json" in [
        item["command"] for item in _canonical_gate_invocations("37.5ic", tmp_path)]
    assert _canonical_gate_invocations("37.4", tmp_path)[0]["command"] == \
        "signoff_metrics_aggregate . --check"


def test_metrics_gate_fail_is_not_rewritten_as_json_pass(tmp_path, monkeypatch):
    inputs, outputs = tmp_path / "inputs", tmp_path / "outputs"
    inputs.mkdir()
    calls = []
    # The real canonical consumer needs current producer outputs before it
    # invokes its checker. Only the expensive checker process is substituted.
    def producer(step, project, params):
        for name in ROWS[step]["canonical"]["required_outputs"]:
            target = project / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps({"scope": "SOURCE_CONTROL_ONLY"}))
        return [{"program": "neutral_metrics_producer", "rc": 0}]
    monkeypatch.setattr(release_worker, "produce", producer)
    import flow_compliance_check as fcc
    def failing_call(project, command):
        module, args = release_worker._command_argv(command, project)
        calls.append((module, list(args)))
        return fcc._ProgramCheckOutcome(False, "FAIL: neutral measured failure", 1)
    monkeypatch.setattr(fcc, "__check_program_exit_zero", failing_call)
    result = execute_release(inputs, outputs, step_id="37.4", params={"input_contract": []})
    metrics = [args for module, args in calls if module == "signoff_metrics_aggregate"]
    assert metrics == [[str(outputs / "project"), "--check"]]
    assert result["qualification"] == "FAIL"
    assert result["gate_records"][0]["verdict"] == "FAIL"


def test_gate_runner_supports_main_without_argv(tmp_path, monkeypatch):
    module_name = "r2_no_argv_gate"
    (tmp_path / (module_name + ".py")).write_text(
        "import sys\n"
        "def main():\n"
        "    open(sys.argv[1], 'w').write('called')\n"
        "    return 0\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    marker = tmp_path / "called.txt"
    assert _call(module_name, [marker])["rc"] == 0
    assert marker.read_text() == "called"




def test_hardmacro_produced_without_native_receipts_stays_unmeasured(tmp_path):
    binding = {"step_id": "37.5ip"}
    (tmp_path / "release-evidence.json").write_text(json.dumps({
        "binding": binding, "step_id": "37.5ip", "qualification": "PASS",
        "producer_verdict": "PASS", "gate_records": [], "outputs": {},
        "native_receipts": [],
    }))
    assert validate(tmp_path, binding).verdict == "NOT_MEASURED"


def test_release_catalog_binds_current_ip_producer_not_context_helper():
    from execution_provider_catalog import RELEASE_SITES
    assert "phase3_one_shot_runner.py:step_ip_release_docs_gen" in RELEASE_SITES["37.5ip"]
    assert not any("_write_ip_release_docs_context" in site for site in RELEASE_SITES["37.5ip"])


def test_step39_has_structured_exclusion_and_not_measured_status(tmp_path):
    inputs, outputs = tmp_path / "inputs", tmp_path / "outputs"
    inputs.mkdir()
    result = execute_release(inputs, outputs, step_id="39", params={"input_contract": []})
    assert result["qualification"] == "NOT_MEASURED"
    assert result["excluded_from_verdict"] is True
    assert result["producer"][0]["verdict"] == "NOT_MEASURED"
