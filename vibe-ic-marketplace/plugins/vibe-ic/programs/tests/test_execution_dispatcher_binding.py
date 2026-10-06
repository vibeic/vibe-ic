"""Production Step-16 dispatch controls; source/software evidence only."""
from dataclasses import replace
import json
from pathlib import Path
import sys

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))
import execution_modes as em
from programs.tests._execution_source_fixture import register_source_fixture, issued_context
import execution_policy as policy
import execution_adapters_release as release
from execution_provider_catalog import coverage_rows, current_source_identity
from programs.tests import test_execution_backend_f3 as backend
from programs.tests import test_execution_modes as decisions
from programs.tests.test_execution_receipt_chain import real_entry, isolated_transport


def arm():
    row = next(r for r in coverage_rows() if r['step_id'] == '16')
    return replace(release._adapter(
        row, current_source_identity(), {'metric': 'canonical_evidence', 'direction': 'max'},
        path='IC', available=True, route_receipt=None, declaration=None), tool_id='source_worker_16')


def wrapper(tmp_path, original, style, *, bind_helper=True):
    component = original.components[0]
    entry = tmp_path / 'alias.py'
    helper = tmp_path / 'dispatch_helper.py'
    bootstrap = 'import sys\nsys.path.insert(0, ' + repr(str(PROGRAMS)) + ')\n'
    files = []
    binary = component.argv[0]
    extra = ()
    if style in ('static', 'static_alias'):
        symbol = 'main as invoke' if style == 'static_alias' else 'main'
        call = 'invoke' if style == 'static_alias' else 'main'
        entry.write_text(bootstrap + f'from execution_release_worker import {symbol}\nraise SystemExit({call}())\n')
        files = [entry]
    elif style == 'dynamic_import':
        entry.write_text(bootstrap + "import importlib\nraise SystemExit(importlib.import_module('execution_release_worker').main())\n")
        files = [entry]
    elif style in ('nested_static', 'nested_dynamic'):
        helper.write_text(bootstrap + ('from execution_release_worker import main\n' if style == 'nested_static' else
                          "import importlib\ndef main():\n return importlib.import_module('execution_release_worker').main()\n"))
        entry.write_text('import sys\nsys.path.insert(0, ' + repr(str(tmp_path)) + ')\nfrom dispatch_helper import main\nraise SystemExit(main())\n')
        files = [entry, helper] if bind_helper else [entry]
    elif style == 'copied_worker':
        entry.write_bytes(Path(component.argv[1]).read_bytes())
        files = [entry]
    else:
        entry = Path(component.argv[1])
        if style == 'executable_symlink':
            link = tmp_path / 'python_alias'; link.symlink_to(binary); binary = str(link)
        elif style == 'entry_symlink':
            link = tmp_path / 'entry_alias.py'; link.symlink_to(entry); entry = link
        elif style == 'entry_path_alias':
            entry = entry.parent / '..' / 'programs' / entry.name
        elif style == 'duplicate_argv':
            extra = (str(entry), str(entry))
    return replace(original, arm_id='wrapped_release_16', tool_id='alias_label', engine_families=('alias_label',),
                   components=(replace(component, argv=(binary, str(entry), *component.argv[2:], *extra)),),
                   source_files={**original.source_files, **{str(p): em.digest(p) for p in files}}), helper


def controller(*arms, fixture_root=None):
    registry = em.Registry()
    for adapter in arms:
        if fixture_root is None:
            registry.register(adapter)
        else:
            register_source_fixture(registry, adapter, fixture_root=fixture_root)
    return em.Controller(registry, em.Budget(2, max(1024, sum(a.ram_mb for a in arms)), workers=2))


def issued_context16(tmp_path):
    return backend.context16(tmp_path)


def record(tmp_path, **facts):
    (tmp_path / 'control.json').write_text(json.dumps(facts, indent=2) + '\n')


@pytest.mark.parametrize('style', ['static', 'static_alias', 'nested_static', 'dynamic_import', 'nested_dynamic',
                                 'executable_symlink', 'entry_symlink', 'entry_path_alias', 'duplicate_argv', 'copied_worker'])
def test_actual_dispatcher_alias_cannot_create_another_eligible_arm(tmp_path, monkeypatch, style):
    original = arm(); alias, _ = wrapper(tmp_path, original, style)
    ctl = controller(original, alias, fixture_root=tmp_path); ctx = issued_context16(tmp_path); root = tmp_path / 'run'
    if style == 'copied_worker':
        monkeypatch.setenv('PYTHONPATH', str(PROGRAMS))
    plan = ctl.plan(ctx, 'ultra-mode')
    result = ctl.run(ctx, root, 'ultra-mode')
    receipt = json.loads((root / original.arm_id / 'receipt.json').read_text())
    record(tmp_path, style=style, plan=plan, result=result, receipt=receipt)
    assert len(plan['arms']) == 1
    assert plan['arms'] == ['release_16'], plan['arms']
    # This source-only fixture intentionally has no declared/resolved PDK, so
    # the canonical clock-plan gate remains a measured FAIL.  Alias admission
    # is the contract under test: one source-bound arm runs, and the alias may
    # neither create a second arm nor mask the real gate failure.
    assert result['candidate_statuses'] == {'release_16': 'FAIL'}
    assert receipt['reason'] == 'GATE_FAIL'
    assert receipt['evidence']['gates']['clock_plan_check'] == 'FAIL'
    assert len(receipt['processes']) == 1
    assert receipt['processes'][0]['rc'] == 0
    assert not (root / alias.arm_id).exists()


