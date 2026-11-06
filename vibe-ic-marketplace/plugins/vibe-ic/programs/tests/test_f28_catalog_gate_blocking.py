"""F28: step 1's catalog synth-safe gate BLOCKS inline, and a declared catalog IP
the elaborated top never reaches FAILs.

Two owner rulings on the gate F9 wired:

1. ``design_one_shot_runner`` runs the gate at step 1 and its exit status
   decides the step (``step_catalog_synth_safe_params``); the gate's header
   says ``ENFORCEMENT: blocking``. The two change together:
   ``flow_gate_enforcement_audit`` reads a blocking declaration without an
   inline spawn as ``contradiction::``, and an inline spawn under an advisory
   declaration as ``declared_weaker_than_wired``. One mutation arm drops the
   spawn from a copy of the runner and requires the contradiction back. The
   audit cannot see whether ``main`` calls the step at all, so a second arm
   reads ``main``'s plan appends and requires the uncalled step to be seen.
2. (F28, F28b) The input declares serv as its reuse; the glue never instantiates it. Yosys's
   ``hierarchy -top`` drops every serv module, so the gate judged zero rows and
   answered PASS. It now FAILs with ``CATALOG_REUSE_DECLARED_NOT_INSTANTIATED``.
   An IP only the pull record names is not held to that (the design never said
   it would use it), which the control below pins. F28b: the same holds for a
   declared IP whose manifest declares NO synth-safe parameter (picorv32); it
   used to stand down as DESIGN_DECLARED_NA without elaborating anything.

Real Yosys (host, else the EDA image), as in test_f9. ``tempfile.mkdtemp``
rather than ``tmp_path``: in the EDA image ``tmp_path`` carries a newline.

THE IMAGE IS STATED (``_stated_eda_image``), not asked of this host: every
in-process resolution in this module answers the stated identity. The gate's
own Yosys runs in a child process: inside the image (no docker) it uses the
image's Yosys and resolves no image at all; on a docker host without Yosys the
child resolves the image it runs, as production does. The stated digest is
not a real image, so handing it to that child would make it run nothing.
"""
import json
import shutil
import sys
import tempfile
from pathlib import Path

import pytest
import yaml

PLUGIN = Path(__file__).resolve().parents[2]
PROGRAMS = PLUGIN / 'programs'
sys.path.insert(0, str(PROGRAMS))
sys.path.insert(0, str(PROGRAMS / 'tests'))
import flow_compliance_check as fcc  # noqa: E402

GATE = 'catalog_synth_safe_params_check'
CODE = 'CATALOG_REUSE_DECLARED_NOT_INSTANTIATED'
CAL = PROGRAMS / 'calibration'
FLOW = PLUGIN / 'flow/phase1_phase2_phase3.yaml'
REPORT = 'reports/phase2/gates/catalog_synth_safe_params.json'
RUNNER = 'design_one_shot_runner.py'
L2_DECLARES_SERV = {'cpu_isa': 'rv32i', 'cpu_arch': 'bit-serial',
                    'description': 'The design reuses the serv core from the IP catalog.'}
#: The inline call this change adds to ``main``; a mutation arm deletes exactly it.
INLINE_CALL = '        plan.append(step_catalog_synth_safe_params(project))\n'


@pytest.fixture(autouse=True)
def _stated_image(monkeypatch):
    from _stated_eda_image import state_the_image
    return state_the_image(monkeypatch)


@pytest.fixture
def root():
    path = Path(tempfile.mkdtemp(prefix='f28_'))
    yield path
    shutil.rmtree(path, ignore_errors=True)


