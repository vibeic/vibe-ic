"""The front door's roll-up, at its edges — through main() and through the guard.

R-0915-145. The conjunction rule itself stands (a FAILING completion audit over
passing phases is a FAIL). These are the four edges a pre-landing review confirmed,
each driven through the entry point rather than through a re-implementation.

H1  #505's DEMOTED ROW. The standalone shape (`--skip-phase3`, a phase1 failure
    that is purely doc-extraction coverage) demotes phase1 to COVERAGE-INCOMPLETE
    and KEEPS its rc, because a coverage-only phase1 always exits 1 -- the rc
    belongs to the verdict the row had BEFORE the demotion. The roll-up's "claims
    a pass but exited non-zero" rule is right for an UNDEMOTED row and turned this
    shape into FAIL/exit 1, where the base published PASS_WITH_WAIVERS/exit 0.
    The demotion now records itself, and only the #505 branch may mint the token.

M2  THE AUDIT AXIS MUST NOT FAIL OPEN. `if ca == "FAIL"` meant NOT_MEASURED, an
    unparseable value and an ABSENT audit all read as satisfied -- so a phase3 run
    whose --strict completion refresh raised inside a swallowed try published PASS
    at exit 0. Only PASS satisfies the axis now; waivers cap at the waiver tier;
    anything else, absence included, is NOT_MEASURED with the reason stated.

M3  AND IT MUST BE THIS RUN'S AUDIT. The reader took
    `reports/orchestrator/phase3_one_shot.json` unconditionally, so a leftover FAIL
    from an earlier full run gated a later `--skip-phase3` invocation that never
    touched phase3. A document counts only when phase3 ran in THIS invocation and
    the document was written at or after it started; an older one is named as
    ignored, not used.

L4  ONE IMPLEMENTATION. `vibe_ic_entry_guard` re-derived the verdict with its own
    copy of the old rule and its verdict set had no NOT_MEASURED, so a GENUINE
    report was discarded as forged and `benchmark_dispatch --score` could refuse a
    real run. The guard now replays the runner's own roll-up.
"""
from __future__ import annotations

import json
import time
import os
import sys
import tempfile
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[2]
PROGRAMS = PLUGIN / "programs"
sys.path.insert(0, str(PROGRAMS))

import _path_layout as _pl                                   # noqa: E402
import vibe_ic_entry_guard as GUARD                          # noqa: E402
import vibe_ic_one_shot_runner as V
import _audit_scope                          # noqa: E402
from _route_fixture import stage_owner_route  # noqa: E402
from programs.tests.test_execution_receipt_chain import real_entry, isolated_transport


@pytest.fixture()
def project(tmp_path_factory):
    p = Path(tempfile.mkdtemp(prefix="fdedge_",
                              dir=str(tmp_path_factory.mktemp("fd"))))
    rtl = p / "phase2/stage1/rtl"
    rtl.mkdir(parents=True)
    (rtl / "d.v").write_text("module d(); endmodule\n")
    # owner route rule 2026-09-28 (ICROUTE)
    stage_owner_route(p, "ic")
    return p


#: WHERE EACH PRODUCER REALLY WRITES -- and now that is ONE RULE, which is the point.
#:
#: Round 3 measured three locations and taught the fixtures all three:
#:     reports/phase1_one_shot.json                 <- phase1's runner, NOT routed
#:     reports/orchestrator/phase2_one_shot.json
#:     reports/orchestrator/phase3_one_shot.json
#: and I made the READER learn them too. That was the wrong half to change. `_path_layout`
#: categorises all three `*_one_shot.json` files as `orchestrator`, and the repo says the
#: flat location is not sanctioned, twice, without being asked:
#:   * `reports_subfolder_taxonomy_check` FAILS on it -- measured against a staged layout:
#:     `[FAIL] ... 1 stray file(s): phase1_one_shot.json`;
#:   * `vibe_ic_entry_guard` documents `reports/orchestrator/phase1_one_shot.json` as the
#:     standalone runner's location and calls the flat one "legacy".
#: So the PRODUCER moved onto the router, and both sides now resolve through one call.
#: These fixtures therefore write through the router too -- not because it is convenient,
#: but because a real `phase1_one_shot_runner` invocation was measured landing there, which
#: `test_phase1s_producer_resolves_its_report_through_the_router` pins against the source.
#:
#: The coverage-only sidecar is NOT in that set and is not routed at all: it is declared
#: literally, as `_path_layout.COVERAGE_ONLY_SIDECAR_REL`, and staged through
#: `coverage_only_sidecar_path` like everything else that touches it.
#:
#: CORRECTING WHAT THIS NOTE USED TO SAY. It claimed three locations -- "its producer writes
#: `reports/`, `_phase1_failure_is_coverage_only` reads `reports/phase1/`, and the router's
#: catch-all would say `reports/audit/`". Measured: the producer writes `reports/phase1/`, the
#: same place the reader reads, so there were never three LOCATIONS -- there were FIVE
#: hand-written COPIES of one location, across three programs, which is a different defect and
#: the one next/icslot-sidecarpath closed. The router's catch-all really would say
#: `reports/audit/`, and that remains a live mismatch: moving the file there is a producer move
#: needing a read-side tolerance for the old place, and it is not done.


def _report(project: Path, name: str, payload: dict) -> Path:
    path = _pl.report_path(project, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload) + "\n")
    return path


def _drive_main(project: Path, monkeypatch, *, phase1, phase2, phase3=None,
                extra_argv=(), after_phase=None, reuse_phase1=False) -> tuple:
    """Run the REAL main() with the phase subprocesses stubbed.

    Only `_run_phase` and the phase-1 entry decision are staged; every line of the
    roll-up, the axis reader and the report writer is the shipped one.
    """
    def fake_run_phase(label, runner, args, env=None):
        if "phase1" in runner.name:
            _report(project, "phase1_one_shot.json", {"verdict": phase1[0]})
            if after_phase:
                after_phase("phase1")
            if phase1[2] is not None:
                # THE SIDECAR'S OWN PATH AND KEY. The path is now ONE declaration
                # (`_path_layout.coverage_only_sidecar_path`) that the producer, both
                # readers and this fixture all ask, so a fixture can no longer drift
                # from the code by staging the old place; the LITERAL is pinned once,
                # in `test_a_pass_one_written_before_the_move_is_still_carried`, which
                # is what still catches a silent relocation. The KEY is read from the
                # consumer: `_phase1_failure_is_coverage_only` asks for
                # `coverage_only_failure`, and any other key stages a fixture the
                # demotion branch cannot see.
                side = _pl.coverage_only_sidecar_path(project)
                side.parent.mkdir(parents=True, exist_ok=True)
                side.write_text(json.dumps(phase1[2]) + "\n")
            return phase1[1]
        if "phase2" in runner.name:
            _report(project, "phase2_one_shot.json", {"verdict": phase2[0]})
            if after_phase:
                after_phase("phase2")
            return phase2[1]
        if "phase3" in runner.name and phase3 is not None:
            _report(project, "phase3_one_shot.json", phase3[0])
            return phase3[1]
        return 0

    monkeypatch.setattr(V, "_run_phase", fake_run_phase)
    if reuse_phase1 is not None:
        monkeypatch.setattr(V, "_phase1_decision", lambda *a, **k:
                            (False, "") if reuse_phase1 else (True, "docs"))
    monkeypatch.setattr(sys, "argv",
                        ["vibe_ic_one_shot_runner", str(project),
                         "--no-dashboard", "--skip-hardware", *extra_argv])
    real_entry('IC', 'default', project)
    rc = V.main()
    out = _pl.report_path(project, "vibe_ic_one_shot.json")
    return rc, json.loads(out.read_text())


def _checkpoint_contract(project, monkeypatch, doc='L1.json'):
    """A neutral D1 contract through the real FCC, not a substitute verdict."""
    import copy
    import _flow_yaml
    import step_write_ledger
    import yaml
    load = _flow_yaml.load
    flow = copy.deepcopy(load())
    row = next(r for r in flow['steps'] if str(r['id']) == 'D1')
    row['required_inputs'] = [{'from': 'external', 'path': 'input/docs/*'}]
    output = 'phase1/generated_docs/' + doc
    row['required_outputs'] = [output]
    row['program_outputs'] = []
    row['gate'] = {'files_exist': [output,
                                  'reports/phase1/mechanical-ready.json']}
    # Both real readers must observe this same contract: the write ledger
    # independently reads its YAML path instead of using _flow_yaml.load.
    fixture_flow = project.parent / (project.name + '-checkpoint-flow.yaml')
    fixture_flow.write_text(yaml.safe_dump(flow, sort_keys=False))
    monkeypatch.setattr(_flow_yaml, 'load', lambda *a, **k: load(fixture_flow))
    monkeypatch.setattr(step_write_ledger, '_flow_yaml_path', lambda: fixture_flow)
    ready = project / 'reports/phase1/mechanical-ready.json'
    ready.parent.mkdir(parents=True, exist_ok=True)
    ready.write_text('{"scope":"SOURCE_CONTROL mechanical input"}\n')
    return ready


@pytest.mark.parametrize("review", ["PASS", "FAIL", "stale", "missing"])
def test_reused_phase1_consumes_current_expert_review_before_phase2(
        project, monkeypatch, review):
    import ai_signed_judgement as ai
    docs = project / "phase1/generated_docs"
    docs.mkdir(parents=True)
    for index in range(1, 14):
        (docs / f"L{index}.json").write_text("{}\n")
    design_input = project / "input/docs/spec.md"
    design_input.parent.mkdir(parents=True, exist_ok=True)
    design_input.write_text("A small digital counter.\n")
    assert V._design_input_present(project) is True
    producer = _report(project, "phase1_one_shot.json", {"verdict": "PASS"})
    _checkpoint_contract(project, monkeypatch)
    # This existing review-only unit stages freshness explicitly. The actual
    # producer/source identity is exercised below with the existing recorder.
    (project / 'phase1/step_identity.json').write_text(
        '{"scope":"SOURCE_CONTROL explicitly staged freshness"}\n')
    monkeypatch.setattr(V, "_phase1_freshness", lambda *a, **k: {
        "state": V._p1id.REUSE, "reason": "CURRENT", "why": "current producer"})
    if review != "missing":
        receipt = project / "reports/audit/ai_judgements/D1.json"
        receipt.parent.mkdir(parents=True, exist_ok=True)
        receipt.write_text(json.dumps({
            "schema": ai.SCHEMA, "step_id": "D1", "signed_by": "expert",
            "judgement": "Reviewed the current document handoff.",
            "verdict": "FAIL" if review == "FAIL" else "PASS",
            "evidence_sha256": ("0" * 64 if review == "stale" else
                                ai.evidence_sha256(project, "D1"))}))
    retained = {p: p.read_bytes() for p in [*docs.glob("*.json"), producer]}
    called = []
    rc, doc = _drive_main(
        project, monkeypatch, phase1=("PASS", 0, None), phase2=("PASS", 0),
        reuse_phase1=True, extra_argv=("--skip-phase3", "--skip-analog"),
        after_phase=called.append)
    if review == "PASS":
        assert called == ["phase2"], doc
        import step_output_collector as versions
        accepted = versions.latest_pass(project, 'D1')
        assert accepted is not None, 'a signed resume must retain complete canonical acceptance'
        assert accepted['current_inputs'] is True
        assert doc['phase1_checkpoint_review']['canonical_acceptance']['verdict'] == 'PASS'
    else:
        assert called == [], doc
        assert rc == 1 and doc["halted_at"] == "phase1", doc
        expected = "FAIL" if review == "FAIL" else "NOT_MEASURED"
        assert doc["phases"][0] == {
            "name": "phase1", "verdict": expected, "rc": 0}, doc
        assert doc["phase1_checkpoint_review"]["producer_reused"] is True
    assert {p: p.read_bytes() for p in retained} == retained


def _recorded_d1_checkpoint(tmp_path, monkeypatch):
    """Run the existing neutral software producer under its real identity recorder."""
    import execution_backend_gates as gates
    import execution_backend_worker as worker
    import step_output_collector as versions
    import _flow_yaml
    from programs.tests.test_fx_stale_ldocs_generated_docs_are_reused_only_when_current import (
        _plugin, _project, _phase1)
    plugin, project = _plugin(tmp_path), _project(tmp_path)
    stage_owner_route(project, 'ic')
    ready = _checkpoint_contract(project, monkeypatch, 'L1_DOC.json')
    knobs = {'ic_name': 'UNNAMED_CHIP', 'pdk': 'auto', 'mode': 'docs'}
    monkeypatch.setattr(V, '_phase1_freshness', lambda p, k=None:
                        V._p1id.assess(p, plugin / 'programs', k))
    row = next(r for r in _flow_yaml.load()['steps'] if str(r['id']) == 'D1')
    inputs = worker._declared_input_files(project, row['required_inputs'])
    attempt = versions.begin_step(project, 'D1', inputs)
    with versions.active_steps(project, [attempt]):
        _phase1(project, plugin, knobs=knobs)
        versions.publish_producer_outputs(project, attempt)
        consumer = gates.evaluate(project, row)
        pending = versions.finish_step(
            project, attempt, verdict=consumer['status'], canonical_pass=False,
            result={'runner': 'phase1_one_shot_runner',
                    'canonical_consumer': consumer})
    assert pending['status'] == 'NOT_MEASURED'
    assert consumer['step']['reason_class'] == 'awaiting_signed_judgement'
    assert versions.latest_pass(project, 'D1') is None
    original = project / 'steps' / pending['folder']
    before = {p: p.read_bytes() for p in (original / 'outputs.json',
                                        original / 'written.json',
                                        project / 'phase1/step_identity.json')}
    return project, plugin, ready, knobs, before


def _sign_d1_checkpoint(project):
    import ai_signed_judgement as ai
    receipt = project / 'reports/audit/ai_judgements/D1.json'
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text(json.dumps({
        'schema': ai.SCHEMA, 'step_id': 'D1', 'verdict': 'PASS',
        'signed_by': 'independent neutral fixture reviewer',
        'judgement': 'Reviewed the actual neutral producer output and input.',
        'evidence_sha256': ai.evidence_sha256(project, 'D1')}))


@pytest.mark.parametrize('review', ['missing', 'FAIL', 'PASS'])
@pytest.mark.parametrize('source_drift', [False, True])
def test_bounded_rtl_request_uses_intact_provenance_without_forging_d1(
        tmp_path, monkeypatch, review, source_drift):
    import ai_signed_judgement as ai
    import emit_attestation
    import step_output_collector as versions
    import task_nature_route as routes
    project, plugin, _, _, before = _recorded_d1_checkpoint(tmp_path, monkeypatch)
    if review in ('FAIL', 'PASS'):
        _sign_d1_checkpoint(project)
        signature = project / 'reports/audit/ai_judgements/D1.json'
        payload = json.loads(signature.read_text())
        payload['verdict'] = review
        signature.write_text(json.dumps(payload))
    if source_drift:
        source = plugin / 'programs/fake_l_producer.py'
        source.write_text(source.read_text() + '\n# A later valid producer revision.\n')
    monkeypatch.setattr(V, '_revalidate_phase1_checkpoint', lambda *a, **k:
                        pytest.fail('bounded RTL must not run full D1 qualification'))
    original = emit_attestation.phase1_provenance(project)
    called = []
    _, doc = _drive_main(
        project, monkeypatch, phase1=('NOT_MEASURED', 1, None), phase2=('PASS', 0),
        reuse_phase1=None, extra_argv=('--skip-phase3', '--skip-analog',
                                    '--exit-step', routes.EVIDENCE_EXIT['lint_validated']['exit_step']),
        after_phase=called.append)
    assert called == ['phase2'], doc
    assert doc['halted_at'] != 'phase1', doc
    assert doc['phase1_checkpoint_review']['verdict'] == (
        review if review in ('FAIL', 'PASS') else 'NOT_MEASURED'), doc
    assert versions.latest_pass(project, 'D1') is None
    assert ai.check(project, 'D1')[0] == (review == 'PASS')
    assert emit_attestation.phase1_provenance(project) == original
    assert {p: p.read_bytes() for p in before} == before
    assert any('BOUNDED_RTL_PHASE1_PROVENANCE' in item for item in doc['advisories'])


@pytest.mark.parametrize('corruption', ['input', 'output', 'identity'])
def test_bounded_rtl_request_refuses_corrupt_source_provenance(tmp_path, monkeypatch, corruption):
    project, _, _, _, _ = _recorded_d1_checkpoint(tmp_path, monkeypatch)
    path = {'input': project / 'input/docs/spec.md',
            'output': project / 'phase1/generated_docs/L1_DOC.json',
            'identity': project / 'phase1/step_identity.json'}[corruption]
    path.write_text(path.read_text() + '\ncorrupted\n')
    called = []
    _, doc = _drive_main(
        project, monkeypatch, phase1=('NOT_MEASURED', 1, None), phase2=('PASS', 0),
        reuse_phase1=None, extra_argv=('--skip-phase3', '--skip-analog',
                                    '--entry-step', '2', '--exit-step', '2'),
        after_phase=called.append)
    assert called == [] and doc['halted_at'] == 'phase1', doc


