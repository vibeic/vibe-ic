"""Permanent R5 public-dispatch controls. No product/EDA runner is executed.

Runtime-pair facts and typed D1 outputs are explicit SOFTWARE_FIXTURE_ONLY
preconditions. The actual candidate dispatcher, anchors, receipt history,
invocation journal and admission code execute unmodified.
"""
import copy, hashlib, json, os, sys
from pathlib import Path
from types import SimpleNamespace
import pytest

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).parent)]
import benchmark_dispatch as bd
import route_decision as rd
import task_nature_route as tnr
import test_ai_first_route_handoff as fixture
import _runtime_pair_fixture as runtime
import emit_attestation as ea
import _path_layout as pl
from _hostpaths import require_repo
PRODUCTION_RUN = bd._RunnerBudget.run

@pytest.fixture(autouse=True)
def runtime_precondition(monkeypatch):
    runtime.assume_matching_runtime_pair(monkeypatch)

def record(name, value):
    # Captured by pytest/JUnit, never written into the repository.
    print(json.dumps({"control": name, **value}, sort_keys=True))

def _issue(tmp_path, monkeypatch, prompt="Design a pulse stretcher named top_module with two clock cycles of output.", typed=True):
    dataset, run = tmp_path / "dataset", tmp_path / "run"
    dataset.mkdir()
    (dataset / "opaque_alpha_prompt.txt").write_text(prompt)
    calls = []
    monkeypatch.setattr(bd.subprocess, "run", fixture._typed_d1_runner(calls))
    assert bd.cmd_solve("verilogeval-human", str(dataset), str(run)) == 2
    assert calls == []
    task = bd._read_jsonl(run / bd._ROUTE_WORKLIST)[0]
    answer = fixture._answer(task, "spec_generation")
    answer["prompt_evidence"] = [{"excerpt": prompt, "supports": "The visible INPUT describes spec_generation."}]
    return dataset, run, task, answer, calls

def _resume(dataset, run):
    return bd.cmd_resume("verilogeval-human", str(dataset), str(run))

def _stop_boundary(calls):
    def stop(_budget, argv):
        calls.append(list(argv))
        return bd._ProcessOutcome(rc=1, stdout="", stderr="", error="CONTROLLED_PROCESS_BOUNDARY_STOP")
    return stop

def _ready_backup(tmp_path, monkeypatch, prompt=None):
    kwargs = {"prompt": prompt} if prompt is not None else {}
    dataset, run, task, answer, calls = _issue(tmp_path, monkeypatch, **kwargs)
    fixture._write_answer(task, answer)
    _resume(dataset, run)
    backup = bd._read_jsonl(run / bd._BACKUP_WORKLIST)
    assert len(backup) == 1
    item = backup[0]
    project = Path(task["project"])
    rtl = project / "phase2/stage1/rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "top_module.v").write_text("module top_module(input a, output y); assign y=a; endmodule\n")
    body = {
        "schema": "vibeic.benchmark.ai_backup_record.v1", "id": item["id"],
        "task_sha256": item["task_sha256"], "prompt_sha256": item["prompt_sha256"],
        "source_sha256": item["public_original_input"]["source_sha256"],
        "output_manifest": bd._backup_output_manifest(project),
        "rtl_sha256": bd._sha256_text(bd._candidate_text(bd._rtl_files(project))),
        "author": {"kind": "AI", "model": "software-boundary-control"},
        "oracle_accessed": False, "disposition": "CHANGED",
        "rationale": "The output is derived only from the visible staged input.",
    }
    (project / "phase2/stage1/ai_backup_author.json").write_text(json.dumps(body))
    completion, reasons = bd._validate_backup_completion(item, run)
    assert completion is not None, reasons
    calls.clear()
    monkeypatch.setattr(bd._RunnerBudget, "run", _stop_boundary(calls))
    return dataset, run, task, calls

frozen = SimpleNamespace(issue=_issue, resume=_resume)
prior = SimpleNamespace(ready_backup=_ready_backup)


@pytest.mark.parametrize("prompt,nature", [
    pytest.param(
        "Implement a Verilog module that reproduces the truth table of a small logic chip. "
        "All signals are single bits.\nmodule CoreBlock(input x, output y);\n",
        "spec_generation", id="implement-module"),
    pytest.param(
        "Write a SystemVerilog module that models an integrated circuit.",
        "spec_generation", id="write-module"),
    pytest.param(
        "Complete the following partial RTL module modeling a chip.",
        "completion", id="complete-module"),
    pytest.param(
        "Modify this module to emulate the behavior of a logic chip.",
        "functional_modification", id="modify-module"),
    pytest.param(
        "Fix the bug in this Verilog module that models a die.",
        "debug", id="fix-module"),
    pytest.param(
        "Write RTL that models an integrated circuit.",
        "spec_generation", id="write-rtl"),
    pytest.param(
        "Implement the truth table of a small chip as a Verilog module.",
        "spec_generation", id="implement-as-module"),
    pytest.param(
        "I need a synthesizable module that models a chip.",
        "spec_generation", id="need-module"),
    pytest.param(
        "Implement a Verilog module with this interface.\n"
        "module CoreBlock(input x, output chip);\n",
        "spec_generation", id="ansi-port-chip"),
    pytest.param(
        "Modify this Verilog module to invert its output.\n"
        "module CoreBlock(x, chip);\ninput x;\noutput chip;\n"
        "assign chip = x;\nendmodule\n",
        "functional_modification", id="nonansi-port-chip"),
    pytest.param(
        "The ReferenceUnit device is a chip with several logic gates. "
        "Create a Verilog module with the same functionality as the ReferenceUnit device.\n"
        "module CoreBlock(input a, output y);\n",
        "spec_generation", id="existing-device-functionality"),
    pytest.param(
        "A family of small integrated circuits contains a few gates each. "
        "The ReferencePart is a chip with several gates. "
        "Create a module in Verilog with the same functionality as the ReferencePart chip.",
        "spec_generation", id="existing-chip-functionality"),
    pytest.param(
        "The 93 device is a chip with several OR gates. "
        "Create a module in Verilog with the same functionality as the 93 device. "
        "It has several inputs and two outputs.",
        "spec_generation", id="numeric-device-background"),
    pytest.param(
        "The Q7 device is a chip with AND gates and OR gates. "
        "Create a Verilog module with the same functionality as the Q7 device. "
        "It has several inputs.",
        "spec_generation", id="declarative-input-background"),
])
def test_module_requests_do_not_inherit_described_chip_family(
        tmp_path, monkeypatch, prompt, nature):
    dataset, run, task, answer, calls = frozen.issue(
        tmp_path, monkeypatch, prompt)
    answer["disposition"] = "OVERRIDE"
    answer["ai_nature"] = nature
    answer["prompt_evidence"] = [{
        "excerpt": prompt, "supports": f"The visible input requests {nature}.",
    }]
    answer["semantic_decision"] = {
        "nature": nature, "delivery_target": "rtl",
        "semantic_payload_sha256": task["semantic_payload_sha256"],
    }
    fixture._write_answer(task, answer)
    decision, reasons = bd._validate_ai_route(task, run)
    record("module-delivery", {
        "prompt": prompt, "requirements": task["prompt_delivery_requirements"],
        "decision": decision, "reasons": reasons,
    })
    assert decision is not None, reasons
    assert decision["delivery_route"] == "ip"
    assert decision["delivery_target"] == "rtl"
    assert frozen.resume(dataset, run) == 2
    assert calls
    assert {argv[argv.index("--route") + 1] for argv in calls} == {"ip"}


