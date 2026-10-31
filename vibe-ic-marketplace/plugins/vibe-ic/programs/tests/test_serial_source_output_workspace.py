"""Real producer/source-owner controls; private workspaces grant no row credit."""
import contextlib
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

import pytest

PROGRAMS = Path(os.environ.get("FLOW109_SOURCE_PROGRAMS", Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(PROGRAMS))
import design_one_shot_runner as runner
import serial_parallel_mul_synth as producer


def _files(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file()}


@pytest.fixture
def source():
    name = os.environ.get("FLOW109_SOURCE_OWNER_PROJECT")
    reference = os.environ.get("FLOW109_SOURCE_OWNER_REFERENCE")
    if not name or not reference:
        pytest.skip("exact normal D01 reference and disposable canonical namespace required")
    project = Path(name)
    for child in project.iterdir():
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink()
    shutil.copytree(reference, project, dirs_exist_ok=True)
    return project


def _stage(source, tmp_path):
    target = tmp_path / "private-output"
    shutil.copytree(source, target)
    return target


@contextlib.contextmanager
def _held_source_and_output(source, stage):
    held_source = runner._Phase1ProjectBinding.open(source)
    held_stage = runner._Phase1ProjectBinding.open(stage)
    held_stage.isolated_rtl_stage = True
    # This is the real parent transaction's upstream FD handoff. The base
    # ignores it and reaches its ordinary foreign-project refusal, not an API error.
    held_stage.rtl_source_binding = held_source
    names = ("_PHASE1_ACTIVE_PROJECT_BINDING", "_RTL_SESSION_BINDING",
             "_RTL_SESSION_OWNED", "_RTL_SESSION_PROJECT")
    old = {name: getattr(runner, name) for name in names}
    runner._PHASE1_ACTIVE_PROJECT_BINDING = held_stage
    runner._RTL_SESSION_BINDING = None
    runner._RTL_SESSION_OWNED = False
    runner._RTL_SESSION_PROJECT = None
    try:
        yield
    finally:
        session = runner._RTL_SESSION_BINDING
        if session is not None and session is not held_stage and session is not held_source:
            session.close()
        for name, value in old.items():
            setattr(runner, name, value)
        held_stage.close()
        held_source.close()


def test_actual_source_and_private_stage_dispatch_succeeds_without_authority_transfer(source, tmp_path):
    import fault_scan_chain_insert as scan

    binding, problems = scan.load_d09_dft_contract(source)
    assert binding is not None and not problems, problems
    stage = _stage(source, tmp_path)
    before = _files(source)
    with _held_source_and_output(source, stage):
        result = runner._try_serial_parallel_mul_rtl(
            stage, "digital_arithmetic_primitive", time.time())
    assert result is not None and result.status == "PASS", result
    assert result.extras["source_project"] == str(source)
    assert result.extras["source_D01_admission"]["current"] is True
    for rel in ("phase2/stage1/rtl/spm.v", "plugin_output/declaration.json"):
        assert (stage / rel).read_bytes() == (source / rel).read_bytes()
    assert _files(source) == before
    refused, why = scan.load_d09_dft_contract(stage)
    assert refused is None and "D01 project or route differs" in str(why), why
    owner = json.loads((stage / "reports/orchestrator/phase1_one_shot.json").read_text())
    assert owner["project"] == str(source)


def test_default_actual_source_refresh_preserves_all_source_bytes(source):
    before = _files(source)
    result = subprocess.run([sys.executable, str(PROGRAMS / "serial_parallel_mul_synth.py"),
                             str(source), "--refresh-contract"], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert _files(source) == before


def test_compiler_output_carries_no_new_canonical_d01(source, tmp_path):
    import fault_scan_chain_insert as scan

    output = tmp_path / "artifacts"
    before = _files(source)
    result = subprocess.run([sys.executable, str(PROGRAMS / "serial_parallel_mul_synth.py"),
                             str(source), "--output-project", str(output), "--emit"],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    record = json.loads(result.stdout.strip().splitlines()[-1])
    assert record["source_project"] == str(source)
    assert record["source_D01_admission"]["current"] is True
    assert (output / "phase2/stage1/rtl/spm.v").read_bytes() == (
        source / "phase2/stage1/rtl/spm.v").read_bytes()
    assert (output / "plugin_output/declaration.json").read_bytes() == (
        source / "plugin_output/declaration.json").read_bytes()
    assert not (output / "reports/orchestrator/phase1_one_shot.json").exists()
    refused, why = scan.load_d09_dft_contract(output)
    assert refused is None and why
    assert _files(source) == before


@pytest.mark.parametrize("mutation", ("missing", "tampered_receipt", "stale_actual_subject", "nonpass"))
def test_distinct_output_requires_current_source_d01_before_publication(source, tmp_path, mutation):
    import ai_signed_judgement as judgement
    import fault_scan_chain_insert as scan

    receipt = source / "reports/audit/ai_judgements/D1.json"
    assert judgement.check(source, "D1")[0]
    if mutation == "missing":
        receipt.unlink()
    elif mutation == "stale_actual_subject":
        path = source / "phase1/generated_docs/L9_INTEGRATION_SPEC.json"
        path.write_bytes(path.read_bytes() + b"\n")
    else:
        data = json.loads(receipt.read_text())
        data["evidence_sha256" if mutation == "tampered_receipt" else "verdict"] = (
            "0" * 64 if mutation == "tampered_receipt" else "FAIL")
        receipt.write_text(json.dumps(data))
    # Retained declaration publication/owner is still admissible: the new
    # signed-current source check must supply this refusal, not an earlier gate.
    binding, problems = scan.load_d09_dft_contract(source)
    assert binding is not None and not problems, problems
    assert judgement.check(source, "D1")[0] is False
    before = _files(source)
    output = tmp_path / "unpublished"
    result = subprocess.run([sys.executable, str(PROGRAMS / "serial_parallel_mul_synth.py"),
                             str(source), "--output-project", str(output), "--emit"],
                            capture_output=True, text=True)
    (tmp_path / "refusal.stdout").write_text(result.stdout)
    (tmp_path / "refusal.stderr").write_text(result.stderr)
    assert result.returncode == 2, result.stdout + result.stderr
    assert "source D01 signed judgement is not current" in result.stdout
    assert not output.exists()
    assert _files(source) == before


@pytest.mark.parametrize("mutation", ("missing", "foreign", "route", "publication", "input"))
def test_default_source_owner_guards_stay_strict(source, mutation):
    report = source / "reports/orchestrator/phase1_one_shot.json"
    if mutation == "missing":
        report.unlink()
    elif mutation in ("foreign", "route"):
        data = json.loads(report.read_text())
        data["project" if mutation == "foreign" else "deliverable"] = (
            str(source / "foreign") if mutation == "foreign" else "hardmacro")
        report.write_text(json.dumps(data))
    elif mutation == "publication":
        path = source / "plugin_output/declaration.json"
        path.write_text(json.dumps(json.loads(path.read_text()), separators=(",", ":")))
    else:
        path = source / "input/docs/L7_verification_plan.md"
        path.write_bytes(path.read_bytes() + b"\n")
    result = subprocess.run([sys.executable, str(PROGRAMS / "serial_parallel_mul_synth.py"),
                             str(source), "--refresh-contract"], capture_output=True, text=True)
    assert result.returncode == 2, result.stdout + result.stderr
    assert "D09_DFT_AUTHORITY_INVALID" in result.stdout


@pytest.mark.parametrize("mutation", ("declaration", "report", "inputs", "sidecar", "route"))
def test_private_output_mismatches_refuse_without_touching_source(source, tmp_path, mutation):
    stage = _stage(source, tmp_path)
    before = _files(source)
    if mutation == "declaration":
        path = stage / "plugin_output/declaration.json"
        data = json.loads(path.read_text()); data["bit_order"] = "conflicting-choice"
        path.write_text(json.dumps(data))
    elif mutation == "report":
        path = stage / "reports/orchestrator/phase1_one_shot.json"
        data = json.loads(path.read_text()); data["project"] = str(stage)
        path.write_text(json.dumps(data))
    elif mutation == "inputs":
        path = stage / "phase1/generated_docs/L9_INTEGRATION_SPEC.json"
        path.write_bytes(path.read_bytes() + b"\n")
    elif mutation == "sidecar":
        path = stage / "plugin_output/declaration.provenance.json"
        path.write_bytes(path.read_bytes() + b"\n")
    else:
        path = stage / "input/step_0_5ic_answers.json"
        data = json.loads(path.read_text()); data["answers"]["deliverable"] = "hardmacro"
        path.write_text(json.dumps(data))
    target_before = _files(stage)
    result = subprocess.run([sys.executable, str(PROGRAMS / "serial_parallel_mul_synth.py"),
                             str(source), "--output-project", str(stage), "--refresh-contract"],
                            capture_output=True, text=True)
    assert result.returncode != 0, result.stdout + result.stderr
    expected = {
        "declaration": ("output declaration differs from the source author",),
        "report": ("output workspace has a different D01 owner",),
        "inputs": ("output workspace inputs differ from the source",),
        "sidecar": ("output authority evidence differs from the source",),
        "route": ("output workspace route differs from the source",
                  "output workspace inputs differ from the source"),
    }
    assert any(reason in result.stdout for reason in expected[mutation]), (
        result.stdout + result.stderr)
    assert _files(source) == before
    assert _files(stage) == target_before


def test_conflicting_retained_output_still_refuses(source, tmp_path):
    stage = _stage(source, tmp_path)
    # This negative models an unpublished conflicting output. A retained
    # reference may carry its source ledger; remove only that TEST_ONLY copy
    # so the original assertion still proves no new provenance is minted.
    (stage / 'phase2/stage1/rtl.provenance.json').unlink(missing_ok=True)
    rtl = stage / "phase2/stage1/rtl/spm.v"
    rtl.write_bytes(rtl.read_bytes() + b"\n// independently changed output\n")
    before = _files(source)
    with _held_source_and_output(source, stage):
        result = runner._try_serial_parallel_mul_rtl(
            stage, "digital_arithmetic_primitive", time.time())
    assert result is None or result.status == "FAIL", result
    assert not (stage / "phase2/stage1/rtl.provenance.json").exists()
    assert _files(source) == before


def _basic_source(tmp_path):
    sys.path.insert(0, str(PROGRAMS / "tests"))
    from test_serial_parallel_mul_synth import _mk_project, _SPM_PORTS
    source = _mk_project(tmp_path, ports=_SPM_PORTS, top="neutral_serial",
                         l2_text="serial-parallel multiplier: p = (x * y) mod 2^N")
    assert producer.main([str(source), "--emit"]) == 0
    return source


def test_source_content_change_after_stage_capture_refuses(tmp_path):
    source = _basic_source(tmp_path)
    stage = _stage(source, tmp_path)
    with _held_source_and_output(source, stage):
        path = source / "phase1/generated_docs/L9_INTEGRATION_SPEC.json"
        path.write_bytes(path.read_bytes() + b"\n")
        result = runner._try_serial_parallel_mul_rtl(
            stage, "digital_arithmetic_primitive", time.time())
    assert result is None or result.status == "FAIL", result
    assert not (stage / "phase2/stage1/rtl.provenance.json").exists()


def test_source_inode_replacement_after_compiler_refuses(tmp_path, monkeypatch):
    source = _basic_source(tmp_path)
    stage = _stage(source, tmp_path)
    original_run = runner._pr.run
    changed = []

    def replace_after_actual_compiler(command, **kwargs):
        result = original_run(command, **kwargs)
        if len(command) > 1 and Path(command[1]).name == "serial_parallel_mul_synth.py":
            source.rename(source.with_name(source.name + "-retired"))
            source.mkdir(); (source / "foreign-sentinel").write_text("untouched")
            changed.append(True)
        return result

    monkeypatch.setattr(runner._pr, "run", replace_after_actual_compiler)
    with _held_source_and_output(source, stage):
        result = runner._try_serial_parallel_mul_rtl(
            stage, "digital_arithmetic_primitive", time.time())
    assert changed
    assert result is not None and result.status == "FAIL", result
    assert set(_files(source)) == {"foreign-sentinel"}
    assert not (stage / "phase2/stage1/rtl.provenance.json").exists()


def test_legacy_non_scan_owner_is_not_republished(source, tmp_path):
    import fault_scan_chain_insert as scan
    import spec_declaration_emit as declaration
    contract, _, _ = declaration.select_contract(source)
    assert contract and not any(f['name'] == 'dft' for f in contract['fields'])
    binding, problems = scan.load_d09_dft_contract(source)
    assert binding and not problems and binding['intent']['requires_scan'] is False
    before = _files(source)
    direct = runner.declaration_before_step4(source)
    assert direct.get('producer') == 'D01' and direct.get('emitted') is True, direct
    assert _files(source) == before
    stage = _stage(source, tmp_path)
    staged_before = _files(stage)
    with _held_source_and_output(source, stage):
        private = runner.declaration_before_step4(stage)
    assert private.get('producer') == 'D01' and private.get('emitted') is True, private
    assert _files(source) == before and _files(stage) == staged_before
    assert scan.load_d09_dft_contract(source)[0] == binding
    # A copied report is not a new owner for the private project namespace.
    assert scan.load_d09_dft_contract(stage)[0] is None


@pytest.mark.parametrize('damage', ['missing_reason', 'decision_drift', 'owner_drift',
                                   'private_decision', 'private_declaration'])
def test_legacy_non_scan_owner_refusal_cannot_fall_back_to_writer(source, tmp_path, damage):
    if damage in ('missing_reason', 'decision_drift'):
        path = source / 'input/feature-decisions.json'
        body = json.loads(path.read_text())
        if damage == 'missing_reason':
            body['dft'].pop('reason')
        else:
            body['dft']['reason'] = 'changed unadopted decision'
        path.write_text(json.dumps(body))
    elif damage == 'owner_drift':
        path = source / 'reports/orchestrator/phase1_one_shot.json'
        body = json.loads(path.read_text()); body['dft_intent_output']['producer'] = 'not_D01'
        path.write_text(json.dumps(body))
    stage = _stage(source, tmp_path)
    if damage == 'private_decision':
        path = stage / 'input/feature-decisions.json'; path.write_text(path.read_text() + '\n')
    elif damage == 'private_declaration':
        path = stage / 'plugin_output/declaration.json'; path.write_text(path.read_text() + '\n')
    before, staged_before = _files(source), _files(stage)
    with _held_source_and_output(source, stage):
        result = runner.declaration_before_step4(stage)
    assert result.get('emitted') is False, result
    assert result.get('producer') == 'D01', result
    assert _files(source) == before and _files(stage) == staged_before


def test_legacy_non_scan_normal_proof_survives_finalization(source):
    from dataclasses import asdict
    import flow109_metric_acceptance as metrics
    before = _files(source)
    result = runner.step_rtl_gen(source, 'digital_arithmetic_primitive')
    assert result.status == 'PASS', result
    assert result.extras['declaration_before_simulation']['producer'] == 'D01'
    assert result.extras['declaration_before_simulation']['emitted'] is True
    assert result.extras['current_source_reuse'] == 'NORMAL_PROOF_PUBLISHED'
    try:
        output = runner._pl.report_path(source, 'phase2_one_shot.json')
        runner._write_phase2_report(output, {'project': str(source), 'verdict': 'PASS',
            'steps': [asdict(result)], 'declared_window': {'entry_step': '1', 'exit_step': '1',
            'dispatched_step_ids': ['1']}}, source)
        runner._finalize_rtl_provenance()
        runner._RTL_SESSION_OWNED = False
        runner._RTL_SESSION_PROJECT = None
        author = json.loads(output.read_text())['steps'][0]
        accepted = metrics.d09_owned_metrics(source, author)
        assert accepted['rtl_requirement_mapping'] == 'PASS'
        assert accepted['declared_ports_parameters'] == 'PASS'
        assert len(accepted['source_demands']) == 137
        for rel in ['plugin_output/declaration.json', 'plugin_output/declaration.provenance.json',
                    'provenance.jsonl', 'reports/orchestrator/phase1_one_shot.json',
                    'phase2/stage1/rtl/spm.v']:
            assert _files(source)[rel] == before[rel], rel
        assert not (source / 'reports/flow109/default_rows').exists()
    finally:
        runner._finalize_rtl_provenance()
        runner._RTL_SESSION_OWNED = False
        runner._RTL_SESSION_PROJECT = None



def test_normal_authored_input_republication_recovers_the_original_owner(source):
    import fault_scan_chain_insert as scan
    before_fields = (source / 'plugin_output/declaration.json').read_bytes()
    before_owner = (source / 'reports/orchestrator/phase1_one_shot.json').read_bytes()
    producer = PROGRAMS / 'spec_declaration_emit.py'
    # Reproduce the prior normal generic publication: the carried dft value
    # survives but its required author input is omitted from the latest claim.
    generic = subprocess.run([sys.executable, str(producer), str(source),
        '--supplied-top', 'spm'], capture_output=True, text=True)
    assert generic.returncode == 0, generic.stdout + generic.stderr
    assert scan.load_d09_dft_contract(source)[0] is None
    recovered = subprocess.run([sys.executable, str(producer), str(source),
        '--from-json', str(source / 'input/feature-decisions.json')], capture_output=True, text=True)
    assert recovered.returncode == 0, recovered.stdout + recovered.stderr
    binding, problems = scan.load_d09_dft_contract(source)
    assert binding and not problems and binding['intent']['requires_scan'] is False
    assert (source / 'plugin_output/declaration.json').read_bytes() == before_fields
    assert (source / 'reports/orchestrator/phase1_one_shot.json').read_bytes() == before_owner
    before = _files(source)
    assert runner.declaration_before_step4(source)['producer'] == 'D01'
    assert _files(source) == before