def test_rtl_only_evidence_resolves_the_existing_registry():
    import task_nature_route as routes
    for name, row in routes.EVIDENCE_EXIT.items():
        expected = name in ('existence', 'lint_validated', 'behaviour', 'proof')
        assert routes.is_rtl_only_evidence(name) == expected
        assert routes.is_rtl_only_evidence(exit_step=row['exit_step']) == expected
        assert routes.is_rtl_only_evidence(name, exit_step=row['exit_step']) == expected
        assert routes.is_rtl_only_evidence(name, exit_step='unrecognised') is False
    assert routes.is_rtl_only_evidence() is False
    assert routes.is_rtl_only_evidence('unrecognised') is False


@pytest.mark.parametrize('extra,skip_physical', [
    (('--exit-step', 'D1'), True),
    (('--entry-step', 'D1', '--exit-step', '2'), True),
    (('--exit-step', '9'), True),
    ((), True),
    (('--exit-step', '2'), False),
])
def test_non_rtl_evidence_retains_full_d1_handoff(tmp_path, monkeypatch, extra, skip_physical):
    project, _, _, _, _ = _recorded_d1_checkpoint(tmp_path, monkeypatch)
    called = []
    _, doc = _drive_main(
        project, monkeypatch, phase1=('NOT_MEASURED', 1, None), phase2=('PASS', 0),
        reuse_phase1=None, extra_argv=('--skip-analog',
                                    *(('--skip-phase3',) if skip_physical else ()), *extra),
        after_phase=called.append)
    assert called == [] and doc['halted_at'] == 'phase1', doc


def test_bounded_rtl_request_does_not_accept_a_failed_rtl_program(tmp_path, monkeypatch):
    project, _, _, _, _ = _recorded_d1_checkpoint(tmp_path, monkeypatch)
    called = []
    _, doc = _drive_main(
        project, monkeypatch, phase1=('NOT_MEASURED', 1, None), phase2=('FAIL', 1),
        reuse_phase1=None, extra_argv=('--skip-phase3', '--skip-analog', '--exit-step', '2'),
        after_phase=called.append)
    assert called == ['phase2'], doc
    assert doc['halted_at'] == 'phase2' and doc['verdict'] != 'PASS', doc


@pytest.mark.timeout(300)
def test_bounded_rtl_request_reaches_the_real_lint_consumer(tmp_path):
    """Real retained producer, normal unified entry and real RTL lint in both directions."""
    import hashlib
    import subprocess
    import emit_attestation
    import benchmark_io_adapter as bio
    from programs.tests._hostpaths import require_repo
    fixture = require_repo() / 'vibe-ic-marketplace/plugins/vibe-ic/programs/tests/fixtures/librelane_lint_frontend/plain.v'
    source = fixture.read_text()
    project = tmp_path / 'native'
    docs = project / 'input/docs'
    docs.mkdir(parents=True)
    prompt = 'Implement this bitwise inverter with the supplied public interface.\n\n```verilog\n' + source + '```\n'
    (docs / 'spec.md').write_text(prompt)
    (project / 'input/phase1_prompt.md').write_text(prompt)
    stage_owner_route(project, 'ic')
    child_env = {key: value for key, value in os.environ.items()
                 if not key.startswith('VIBEIC_EXECUTION')}
    producer = subprocess.run([
        sys.executable, str(PROGRAMS / 'phase1_one_shot_runner.py'), str(project),
        '--mode', 'docs', '--skip-analog', '--ic-name', 'plain'],
        capture_output=True, text=True, env=child_env, timeout=80)
    (tmp_path / 'native-phase1.log').write_text(producer.stdout + producer.stderr)
    provenance = emit_attestation.phase1_provenance(project)
    assert provenance.get('ran') is True, producer.stdout + producer.stderr
    original = {p: hashlib.sha256(p.read_bytes()).hexdigest()
                for p in (docs / 'spec.md', project / 'input/phase1_prompt.md')}
    rtl = project / 'phase2/stage1/rtl/plain.v'
    rtl.parent.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, str(PROGRAMS / 'vibe_ic_one_shot_runner.py'),
               str(project), '--route', 'ic', '--ic-name', 'plain',
               '--skip-phase3', '--skip-analog', '--skip-hardware', '--no-dashboard',
               '--entry-step', '2', '--exit-step', '2', '--max-rtl-repair-retries', '0']
    for valid in (True, False):
        rtl.write_text(source if valid else 'module plain( input [7:0] value_i, output [7:0] value_o); assign value_o = ; endmodule\n')
        result = subprocess.run(command, capture_output=True, text=True,
                                env=child_env, timeout=80)
        (tmp_path / ('native-valid.log' if valid else 'native-invalid.log')).write_text(
            result.stdout + result.stderr)
        report = json.loads(_pl.report_path(project, 'vibe_ic_one_shot.json').read_text())
        phase2 = next(row for row in report['phases'] if row['name'] == 'phase2')
        assert phase2['verdict'] != 'SKIPPED', report
        lint_path = project / 'reports/phase2/lint/rtl_hygiene.json'
        assert lint_path.is_file(), result.stdout + result.stderr
        lint = json.loads(lint_path.read_text())
        assert isinstance(lint, list), lint
        child = json.loads(_pl.report_path(project, 'phase2_one_shot.json').read_text())
        measured = next(row for row in child['steps'] if row['name'] == 'rtl_lint_tool')
        assert measured['status'] == ('PASS' if valid else 'FAIL'), child
        context = measured['extras']['native_context']
        assert isinstance(context['native_returncode'], int), context
        assert (context['native_returncode'] == 0) is valid, context
        assert context['input_sha256'], context
        if valid:
            assert context['status'] == 'MEASURED', context
        else:
            assert lint, 'the compiler rejection must retain its actual findings'
        if valid:
            collected = bio.collect('verilogeval', project.name, project,
                                    supplied_rtl=True, required_top='plain')
            assert collected['ok'] is True, collected
            assert bio.collect('verilogeval', project.name, project,
                               required_top='plain')['ok'] is False
        else:
            assert phase2['verdict'] == 'FAIL' and result.returncode != 0, report
        assert emit_attestation.phase1_provenance(project) == provenance
        assert {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in original} == original


@pytest.mark.parametrize('control', ['valid', 'invalid_rtl', 'rejected_d1'])
def test_explicit_rtl_window_summary_keeps_retained_d1_qualification(tmp_path, control):
    """Actual D01 provenance and D11 lint through the public bounded caller."""
    import subprocess
    import emit_attestation
    import flow109
    from programs.tests._hostpaths import require_repo
    fixture = require_repo() / 'vibe-ic-marketplace/plugins/vibe-ic/programs/tests/fixtures/librelane_lint_frontend/plain.v'
    source = fixture.read_text()
    project = tmp_path / 'scoped'
    (project / 'input/rtl').mkdir(parents=True)
    prompt = project / 'input/phase1_prompt.md'
    prompt.write_text('Debug this bitwise inverter; deliver only RTL with lint validation.\n'
                      '```verilog\n' + source + '```\n')
    supplied = project / 'input/rtl/plain.v'
    supplied.write_text(source)
    profile = next(row for row in flow109.load_registry()['reference_profiles']
                   if row['name'] == 'RTL-only')
    manifest = project / 'input/flow109-manifest.json'
    manifest.write_text(json.dumps({'features': profile['features']}))
    child_env = {key: value for key, value in os.environ.items()
                 if not key.startswith('VIBEIC_EXECUTION')}
    command = [sys.executable, str(PROGRAMS / 'vibe_ic_one_shot_runner.py'),
               str(project), '--route', 'ip', '--delivery-target', 'rtl',
               '--flow', '109', '--flow109-manifest', str(manifest),
               '--skip-phase3', '--skip-analog', '--skip-hardware', '--no-dashboard']
    producer = subprocess.run(command + ['--entry-step', 'D01', '--exit-step', 'D01'],
                              capture_output=True, text=True, env=child_env, timeout=80)
    provenance = emit_attestation.phase1_provenance(project)
    assert provenance.get('ran') is True, producer.stdout + producer.stderr
    retained_report = _pl.report_path(project, 'phase1_one_shot.json')
    before = {path: path.read_bytes() for path in (prompt, supplied, manifest, retained_report)}
    if control == 'rejected_d1':
        _sign_d1_checkpoint(project)
        signature = project / 'reports/audit/ai_judgements/D1.json'
        payload = json.loads(signature.read_text())
        payload['verdict'] = 'FAIL'
        signature.write_text(json.dumps(payload))
    staged = project / 'phase2/stage1/rtl/plain.v'
    staged.parent.mkdir(parents=True, exist_ok=True)
    staged.write_text(source if control != 'invalid_rtl' else
                      'module plain(input [7:0] value_i, output [7:0] value_o); assign value_o = ; endmodule\n')
    result = subprocess.run(command + ['--entry-step', 'D11', '--exit-step', 'D11',
                                      '--top-name', 'plain', '--max-rtl-repair-retries', '0'],
                            capture_output=True, text=True, env=child_env, timeout=80)
    (tmp_path / 'scoped-run.log').write_text(result.stdout + result.stderr)
    report = json.loads(_pl.report_path(project, 'vibe_ic_one_shot.json').read_text())
    child = json.loads(_pl.report_path(project, 'phase2_one_shot.json').read_text())
    row = json.loads(sorted((project / 'steps/019_rtl-validation-and-lint').glob('*/result.json'))[-1].read_text())
    assert child['verdict'] == ('FAIL' if control == 'invalid_rtl' else 'PASS'), child
    assert row['default_row_status'] == ('FAIL' if control == 'invalid_rtl' else 'PASS'), row
    assert row['completed'] is (control != 'invalid_rtl'), row
    assert row['exit_code'] == (1 if control == 'invalid_rtl' else 0), row
    assert result.returncode == (0 if control == 'valid' else 1), report
    assert report['dispatched_verdict'] == ('PASS' if control == 'valid' else 'FAIL'), report
    assert report['phases'][0] == {
        'name': 'phase1', 'verdict': 'FAIL' if control == 'rejected_d1' else 'NOT_MEASURED', 'rc': 0}
    assert report['whole_flow_verdict'] == 'NOT_MEASURED'
    assert report['verdict'] == ('NOT_MEASURED' if control == 'valid' else 'FAIL')
    assert emit_attestation.phase1_provenance(project) == provenance
    assert {path: path.read_bytes() for path in before} == before


def test_signed_reused_d1_runs_complete_consumer_and_retains_current_pass(
        tmp_path, monkeypatch):
    import step_output_collector as versions
    project, _, _, _, before = _recorded_d1_checkpoint(tmp_path, monkeypatch)
    _sign_d1_checkpoint(project)
    docs_before = V._p1id.docs_snapshot(project)
    called = []
    _, doc = _drive_main(
        project, monkeypatch, phase1=('FAIL', 1, None), phase2=('PASS', 0),
        reuse_phase1=True, extra_argv=('--skip-phase3', '--skip-analog'),
        after_phase=called.append)
    assert called == ['phase2'], 'the producer and expert extraction must not rerun'
    accepted = versions.latest_pass(project, 'D1')
    assert accepted is not None, 'the signed checkpoint has no retained canonical PASS'
    assert accepted['canonical_pass'] is True and accepted['current_inputs'] is True
    assert doc['phase1_checkpoint_review']['canonical_acceptance']['verdict'] == 'PASS'
    assert accepted['result']['canonical_consumer']['status'] == 'PASS'
    assert accepted['result']['checkpoint']['producer_started'] is False
    assert accepted['result']['checkpoint']['producer_reused'] is True
    assert accepted['folder'] != accepted['result']['checkpoint']['prior_folder']
    # The view index can hold the enclosing materializer's partial observation.
    # Complete acceptance belongs to the retained canonical-consumer record.
    consumed = next(r for r in versions.current_acceptance(project, 0) if r['id'] == 'D1')
    assert consumed['status'] == 'PASS'
    assert consumed['folder'] == accepted['folder']
    old_written = next(data for path, data in before.items() if path.name == 'written.json')
    assert (project / 'steps' / accepted['folder'] / 'written.json').read_bytes() == old_written
    assert V._p1id.docs_snapshot(project) == docs_before
    assert {p: p.read_bytes() for p in before} == before


@pytest.mark.parametrize('mutate_during_consumer', [False, True])
def test_signed_d1_cannot_override_a_complete_gate_failure(
        tmp_path, monkeypatch, mutate_during_consumer):
    import execution_backend_gates as gates
    import step_output_collector as versions
    project, _, ready, _, before = _recorded_d1_checkpoint(tmp_path, monkeypatch)
    _sign_d1_checkpoint(project)
    ready.unlink()  # Outside the signed L-doc evidence; the full gate must refuse it.
    consume = gates.evaluate
    calls = []
    def observe(project, row):
        result = consume(project, row)
        calls.append(result['status'])
        if mutate_during_consumer:
            (project / 'input/docs/spec.md').write_text('changed during the refused gate')
        return result
    monkeypatch.setattr(gates, 'evaluate', observe)
    called = []
    _, doc = _drive_main(
        project, monkeypatch, phase1=('PASS', 0, None), phase2=('PASS', 0),
        reuse_phase1=True, extra_argv=('--skip-phase3', '--skip-analog'),
        after_phase=called.append)
    assert calls == ['FAIL'] and called == []
    assert doc['halted_at'] == 'phase1'
    assert doc['phase1_checkpoint_review']['verdict'] == 'FAIL'
    assert doc['phase1_checkpoint_review']['canonical_acceptance']['verdict'] == 'FAIL'
    assert versions.latest_pass(project, 'D1') is None
    consumed = next(r for r in versions.current_acceptance(project, 0) if r['id'] == 'D1')
    assert consumed['status'] == 'FAIL'
    assert consumed['canonical_pass'] is False
    assert consumed['result']['canonical_consumer']['status'] == 'FAIL'
    assert {p: p.read_bytes() for p in before} == before


def test_d1_evidence_changed_during_revalidation_cannot_publish_pass(tmp_path, monkeypatch):
    import execution_backend_gates as gates
    import step_output_collector as versions
    project, _, _, _, _ = _recorded_d1_checkpoint(tmp_path, monkeypatch)
    _sign_d1_checkpoint(project)
    consume = gates.evaluate
    def change(project, row):
        result = consume(project, row)
        assert result['status'] == 'PASS'
        (project / 'input/docs/spec.md').write_text('changed after the full consumer')
        return result
    monkeypatch.setattr(gates, 'evaluate', change)
    called = []
    _, doc = _drive_main(
        project, monkeypatch, phase1=('PASS', 0, None), phase2=('PASS', 0),
        reuse_phase1=True, extra_argv=('--skip-phase3', '--skip-analog'),
        after_phase=called.append)
    assert called == [] and doc['halted_at'] == 'phase1'
    assert versions.latest_pass(project, 'D1') is None
    accepted = versions.current_acceptance(project, 0)[0]
    assert accepted['status'] == 'NOT_MEASURED'
    assert accepted['result']['canonical_consumer']['status'] == 'NOT_MEASURED'
    assert accepted['result']['observed_canonical_consumer']['status'] == 'PASS'


@pytest.mark.parametrize('mutation', ['input', 'output', 'producer'])
def test_d1_checkpoint_identity_still_refuses_changed_evidence(tmp_path, monkeypatch, mutation):
    project, plugin, _, knobs, _ = _recorded_d1_checkpoint(tmp_path, monkeypatch)
    _sign_d1_checkpoint(project)
    path = {'input': project / 'input/docs/spec.md',
            'output': project / 'phase1/generated_docs/L1_DOC.json',
            'producer': plugin / 'programs/fake_l_producer.py'}[mutation]
    path.write_text(path.read_text() + '\nchanged\n')
    fresh = V._phase1_freshness(project, knobs)
    assert fresh['state'] != V._p1id.REUSE
    run, mode = V._phase1_decision(project, False, knobs)
    assert (run, mode) == ((False, V._P1_MODE_REFUSED) if mutation == 'output'
                           else (True, 'docs'))