def test_module_delivery_reentry_consumes_checked_in_flow_registry(
        tmp_path, monkeypatch):
    flow = require_repo("vibe-ic-marketplace", "plugins", "vibe-ic", "flow",
                        "phase1_phase2_phase3.yaml")
    monkeypatch.setattr(tnr, "_FLOW_YAML", flow)
    dataset, run, task, calls = prior.ready_backup(
        tmp_path, monkeypatch,
        prompt="Implement a Verilog module that models a logic chip.")
    assert frozen.resume(dataset, run) == 2
    assert len(calls) == 1
    argv = calls[0]
    exit_step = argv[argv.index("--exit-step") + 1]
    record("module-reentry", {
        "requirements": task["prompt_delivery_requirements"], "argv": argv,
        "flow_sha256": hashlib.sha256(flow.read_bytes()).hexdigest(),
        "flow_steps": tnr.flow_step_ids(flow),
    })
    assert argv[argv.index("--route") + 1] == "ip"
    assert exit_step == "2"
    assert exit_step in tnr.flow_step_ids(flow)
    assert "--skip-phase3" in argv


@pytest.mark.parametrize("prompt,minimum", [
    pytest.param("The Verilog module describes a chip.", None,
                 id="module-description"),
    pytest.param("Design a complete IC. Implement its RTL module.", None,
                 id="explicit-ic"),
    pytest.param("Need a complete chip. Implement its internal RTL module.", None,
                 id="need-complete-chip"),
    pytest.param("Output a complete chip. Include its RTL module.", None,
                 id="output-complete-chip"),
    pytest.param("Write a module for a chip. Deliver a complete chip.", None,
                 id="explicit-chip-after-module"),
    pytest.param("Implement a module for a logic chip and deliver GDSII.", "gds",
                 id="gds"),
    pytest.param("Write the module for a chip for tapeout.", "shippable_gds",
                 id="tapeout"),
    pytest.param("Complete a module for the chip's shuttle run.", None,
                 id="shuttle"),
])
def test_module_words_preserve_physical_delivery_requirements(prompt, minimum):
    requirements = tnr.prompt_delivery_requirements(prompt)
    resolution = tnr.resolve_prompt_delivery_target(requirements, "rtl")
    record("physical-with-module", {
        "prompt": prompt, "requirements": requirements, "resolution": resolution,
    })
    assert requirements["route_family"] == "DIE"
    assert requirements["minimum_target"] == minimum
    assert resolution["ok"] is (minimum is None)


@pytest.mark.parametrize("prompt", [
    "Deliver the final chip. Implement its RTL module.",
    "Implement a chip. Write a Verilog module for its controller.",
    "Build a silicon chip. Write RTL for its controller.",
    "Deliver the final chip and implement its RTL module.",
    "Build a silicon chip with its controller as a Verilog module.",
    "Make a chip. Write its RTL module.",
    "Develop the final IC. Implement its RTL module.",
    "Write RTL and fabricate the chip.",
    "Write a module for a chip and fabricate it.",
    "Implement RTL that models a chip, then manufacture it.",
    "Write a module for a chip. Fabricate it.",
    "Implement RTL that models a chip. Manufacture it.",
    "Write a module for a chip. It must be fabricated.",
    "Implement RTL that models a chip. It shall be manufactured.",
    "Write a module for a chip and its companion. They must be fabricated.",
])
def test_explicit_chip_object_survives_module_request(prompt):
    requirements = tnr.prompt_delivery_requirements(prompt)
    resolution = tnr.resolve_prompt_delivery_target(requirements, "rtl")
    route = tnr.delivery_route_for_target(
        resolution["target"], resolution["route_family"])
    record("chip-object-with-module", {
        "prompt": prompt, "requirements": requirements,
        "resolution": resolution, "route": route,
    })
    assert route == "ic"
    assert requirements["route_family"] == "DIE"
    assert not tnr.resolve_prompt_delivery_target(requirements, "ip_hardmacro")["ok"]


