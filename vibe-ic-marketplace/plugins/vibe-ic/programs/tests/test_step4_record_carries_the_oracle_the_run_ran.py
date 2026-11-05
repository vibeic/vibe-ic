#!/usr/bin/env python3
"""The canonical Step-4 record must not contradict the run that produced it.

`step_reference_tb`'s connectivity bridge writes `phase2/stage1/sim/results.xml`
— the one path the flow treats as canonical — and its waiver text says
functional verification is "DEFERRED to a per-IC oracle TB". In the SAME Phase-2
pass, `professional_tb_gen` runs FIRST and, when its Tier-3 hook is filled,
closes exactly that deferral with a real cocotb run against the real rtl/.
Nothing reconciled the two, so the canonical record kept saying
`functional_verified=false` while the run's own JUnit transcript said otherwise.

MEASURED, sha256 x sky130A, plugin 1.15.87:

    phase2/stage1/sim/results.xml                 functional_verified=false
    phase2/stage1/sim_professional/*/results.xml  tests=1 failures=0 errors=0

The half that keeps this honest is the REVERSE direction, and most of the cases
below are it: a claim of functional verification is a forgery unless the record
can SHOW the transcript, and every unshowable shape — no pointer, a dangling
pointer, a non-JUnit file, a zero-test result, a failing result — must still be
refused exactly as it was before. Those cases pass on BOTH trees by design.

All fixtures are synthetic; no chip, PDK or vendor literal decides anything.
"""
from __future__ import annotations

import sys
import inspect
import json
import time
import shutil
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import design_one_shot_runner as DOSR              # noqa: E402
import cpu_functional_oracle_waiver_check as GATE  # noqa: E402

TRACK_REASON = "class 'widget_engine' verification_track='generic_full_stack'"
TOP = "widget_engine"


def _junit(tests: int, failures: int = 0, errors: int = 0,
           skipped: int = 0) -> str:
    """A cocotb-shaped JUnit document with `tests` testcase elements.

    The count and the elements are kept CONSISTENT on purpose: `parse_junit`
    falls back to counting `<testcase>` when the attribute reads 0, so a
    `tests="0"` suite that still lists a case is not a vacuous result and
    would not exercise the control it looks like it exercises.
    """
    cases = "".join(
        f'<testcase classname="tb_{TOP}" name="oracle{i}" time="1.0"/>'
        for i in range(tests))
    return (
        "<?xml version='1.0' encoding='utf-8'?>\n"
        f'<testsuites name="cocotb tests"><testsuite name="tb_{TOP}" '
        f'errors="{errors}" failures="{failures}" skipped="{skipped}" '
        f'tests="{tests}" time="1.0">'
        f"{cases}"
        "</testsuite></testsuites>\n")


def _project(tmp_path: Path, professional: "str | None") -> Path:
    """A project with a completed connectivity transcript, optionally beside a
    professional-TB result."""
    proj = tmp_path / "proj"
    fs = proj / "phase2" / "stage1" / "sim_full_stack" / "run"
    fs.mkdir(parents=True, exist_ok=True)
    transcript = fs / "full_stack.log"
    transcript.write_text(
        "binding widget_engine\nFULL_STACK_TB_CHECKS pass=4 fail=0\n"
        "FULL_STACK_TB_DONE\n", encoding="utf-8")
    if professional is not None:
        pd = proj / "phase2" / "stage1" / "sim_professional" / TOP
        pd.mkdir(parents=True, exist_ok=True)
        (pd / "results.xml").write_text(professional, encoding="utf-8")
    return proj


def _emit(proj: Path) -> bool:
    transcript = (proj / "phase2" / "stage1" / "sim_full_stack" / "run"
                  / "full_stack.log")
    return DOSR._emit_connectivity_sim_bridge(proj, transcript, TOP,
                                              TRACK_REASON)


def _record(proj: Path) -> str:
    return (proj / "phase2" / "stage1" / "sim"
            / "results.xml").read_text(encoding="utf-8")


def _field(xml: str, name: str) -> str:
    return GATE._read_xml_field(xml, name)