@pytest.mark.parametrize('review', ['PASS', 'FAIL', 'missing', 'stale'])
@pytest.mark.parametrize('mechanical', ['present', 'missing'])
def test_source_drift_uses_current_d1_without_reextracting(
        tmp_path, monkeypatch, review, mechanical):
    """Run the actual front-door decision and full neutral D1 consumer."""
    import ai_signed_judgement as ai
    import step_output_collector as versions
    project, plugin, ready, knobs, before = _recorded_d1_checkpoint(tmp_path, monkeypatch)
    monkeypatch.setattr(V, 'PROGRAMS_DIR', plugin / 'programs')
    _sign_d1_checkpoint(project)
    signature = project / 'reports/audit/ai_judgements/D1.json'
    if review == 'missing':
        signature.unlink()
    elif review in ('FAIL', 'stale'):
        payload = json.loads(signature.read_text())
        if review == 'FAIL':
            payload['verdict'] = 'FAIL'
        else:
            payload['evidence_sha256'] = '0' * 64
        signature.write_text(json.dumps(payload))
    source = plugin / 'programs/fake_l_producer.py'
    source.write_text(source.read_text() + '\n# A later source revision.\n')
    if mechanical == 'missing':
        ready.unlink()
    docs_before = V._p1id.docs_snapshot(project)
    assert V._phase1_freshness(project, knobs)['reason'] == 'PRODUCER_CHANGED'
    called = []
    _, report = _drive_main(
        project, monkeypatch, phase1=('FAIL', 1, None), phase2=('PASS', 0),
        reuse_phase1=None, extra_argv=('--skip-phase3', '--skip-analog'),
        after_phase=called.append)
    passes = review == 'PASS' and mechanical == 'present'
    assert called == (['phase2'] if passes else [])
    assert report['halted_at'] != 'phase1' if passes else report['halted_at'] == 'phase1'
    assert report['phase1_generated_docs']['state'] == 'REVALIDATE'
    if passes:
        assert report['phase1_generated_docs']['consumer_revalidated'] is True
        assert not any('STALE_GENERATED_DOCS' in a for a in report['advisories'])
        accepted = versions.latest_pass(project, 'D1')
        assert accepted is not None and accepted['canonical_pass']
        checkpoint = accepted['result']['checkpoint']
        assert checkpoint['producer_started'] is False
        assert checkpoint['producer_current'] is False
        assert checkpoint['source_assessment']['reason'] == 'PRODUCER_CHANGED'
        original_written = next(v for p, v in before.items() if p.name == 'written.json')
        assert (project / 'steps' / accepted['folder'] / 'written.json').read_bytes() == original_written
    else:
        assert versions.latest_pass(project, 'D1') is None
        assert report['phase1_checkpoint_review']['verdict'] != 'PASS'
        assert report['verdict'] != 'PASS'
    assert ai.check(project, 'D1')[0] == (review == 'PASS')
    assert V._p1id.docs_snapshot(project) == docs_before
    assert {p: p.read_bytes() for p in before} == before


@pytest.mark.parametrize('change', ['input', 'output', 'source'])
def test_source_drift_revalidation_refuses_changes_during_consumer(
        tmp_path, monkeypatch, change):
    import execution_backend_gates as gates
    import step_output_collector as versions
    project, plugin, _, _, _ = _recorded_d1_checkpoint(tmp_path, monkeypatch)
    monkeypatch.setattr(V, 'PROGRAMS_DIR', plugin / 'programs')
    _sign_d1_checkpoint(project)
    source = plugin / 'programs/fake_l_producer.py'
    source.write_text(source.read_text() + '\n# First source revision.\n')
    consume = gates.evaluate
    def mutate(project, row):
        result = consume(project, row)
        assert result['status'] == 'PASS'
        path = {'input': project / 'input/docs/spec.md',
                'output': project / 'phase1/generated_docs/L1_DOC.json',
                'source': source}[change]
        path.write_text(path.read_text() + '\nchanged while being reviewed\n')
        return result
    monkeypatch.setattr(gates, 'evaluate', mutate)
    called = []
    _, report = _drive_main(
        project, monkeypatch, phase1=('FAIL', 1, None), phase2=('PASS', 0),
        reuse_phase1=None, extra_argv=('--skip-phase3', '--skip-analog'),
        after_phase=called.append)
    assert called == [] and report['halted_at'] == 'phase1'
    assert versions.latest_pass(project, 'D1') is None
    current = next(r for r in versions.current_acceptance(project, 0) if r['id'] == 'D1')
    assert current['status'] == 'NOT_MEASURED'
    assert current['result']['observed_canonical_consumer']['status'] == 'PASS'


def _save_complete_acceptance(project, sid, status, *, runner, excluded=""):
    """Use the actual version writer; the phase producer's result stays separate."""
    import step_output_collector as versions
    attempt = versions.begin_step(project, sid)
    return versions.finish_step(
        project, attempt, verdict=status, canonical_pass=(status == "PASS"),
        result={"runner": runner, "canonical_consumer": {
            "status": status, "ledger": [],
            "step": {"id": sid, "status": status,
                     "excluded_from_verdict": excluded}}})


@pytest.mark.parametrize("phase,sid,runner", [
    ("phase1", "0.5ic", "phase1_one_shot_runner"),
    ("phase2", "10", "design_one_shot_runner"),
])
@pytest.mark.parametrize("status", ["FAIL", "NOT_MEASURED"])
def test_complete_current_rejection_halts_before_the_next_phase(
        project, monkeypatch, phase, sid, runner, status):
    called = []
    def after_phase(name):
        called.append(name)
        if name == phase:
            _save_complete_acceptance(project, sid, status, runner=runner)
    rc, doc = _drive_main(
        project, monkeypatch, phase1=("PASS", 0, None), phase2=("PASS", 0),
        phase3=({"verdict": "PASS"}, 0), after_phase=after_phase)
    assert rc == 1 and doc["verdict"] == status, doc
    assert doc["halted_at"] == phase
    assert called == (["phase1"] if phase == "phase1" else ["phase1", "phase2"])
    # The raw native report/rc remain honest; only the flow decision changes.
    assert doc["phases"][0 if phase == "phase1" else 1]["rc"] == 0
    assert V._read_report(V._phase_report_path(
        project, phase + "_one_shot.json"))["verdict"] == "PASS"


@pytest.mark.parametrize("latest", ["PASS", "FAIL"])
def test_latest_complete_attempt_controls_advancement_not_partial_index(
        project, monkeypatch, latest):
    import step_output_collector as versions
    called = []
    def after_phase(name):
        called.append(name)
        if name != "phase1":
            return
        _save_complete_acceptance(project, "D1", "FAIL" if latest == "PASS" else "PASS",
                                  runner="phase1_one_shot_runner")
        accepted = _save_complete_acceptance(project, "D1", latest,
                                             runner="phase1_one_shot_runner")
        partial = versions.begin_step(project, "D1")
        versions.finish_step(project, partial, verdict="PASS",
                             result={"runner": "phase1_one_shot_runner", "canonical_consumer": None})
        assert versions._read_index(project)["steps"][0]["folder"] == partial["folder"]
        assert accepted["folder"] != partial["folder"]
    rc, doc = _drive_main(project, monkeypatch, phase1=("PASS", 0, None),
                          phase2=("PASS", 0), extra_argv=("--skip-phase3",),
                          after_phase=after_phase)
    assert called == (["phase1", "phase2"] if latest == "PASS" else ["phase1"])
    assert (rc, doc["verdict"], doc["halted_at"]) == (
        (0, "PASS", None) if latest == "PASS" else (1, "FAIL", "phase1"))


def test_prior_complete_failure_does_not_poison_a_new_phase(project, monkeypatch):
    _save_complete_acceptance(project, "D1", "FAIL", runner="phase1_one_shot_runner")
    called = []
    def after_phase(name):
        called.append(name)
        if name == "phase1":
            _save_complete_acceptance(project, "D1", "PASS", runner="phase1_one_shot_runner")
    rc, doc = _drive_main(project, monkeypatch, phase1=("PASS", 0, None),
                          phase2=("PASS", 0), extra_argv=("--skip-phase3",),
                          after_phase=after_phase)
    assert called == ["phase1", "phase2"]
    assert rc == 0 and doc["verdict"] == "PASS"


def test_existing_board_exclusion_remains_unmeasured_and_nonblocking(project, monkeypatch):
    def after_phase(name):
        if name == "phase2":
            _save_complete_acceptance(
                project, "39", "NOT_MEASURED", runner="design_one_shot_runner",
                excluded="NOT_MEASURED, excluded from the run verdict: board not built")
    rc, doc = _drive_main(project, monkeypatch, phase1=("PASS", 0, None),
                          phase2=("PASS", 0), extra_argv=("--skip-phase3",),
                          after_phase=after_phase)
    assert rc == 0 and doc["verdict"] == "PASS"
    import step_output_collector as versions
    assert versions.latest_pass(project, "39") is None


def test_coverage_only_demotion_cannot_hide_another_current_step_rejection(project, monkeypatch):
    def after_phase(name):
        if name == 'phase1':
            _save_complete_acceptance(project, '0.5ic', 'FAIL', runner='phase1_one_shot_runner')
    rc, doc = _drive_main(
        project, monkeypatch,
        phase1=('FAIL', 1, {'coverage_only_failure': True, 'coverage_pct': 71.0, 'total_todo': 0}),
        phase2=('PASS', 0), extra_argv=('--skip-phase3',), after_phase=after_phase)
    assert rc == 1 and doc['verdict'] == 'FAIL'
    assert doc['halted_at'] == 'phase1' and doc['demoted_phases'] == {}


def test_current_unmeasured_consumer_never_downgrades_native_failure(project):
    started = time.time()
    _save_complete_acceptance(project, 'D1', 'NOT_MEASURED', runner='phase1_one_shot_runner')
    _report(project, 'phase1_one_shot.json', {'verdict': 'FAIL'})
    assert V._row_verdict(project, 'phase1_one_shot.json', 1, started, 'phase1')[0] == 'FAIL'


# ── H1: the #505 standalone shape ──────────────────────────────────────────

def test_the_505_standalone_shape_is_pass_with_waivers_at_exit_zero(
        project, monkeypatch):
    """THE REGRESSION, through main(): coverage-only phase1 FAIL at rc 1, demoted,
    plus a passing phase2. On 99ae0fa6b this published FAIL and exited 1."""
    rc, doc = _drive_main(
        project, monkeypatch,
        phase1=("FAIL", 1, {"coverage_only_failure": True,
                            "coverage_pct": 71.0, "total_todo": 0}),
        phase2=("PASS", 0),
        extra_argv=("--skip-phase3",))
    assert doc["verdict"] == "PASS_WITH_WAIVERS", (
        doc["verdict"], doc.get("verdict_reasons"))
    assert rc == 0, rc
    phases = {r["name"]: r for r in doc["phases"]}
    assert phases["phase1"]["verdict"] == "COVERAGE-INCOMPLETE"
    assert phases["phase1"]["rc"] == 1, (
        "the row must KEEP the rc its process really returned; the demotion is "
        "recorded beside it, not by rewriting history")
    dem = doc["demoted_phases"]["phase1"]
    assert dem["token"] == V.DEMOTION_COVERAGE_ONLY
    assert dem["original_rc"] == 1 and dem["original_verdict"] == "FAIL"
    assert any("pre-demotion" in r for r in doc["verdict_reasons"]), (
        doc["verdict_reasons"])


def test_an_undemoted_row_claiming_a_pass_at_nonzero_rc_still_fails(
        project, monkeypatch):
    """The rule the demotion exemption must not launder: phase2 reports PASS and
    exits 1, with no demotion record. That is a report disagreeing with its own
    process and it still fails."""
    rc, doc = _drive_main(project, monkeypatch,
                          phase1=("PASS", 0, None), phase2=("PASS", 1),
                          extra_argv=("--skip-phase3",))
    assert doc["verdict"] == "FAIL", (doc["verdict"], doc["verdict_reasons"])
    assert rc == 1
    assert doc["demoted_phases"] == {}
    assert any("rc=1" in r for r in doc["verdict_reasons"])


def test_only_the_505_token_exempts_an_rc():
    """The exemption is keyed on ONE token minted at ONE site. A row carrying any
    other demotion record is not exempt — demotion is not a laundering path."""
    rows = [("phase1", "COVERAGE-INCOMPLETE", 1)]
    assert V._roll_up(rows, ["PASS"],
                      demoted={"phase1": {"token": V.DEMOTION_COVERAGE_ONLY}},
                      audit_axis={"state": "PASS"})[0] == "PASS_WITH_WAIVERS"
    for bogus in ({"token": "something_else"}, {}, {"token": ""}):
        assert V._roll_up(rows, ["PASS"], demoted={"phase1": bogus},
                          audit_axis={"state": "PASS"})[0] == "FAIL", bogus


# ── M2: the audit axis never passes on a token nobody taught it ────────────

def test_the_audit_axis_is_fail_closed_for_every_token():
    assert V._audit_axis_from_verdicts(["PASS"])["state"] == "PASS"
    assert V._audit_axis_from_verdicts(["FAIL"])["state"] == "FAIL"
    assert V._audit_axis_from_verdicts(["FAIL", "PASS"])["state"] == "FAIL"
    assert V._audit_axis_from_verdicts(
        ["PASS_WITH_WAIVERS"])["state"] == "PASS_WITH_WAIVERS"
    for token in ("NOT_MEASURED", "INSUFFICIENT_DATA", "", "greenish", None):
        axis = V._audit_axis_from_verdicts([token] if token is not None else [])
        assert axis["state"] == "NOT_MEASURED", (token, axis)
        assert axis["reason"], token
    assert V._audit_axis_from_verdicts(None)["state"] == "NOT_MEASURED"


def test_a_phase3_run_with_no_readable_audit_is_not_measured(project,
                                                             monkeypatch):
    """THE SWALLOWED-REFRESH CASE, through main(): phase3 ran and reported PASS,
    and no completion audit exists. On 99ae0fa6b that published PASS at exit 0."""
    rc, doc = _drive_main(project, monkeypatch,
                          phase1=("PASS", 0, None), phase2=("PASS", 0),
                          phase3=({"verdict": "PASS"}, 0))
    assert doc["completion_audit_axis"]["state"] == "NOT_MEASURED", (
        doc["completion_audit_axis"])
    assert doc["verdict"] == "NOT_MEASURED", (
        doc["verdict"], doc["verdict_reasons"])
    assert rc == 1
    assert any("completion audit" in r for r in doc["verdict_reasons"])


def test_a_failing_audit_still_fails_a_fully_passing_run(project, monkeypatch):
    """The refutation that stands: the conjunction includes the audit."""
    def _phase3(payload, code):
        return payload, code
    monkeypatch.setattr(V, "_phase1_decision", lambda *a, **k: (True, "docs"))
    # the audit document is written by phase3's stub so it belongs to this run
    def fake_run_phase(label, runner, args, env=None):
        if "phase1" in runner.name:
            _report(project, "phase1_one_shot.json", {"verdict": "PASS"})
            return 0
        if "phase2" in runner.name:
            _report(project, "phase2_one_shot.json", {"verdict": "PASS"})
            return 0
        if "phase3" in runner.name:
            _report(project, "phase3_one_shot.json", {"verdict": "PASS"})
            _report(project, "phase23_completion_audit.json", {"verdict": "FAIL"})
            return 0
        return 0
    monkeypatch.setattr(V, "_run_phase", fake_run_phase)
    monkeypatch.setattr(sys, "argv", ["vibe_ic_one_shot_runner", str(project),
                                      "--no-dashboard", "--skip-hardware"])
    real_entry('IC', 'default', project)
    rc = V.main()
    doc = json.loads(_pl.report_path(project, "vibe_ic_one_shot.json").read_text())
    assert doc["completion_audit_axis"]["state"] == "FAIL"
    assert doc["verdict"] == "FAIL" and rc == 1
    assert any("completion audit" in r for r in doc["verdict_reasons"])


# ── M3: the axis belongs to THIS invocation ────────────────────────────────

def test_a_leftover_audit_from_an_earlier_run_does_not_gate_this_one(
        project, monkeypatch):
    """A `--skip-phase3` invocation over a tree that still carries an earlier full
    run's FAILING audit. On 99ae0fa6b that published FAIL; the base read PASS. This
    run has no audit axis at all, and says so."""
    old = _report(project, "phase23_completion_audit.json", {"verdict": "FAIL"})
    _report(project, "phase3_one_shot.json",
            {"verdict": "FAIL", "completion_audit_verdict": "FAIL"})
    import os
    stale = os.stat(old).st_mtime_ns - 10 ** 10
    for rel in ("phase23_completion_audit.json", "phase3_one_shot.json"):
        os.utime(_pl.report_path(project, rel), ns=(stale, stale))

    rc, doc = _drive_main(project, monkeypatch,
                          phase1=("PASS", 0, None), phase2=("PASS", 0),
                          extra_argv=("--skip-phase3",))
    assert doc["completion_audit_axis"]["state"] == "NOT_APPLICABLE", (
        doc["completion_audit_axis"])
    assert doc["verdict"] == "PASS", (doc["verdict"], doc["verdict_reasons"])
    assert rc == 0
    assert any("no phase2/3 completion audit axis" in r
               for r in doc["verdict_reasons"]), doc["verdict_reasons"]


def test_a_document_older_than_this_invocation_is_named_as_ignored(project):
    """The axis reader, directly: phase3 ran, but the only audit on disk predates
    this invocation. It is IGNORED and the axis is NOT_MEASURED — never PASS, and
    never that document's verdict either."""
    import os
    _report(project, "phase23_completion_audit.json", {"verdict": "PASS"})
    path = _pl.report_path(project, "phase23_completion_audit.json")
    stale = os.stat(path).st_mtime_ns - 10 ** 10
    os.utime(path, ns=(stale, stale))
    axis = V._completion_audit_axis(project, phase3_ran=True,
                                    started_at=os.stat(path).st_mtime + 5)
    assert axis["state"] == "NOT_MEASURED", axis
    assert axis["ignored"] == [
        "reports/audit/phase23_completion_audit.json"], axis
    assert "earlier run" in axis["reason"], axis
    assert axis["sources"] == []