@pytest.mark.parametrize("prompt", [
    pytest.param("Write a module for a chip. You must fabricate it.", id="second-person-obligation"),
    pytest.param("Write a module for a chip. It needs to be fabricated.", id="needs-passive"),
    pytest.param("Write a module for a chip. It is to be fabricated.", id="is-to-passive"),
    pytest.param("Write a module for a chip. We require you to fabricate it.", id="indirect-obligation"),
    pytest.param("Write a module for a chip. Please fabricate this.", id="demonstrative-object"),
    pytest.param("Write a module for a chip. The latter must be fabricated.", id="latter-reference"),
    pytest.param("Write a module for a chip. Fabricate the device.", id="device-fabrication"),
    pytest.param("Implement RTL that models a chip. Manufacture the device.", id="device-manufacturing"),
    pytest.param("Write a module for a chip. Fabrication is required.", id="fabrication-context"),
    pytest.param("Write a module for a chip. Use the specified manufacturing process.", id="manufacturing-context"),
    pytest.param("Write a module for a chip. Send the device to the foundry.", id="foundry-context"),
    pytest.param("Write a module for a chip. Produce the device on a wafer.", id="wafer-context"),
    pytest.param("Write a module for a chip. We will process it using the selected technology.", id="unknown-it-clause"),
    pytest.param("Write a module for a chip. They are the final devices.", id="unknown-they-clause"),
    pytest.param("Write a module for a chip. Our team will deliver them to the package vendor.", id="unknown-them-clause"),
    pytest.param("Write a module for a chip. It has 10 inputs and 2 outputs and is the final deliverable.",
                 id="io-with-extra-obligation"),
])
def test_unresolved_module_reference_preserves_chip_family(prompt):
    requirements = tnr.prompt_delivery_requirements(prompt)
    resolution = tnr.resolve_prompt_delivery_target(requirements, "rtl")
    route = tnr.delivery_route_for_target(
        resolution["target"], resolution["route_family"])
    record("unresolved-module-reference", {
        "prompt": prompt, "requirements": requirements,
        "resolution": resolution, "route": route,
    })
    assert route == "ic"
    assert requirements["route_family"] == "DIE"
    assert not tnr.resolve_prompt_delivery_target(requirements, "ip_hardmacro")["ok"]


@pytest.mark.parametrize("description", [
    "It has 10 inputs and 2 outputs.",
    "It has several inputs and two outputs.",
    "It has several inputs.",
])
def test_pure_io_description_keeps_module_delivery(description):
    prompt = "Write a module for a chip. " + description
    requirements = tnr.prompt_delivery_requirements(prompt)
    resolution = tnr.resolve_prompt_delivery_target(requirements, "rtl")
    record("module-io-description", {
        "prompt": prompt, "requirements": requirements, "resolution": resolution,
    })
    assert requirements["route_family"] is None
    assert resolution["ok"] is True
    assert tnr.delivery_route_for_target(
        resolution["target"], resolution["route_family"]) == "ip"


@pytest.mark.parametrize("description", [
    pytest.param("It has three\ninputs and five outputs.", id="wrapped-input-field"),
    pytest.param("It has three inputs and\nfive outputs.", id="wrapped-output-field"),
])
def test_wrapped_io_description_keeps_module_delivery(description):
    prompt = ("The Q device is a chip with gates. "
              "Create a module with the same functionality as the Q device.\n"
              + description)
    requirements = tnr.prompt_delivery_requirements(prompt)
    resolution = tnr.resolve_prompt_delivery_target(requirements, "rtl")
    record("module-wrapped-io-description", {
        "prompt": prompt, "requirements": requirements, "resolution": resolution,
    })
    assert requirements["route_family"] is None
    assert resolution["ok"] is True
    assert tnr.delivery_route_for_target(
        resolution["target"], resolution["route_family"]) == "ip"


@pytest.mark.parametrize("prompt,minimum", [
    ("Write a module for a chip and deliver GDS.", "gds"),
    ("Write RTL for a chip. Foundry handoff is required.", "foundry_handoff"),
    ("Write RTL for a chip and hand off to the foundry.", "foundry_handoff"),
    ("Write RTL for a chip and produce a GDS.", "gds"),
    ("Write RTL for a chip and generate GDSII.", "gds"),
    ("Write RTL for a chip with shippable GDS.", "shippable_gds"),
])
def test_module_request_cannot_flip_physical_delivery_to_hardmacro(prompt, minimum):
    requirements = tnr.prompt_delivery_requirements(prompt)
    resolution = tnr.resolve_prompt_delivery_target(requirements, "ip_hardmacro")
    record("module-physical-flip", {
        "prompt": prompt, "requirements": requirements, "resolution": resolution,
    })
    assert resolution["ok"] is False
    assert requirements["route_family"] == "DIE"
    assert requirements["minimum_target"] == minimum


@pytest.mark.parametrize("mutate_route", [False, True])
def test_rtl_window_retains_the_issued_die_family_on_backup_reentry(
        tmp_path, monkeypatch, mutate_route):
    # A bounded RTL proof does not change the input's declared IC delivery
    # family. Exercise issuance, D1, backup completion and ordinary resume.
    prompt = ("Design a complete IC with module top_module, input a and "
              "output y wired directly to a. Supply the RTL implementation.")
    dataset, run, task, calls = prior.ready_backup(
        tmp_path, monkeypatch, prompt=prompt)
    solve_path = run / "solve_report.json"
    solve = json.loads(solve_path.read_text())
    row = solve["results"][0]
    assert task["prompt_delivery_requirements"]["route_family"] == "DIE"
    assert row["route_receipt"]["delivery_target"] == "rtl"
    assert row["delivery_route"] == "ic"
    if mutate_route:
        row["delivery_route"] = "ip"
        solve_path.write_text(json.dumps(solve))

    rc = frozen.resume(dataset, run)
    assert rc == 2
    if mutate_route:
        assert calls == []
        current = json.loads(solve_path.read_text())["results"][0]
        assert "ROUTE_REENTRY_ROUTE_MUTATION" in str(current)
    else:
        assert len(calls) == 1
        assert calls[0][calls[0].index("--route") + 1] == "ic"
        assert calls[0][calls[0].index("--exit-step") + 1] == "2"

IC_PROMPTS=[
    'Design a complete chip containing an IP hardmacro and deliver a shippable GDS.',
    'Build a complete IC that incorporates a hardmacro and deliver a GDS.',
    'Deliver a complete chip as GDS.\nComponents: an IP hardmacro and a digital controller.',
    'Integrate an IP hardmacro\ninto a complete chip and deliver a shippable GDS.',
    'Design a complete chip and deliver a shippable GDS. Integrate the vendor-supplied analog subsystem with its calibration controller, reset bridge, synchronization chain and IP hardmacro.',
    'Create a complete chip: (the subsystem contains (an IP hardmacro)). Deliver a shippable GDS.',
]