def test_unregistered_executed_helper_has_terminal_refusal(tmp_path):
    alias, helper = wrapper(tmp_path, arm(), 'nested_static', bind_helper=False)
    ctl = controller(alias, fixture_root=tmp_path); root = tmp_path / 'run'; ctx = backend.context16(tmp_path)
    try:
        result = ctl.run(ctx, root, 'ultra-mode')
        status = result['candidate_statuses'].get(alias.arm_id)
    except em.Refusal as exc:
        status = 'REFUSED'; reason = exc.code
    record(tmp_path, status=status, helper=str(helper), helper_registered=str(helper) in alias.source_files)
    assert status == 'REFUSED', status
    refusal = json.loads((root / 'refusal.json').read_text())
    assert refusal['reason'] == reason == 'PROVIDER_DEPENDENCY_UNBOUND'
    assert not (root / alias.arm_id).exists()


def test_bound_executed_helper_drift_refuses_adoption(tmp_path):
    alias, helper = wrapper(tmp_path, arm(), 'nested_static')
    ctl = controller(alias, fixture_root=tmp_path); root = tmp_path / 'run'
    ctx = backend.context16(tmp_path, native_clock=True)
    result = ctl.run(ctx, root, 'ultra-mode')
    assert result['candidate_statuses'] == {alias.arm_id: 'ELIGIBLE'}
    before = em.digest(helper)
    helper.write_text(helper.read_text() + '\n# bytes changed after issuance\n')
    try:
        adopted = ctl.adopt(ctx, root, decisions.choice(ctx, root, alias.arm_id)); status = adopted['status']
    except em.Refusal as exc:
        status = 'REFUSED'; reason = exc.code
    persisted = json.loads((root / 'adoption.json').read_text())
    record(tmp_path, status=status, persisted=persisted, result=result, before=before, after=em.digest(helper))
    assert status == 'REFUSED', status
    assert persisted['status'] == 'REFUSED' and persisted['reason'] == reason == 'PROVIDER_DEPENDENCY_UNBOUND'
    assert persisted['selected'] is None
    assert json.loads((root / alias.arm_id / 'receipt.json').read_text())['status'] == 'ELIGIBLE'


@pytest.mark.parametrize('style', ['opaque_side_effect', 'computed_import'])
def test_unproven_dispatch_has_terminal_refusal(tmp_path, style):
    alias, _ = wrapper(tmp_path, arm(), 'static')
    entry = Path(alias.components[0].argv[1])
    if style == 'opaque_side_effect':
        entry.write_text(entry.read_text().replace('raise SystemExit', "open('side_effect', 'w').write('unproven')\nraise SystemExit"))
    else:
        entry.write_text('import sys\nsys.path.insert(0, ' + repr(str(PROGRAMS)) + ')\n'
                         "import importlib\nname = 'execution_release_worker'\nraise SystemExit(importlib.import_module(name).main())\n")
    alias = replace(alias, source_files={**alias.source_files, str(entry): em.digest(entry)})
    ctl = controller(alias, fixture_root=tmp_path); root = tmp_path / 'run'
    result = ctl.run(backend.context16(tmp_path), root, 'ultra-mode')
    receipt = json.loads((root / alias.arm_id / 'receipt.json').read_text())
    record(tmp_path, style=style, result=result, receipt=receipt)
    assert result['candidate_statuses'] == {alias.arm_id: 'NOT_MEASURED'}
    assert receipt['reason'] == 'PROVIDER_DEPENDENCY_UNBOUND' and receipt['processes'] == []


def test_copied_dispatcher_dependency_shadow_still_refused(tmp_path, monkeypatch):
    from execution_provider_catalog import proven_dispatcher_closure
    worker = PROGRAMS / 'execution_release_worker.py'
    entry = tmp_path / 'copied_worker.py'
    entry.write_bytes(worker.read_bytes())
    monkeypatch.setenv('PYTHONPATH', str(PROGRAMS))
    (tmp_path / 'execution_release_rows.py').write_text('ROWS = {}\n')
    with pytest.raises(ValueError, match='copied worker import resolution differs'):
        proven_dispatcher_closure(entry, worker)