def test_no_phase3_means_no_axis_not_a_satisfied_one(project):
    _report(project, "phase23_completion_audit.json", {"verdict": "PASS"})
    axis = V._completion_audit_axis(project, phase3_ran=False, started_at=0.0)
    assert axis["state"] == "NOT_APPLICABLE", axis
    assert "did not run in this invocation" in axis["reason"]


# ── L4: the guard replays the runner's roll-up ─────────────────────────────

def _orchestrator_report(verdict: str, phases: list, **extra) -> dict:
    doc = {"phase": "vibe-ic", "verdict": verdict, "phases": phases}
    doc.update(extra)
    return doc


def test_the_guard_accepts_a_genuine_new_rule_report():
    """A report that is FAIL because its own completion audit failed, with every
    phase passing. The guard's old copy of the rule derived PASS and discarded it
    as forged."""
    phases = [{"name": "phase1", "verdict": "PASS", "rc": 0},
              {"name": "phase2", "verdict": "PASS", "rc": 0},
              {"name": "analog", "verdict": "SKIPPED", "rc": 0},
              {"name": "phase3", "verdict": "PASS", "rc": 0},
              {"name": "mixed_signal", "verdict": "SKIPPED", "rc": 0}]
    data = _orchestrator_report(
        "FAIL", phases, completion_audit_axis={"state": "FAIL", "reason": "x"},
        completion_audit_verdicts=["FAIL"], demoted_phases={})
    assert GUARD._expected_front_door_verdict(data, phases) == "FAIL"


def test_the_guard_rejects_a_forged_pass_over_a_failing_audit():
    phases = [{"name": "phase1", "verdict": "PASS", "rc": 0},
              {"name": "phase2", "verdict": "PASS", "rc": 0},
              {"name": "analog", "verdict": "SKIPPED", "rc": 0},
              {"name": "phase3", "verdict": "PASS", "rc": 0},
              {"name": "mixed_signal", "verdict": "SKIPPED", "rc": 0}]
    data = _orchestrator_report(
        "PASS", phases, completion_audit_axis={"state": "FAIL", "reason": "x"},
        completion_audit_verdicts=["FAIL"], demoted_phases={})
    assert GUARD._expected_front_door_verdict(data, phases) != "PASS"


def test_not_measured_is_a_front_door_verdict_the_guard_knows():
    assert "NOT_MEASURED" in GUARD._ORCHESTRATOR_VERDICTS, (
        "a genuine NOT_MEASURED report is discarded before any derivation runs")


def test_the_guard_holds_a_legacy_report_to_the_rule_it_was_published_under():
    """A report from before these fields existed carries no axis. It is judged by
    the old derivation — exactly as trusted as it was, and no more — because a
    guard cannot fairly hold a document to a rule it could not have followed."""
    phases = [{"name": "phase1", "verdict": "PASS", "rc": 0},
              {"name": "phase2", "verdict": "PASS", "rc": 0},
              {"name": "analog", "verdict": "SKIPPED", "rc": 0},
              {"name": "phase3", "verdict": "PASS", "rc": 0},
              {"name": "mixed_signal", "verdict": "SKIPPED", "rc": 0}]
    legacy = _orchestrator_report("PASS", phases)
    assert "completion_audit_axis" not in legacy
    assert GUARD._expected_front_door_verdict(legacy, phases) == "PASS"


def test_the_guard_does_not_keep_its_own_copy_of_the_rule():
    """SOURCE PIN, on the thing that drifted: the guard must delegate to the
    runner's roll-up for a report carrying its inputs."""
    src = (PROGRAMS / "vibe_ic_entry_guard.py").read_text()
    assert "_roll_up(" in src, (
        "the guard no longer calls the runner's roll-up; a second copy of the "
        "conjunction rule is what discarded genuine reports as forged")
    assert "import vibe_ic_one_shot_runner" in src


def test_main_always_supplies_the_axis():
    """THE PIN THAT KEEPS THE STRICT PATH FROM BEING BYPASSED.

    `_roll_up` applies the fail-closed audit rule only when an axis is SUPPLIED,
    because a caller passing none is not talking about the completion audit (#505's
    properties are stated that way). That scoping is only safe while the real
    front door always supplies one — so this asserts main's call site does, by AST,
    on the keyword rather than on surrounding text.
    """
    import ast
    tree = ast.parse((PROGRAMS / "vibe_ic_one_shot_runner.py").read_text())
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
             and n.func.id == "_roll_up"]
    assert calls, "main no longer rolls up through `_roll_up`"
    kwargs = [{k.arg for k in c.keywords} for c in calls]
    assert any("audit_axis" in kw and "demoted" in kw for kw in kwargs), (
        f"main's roll-up call does not supply `audit_axis`/`demoted`, so the "
        f"fail-closed audit rule and the #505 demotion exemption are both "
        f"unreachable on a real run; keywords seen: {kwargs}")
    # and the axis it supplies is the one tied to this invocation
    src = (PROGRAMS / "vibe_ic_one_shot_runner.py").read_text()
    assert "_completion_audit_axis(" in src and "phase3_ran=_phase3_ran" in src
    # PHASE 3's start, not the run's: a document written before phase3 began
    # cannot be phase3's refresh of it.
    assert 'started_at=_phase_started.get("phase3", t0)' in src


# ── R-0915-151: freshness on the CARRIED verdict, and on the rows ───────────

def _audit(project: Path, verdict: str, *, scope: dict = None,
           phase: str = "all") -> Path:
    doc = {"verdict": verdict, "phase": phase}
    if scope is not None:
        doc["scope"] = scope
    return _report(project, "phase23_completion_audit.json", doc)


WHOLE = {"whole_flow": True, "step_count": 70, "flow_step_total": 70}


def test_a_stale_audit_pass_repeated_by_a_fresh_carrier_is_not_measured(
        project, monkeypatch):
    """THE HIGH, through main(). phase3's finalize refresh swallows a TimeoutExpired,
    and `_derive_headline_verdict` then copies the OLD audit's verdict into a FRESH
    phase3_one_shot.json. My round-2 reader put the audit FILE in `ignored` and then
    accepted the SAME verdict from that carrier — axis PASS, exit 0.

    Here the audit says PASS and predates phase3; the carrier repeats it and is
    today's. The axis must be NOT_MEASURED, and the carrier must appear as a POINTER
    that was not used as evidence.
    """
    import os
    stale = _audit(project, "PASS", scope=dict(WHOLE))
    old = os.stat(stale).st_mtime_ns - 10 ** 10
    os.utime(stale, ns=(old, old))

    def fake_run_phase(label, runner, args, env=None):
        if "phase1" in runner.name:
            _report(project, "phase1_one_shot.json", {"verdict": "PASS"})
            return 0
        if "phase2" in runner.name:
            _report(project, "phase2_one_shot.json", {"verdict": "PASS"})
            return 0
        if "phase3" in runner.name:
            # the swallowed refresh: a FRESH report carrying the OLD audit's verdict
            _report(project, "phase3_one_shot.json",
                    {"verdict": "PASS", "completion_audit_verdict": "PASS"})
            return 0
        return 0

    monkeypatch.setattr(V, "_run_phase", fake_run_phase)
    monkeypatch.setattr(V, "_phase1_decision", lambda *a, **k: (True, "docs"))
    monkeypatch.setattr(sys, "argv", ["vibe_ic_one_shot_runner", str(project),
                                      "--no-dashboard", "--skip-hardware"])
    real_entry('IC', 'default', project)
    rc = V.main()
    doc = json.loads(_pl.report_path(project, "vibe_ic_one_shot.json").read_text())
    axis = doc["completion_audit_axis"]
    assert axis["state"] == "NOT_MEASURED", axis
    assert axis["sources"] == [], axis
    assert "reports/audit/phase23_completion_audit.json" in axis["ignored"], axis
    assert any(p["carries"] == "PASS" and p["used_as_evidence"] is False
               for p in axis["pointers"]), axis
    assert doc["verdict"] == "NOT_MEASURED" and rc == 1


def test_a_stale_audit_fail_does_not_gate_a_good_run(project, monkeypatch):
    """THE MIRROR, which matters just as much: a stale FAIL must not gate a run it
    never measured. It is still NOT_MEASURED — never FAIL, and never PASS."""
    import os
    stale = _audit(project, "FAIL", scope=dict(WHOLE))
    old = os.stat(stale).st_mtime_ns - 10 ** 10
    os.utime(stale, ns=(old, old))

    def fake_run_phase(label, runner, args, env=None):
        for name in ("phase1", "phase2", "phase3"):
            if name in runner.name:
                _report(project, f"{name}_one_shot.json", {"verdict": "PASS"})
        return 0

    monkeypatch.setattr(V, "_run_phase", fake_run_phase)
    monkeypatch.setattr(V, "_phase1_decision", lambda *a, **k: (True, "docs"))
    monkeypatch.setattr(sys, "argv", ["vibe_ic_one_shot_runner", str(project),
                                      "--no-dashboard", "--skip-hardware"])
    real_entry('IC', 'default', project)
    V.main()
    doc = json.loads(_pl.report_path(project, "vibe_ic_one_shot.json").read_text())
    assert doc["completion_audit_axis"]["state"] == "NOT_MEASURED"
    assert doc["verdict"] == "NOT_MEASURED", doc["verdict"]


def test_a_scoped_audit_is_not_this_runs_axis(project):
    """THE MEDIUM: who wrote the audit, over what population. R-0915-147 gives the
    document a scope, so a phase-2-scoped audit or a pre-Step-29 snapshot is no
    longer accepted as the phase2/3 axis."""
    _audit(project, "PASS", scope={"whole_flow": False, "step_count": 13,
                                   "flow_step_total": 70, "stage_id": "stage2"})
    axis = V._completion_audit_axis(project, phase3_ran=True, started_at=0.0)
    assert axis["state"] == "NOT_MEASURED", axis
    assert "13 of 70" in axis["reason"], axis["reason"]


def test_a_whole_flow_fresh_audit_is_the_axis(project):
    """THE OTHER DIRECTION: the document that IS this run's whole-flow audit is
    accepted, and says which signal established that."""
    _audit(project, "PASS", scope=dict(WHOLE))
    axis = V._completion_audit_axis(project, phase3_ran=True, started_at=0.0)
    assert axis["state"] == "PASS", axis
    assert axis["scope_signal"] == "scope.whole_flow"
    assert axis["sources"][0]["verdict"] == "PASS"


def test_an_audit_without_a_scope_block_is_taken_on_the_weaker_signal(project):
    """A document predating R-0915-147 cannot state its population. It is accepted
    only on `phase == "all"` AND the weaker signal is DISCLOSED, because a weak
    signal read silently is the same mistake in a quieter voice."""
    _audit(project, "PASS", phase="all")
    axis = V._completion_audit_axis(project, phase3_ran=True, started_at=0.0)
    assert axis["state"] == "PASS", axis
    assert "weaker signal" in axis["scope_signal"], axis["scope_signal"]
    _audit(project, "PASS", phase="2")
    axis2 = V._completion_audit_axis(project, phase3_ran=True, started_at=0.0)
    assert axis2["state"] == "NOT_MEASURED", axis2


def test_a_phase_that_left_no_report_is_not_measured(project, monkeypatch):
    """THE ROW SIDE of the same rule. phase3's `[SKIP] no usable PDK` returns 0
    WITHOUT writing a report, and the front door then read a stale
    phase3_one_shot.json or invented PASS from rc 0 — for a phase that measured
    nothing."""
    def fake_run_phase(label, runner, args, env=None):
        if "phase3" in runner.name:
            return 0                      # rc 0 and NO report, the shipped shape
        for name in ("phase1", "phase2"):
            if name in runner.name:
                _report(project, f"{name}_one_shot.json", {"verdict": "PASS"})
        return 0

    monkeypatch.setattr(V, "_run_phase", fake_run_phase)
    monkeypatch.setattr(V, "_phase1_decision", lambda *a, **k: (True, "docs"))
    monkeypatch.setattr(sys, "argv", ["vibe_ic_one_shot_runner", str(project),
                                      "--no-dashboard", "--skip-hardware"])
    real_entry('IC', 'default', project)
    rc = V.main()
    doc = json.loads(_pl.report_path(project, "vibe_ic_one_shot.json").read_text())
    rows = {r["name"]: r["verdict"] for r in doc["phases"]}
    assert rows["phase3"] == "NOT_MEASURED", (rows, doc["verdict"])
    assert doc["verdict"] == "NOT_MEASURED" and rc == 1
    assert any("left no phase3_one_shot.json" in a for a in doc["advisories"]), (
        doc["advisories"])


def test_a_stale_phase_report_is_not_this_runs_row(project, monkeypatch):
    """And a report from an EARLIER run does not become this phase's verdict."""
    import os
    stale = _report(project, "phase3_one_shot.json", {"verdict": "PASS"})
    old = os.stat(stale).st_mtime_ns - 10 ** 10
    os.utime(stale, ns=(old, old))

    def fake_run_phase(label, runner, args, env=None):
        if "phase3" in runner.name:
            return 0                      # leaves the stale report in place
        for name in ("phase1", "phase2"):
            if name in runner.name:
                _report(project, f"{name}_one_shot.json", {"verdict": "PASS"})
        return 0

    monkeypatch.setattr(V, "_run_phase", fake_run_phase)
    monkeypatch.setattr(V, "_phase1_decision", lambda *a, **k: (True, "docs"))
    monkeypatch.setattr(sys, "argv", ["vibe_ic_one_shot_runner", str(project),
                                      "--no-dashboard", "--skip-hardware"])
    real_entry('IC', 'default', project)
    V.main()
    doc = json.loads(_pl.report_path(project, "vibe_ic_one_shot.json").read_text())
    rows = {r["name"]: r["verdict"] for r in doc["phases"]}
    assert rows["phase3"] == "NOT_MEASURED", rows
    assert any("predates phase3's start" in a for a in doc["advisories"]), (
        doc["advisories"])


def test_a_stale_coverage_sidecar_does_not_demote(project, monkeypatch):
    """M/L: my H1 exemption rests on `_phase1_failure_is_coverage_only`, whose
    sidecar is not tied to this invocation and is written BEFORE three later
    non-coverage blocking returns. A stale sidecar must not demote a phase1 FAIL."""
    import os
    side = _pl.coverage_only_sidecar_path(project)
    side.parent.mkdir(parents=True, exist_ok=True)
    side.write_text(json.dumps({"coverage_only_failure": True,
                                "coverage_pct": 71.0, "total_todo": 0}) + "\n")
    old = os.stat(side).st_mtime_ns - 10 ** 10
    os.utime(side, ns=(old, old))

    rc, doc = _drive_main(project, monkeypatch,
                          phase1=("FAIL", 1, None), phase2=("PASS", 0),
                          extra_argv=("--skip-phase3",))
    assert doc["demoted_phases"] == {}, doc["demoted_phases"]
    assert doc["verdict"] == "FAIL" and rc == 1
    assert any("predates phase1's start" in a for a in doc["advisories"]), (
        doc["advisories"])


def test_only_rc_1_is_exempt_from_the_demotion(project, monkeypatch):
    """The coverage-only path returns rc 1. Any other rc is a different failure, and
    a fresh sidecar does not make it one."""
    rc, doc = _drive_main(
        project, monkeypatch,
        phase1=("FAIL", 2, {"coverage_only_failure": True, "coverage_pct": 71.0,
                            "total_todo": 0}),
        phase2=("PASS", 0), extra_argv=("--skip-phase3",))
    assert doc["demoted_phases"] == {}, doc["demoted_phases"]
    assert doc["verdict"] == "FAIL" and rc == 1
    assert any("not the rc the" in a for a in doc["advisories"]), doc["advisories"]


def test_a_blocking_return_the_classifier_did_not_classify_drops_the_sidecar():
    """THE OTHER HALF OF THE DEMOTION, in phase1's own runner.

    The sidecar is written BEFORE three later blocking returns — the L8 clock-period
    conflict, the extraction gap, the semantic layer gates — and its classifier knows
    nothing about any of them. All three `return 1`, the same rc the coverage-only path
    returns, so no reader can separate them by exit code: the #505 demotion would take
    a NON-coverage phase1 failure and publish PASS_WITH_WAIVERS at exit 0. My rc==1
    guard alone does NOT close that, which is why this half is here.

    Each of those returns now removes the sidecar it would otherwise leave. Pinned by
    AST on the call, and by position: the drop must precede the return it guards.
    """
    import ast
    src = (PROGRAMS / "phase1_doc_one_shot_runner.py").read_text()
    assert src.count("_drop_v0_3_7_exit_reason(project)") >= 3, (
        "fewer than three unclassified blocking returns drop the sidecar")
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef)
              and n.name == "_drop_v0_3_7_exit_reason")
    assert "unlink" in ast.unparse(fn), "the drop does not remove anything"
    # every drop sits immediately before a `return 1`, never after it
    lines = src.splitlines()
    for i, line in enumerate(lines):
        if "_drop_v0_3_7_exit_reason(project)" in line and "def " not in line:
            nxt = next((l.strip() for l in lines[i + 1:i + 3] if l.strip()), "")
            assert nxt.startswith("return"), (i + 1, nxt)