# ===========================================================================
# forward — the run's own oracle must reach the canonical record
# ===========================================================================
def test_the_canonical_record_reports_the_oracle_this_run_ran(tmp_path):
    proj = _project(tmp_path, _junit(tests=3))
    assert _emit(proj) is True
    xml = _record(proj)
    assert _field(xml, "functional_verified") == "true", (
        "the run closed functional verification with a real cocotb PASS and "
        "the canonical Step-4 record still says functional_verified=false; "
        f"record was: {xml}")


def test_professional_functional_result_does_not_require_connectivity_xml(tmp_path):
    proj = _project(tmp_path, _junit(tests=3))
    rc, detail = GATE._evaluate(proj)
    assert rc == 0, detail
    assert 'professional-TB' in detail
    assert not (proj / 'phase2/stage1/sim/results.xml').exists()


@pytest.mark.parametrize('damage', ['failed_suite', 'unexecuted_case'])
def test_without_connectivity_xml_real_functional_obligations_still_apply(tmp_path, damage):
    proj = _project(tmp_path, _junit(tests=3, failures=int(damage == 'failed_suite')))
    if damage == 'unexecuted_case':
        docs = proj / 'phase1/generated_docs'
        docs.mkdir(parents=True)
        (docs / 'L10_TEST_CASES.json').write_text(json.dumps({
            'test_cases': [{'name': 'independent_case', 'kind': 'functional_vector',
                            'input': {'a': 1}, 'expected': {'y': 1}}]}))
    rc, detail = GATE._evaluate(proj)
    assert rc != 0, detail


def _current_professional_reference(tmp_path, monkeypatch, *, during_run=None,
                                    during_generate=None):
    """Real producers/consumers; only simulator transport is a neutral fixture."""
    import professional_tb_gen as generator
    project = _project(tmp_path, None)
    rtl = project / 'phase2/stage1/rtl'
    rtl.mkdir(parents=True)
    (rtl / (TOP + '.v')).write_text(
        f'module {TOP}(input a, output y); assign y=a; endmodule\n')
    docs = project / 'phase1/generated_docs'
    docs.mkdir(parents=True)
    (docs / 'L9_INTEGRATION_SPEC.json').write_text(json.dumps({
        'top_module': TOP, 'top_ports': [
            {'name': 'a', 'direction': 'input'},
            {'name': 'y', 'direction': 'output'}]}))
    full = project / 'phase2/stage1/sim_full_stack'
    (full / f'tb_{TOP}_full.v').write_text(
        f'module tb; reg a=0; wire y; {TOP} dut(a,y); endmodule\n')
    bundle = project / 'phase2/stage1/sim_professional' / TOP
    bundle.mkdir(parents=True)
    (bundle / 'expert_reference_tb.py').write_text(
        'def expected(a):\n    return {"y": a}\n')
    def generated(*_):
        if during_generate:
            during_generate(project, bundle)
        return {'status': 'PASS', 'dut_kind': 'expert_reference', 'out_dir': str(bundle)}
    monkeypatch.setattr(generator, 'generate', generated)
    monkeypatch.setattr(DOSR, '_professional_tb_exec_site', lambda *_: 'host')
    monkeypatch.setattr(DOSR, '_professional_tb_sim_differential', lambda *_: None)
    def simulated_make(argv, **kwargs):
        assert argv[:2] == ['bash', '-lc']
        (bundle / 'results.xml').write_text(_junit(1))
        if during_run:
            during_run(project, bundle)
        return 0, 'PROFESSIONAL_TB PASS\n', ''
    monkeypatch.setattr(DOSR, '_run', simulated_make)
    began = time.time()
    producer = DOSR.step_professional_tb_gen(project, TOP, '')
    assert producer.status == 'PASS', producer.detail
    monkeypatch.setattr(DOSR, '_iverilog_available', lambda *_: True)
    monkeypatch.setattr(DOSR, '_iverilog_compile_with_sv_fallback',
                        lambda *_args, **_kw: (0, '', '', 'iverilog_g2012'))
    monkeypatch.setattr(DOSR, '_sim_run_or_reuse', lambda *_args, **_kw: (
        0, 'FULL_STACK_TB_CHECKS pass=1 fail=0\nFULL_STACK_TB_DONE\n', ''))
    monkeypatch.setattr(DOSR, '_run_pulse_width_rearm_normal_gate',
                        lambda *_: (0, {'verdict': 'NOT_APPLICABLE'},
                                     project / 'absent-pulse-report.json'))
    return project, producer, began