@pytest.mark.parametrize('prompt', IC_PROMPTS)
def test_complete_chip_words_do_not_authorize_ip_runner(tmp_path,monkeypatch,prompt):
    dataset,run,task,answer,calls=frozen.issue(tmp_path,monkeypatch,prompt,typed=True)
    answer['semantic_decision']={'nature':'spec_generation','delivery_target':'ip_hardmacro',
        'semantic_payload_sha256':task['semantic_payload_sha256']}
    fixture._write_answer(task,answer)
    decision,reasons=bd._validate_ai_route(task,run,benchmark='verilogeval-human',dataset=dataset)
    rc=frozen.resume(dataset,run)
    record('ic-'+task['prompt_sha256'][:12],{'prompt':prompt,'requirements':task['prompt_delivery_requirements'],
        'decision':decision,'reasons':reasons,'rc':rc,'runner_calls':calls})
    assert calls==[], f'complete-chip INPUT authorized IP argv: {calls}'

@pytest.mark.parametrize('prompt',[
    'Deliver a standalone IP hardmacro for use inside a customer chip; include GDS, LEF, Liberty and Verilog views.',
    'Deliver a standalone IP hardmacro to be integrated into a host IC; produce a GDS with LEF and Liberty views.',
    'Deliver a standalone IP hardmacro with GDS, LEF and Liberty views. Its embedded controller handles calibration.',
])
def test_standalone_ip_context_does_not_flip_to_die(prompt):
    req=tnr.prompt_delivery_requirements(prompt)
    resolution=tnr.resolve_prompt_delivery_target(req,'ip_hardmacro')
    record('standalone-'+hashlib.sha256(prompt.encode()).hexdigest()[:12],{'prompt':prompt,'requirements':req,'resolution':resolution})
    assert req['route_family']=='HARDMACRO' and resolution['ok'] is True

@pytest.mark.parametrize('prompt',[
    'Deliver a complete chip and a separate standalone IP hardmacro; produce a GDS and the LEF and Liberty views.',
    'The output is either a complete chip or a standalone IP hardmacro; the owner has not chosen. Deliver a GDS.',
])
def test_ambiguous_physical_object_does_not_authorize_runner(tmp_path,monkeypatch,prompt):
    dataset,run,task,answer,calls=frozen.issue(tmp_path,monkeypatch,prompt,typed=True)
    answer['semantic_decision']={'nature':'spec_generation','delivery_target':'ip_hardmacro',
        'semantic_payload_sha256':task['semantic_payload_sha256']}
    fixture._write_answer(task,answer)
    rc=frozen.resume(dataset,run)
    record('ambiguous-'+task['prompt_sha256'][:12],{'prompt':prompt,'requirements':task['prompt_delivery_requirements'],'rc':rc,'runner_calls':calls})
    assert calls==[]

def state(run,project):
    solve=json.loads((run/'solve_report.json').read_text())
    tasks=bd._read_jsonl(run/bd._ROUTE_WORKLIST)
    return bd._validated_route_reentry_state(bench='verilogeval-human',dataset=None,fmt=None,
        run_p=run,pid=tasks[0]['id'],result=solve['results'][0],route_worklist=tasks,allow_d1_only=False,supplied_rtl=True)

@pytest.mark.parametrize('mutation',[
    'none','entry','exit_deleted','route_deleted','prompt','report_deleted','report_duplicate',
    'ldoc_deleted','input_changed','dataset_changed','activation_rollback','duplicate_exit','duplicate_mode',
    'route_pointer_duplicate','ldoc_and_entry','route_removed_and_ldoc',
])
def test_public_backup_admission_current_and_strict(tmp_path,monkeypatch,mutation):
    dataset,run,task,calls=prior.ready_backup(tmp_path,monkeypatch)
    project=Path(task['project']); solve_path=run/'solve_report.json'
    solve=json.loads(solve_path.read_text()); row=solve['results'][0]
    docs=project/'phase1/generated_docs/L1.json'
    report=pl.report_path(project,'phase1_one_shot.json')
    if mutation=='entry': row['entry']='9'
    if mutation=='exit_deleted': row.pop('exit',None)
    if mutation=='route_deleted': row.pop('delivery_route',None)
    if mutation=='prompt': (project/'input/phase1_prompt.md').write_text('A changed design INPUT.')
    if mutation=='report_deleted': report.unlink()
    if mutation=='report_duplicate':
        raw=report.read_text(); report.write_text(raw.replace('"verdict": "PASS"','"verdict": "FAIL", "verdict": "PASS"'))
    if mutation=='ldoc_deleted': docs.unlink()
    if mutation=='input_changed':
        manifest = project / "input/public_original/manifest.json"
        value = json.loads(manifest.read_text())
        value["source_sha256"] = "f" * 64
        manifest.write_text(json.dumps(value))
    if mutation=='dataset_changed': (dataset/(task['id']+'_prompt.txt')).write_text('A changed external dataset, after immutable staging.')
    if mutation=='activation_rollback':
        pointer=bd._receipt_current_pointer(project,'d1_activation'); saved=pointer.read_bytes()
        activation=bd._read_current_receipt(project,'d1_activation')['receipt']
        bd._publish_current_receipt(project,'d1_activation',activation,digest_field='activation_sha256',run_id='review-repeat-activation')
        pointer.write_bytes(saved)
    if mutation in {'ldoc_and_entry','route_removed_and_ldoc'}:
        row['entry']='2'; docs.unlink()
        if mutation=='route_removed_and_ldoc': bd._receipt_current_pointer(project,'route_decision').unlink()
    solve_path.write_text(json.dumps(solve))
    if mutation=='duplicate_exit':
        raw=solve_path.read_text(); solve_path.write_text(raw.replace('"exit": "2"','"exit": "37.5ic", "exit": "2"',1))
    if mutation=='duplicate_mode':
        raw=solve_path.read_text(); solve_path.write_text(raw.replace('"authority": "PROGRAM_DEFAULT"','"authority": "USER_EXPLICIT_ULTRA", "authority": "PROGRAM_DEFAULT"',1))
    if mutation=='route_pointer_duplicate':
        p=bd._receipt_current_pointer(project,'route_decision'); raw=p.read_text()
        p.write_text(raw.replace('"kind": "route_decision"','"kind": "wrong", "kind": "route_decision"'))
    rc=frozen.resume(dataset,run)
    record('admission-'+mutation,{'rc':rc,'runner_calls':calls,'solve_report':json.loads(solve_path.read_text()),
        'ldoc_exists':docs.exists(),'report_exists':report.exists()})
    if mutation in {'none','exit_deleted','route_deleted','dataset_changed'}:
        assert len(calls)==1 and calls[0][calls[0].index('--exit-step')+1]=='2'
    else: assert calls==[], f'{mutation} passed into runner: {calls}'