def test_phase1s_report_is_read_where_its_producer_writes(project, monkeypatch):
    """THE ARM THAT WOULD HAVE CAUGHT MY ROUND-3 REGRESSION, now against ONE definition.

    Round 3: `_pl.report_path` routed to `reports/orchestrator/` while phase1's runner
    wrote `reports/phase1_one_shot.json`, so EVERY phase1-inclusive run came out
    NOT_MEASURED at exit 1 -- and a real phase1 FAIL became NOT_MEASURED, so the halt never
    fired and phase2/3 ran on bad L documents. My first fix taught the READER both
    locations, which added a fifth answer to a question that already had four. The producer
    now resolves through the router, so this stages the report the way the producer does --
    through that same call -- and requires the row to be the verdict in it.
    """
    def fake_run_phase(label, runner, args, env=None):
        if "phase1" in runner.name:
            # the producer's own resolution, which is now the router's
            _report(project, "phase1_one_shot.json", {"verdict": "PASS"})
            return 0
        if "phase2" in runner.name:
            _report(project, "phase2_one_shot.json", {"verdict": "PASS"})
            return 0
        return 0

    monkeypatch.setattr(V, "_run_phase", fake_run_phase)
    monkeypatch.setattr(V, "_phase1_decision", lambda *a, **k: (True, "docs"))
    monkeypatch.setattr(sys, "argv", ["vibe_ic_one_shot_runner", str(project),
                                      "--no-dashboard", "--skip-hardware",
                                      "--skip-phase3"])
    real_entry('IC', 'default', project)
    rc = V.main()
    doc = json.loads(_pl.report_path(project, "vibe_ic_one_shot.json").read_text())
    rows = {r["name"]: r["verdict"] for r in doc["phases"]}
    assert rows["phase1"] == "PASS", (rows, doc["verdict"], doc["advisories"])
    assert doc["verdict"] == "PASS" and rc == 0, (doc["verdict"], doc["verdict_reasons"])


def test_the_reader_has_exactly_one_definition_of_where_a_report_lives(project):
    """One call to the router, for every phase, and NO second location.

    The arm is about what the reader does NOT do: a report staged at the unsanctioned flat
    path must not be found, because finding it is what let the two layouts coexist. All
    three `*_one_shot.json` names are categorised `orchestrator` by `_path_layout`, so the
    reader needs no per-phase knowledge at all.
    """
    for name in ("phase1_one_shot.json", "phase2_one_shot.json", "phase3_one_shot.json"):
        assert V._phase_report_path(project, name) == _pl.report_path(project, name), name

    # a file at the flat path is NOT what the reader resolves to, even when it is the only
    # one present and the routed one does not exist
    flat = project / "reports" / "phase1_one_shot.json"
    flat.parent.mkdir(parents=True, exist_ok=True)
    flat.write_text(json.dumps({"verdict": "PASS"}) + "\n")
    resolved = V._phase_report_path(project, "phase1_one_shot.json")
    assert resolved != flat, (
        "the reader still knows a second location; that is what made four answers")
    assert not resolved.is_file()

    # and the resolver reads nothing off the disk, so a newer stale file cannot win it
    import inspect
    src = inspect.getsource(V._phase_report_path)
    for forbidden in ("st_mtime", "is_file", "exists("):
        assert forbidden not in src, (
            f"`_phase_report_path` consults the filesystem ({forbidden}); a path resolver "
            f"that picks by mtime can prefer a stale file from another location")


def test_phase1s_producer_resolves_its_report_through_the_router():
    """The premise, pinned against the producer itself, in BOTH directions.

    No flat write may remain, and every write of this report must go through the router --
    so if anyone reintroduces `reports / "phase1_one_shot.json"`, this arm says so instead
    of the front door silently reading a path nothing writes again.
    """
    import ast
    src = (PROGRAMS / "phase1_one_shot_runner.py").read_text()
    assert 'reports / "phase1_one_shot.json"' not in src, (
        "phase1's runner writes the flat path again; `reports_subfolder_taxonomy_check` "
        "FAILS on that location and the front door resolves only the router's")

    tree = ast.parse(src)
    routed = 0
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "report_path"
                and any(isinstance(a, ast.Constant) and a.value == "phase1_one_shot.json"
                        for a in node.args)):
            routed += 1
    assert routed >= 3, (
        f"only {routed} of phase1's writes of this report resolve through the router; "
        f"measured, the runner has three write sites")


def test_the_sanctioned_location_is_the_one_the_taxonomy_gate_accepts(tmp_path):
    """WHY the router's answer is the sanctioned one, driven through the shipped gate.

    Not an appeal to the router's own table: `reports_subfolder_taxonomy_check` is run over
    both layouts and only one of them passes. If the doctrine ever changes, this arm changes
    with it instead of the claim quietly going stale.
    """
    import subprocess

    def strays(rel: str) -> str:
        proj = tmp_path / rel.replace("/", "_")
        f = proj / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps({"verdict": "PASS"}) + "\n")
        r = subprocess.run(
            [sys.executable, str(PROGRAMS / "reports_subfolder_taxonomy_check.py"),
             str(proj)], capture_output=True, text=True, timeout=300)
        return r.stdout + r.stderr

    assert "phase1_one_shot.json" in strays("reports/phase1_one_shot.json"), (
        "the flat location is no longer reported as a stray file; re-measure which layout "
        "the doctrine sanctions before trusting the router")
    assert "phase1_one_shot.json" not in strays(
        "reports/orchestrator/phase1_one_shot.json")


# ── the round-2 M, now that 70 sits on 77 ────────────────────────────────────

def test_a_scoped_audit_written_by_the_real_auditor_is_refused(tmp_path):
    """THE ROUND-2 M, closed against a document the REAL auditor wrote.

    My round-2 reader accepted an audit on the weak `phase == "all"` signal, because that
    was the only signal there was: `flow_compliance_check` stamped every receipt
    `phase: "all"` whatever `--stage` said, so a stage-scoped audit was indistinguishable
    from the whole run's. R-0915-147 gave the document a `scope` block, and this asserts
    the front door refuses a scoped one — driven by RUNNING a scoped pass, not by a
    hand-built fixture, because the premise under test is what that program actually
    writes.

    MEASURED here: `flow_compliance_check . --stage-id stage_phase1` publishes the
    canonical audit with `scope.whole_flow=false, step_count=2, flow_step_total=70`.
    """
    import subprocess
    import time

    project = tmp_path / "proj"
    (project / "input").mkdir(parents=True)
    (project / "input" / "spec.md").write_text("# a counter\n")

    started_at = time.time()
    time.sleep(0.05)                       # the audit must land at or after the start
    subprocess.run(
        [sys.executable, str(PROGRAMS / "flow_compliance_check.py"), str(project),
         "--stage-id", "stage_phase1"],
        capture_output=True, text=True, cwd=str(project), timeout=900)

    audit = _pl.report_path(project, "phase23_completion_audit.json")
    assert audit.is_file(), "the scoped pass wrote no canonical audit to refuse"
    doc = json.loads(audit.read_text())
    assert doc["scope"]["whole_flow"] is False, doc["scope"]
    assert doc["scope"]["step_count"] < doc["scope"]["flow_step_total"], doc["scope"]

    axis = V._completion_audit_axis(project, phase3_ran=True, started_at=started_at)

    assert axis["state"] == "NOT_MEASURED", axis
    assert axis["sources"] == [], axis
    assert axis["scope_signal"] == _audit_scope.SIGNAL_SCOPE, axis
    assert str(doc["scope"]["step_count"]) in axis["reason"], axis["reason"]
    assert str(doc["scope"]["flow_step_total"]) in axis["reason"], axis["reason"]


def test_the_front_door_refuses_a_scoped_audit_the_same_way_the_other_readers_do():
    """ONE definition, not four. The front door must not be able to disagree with
    `benchmark_evidence_publish`, `phase3_one_shot_runner` and the pre-burn guard about
    what an audit judged — so it calls the same predicate, and this pins that it does.
    """
    import ast
    import inspect
    import textwrap

    src = textwrap.dedent(inspect.getsource(V._completion_audit_axis))
    fn = ast.parse(src).body[0]
    assert "_audit_scope.audit_scope_is_whole_flow" in src, (
        "the front door decides the audit's population by its own copy of the rule")

    # CODE ONLY. The docstring explains the rule at length and must go on doing so -- it is
    # the prose a reviewer reads. What must not exist is a SECOND READING of the block: the
    # comment-and-docstring text is stripped and the remaining statements are checked.
    body = [n for n in fn.body
            if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)
                    and isinstance(n.value.value, str))]
    code = ast.unparse(ast.Module(body=body, type_ignores=[]))
    # the CALL to the shared predicate is the one mention that must remain
    code = code.replace("_audit_scope.audit_scope_is_whole_flow", "<the one predicate>")
    assert "whole_flow" not in code, (
        "a second reading of `scope.whole_flow` is still in this reader's code")
    assert "'scope'" not in code and '"scope"' not in code, (
        "the reader still reaches into the audit's scope block itself")

    # and the predicate really is the one the other readers use
    for consumer in ("benchmark_evidence_publish.py", "phase3_one_shot_runner.py"):
        text = (PROGRAMS / consumer).read_text(errors="replace")
        assert "audit_scope_is_whole_flow" in text, consumer


def test_a_whole_flow_audit_from_the_real_auditor_is_still_accepted(tmp_path):
    """The other direction, so the arm above is not satisfied by refusing everything."""
    project = tmp_path / "proj"
    audit = _pl.report_path(project, "phase23_completion_audit.json")
    audit.parent.mkdir(parents=True, exist_ok=True)
    # the shape a whole-flow pass publishes, with the scope block R-0915-147 added
    audit.write_text(json.dumps({
        "verdict": "PASS",
        "scope": {"phase": "all", "stage": None, "stage_id": None,
                  "step_count": 70, "flow_step_total": 70, "whole_flow": True},
    }) + "\n")
    axis = V._completion_audit_axis(project, phase3_ran=True, started_at=0.0)
    assert axis["state"] != "NOT_MEASURED", axis
    assert axis["sources"] and axis["sources"][0]["verdict"] == "PASS", axis
    assert axis["scope_signal"] == _audit_scope.SIGNAL_SCOPE, axis


def test_a_legacy_audit_with_no_scope_block_is_accepted_but_disclosed(tmp_path):
    """The weaker signal is still usable — and says so, in the predicate's own words."""
    project = tmp_path / "proj"
    audit = _pl.report_path(project, "phase23_completion_audit.json")
    audit.parent.mkdir(parents=True, exist_ok=True)
    audit.write_text(json.dumps({"verdict": "PASS", "phase": "all"}) + "\n")
    axis = V._completion_audit_axis(project, phase3_ran=True, started_at=0.0)
    assert axis["state"] != "NOT_MEASURED", axis
    assert axis["scope_signal"] == _audit_scope.SIGNAL_LEGACY_PHASE, axis
    assert "weaker signal" in axis["scope_signal"]


# ── a phase whose PROCESS failed and left no report ──────────────────────────

def test_a_phase_whose_process_failed_with_no_report_is_a_fail_and_halts(project,
                                                                        monkeypatch):
    """R-0915-160. My round-3 rule silenced the only witness there was.

    "rc is an exit status, not a measurement" is right for rc == 0 -- phase3's
    `[SKIP] no usable PDK` exits 0 without writing anything, and a PASS conjured from that is
    a claim nobody made. For rc != 0 it is the mirror of the defect it was closing: the
    process DID tell us something, and NOT_MEASURED does not halt, so phase 2 and 3 ran on
    oracle-contaminated L documents. phase1's oracle-leak guard exits `SystemExit(2)` and
    writes no report; so does any traceback.
    """
    def fake_run_phase(label, runner, args, env=None):
        if "phase1" in runner.name:
            return 2                       # the leak guard's exit; NO report written
        _report(project, "phase2_one_shot.json", {"verdict": "PASS"})
        return 0

    monkeypatch.setattr(V, "_run_phase", fake_run_phase)
    monkeypatch.setattr(V, "_phase1_decision", lambda *a, **k: (True, "docs"))
    monkeypatch.setattr(sys, "argv", ["vibe_ic_one_shot_runner", str(project),
                                      "--no-dashboard", "--skip-hardware",
                                      "--skip-phase3"])
    real_entry('IC', 'default', project)
    rc = V.main()

    doc = json.loads(_pl.report_path(project, "vibe_ic_one_shot.json").read_text())
    rows = {r["name"]: r["verdict"] for r in doc["phases"]}
    assert rows.get("phase1") == "FAIL", (rows, doc.get("advisories"))
    assert doc["verdict"] != "PASS" and rc != 0, (doc["verdict"], rc)
    assert doc.get("halted_at") == "phase1", (
        f"the run did not halt at phase1, so phase 2/3 would build on whatever phase 1 "
        f"left behind: halted_at={doc.get('halted_at')!r}")
    # phase 2 must not even appear as having been measured
    assert rows.get("phase2") in (None, "NOT_RUN", "SKIPPED"), rows


def test_a_phase_that_exited_zero_with_no_report_is_still_not_measured(project,
                                                                      monkeypatch):
    """The half that must NOT move: rc 0 and no report is an absence, not a pass."""
    def fake_run_phase(label, runner, args, env=None):
        if "phase1" in runner.name:
            _report(project, "phase1_one_shot.json", {"verdict": "PASS"})
            return 0
        return 0                            # phase2 exits 0 and writes NOTHING

    monkeypatch.setattr(V, "_run_phase", fake_run_phase)
    monkeypatch.setattr(V, "_phase1_decision", lambda *a, **k: (True, "docs"))
    monkeypatch.setattr(sys, "argv", ["vibe_ic_one_shot_runner", str(project),
                                      "--no-dashboard", "--skip-hardware",
                                      "--skip-phase3"])
    real_entry('IC', 'default', project)
    rc = V.main()

    doc = json.loads(_pl.report_path(project, "vibe_ic_one_shot.json").read_text())
    rows = {r["name"]: r["verdict"] for r in doc["phases"]}
    assert rows.get("phase2") == "NOT_MEASURED", rows
    assert doc["verdict"] != "PASS" and rc != 0, (doc["verdict"], rc)


def test_the_split_turns_on_the_exit_status_and_nothing_else(project):
    """Driven directly, both sides, with the report absent in both."""
    import time
    now = time.time()
    assert V._row_verdict(project, "phase1_one_shot.json", 0, now, "phase1")[0] \
        == "NOT_MEASURED"
    for rc in (1, 2, 137):
        verdict, why = V._row_verdict(project, "phase1_one_shot.json", rc, now, "phase1")
        assert verdict == "FAIL", (rc, verdict)
        assert str(rc) in why, (rc, why)

    # and a report that IS there outranks the exit status -- the phase's own account
    f = _pl.report_path(project, "phase1_one_shot.json")
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({"verdict": "PASS"}) + "\n")
    assert V._row_verdict(project, "phase1_one_shot.json", 2, 0.0, "phase1")[0] == "PASS"


# ── the RE-RUN cases (R-0915-160 second cut) ─────────────────────────────────