def _reference_current(project, producer, began, *, public):
    # Overlay the same behavior test on a predecessor that has no optional
    # producer argument: execute its real consumer rather than fail on an API.
    consumer = DOSR.step_reference_tb if public else DOSR._reference_tb_generic_full_stack
    kwargs = {}
    if 'professional_result' in inspect.signature(consumer).parameters:
        kwargs.update(professional_result=producer, professional_started_after=began)
    if public:
        return consumer(project, TOP, 'processor_cpu', '', **kwargs)
    return consumer(project, TOP, TRACK_REASON, time.time(), '', 'processor_cpu', **kwargs)


@pytest.mark.parametrize('public', [False, True])
def test_reference_consumer_reports_the_current_professional_oracle(tmp_path, monkeypatch, public):
    project, producer, began = _current_professional_reference(tmp_path, monkeypatch)
    result = _reference_current(project, producer, began, public=public)
    gate_rc, gate_detail = GATE._evaluate(project)
    observed = {'reference_status': result.status,
                'functional_verified': result.extras.get('functional_verified'),
                'gate_rc': gate_rc, 'gate_detail': gate_detail}
    assert gate_rc == 0, observed
    assert result.status == 'PASS', observed
    assert result.extras.get('functional_verified') is True, observed


@pytest.mark.parametrize('damage', [
    'missing_witness', 'foreign_project', 'prior_run', 'future_run',
    'producer_fail', 'no_sim', 'rtl_changed', 'report_changed',
    'hook_changed', 'l_doc_changed', 'junit_changed', 'junit_missing',
    'junit_failed', 'junit_vacuous', 'junit_skipped', 'sibling_failed',
    'sibling_missing',
])
def test_reference_consumer_cannot_adopt_noncurrent_professional_evidence(
        tmp_path, monkeypatch, damage):
    project, producer, began = _current_professional_reference(tmp_path, monkeypatch)
    bundle = project / 'phase2/stage1/sim_professional' / TOP
    if damage == 'missing_witness':
        producer = None
    elif damage == 'foreign_project':
        copied = tmp_path / 'other_project'
        shutil.copytree(project, copied)
        project = copied
    elif damage == 'prior_run':
        began = time.time() + 1
    elif damage == 'future_run':
        producer.extras.setdefault('reference_execution', {})['started_at'] = time.time() + 10
    elif damage == 'producer_fail':
        producer.status = 'FAIL'
    elif damage == 'no_sim':
        producer = DOSR.StepResult('professional_tb_gen', 'PASS')
    elif damage == 'rtl_changed':
        (project / f'phase2/stage1/rtl/{TOP}.v').write_text(
            f'module {TOP}(input a, output y); assign y=~a; endmodule\n')
    elif damage == 'report_changed':
        report = project / 'reports/phase2/gates/professional_tb.json'
        value = json.loads(report.read_text()); value['ran_cocotb'] = False
        report.write_text(json.dumps(value))
    elif damage == 'hook_changed':
        (bundle / 'expert_reference_tb.py').write_text(
            'def expected(a):\n    return {"y": 0}\n')
    elif damage == 'l_doc_changed':
        (project / 'phase1/generated_docs/L9_INTEGRATION_SPEC.json').write_text('{}')
    elif damage == 'junit_changed':
        (bundle / 'results.xml').write_text(_junit(2))
    elif damage == 'junit_missing':
        (bundle / 'results.xml').unlink()
    elif damage == 'junit_failed':
        (bundle / 'results.xml').write_text(_junit(1, failures=1))
    elif damage == 'junit_vacuous':
        (bundle / 'results.xml').write_text(_junit(0))
    elif damage == 'junit_skipped':
        (bundle / 'results.xml').write_text(_junit(1, skipped=1))
    else:
        other = bundle.parent / 'another_suite'; other.mkdir()
        if damage == 'sibling_failed':
            (other / 'results.xml').write_text(_junit(1, failures=1))
    result = _reference_current(project, producer, began, public=True)
    assert result.status == 'NOT_MEASURED', {'damage': damage, 'result': result}
    assert result.extras.get('functional_verified') is not True