@pytest.mark.parametrize('mutation',['none','report_delete','report_fail','ldoc_delete','ldoc_change','input_change'])
def test_downstream_changes_cannot_be_hidden_by_d1_restoration(tmp_path,monkeypatch,mutation):
    dataset,run,task,calls=prior.ready_backup(tmp_path,monkeypatch)
    if os.environ.get('R4_REVERSE')=='restore-disabled':
        monkeypatch.setattr(bd,'_restore_d1_evidence',lambda snapshot:None)
    project=Path(task['project']); docs=project/'phase1/generated_docs/L1.json'
    report=pl.report_path(project,'phase1_one_shot.json')
    before={'report_sha256':hashlib.sha256(report.read_bytes()).hexdigest(),'provenance':ea.phase1_provenance(project)}
    during={}
    def downstream(argv,*args,**kwargs):
        calls.append(list(argv))
        if mutation=='report_delete': report.unlink()
        if mutation=='report_fail':
            payload=json.loads(report.read_text()); payload['verdict']='FAIL'; report.write_text(json.dumps(payload))
        if mutation=='ldoc_delete': docs.unlink()
        if mutation=='ldoc_change': docs.write_text('{"requirement":"different during execution"}\n')
        if mutation=='input_change': (project/'input/phase1_prompt.md').write_text('A different prompt during execution.')
        during.update(report_exists=report.exists(),provenance=ea.phase1_provenance(project))
        if report.exists(): during['report_sha256']=hashlib.sha256(report.read_bytes()).hexdigest()
        return SimpleNamespace(returncode=1,stdout='',stderr='')
    # Keep genuine _RunnerBudget invocation/receipt production and diagnostics.
    monkeypatch.setattr(bd._RunnerBudget,'run',PRODUCTION_RUN)
    monkeypatch.setattr(bd.subprocess,'run',downstream)
    rc=frozen.resume(dataset,run)
    after=state(run,project)
    result=json.loads((run/'solve_report.json').read_text())['results'][0]
    first_calls=copy.deepcopy(calls)
    if mutation not in {'none','input_change'}:
        calls.clear()
        monkeypatch.setattr(bd._RunnerBudget,'run',_stop_boundary(calls))
        subsequent_rc=frozen.resume(dataset,run)
        next_calls=copy.deepcopy(calls)
    else: subsequent_rc,next_calls=None,[]
    record('during-'+mutation,{'rc':rc,'calls':first_calls,'subsequent_rc':subsequent_rc,'subsequent_calls':next_calls,'before':before,'during':during,
        'after_admission':{k:v for k,v in after.items() if k not in {'project','task'}},
        'after_report_sha256':hashlib.sha256(report.read_bytes()).hexdigest() if report.exists() else None,
        'after_provenance':ea.phase1_provenance(project),'result':result,
        'latest_invocation':json.loads((project/'reports/orchestrator/runner_invocations/latest.json').read_text())})
    assert len(first_calls)==1
    if mutation=='none': assert after['status']=='ACTIVE'
    else: assert after['status']=='REFUSED', f'{mutation} was hidden and old activation remains ACTIVE'

@pytest.mark.parametrize('seam',['fanout_route_delete','fanout_report_delete','capture_report_fail'])
def test_admission_is_rechecked_at_actual_runner_boundary(tmp_path,monkeypatch,seam):
    dataset,run,task,calls=prior.ready_backup(tmp_path,monkeypatch)
    project=Path(task['project']); report=pl.report_path(project,'phase1_one_shot.json')
    if seam.startswith('fanout'):
        original=bd._runtime_pair_before_fan_out
        def mutate(plans,*args,**kwargs):
            if plans:
                if seam=='fanout_route_delete': bd._receipt_current_pointer(project,'route_decision').unlink()
                else: report.unlink()
            return original(plans,*args,**kwargs)
        monkeypatch.setattr(bd,'_runtime_pair_before_fan_out',mutate)
    else:
        original=bd._capture_d1_evidence
        def mutate(p):
            payload=json.loads(report.read_text()); payload['verdict']='FAIL'; report.write_text(json.dumps(payload))
            return original(p)
        monkeypatch.setattr(bd,'_capture_d1_evidence',mutate)
    rc=frozen.resume(dataset,run)
    record('seam-'+seam,{'rc':rc,'calls':calls,'result':json.loads((run/'solve_report.json').read_text())['results'][0]})
    assert calls==[]

@pytest.mark.parametrize('operation',['missing_report','missing_route','missing_activation'])
def test_refusal_persists_across_repeated_invocation(tmp_path,monkeypatch,operation):
    dataset,run,task,calls=prior.ready_backup(tmp_path,monkeypatch)
    project=Path(task['project'])
    path=(pl.report_path(project,'phase1_one_shot.json') if operation=='missing_report' else
        bd._receipt_current_pointer(project,'route_decision' if operation=='missing_route' else 'd1_activation'))
    path.unlink()
    returns=[frozen.resume(dataset,run),frozen.resume(dataset,run)]
    record('repeat-'+operation,{'returns':returns,'calls':calls,'missing_path':str(path),'exists':path.exists()})
    assert calls==[] and not path.exists()