def _stale(path: Path, payload: dict, age_s: float = 9999.0) -> Path:
    """A report on disk from an EARLIER run: written, then back-dated."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload) + "\n")
    old = time.time() - age_s
    os.utime(path, (old, old))
    return path


def test_a_phase_that_crashed_over_a_stale_report_is_a_fail_and_halts(project,
                                                                     monkeypatch):
    """(1) THE RE-RUN CASE, and the one that matters most.

    R-0915-151 moved phase 1's producer onto the routed path this reader reads, so on EVERY
    re-run a report is already sitting there. A phase-1 crash after the L documents are written --
    the oracle-leak `SystemExit(2)`, or a killed expert second pass at rc 137 -- then found the
    file present and stale, and my first cut answered NOT_MEASURED while ignoring rc. NOT_MEASURED
    does not halt, so phases 2 and 3 ran on oracle-contaminated documents.
    """
    _stale(_pl.report_path(project, "phase1_one_shot.json"),
           {"verdict": "PASS", "from": "an earlier run"})

    def fake_run_phase(label, runner, args, env=None):
        if "phase1" in runner.name:
            return 2                       # the leak guard's exit; writes nothing NEW
        _report(project, "phase2_one_shot.json", {"verdict": "PASS"})
        return 0

    monkeypatch.setattr(V, "_run_phase", fake_run_phase)
    monkeypatch.setattr(V, "_phase1_decision", lambda *a, **k: (True, "docs"))
    monkeypatch.setattr(sys, "argv", ["vibe_ic_one_shot_runner", str(project),
                                      "--no-dashboard", "--skip-hardware",
                                      "--skip-phase3"])
    real_entry('IC', 'default', project)
    rc = V.main()
    doc = json.loads(_pl.report_path(project, "vibe_ic_one_shot.json").read_text())
    rows = {r["name"]: r["verdict"] for r in doc["phases"]}

    assert rows.get("phase1") == "FAIL", (rows, doc.get("advisories"))
    assert doc.get("halted_at") == "phase1", (
        f"the run did not halt, so phases 2/3 would build on whatever phase 1 left: "
        f"halted_at={doc.get('halted_at')!r}")
    assert rc != 0
    # and the stale report's verdict was never read
    assert doc["verdict"] != "PASS", doc["verdict"]
    assert rows.get("phase2") in (None, "NOT_RUN", "SKIPPED"), rows


@pytest.mark.parametrize("rc", [1, 2, 3, 137])
def test_the_class_is_the_same_fresh_or_re_run(project, rc):
    """(1b) ONE CLASS FOR EVERY NON-ZERO rc, INCLUDING THE STALL.

    It used to be FAIL on a fresh project and NOT_MEASURED on a re-run -- two answers to one
    question. MEASURED, every non-zero rc a phase runner in this tree returns is a refusal or an
    error and none is benign: rc 2 is "not a directory", an uncaught exception, or "REFUSED:
    canonical Phase-3 admission"; rc 3 refuses a second concurrent run. So FAIL on both paths.
    """
    now = time.time()
    fresh_answer = V._row_verdict(project, "phase1_one_shot.json", rc, now, "phase1")
    _stale(_pl.report_path(project, "phase1_one_shot.json"), {"verdict": "PASS"})
    rerun_answer = V._row_verdict(project, "phase1_one_shot.json", rc, now, "phase1")

    assert fresh_answer[0] == "FAIL", (rc, fresh_answer)
    assert rerun_answer[0] == "FAIL", (rc, rerun_answer)
    assert str(rc) in (rerun_answer[1] or ""), rerun_answer[1]
    assert "earlier run" in (rerun_answer[1] or ""), rerun_answer[1]


def test_rc_zero_over_a_stale_report_is_still_not_measured(project):
    """The half that must NOT move: exit 0 and no report OF ITS OWN is an absence, not a pass,
    and the stale file's verdict is never read."""
    _stale(_pl.report_path(project, "phase1_one_shot.json"), {"verdict": "PASS"})
    verdict, why = V._row_verdict(project, "phase1_one_shot.json", 0, time.time(), "phase1")
    assert verdict == "NOT_MEASURED", (verdict, why)
    assert "describes an earlier run" in (why or ""), why
    assert "verdict is not read" in (why or ""), why


# ── H5: the AI-backup re-invocation, driven END TO END ──────────────────────
#
# THE DEFECT (review wjn67aev3, MEDIUM #2). The front door may demote a coverage-only phase-1
# FAIL, and for a FIRST pass it decides the sidecar is this invocation's by mtime against the
# phase-1 start. On the expert SECOND pass that is wrong -- the pass carries pass 1's record and
# never rewrites the sidecar -- so the record NAMES the sidecar by content instead.
#
# r7 got the producer half backwards: the second pass named it only when
# `sidecar.mtime >= record.mtime`, while pass 1 writes the sidecar FIRST (in-process, from inside
# D1) and its record LAST. So on every real re-invocation nothing was named, the front door read
# "NOT demoting", and a `--skip-phase3` coverage-only project that was PASS_WITH_WAIVERS flipped
# to FAIL and halted at phase 1.
#
# AND NEITHER HALF'S ARMS COULD SEE IT: the producer fixture staged the sidecar at `record + 10s`,
# the reverse of the real order, and the reader arm asserted source substrings without ever
# calling `main()`. These three arms drive the REAL `main()`, in the REAL write order, with the
# REAL `run_second_pass_only` doing the carrying.

def _sidecar(project: Path) -> Path:
    return _pl.coverage_only_sidecar_path(project)


def _as_pass_one_leaves_it(project: Path, *, age_s: float = 5000.0) -> str:
    """Stage what a completed pass 1 leaves behind, IN THE REAL ORDER, and return the sha it named.

    Sidecar first, record last, both old enough to predate any later invocation's phase-1 start --
    which is exactly the situation the second pass is in and the one the mtime rule got wrong.
    """
    import hashlib
    import os

    import phase1_one_shot_runner as P1

    side = _sidecar(project)
    side.parent.mkdir(parents=True, exist_ok=True)
    side.write_text(json.dumps({"coverage_only_failure": True,
                                "coverage_pct": 71.0, "total_todo": 0}) + "\n")
    sha = hashlib.sha256(side.read_bytes()).hexdigest()

    summary = {"phase": 1, "mode": "docs", "verdict": "FAIL",
               "steps": [{"name": "doc_extract", "status": "FAIL"}]}
    # THE PRODUCER'S OWN CALL, not a hand-written field: if pass 1 stops naming the sidecar, or
    # names it differently, these arms follow it instead of describing a shape nobody writes.
    P1._name_the_sidecar_this_pass_wrote(project, summary, d1_ran=True)
    assert summary.get("pass1_coverage_sidecar", {}).get("sha256") == sha, summary
    _report(project, "phase1_one_shot.json", summary)

    then = time.time() - age_s
    os.utime(side, (then, then))                                  # sidecar first ...
    record = _pl.report_path(project, "phase1_one_shot.json")
    os.utime(record, (then + 10, then + 10))                      # ... record last
    assert side.stat().st_mtime < record.stat().st_mtime, (
        "the fixture must stage the REAL order, or it reproduces nothing")
    return sha


def _drive_second_pass(project: Path, monkeypatch, *, extra_argv=()) -> tuple:
    """`main()` where phase 1 is the REAL `run_second_pass_only`.

    Only the expert consumption and the steps view are stubbed -- the two things that would need a
    delivered subagent answer and a full step tree. The carrying, the naming and every line of the
    front door's demotion branch are the shipped ones.
    """
    import phase1_one_shot_runner as P1

    monkeypatch.setattr(P1._pl, "emit_steps_view", lambda *a, **k: {"stubbed": True},
                        raising=False)
    monkeypatch.setattr(P1, "_consume_expert_answer",
                        lambda *a, **k: (0, {"consumed": True}), raising=False)

    def fake_run_phase(label, runner, args, env=None):
        if "phase1" in runner.name:
            return P1.run_second_pass_only(project, "zzdie", route="ic")
        if "phase2" in runner.name:
            _report(project, "phase2_one_shot.json", {"verdict": "PASS"})
            return 0
        return 0

    monkeypatch.setattr(V, "_run_phase", fake_run_phase)
    monkeypatch.setattr(V, "_phase1_decision", lambda *a, **k: (True, "docs"))
    monkeypatch.setattr(sys, "argv",
                        ["vibe_ic_one_shot_runner", str(project),
                         "--no-dashboard", "--skip-hardware", "--skip-phase3", *extra_argv])
    real_entry('IC', 'default', project)
    rc = V.main()
    out = _pl.report_path(project, "vibe_ic_one_shot.json")
    return rc, json.loads(out.read_text())


def test_invocation_a_demotes_on_a_sidecar_this_pass_wrote(project, monkeypatch):
    """INVOCATION A. A first pass writes the sidecar in this invocation, so the front door's own
    freshness rule carries the demotion. The baseline the re-invocation must not lose."""
    rc, doc = _drive_main(
        project, monkeypatch,
        phase1=("FAIL", 1, {"coverage_only_failure": True,
                            "coverage_pct": 71.0, "total_todo": 0}),
        phase2=("PASS", 0),
        extra_argv=("--skip-phase3",))
    assert doc["verdict"] == "PASS_WITH_WAIVERS", (doc["verdict"], doc.get("verdict_reasons"))
    assert rc == 0, rc
    assert doc["demoted_phases"]["phase1"]["token"] == V.DEMOTION_COVERAGE_ONLY


def test_invocation_b_second_pass_still_demotes(project, monkeypatch):
    """INVOCATION B, THE REGRESSION. The same project, re-entered as the expert second pass: the
    sidecar now predates this invocation's phase-1 start by an hour and a half, and what makes it
    trustworthy is that the carried record names it by content.

    At r7 this exits 1 with verdict FAIL and the advisory 'NOT demoting', because the carried
    record named nothing."""
    _as_pass_one_leaves_it(project)
    rc, doc = _drive_second_pass(project, monkeypatch)

    assert doc["verdict"] == "PASS_WITH_WAIVERS", (
        doc["verdict"], doc.get("verdict_reasons"),
        [a for a in doc.get("advisories", []) if "sidecar" in a])
    assert rc == 0, rc
    assert doc["demoted_phases"]["phase1"]["token"] == V.DEMOTION_COVERAGE_ONLY
    assert any("names it by content" in a for a in doc.get("advisories", [])), (
        doc.get("advisories"))
    assert not any("NOT demoting" in a for a in doc.get("advisories", [])), (
        doc.get("advisories"))


def test_a_sidecar_swapped_after_pass_one_named_it_is_refused(project, monkeypatch):
    """THE NEGATIVE CONTROL, and the reason the name is a DIGEST and not a path. Pass 1 named one
    set of bytes; something replaced them afterwards. The carried name no longer matches, so the
    demotion is refused and the run halts at phase 1 as it should."""
    sha = _as_pass_one_leaves_it(project)
    side = _sidecar(project)
    then = side.stat().st_mtime
    side.write_text(json.dumps({"coverage_only_failure": True, "swapped": True}) + "\n")
    # THE ARM HAS TO CLOSE THE OTHER ROUTE, and my first cut did not. The front door has TWO ways
    # to accept a sidecar: this invocation's phase-1 start (by mtime) OR the carried record's name
    # (by digest). Writing the bytes moved the mtime to now, and `main()` starts milliseconds
    # later, so `_FRESHNESS_TOLERANCE_S` legitimately made the swapped file "this invocation's" --
    # the run demoted, and the arm was measuring the mtime route while claiming to measure the
    # digest. Back-dated so the DIGEST is the only thing that could authorise it.
    os.utime(side, (then, then))
    import hashlib
    assert hashlib.sha256(side.read_bytes()).hexdigest() != sha
    assert side.stat().st_mtime < time.time() - 100, (
        "the swapped sidecar must still look old, or the mtime route decides this arm")

    rc, doc = _drive_second_pass(project, monkeypatch)
    assert doc["verdict"] == "FAIL", (doc["verdict"], doc.get("verdict_reasons"))
    assert rc == 1, rc
    assert doc.get("demoted_phases") == {}, doc.get("demoted_phases")
    assert any("NOT demoting" in a for a in doc.get("advisories", [])), doc.get("advisories")


def test_a_crashed_phase_one_cannot_borrow_an_earlier_runs_naming(project, monkeypatch):
    """THE HOLE r8 OPENED, and the one this round closes (review wkevxl71c).

    Invocation A left a fresh pass-1 record naming the sidecar it wrote, and the front door demoted
    on it -- correctly. Invocation B, on the same tree: phase 1 dies on an uncaught exception, exits
    1 and publishes NO record. `_row_verdict` says FAIL, which halts. But the #505 branch read the
    record still on disk -- A's -- found its name matching the untouched sidecar, saw rc == 1, and
    DEMOTED: phase 2 ran and the roll-up could publish PASS_WITH_WAIVERS for a run whose phase 1
    had crashed. A stale record must never authorise a demotion, whatever it names.
    """
    _as_pass_one_leaves_it(project)                     # invocation A's leftovers

    def crashed_phase1(label, runner, args, env=None):
        if "phase1" in runner.name:
            return 1                                    # exits 1, writes nothing
        if "phase2" in runner.name:
            _report(project, "phase2_one_shot.json", {"verdict": "PASS"})
            return 0
        return 0

    monkeypatch.setattr(V, "_run_phase", crashed_phase1)
    monkeypatch.setattr(V, "_phase1_decision", lambda *a, **k: (True, "docs"))
    monkeypatch.setattr(sys, "argv",
                        ["vibe_ic_one_shot_runner", str(project),
                         "--no-dashboard", "--skip-hardware", "--skip-phase3"])
    real_entry('IC', 'default', project)
    rc = V.main()
    doc = json.loads(_pl.report_path(project, "vibe_ic_one_shot.json").read_text())

    assert doc["verdict"] == "FAIL", (
        f"a run whose phase 1 crashed and published nothing was demoted on an EARLIER run's "
        f"naming: {doc['verdict']} / {doc.get('verdict_reasons')} / "
        f"{[a for a in doc.get('advisories', []) if 'sidecar' in a or 'earlier run' in a]}")
    assert rc == 1, rc
    assert doc.get("demoted_phases") == {}, doc.get("demoted_phases")
    assert any("belongs to an earlier run" in a for a in doc.get("advisories", [])), (
        doc.get("advisories"))
    # and the demotion route said so too, rather than falling silent
    assert any("NOT demoting" in a for a in doc.get("advisories", [])), doc.get("advisories")


def test_a_first_pass_that_crashes_after_writing_the_sidecar_is_not_demoted(
        project, monkeypatch):
    """THE SIBLING ON THE MTIME ROUTE (review w3nppqdpn), which r9 left open.

    A FIRST pass, nothing stale anywhere: D1 writes a fresh coverage-only sidecar, and the pass then
    dies before publishing its record -- `_run_expert_track` raising, or the record write itself.
    rc 1, NO record, and `_side_fresh` is True from the sidecar's own mtime, so r9's check (which
    sat on the carried-name route, reached only when the sidecar is NOT fresh) was never asked. The
    run demoted and phase 2 ran on a phase 1 that had crashed.

    `_drive_main` cannot express this: its fake always writes a record. That is the whole point of
    the case, so the fake here writes the sidecar and nothing else.
    """
    def crashes_after_the_sidecar(label, runner, args, env=None):
        if "phase1" in runner.name:
            side = _sidecar(project)
            side.parent.mkdir(parents=True, exist_ok=True)
            side.write_text(json.dumps({"coverage_only_failure": True,
                                        "coverage_pct": 71.0, "total_todo": 0}) + "\n")
            return 1                                    # ... and then it dies. No record.
        if "phase2" in runner.name:
            _report(project, "phase2_one_shot.json", {"verdict": "PASS"})
            return 0
        return 0

    monkeypatch.setattr(V, "_run_phase", crashes_after_the_sidecar)
    monkeypatch.setattr(V, "_phase1_decision", lambda *a, **k: (True, "docs"))
    monkeypatch.setattr(sys, "argv",
                        ["vibe_ic_one_shot_runner", str(project),
                         "--no-dashboard", "--skip-hardware", "--skip-phase3"])
    real_entry('IC', 'default', project)
    rc = V.main()
    doc = json.loads(_pl.report_path(project, "vibe_ic_one_shot.json").read_text())

    # the premise: the sidecar really is fresh, so the mtime route really was open
    assert _sidecar(project).is_file()
    assert not _pl.report_path(project, "phase1_one_shot.json").is_file(), (
        "the arm must leave phase 1 with NO record; a record makes this a different case")

    assert doc["verdict"] == "FAIL", (
        f"a phase 1 that crashed before publishing its record was demoted on its own fresh "
        f"sidecar: {doc['verdict']} / {doc.get('verdict_reasons')}")
    assert rc == 1, rc
    assert doc.get("demoted_phases") == {}, doc.get("demoted_phases")
    assert any("published NO record in this invocation" in a
               for a in doc.get("advisories", [])), doc.get("advisories")
    # and it is NOT excused as "the record belongs to an earlier run" -- there is no record at all
    assert not any("belongs to an earlier run" in a for a in doc.get("advisories", [])), (
        doc.get("advisories"))