def _put(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(obj if isinstance(obj, str) else json.dumps(obj))


def _design(root, glue, l2=L2_DECLARES_SERV):
    """The calibration IP staged under one of serv's manifest file names."""
    p = root / 'proj'
    rtl = p / 'phase2/stage1/rtl'
    rtl.mkdir(parents=True)
    shutil.copy(CAL / 'cal_catalog_ip.v', rtl / 'serv_top.v')
    shutil.copy(CAL / f'cal_catalog_glue_{glue}.v', rtl / 'glue.v')
    _put(p / 'phase1/generated_docs/L2_FRS.json', l2)
    _put(p / 'phase1/generated_docs/L9_INTEGRATION_SPEC.json', {'top_module': 'top'})
    return p


def _step1():
    flow = yaml.safe_load(FLOW.read_text())
    return next(s for s in flow['steps'] if str(s.get('id')) == '1')


def _step1_verdict(p):
    result = fcc.check_step(p, _step1(), {})
    return result, json.loads((p / REPORT).read_text())


# -- ruling 2: declared but never reached ---------------------------------

def test_a_declared_ip_the_top_never_reaches_fails_step1(root):
    p = _design(root, 'unreached')
    result, report = _step1_verdict(p)
    assert (report['verdict'], result.status) == ('FAIL', 'FAIL'), report
    assert report['failure_codes'] == [CODE]
    assert report['declaration']['declared_catalog_reuse'] == ['serv']
    assert report['reached_ips'] == [] and report['instances'] == []
    assert CODE in report['reason'] and "['serv']" in report['reason']


def test_the_same_declaration_reached_and_pinned_still_passes(root):
    # The control: only the glue differs, and it instantiates the IP.
    p = _design(root, 'pinned')
    result, report = _step1_verdict(p)
    assert (report['verdict'], result.status) == ('PASS', 'PASS'), report
    assert report['reached_ips'] == ['serv']
    assert 'failure_codes' not in report


def test_an_undeclared_pulled_ip_is_not_held_to_reachability(root):
    # The pull record names serv, the docs do not: the design never said it
    # would use it, so an unreached copy is not a spec/RTL inconsistency.
    p = _design(root, 'unreached', {'description': 'a counter'})
    (p / 'phase2/stage1/rtl/serv_top.v').rename(p / 'phase2/stage1/rtl/ip.v')
    _put(p / 'plugin_output/declaration.json', {'ip_catalog_used': [
        {'ip_name': 'serv', 'status': 'PASS',
         'files_copied': [{'dest': str(p / 'phase2/stage1/rtl/ip.v')}]}]})
    result, report = _step1_verdict(p)
    assert report['declaration']['declared_catalog_reuse'] == []
    assert (report['verdict'], result.status) == ('PASS', 'PASS'), report
    assert report['reached_ips'] == []


def test_the_unsafe_path_keeps_its_own_code(root):
    # Reached but unsafe: the new code must not be charged, the old FAIL names
    # its own.
    p = _design(root, 'unsafe')
    _, report = _step1_verdict(p)
    assert report['verdict'] == 'FAIL'
    assert report['failure_codes'] == ['CATALOG_SYNTH_SAFE_VALUE_NOT_PINNED']


# -- F28b: reachability does not depend on synth-safe parameters -----------

#: picorv32's manifest carries no ``synth_safe_params``; this L2 matches it and
#: names it, so it is the design's declared reuse.
L2_DECLARES_PICORV32 = {'cpu_isa': 'rv32i', 'cpu_arch': 'multi-cycle',
                        'description': 'The design reuses the picorv32 core '
                                       'from the IP catalog.'}


def _picorv32_design(root, glue):
    p = _design(root, glue, L2_DECLARES_PICORV32)
    (p / 'phase2/stage1/rtl/serv_top.v').rename(p / 'phase2/stage1/rtl/picorv32.v')
    return p


def test_a_declared_ip_without_synth_safe_params_the_top_never_reaches_fails(root):
    p = _picorv32_design(root, 'unreached')
    result, report = _step1_verdict(p)
    assert report['declaration']['declared_catalog_reuse'] == ['picorv32']
    assert report['ips'] == []          # nothing to judge a value of ...
    assert (report['verdict'], result.status) == ('FAIL', 'FAIL'), report
    assert report['failure_codes'] == [CODE]   # ... and still owed to the top
    assert report['reached_ips'] == []


def test_a_declared_ip_without_synth_safe_params_that_is_reached_passes(root):
    p = _picorv32_design(root, 'pinned')
    result, report = _step1_verdict(p)
    assert (report['verdict'], result.status) == ('PASS', 'PASS'), report
    assert report['reached_ips'] == ['picorv32']
    assert report['instances'] == []


def test_the_runner_step_fails_a_declared_ip_without_params_it_never_reaches(root):
    import design_one_shot_runner as dor
    sr = dor.step_catalog_synth_safe_params(_picorv32_design(root, 'unreached'))
    assert (sr.status, sr.extras['failure_codes']) == ('FAIL', [CODE]), sr


def test_a_declared_ip_naming_no_rtl_file_is_refused_never_passed(root, monkeypatch):
    # The refusal arm: with no file to own a module, "not reached" cannot be
    # read, so the gate refuses (rc 1) before elaborating anything.
    import importlib
    gate = importlib.import_module('catalog_synth_safe_params_check')
    p = _picorv32_design(root, 'pinned')
    monkeypatch.setattr(gate, 'judged_ips', lambda project, declared: [
        {'ip_name': 'picorv32', 'files': [], 'params': {}, 'manifest': None,
         'declared': True}])
    assert gate.main([str(p)]) == 1
    report = json.loads((p / REPORT).read_text())
    assert (report['verdict'], 'yosys' in report) == ('NOT_MEASURED', False), report
    assert "['picorv32'] names no RTL file" in report['reason']


# -- ruling 1: the runner blocks on it inline ------------------------------

def test_the_runner_step_fails_on_the_gate_it_spawns(root):
    import design_one_shot_runner as dor
    p = _design(root, 'unreached')
    sr = dor.step_catalog_synth_safe_params(p)
    assert sr.status == 'FAIL', sr
    assert sr.extras['failure_codes'] == [CODE]
    assert sr.output_files == [REPORT]


def test_the_runner_step_passes_and_stands_down_as_the_gate_does(root):
    import design_one_shot_runner as dor
    assert dor.step_catalog_synth_safe_params(_design(root, 'pinned')).status == 'PASS'
    shutil.rmtree(root / 'proj')
    plain = _design(root, 'pinned', {'description': 'a toggle flip-flop'})
    sr = dor.step_catalog_synth_safe_params(plain)
    assert (sr.status, sr.declared_by) == ('NOT_APPLICABLE', 'DESIGN_DECLARED_NA'), sr


def test_the_runner_step_never_credits_an_unread_declaration(root):
    import design_one_shot_runner as dor
    p = _design(root, 'pinned')
    _put(p / 'phase1/generated_docs/L2_FRS.json', '{"cpu_isa": ')
    sr = dor.step_catalog_synth_safe_params(p)
    assert (sr.status, sr.reason_class) == ('NOT_MEASURED', 'input_absent'), sr






def _main_plan_appends(src):
    """``plan.append(<call>)`` targets inside ``main``, in source order.

    The audit credits the spawn INSIDE ``step_catalog_synth_safe_params``; it
    cannot see whether ``main`` ever calls that function (measured: replacing
    the call with ``pass`` left the audit at INLINE_BLOCKING). This reads it.
    """
    import ast
    main = next(f for f in ast.parse(src).body
                if isinstance(f, ast.FunctionDef) and f.name == 'main')
    calls = [n for n in ast.walk(main)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
             and n.func.attr == 'append' and isinstance(n.func.value, ast.Name)
             and n.func.value.id == 'plan' and n.args
             and isinstance(n.args[0], ast.Call)]
    return [ast.unparse(c.args[0].func)
            for c in sorted(calls, key=lambda c: (c.lineno, c.col_offset))]




def test_main_appends_the_step_after_the_rtl_is_staged_and_before_step2():
    order = _main_plan_appends((PROGRAMS / RUNNER).read_text())
    assert order.count('step_catalog_synth_safe_params') == 1, order
    at = order.index('step_catalog_synth_safe_params')
    # After the last step-1 stager (reused-IP consume and both alias emitters)
    # and before the step-2/3 determinism gates and synthesis.
    for before in ('step_reused_ip_consume', 'step_leaf_typo_aliases',
                   'step_reset_clock_variant_aliases'):
        assert order.index(before) < at, (before, order[:at + 1])
    assert at < order.index('step_lesson_consumption'), order


def test_mutation_an_uncalled_step_is_seen(tmp_path):
    text = (PROGRAMS / RUNNER).read_text()
    assert text.count(INLINE_CALL) == 1, 'the inline call moved; update INLINE_CALL'
    cut = text.replace(INLINE_CALL, '        pass\n')
    assert 'step_catalog_synth_safe_params' not in _main_plan_appends(cut)




def test_the_register_is_not_written_for_it():
    # Newly ENFORCED is not debt paid from a register it was never in: neither
    # register names the gate, and the shipped audit passes without a write.
    doc = json.loads((PROGRAMS / 'flow_gate_enforcement_baseline.json').read_text())
    for key in ('known', 'undeclared_known'):
        assert [e for e in doc[key] if e.endswith(f'::{GATE}')] == [], doc[key]