@pytest.mark.parametrize('exception',['runtime_error','signal_exit'])
def test_failed_subprocess_cannot_restore_a_deleted_d1_permit(tmp_path,monkeypatch,exception):
    dataset,run,task,calls=prior.ready_backup(tmp_path,monkeypatch)
    project=Path(task['project']); report=pl.report_path(project,'phase1_one_shot.json')
    def failed(argv,*args,**kwargs):
        calls.append(list(argv)); report.unlink()
        if exception=='runtime_error': raise RuntimeError('REVIEW_CONTROLLED_CHILD_FAILURE')
        return SimpleNamespace(returncode=-15,stdout='',stderr='')
    monkeypatch.setattr(bd._RunnerBudget,'run',PRODUCTION_RUN)
    monkeypatch.setattr(bd.subprocess,'run',failed)
    rc=frozen.resume(dataset,run)
    admission=state(run,project)
    result=json.loads((run/'solve_report.json').read_text())['results'][0]
    record('exception-'+exception,{'rc':rc,'calls':calls,'report_exists':report.exists(),
        'admission':{k:v for k,v in admission.items() if k not in {'task','project'}},'result':result})
    assert len(calls)==1
    assert admission['status']=='REFUSED', 'failed child restored old deleted PASS into an ACTIVE launch permit'

@pytest.mark.parametrize('mutation',['target','mode'])
def test_co_mutated_run_root_cannot_replace_admitted_ai_route(tmp_path,monkeypatch,mutation,prompt=None):
    dataset,run,task,calls=_ready_backup(tmp_path,monkeypatch,prompt=prompt)
    project=Path(task['project'])
    external,capability=bd._route_anchor_paths(run)
    original_anchor=external.read_bytes()
    original_response=Path(task['response_path']).read_bytes()
    solve_path=run/'solve_report.json'; solve=json.loads(solve_path.read_text()); row=solve['results'][0]
    original=copy.deepcopy(row['route_receipt'])
    prompt=(project/'input/phase1_prompt.md').read_text()
    receipt=tnr.route_decision_receipt(prompt,nature=original['task_nature'],requested_evidence=original['requested_evidence'],
        delivery_target='ip_hardmacro' if mutation=='target' else original['delivery_target'],
        source_sha256=original['source_sha256'],
        explicit_user_evidence=rd.explicit_ultra_evidence('use ultra mode') if mutation=='mode' else None)
    activation=bd._read_current_receipt(project,'d1_activation')['receipt']
    gate=rd.make_d1_gate(verdict='PASS',route_receipt=receipt,provenance=ea.phase1_provenance(project),
        source_sha256=receipt['source_sha256'],task_sha256=task['task_sha256'],
        ldoc_root_handle=activation['ldoc_root_handle'],invocation_id=activation['d1_gate']['invocation_id'],
        report_sha256=activation['d1_gate']['report_sha256'])
    pending=rd.write_d1_pending(project/'unused',route_receipt=receipt,source_sha256=receipt['source_sha256'],task_sha256=task['task_sha256'])
    replacement=rd.activate_d1(pending=pending,route_receipt=receipt,provenance=ea.phase1_provenance(project),
        source_sha256=receipt['source_sha256'],task_sha256=task['task_sha256'],
        ldoc_root_handle=activation['ldoc_root_handle'],d1_gate=gate)
    # Only run-root files change. No prompt, original AI response, dataset,
    # external owner anchor, capability or product source is rewritten.
    bd._publish_current_receipt(project,'route_decision',receipt,digest_field='receipt_sha256',run_id='review-co-mutation-route')
    bd._publish_current_receipt(project,'d1_pending',pending,digest_field='activation_sha256',run_id='review-co-mutation-pending')
    bd._publish_current_receipt(project,'d1_activation',replacement,digest_field='activation_sha256',run_id='review-co-mutation-activation')
    row.update(route_receipt=receipt,d1_activation=replacement,entry=receipt['entry_step'],exit=receipt['verify_through'],
        delivery_route=tnr.delivery_route_for_target(receipt['delivery_target']))
    solve_path.write_text(json.dumps(solve))
    rc=frozen.resume(dataset,run)
    record('co-mutation-'+mutation,{'rc':rc,'calls':calls,'original_receipt':original,'replacement_receipt':receipt,
        'external_anchor_unchanged':external.read_bytes()==original_anchor,
        'original_ai_response_unchanged':Path(task['response_path']).read_bytes()==original_response,
        'replacement_activation':replacement,'result':json.loads(solve_path.read_text())['results'][0]})
    assert calls==[], f'run-root rewrite replaced admitted AI {mutation} without changing the owner anchor: {calls}'

@pytest.mark.parametrize('prompt,target,route,terminal', [
    (IC_PROMPTS[0], 'shippable_gds', 'ic', '37.5ic'),
    (IC_PROMPTS[2], 'gds', 'ic', '37'),
    ('Deliver a standalone IP hardmacro to be integrated into a host IC; produce GDS, LEF and Liberty views.', 'ip_hardmacro', 'ip', '37.5ip'),
])
def test_compatible_object_enters_its_public_dispatch_span(tmp_path, monkeypatch, prompt, target, route, terminal):
    dataset, run, task, answer, calls = _issue(tmp_path, monkeypatch, prompt)
    answer['semantic_decision'] = {'nature': 'spec_generation', 'delivery_target': target,
                                   'semantic_payload_sha256': task['semantic_payload_sha256']}
    fixture._write_answer(task, answer)
    _resume(dataset, run)
    assert len(calls) == 2
    assert calls[0][calls[0].index('--exit-step') + 1] == 'D1'
    assert calls[1][calls[1].index('--exit-step') + 1] == terminal
    assert all(argv[argv.index('--route') + 1] == route for argv in calls)