def test_reference_current_execution_still_requires_existing_substance_gate(tmp_path, monkeypatch):
    project, producer, began = _current_professional_reference(tmp_path, monkeypatch)
    # Declare a new, unexecuted oracle case before the current producer runs.
    # Refreshing that real producer witness cannot replace the gate's missing
    # per-case execution proof.
    (project / 'phase1/generated_docs/L10_TEST_CASES.json').write_text(json.dumps({
        'test_cases': [{'id': 'neutral_case', 'type': 'functional',
                        'input': {'a': 1}, 'expected': {'y': 1}}]}))
    producer = DOSR.step_professional_tb_gen(project, TOP, '')
    result = _reference_current(project, producer, began, public=True)
    rc, reason = GATE._evaluate(project)
    assert rc == 1, reason
    assert result.status == 'NOT_MEASURED', result


def test_reference_current_execution_cannot_bypass_pulse_gate(tmp_path, monkeypatch):
    project, producer, began = _current_professional_reference(tmp_path, monkeypatch)
    monkeypatch.setattr(DOSR, '_run_pulse_width_rearm_normal_gate', lambda *_: (
        1, {'verdict': 'FAIL', 'measured': True}, project / 'pulse.json'))
    result = _reference_current(project, producer, began, public=True)
    assert result.status == 'FAIL'


@pytest.mark.parametrize('change', ['hook', 'l_doc', 'new_hook', 'new_l_doc'])
@pytest.mark.parametrize('phase', ['generate', 'simulate'])
def test_reference_execution_cannot_bind_inputs_changed_during_production(
        tmp_path, monkeypatch, change, phase):
    def mutate(project, bundle):
        if change == 'hook':
            (bundle / 'expert_reference_tb.py').write_text(
                'def expected(a):\n    return {"y": 0}\n')
        elif change == 'new_hook':
            (bundle / 'other').mkdir()
            (bundle / 'other/expert_reference_tb.py').write_text('def expected(a): return a\n')
        elif change == 'l_doc':
            (project / 'phase1/generated_docs/L9_INTEGRATION_SPEC.json').write_text('{}')
        else:
            (project / 'phase1/generated_docs/L8_CLOCK_SPEC.json').write_text(
                '{"sampling": "a changed source definition"}')
    project, producer, began = _current_professional_reference(
        tmp_path, monkeypatch,
        **{'during_generate' if phase == 'generate' else 'during_run': mutate})
    assert producer.status == 'PASS'  # A real passing transcript is insufficient.
    result = _reference_current(project, producer, began, public=True)
    assert result.status == 'NOT_MEASURED', {'phase': phase, 'change': change,
                                           'result': result,
                                           'producer': producer.extras}


def test_the_record_shows_the_transcript_it_claims(tmp_path):
    """A flag is a claim; a resolvable pointer is evidence."""
    proj = _project(tmp_path, _junit(tests=3))
    _emit(proj)
    pointer = _field(_record(proj), "functional_evidence")
    assert pointer, "functional_verified=true was written with no pointer"
    assert (proj / pointer).is_file(), (
        f"<functional_evidence>{pointer}</> does not resolve inside the project")


def test_the_gate_accepts_a_claim_it_can_check(tmp_path):
    """A reverse control, not a discriminator: the gate already reached rc 0 on
    this shape through `find_professional_tb_pass`. It is here so a fix that
    made the RECORD honest by breaking the GATE would be caught."""
    proj = _project(tmp_path, _junit(tests=3))
    _emit(proj)
    rc, msg = GATE._evaluate(proj)
    assert rc == 0, f"the gate refused a substantiated record: {msg}"


# ===========================================================================
# reverse controls — these must hold on BOTH trees
# ===========================================================================
def test_with_no_oracle_the_record_is_the_connectivity_record(tmp_path):
    proj = _project(tmp_path, None)
    assert _emit(proj) is True
    xml = _record(proj)
    assert _field(xml, "verdict") == "CONNECTIVITY_PASS"
    assert _field(xml, "functional_verified") == "false", (
        "a run with no functional oracle must still record none")