# #3168 — the bounded publisher writes a token-scoped terminal account. Drive
# BOTH real main branches; stage only external execution/admission boundaries.
def _drive_bounded_phase3_receiver(front, project, monkeypatch, *, route="entry",
                                  child_document=None, child_rc=0,
                                  canonical_bytes=None, parent_token=None,
                                  published_token=None, report_mtime=None,
                                  phase_clock=None):
    """Reusable receiver replay, compatible with base and candidate main().

    `child_document(token)` returns bytes, or None to publish nothing. A caller
    may feed unchanged historical sender bytes and control token/clock/mtime:
    that proves receiver behavior, never new native execution. No new product
    helper is called here, so a base reversal fails on values, not a missing API.
    Use only an owned temporary project; admission and image I/O are fixtures.
    """
    from types import SimpleNamespace
    import secrets

    project = Path(project)
    project.mkdir(parents=True, exist_ok=True)
    stage_owner_route(project, "ic")
    monkeypatch.setattr(front, "_configure_execution_policy",
                        lambda _args: {"mode": "default"})
    monkeypatch.setattr(front, "_capture_container_image",
                        lambda *_args: {"verdict": "PASS",
                                         "scope": "SOURCE_CONTROL: image I/O fixture"})
    monkeypatch.setattr(front._canonical_admission, "admit_span", lambda *a, **k:
                        SimpleNamespace(admitted=True, identity_sha256="source-control"))
    monkeypatch.setattr(front._canonical_admission, "child_env",
                        lambda _identity, env: dict(env))
    monkeypatch.setattr(front, "_phase1_decision", lambda *a, **k: (True, "docs"))
    if parent_token is not None:
        monkeypatch.setattr(secrets, "token_hex", lambda _n: parent_token)
    if phase_clock is not None:
        monkeypatch.setattr(front.time, "time", lambda: phase_clock)
    monkeypatch.delenv("VIBEIC_RUNNER_INVOCATION_CONTEXT", raising=False)
    trace = []
    published = {}

    def child(label, runner, args, env=None):
        trace.append({"label": label, "runner": str(runner), "argv": args})
        if runner.name in ("phase1_one_shot_runner.py", "phase2_one_shot_runner.py",
                           "design_one_shot_runner.py"):
            name = ("phase1_one_shot.json" if runner.name.startswith("phase1")
                    else "phase2_one_shot.json")
            p = _pl.report_path(project, name)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text('{"verdict":"PASS","scope":"SOURCE_CONTROL child fixture"}\n')
            return 0
        if runner.name == "flow_compliance_check.py" and "stage_analog" in args:
            p = Path(args[args.index("--json") + 1])
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text('{"verdict":"PASS","scope":"SOURCE_CONTROL child fixture"}\n')
            return 0
        assert runner.name == "phase3_one_shot_runner.py", trace
        token = env["VIBEIC_PHASE3_WINDOW_RUN_ID"]
        canonical = project / "reports/orchestrator/phase3_one_shot.json"
        canonical.parent.mkdir(parents=True, exist_ok=True)
        canonical.write_bytes(canonical_bytes if canonical_bytes is not None else
                              b'{"program":"phase3_one_shot_runner","record":"in-progress","steps":[]}\n')
        published["canonical_before"] = canonical.read_bytes().hex()
        published["parent_token"] = token
        raw = child_document(token) if child_document is not None else None
        if raw is not None:
            # Publisher contract is staged on disk independently of the reader.
            path = project / "reports/orchestrator/windows" / (published_token or token) / "phase3_one_shot.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            if report_mtime is not None:
                os.utime(path, (report_mtime, report_mtime))
            published["scoped_path"] = str(path)
            published["scoped_before"] = raw.hex()
        return child_rc

    monkeypatch.setattr(front, "_run_phase", child)
    flags = (["--entry-step", "15", "--exit-step", "16"] if route == "entry"
             else ["--exit-step", "16"])
    monkeypatch.setattr(sys, "argv", ["vibe_ic_one_shot_runner", str(project),
                                     "--no-dashboard", "--skip-analog", *flags])
    rc = front.main()
    out = _pl.report_path(project, "vibe_ic_one_shot.json")
    report = json.loads(out.read_text())
    canonical = project / "reports/orchestrator/phase3_one_shot.json"
    published["canonical_after"] = canonical.read_bytes().hex()
    if "scoped_path" in published:
        published["scoped_after"] = Path(published["scoped_path"]).read_bytes().hex()
    observation = {"scope": "SOURCE_CONTROL receiver replay; no native child",
                   "route": route, "rc": rc, "summary": report,
                   "child_rc": child_rc, "trace": trace, "published": published}
    (project / "receiver.observation.json").write_text(
        json.dumps(observation, indent=2) + "\n")
    return observation


def _bounded_terminal(token, *, verdict="PASS", route="entry", stale=True):
    return json.dumps({"program": "phase3_one_shot_runner", "bounded": True,
                       "window_run_id": token,
                       "declared_window": {"entry_step": "15" if route == "entry" else "9",
                                           "exit_step": "16"},
                       "verdict": verdict, "audit_verdict": verdict,
                       "audit_scope": "bounded; full declared gates for selected steps",
                       "stale_downstream": ({"17": {"status": "NOT_MEASURED"}}
                                            if stale else {}),
                       "bounded_disclosures": [{"refresh": "whole-flow", "kind": "skipped"}]
                       }).encode() + b"\n"


@pytest.mark.parametrize("route", ["entry", "forwarded"])
def test_bounded_main_consumes_its_exact_terminal_report(project, monkeypatch, route):
    other = project / "reports/orchestrator/windows/newer-unrelated/phase3_one_shot.json"
    other.parent.mkdir(parents=True)
    other.write_bytes(_bounded_terminal("newer-unrelated", verdict="FAIL"))
    obs = _drive_bounded_phase3_receiver(V, project, monkeypatch, route=route,
        child_document=lambda token: _bounded_terminal(token, route=route))
    doc = obs["summary"]
    assert obs["rc"] == 0, obs
    assert doc["bounded"] is True and doc["dispatched_verdict"] == "PASS", doc
    assert doc["verdict"] == "NOT_MEASURED" and doc["audit_verdict"] == "NOT_MEASURED", doc
    assert doc["stale_downstream"] == {"17": {"status": "NOT_MEASURED"}}, doc
    assert obs["published"]["canonical_before"] == obs["published"]["canonical_after"]
    assert obs["published"]["scoped_before"] == obs["published"]["scoped_after"]
    p3 = next(t for t in obs["trace"] if Path(t["runner"]).name == "phase3_one_shot_runner.py")
    assert p3["argv"][p3["argv"].index("--entry-step") + 1] == ("15" if route == "entry" else "9")


@pytest.mark.parametrize("route", ["entry", "forwarded"])
def test_bounded_main_propagates_terminal_failure(project, monkeypatch, route):
    obs = _drive_bounded_phase3_receiver(V, project, monkeypatch, route=route,
        child_document=lambda token: _bounded_terminal(token, verdict="FAIL", route=route),
        child_rc=1)
    assert obs["rc"] == 1, obs
    assert obs["summary"]["dispatched_verdict"] == "FAIL", obs
    assert obs["summary"]["verdict"] == "FAIL", obs


@pytest.mark.parametrize("route", ["entry", "forwarded"])
@pytest.mark.parametrize("damage", ["missing", "malformed", "nonobject", "wrong-id",
                                     "wrong-directory", "stale", "missing-verdict", "unknown-verdict",
                                     "unbounded-account"])
def test_bounded_main_never_takes_unusable_or_other_terminal_as_dispatch_pass(
        project, monkeypatch, route, damage):
    def sender(token):
        if damage == "missing":
            return None
        if damage == "malformed":
            return b"{"
        if damage == "nonobject":
            return b"[]"
        if damage == "wrong-id":
            return _bounded_terminal("not-this-parent", route=route)
        d = json.loads(_bounded_terminal(token, route=route))
        if damage == "missing-verdict":
            del d["verdict"]
        if damage == "unknown-verdict":
            d["verdict"] = "UNRECOGNIZED"
        if damage == "unbounded-account":
            d["bounded"] = False
        return json.dumps(d).encode()
    obs = _drive_bounded_phase3_receiver(V, project, monkeypatch, route=route,
        child_document=sender,
        published_token="different-window" if damage == "wrong-directory" else None,
        report_mtime=1 if damage == "stale" else None)
    assert obs["summary"].get("dispatched_verdict") != "PASS", obs
    assert next(r for r in obs["summary"]["phases"]
                if r["name"] == "phase3")["verdict"] != "PASS", obs
    assert obs["summary"]["verdict"] != "PASS", obs


@pytest.mark.parametrize("route", ["entry", "forwarded"])
def test_bounded_main_canonical_pass_cannot_replace_its_missing_window(
        project, monkeypatch, route):
    token = "1" * 32
    obs = _drive_bounded_phase3_receiver(V, project, monkeypatch, route=route,
        parent_token=token, canonical_bytes=_bounded_terminal(token, route=route),
        child_document=None)
    assert obs["summary"].get("dispatched_verdict") != "PASS", obs
    assert next(r for r in obs["summary"]["phases"]
                if r["name"] == "phase3")["verdict"] != "PASS", obs
    assert obs["rc"] != 0, obs


@pytest.mark.parametrize("route", ["entry", "forwarded"])
@pytest.mark.parametrize("valid_identity", [True, False], ids=["current", "wrong-id"])
def test_bounded_main_retains_nonzero_child_rc(project, monkeypatch, route, valid_identity):
    obs = _drive_bounded_phase3_receiver(V, project, monkeypatch, route=route,
        child_document=lambda token: _bounded_terminal(
            token if valid_identity else "not-this-parent", route=route), child_rc=7)
    assert obs["rc"] == 7, obs
    phase = next(r for r in obs["summary"]["phases"] if r["name"] == "phase3")
    assert phase["rc"] == 7, phase
    assert phase["verdict"] == ("PASS" if valid_identity else
                                "FAIL" if route == "forwarded" else "NOT_MEASURED"), phase


@pytest.mark.parametrize("canonical,expected", [("PASS", "PASS"), ("FAIL", "FAIL"),
                                                (None, "NOT_MEASURED")])
def test_unbounded_row_still_reads_only_its_canonical_report(project, canonical, expected):
    if canonical is not None:
        _report(project, "phase3_one_shot.json", {"verdict": canonical})
    other = project / "reports/orchestrator/windows/unrelated/phase3_one_shot.json"
    other.parent.mkdir(parents=True)
    other.write_bytes(_bounded_terminal("unrelated", verdict="PASS"))
    # The pre-existing API and no path override: base is fully invocable too.
    verdict, _ = V._row_verdict(project, "phase3_one_shot.json", 0, 0.0,
                               "phase3", _acceptance=[])
    assert verdict == expected


@pytest.mark.parametrize("route", ["entry", "forwarded"])
@pytest.mark.parametrize("consumer_status", ["FAIL", "NOT_MEASURED"])
def test_bounded_terminal_preserves_current_consumer_rejection(
        project, monkeypatch, route, consumer_status):
    """Peer3169 counterexample through real main and real retained consumer."""
    def publish(token):
        _save_complete_acceptance(project, "15", consumer_status,
                                  runner="phase3_one_shot_runner")
        return _bounded_terminal(token, route=route)
    obs = _drive_bounded_phase3_receiver(V, project, monkeypatch, route=route,
                                        child_document=publish)
    assert any(r["id"] == "15" and r["status"] == consumer_status
               for r in V._current_default_acceptance(project, 0)), obs
    phase = next(r for r in obs["summary"]["phases"] if r["name"] == "phase3")
    assert phase["verdict"] == consumer_status, obs
    assert obs["summary"]["dispatched_verdict"] == consumer_status, obs
    assert obs["rc"] != 0, obs
    assert obs["summary"]["verdict"] == consumer_status, obs
    assert obs["summary"]["whole_flow_verdict"] == "NOT_MEASURED", obs
    assert obs["published"]["canonical_before"] == obs["published"]["canonical_after"]
    assert obs["published"]["scoped_before"] == obs["published"]["scoped_after"]


@pytest.mark.parametrize("route", ["entry", "forwarded"])
@pytest.mark.parametrize("verdict", ["UNRECOGNIZED", ["PASS"]])
def test_bounded_invalid_verdict_is_unmeasured_non_success(
        project, monkeypatch, route, verdict):
    obs = _drive_bounded_phase3_receiver(V, project, monkeypatch, route=route,
        child_document=lambda token: _bounded_terminal(token, verdict=verdict, route=route))
    assert obs["rc"] != 0, obs
    assert obs["summary"]["dispatched_verdict"] == "NOT_MEASURED", obs
    assert next(r for r in obs["summary"]["phases"]
                if r["name"] == "phase3")["verdict"] == "NOT_MEASURED", obs


@pytest.mark.parametrize("route", ["entry", "forwarded"])
@pytest.mark.parametrize("verdict", ["PASS", "PASS_WITH_WAIVERS"])
def test_bounded_success_keeps_whole_flow_unmeasured_without_stale_rows(
        project, monkeypatch, route, verdict):
    obs = _drive_bounded_phase3_receiver(V, project, monkeypatch, route=route,
        child_document=lambda token: _bounded_terminal(token, verdict=verdict,
                                                       route=route, stale=False))
    assert obs["rc"] == 0, obs
    assert obs["summary"]["dispatched_verdict"] == verdict, obs
    assert obs["summary"]["verdict"] == "NOT_MEASURED", obs
    assert obs["summary"]["whole_flow_verdict"] == "NOT_MEASURED", obs


def _pending_step5_checkpoint(tmp_path, monkeypatch):
    """Real recorder/FCC handoff over a neutral software-only Step5 contract."""
    import copy
    import _flow_yaml
    import execution_backend_gates as gates
    import execution_backend_worker as worker
    import execution_policy
    import step_output_collector as versions
    import step_write_ledger
    import yaml
    project = tmp_path / 'step5_project'
    stage_owner_route(project, 'ic')
    source = project / 'input/neutral.v'
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text('module neutral(input clk, rst, output p); assign p = rst; endmodule\n')
    load = _flow_yaml.load
    flow = copy.deepcopy(load())
    row = next(r for r in flow['steps'] if str(r['id']) == '5')
    raw = 'reports/step5_source_control.json'
    ready = project / 'reports/step5_mechanical_ready.json'
    ready.parent.mkdir(parents=True, exist_ok=True)
    ready.write_text('{"ready":true,"scope":"SOURCE_CONTROL software consumer"}\n')
    row.update(required_inputs=[{'from': 'external', 'path': 'input/neutral.v'}],
               required_outputs=[raw], program_outputs=[],
               gate={'all_of': [{'files_exist': [raw]}, {'json_field_true': {
                   'file': str(ready.relative_to(project)), 'field': 'ready'}}]})
    fixture_flow = tmp_path / 'step5-flow.yaml'
    fixture_flow.write_text(yaml.safe_dump(flow, sort_keys=False))
    monkeypatch.setattr(_flow_yaml, 'load', lambda *a, **k: load(fixture_flow))
    monkeypatch.setattr(step_write_ledger, '_flow_yaml_path', lambda: fixture_flow)
    monkeypatch.setattr(execution_policy, 'request', lambda: {'mode': 'default'})
    monkeypatch.setattr(execution_policy, '_ordinary_runtime', None)
    inputs = worker._declared_input_files(project, row['required_inputs'])
    attempt = versions.begin_step(project, '5', inputs)
    with versions.active_steps(project, [attempt]):
        (project / raw).write_text('{"population":1,"scope":"SOURCE_CONTROL software producer"}\n')
        formal = project / 'phase2/stage1/formal'
        formal.mkdir(parents=True)
        (formal / 'formal_authoring_request.json').write_text(
            '{"fallback_skill":"formal-verify","scope":"SOURCE_CONTROL review request"}\n')
        versions.publish_producer_outputs(project, attempt)
        consumer = gates.evaluate(project, row)
        pending = versions.finish_step(
            project, attempt, verdict=consumer['status'], canonical_pass=False,
            result={'runner': 'neutral_software_producer', 'invocation_status': 'PASS',
                    'step_rows': [{'step_id': '5', 'status': 'PASS'}],
                    'canonical_consumer': consumer})
    assert pending['status'] == 'NOT_MEASURED'
    assert consumer['step']['reason_class'] == 'awaiting_signed_judgement'
    folder = project / 'steps' / pending['folder']
    original = {p: p.read_bytes() for p in (folder / 'outputs.json', folder / 'written.json')}
    return project, source, ready, folder, original


def _sign_step5_checkpoint(project):
    import ai_signed_judgement as ai
    review = project / 'phase2/stage1/formal/formal_expert_review.json'
    review.write_text('{"invocation_status":"INVOKED","fallback_skill":"formal-verify",'
                      '"scope":"SOURCE_CONTROL independent review"}\n')
    receipt = project / 'reports/audit/ai_judgements/5.json'
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text(json.dumps({
        'schema': ai.SCHEMA, 'step_id': '5', 'verdict': 'PASS',
        'signed_by': 'independent neutral fixture reviewer',
        'judgement': 'Reviewed the exact neutral software checkpoint.',
        'evidence_sha256': ai.evidence_sha256(project, '5')}))


def test_signed_step5_revalidation_keeps_native_provenance_and_is_idempotent(
        tmp_path, monkeypatch):
    import step_output_collector as versions
    project, _, _, old, before = _pending_step5_checkpoint(tmp_path, monkeypatch)
    _sign_step5_checkpoint(project)
    accepted = V._revalidate_step5_checkpoint(project)
    assert accepted['verdict'] == 'PASS'
    current = versions.latest_pass(project, '5')
    assert current['canonical_pass'] and current['current_inputs']
    assert current['result']['checkpoint']['producer_started'] is False
    assert current['result']['checkpoint']['prior_folder'] == str(old.relative_to(project / 'steps'))
    new = project / 'steps' / accepted['folder']
    assert (new / 'written.json').read_bytes() == before[old / 'written.json']
    assert {p: p.read_bytes() for p in before} == before
    assert V._revalidate_step5_checkpoint(project)['folder'] == accepted['folder']
    assert versions.latest_pass(project, '5')['folder'] == accepted['folder']


def test_signed_step5_cannot_override_a_real_complete_gate_failure(tmp_path, monkeypatch):
    import step_output_collector as versions
    project, _, ready, old, before = _pending_step5_checkpoint(tmp_path, monkeypatch)
    _sign_step5_checkpoint(project)
    ready.write_text('{"ready":false,"scope":"SOURCE_CONTROL real mechanical refusal"}\n')
    refused = V._revalidate_step5_checkpoint(project)
    assert refused['verdict'] == 'FAIL'
    assert versions.latest_pass(project, '5') is None
    record = json.loads((project / 'steps' / refused['folder'] / 'outputs.json').read_text())
    assert record['result']['canonical_consumer']['step']['status'] == 'FAIL'
    assert {p: p.read_bytes() for p in before} == before
    assert V._revalidate_step5_checkpoint(project)['verdict'] == 'FAIL'