@pytest.mark.parametrize('location', ['route_history', 'route_envelope', 'pending_pointer', 'activation_pointer', 'anchor', 'admission', 'config', 'response'])
@pytest.mark.parametrize('raw_kind', ['duplicate', 'overflow'])
def test_each_authority_reader_refuses_ambiguous_json(tmp_path, monkeypatch, location, raw_kind):
    dataset, run, task, calls = _ready_backup(tmp_path, monkeypatch)
    project = Path(task['project'])
    if location == 'route_history': path = bd._receipt_history_head(project, 'route_decision')
    elif location == 'route_envelope': path = bd._read_current_receipt(project, 'route_decision')['path']
    elif location in {'pending_pointer', 'activation_pointer'}:
        path = bd._receipt_current_pointer(project, 'd1_pending' if location == 'pending_pointer' else 'd1_activation')
    elif location == 'anchor': path = bd._route_anchor_paths(run)[0]
    elif location == 'admission': path = bd._route_admission_path(run, task)
    elif location == 'config': path = run / 'solve_report.json'
    else: path = Path(task['response_path'])
    path = Path(path)
    value = json.loads(path.read_text())
    key = next(iter(value))
    raw = path.read_text()
    injected = (json.dumps(key) + ':"shadow",' if raw_kind == 'duplicate' else '"invalid_number":1e999,')
    path.write_text(raw.replace('{', '{' + injected, 1))
    _resume(dataset, run)
    assert calls == []

@pytest.mark.parametrize('mutation', ['restore_old_bytes', 'retype_current_route'])
def test_invalidated_d1_requires_new_typed_invocation(tmp_path, monkeypatch, mutation):
    dataset, run, task, calls = _ready_backup(tmp_path, monkeypatch)
    project = Path(task['project']); report = pl.report_path(project, 'phase1_one_shot.json')
    original_bytes = report.read_bytes()
    old_activation = bd._read_current_receipt(project, 'd1_activation')['receipt']
    def corrupt(argv, *args, **kwargs):
        calls.append(list(argv))
        report.unlink()
        return SimpleNamespace(returncode=-15, stdout='', stderr='')
    monkeypatch.setattr(bd._RunnerBudget, 'run', PRODUCTION_RUN)
    monkeypatch.setattr(bd.subprocess, 'run', corrupt)
    _resume(dataset, run)
    assert len(calls) == 1 and not report.exists()
    report.write_bytes(original_bytes)
    assert state(run, project)['status'] == 'REFUSED'
    if mutation == 'retype_current_route':
        receipt = bd._read_current_receipt(project, 'route_decision')['receipt']
        monkeypatch.setattr(bd.subprocess, 'run', fixture._typed_d1_runner(calls))
        _, _, fresh = bd._activate_route_d1(project, task, receipt,
            Path(bd.__file__).parent / 'vibe_ic_one_shot_runner.py', bd._RunnerBudget(1, 1, 1))
        assert fresh['d1_gate']['invocation_id'] != old_activation['d1_gate']['invocation_id']
        assert state(run, project)['status'] == 'ACTIVE'

@pytest.mark.parametrize('seam', ['capture_replace', 'native_replace', 'native_fail', 'native_route_delete', 'native_response_replace'])
def test_snapshot_generation_is_checked_through_native_submission(tmp_path, monkeypatch, seam):
    dataset, run, task, calls = _ready_backup(tmp_path, monkeypatch)
    project = Path(task['project']); report = pl.report_path(project, 'phase1_one_shot.json')
    touched = []
    def replace():
        if seam == 'native_route_delete':
            bd._receipt_current_pointer(project, 'route_decision').unlink()
            touched.append(1)
            return
        if seam == 'native_response_replace':
            response = Path(task['response_path'])
            value = json.loads(response.read_text())
            value['author']['model'] = 'replacement-model'
            response.write_text(json.dumps(value))
            touched.append(1)
            return
        raw = report.read_bytes()
        if seam == 'native_fail':
            value = json.loads(raw); value['verdict'] = 'FAIL'; raw = json.dumps(value).encode()
        other = report.with_suffix('.replacement'); other.write_bytes(raw); other.replace(report)
        touched.append(1)
    if seam == 'capture_replace':
        original = bd._capture_d1_evidence
        def capture(p):
            snapshot = original(p)
            replace()
            return snapshot
        monkeypatch.setattr(bd, '_capture_d1_evidence', capture)
    else:
        original = bd._runner_material_snapshot
        def material(p):
            value = original(p)
            if getattr(bd._D1_LAUNCH_CONTEXT, 'snapshot', None) is not None and not touched:
                replace()
            return value
        monkeypatch.setattr(bd, '_runner_material_snapshot', material)
    def stop(argv, *args, **kwargs):
        calls.append(list(argv)); return SimpleNamespace(returncode=1, stdout='', stderr='')
    monkeypatch.setattr(bd._RunnerBudget, 'run', PRODUCTION_RUN)
    monkeypatch.setattr(bd.subprocess, 'run', stop)
    _resume(dataset, run)
    assert touched and calls == []


def test_finite_json_numbers_do_not_change_public_route_admission(tmp_path, monkeypatch):
    dataset, run, task, calls = _ready_backup(tmp_path, monkeypatch)
    path = run / 'solve_report.json'
    solve = json.loads(path.read_text())
    solve['measured_seconds'] = 0.125
    solve['bookkeeping_delta'] = -12.5
    path.write_text(json.dumps(solve))
    _resume(dataset, run)
    assert len(calls) == 1
    assert calls[0][calls[0].index('--exit-step') + 1] == '2'


def test_real_input_cannot_acquire_replacement_mode_authority(tmp_path, monkeypatch):
    from _hostpaths import require_repo
    prompt = require_repo(
        'vibe-ic-marketplace', 'plugins', 'vibe-ic', 'programs', 'tests',
        'fixtures', 'real_benchmark', 'directional_bump_fall_moore_prompt.md').read_text()
    assert 'module TopModule' in prompt
    test_co_mutated_run_root_cannot_replace_admitted_ai_route(
        tmp_path, monkeypatch, 'mode', prompt=prompt)