def test_a_failing_oracle_does_not_become_a_functional_pass(tmp_path):
    proj = _project(tmp_path, _junit(tests=3, failures=1))
    _emit(proj)
    assert _field(_record(proj), "functional_verified") == "false", (
        "a professional TB with a failure was recorded as functional evidence")


def test_a_zero_test_oracle_does_not_become_a_functional_pass(tmp_path):
    proj = _project(tmp_path, _junit(tests=0))
    _emit(proj)
    assert _field(_record(proj), "functional_verified") == "false", (
        "a vacuous zero-test professional result was recorded as evidence")


def test_the_per_case_oracle_gap_marker_survives_both_branches(tmp_path):
    """`l10_tb_conformance_check` keys its strictness on this marker; a
    whole-design functional TB says nothing about the per-case gap, so the
    marker must not disappear when the oracle appears."""
    with_oracle = _project(tmp_path / "a", _junit(tests=3))
    without = _project(tmp_path / "b", None)
    _emit(with_oracle)
    _emit(without)
    for proj in (with_oracle, without):
        assert _field(_record(proj), "capability_gap") == \
            GATE.CAP_CPU_FUNCTIONAL_ORACLE, (
            f"the per-case oracle gap marker was dropped in {proj}")


def test_a_bare_claim_with_no_pointer_is_still_a_forgery(tmp_path):
    proj = _project(tmp_path, None)
    _emit(proj)
    rec = proj / "phase2" / "stage1" / "sim" / "results.xml"
    rec.write_text(_record(proj).replace(
        "<functional_verified>false</functional_verified>",
        "<functional_verified>true</functional_verified>"), encoding="utf-8")
    rc, msg = GATE._evaluate(proj)
    assert rc == 1, (
        f"a hand-edited flag with nothing behind it was accepted: {msg}")


def test_a_pointer_to_a_non_junit_file_is_still_a_forgery(tmp_path):
    proj = _project(tmp_path, None)
    _emit(proj)
    (proj / "not_junit.xml").write_text("<results><verdict>PASS</verdict>"
                                        "</results>", encoding="utf-8")
    rec = proj / "phase2" / "stage1" / "sim" / "results.xml"
    rec.write_text(_record(proj).replace(
        "<functional_verified>false</functional_verified>",
        "<functional_verified>true</functional_verified>"
        "<functional_evidence>not_junit.xml</functional_evidence>"),
        encoding="utf-8")
    rc, msg = GATE._evaluate(proj)
    assert rc == 1, f"a non-JUnit document was accepted as a transcript: {msg}"


def test_a_pointer_to_a_failing_transcript_is_still_a_forgery(tmp_path):
    proj = _project(tmp_path, None)
    _emit(proj)
    (proj / "failing.xml").write_text(_junit(tests=3, failures=2),
                                      encoding="utf-8")
    rec = proj / "phase2" / "stage1" / "sim" / "results.xml"
    rec.write_text(_record(proj).replace(
        "<functional_verified>false</functional_verified>",
        "<functional_verified>true</functional_verified>"
        "<functional_evidence>failing.xml</functional_evidence>"),
        encoding="utf-8")
    rc, msg = GATE._evaluate(proj)
    assert rc == 1, f"a failing transcript was accepted as a PASS: {msg}"


def test_a_dangling_pointer_is_still_a_forgery(tmp_path):
    proj = _project(tmp_path, None)
    _emit(proj)
    rec = proj / "phase2" / "stage1" / "sim" / "results.xml"
    rec.write_text(_record(proj).replace(
        "<functional_verified>false</functional_verified>",
        "<functional_verified>true</functional_verified>"
        "<functional_evidence>nowhere/results.xml</functional_evidence>"),
        encoding="utf-8")
    rc, msg = GATE._evaluate(proj)
    assert rc == 1, f"a dangling pointer was accepted: {msg}"


def test_a_connectivity_record_with_no_claim_still_refuses(tmp_path):
    """The pre-existing INCOMPLETE path must be untouched."""
    proj = _project(tmp_path, None)
    _emit(proj)
    rc, msg = GATE._evaluate(proj)
    assert rc == 1 and "INCOMPLETE" in msg, (
        f"connectivity-only evidence stopped being refused: rc={rc} {msg}")