@pytest.mark.parametrize('changed', ['input', 'output', 'written', 'producer'])
def test_step5_revalidation_refuses_changed_or_unmeasured_native_checkpoint(
        tmp_path, monkeypatch, changed):
    import step_output_collector as versions
    project, source, _, old, _ = _pending_step5_checkpoint(tmp_path, monkeypatch)
    _sign_step5_checkpoint(project)
    if changed == 'input':
        source.write_text(source.read_text() + '// changed original producer input\n')
    elif changed == 'output':
        raw = project / 'reports/step5_source_control.json'
        raw.write_text(raw.read_text() + ' ')
    elif changed == 'written':
        (old / 'written.json').unlink()
    else:
        path = old / 'outputs.json'
        record = json.loads(path.read_text())
        record['result']['invocation_status'] = 'NOT_MEASURED'
        path.write_text(json.dumps(record))
    assert V._revalidate_step5_checkpoint(project)['verdict'] == 'NOT_MEASURED'
    assert versions.latest_pass(project, '5') is None
    assert next(r for r in versions._read_index(project)['steps'] if r['id'] == '5')['folder'] == str(old.relative_to(project / 'steps'))


@pytest.mark.parametrize('signed', [False, True])
def test_step5_revalidation_requires_a_current_review(tmp_path, monkeypatch, signed):
    import step_output_collector as versions
    project, _, _, old, before = _pending_step5_checkpoint(tmp_path, monkeypatch)
    if signed:
        _sign_step5_checkpoint(project)
        review = project / 'phase2/stage1/formal/formal_expert_review.json'
        review.write_text(review.read_text() + ' ')
    assert V._revalidate_step5_checkpoint(project)['verdict'] == 'NOT_MEASURED'
    assert versions.latest_pass(project, '5') is None
    assert {p: p.read_bytes() for p in before} == before


@pytest.mark.parametrize('science_passes', [False, True])
def test_step5_revalidation_keeps_measured_fail_before_changed_evidence(
        tmp_path, monkeypatch, science_passes):
    import execution_backend_gates as gates
    import step_output_collector as versions
    project, source, ready, old, before = _pending_step5_checkpoint(tmp_path, monkeypatch)
    _sign_step5_checkpoint(project)
    if not science_passes:
        ready.write_text('{"ready":false}\n')
    evaluate = gates.evaluate
    def consume_then_change(project, row):
        result = evaluate(project, row)
        source.write_text(source.read_text() + '// changed during consumer\n')
        return result
    monkeypatch.setattr(gates, 'evaluate', consume_then_change)
    refused = V._revalidate_step5_checkpoint(project)
    assert refused['verdict'] == ('NOT_MEASURED' if science_passes else 'FAIL')
    assert versions.latest_pass(project, '5') is None
    record = json.loads((project / 'steps' / refused['folder'] / 'outputs.json').read_text())
    assert record['result']['observed_canonical_consumer']['status'] == ('PASS' if science_passes else 'FAIL')
    assert record['canonical_pass'] is False
    assert record['input_files'][0]['sha256'] == record['inputs']['input/neutral.v']
    assert versions._sha(source) != record['inputs']['input/neutral.v']
    new = project / 'steps' / refused['folder']
    assert (new / 'written.json').read_bytes() == before[old / 'written.json']


def _step14_handoff_source_control(tmp_path, monkeypatch, project, *, ready=True):
    """Use the real declared-producer census and FCC; replace only its process.

    The neutral report is software fixture evidence, not a Yosys measurement.
    Both declaration readers consume the same physical fixture flow.
    """
    import _gate_authorship as authorship
    import flow_declared_producer_run as declared
    import yaml
    fixture_flow = tmp_path / 'step5-flow.yaml'
    flow = yaml.safe_load(fixture_flow.read_text())
    row = next(r for r in flow['steps'] if str(r['id']) == '14')
    raw = 'reports/step14_source_control.json'
    program = 'yosys_hilomap_required_check'
    row.update(required_inputs=[{'from': 'external', 'path': 'input/neutral.v'}],
               required_outputs=[raw], programs=[program],
               program_outputs=[{'program': program, 'path': raw,
                   'producer_command': program + ' . --json ' + raw}],
               gate={'all_of': [{'files_exist': [raw]}, {'json_field_true': {
                   'file': raw, 'field': 'ready'}}]})
    fixture_flow.write_text(yaml.safe_dump(flow, sort_keys=False))
    clauses = declared.declared_producer_clauses
    monkeypatch.setattr(declared, 'declared_producer_clauses', lambda: clauses(fixture_flow))
    calls = []
    def neutral_process(project, clause, timeout):
        assert clause['step'] == '14' and clause['program'] == program
        calls.append(clause['target'])
        target = project / clause['target']
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(authorship.stamp({
            'program': program, 'ready': ready,
            'scope': 'SOURCE_CONTROL neutral software process'},
            role=authorship.ROLE_PRODUCER)))
        return {'executed': True, 'rc': 0, 'target_exists_after': True,
                'authorship': authorship.ROLE_PRODUCER, 'program': program}
    monkeypatch.setattr(declared, '_run_one', neutral_process)
    return calls


@pytest.mark.parametrize('mechanical_ready', [False, True])
def test_phase3_entry_revalidates_pending_step5_before_dispatch(
        tmp_path, monkeypatch, mechanical_ready):
    import step_output_collector as versions
    project, _, ready, _, _ = _pending_step5_checkpoint(tmp_path, monkeypatch)
    handoff_calls = _step14_handoff_source_control(tmp_path, monkeypatch, project)
    _sign_step5_checkpoint(project)
    if not mechanical_ready:
        ready.write_text('{"ready":false}\n')
    called = []
    class ReachedExistingBackend(Exception):
        pass
    def phase3_only(label, runner, args, env=None):
        called.append(runner.name)
        assert runner.name == 'phase3_one_shot_runner.py', 'Step4/5 producer must not restart'
        if mechanical_ready:
            assert versions.latest_pass(project, '5')['canonical_pass']
            assert versions.latest_pass(project, '14')['canonical_pass']
            assert handoff_calls == ['reports/step14_source_control.json']
        else:
            assert versions.latest_pass(project, '5') is None
        raise ReachedExistingBackend
    monkeypatch.setattr(V, '_run_phase', phase3_only)
    monkeypatch.setattr(sys, 'argv', ['vibe_ic_one_shot_runner', str(project),
                        '--entry-step', '15', '--exit-step', '15', '--no-dashboard',
                        '--skip-hardware', '--skip-analog'])
    real_entry('IC', 'default', project)
    if mechanical_ready:
        with pytest.raises(ReachedExistingBackend):
            V.main()
        assert called == ['phase3_one_shot_runner.py']
    else:
        assert V.main() == 1
        assert called == []
        assert handoff_calls == []
        report = json.loads(_pl.report_path(project, 'vibe_ic_one_shot.json').read_text())
        assert report['step5_checkpoint_review']['verdict'] == 'FAIL'
        assert report['halted_at'] == 'phase2'


def test_phase3_handoff_refuses_a_real_step14_complete_gate_failure(tmp_path, monkeypatch):
    import step_output_collector as versions
    project, _, _, _, _ = _pending_step5_checkpoint(tmp_path, monkeypatch)
    calls = _step14_handoff_source_control(tmp_path, monkeypatch, project, ready=False)
    _sign_step5_checkpoint(project)
    dispatched = []
    monkeypatch.setattr(V, '_run_phase', lambda *a, **k: dispatched.append(a))
    monkeypatch.setattr(sys, 'argv', ['vibe_ic_one_shot_runner', str(project),
                        '--entry-step', '15', '--exit-step', '15', '--no-dashboard',
                        '--skip-hardware', '--skip-analog'])
    real_entry('IC', 'default', project)
    assert V.main() == 1
    assert calls == ['reports/step14_source_control.json']
    assert versions.latest_pass(project, '5')['canonical_pass']
    assert versions.latest_pass(project, '14') is None
    assert dispatched == []
    acceptance = next(r for r in versions.current_acceptance(project, 0) if r['id'] == '14')
    assert acceptance['result']['producer_return']['rc'] == 0
    assert acceptance['result']['canonical_consumer']['status'] == 'FAIL'
    report = json.loads(_pl.report_path(project, 'vibe_ic_one_shot.json').read_text())
    assert report['step14_handoff']['verdict'] == 'FAIL'
    assert report['halted_at'] == 'phase2'


def test_step14_remains_unsupported_as_a_runner_entry(tmp_path, monkeypatch, capsys):
    project, _, _, _, _ = _pending_step5_checkpoint(tmp_path, monkeypatch)
    dispatched = []
    monkeypatch.setattr(V, '_run_phase', lambda *a, **k: dispatched.append(a))
    monkeypatch.setattr(sys, 'argv', ['vibe_ic_one_shot_runner', str(project),
                        '--entry-step', '14', '--exit-step', '14', '--no-dashboard',
                        '--skip-hardware', '--skip-analog'])
    real_entry('IC', 'default', project)
    assert V.main() == 2
    assert "no runner can be entered at step '14'" in capsys.readouterr().err
    assert dispatched == []
# The checkpoint consumer is a software boundary here, not an IC producer.
# Its real retained inputs, signed review, identity and output recorder still
# run; the leaf supplies the existing pass-with-note tier and its exact reason.
def test_unbounded_refused_checkpoint_cannot_succeed(tmp_path, monkeypatch):
    import execution_backend_gates as gates

    # The aggregate/report writer is real; unrelated full-flow summary/audit
    # generation is outside this software caller's proof population.
    monkeypatch.setattr(_pl, "emit_final_summary", lambda *a, **k: False)
    project, _, _, _, before = _recorded_d1_checkpoint(tmp_path, monkeypatch)
    _sign_d1_checkpoint(project)
    consume = gates.evaluate
    reason = "neutral software checkpoint requires strict PASS before downstream admission"
    observed = []

    def noted_consumer(project, row):
        result = consume(project, row)
        assert result["status"] == "PASS", result
        observed.append(result["status"])
        return {**result, "status": "PASS_WITH_WAIVERS",
                "step": {**result["step"], "status": "PASS_WITH_WAIVERS",
                         "reasons": [reason]}}

    monkeypatch.setattr(gates, "evaluate", noted_consumer)
    called = []
    rc, doc = _drive_main(
        project, monkeypatch, phase1=("FAIL", 1, None), phase2=("PASS", 0),
        phase3=({"verdict": "PASS"}, 0), reuse_phase1=True,
        after_phase=called.append)
    observation = {"scope": "Normal main/report/replay software control only; no IC or native EDA",
                   "rc": rc, "report": doc, "phase_calls": called,
                   "native_consumer_before_note": observed}
    (tmp_path / "HALTED_CHECKPOINT_OBSERVATION.json").write_text(
        json.dumps(observation, indent=2) + "\n")
    assert observed and called == [], observation
    assert doc["halted_at"] == "phase1", observation
    assert doc["phases"][0] == {"name": "phase1", "verdict": "PASS_WITH_WAIVERS", "rc": 0}
    assert doc["phase1_checkpoint_review"]["canonical_acceptance"]["verdict"] == "PASS_WITH_WAIVERS"
    assert doc["phase1_checkpoint_review"]["detail"] == reason
    assert doc["completion_audit_axis"]["state"] == "NOT_APPLICABLE"
    assert all(row["verdict"] == "SKIPPED" for row in doc["phases"][1:])
    assert {path: path.read_bytes() for path in before} == before
    assert (rc, doc["verdict"]) == (1, "NOT_MEASURED"), observation
    assert GUARD._expected_front_door_verdict(doc, doc["phases"]) == "NOT_MEASURED"
    assert GUARD._is_orchestrator_report(
        _pl.report_path(project, "vibe_ic_one_shot.json"), project)
    forged = dict(doc, verdict="PASS_WITH_WAIVERS")
    forged_path = tmp_path / "forged-success.json"
    forged_path.write_text(json.dumps(forged) + "\n")
    assert not GUARD._is_orchestrator_report(forged_path, project)


@pytest.mark.parametrize("phase2_verdict", ["PASS", "FAIL"])
def test_terminal_halt_context_preserves_full_success_and_phase_failure(
        project, monkeypatch, phase2_verdict):
    """Real coordinator/axis/report/replay; phase execution is software IO."""
    from types import SimpleNamespace

    monkeypatch.setattr(_pl, "emit_final_summary", lambda *a, **k: False)
    monkeypatch.setattr(V._canonical_admission, "admit_span", lambda *a, **k:
                        SimpleNamespace(admitted=True, identity_sha256="source-control"))
    monkeypatch.setattr(V._canonical_admission, "child_env",
                        lambda _identity, env: dict(env))
    read_axis = V._completion_audit_axis

    def current_axis(project, *, phase3_ran, started_at):
        if phase3_ran:
            _audit(project, "PASS", scope=WHOLE)
        return read_axis(project, phase3_ran=phase3_ran, started_at=started_at)

    monkeypatch.setattr(V, "_completion_audit_axis", current_axis)
    rc, doc = _drive_main(project, monkeypatch, phase1=("PASS", 0, None),
                          phase2=(phase2_verdict, 0 if phase2_verdict == "PASS" else 1),
                          phase3=({"verdict": "PASS"}, 0))
    observation = {"scope": "Software phase/admission/audit-writer leaves; real coordinator and audit reader",
                   "rc": rc, "report": doc}
    (project / "TERMINAL_HALT_CONTEXT_OBSERVATION.json").write_text(
        json.dumps(observation, indent=2) + "\n")
    assert doc["verdict"] == phase2_verdict, observation
    assert rc == (0 if phase2_verdict == "PASS" else 1), observation
    assert doc["halted_at"] == (None if phase2_verdict == "PASS" else "phase2"), observation
    assert GUARD._expected_front_door_verdict(doc, doc["phases"]) == phase2_verdict
    if phase2_verdict == "PASS":
        assert doc["completion_audit_axis"]["state"] == "PASS"
        assert all(row["verdict"] == "PASS" for row in doc["phases"]
                   if row["name"] in ("phase1", "phase2", "phase3"))
    else:
        assert next(row for row in doc["phases"] if row["name"] == "phase3")["verdict"] == "SKIPPED"


def test_explicit_frontend_window_preserves_signed_d1_success(tmp_path, monkeypatch):
    """A signed D1 and a software Phase-2 child close only the explicit window."""
    from types import SimpleNamespace
    import step_output_collector as versions

    project, _, _, _, before = _recorded_d1_checkpoint(tmp_path, monkeypatch)
    _sign_d1_checkpoint(project)
    monkeypatch.setattr(_pl, "emit_final_summary", lambda *a, **k: False)
    monkeypatch.setattr(V, "_phase1_decision", lambda *a, **k: (False, ""))
    monkeypatch.setattr(V._canonical_admission, "admit_span", lambda *a, **k:
                        SimpleNamespace(admitted=True, identity_sha256="source-control"))
    monkeypatch.setattr(V._canonical_admission, "child_env",
                        lambda _identity, env: dict(env))
    calls = []

    def bounded_child(label, runner, args, env=None):
        calls.append(runner.name)
        assert runner.name == "phase2_one_shot_runner.py", calls
        assert args[args.index("--exit-step") + 1] == "2", args
        _report(project, "phase2_one_shot.json", {
            "verdict": "PASS", "bounded": True,
            "declared_window": {"entry_step": None, "exit_step": "2"},
            "scope": "SOURCE_CONTROL Phase-2 subprocess writer; no native producer"})
        return 0

    monkeypatch.setattr(V, "_run_phase", bounded_child)
    monkeypatch.setattr(sys, "argv", ["vibe_ic_one_shot_runner", str(project),
        "--no-dashboard", "--skip-hardware", "--skip-analog", "--exit-step", "2"])
    real_entry("IC", "default", project)
    rc = V.main()
    report = _pl.report_path(project, "vibe_ic_one_shot.json")
    doc = json.loads(report.read_text())
    observation = {"scope": "Signed retained neutral D1 and real main/rollup/report/replay; Phase-2 admission/subprocess are software leaves",
                   "rc": rc, "report": doc, "phase_calls": calls}
    (tmp_path / "EXPLICIT_BOUNDED_SUCCESS_OBSERVATION.json").write_text(
        json.dumps(observation, indent=2) + "\n")
    assert rc == 0 and doc["bounded"] is True, observation
    assert doc["dispatched_verdict"] == "PASS", observation
    assert doc["verdict"] == doc["whole_flow_verdict"] == "NOT_MEASURED", observation
    assert doc["declared_window"] == {"entry_step": None, "exit_step": "2"}
    assert doc.get("halted_at") is None and calls == ["phase2_one_shot_runner.py"]
    assert doc["phases"][0] == {"name": "phase1", "verdict": "PASS", "rc": 0}
    assert versions.latest_pass(project, "D1")["canonical_pass"] is True
    assert {path: path.read_bytes() for path in before} == before
    assert GUARD._is_orchestrator_report(report, project)