def test_co_mutated_d1_must_come_from_a_fresh_typed_gate(tmp_path, monkeypatch):
    runtime.assume_matching_runtime_pair(monkeypatch)
    dataset, run, task, calls = _ready_backup(tmp_path, monkeypatch)
    project = Path(task['project'])
    receipt = bd._read_current_receipt(project, 'route_decision')['receipt']
    original = bd._read_current_receipt(project, 'd1_activation')['receipt']
    report = pl.report_path(project, 'phase1_one_shot.json')
    value = json.loads(report.read_text())
    value['runner_binding']['invocation_id'] = 'unissued-software-control-d1'
    report.write_text(json.dumps(value))
    gate = rd.make_d1_gate(verdict='PASS', route_receipt=receipt, provenance=ea.phase1_provenance(project),
        source_sha256=receipt['source_sha256'], task_sha256=task['task_sha256'],
        ldoc_root_handle=original['ldoc_root_handle'], invocation_id=value['runner_binding']['invocation_id'],
        report_sha256=hashlib.sha256(report.read_bytes()).hexdigest())
    pending = bd._read_current_receipt(project, 'd1_pending')['receipt']
    replacement = rd.activate_d1(pending=pending, route_receipt=receipt, provenance=ea.phase1_provenance(project),
        source_sha256=receipt['source_sha256'], task_sha256=task['task_sha256'],
        ldoc_root_handle=original['ldoc_root_handle'], d1_gate=gate)
    bd._publish_current_receipt(project, 'd1_activation', replacement,
        digest_field='activation_sha256', run_id='unissued-d1-control')
    _resume(dataset, run)
    print(json.dumps({'calls':calls,'original_activation':original,'replacement_activation':replacement}))
    assert calls == [], f'An unissued replacement D1 gate reached the child boundary: {calls}'


@pytest.mark.parametrize('prompt', [
    'Write a module that models a chip. Deliver the modeled device in a physical package.',
    'Write a module for a chip. Deliver that device in a physical package.',
    'Write a module that models a chip. Ship the modeled device in a physical package.',
    'Write a module that models a chip. Assemble the modeled device in a physical package.',
    'Write a module that models a chip. Place the modeled device in a physical package.',
    'Write a module that models a chip. The modeled device is required in a physical package.',
    'Write a module that models a chip. Physically package the modeled device.',
    'Write a module that models a chip. The modeled device must be physically packaged.',
])
def test_physical_package_delivery_cannot_become_rtl_only(prompt):
    requirements = tnr.prompt_delivery_requirements(prompt)
    rtl = tnr.resolve_prompt_delivery_target(requirements, 'rtl')
    record('physical-package-floor', {'prompt': prompt, 'requirements': requirements, 'rtl': rtl})
    assert rtl['ok'] == False, rtl
    assert requirements['route_family'] == 'DIE'
    resolved = tnr.resolve_prompt_delivery_target(requirements, None)
    assert resolved['ok'] == True
    assert tnr.delivery_route_for_target(resolved['target'], resolved['route_family']) == 'ic'
    assert not tnr.resolve_prompt_delivery_target(requirements, 'ip_hardmacro')['ok']


@pytest.mark.parametrize('obligation', [
    'Deliver the modeled device.',
    'Deliver that device.',
    'The modeled device must be delivered.',
    'Production of the modeled device is required.',
])
def test_independent_delivery_is_not_erased_with_its_reference(obligation):
    prompt = 'Write a module that models a chip. ' + obligation
    requirements = tnr.prompt_delivery_requirements(prompt)
    resolved = tnr.resolve_prompt_delivery_target(requirements, 'rtl')
    assert requirements['route_family'] == 'DIE', requirements
    assert resolved['ok'] == True
    assert tnr.delivery_route_for_target(resolved['target'], resolved['route_family']) == 'ic'


@pytest.mark.parametrize('suffix', [
    'Deliver only RTL source.',
    'Produce a Verilog module.',
])
def test_explicit_rtl_artifact_delivery_is_not_a_physical_obligation(suffix):
    prompt = 'Write a module that models a chip. ' + suffix
    requirements = tnr.prompt_delivery_requirements(prompt)
    resolved = tnr.resolve_prompt_delivery_target(requirements, 'rtl')
    assert tnr.delivery_route_for_target(resolved['target'], resolved['route_family']) == 'ip'


@pytest.mark.parametrize('prompt', [
    'Write a module that models a chip in a physical package.',
    'Write a module that models a chip. The model is not in a physical package.',
    'Write a module that models a chip. Deliver only the RTL module.',
])
def test_physical_package_description_is_not_an_independent_obligation(prompt):
    requirements = tnr.prompt_delivery_requirements(prompt)
    resolved = tnr.resolve_prompt_delivery_target(requirements, 'rtl')
    assert resolved['ok'] == True, resolved
    assert requirements['minimum_target'] is None
    assert tnr.delivery_route_for_target(resolved['target'], resolved['route_family']) == 'ip'


@pytest.mark.parametrize('negative', [
    'No delivery in a physical package is required.',
    'Delivery in a physical package is not required.',
    'There is no requirement for delivery in a physical package.',
    'Do not physically package the modeled device.',
    'The modeled device must not be physically packaged.',
])
def test_denied_package_relation_cannot_invent_a_delivery_floor(negative):
    prompt = 'Write a module that models a chip. ' + negative
    req = tnr.prompt_delivery_requirements(prompt)
    resolved = tnr.resolve_prompt_delivery_target(req, 'rtl')
    assert resolved['ok'] == True, resolved
    assert req['minimum_target'] is None, req


@pytest.mark.parametrize('positive', [
    'Ship the modeled device in a physical package, not the accessory.',
    'Place the modeled device in a physical package with no spare pins.',
])
def test_unrelated_negative_qualifier_cannot_erase_package_obligation(positive):
    prompt = 'Write a module that models a chip. ' + positive
    req = tnr.prompt_delivery_requirements(prompt)
    resolved = tnr.resolve_prompt_delivery_target(req, 'rtl')
    assert resolved['ok'] == False, resolved
    assert req['route_family'] == 'DIE'


def test_denied_relation_does_not_waive_a_separate_affirmative_relation():
    prompt = ('Write a module that models a chip. '
              'No delivery in a physical package is required. '
              'Physically package the modeled device.')
    req = tnr.prompt_delivery_requirements(prompt)
    assert tnr.resolve_prompt_delivery_target(req, 'rtl')['ok'] == False
    assert req['route_family'] == 'DIE'
