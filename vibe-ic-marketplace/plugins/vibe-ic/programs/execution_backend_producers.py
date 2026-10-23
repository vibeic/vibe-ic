"""Explicit bounded backend producer sites. Never call main or step_pnr.

All native dispatch goes through F1's leased boundary in the worker. Existing
model/deck/RCX guards remain in the producer modules that own those semantics.
"""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor, as_completed
import tempfile
import time
import json
import os
import shutil
import shlex
import sys
from pathlib import Path
from types import SimpleNamespace

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

import _docker_memory as _dmem
import execution_backend_snapshot as snap
import execution_modes as em
from librelane_contract import Refusal as LibrelaneRefusal

PNR = 'phase3/stage3/pnr/'
RPT = 'reports/phase3/'

# These rows are produced by the native PnR producer itself.  Their flow
# programs are consumers, so they intentionally have no
# ``flow_declared_producer_run`` clause.  Keep this allow-list explicit: a
# missing declared producer on any other row must remain a refusal.
_NATIVE_CURRENT_STEP_ROWS = {
    '18': 'execution_backend_producers.produce_pnr',
    '19': 'execution_backend_producers._cts_split',
    '20': 'execution_backend_producers._cts_split',
}


def _native_registry_current_step_rows():
    """Return registry producers eligible for the current-step native seam.

    The catalog is the source of producer identity.  A row is eligible here
    only when it is a backend row with canonical outputs, names at least one
    producer site, and has no flow-declared producer clause.  The explicit
    18--20 map remains authoritative for its existing behavior.
    """
    try:
        from execution_provider_catalog import BACKEND_ROWS, BACKEND_SITES
        import flow_declared_producer_run as declared
        import yaml
        if not Path(declared.FLOW_YAML).is_file():
            return {}
        try:
            flow_doc = yaml.safe_load(Path(declared.FLOW_YAML).read_text(errors='replace'))
        except (OSError, ValueError, yaml.YAMLError):
            return {}
        if not isinstance(flow_doc, (dict, list)):
            return {}
        clauses = declared.declared_producer_clauses()
    except (ImportError, OSError, TypeError, ValueError, AttributeError):
        return {}
    if not isinstance(clauses, list):
        return {}
    declared_steps = {str(row.get('step')) for row in clauses
                      if isinstance(row, dict) and row.get('step') is not None}
    rows = {}
    for raw_sid, sites in BACKEND_SITES.items():
        sid = str(raw_sid)
        if sid in _NATIVE_CURRENT_STEP_ROWS or sid in declared_steps:
            continue
        row = BACKEND_ROWS.get(sid)
        canonical = row.get('canonical_row') if isinstance(row, dict) else None
        if (not isinstance(canonical, dict)
                or not canonical.get('required_outputs')
                or not isinstance(sites, (tuple, list)) or not sites
                or any(not isinstance(site, str) or not site for site in sites)):
            continue
        rows[sid] = list(sites)
    return rows


def _native_current_step_producer(step_id):
    sid = str(step_id)
    explicit = _NATIVE_CURRENT_STEP_ROWS.get(sid)
    if explicit is not None:
        return explicit
    return _native_registry_current_step_rows().get(sid)


def _native_output_identity(path):
    path = Path(path)
    try:
        if path.is_symlink() or not path.is_file() or not path.stat().st_size:
            return None
        stat = path.stat()
        return {'sha256': snap.sha(path), 'size': stat.st_size,
                'mtime_ns': stat.st_mtime_ns, 'st_dev': stat.st_dev,
                'st_ino': stat.st_ino}
    except (OSError, ValueError):
        return None


def _native_current_step_output_snapshot(project, step_id):
    """Capture output identities before the native producer is invoked."""
    try:
        from execution_adapters_backend import ROWS
        specs = ROWS[str(step_id)]['canonical_row'].get('required_outputs', ())
    except (KeyError, OSError, TypeError, ValueError):
        return {}
    before = {}
    for spec in specs:
        for pattern in str(spec).split(' OR '):
            for path in sorted(Path(project).glob(pattern.strip())):
                identity = _native_output_identity(path)
                if identity is not None:
                    before[str(path.relative_to(project))] = identity
    return before


def _step30_parallel_instruments(simulators, run_one):
    """Run distinct Step30 instruments and collect every sibling outcome.

    A single worker may refuse, time out, or raise after another worker has
    already measured a FAIL.  Collection therefore records that sibling as
    NOT_MEASURED and continues until every future has been reaped; callers can
    preserve the measured FAIL through the joint consumer.
    """
    names = tuple(simulators)
    if not names:
        return {}
    results = {}
    pool = ThreadPoolExecutor(max_workers=len(names),
                              thread_name_prefix='step30-instrument')
    try:
        futures = {pool.submit(run_one, name): name for name in names}
        for future in as_completed(futures):
            name = futures[future]
            started = time.monotonic_ns()
            try:
                value = future.result()
            except Exception as exc:  # preserve sibling evidence
                value = {'verdict': 'NOT_MEASURED',
                         'reason': type(exc).__name__ + ': ' + str(exc)}
            if isinstance(value, dict):
                value.setdefault('lifecycle', {})
                value['lifecycle'].setdefault('collector_pid', os.getpid())
                value['lifecycle'].setdefault('collected_ns', time.monotonic_ns())
                value['lifecycle'].setdefault('future_started_ns', started)
            results[name] = value
    finally:
        # Cancel work that has not entered a worker and wait for every running
        # sibling's supervised container to reach its terminal record.
        pool.shutdown(wait=True, cancel_futures=True)
    return {name: results[name] for name in names}



def _step30_rebind_private(value, private_project, project, simulator):
    """Translate private-project paths to retained canonical paths."""
    private_project, project = Path(private_project).resolve(), Path(project).resolve()
    arm = Path('phase3/tool_arms/30') / simulator
    if isinstance(value, Path):
        value = str(value)
    if isinstance(value, list):
        return [_step30_rebind_private(item, private_project, project, simulator) for item in value]
    if isinstance(value, tuple):
        return [_step30_rebind_private(item, private_project, project, simulator) for item in value]
    if isinstance(value, dict):
        return {key: _step30_rebind_private(item, private_project, project, simulator)
                for key, item in value.items()}
    if not isinstance(value, str) or not value.startswith('/'):
        return value
    candidate = Path(value)
    try:
        relative = candidate.resolve().relative_to(private_project)
    except (OSError, ValueError):
        return value
    destination = project / arm / relative.relative_to(arm) if relative.parts[:len(arm.parts)] == arm.parts else project / relative
    return str(destination)



def _step30_rebase_project_paths(private_project, original_project):
    """Rebase copied state manifests before any post-PNR consumer reads them."""
    private_project = Path(private_project).resolve()
    original_project = Path(original_project).resolve()

    def translate(value):
        if isinstance(value, list):
            return [translate(item) for item in value]
        if isinstance(value, dict):
            return {key: translate(item) for key, item in value.items()}
        if isinstance(value, str) and value.startswith('/'):
            try:
                relative = Path(value).resolve().relative_to(original_project)
            except (OSError, ValueError):
                return value
            return str(private_project / relative)
        return value

    for manifest in private_project.rglob('*.json'):
        try:
            before = json.loads(manifest.read_text())
            after = translate(before)
        except (OSError, ValueError):
            continue
        if after != before:
            snap.dump(manifest, after)



def _step30_retain_document(project, private_project, simulator, document):
    """Copy a private arm before TemporaryDirectory cleanup and validate paths."""
    source = Path(private_project) / 'phase3/tool_arms/30' / simulator
    target = Path(project) / 'phase3/tool_arms/30' / simulator
    if source.is_dir():
        shutil.copytree(source, target, symlinks=False, dirs_exist_ok=True)
    retained = _step30_rebind_private(document, private_project, project, simulator)
    missing = []
    hashes = {}

    def visit(value):
        if isinstance(value, dict):
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)
        elif isinstance(value, str) and value.startswith('/'):
            path = Path(value)
            if path.is_file():
                hashes[str(path)] = snap.sha(path)
            elif ('/phase3/' in value or '/reports/' in value or value.endswith(('.sp', '.spef', '.rpt', '.v', '.sdc'))):
                missing.append(value)
    visit(retained)
    if missing:
        raise em.Refusal('STEP30_RETAINED_ARTIFACT_ABSENT',
                         'inspected retained artifact paths: ' + repr(sorted(set(missing))))
    if isinstance(retained, dict):
        retained['retained_artifact_sha256'] = hashes
    return retained



def _step30_validate_retained_document(document):
    """Recheck every retained artifact hash at the joint-consumer boundary."""
    expected = document.get('retained_artifact_sha256') if isinstance(document, dict) else None
    if not isinstance(expected, dict):
        return
    for name, value in expected.items():
        path = Path(name)
        if path.is_symlink() or not path.is_file() or snap.sha(path) != value:
            raise em.Refusal('STEP30_RETAINED_ARTIFACT_MISMATCH', name)



def _step30_lifecycle(params, simulator, started_ns):
    """Expose the F1 command witness for one selected instrument."""
    lease_value = params.get('_step30_lease')
    if not isinstance(lease_value, str):
        return {'pid': None, 'cid': None, 'rc': None,
                'start_ns': started_ns, 'end_ns': time.monotonic_ns(),
                'status': 'NOT_MEASURED'}
    commands = Path(lease_value) / 'commands.jsonl'
    rows = []
    if commands.is_file():
        for line in commands.read_text().splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            argv = row.get('original_native_argv') or []
            if (row.get('started_ns', 0) >= started_ns
                    and simulator.lower() in {str(item).lower() for item in argv}):
                rows.append(row)
    return {'pid': rows[-1].get('pid') if rows else None,
            'cid': rows[-1].get('cid') if rows else None,
            'rc': rows[-1].get('rc') if rows else None,
            'start_ns': rows[0].get('started_ns', started_ns) if rows else started_ns,
            'end_ns': rows[-1].get('ended_ns', time.monotonic_ns()) if rows else time.monotonic_ns(),
            'commands': rows,
            'status': 'MEASURED' if rows else 'NOT_MEASURED'}



def _step30_private_projects(project, simulators, run_one):
    """Give concurrent instrument runs private report/output populations."""
    with tempfile.TemporaryDirectory(prefix='step30-instruments-') as folder:
        root = Path(folder)
        private = {}
        for simulator in simulators:
            target = root / simulator
            shutil.copytree(project, target, symlinks=False)
            _step30_rebase_project_paths(target, project)
            private[simulator] = target
        return _step30_parallel_instruments(
            simulators, lambda simulator: run_one(simulator, private[simulator]))



def _step30_merge_parallel(project, results, simulators, spice):
    """Merge private native documents before the mandatory joint consumer."""
    judgments = {}
    paths = {}
    details = {}
    for simulator in simulators:
        document = results.get(simulator)
        if not isinstance(document, dict):
            document = {'verdict': 'NOT_MEASURED', 'reason': 'instrument document absent'}
        try:
            _step30_validate_retained_document(document)
        except em.Refusal as exc:
            # A retained artifact refusal prevents PASS but cannot erase a
            # measured FAIL already collected from this instrument.
            measured_fail = (document.get('verdict') == 'FAIL' or
                (document.get('arms') or {}).get(simulator, {}).get('verdict') == 'FAIL')
            document = {'verdict': 'FAIL' if measured_fail else 'NOT_MEASURED',
                        'arms': {simulator: {'verdict': 'FAIL' if measured_fail else 'NOT_MEASURED',
                                             'reason': str(exc)}},
                        'reason': str(exc), 'lifecycle': document.get('lifecycle') or {}}
        judgment = (document.get('arms') or {}).get(simulator)
        if document.get('verdict') == 'FAIL':
            judgment = {**(judgment or {}), 'verdict': 'FAIL'}
        judgments[simulator] = judgment or {'verdict': 'FAIL' if document.get('verdict') == 'FAIL' else 'NOT_MEASURED',
                                             'reason': document.get('reason', 'instrument document absent')}
        detail = dict((document.get('detail') or {}).get(simulator) or {})
        if document.get('retained_artifact_sha256'):
            detail['retained_artifact_sha256'] = document['retained_artifact_sha256']
        if document.get('lifecycle'):
            detail['lifecycle'] = document['lifecycle']
        details[simulator] = detail
        paths[simulator] = (detail.get('base') or {}).get('paths') or []
    seed = next((results[name] for name in simulators if 'arms' in results[name]),
                results[simulators[0]])
    merged = dict(seed)
    merged['arms'] = judgments
    merged['detail'] = details
    merged.update(spice.step_verdict(judgments, paths))
    merged['mode'] = 'ultra'
    merged['instruments_concurrent'] = list(simulators)
    snap.dump(project / RPT / 'spice_path_tool.json', merged)
    return merged


def _require(path):
    p = Path(path)
    if not p.is_file() or p.is_symlink() or not p.stat().st_size:
        raise em.Refusal('BACKEND_PRODUCER_INPUT_ABSENT', str(p))
    return p


def _step24_spef(project, top, legacy):
    """Select the exact current STA SPEF before requiring the legacy alias.

    The current owner remains authoritative whenever its Step23 record is
    present.  Its ordinary validator binds State/config/image/PDK material and
    the selected corner mapping; this seam only confirms that the returned
    SPEF is a current, project-owned regular file.  Absence of the owner alone
    preserves the legacy Step24 route.
    """
    import librelane_ir_antenna as ir

    project = Path(project).resolve()
    if not (project / ir.CURRENT_STA_RECORD).is_file():
        return _require(legacy)
    import _opensta_current as current
    try:
        subject, tool = current.tool_subject(project, top)
    except (OSError, ValueError, KeyError, TypeError, LibrelaneRefusal) as exc:
        raise em.Refusal('BACKEND_CURRENT_SPEF_INVALID', str(exc)) from exc
    rows = [row for row in subject.get('inputs') or []
            if isinstance(row, dict) and row.get('role') == 'spef']
    if len(rows) != 1:
        raise em.Refusal('BACKEND_CURRENT_SPEF_AMBIGUOUS', str(rows))
    row = rows[0]
    named = Path(row.get('path') or '')
    try:
        spef = named.resolve(strict=True)
    except OSError as exc:
        raise em.Refusal('BACKEND_CURRENT_SPEF_MISSING', str(named)) from exc
    if (named.is_symlink() or not spef.is_file()
            or not spef.is_relative_to(project)
            or row.get('resolved') != str(spef)
            or row.get('sha256') != snap.sha(spef)):
        code = ('BACKEND_CURRENT_SPEF_FOREIGN' if not spef.is_relative_to(project)
                else 'BACKEND_CURRENT_SPEF_CHANGED')
        raise em.Refusal(code, str(named))
    try:
        state = json.loads(Path(tool['state']).read_text())
        mapped = state.get('spef') or {}
        values = [mapped] if isinstance(mapped, str) else list(mapped.values())
        selected = {(Path(value) if Path(value).is_absolute()
                     else project / value).resolve(strict=True) for value in values}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise em.Refusal('BACKEND_CURRENT_SPEF_STATE_INVALID', str(exc)) from exc
    if spef not in selected:
        raise em.Refusal('BACKEND_CURRENT_SPEF_MAPPING_MISMATCH', str(spef))
    return spef


def _copy(source, target):
    source = _require(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)


def _step15_sdc(project):
    """Resolve the physical SDC published by the bounded Step 15 producer."""
    project = Path(project)
    pnr = project / PNR
    record_path = pnr / 'step15_state.json'
    if not record_path.is_file():
        return _require(pnr / 'constraint.sdc')
    try:
        record = json.loads(record_path.read_text())
        if not isinstance(record, dict):
            raise ValueError('record must be a mapping')
        source = pnr / 'constraint.sdc'
        views = record.get('views')
        if not isinstance(views, dict):
            raise ValueError('views missing')
        # Schema/1 records predating the physical-deck split bind their native
        # SDC directly to the canonical PNR deck.  Accept only that exact,
        # contained regular file; do not invent an upstream/derived relation.
        if 'sdc_derived' not in views and 'upstream_sdc' not in record:
            if record.get('schema') != 'vibeic/step15-state-handoff/1':
                raise ValueError('legacy schema invalid')
            legacy = views.get('sdc')
            resolved = source.resolve()
            if (not isinstance(legacy, dict)
                    or legacy.get('path') != str(source.relative_to(project))
                    or not resolved.is_relative_to(project.resolve())
                    or source.is_symlink() or not source.is_file()
                    or not source.stat().st_size
                    or legacy.get('sha256') != snap.sha(source)):
                raise ValueError('legacy SDC binding changed')
            # Reuse the existing raw state/PDN/handoff/view verifier.  The
            # legacy deck is native; it is never relabelled as upstream.
            _read_step15_bounded_state(project)
            return _require(source)
        info = views['sdc_derived']
        upstream = record['upstream_sdc']
        expected = project / PNR / 'step15.constraint.sdc'
        if (not isinstance(info, dict) or not isinstance(upstream, dict)
                or info.get('path') != str(expected.relative_to(project))):
            raise ValueError('non-canonical derived path')
        derived = expected
        if (not derived.is_file() or derived.is_symlink()
                or not derived.resolve().is_relative_to(project.resolve())):
            raise ValueError('derived SDC path invalid')
        if upstream['path'] != str(source.relative_to(project)) or upstream['sha256'] != snap.sha(source):
            raise ValueError('upstream constraint changed')
        if info['sha256'] != snap.sha(derived):
            raise ValueError('derived SDC changed')
        # An intact deck cannot outlive the native handoff that published it.
        # Apply the same lineage check used for the legacy physical deck.
        _read_step15_bounded_state(project)
        return _require(derived)
    except em.Refusal as exc:
        raise em.Refusal('BACKEND_STEP15_SDC_BINDING_CHANGED', str(record_path)) from exc
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        raise em.Refusal('BACKEND_STEP15_SDC_BINDING_CHANGED', str(record_path)) from exc


def _parameters(project, params):
    import phase3_one_shot_runner as R
    import librelane_contract as ll
    missing = [name for name in ("pdk_name", "image_id", "pdk_root", "top")
               if not params.get(name)]
    if missing:
        raise em.Refusal('BACKEND_PRODUCER_PARAMS_UNBOUND', ','.join(missing))
    pdk = R._detect_pdk(project, params['pdk_name'])
    if pdk is None or str(pdk.name) != params['pdk_name']:
        raise em.Refusal('BACKEND_PDK_RESOLUTION_FAILED', params['pdk_name'])
    staging = ll.pdk_root_resolution(project, pdk.name, image=params['image_id'])
    if Path(staging['path']).resolve() != Path(params['pdk_root']).resolve():
        raise em.Refusal('BACKEND_PDK_ROOT_CHANGED', str(staging['path']))
    R._host_staged_liberty(pdk, staging)
    R.set_invocation_provenance_sink(project)
    # F1's native_boundary converts legacy dispatch into admitted Docker run.
    container = params.get('container', '')
    return R, ll, pdk, container


def _retained_synth_census(project, params, R, ll, pdk):
    """Measure the retained mapped netlist, without invoking synthesis.

    The staged Liberty is a host path, not a mount of the legacy persistent
    container. Give this short native measurement its explicit project/PDK
    mounts, with identical paths so its generated Tcl and receipt agree.
    """
    import drv_stage_receipts as drv_stages
    import uuid
    if drv_stages.current_run(project) is None:
        return None
    evidence = drv_stages.abc_script_path(project).parent
    receipt = project / drv_stages.RECEIPT_DIR / 'synth.json'
    if evidence.is_dir() or receipt.is_file():
        archive = project / 'reports/phase3/drv_stage_history' / (
            'retained-synth-census-' + uuid.uuid4().hex)
        archive.mkdir(parents=True)
        if evidence.is_dir():
            shutil.copytree(evidence, archive / 'evidence' / 'synth')
        if receipt.is_file():
            shutil.copy2(receipt, archive / receipt.name)
    root = Path(params['pdk_root']).resolve()
    project = Path(project).resolve()
    image = params['image_id']

    def execute(cmd, marker, log_path):
        network, command = ll.native_tool_command(image, shlex.split(cmd))
        result = ll.run_container([
            'docker', 'run', *_dmem.docker_memory_flags(), '--rm', '--network', network,
            '-v', f'{project}:{project}', '-v', f'{root}:{root}:ro',
            image, '--skip', *command], supervised=True, log=log_path)
        return result.returncode, result.stdout, result.stderr

    return drv_stages.synth_stage_supervised(
        project, netlist=R._pl.synth_dir(project) / f"{params['top']}_synth.v",
        top=params['top'], liberties=[str(pdk.liberty)],
        sdc=project / PNR / 'constraint.sdc', to_container=str,
        execute=execute)


def _current_physical_sdc(project, params):
    """Read the SDC already adopted by placement, without redoing that work.

    Native write_sdc may rewrite the deck. Its state lineage proves adoption;
    only the canonical source is compared to the accepted bridge's hash.
    """
    import step_output_collector as versions
    import librelane_contract as ll
    project = Path(project).resolve()
    accepted = versions.latest_pass(project, '17') if params.get('execution_mode') == 'default' else None
    if not accepted or not any(row.get('rel', '').endswith('/sdc_derivation.json')
                               for row in accepted.get('written_files', [])):
        return _step15_sdc(project)
    try:
        if not accepted or not accepted.get('canonical_pass'):
            raise ValueError('placement has not accepted a current bridge')
        written = {row['rel']: row['sha256'] for row in accepted['written_files']}
        def adopted(path):
            path = _require(project / path)
            if written.get(str(path.relative_to(project))) != snap.sha(path):
                raise ValueError('placement did not adopt these bytes: ' + str(path))
            return path
        ledger_path = adopted(project / RPT / 'execution-backend-17.json')
        ledger = json.loads(ledger_path.read_text())
        initial = _require(project / ledger['initial_state'])
        derivation_path = adopted(initial.parent / 'sdc_derivation.json')
        derivation = json.loads(derivation_path.read_text())
        bound = _read_step15_bounded_state(project)
        if (derivation['schema'] != 'vibeic/step17-sdc-derivation/1'
                or derivation['step15_record_sha256'] != snap.sha(project / PNR / 'step15_state.json')
                or derivation['retained_views'] != bound['record']['views']):
            raise ValueError('retained floorplan changed after placement adoption')
        current = derivation['current_sdc']
        sdc = _require(project / PNR / 'constraint.sdc')
        provenance_path = sdc.parent / 'constraint_sdc_provenance.json'
        provenance = json.loads(provenance_path.read_text())
        import _path_layout as layout
        step7 = json.loads((layout.constraints_dir(project) / 'asic_sdc.json').read_text())
        # Refresh may change author diagnostics/code fingerprints while the
        # consumed deck is identical. Validate material source/deck identity,
        # not transient regenerated_by_step7_producer metadata.
        if (current['path'] != str(sdc.relative_to(project)) or current['sha256'] != snap.sha(sdc)
                or provenance['deck_sha256'] != current['sha256']
                or provenance['step7_sdc'] != step7['path']
                or provenance['step7_sha256'] != step7['sha256']
                or provenance['step7_deck_sha256'] != step7['deck_sha256']
                or step7['sha256'] != snap.sha(_require(project / step7['path']))):
            raise ValueError('adopted canonical SDC source changed')
        previous = snap.sha(initial)
        if (ledger['initial_sha256'] != previous or derivation['state']['sha256'] != previous
                or (project / derivation['state']['path']).resolve() != initial.resolve()):
            raise ValueError('placement initial state changed')
        states = ledger['states']
        if not states or [row['step'] for row in states] != ledger['ordered_steps']:
            raise ValueError('placement native chain is absent')
        for row in states:
            state = _require(project / row['state'])
            receipt = ll.validate_step_receipt(state.parent, row['step'])
            if (receipt['input']['state'] != previous or receipt['input']['image'] != params['image_id']
                    or row['sha256'] != snap.sha(state)):
                raise ValueError('placement native chain changed')
            for name, expected in receipt['input'].get('config_files', {}).items():
                path = Path(name)
                if path.is_relative_to(ll.PDK_GUEST_ROOT):
                    host = Path(params['pdk_root']) / path.relative_to(ll.PDK_GUEST_ROOT)
                    if snap.sha(_require(host)) != expected:
                        raise ValueError('placement PDK input changed: ' + name)
            previous = snap.sha(state)
        if snap.sha(_predecessor_state(project, 'placed.def')) != previous:
            raise ValueError('placement handoff does not belong to this bridge')
        return sdc
    except (OSError, ValueError, KeyError, TypeError, em.Refusal, ll.Refusal) as exc:
        raise em.Refusal('BACKEND_CURRENT_SDC_UNBOUND', str(exc)) from exc


def _views(project, top, predecessor, params=None):
    import phase3_one_shot_runner as R
    nl, _, _ = R.pnr_input_netlist(project, top)
    routed = project / PNR / f'{top}_pnr.v'
    return {'def': _require(project / PNR / predecessor),
            'nl': _require(routed if routed.is_file() else nl),
            'sdc': _current_physical_sdc(project, params) if params is not None else _step15_sdc(project)}


def _predecessor_state(project, predecessor):
    """Read the native checkpoint actually handed to the preceding row."""
    names = {
        'placed.def': ('librelane_placement_handoff.json', 'def'),
        'post_spare.def': ('librelane_spare_handoff.json', 'def'),
        'post_cts.def': ('librelane_cts_handoff.json', 'post_cts_def'),
        'post_hold.def': ('librelane_cts_hold_handoff.json', 'post_hold_def'),
    }
    receipt_name, view_name = names[predecessor]
    try:
        document = json.loads(_require(project / RPT / receipt_name).read_text())
        view = document['views'][view_name]
        canonical = _require(project / PNR / predecessor)
        if (Path(view['dest']).resolve() != canonical.resolve()
                and (project / view['dest']).resolve() != canonical.resolve()):
            raise ValueError('receipt names another predecessor DEF')
        if view['dest_sha256'] != snap.sha(canonical):
            raise ValueError('predecessor DEF changed after its handoff')
        raw = document.get('measured_state', document.get('state'))
        expected = document.get('measured_state_sha256', document.get('state_sha256'))
        if predecessor == 'post_cts.def':
            # Hold always starts at immutable CTS, including on a retry.
            source = Path(view['source'])
            original_root = None
            if source.is_absolute() and not source.is_relative_to(project.resolve()):
                from execution_adapters_backend import _cts_handoff_input_files
                _, original_root = _cts_handoff_input_files(project)
                source = project / source.relative_to(original_root)
            source = _require(project / source)
            if snap.sha(source) != view['source_sha256'] or snap.sha(source) != snap.sha(canonical):
                raise ValueError('CTS source differs from its handed checkpoint')
        state = _require(project / raw)
        if expected != snap.sha(state):
            raise ValueError('predecessor native state changed after its handoff')
        if predecessor == 'post_cts.def' and original_root is not None:
            # Preserve the measured state and receipt bytes. Only the next
            # producer's input state is derived into its staged namespace.
            def relocate(value):
                if isinstance(value, dict):
                    return {k: relocate(v) if k != 'metrics' else v for k, v in value.items()}
                if isinstance(value, list):
                    return [relocate(v) for v in value]
                if isinstance(value, str) and value.startswith('/'):
                    return str(project / Path(value).relative_to(original_root))
                return value
            import librelane_contract as ll
            mapped = project / 'phase3/librelane/execution-backend-20-config/cts-state-in.json'
            ll.write_json(mapped, relocate(json.loads(state.read_text())))
            return mapped
        return state
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise em.Refusal('BACKEND_PREDECESSOR_STATE_UNBOUND',
                         f'{predecessor}: {exc}') from exc


def _cts_selected_predecessor(project, sid):
    """Bind CTS to the latest selected Flow109 physical producer."""
    default = 'post_spare.def' if sid == '19' else 'post_cts.def'
    if sid != '19':
        return default
    import flow109
    try:
        selected = flow109.active_native_predecessor(project, sid)
    except flow109.Flow109Error as exc:
        raise em.Refusal(exc.code, exc.detail) from exc
    if selected is None:
        return default
    allowed = {'17': 'placed.def', '18': 'post_spare.def'}
    native = selected['native_step_id']
    predecessor = allowed.get(native)
    expected_rel = PNR + predecessor if predecessor else None
    if predecessor is None or selected['output'] != expected_rel:
        raise em.Refusal('BACKEND_CTS_PREDECESSOR_UNSUPPORTED', str(selected))
    receipt_path = project / 'reports/phase3/default_steps' / native / 'backend_result.json'
    try:
        receipt = json.loads(_require(receipt_path).read_text())
        actual = _require(project / expected_rel)
        expected = snap.sha(actual)
        if (receipt.get('verdict') != 'PASS'
                or receipt.get('producer_verdict') != 'PASS'
                or receipt.get('outputs', {}).get(expected_rel) != expected):
            raise ValueError('canonical predecessor PASS/output binding is absent or stale')
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise em.Refusal('BACKEND_CTS_PREDECESSOR_UNBOUND',
                         f'{selected["row_id"]}/{native}: {exc}') from exc
    return predecessor


def _step17_current_sdc_bridge(project, params, bound):
    """Adopt current constraints without reclassifying the retained floorplan.

    Only Step7's named SDC/record may differ from the accepted Step15 input
    set. Its physical handoff and every other project/PDK input remain bound.
    This authorizes a new placement measurement, never an old timing PASS.
    """
    import step_output_collector as versions
    from _ppa import timing
    import librelane_contract as ll
    project = Path(project).resolve()
    record = bound['record']
    try:
        if params.get('step_id') != '17' or params.get('execution_mode') != 'default':
            raise ValueError('only Default placement may derive this input')
        retained = versions.latest_pass(project, '15')
        if not retained or not retained.get('canonical_pass') or not retained.get('inputs'):
            raise ValueError('accepted Step15 inputs are absent')
        state_path = project / PNR / 'step15_state.json'
        saved_state = next(row for row in retained['written_files']
                           if row['rel'] == str(state_path.relative_to(project)))
        if saved_state['sha256'] != snap.sha(state_path):
            raise ValueError('accepted Step15 handoff differs')
        import phase3_one_shot_runner as R
        # Match the canonical front-door author's PDK representation. Native
        # transport's _parameters host-rebases Liberty paths (including source
        # comments); it must not become a second SDC author here.
        pdk = R._detect_pdk(project, params['pdk_name'])
        if pdk is None or str(pdk.name) != params['pdk_name']:
            raise ValueError('canonical PDK resolution failed')
        container = params.get('container', '')
        current, why = timing.read_step7_asic_sdc(R, project, params['top'], pdk)
        if current is None:
            raise ValueError('current canonical Step7 SDC required: ' + why)
        record_rel = str((R._pl.constraints_dir(project) / timing.ASIC_SDC_RECORD).relative_to(project))
        archive = versions._versions_root(project) / retained['folder'] / 'inputs'
        previous_record = archive / record_rel
        def digest(value):
            return value.get('sha256') if isinstance(value, dict) else value
        if snap.sha(_require(previous_record)) != digest(retained['inputs'].get(record_rel)):
            raise ValueError('retained Step7 record is unbound')
        previous = json.loads(previous_record.read_text())
        if previous['path'] != current['path']:
            raise ValueError('canonical Step7 path changed')
        sdc_rel = current['path']
        if (previous['sha256'] != digest(retained['inputs'].get(sdc_rel))
                or snap.sha(_require(archive / sdc_rel)) != previous['sha256']):
            raise ValueError('retained Step7 SDC is unbound')
        changed, retained_count = [], 0
        for rel, identity in retained['inputs'].items():
            if snap.sha(_require(project / rel)) != digest(identity):
                if rel not in (record_rel, sdc_rel):
                    raise ValueError('non-SDC Step15 input changed: ' + rel)
                changed.append(rel)
            else:
                retained_count += 1
        pnr_sdc = _require(project / PNR / 'constraint.sdc')
        upstream = record['upstream_sdc']
        if upstream['path'] != str(pnr_sdc.relative_to(project)):
            raise ValueError('old physical SDC source is not canonical')
        # Reuse the canonical derivation read-only: its Step7 record was just
        # validated, so no author or upstream native producer is invoked.
        derived = timing.asic_sdc_for_pnr(R, project, params['top'], pdk, container)
        provenance = json.loads((pnr_sdc.parent / 'constraint_sdc_provenance.json').read_text())
        if (pnr_sdc.read_text() != derived['text']
                or provenance['step7_sha256'] != current['sha256']
                or provenance['deck_sha256'] != snap.sha(pnr_sdc)):
            raise ValueError('PNR deck is not the current canonical derivation')
        handoff = json.loads((project / record['handoff']['path']).read_text())
        native_folder = Path(handoff['views']['odb']['source']).parent
        native = ll.validate_step_receipt(native_folder, 'OpenROAD.GeneratePDN')
        if (snap.sha(native_folder / 'state_out.json') != record['raw_state_sha256']
                or native['input']['image'] != params['image_id']):
            raise ValueError('native floorplan identity changed')
        config_inputs = native['input']['config_files']
        if not config_inputs or not any(Path(name).is_relative_to(ll.PDK_GUEST_ROOT)
                                        for name in config_inputs):
            raise ValueError('retained PDK inputs are absent')
        for name, expected in config_inputs.items():
            path = Path(name)
            if path == pnr_sdc:
                if expected != upstream['sha256']:
                    raise ValueError('native old SDC differs from Step15 source')
                continue
            if path.is_relative_to(ll.PDK_GUEST_ROOT):
                path = Path(params['pdk_root']) / path.relative_to(ll.PDK_GUEST_ROOT)
            if snap.sha(_require(path)) != expected:
                raise ValueError('Step15 PDK/config input changed: ' + name)
        return pnr_sdc, {
            'schema': 'vibeic/step17-sdc-derivation/1',
            'purpose': 'new placement measurement with retained floorplan',
            'step15_record_sha256': snap.sha(state_path),
            'retained_input_count': retained_count, 'changed_inputs': sorted(changed),
            'old_upstream_sdc': upstream, 'old_physical_sdc': record['views']['sdc_derived'],
            'current_sdc': {'path': str(pnr_sdc.relative_to(project)), 'sha256': snap.sha(pnr_sdc)},
            'step7_record_sha256': snap.sha(project / record_rel),
            'pnr_provenance_sha256': snap.sha(pnr_sdc.parent / 'constraint_sdc_provenance.json'),
            'native_receipt_sha256': snap.sha(native_folder / 'vibeic_receipt.json'),
            'retained_views': record['views']}
    except (OSError, ValueError, KeyError, TypeError, StopIteration, em.Refusal, ll.Refusal) as exc:
        raise em.Refusal('BACKEND_STEP17_SDC_DERIVATION_REFUSED', str(exc)) from exc


def _state_chain(project, params, ids, predecessor, overlay=None, *, respect_flow_gates=False):
    import librelane_contract as ll
    import phase3_one_shot_runner as R
    image, pdk, root = params['image_id'], params['pdk_name'], Path(params['pdk_root'])
    lane = 'execution-backend-' + params['step_id'].replace('.', '-')
    configs = ll.resolve_step_configs(project, image, pdk, ids,
                    pdk_root=root, folder=lane + '-config', overlay=overlay)
    if respect_flow_gates:
        gated_off = ll.flow_gated_off(project / 'phase3/librelane' / (lane + '-config'))
        ids = [sid for sid in ids if sid not in gated_off]
    configs, _ = R._resolved_cell_policy(configs, root, pdk)
    if params['step_id'] == '21':
        import librelane_route as route
        spare_record = project / PNR / 'spare_cells.json'
        spares = json.loads(spare_record.read_text()) if spare_record.is_file() else {}
        reserved = [row['name'] for row in spares.get('instances', []) if row.get('name')]
        configs[route.NVR] = route.named_violation_config(
            R, project=project, configs=configs, ids=ids, lane=lane,
            cfg_dir=project / 'phase3/librelane' / (lane + '-config'),
            reserved_instance_names=reserved or None)
    mounts = [(root.resolve(), ll.PDK_GUEST_ROOT)]
    if predecessor in ('placed.def', 'post_spare.def', 'post_hold.def') and not params.get('state_in'):
        # Carry the actual database/netlist/metrics; rebuilding from an old
        # top_pnr.v can silently import a previous run's spares or clock tree.
        params = {**params, 'state_in': str(_predecessor_state(project, predecessor))}
    if params.get('state_in'):
        state = _require(Path(params['state_in']))
    elif predecessor == 'floorplan.def':
        bound = _read_step15_bounded_state(project)
        # The validated LibreLane handoff is now the source of truth for the
        # canonical DEF/ODB targets.  Use the existing state bridge to read
        # those targets, preserving its path mapping and view checks.
        upstream = bound['record'].get('upstream_sdc') or {}
        current_sdc = project / PNR / 'constraint.sdc'
        derivation = None
        if (params.get('step_id') == '17' and params.get('execution_mode') == 'default'
                and upstream.get('sha256') and current_sdc.is_file()
                and upstream['sha256'] != snap.sha(current_sdc)):
            sdc, derivation = _step17_current_sdc_bridge(project, params, bound)
        else:
            sdc = _step15_sdc(project)
        bridge_dir = project / 'phase3/librelane' / (lane + '-config/bridge')
        if derivation is not None:
            bridge_dir = bridge_dir / ('sdc-resume-' + str(time.time_ns()))
        state = ll.state_from_direct(
            project, image, configs[ids[0]],
            {**{name: path for name, path in bound['views'].items()
                if name != 'sdc_derived'}, 'sdc': sdc}, bridge_dir,
            chain=[configs[s] for s in ids[1:]], mounts=mounts,
            metrics=bound['metrics'], metrics_source=bound['metrics_source'])
        if derivation is not None:
            derivation['state'] = {'path': str(state.relative_to(project)), 'sha256': snap.sha(state)}
            snap.dump(bridge_dir / 'sdc_derivation.json', derivation)
    else:
        state = ll.state_from_direct(project, image, configs[ids[0]],
                _views(project, params['top'], predecessor, params),
                project / 'phase3/librelane' / (lane + '-config/bridge'),
                chain=[configs[s] for s in ids[1:]], mounts=mounts)
    folders = ll.run_chain(project, image, [(s, configs[s], state) for s in ids],
                          mounts=mounts, lane=lane, pdk_root=ll.PDK_GUEST_ROOT)
    snap.dump(project / RPT / (lane + '.json'),
              {'ordered_steps': ids, 'initial_state': str(state),
               'initial_sha256': snap.sha(state),
               'states': [{'step': sid, 'state': str(f / 'state_out.json'),
                           'sha256': snap.sha(f / 'state_out.json')} for sid, f in zip(ids, folders)]})
    return ll, configs, dict(zip(ids, folders))


def _handoff(project, ll, folder, names):
    target = {view: project / name for view, name in names.items()}
    return ll.handoff_to_direct(folder / 'state_out.json', target,
               project / RPT / ('execution-backend-' + folder.parent.name + '-handoff.json'))


def _publish_step17_timing_script(project, ll, folder, config, image):
    """Publish the selected native session's actual OpenROAD subject bytes."""
    try:
        folder = Path(folder).resolve()
        receipt = ll.validate_step_receipt(folder, 'Vibeic.PostGPLFanoutClosure')
        if (receipt['input']['image'] != image
                or receipt['input']['config'] != snap.sha(config)):
            raise ValueError('selected native image/config differs')
        record_path = folder / 'pnr_postgpl_timing.json'
        if (record_path.is_symlink()
                or receipt['sha256'].get(record_path.name) != snap.sha(record_path)):
            raise ValueError('native script-body record is not receipt-bound')
        record = json.loads(record_path.read_text())
        subject = folder / 'pnr_postgpl_timing.tcl'
        commands = folder / 'COMMANDS'
        if (record['script'] != subject.name or subject.is_symlink()
                or not subject.is_file() or not subject.stat().st_size
                or record['sha256'] != snap.sha(subject)
                or record['commands_sha256'] != snap.sha(commands)):
            raise ValueError('executed subject or command journal changed')
        journals = [shlex.split(line) for line in commands.read_text().splitlines()
                    if line.strip()]
        if (len(journals) != 1 or not journals[0]
                or Path(journals[0][-1]).resolve() != subject):
            raise ValueError('native COMMANDS names another subject')
        target = project / PNR / subject.name
        _copy(subject, target)
    except (ll.Refusal, OSError, ValueError, KeyError, TypeError) as exc:
        raise em.Refusal('BACKEND_PLACEMENT_TIMING_SCRIPT_UNBOUND', str(exc)) from exc


def _read_step15_bounded_state(project):
    """Verify portable native lineage and return the actual Step17 input views."""
    project = Path(project).resolve()
    record_path = project / PNR / 'step15_state.json'
    try:
        record = json.loads(_require(record_path).read_text())
        if record.get('schema') != 'vibeic/step15-state-handoff/1':
            raise ValueError('state handoff schema')
    except (OSError, ValueError, TypeError, AttributeError, em.Refusal) as exc:
        raise em.Refusal('BACKEND_STEP15_STATE_ABSENT', str(record_path)) from exc

    def verify(info, code):
        if not isinstance(info, dict) or not isinstance(info.get('path'), str):
            raise em.Refusal(code + '_ABSENT', str(info))
        rel = Path(info['path'])
        path = project / rel
        if (rel.is_absolute() or '..' in rel.parts or not path.resolve().is_relative_to(project)
                or path.is_symlink() or not path.is_file() or not path.stat().st_size):
            raise em.Refusal(code + '_ABSENT', str(path))
        if snap.sha(path) != info.get('sha256'):
            raise em.Refusal(code + '_CHANGED', str(path))
        return path

    native = verify(record.get('native_state'), 'BACKEND_STEP15_STATE')
    pdn = verify(record.get('pdn_state'), 'BACKEND_STEP15_PDN_STATE')
    handoff = verify(record.get('handoff'), 'LL_HANDOFF')
    try:
        raw = json.loads(handoff.read_text())
    except (OSError, ValueError, TypeError) as exc:
        raise em.Refusal('LL_HANDOFF_ABSENT', str(handoff)) from exc
    if not isinstance(raw, dict):
        raise em.Refusal('LL_HANDOFF_ABSENT', str(handoff))
    raw_views = raw.get('views')
    if not isinstance(raw_views, dict):
        raise em.Refusal('LL_HANDOFF_VIEW_ABSENT', str(handoff))
    if raw.get('state_sha256') != snap.sha(native):
        raise em.Refusal('LL_HANDOFF_STATE_CHANGED', str(handoff))
    if (raw.get('state_sha256') != record.get('raw_state_sha256')
            or raw.get('state_sha256') != record.get('handoff_state_sha256')):
        raise em.Refusal('LL_HANDOFF_STATE_CHANGED', str(handoff))
    views = {name: verify(info, 'LL_HANDOFF_VIEW')
             for name, info in record.get('views', {}).items()}
    canonical_views = {
        'def': Path(PNR) / 'floorplan.def',
        'odb': Path(PNR) / 'librelane_floorplan.odb',
    }
    for name in ('def', 'odb'):
        published = (record.get('views') or {}).get(name, {})
        if Path(published.get('path', '')) != canonical_views[name]:
            raise em.Refusal('LL_HANDOFF_VIEW_CHANGED', name)
        info = raw_views.get(name, {})
        handoff_view = (record.get('handoff_views') or {}).get(name, {})
        if (name not in views or info.get('source_sha256') != snap.sha(views[name])
                or info.get('dest_sha256') != snap.sha(views[name])
                or info != handoff_view):
            raise em.Refusal('LL_HANDOFF_VIEW_CHANGED', name)
    marker = json.loads(_require(project / PNR / 'pdn.done').read_text())
    pdn_info = record.get('pdn_state') or {}
    if (marker.get('state') != pdn_info.get('path')
            or marker.get('sha256') != snap.sha(pdn)
            or marker.get('sha256') != record.get('raw_pdn_state_sha256')):
        raise em.Refusal('BACKEND_STEP15_PDN_MARKER_CHANGED', str(pdn))
    return {'views': views, 'metrics': json.loads(native.read_text()).get('metrics', {}),
            'metrics_source': str(record_path), 'record': record}


def _publish_step15_bounded_state(project, row):
    """Export exact native state/receipt/view bytes into the carried PNR closure."""
    project = Path(project).resolve()
    extras = row.extras if isinstance(row.extras, dict) else {}
    if not extras.get('bounded_state'):
        raise em.Refusal('BACKEND_STEP15_STATE_MODE_UNBOUND', 'producer row')
    def source(key):
        path = _require(extras[key])
        if not path.resolve().is_relative_to(project):
            raise em.Refusal('BACKEND_STEP15_STATE_ESCAPE', str(path))
        return path
    native, pdn, handoff = (source(key) for key in ('native_state', 'pdn_state', 'handoff'))
    document = json.loads(native.read_text())
    raw_handoff = json.loads(handoff.read_text())
    raw_views = raw_handoff.get('views')
    if not isinstance(raw_views, dict):
        raise em.Refusal('LL_HANDOFF_VIEW_ABSENT', str(handoff))
    native_sha = snap.sha(native)
    if raw_handoff.get('state_sha256') != native_sha:
        raise em.Refusal('LL_HANDOFF_STATE_CHANGED', str(handoff))
    # The native helper has already handed these exact bytes into the
    # canonical PNR closure.  Require that boundary rather than copying an
    # isolated LibreLane path here; Step17 must consume the actual handoff.
    views = {}
    for name, key, filename in (
            ('def', 'floorplan', 'floorplan.def'),
            ('odb', 'odb', 'librelane_floorplan.odb')):
        path = source(key)
        target = project / PNR / filename
        if path.resolve() != target.resolve():
            raise em.Refusal('LL_HANDOFF_VIEW_ABSENT', str(target))
        views[name] = target
    for name in ('def', 'odb'):
        info = raw_views.get(name, {})
        if (info.get('source_sha256') != snap.sha(views[name])
                or info.get('dest_sha256') != snap.sha(views[name])):
            raise em.Refusal('LL_HANDOFF_VIEW_CHANGED', name)
    if any(name not in raw_views for name in ('def', 'odb')):
        raise em.Refusal('LL_HANDOFF_VIEW_ABSENT', str(handoff))
    # Native chip-top netlist, SDC and power views, rather than the bare-core
    # synth views, travel with the ODB to the next isolated bounded worker.
    upstream_sdc = _require(project / PNR / 'constraint.sdc')
    native_sdc = document.get('sdc')
    if not native_sdc:
        raise em.Refusal('BACKEND_STEP15_SDC_ABSENT', str(native))
    native_sdc = _require(native_sdc)
    if not native_sdc.resolve().is_relative_to(project):
        raise em.Refusal('BACKEND_STEP15_STATE_ESCAPE', str(native_sdc))
    derived_sdc = project / PNR / 'step15.constraint.sdc'
    _copy(native_sdc, derived_sdc)
    views['sdc_derived'] = derived_sdc
    for name, filename in (('nl', 'step15.nl.v'), ('pnl', 'step15.pnl.v'), ('json_h', 'step15.h.json')):
        if document.get(name):
            path = _require(document[name])
            if not path.resolve().is_relative_to(project):
                raise em.Refusal('BACKEND_STEP15_STATE_ESCAPE', str(path))
            target = project / PNR / filename
            _copy(path, target)
            views[name] = target
    def exported(path, filename):
        target = project / PNR / filename
        _copy(path, target)
        return {'path': str(target.relative_to(project)), 'sha256': snap.sha(target)}
    pdn_sha = snap.sha(pdn)
    record = {
        'schema': 'vibeic/step15-state-handoff/1',
        'producer': 'execution_backend_producers.produce_pnr',
        'raw_state_sha256': native_sha,
        'raw_pdn_state_sha256': pdn_sha,
        'handoff_state_sha256': raw_handoff.get('state_sha256'),
        'handoff_views': {name: raw_views[name] for name in ('def', 'odb')},
        'native_state': exported(native, 'step15_native_state.json'),
        'pdn_state': exported(pdn, 'step15_pdn_state.json'),
        'handoff': exported(handoff, 'step15_handoff.json'),
        'views': {name: {'path': str(path.relative_to(project)), 'sha256': snap.sha(path)}
                  for name, path in views.items()},
        'upstream_sdc': {'path': str(upstream_sdc.relative_to(project)),
                         'sha256': snap.sha(upstream_sdc)},
    }
    snap.dump(project / PNR / 'step15_state.json', record)
    # Same marker contract as the existing non-pad branch, bound to the
    # actual completed OpenROAD.GeneratePDN state (the exported copy is exact).
    snap.dump(project / PNR / 'pdn.done', {
        'state': str((project / PNR / 'step15_pdn_state.json').relative_to(project)),
        'sha256': pdn_sha,
    })
    _read_step15_bounded_state(project)
    return record


def _logs(project, folders, name='openroad.log'):
    target = project / PNR / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(''.join('# ' + str(f.relative_to(project)) + '/' + p.name + '\n' +
                     p.read_text(errors='replace') + '\n' for f in folders for p in sorted(f.glob('*.log'))))
    return target


def _step37_route(params):
    """Bind the worker's issued arm to the actual Step-37 runner route."""
    arm = os.environ.get('VIBEIC_ARM_ID')
    if arm is None:
        route = params.get('streamout_route')
        return route if route in ('direct', 'librelane') else None
    route = {'backend_37_librelane': 'librelane',
             'backend_37_direct': 'direct'}.get(arm)
    issued = os.environ.get('VIBEIC_STEP37_ROUTE')
    if (route is None or issued != route or
            params.get('route') != route or params.get('streamout_route') != route):
        raise em.Refusal('BACKEND_STEP37_ROUTE_UNBOUND', arm)
    return route


def _step37_streamout_result(project, route, row):
    """Persist and enforce the streamout engine emitted by the runner."""
    allowed = {'librelane': ('magic', 'klayout'), 'direct': ('magic',)}[route]
    observed = row.extras.get('streamout_engine')
    arm = os.environ.get('VIBEIC_ARM_ID') or 'backend_37_' + route
    receipt = project / RPT / 'step37_streamout' / 'vibeic_receipt.json'
    snap.dump(receipt, {
        'schema': 'vibeic/step37-streamout-engine/1',
        'step_id': '37', 'arm_id': arm, 'route': route,
        'allowed_streamout_engines': list(allowed),
        'streamout_engine': observed, 'status': row.status,
        'detail': row.detail,
    })
    if arm != 'backend_37_' + route or observed not in allowed:
        mismatch = (
            'BACKEND_STEP37_STREAMOUT_ENGINE_MISMATCH: '
            f'arm={arm} route={route} allowed={allowed} observed={observed!r}')
        return {'verdict': 'FAIL' if row.status == 'FAIL' else 'NOT_MEASURED',
                'detail': mismatch + '; ' + row.detail,
                'streamout_engine': observed, 'streamout_route': route}
    return {'verdict': row.status, 'detail': row.detail,
            'streamout_engine': observed, 'streamout_route': route}


def _step17_expected_inputs(paths):
    expected = {}
    for value in paths:
        if value is None:
            continue
        path = Path(value)
        if path.is_file() and not path.is_symlink():
            expected[str(path.resolve())] = snap.sha(path)
    return expected



def _step17_add_bound_json_paths(expected, path):
    """Add real absolute file references declared by a source-owned JSON."""
    try:
        document = json.loads(Path(path).read_text())
    except (OSError, ValueError, TypeError):
        return
    pending = [document]
    while pending:
        value = pending.pop()
        if isinstance(value, dict):
            pending.extend(value.values())
        elif isinstance(value, (list, tuple)):
            pending.extend(value)
        elif isinstance(value, str) and value.startswith('/'):
            candidate = Path(value)
            if candidate.is_file() and not candidate.is_symlink():
                expected[str(candidate.resolve())] = snap.sha(candidate)



def _step17_direct_inputs(project, params, R, ll, pdk):
    """Resolve the issued Step15 -> direct-placement input seam."""
    root = project / '.execution-backend/17-direct'
    root.mkdir(parents=True, exist_ok=True)
    pnr = project / PNR
    floorplan = _require(pnr / 'floorplan.def')
    nl, _, _ = R.pnr_input_netlist(project, params['top'])
    nl = _require(nl)
    sdc = _step15_sdc(project)
    state_value = params.get('step15_state') or params.get('state_in')
    state = Path(state_value) if state_value else None
    if state is None:
        state = root / 'step15_state.json'
        snap.dump(state, {'def': str(floorplan.resolve()), 'nl': str(nl.resolve()),
                          'sdc': str(sdc.resolve())})
    state = _require(state)
    image, pdk_root = params['image_id'], Path(params['pdk_root'])
    config_value = params.get('sta_config')
    config = Path(config_value) if config_value else None
    if config is None:
        config = ll.resolve_step_configs(project, image, pdk.name,
            ['OpenROAD.STAMidPNR'], pdk_root=pdk_root,
            folder='execution-backend-17-direct-config')['OpenROAD.STAMidPNR']
    config = _require(config)
    prep_value = params.get('builder_preparation_input')
    builder_value = params.get('builder_input')
    prep = Path(prep_value) if prep_value else None
    builder = Path(builder_value) if builder_value else None
    mounts = [(pdk_root / pdk.name, '/pdk/' + pdk.name)]
    if builder is None:
        if prep is None:
            prep = pnr / 'builder.preparation.input.json'
        prep = _require(prep)
        derived = root / 'builder-derivation'
        row_inputs = {'floorplan': floorplan, 'sdc': sdc, 'netlist': nl}
        source_paths = [R.__file__, state, prep, floorplan, sdc, nl,
                        pdk.tech_lef, pdk.cell_lef, pdk.liberty,
                        ll.views_path(config)]
        import flow_compliance_check as fcc
        source_paths.append(fcc.DEFAULT_FLOW_DEF)
        source_paths.extend(path for root_name in ('input', 'generated_docs')
                            for path in (project / root_name).rglob('*')
                            if path.is_file() and not path.is_symlink())
        expected = _step17_expected_inputs(source_paths)
        _step17_add_bound_json_paths(expected, prep)
        built = R.prepare_direct_pnr_builder_input(
            project, step_id='17', predecessor_state=state,
            preparation_input=prep, spare_plan=None, row_inputs=row_inputs,
            expected_inputs=expected,
            mounts=mounts, arm_dir=derived)
        builder = Path(built['builder_input'])
        expected = dict(built['expected_inputs'])
    else:
        builder = _require(builder)
        expected = _step17_expected_inputs([R.__file__, state, config,
                                            ll.views_path(config), builder,
                                            floorplan, sdc, nl])
    # The direct helper's host() verifier checks every literal PDK view and
    # sidecar it consumes; include the resolved config and builder references.
    for path in (config, ll.views_path(config), builder):
        try:
            document = json.loads(path.read_text())
        except (OSError, ValueError, TypeError):
            document = {}
        stack = [document]
        while stack:
            value = stack.pop()
            if isinstance(value, dict):
                stack.extend(value.values())
            elif isinstance(value, (list, tuple)):
                stack.extend(value)
            elif isinstance(value, str) and value.startswith('/'):
                candidate = Path(value)
                if candidate.is_file() and not candidate.is_symlink():
                    expected[str(candidate.resolve())] = snap.sha(candidate)
    expected.update(_step17_expected_inputs([state, config,
                                             ll.views_path(config), builder,
                                             floorplan, sdc, nl, R.__file__]))
    return dict(step15_state=state, sta_config=config, builder_input=builder,
                spare_plan=None, expected_inputs=expected, mounts=mounts,
                arm_dir=root / 'openroad-arm')



def _produce_step17_direct(project, params, R, ll, pdk):
    if not all(callable(getattr(R, name, None)) for name in (
            'prepare_direct_pnr_builder_input', 'prepare_step17_direct_placement',
            'run_step17_direct_placement')):
        raise em.Refusal('DIRECT_PROVIDER_DEPENDENCY_UNAVAILABLE', '17')
    direct = _step17_direct_inputs(project, params, R, ll, pdk)
    result = R.run_step17_direct_placement(
        project, image=params['image_id'],
        # native_boundary() has replaced this exact LibreLane seam with F1's
        # leased Docker issuer; the direct arm must use the same admission.
        native_run=ll.run_container,
        step15_state=direct['step15_state'], sta_config=direct['sta_config'],
        builder_input=direct['builder_input'], spare_plan=direct['spare_plan'],
        expected_inputs=direct['expected_inputs'], mounts=direct['mounts'],
        arm_dir=direct['arm_dir'])
    arm = Path(direct['arm_dir'])
    pnr = project / PNR
    pnr.mkdir(parents=True, exist_ok=True)
    for source, target in ((arm / 'placed.def', pnr / 'placed.def'),
                           (arm / 'placed.odb', pnr / 'librelane_placed.odb'),
                           (arm / 'placed.v', pnr / (params['top'] + '_pnr.v')),
                           (arm / 'placement.tcl', pnr / 'pnr.tcl'),
                           (arm / 'openroad.log', pnr / 'openroad.log'),
                           (arm / 'timing.rpt', pnr / 'timing.rpt')):
        if source.is_file() and not source.is_symlink():
            _copy(source, target)
    producer = result.get('producer_verdict', result.get('verdict', 'NOT_MEASURED'))
    measurement = result.get('measurement') or {}
    return {**result, 'verdict': result.get('verdict', 'NOT_MEASURED'),
            'producer_verdict': producer,
            'measurement_verdict': measurement.get('verdict', 'NOT_MEASURED'),
            'canonical_validation_pending': True,
            'detail': 'direct Step17 OpenROAD producer; canonical gates consume its current outputs'}


def _cts_split(project, params, R, ll, pdk, overlay):
    """Selected predecessor -> CTS or resizer -> one measurement per corner.

    This preserves the original CTS/hold handoff reader's schema. Step 20
    inherits the actual step-19 state; it never re-runs CTS or floorplan.
    """
    import librelane_cts_hold as ch
    sid = params['step_id']
    root, image = Path(params['pdk_root']), params['image_id']
    lane = 'execution-backend-' + sid
    ids = (['OpenROAD.CTS', 'Vibeic.ClockPathDriveSizing', 'Vibeic.ExternalCaptureLaunchRetap']
           if sid == '19' else ['OpenROAD.ResizerTimingPostCTS'])
    scene = ch.signoff_scene_sdc(R, _current_physical_sdc(project, params),
                                project / 'phase3/librelane' / (lane + '-config'))
    overlay['PNR_SDC_FILE'] = (str(scene), 'selected SDC + accepted signoff OCV scene')
    configs = ll.resolve_step_configs(project, image, pdk.name, ids + ['OpenROAD.STAMidPNR'],
                    pdk_root=root, folder=lane + '-config', overlay=overlay)
    configs, policy_steps = R._resolved_cell_policy(configs, root, pdk.name,
                required=('OpenROAD.CTS',) if sid == '19' else ('OpenROAD.ResizerTimingPostCTS',))
    corners = json.loads(configs['OpenROAD.STAMidPNR'].read_text()).get('STA_CORNERS') or []
    if not corners:
        raise em.Refusal('BACKEND_CTS_HOLD_CORNERS_UNSTATED', sid)
    predecessor = _cts_selected_predecessor(project, sid)
    if sid == '19':
        instances = configs['OpenROAD.CTS'].parent / 'pre_cts.instances'
        components = R._parse_def_components(_require(project / PNR / predecessor))
        if not components:
            raise em.Refusal('BACKEND_PRE_CTS_INSTANCE_POPULATION_EMPTY', sid)
        instances.write_text('\n'.join(name for name, _ in components) + '\n')
        sizing = instances.with_name('clock_path_drive_sizing.body.tcl')
        sizing.write_text(R._clock_path_drive_sizing_tcl())
        for step in ids[1:]:
            updates = {'PNR_CORNERS': (corners, 'resolved STA_CORNERS'),
                       'VIBEIC_CLKPATH_PRECTS_INSTANCES': (str(instances), 'selected placed DEF instance population')}
            if step == 'Vibeic.ClockPathDriveSizing':
                updates['VIBEIC_CLKPATH_SIZING_TCL'] = (str(sizing), 'accepted runner clock path sizing body')
            configs[step] = ll.derive_step_config(configs[step], configs[step], updates)
    chain = [(sid, configs[sid]) for sid in ids]
    for corner in corners:
        native = configs['OpenROAD.STAMidPNR']
        selected = native.with_name('OpenROAD.STAMidPNR@' + corner + '.json')
        ll.derive_step_config(native, selected, {'PNR_CORNERS': ([corner], 'resolved STA_CORNERS, one measurement per corner')})
        chain.append(('OpenROAD.STAMidPNR', selected))
    mounts = [(root.resolve(), ll.PDK_GUEST_ROOT)]
    state = (_require(Path(params['state_in'])) if params.get('state_in') else
             _predecessor_state(project, predecessor))
    folders = ll.run_chain(project, image, [(s, cfg, state) for s, cfg in chain],
                          mounts=mounts, lane=lane, pdk_root=ll.PDK_GUEST_ROOT)
    production = folders[len(ids) - 1]
    names = {'def': PNR + ('post_cts.def' if sid == '19' else 'post_hold.def'),
             'odb': PNR + ('post_cts.odb' if sid == '19' else 'post_hold.odb')}
    handoff = _handoff(project, ll, production, names)
    cts_path = project / RPT / 'librelane_cts_handoff.json'
    receipt_path = cts_path if sid == '19' else project / RPT / 'librelane_cts_hold_handoff.json'
    previous = json.loads(_require(cts_path).read_text()) if sid == '20' else {}
    receipt = {**previous, 'program': 'execution_backend_producers._cts_split',
               'modes': {'19': 'librelane', '20': 'librelane'}, 'selected': 'librelane',
               'image': image, 'steps': [s for s, _ in chain], 'corners': corners,
               'chain': {**previous.get('chain', {}), **{s: str(f.relative_to(project)) for (s, _), f in zip(chain, folders)}},
               'measured_state': str((folders[-1] / 'state_out.json').relative_to(project)),
               'measured_state_sha256': snap.sha(folders[-1] / 'state_out.json'),
               'views': dict(previous.get('views', {}))}
    for view, info in handoff['views'].items():
        receipt['views']['post_' + ('cts' if sid == '19' else 'hold') + '_' + view] = {
            **info, 'dest': str(Path(info['dest']).relative_to(project))}
    if sid == '19':
        report = _require(folders[0] / 'cts.rpt')
        destination = project / 'phase3/stage3/cts/clock_tree.rpt'
        _copy(report, destination)
        receipt['views']['cts_rpt'] = {'source': str(report), 'source_sha256': snap.sha(report),
                                     'dest': str(destination.relative_to(project)), 'dest_sha256': snap.sha(destination)}
    else:
        before_area = json.loads(state.read_text()).get('metrics', {}).get('design__instance__area__stdcell')
        after_metrics = json.loads((production / 'state_out.json').read_text()).get('metrics', {})
        snap.dump(project / RPT / 'pnr/hold_area.json', {
            'program': 'execution_backend_producers._cts_split', 'before_total_area': before_area,
            'after_total_area': after_metrics.get('design__instance__area__stdcell'),
            'hold_buffer_count': after_metrics.get('design__instance__count__hold_buffer'),
            'setup_buffer_count': after_metrics.get('design__instance__count__setup_buffer'),
            'sources': {'before': str(state.relative_to(project)), 'after': str((production / 'state_out.json').relative_to(project))},
            'numerator_basis': 'accepted resizer stdcell-area delta; no pad-area dilution'})
    snap.dump(receipt_path, receipt)
    _logs(project, folders)
    return {'verdict': 'PASS', 'detail': 'native CTS/hold chain measured every resolved corner; gates judge its values'}


def _produce_direct_pnr(project, params, R):
    """Run the source-owned OpenROAD provider for the two complete rows.

    The caller must issue the typed builder inputs and their digests.  This
    deliberately refuses an inferred or copied predecessor, so a missing
    direct-input bundle remains NOT_MEASURED rather than becoming a green
    alias of the LibreLane route.
    """
    sid = str(params['step_id'])
    if sid not in ('15', '19'):
        raise em.Refusal('DIRECT_PROVIDER_ROW_UNSUPPORTED', sid)
    spec = params.get('direct_inputs')
    if not isinstance(spec, dict):
        raise em.Refusal('DIRECT_PROVIDER_INPUTS_UNISSUED', sid)
    required = ('predecessor_state', 'preparation_input', 'builder_input',
                'expected_inputs', 'row_inputs')
    if any(k not in spec for k in required):
        raise em.Refusal('DIRECT_PROVIDER_INPUTS_INCOMPLETE', sid)
    if not callable(getattr(R, 'run_direct_pnr_row', None)):
        raise em.Refusal('DIRECT_PROVIDER_DEPENDENCY_UNAVAILABLE', sid)
    def path(key):
        value = spec[key]
        if not isinstance(value, (str, Path)):
            raise em.Refusal('DIRECT_PROVIDER_INPUT_PATH_UNSTATED', key)
        return Path(value)
    if not spec.get('execution_arm_dir') and not spec.get('arm_dir'):
        raise em.Refusal('DIRECT_PROVIDER_INPUTS_INCOMPLETE', sid)
    arm = path('execution_arm_dir') if spec.get('execution_arm_dir') else path('arm_dir')
    if arm.exists() and any(arm.iterdir()):
        raise em.Refusal('DIRECT_PROVIDER_ARM_NOT_PRIVATE', str(arm))
    arm.mkdir(parents=True, exist_ok=True)
    import librelane_contract as lc
    mounts = [(Path(a), str(b)) for a, b in spec.get('mounts', [])]
    result = R.run_direct_pnr_row(
        project, image=str(params['image_id']), native_run=lc.run_container,
        step_id=sid, predecessor_state=path('predecessor_state'),
        builder_input=path('builder_input'),
        spare_plan=path('spare_plan') if spec.get('spare_plan') else None,
        row_inputs={k: Path(v) for k, v in spec['row_inputs'].items()},
        expected_inputs={str(k): str(v) for k, v in spec['expected_inputs'].items()},
        mounts=mounts, arm_dir=arm)
    if result.get('verdict') == 'FAIL':
        return result
    canonical = ('phase3/stage3/pnr/floorplan.def', 'phase3/stage3/pnr/pdn.tcl',
                 'phase3/stage3/pnr/pdn.done') if sid == '15' else (
                 'phase3/stage3/pnr/post_cts.def', 'phase3/stage3/cts/clock_tree.rpt')
    missing = []
    for name in canonical:
        source = arm / name
        if source.is_file() and source.stat().st_size:
            target = project / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        elif name.endswith(('.tcl', '.done')) and sid == '15':
            continue
        else:
            missing.append(name)
    if missing or result.get('canonical_missing'):
        result['verdict'] = 'NOT_MEASURED'
        result['missing'] = sorted(set(result.get('missing', []) + missing))
    return result


def produce_pnr(project, params):
    R, ll, pdk, container = _parameters(project, params)
    sid, top = params['step_id'], params['top']
    overlay = {k: tuple(v) for k, v in (params.get('overlay') or {}).items()}
    if sid == '15':
        # Keep the runner's input-derived die/core and pad geometry front door.
        if 'die_um' not in params or 'util' not in params:
            raise em.Refusal('BACKEND_FLOORPLAN_OBJECTIVES_UNSTATED', sid)
        prep = R.step_prepnr(project, top, pdk, container,
                            params['die_um'], params['util'])
        # The pad producer is part of Step 15, but its electrical record is an
        # input to Step 7's ASIC SDC.  On the first chip-path invocation the
        # preparation has therefore completed all of its own physical work
        # while its read-only Step-7 seam quite correctly reports stale.  Heal
        # that one typed seam here, in this same Default invocation, through
        # Step 7's canonical author; requiring an external 7..14 rerun creates
        # a permanent 7 -> 15 -> 7 cycle whenever the pad plan changes.
        #
        # Do not turn any other NOT_MEASURED result into a retry.  The
        # producer, floorplan and pad assignment must all have completed, and
        # the only absent item must be the input-bound SDC path.
        _prep_extras = prep.extras if isinstance(prep.extras, dict) else {}
        _prep_chip = _prep_extras.get('chip_top') or {}
        _prep_sdc = _prep_extras.get('sdc') or {}
        _prep_floorplan = _prep_extras.get('floorplan')
        _prep_assign = _prep_extras.get('pad_assignment') or {}
        _sdc_only_pending = (
            prep.status == 'NOT_MEASURED'
            and _prep_chip.get('status') == 'PASS'
            and _prep_sdc.get('path') is None
            and str(_prep_sdc.get('basis', '')).startswith('SDC_SEAM_PENDING:')
            and isinstance(_prep_floorplan, dict)
            and (not R._chip_path_requests_pad_ring(project)
                 or _prep_assign.get('status') == 'PASS'))
        if _sdc_only_pending:
            from _ppa import timing
            current_sdc = timing.asic_sdc_for_pnr(
                R, project, top, pdk, container)
            timing.publish_pnr_sdc(current_sdc, project / PNR)
            seam_path, seam_basis = R._prepnr_constraint_file(
                project, top, pdk)
            if seam_path is not None:
                prep.status = 'PASS'
                prep.reason_class = ''
                prep.extras['sdc'] = {'path': str(seam_path),
                                      'basis': seam_basis}
                prep.detail = (prep.detail.rsplit('; ', 1)[0] +
                               '; ' + seam_basis)
        if prep.status != 'PASS':
            return {'verdict': prep.status, 'detail': prep.detail}
        # Preparation can refresh the chip wrapper.  Resolve Step 7's deck
        # and its physical pad derivation now, before the native floorplan
        # reads constraint.sdc; a previous run's file is not this row's input.
        from _ppa import timing
        current_sdc = timing.asic_sdc_for_pnr(R, project, top, pdk, container)
        timing.publish_pnr_sdc(current_sdc, project / PNR)
        # Complete the existing synthesis receipt under Step 7's current SDC.
        # Default does not enter the enclosing step_pnr that used to do this.
        _retained_synth_census(project, params, R, ll, pdk)
        if R._chip_path_requests_pad_ring(project):
            # The accepted ring-pinned producer retains its tap coverage,
            # master free-run exclusion, pad connection and PDN semantics.
            row, _ = R._prepare_librelane_floorplan_for_route(
                project, pdk, container, project / PNR, '',
                {'15': 'librelane', '15.5ic': 'librelane'},
                bounded_state=True)
            if row.status == 'PASS':
                _publish_step15_bounded_state(project, row)
            return {'verdict': row.status, 'detail': row.detail}
        ids = ['Yosys.JsonHeader'] + ll.flow_segment(params['image_id'],
                    'OpenROAD.Floorplan', 'Odb.RemovePDNObstructions', flow='Classic')
        # Floorplan starts from a netlist, not from a fabricated DEF bridge.
        nl, _, _ = R.pnr_input_netlist(project, top)
        configs = ll.resolve_step_configs(project, params['image_id'], pdk.name, ids,
                     pdk_root=Path(params['pdk_root']), folder='execution-backend-15-config', overlay=overlay)
        configs, _ = R._resolved_cell_policy(configs, Path(params['pdk_root']), pdk.name)
        mounts = [(Path(params['pdk_root']).resolve(), ll.PDK_GUEST_ROOT)]
        state = ll.state_from_direct(project, params['image_id'], configs[ids[0]],
                     {'nl': _require(nl)}, project / 'phase3/librelane/execution-backend-15-config/bridge',
                     chain=[configs[s] for s in ids[1:]], mounts=mounts)
        folders = ll.run_chain(project, params['image_id'], [(s, configs[s], state) for s in ids],
                              mounts=mounts, lane='execution-backend-15', pdk_root=ll.PDK_GUEST_ROOT)
        by = dict(zip(ids, folders))
        _handoff(project, ll, folders[-1], {'def': PNR + 'floorplan.def',
                                           'odb': PNR + 'librelane_floorplan.odb'})
        handoff_path = (project / RPT /
                        ('execution-backend-' + folders[-1].parent.name +
                         '-handoff.json'))
        pdn_step = by.get('OpenROAD.GeneratePDN')
        if pdn_step is None:
            raise em.Refusal('BACKEND_PDN_NOT_EXECUTED', sid)
        tap = by.get('OpenROAD.TapEndcapInsertion')
        if tap:
            tap_def = Path(json.loads((tap / 'state_out.json').read_text())['def'])
            rc, detail = R._librelane_tap_coverage(project, pdk, container, tap_def, 'lattice')
            if rc:
                return {'verdict': 'FAIL' if rc == 1 else 'NOT_MEASURED', 'detail': detail}
        # The done marker is a bound completed native PDN state, not rc0 alone.
        snap.dump(project / PNR / 'pdn.done', {'state': str(pdn_step / 'state_out.json'),
                  'sha256': snap.sha(pdn_step / 'state_out.json')})
        # Core-only Step 15 uses the same portable state/DEF/ODB contract as
        # the pad path.  Step17 receives only phase3/stage3/pnr, so export the
        # actual native state lineage and handoff receipt there as well.
        _publish_step15_bounded_state(project, SimpleNamespace(extras={
            'bounded_state': True,
            'native_state': str(folders[-1] / 'state_out.json'),
            'pdn_state': str(pdn_step / 'state_out.json'),
            'floorplan': str(project / PNR / 'floorplan.def'),
            'odb': str(project / PNR / 'librelane_floorplan.odb'),
            'handoff': str(handoff_path),
        }))
    elif sid == '15.5ic':
        # The Chip chain places pads before tap/PDN, as LibreLane requires.
        # Describe and independently check that actual native ring here;
        # dispatching the direct placer again changes the selected tool and
        # can reject orientations the native PadRing already honoured.
        bound = _read_step15_bounded_state(project)
        try:
            handoff = json.loads(_require(
                project / RPT / 'librelane_padring_handoff.json').read_text())
            ring_state = _require(Path(handoff['state']))
            floorplan_source = Path(bound['record']['handoff_views']['def']['source'])
            if ring_state.parent.parent != floorplan_source.parent.parent:
                raise ValueError('PadRing belongs to another native floorplan chain')
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise em.Refusal('BACKEND_PADRING_STATE_CHANGED', str(exc)) from exc
        row = R.step_pad_ring_gen(project, container, pdk,
                                  librelane_state=ring_state)
        return {'verdict': row.status, 'detail': row.detail}
    elif sid == '17':
        ids = ll.flow_segment(params['image_id'], 'OpenROAD.GlobalPlacement', 'OpenROAD.DetailedPlacement')
        at = ids.index('OpenROAD.RepairDesignPostGPL')
        ids.insert(at + 1, 'Vibeic.PostGPLFanoutClosure')
        ll, configs, by = _state_chain(project, params, ids, 'floorplan.def', overlay)
        handoff = _handoff(project, ll, by[ids[-1]], {
            'def': PNR + 'placed.def', 'odb': PNR + 'librelane_placed.odb'})
        snap.dump(project / RPT / 'librelane_placement_handoff.json', handoff)
        _publish_step17_timing_script(project, ll, by['Vibeic.PostGPLFanoutClosure'],
                                     configs['Vibeic.PostGPLFanoutClosure'], params['image_id'])
        _logs(project, by.values(), 'librelane_placement.log')
    elif sid == '18':
        ids = ['Vibeic.InsertSpareCells']
        params = {**params, 'state_in': str(_predecessor_state(project, 'placed.def'))}
        if params.get('spare_density') is not None:
            overlay['VIBEIC_SPARE_DENSITY'] = (
                params['spare_density'], 'runner --spare-density')
        ll, configs, by = _state_chain(project, params, ids, 'placed.def', overlay)
        handoff = _handoff(project, ll, by[ids[-1]], {
            'def': PNR + 'post_spare.def', 'odb': PNR + 'post_spare.odb'})
        snap.dump(project / RPT / 'librelane_spare_handoff.json', handoff)
        _logs(project, by.values(), 'librelane_spare_cells.log')
        reports = list(by[ids[-1]].rglob('spare_cells.json'))
        if len(reports) != 1:
            raise em.Refusal('BACKEND_SPARE_NATIVE_RECORD_ABSENT', str(reports))
        _copy(reports[0], project / PNR / 'spare_cells.json')
        import spare_cell_preservation_check as spare_preservation
        native_plan = json.loads(reports[0].read_text())
        if native_plan.get('spare_pads'):
            handoff['insertion_provenance'] = spare_preservation.native_insertion_provenance(
                project, native_plan)
            snap.dump(project / RPT / 'librelane_spare_handoff.json', handoff)
        R._emit_spare_cell_coverage(project, project / PNR / 'spare_cells.json')
    elif sid in ('19', '20'):
        return _cts_split(project, params, R, ll, pdk, overlay)
    elif sid == '21':
        import librelane_route as route
        ids = route.chain_ids(params['image_id'], canonical_routing_only=True)
        overlay = {**route.POST_GRT_DESIGN_REPAIR, **overlay}
        ll, configs, by = _state_chain(project, params, ids, 'post_hold.def', overlay,
                                       respect_flow_gates=True)
        _handoff(project, ll, list(by.values())[-1], {'def': PNR + 'routed.def', 'odb': PNR + 'routed.odb',
                                         'nl': PNR + top + '_pnr.v'})
        log = _logs(project, by.values())
        # The reroute step's own saved report describes the final native
        # route. The detailed router's earlier report predates that repair.
        final_drc = by[route.NVR] / 'named_viol_after.drc'
        # A completed zero-violation native run writes an empty DRC report.
        # Its measurement is qualified by the transcript/DEF receipt below,
        # not by requiring a violation to make the file nonempty.
        if not final_drc.is_file() or final_drc.is_symlink():
            raise em.Refusal('BACKEND_ROUTER_REPORT_ABSENT', str(final_drc))
        shutil.copyfile(final_drc, project / PNR / R.ROUTER_DRC_REPORT_NAME)
        # Use the accepted receipt emitter; an incomplete routing transcript
        # refuses instead of creating a zero-error router certificate.
        if R._write_router_drc_receipt(project / PNR, project / PNR / 'routed.def', log.read_text()) is None:
            raise em.Refusal('BACKEND_ROUTER_TERMINAL_UNMEASURED', sid)
        R._emit_router_drc_report(project, project / PNR, project / RPT, [])
        # Publish the surviving product of this completed native chain before
        # the unchanged provenance consumer reads the canonical DEF.
        R._log_surviving_artefact(
            [str(project / PNR / 'routed.def'), str(project / PNR / (top + '_pnr.v'))],
            produced_by='LibreLane native routing chain (step 21)',
            tool='openroad', exit_code=0)
    else:
        raise em.Refusal('BACKEND_UNKNOWN_PNR_STEP', sid)
    return {'verdict': 'PASS', 'detail': 'native ordered chain complete; canonical gates still required'}


def produce_signoff(project, params):
    R, ll, pdk, container = _parameters(project, params)
    sid, top = params['step_id'], params['top']
    notes, written, failures = [], [], []
    drv_final_state = None
    pnr, rpt = project / PNR, project / RPT
    extracted = project / 'phase3/stage3/extracted'
    spef = extracted / (top + '.spef')
    root, image = Path(params['pdk_root']), params['image_id']
    if sid == '22':
        # Current fivegap binding/finite-C/non-alias guards are inherited here.
        R._librelane_rcx_publish(project, top, pdk, spef,
                    extracted / 'spef_corners', rpt / 'librelane_rcx_handoff.json', refresh=True)
        handed = R._librelane_handed_spefs(rpt / 'librelane_rcx_handoff.json')
        R._log_surviving_artefact(
            [str(spef), *(str(path) for path in handed.values())],
            produced_by='LibreLane.OpenROAD.RCX', tool='openroad', exit_code=0)
    elif sid == '23':
        corners = R._librelane_handed_spefs(rpt / 'librelane_rcx_handoff.json')
        if not corners:
            raise em.Refusal('BACKEND_CURRENT_RCX_HANDOFF_ABSENT',
                             f'step {sid}: inspected current corner records in '
                             f'{rpt / "librelane_rcx_handoff.json"}')
        nominal = _require(spef)
        sta = project / 'phase3/stage3/sta'
        sta.mkdir(parents=True, exist_ok=True)
        ordinary = params.get('execution_mode') == 'default'
        if not ordinary:
            if not R._emit_spef_sta(project, top, pdk, container, nominal, sta / 'sta_spef_based.rpt', notes):
                raise em.Refusal('BACKEND_STA_NATIVE_UNMEASURED', sid)
            _copy(sta / 'sta_spef_based.rpt', sta / 'post_route_timing.rpt')
            _copy(sta / 'sta_spef_based.rpt', rpt / 'sta_spef_based.rpt')
        R._librelane_signoff_record(project, top, pdk, 'librelane', 'librelane',
              extracted / 'spef_corners', sta / 'multi_corner_ocv_sta.rpt', notes, failures, written,
              **({'qualify': False} if ordinary else {}))
        if ordinary:
            import librelane_signoff as signoff
            record = json.loads(_require(rpt / 'sta_postpnr_signoff.json').read_text())
            drv_final_state = {'capture_step': '23', 'final': {
                'sta_state': record['sta_state'],
                'sta_state_sha256': record['sta_state_sha256']}}
            native = Path(record['sta_state']).parent
            reports = [_require(native / corner / signoff.CORNER_REPORT)
                       for corner in record.get('corners', {})]
            if not reports:
                raise em.Refusal('BACKEND_STA_NATIVE_UNMEASURED', 'no selected STA corner report')
            body = 'POST-ROUTE SPEF-BASED STA: LibreLane.OpenROAD.STAPostPNR\n'
            body += '\n'.join(f'CORNER: {path.parent.name}\n' + path.read_text()
                              for path in reports)
            R._aa.write_text(sta / 'sta_spef_based.rpt', body)
            _copy(sta / 'sta_spef_based.rpt', sta / 'post_route_timing.rpt')
            _copy(sta / 'sta_spef_based.rpt', rpt / 'sta_spef_based.rpt')
            R._log_surviving_artefact(
                [str(sta / 'sta_spef_based.rpt'), str(sta / 'post_route_timing.rpt'),
                 str(rpt / 'sta_spef_based.rpt')],
                produced_by='LibreLane.OpenROAD.STAPostPNR', tool='openroad', exit_code=0)
            # The independent Step23 consumer reads the achieved period now,
            # before the legacy phase runner's later all-step publication.
            # Reuse its selected-arm writer so a rerun replaces the live
            # measurement with the current worst corner, without changing SDC.
            R._achievable_fmax_from_tool_arm(project, top, notes, written)
            # This row's disclosure consumer runs before the phase runner's
            # final sign-off sweep. Publish the existing clock-source record
            # now, and stamp any assumed period into the current tool record.
            import clock_target_provenance as provenance
            period, _ = R._resolve_clock_spec(project, top=top, pdk_name=pdk.name)
            provenance.emit_report(project, pdk=pdk.name, applied_period_ns=float(period))
            provenance.stamp_signoff_records(project)
            # This existing input-stated L24 reading is due at this row.
            # It measures the current route, independently of timing/IR budgets.
            import librelane_ir_antenna as power_grid
            connectivity = power_grid.publish_power_connectivity(
                project, image, root, routed_def=pnr / (top + '.def'),
                config=project / 'phase3/librelane/22-config/OpenROAD.RCX.json')
            pg_failures = connectivity.get('failures', [])
            pg_missing = connectivity.get('not_measured', [])
            pg_detail = ('power-network connectivity: ' + str(connectivity.get('counts', {})) +
                         f'; failures={len(pg_failures)}; not_measured={len(pg_missing)}' +
                         '; samples=' + repr([str(s)[:240] for s in (pg_failures[:3] + pg_missing[:3])]) +
                         '; full_report=' + power_grid.POWER_CONNECTIVITY_REPORT)
            if connectivity['verdict'] == 'FAIL':
                failures.append(pg_detail)
            elif connectivity['verdict'] == 'NOT_MEASURED' and not failures:
                return {'verdict': 'NOT_MEASURED',
                        'detail': pg_detail}
        if failures:
            return {'verdict': 'FAIL', 'detail': '\n'.join(failures)}
    elif sid == '24':
        subject = None
        if params.get('execution_mode') == 'default':
            from execution_adapters_backend import default_step24_physical_subject
            subject = default_step24_physical_subject(
                project, execution_mode='default')
        if subject is None:
            R._librelane_step24_record(
                project, top, pdk, 'librelane', _step24_spef(project, top, spef), written)
        else:
            # Consume exactly the paths the ordinary issuer froze.  No
            # canonical alias is authored here; missing or changed issued
            # bytes are refused by the worker contract and by _require.
            R._librelane_step24_record(
                project, top, pdk, 'librelane',
                _require(project / subject['spef']), written,
                routed_def=_require(project / subject['def']),
                netlist=_require(project / subject['netlist']),
                sdc=_require(project / subject['sdc']))
        record = json.loads((rpt / R._LL_IR_RECORD).read_text())
        if record.get('record'):
            R._librelane_step24_publish(project, record)
            R._step24_adopt_primary(project, None, notes)
        else:
            R._librelane_step24_refusal_publish(project, record)
    elif sid == '25':
        # Same SDC+SPEF/VSRC basis as the IR pipeline. Both outputs are retained;
        # the existing EM authority judges drawn width and foundry Jmax.
        ordinary = params.get('execution_mode') == 'default'
        if ordinary:
            import em_current_density_check as density
            primary = density.validate_primary_ir(project)
            if not primary['valid']:
                return {'verdict': 'NOT_MEASURED', 'detail': primary['reason']}
        ok = R._emit_ir_em_reports(
            project, top, pdk, container,
            rpt / ('ir_drop_psm_cross_check.rpt' if ordinary else 'ir_drop.rpt'),
            rpt / 'em.rpt', notes, **({'em_only': True} if ordinary else {}))
        if not ok[1]:
            raise em.Refusal('BACKEND_EM_NATIVE_UNMEASURED', sid)
        R._emit_em_current_authority(project, pdk, container, notes)
        if ordinary and primary['verdict'] == 'FAIL':
            return {'verdict': 'FAIL', 'detail': 'current Step-24 IR measurement failed; ' + '; '.join(notes)}
    elif sid == '26':
        R._librelane_antenna_router(project, top, pdk, 'librelane', written)
        if params.get('execution_mode') == 'default':
            basis, refusal = R._layout_basis(project, top, pdk, container)
            census, error = (R._prestream_route_census(project, top, pdk, container, basis)
                             if not refusal else (None, refusal))
            if not error:
                # Consume the persisted current record at this same boundary;
                # the existing reader binds its DEF/hash/count population.
                census, error = R._prestream_route_census(
                    project, top, pdk, container, basis, measure=False)
            if error:
                return {'verdict': 'NOT_MEASURED', 'detail': error}
            if census['unrouted_nets']:
                return {'verdict': 'FAIL', 'detail': 'routed ODB has unrouted nets'}
        gds = pnr / (top + '.gds')
        if params.get('execution_mode') != 'default' and gds.is_file():
            R._librelane_antenna_gds(project, top, pdk, 'librelane', written)
    elif sid == '26.5ic':
        ok, detail = R._die_finishing(project, top, pdk, _require(pnr / (top + '.gds')), container)
        if not ok:
            return {'verdict': 'NOT_MEASURED', 'detail': detail}
    elif sid == '27':
        import si_mcf_sta as mcf
        nl = _require(pnr / (top + '_pnr.v'))
        voltage = R._pdk_nominal_voltage(pdk, container)
        if voltage is None:
            raise em.Refusal('BACKEND_SI_VOLTAGE_UNSTATED', sid)
        if params.get('execution_mode') == 'default':
            # The current SI owner publishes the compound report and the
            # timing-consumption receipt required by the unchanged full gate.
            if not R._emit_si_crosstalk_report(
                    project, top, _require(spef), rpt / 'ir_drop.rpt',
                    rpt / 'si_crosstalk.rpt', notes, pdk=pdk, container=container, vdd_v=voltage):
                return {'verdict': 'NOT_MEASURED', 'detail': '; '.join(notes)}
            import _opensta_current as current
            subject = current.si_binding(project)
            inputs = {row['role']: row['path'] for row in subject['inputs']}
            liberties = [inputs[f'liberty:{i}'] for i in
                         range(sum(role.startswith('liberty:') for role in inputs))]
            # The logical artifact stem can differ from the module and corner
            # the native STA actually linked. MCF must consume that same
            # validated subject, not reconstruct it from nominal aliases.
            mcf_inputs = dict(spef=inputs['spef'], netlist=inputs['netlist'],
                sdc=inputs['sdc'], liberty=liberties[0], macro_libs=liberties[1:],
                top=subject.get('physical_top', subject['top']))
        else:
            sdc = _current_physical_sdc(project, params)
            mcf_inputs = dict(spef=str(spef), netlist=str(nl), sdc=str(sdc),
                              liberty=pdk.liberty, top=top, macro_libs=pdk.macro_libs)
            import si_signoff_timing_aware as si
            timing = rpt / 'si_timing.json'
            if not R._emit_si_timing_json(project, top, pdk, container, _require(spef), sdc, nl, timing, notes, voltage):
                raise em.Refusal('BACKEND_SI_NATIVE_UNMEASURED', sid)
            si.run_si_signoff_timing_aware(spef, timing, vdd_v=voltage,
                            out_json=rpt / 'si_crosstalk.json', out_rpt=rpt / 'si_crosstalk.rpt')
        mcf.run(project, container=container, **mcf_inputs,
                vdd_v=voltage, out_json=rpt / 'si_mcf_sta.json', timeout=int(params['timeout_s']))
    elif sid == '28':
        if not R._emit_perc_equivalent(project, top, pdk, container, notes):
            raise em.Refusal('BACKEND_PERC_UNMEASURED', sid)
    elif sid == '29':
        sim = project / 'phase3/stage3/sim_postlayout'
        sim.mkdir(parents=True, exist_ok=True)
        sdf = None
        if params.get('execution_mode') != 'default':
            sdf = sim / (top + '.sdf')
            if not R._emit_sdf(project, top, pdk, container, sdf, notes):
                raise em.Refusal('BACKEND_SDF_NATIVE_UNMEASURED', sid)
        # Default consumes the full-PDK STAPostPNR corner SDFs through the
        # existing tool arm; the optional direct arm only compares coverage.
        R._step29_tool_arm(project, top, pdk, 'librelane', sim, sdf, written, notes)
    elif sid == '30':
        if params.get('execution_mode', 'default') == 'default':
            from execution_adapters_backend import _step30_simulators
            instruments = _step30_simulators(params)
            if instruments != ('ngspice',):
                return {'verdict': 'NOT_MEASURED',
                        'detail': 'BACKEND_CURRENT_STEP30_PROVIDER_UNQUALIFIED: ' +
                                  repr(instruments)}
            # Use the same current producer and strict consumer as the
            # ordinary Phase-3 caller. Its native correlation record belongs
            # at the canonical path; the audit belongs in phase2/gates.
            if not R._step30_tool_arm(project, pdk, written, notes, container=container,
                                     paths=params.get('spice_paths', 1)):
                gate = _require(project / 'reports/phase2/gates/spice_correlation.json')
                verdict = json.loads(gate.read_text()).get('summary', {}).get('verdict')
                return {'verdict': 'FAIL' if verdict == 'FAIL' else 'NOT_MEASURED',
                        'detail': '\n'.join(notes)}
            return {'verdict': 'PASS', 'detail': '\n'.join(notes)}
        import path_spice_tool as spice
        from execution_adapters_backend import _step30_simulators
        result = spice.run_step30(project, image, root, pdk.name,
                          paths=params.get('spice_paths', 1), simulators=tuple(_step30_simulators(params)))
        # Tool refusal/model gaps remain explicit. Existing correlation gates
        # judge the record at its declared canonical output path.
        # Keep the native tool report in its own schema. The correlation
        # consumer reads it explicitly; never relabel it as a legacy report.
        import spice_correlation_check as correlation
        audited = correlation.run_audit(project, run_spice=False, container=container)
        from dataclasses import asdict
        snap.dump(rpt / 'spice_correlation.json', asdict(audited))
        if result.get('verdict') != 'PASS':
            return {'verdict': result.get('verdict', 'NOT_MEASURED'), 'detail': str(result.get('reason', ''))}
    elif sid == '32':
        # A bounded resume can retain synthesis while refreshing its missing
        # DRV measurement under the current deck. Never resynthesize here.
        _retained_synth_census(project, params, R, ll, pdk)
        row = R.step_postroute_repair_librelane(project, top, pdk, container)
        if row.status in ('PASS', 'FAIL'):
            # The current receipt is checked before the legacy all-step
            # canonicalizer runs. Publish this row's existing canonical
            # decision now, from its bound native measurement, without
            # replacing the producer's raw decision or rerunning STA. A
            # measured native FAIL needs the same publication: the canonical
            # record explains that FAIL; it does not convert it to PASS.
            out = project / 'phase3/stage3/postroute_timing_repair'
            producer = R._step32_producer_receipt(project, out)
            if producer is None:
                if row.status == 'PASS':
                    return {'verdict': 'NOT_MEASURED',
                            'detail': 'current Step-32 bound producer decision absent'}
                return {'verdict': row.status, 'detail': row.detail}
            import librelane_postroute_repair as repair
            source = project / producer['source_report']
            report = json.loads(source.read_text())
            trigger = repair.measured_repair_trigger(report.get('final') or {})
            timing = ('NOT_MEASURED' if any(key in trigger['missing'] for key in
                                          ('setup_ws_min', 'hold_ws_min'))
                      else 'VIOLATED' if any(key in trigger['violated'] for key in
                                            ('setup_ws_min', 'hold_ws_min'))
                      else 'CLEAN')
            decision = R._repair_dec.decide(
                None, timing == 'CLEAN', project=project,
                single_corner_evidence=timing, producer_receipt=producer,
                timing_basis='current Step-32 STAPostPNR per-corner census',
                decision_scope='step32_native' if params.get('execution_mode') == 'default'
                               else 'whole_signoff')
            if R._publish_step32_decision(
                    project, decision, source, source, out, producer, written, notes):
                return {'verdict': 'NOT_MEASURED', 'detail': '; '.join(notes)}
        return {'verdict': row.status, 'detail': row.detail}
    elif sid == '33':
        # Run OpenSTA's native report_power on the selected current SPEFs.
        # The report reader below consumes the newly issued STA state.
        if params.get('execution_mode') != 'default':
            R._librelane_signoff_record(project, top, pdk, 'librelane', 'librelane',
                  extracted / 'spef_corners', project / 'phase3/stage3/sta/multi_corner_ocv_sta.rpt',
                  notes, failures, written)
        R._step33_tool_arm(project, top, pdk, 'librelane', rpt / 'power.rpt', False, written, notes)
    elif sid == '34':
        if params.get('execution_mode') == 'default':
            # Stream-out already consumed these exact filled DEF/GDS bytes.
            # This row owns their complete fill consumer, not a second writer.
            import librelane_fill_dfm as fill
            fill.validate_default_stream(project)
            return {'verdict': 'PASS', 'detail': 'current finished fill retained',
                    'finishing_receipt': str(project / fill.DEFAULT_STREAM_REL)}
        else:
            if not R._emit_metal_fill(project, top, pdk, container, pnr / 'filled.def', notes):
                raise em.Refusal('BACKEND_FILL_NATIVE_UNMEASURED', sid)
            if not R._emit_metal_density_report(project, top, pdk, container, rpt / 'density.json', notes):
                raise em.Refusal('BACKEND_DENSITY_NATIVE_UNMEASURED', sid)
    elif sid == '37':
        if params.get('execution_mode') == 'default':
            import librelane_fill_dfm as fill
            promotion = project / fill.DEFAULT_STREAM_REL
            basis, error = R._layout_basis(project, top, pdk, container)
            if (promotion.is_file() and not error and
                    R._ga.admitted_gds(project, pnr / (top + '.gds'), basis)):
                # A final-consumer repair must not replay an already admitted
                # native stream, seal/fill or its pre-stream instruments. The
                # existing owner rechecks all retained native bytes, readsets
                # and per-layer density before the unchanged full row consumer.
                _step37_retained_output_sources(project, str(promotion))
                pad = (R.step_pad_ring_final_evidence(
                    project, top, R.StepResult('gds', 'PASS', 0.0,
                        'retained native stream owner validated'), container)
                    if R._chip_path_requests_pad_ring(project) else None)
                return {'verdict': pad.status if pad else 'PASS',
                        'detail': (pad.detail if pad else
                                   'admitted native stream retained and validated'),
                        'streamout_engine': 'klayout',
                        'finishing_receipt': str(promotion)}
        pre = R.step_prestream_gate(project, top, pdk, container)
        if pre.status != 'PASS':
            return {'verdict': pre.status, 'detail': pre.detail}
        route = _step37_route(params)
        row = R.step_gds(project, top, pdk, container)
        if row.status == 'PASS':
            _copy(pnr / (top + '.gds'), project / 'phase3/stage4/gds' / (top + '.gds'))
            if params.get('execution_mode') == 'default':
                # The geometry axis belongs to this finished stream. A router
                # antenna report never measures seal/fill GDS geometry.
                R._librelane_antenna_gds(project, top, pdk, 'librelane', written)
                R._ga.admit_gds(project, pnr / (top + '.gds'),
                                pre.extras['layout_digest'],
                                R._layout_basis_paths(project, top))
                if R._chip_path_requests_pad_ring(project):
                    pad = R.step_pad_ring_final_evidence(project, top, row, container)
                    if pad.status != 'PASS':
                        return {'verdict': pad.status, 'detail': pad.detail}
        if params.get('execution_mode') == 'default':
            return {'verdict': row.status, 'detail': row.detail,
                    'streamout_engine': row.extras.get('streamout_engine'),
                    'finishing_receipt': row.extras.get('finishing_receipt')}
        return _step37_streamout_result(project, route, row)
    elif sid == '37.3':
        import gds_xor_check as xor
        if params.get('execution_mode') == 'default':
            # Default stream publication returns before the legacy units
            # publisher. Resume from the validated filled subject and retained
            # PDK views without rewriting accepted declaration inputs.
            physical_views = R._restore_recorded_physical_views(project, pdk, container)
            if physical_views.get('refused'):
                return {'verdict': 'NOT_MEASURED',
                        'detail': 'Step37.3 recorded physical views refused: ' + physical_views['refused'],
                        'physical_views': physical_views}
            import _native373_current as native373
            R.publish_database_unit_declaration(
                project, pdk, container, native373._source_def(project),
                publish_declaration=False)
        rc = xor.main([str(project), '--json', str(rpt / 'gds_xor.json'), '--container', container])
        return {'verdict': 'PASS' if rc == 0 else 'FAIL' if rc == 1 else 'NOT_MEASURED', 'detail': f'gds_xor producer rc={rc}'}
    elif sid == '31':
        # Admission uses the same fresh routed basis as stream publication.
        # Instrument-only restoration below mutates this PDK object in memory.
        basis, error = R._layout_basis(project, top, pdk, container)
        # A resumed backend producer detects its own PDK object. Restore the
        # recorded views on that object before either physical instrument reads
        # it, just as the individual post-route window already does.
        physical_views = R._restore_recorded_physical_views(project, pdk, container)
        if physical_views.get('refused'):
            return {'verdict': 'NOT_MEASURED',
                    'detail': 'Step31 recorded physical views refused: ' + physical_views['refused'],
                    'physical_views': physical_views}
        if error or not R._ga.admitted_gds(project, pnr / (top + '.gds'), basis):
            return {'verdict': 'NOT_MEASURED',
                    'detail': 'Step31 refused unadmitted routed GDS: ' + str(error or basis),
                    'physical_views': physical_views}
        # Complementary axes ALL execute. No DRC winner can hide a failing LVS.
        drc = R.step_drc(project, top, pdk, container)
        lvs = R.step_lvs(project, top, pdk, container, upstream_pnr=None)
        if params.get('execution_mode') == 'default':
            import _native_erc
            _native_erc.emit(project, top, pdk, container, rpt / 'erc.rpt', notes)
        else:
            R._emit_erc_report(project, top, pdk, container, rpt / 'erc.rpt', notes)
        import perc_corpus_sweep as sweep
        sweep.main([str(project), '--report', str(rpt / 'perc_sweep.json')])
        statuses = [drc.status, lvs.status]
        detail = 'DRC: ' + drc.detail + '\nLVS: ' + lvs.detail
        if params.get('execution_mode') == 'default':
            # The final capture binds the finished GDS and actual LVS output.
            # It belongs after these producers, before the full row consumer.
            spec = next(row for row in R._DECLARED_SIGNOFF_GATES if row[0] == 'drv_signoff')
            drv = R._run_declared_signoff_gate(project, *spec)
            statuses.append(drv.status)
            detail += '\nFinal DRV: ' + drv.detail
        result = {'verdict': 'FAIL' if 'FAIL' in statuses else 'PASS' if all(status == 'PASS' for status in statuses) else 'NOT_MEASURED',
                  'detail': detail}
        if drc.extras.get('retained_drc_checkpoint'):
            result['retained_drc_checkpoint'] = drc.extras['retained_drc_checkpoint']
        return result
    else:
        raise em.Refusal('BACKEND_UNKNOWN_SIGNOFF_STEP', sid)
    result = {'verdict': 'PASS', 'detail': '\n'.join(notes)}
    if drv_final_state is not None:
        result['drv_final_state'] = drv_final_state
    return result


def _run_current_step_declared_producers(project, step_id, input_manifest=None):
    """Materialize this row's flow-declared outputs before its consumer.

    The phase runner's final refresh still owns the all-step sweep.  A backend
    worker, however, evaluates its row immediately after ``produce``; calling
    the existing step-filtered seam here lets that row author only its own
    declared documents (with the producer authorship stamp) before the gate
    reads them.  A helper failure remains an explicit receipt and never turns a
    missing document into a pass.
    """
    try:
        import flow_declared_producer_run as declared
        kwargs = ({'input_manifest': input_manifest} if input_manifest is not None else {})
        result = declared.run_for_step(Path(project), str(step_id), **kwargs)
        if not isinstance(result, dict):
            raise ValueError("current-step producer returned no record")
        return result
    except BaseException as exc:
        return {
            "program": "flow_declared_producer_run",
            "scope": "current-step",
            "step_id": str(step_id),
            "verdict": "INCOMPLETE",
            "executed": 0,
            "consumer_allowed": False,
            "error": f"{type(exc).__name__}: {exc}",
        }


def _step37_retained_output_sources(project, finishing_receipt):
    """Recheck the existing whole-stream owner, then bind its publications.

    The canonical transcript is copied from the native invocation at normal
    publication. Its equality is not part of validate_default_stream, so it
    must also match the original StreamOut receipt before it can be adopted.
    """
    import librelane_fill_dfm as fill
    import _stream_input_record as sir
    project = Path(project).resolve()
    if (not isinstance(finishing_receipt, str)
            or Path(finishing_receipt).resolve() !=
            (project / fill.DEFAULT_STREAM_REL).resolve()):
        raise ValueError('Step37 retained finishing receipt is not the owning promotion')
    record = fill.validate_default_stream(project)
    arm = fill._load(project / fill.RECORD_REL)['gds']['librelane']
    judged = fill.current_metal_density(project, arm, record)
    if arm.get(fill.DENSITY_METRIC) != 0 or judged.get('verdict') != 'PASS':
        raise ValueError('Step37 retained per-layer density did not pass')
    pnr = project / 'phase3/stage3/pnr'
    inputs = sir.record_path(pnr / (record['file_top'] + '.gds'))
    readset, why = sir.read(inputs)
    if readset is None:
        raise ValueError('Step37 retained readset is unavailable: ' + str(why))
    native = Path(record['stream_state']).parent
    receipt = fill.validate_step_receipt(native, 'KLayout.StreamOut')
    log_sha = receipt['sha256'].get('invocation.log')
    if not log_sha or snap.sha(native / 'invocation.log') != log_sha:
        raise ValueError('Step37 retained native invocation log is unbound')
    sources = {record[key]: record[key + '_sha256']
               for key in ('canonical', 'pnr_gds')}
    sources.update({str(inputs): record['stream_inputs_sha256'],
                    str(project / readset['recipe']['project_rel']):
                        readset['recipe']['sha256'],
                    str(pnr / 'stream_out.log'): log_sha})
    bound = {}
    for raw, expected in sources.items():
        path = Path(raw)
        relative = str(path.relative_to(project))
        if path.is_symlink() or not path.is_file() or snap.sha(path) != expected:
            raise ValueError('Step37 retained publication changed: ' + relative)
        bound[relative] = expected
    return bound


def _step34_retained_output_sources(project, finishing_receipt):
    """Bind retained DEF fill and re-derive its original report documents."""
    import librelane_fill_dfm as fill
    import phase3_one_shot_runner as runner
    project = Path(project).resolve()
    if (not isinstance(finishing_receipt, str)
            or Path(finishing_receipt).resolve() !=
            (project / fill.DEFAULT_STREAM_REL).resolve()):
        raise ValueError('Step34 retained finishing receipt is not the owning promotion')
    record = fill.validate_default_stream(project)
    doc = fill._load(project / fill.RECORD_REL)
    arm = doc['gds']['librelane']
    if (arm.get(fill.DENSITY_METRIC) != 0
            or fill.current_metal_density(project, arm, record).get('verdict') != 'PASS'):
        raise ValueError('Step34 retained per-layer density did not pass')
    # validate_default_stream already verifies the FillInsertion receipt,
    # native state/output DEF and handoff into this canonical filled.def.
    tool = doc['odb']['tool']
    pnr = project / 'phase3/stage3/pnr'
    filled = pnr / 'filled.def'
    subject = runner._measured_subject(
        project, record['file_top'], [Path(tool['subject']), filled],
        tool_log=Path(tool['state']).parent / 'openroad-fillinsertion.log')
    report, document, marker = fill.direct_schema_reports(
        tool, subject, runner._measured_subject_lines(subject))
    bound = {str(filled.relative_to(project)): tool['filled_def_sha256']}
    expected = {pnr / 'metal_fill.done': marker}
    for folder in (project / 'reports', project / 'reports/phase3'):
        expected[folder / 'density.rpt'] = report
        path = folder / 'density.json'
        if path.exists():
            if path.is_symlink() or fill._load(path) != document:
                raise ValueError('Step34 retained density document changed: ' + str(path))
            bound[str(path.relative_to(project))] = snap.sha(path)
    for path, content in expected.items():
        if path.exists():
            if path.is_symlink() or path.read_text() != content:
                raise ValueError('Step34 retained fill report changed: ' + str(path))
            bound[str(path.relative_to(project))] = snap.sha(path)
    return bound


def _native_current_step_receipt(project, step_id, params, result,
                                 started_ns, prior_outputs=None):
    """Create the current receipt for a registry-backed native producer.

    Rows with no flow-declared producer deliberately need a separate receipt;
    running their consumers through ``flow_declared_producer_run`` would make
    the gate certify its own output.  The receipt binds the resolved input
    manifest plus every canonical output byte written by that invocation.
    """
    sid = str(step_id)
    producer_name = _native_current_step_producer(sid)
    if producer_name is None:
        return None
    prior_outputs = dict(prior_outputs or {})
    verdict = result.get('verdict') if isinstance(result, dict) else None
    receipt = {
        'schema': 'vibeic/native-current-step-receipt/1',
        'step_id': sid,
        'producer': producer_name,
        'verdict': ('PRODUCED' if verdict == 'PASS'
                    else 'FAIL' if verdict == 'FAIL' else 'NOT_MEASURED'),
        'started_ns': int(started_ns),
        'finished_ns': time.time_ns(),
        'inputs': {},
        'outputs': {},
        'output_specs': [],
        'preexisting_outputs': prior_outputs,
    }
    manifest = params.get('resolved_input_manifest')
    files = manifest.get('files') if isinstance(manifest, dict) else None
    if not isinstance(files, dict) or not files:
        receipt['verdict'] = 'NOT_MEASURED'
        receipt['reason'] = 'NATIVE_CURRENT_INPUT_MANIFEST_ABSENT'
        return receipt
    for raw, expected in sorted(files.items()):
        if not isinstance(raw, str) or Path(raw).is_absolute() or '..' in Path(raw).parts:
            receipt['verdict'] = 'NOT_MEASURED'
            receipt['reason'] = f'NATIVE_CURRENT_INPUT_PATH_INVALID: {raw!r}'
            return receipt
        path = Path(project) / raw
        try:
            digest = snap.sha(path)
        except (OSError, ValueError):
            receipt['verdict'] = 'NOT_MEASURED'
            receipt['reason'] = f'NATIVE_CURRENT_INPUT_ABSENT: {raw}'
            return receipt
        expected_sha = (expected.get('sha256') if isinstance(expected, dict)
                        else expected)
        expected_sha = str(expected_sha).removeprefix('sha256:')
        if digest != expected_sha:
            receipt['verdict'] = 'NOT_MEASURED'
            receipt['reason'] = f'NATIVE_CURRENT_INPUT_CHANGED: {raw}'
            return receipt
        receipt['inputs'][raw] = {'sha256': digest}

    try:
        from execution_adapters_backend import ROWS
        row = ROWS[sid]['canonical_row']
        from execution_backend_gates import contracts
        contract = contracts(Path(project), row)
    except (KeyError, OSError, ValueError, TypeError, em.Refusal) as exc:
        receipt['verdict'] = 'NOT_MEASURED'
        receipt['reason'] = f'NATIVE_CURRENT_OUTPUT_CONTRACT_UNAVAILABLE: {exc}'
        return receipt
    retained_sources = None
    for spec, paths in contract.items():
        receipt['output_specs'].append(spec)
        for raw, digest in sorted(paths.items()):
            path = Path(project) / raw
            try:
                stat = path.stat()
            except OSError:
                receipt['verdict'] = 'NOT_MEASURED'
                receipt['reason'] = f'NATIVE_CURRENT_OUTPUT_ABSENT: {raw}'
                return receipt
            # A prior-run output must not be credited when the native producer
            # returned without writing or replacing this invocation's artefact.
            # Compare the complete pre-invocation identity rather than using a
            # wall-clock threshold, which can credit a no-op on coarse filesystems.
            before = prior_outputs.get(raw)
            after = _native_output_identity(path)
            if before is not None and after == before:
                try:
                    if (sid not in ('34', '37') or verdict != 'PASS'
                            or params.get('execution_mode') != 'default'):
                        raise ValueError('no retained Default stream producer')
                    if retained_sources is None:
                        owner = (_step34_retained_output_sources if sid == '34'
                                 else _step37_retained_output_sources)
                        retained_sources = owner(project, result.get('finishing_receipt'))
                    if retained_sources.get(raw) != digest:
                        raise ValueError('output is not bound by the retained stream')
                except (OSError, ValueError, KeyError, TypeError, em.Refusal, LibrelaneRefusal) as exc:
                    receipt['verdict'] = 'NOT_MEASURED'
                    receipt['reason'] = f'NATIVE_CURRENT_OUTPUT_UNCHANGED: {raw}; {exc}'
                    return receipt
                adoption = receipt.setdefault('retained_outputs', {
                    'execution_mode': 'default',
                    'finishing_receipt': result['finishing_receipt'], 'outputs': {}})
                adoption['outputs'][raw] = digest
            actual = snap.sha(path)
            if actual != digest:
                receipt['verdict'] = 'NOT_MEASURED'
                receipt['reason'] = f'NATIVE_CURRENT_OUTPUT_CHANGED: {raw}'
                return receipt
            receipt['outputs'][raw] = {
                'sha256': actual, 'size': stat.st_size,
                'mtime_ns': stat.st_mtime_ns,
            }
    if receipt['verdict'] == 'PRODUCED' and not receipt['outputs']:
        receipt['verdict'] = 'NOT_MEASURED'
        receipt['reason'] = 'NATIVE_CURRENT_OUTPUT_EMPTY'
    return receipt


def _current_step_producer_authority(record, project=None):
    """Classify the current-step producer census before consumer evaluation."""

    def _execution_result_is_acceptable(row):
        rc = row.get("rc") if isinstance(row, dict) else None
        return (rc == 0 or
                (rc == 1 and row.get("enforcement") == "advisory"))

    if not isinstance(record, dict):
        return False, "current-step producer record is malformed", "NOT_MEASURED"
    if record.get('schema') == 'vibeic/native-current-step-receipt/1':
        sid = str(record.get('step_id'))
        expected_producer = _native_current_step_producer(sid)
        if expected_producer is None or record.get('producer') != expected_producer:
            return False, "native current producer identity is invalid", "NOT_MEASURED"
        if record.get('verdict') != 'PRODUCED':
            status = 'FAIL' if record.get('verdict') == 'FAIL' else 'NOT_MEASURED'
            return False, record.get('reason', 'native producer did not complete'), status
        if type(record.get('started_ns')) is not int or type(record.get('finished_ns')) is not int:
            return False, "native current producer timing is missing", "NOT_MEASURED"
        if not isinstance(record.get('inputs'), dict) or not record['inputs']:
            return False, "native current producer inputs are missing", "NOT_MEASURED"
        outputs = record.get('outputs')
        if not isinstance(outputs, dict) or not outputs:
            return False, "native current producer outputs are missing", "NOT_MEASURED"
        if project is None:
            return False, "native current producer project is missing", "NOT_MEASURED"
        inputs = record.get('inputs')
        for raw, info in (inputs or {}).items():
            if (not isinstance(raw, str) or Path(raw).is_absolute()
                    or '..' in Path(raw).parts or not isinstance(info, dict)
                    or not isinstance(info.get('sha256'), str)):
                return False, "native current producer input receipt is malformed", "NOT_MEASURED"
            path = Path(project) / raw
            try:
                if (path.is_symlink() or not path.is_file()
                        or snap.sha(path) != info['sha256']):
                    return False, f"native current producer input changed: {raw}", "NOT_MEASURED"
            except OSError:
                return False, f"native current producer input absent: {raw}", "NOT_MEASURED"
        for raw, info in outputs.items():
            if (not isinstance(raw, str) or not isinstance(info, dict)
                    or Path(raw).is_absolute() or '..' in Path(raw).parts
                    or not isinstance(info.get('sha256'), str)):
                return False, "native current producer output receipt is malformed", "NOT_MEASURED"
            path = Path(project) / raw
            try:
                if path.is_symlink() or not path.is_file() or snap.sha(path) != info['sha256']:
                    return False, f"native current producer output changed: {raw}", "NOT_MEASURED"
            except OSError:
                return False, f"native current producer output absent: {raw}", "NOT_MEASURED"
        adoption = record.get('retained_outputs')
        if adoption is not None:
            try:
                if (sid not in ('34', '37') or not isinstance(adoption, dict)
                        or adoption.get('execution_mode') != 'default'
                        or not isinstance(adoption.get('outputs'), dict)
                        or not adoption['outputs']):
                    raise ValueError('invalid retained stream adoption')
                owner = (_step34_retained_output_sources if sid == '34'
                         else _step37_retained_output_sources)
                sources = owner(project, adoption.get('finishing_receipt'))
                for raw, digest in adoption['outputs'].items():
                    if (raw not in outputs or outputs[raw]['sha256'] != digest
                            or sources.get(raw) != digest):
                        raise ValueError('retained output is not bound: ' + str(raw))
            except (OSError, ValueError, KeyError, TypeError, em.Refusal, LibrelaneRefusal) as exc:
                return False, f"native retained stream refused: {exc}", "NOT_MEASURED"
        return True, "", "PASS"
    results = record.get("results")
    if not isinstance(results, list):
        return False, "current-step producer results are missing", "NOT_MEASURED"
    if any(isinstance(row, dict) and not _execution_result_is_acceptable(row)
           for row in results):
        return False, "current-step producer execution failed", "FAIL"
    verdict = record.get("verdict")
    if verdict != "PRODUCED":
        return False, f"current-step producer verdict is {verdict!r}", "NOT_MEASURED"
    population = record.get("population")
    if type(population) is not int or population <= 0:
        return False, "current-step producer population is zero", "NOT_MEASURED"
    already = record.get('already_produced_by_the_run', 0)
    if type(already) is not int or already < 0 or population != len(results) + already:
        return False, "current-step producer population is unaccounted", "NOT_MEASURED"
    reused = [row for row in record.get('skipped', [])
              if isinstance(row, dict) and not str(row.get('why', '')).startswith(
                  'the run did not perform this step')]
    if already and (len(reused) != already or any(
            row.get('current_input_identity_valid') is not True or
            not isinstance(row.get('target_sha256'), str) for row in reused)):
        return False, "prior producer target lacks current input/content proof", "NOT_MEASURED"
    invalid = record.get("invalid_results") or record.get("unexecutable")
    if invalid:
        nonzero = any(row.get("rc") not in (None, 0)
                      for row in invalid if isinstance(row, dict))
        return False, "current-step producer result is incomplete", (
            "FAIL" if nonzero else "NOT_MEASURED")
    for row in results:
        if not isinstance(row, dict):
            return False, "current-step producer result is malformed", "NOT_MEASURED"
        if (not _execution_result_is_acceptable(row) or
                row.get("executed") is not True or
                row.get("target_exists_after") is not True):
            return False, "current-step producer target did not complete", "NOT_MEASURED"
        if row.get("authorship") != "producer":
            return False, "current-step producer authorship is not producer", "NOT_MEASURED"
    return True, "", "PASS"

def produce(project, params):
    started_ns = time.time_ns()
    sid = str(params['step_id'])
    prior_outputs = _native_current_step_output_snapshot(Path(project), sid)
    if params['step_id'] in ('15', '15.5ic', '17', '18', '19', '20', '21'):
        result = produce_pnr(project, params)
    else:
        result = produce_signoff(project, params)
    if params.get('stop_on_producer_failure') and result.get('verdict') != 'PASS':
        # The local Default caller cannot advance without this producer's
        # outputs. A registry-backed native row can still have authored its
        # complete current outputs before returning FAIL. Bind those bytes so
        # the terminal receipt reports the actual producer failure rather than
        # a malformed/null producer census. Do not run declared downstream
        # report producers after preparation or the native tool refused.
        if _native_current_step_producer(sid) is not None:
            current = _native_current_step_receipt(
                Path(project), sid, params, result, started_ns, prior_outputs)
            allowed, reason, authority_verdict = _current_step_producer_authority(
                current, project=Path(project))
            current['consumer_allowed'] = allowed
            current['authority_verdict'] = authority_verdict
            current['authority_detail'] = reason
            result['current_step_declared_producers'] = current
        return result
    # The backend consumer runs immediately after this function.  Materialize
    # only this row's flow-declared producer outputs now; the phase runner's
    # later all-step refresh remains unchanged and does not get used as a
    # substitute for current-step ownership.
    if _native_current_step_producer(sid) is not None:
        current = _native_current_step_receipt(
            Path(project), sid, params, result, started_ns, prior_outputs)
    else:
        current = _run_current_step_declared_producers(
            project, sid, params.get('resolved_input_manifest'))
    allowed, reason, authority_verdict = _current_step_producer_authority(
        current, project=Path(project))
    current['consumer_allowed'] = allowed
    current['authority_verdict'] = authority_verdict
    current['authority_detail'] = reason
    result['current_step_declared_producers'] = current
    if not allowed:
        result['verdict'] = ("FAIL" if authority_verdict == "FAIL" or result.get('verdict') == 'FAIL'
                             else "NOT_MEASURED")
        result['detail'] = (str(result.get('detail', '')) +
                            f"; {reason}").strip('; ')
    # These are the existing canonical report producers, scoped to this row.
    # They consume actual native outputs; they do not stand in for native work.
    import phase3_one_shot_runner as R
    names = {'23': {'sta_signoff', 'sta_corner', 'sta_record', 'sta_architectural_residual'},
             '24': {'ir_drop'}, '25': {'em_signoff'}, '26': {'antenna'}}.get(sid, set())
    if sid == '23' and params.get('execution_mode') == 'default':
        # The current row precedes stream-out/LVS. Its existing pre-stream
        # instrument captures fresh DRV evidence; final capture stays in the
        # phase runner's post-stream signoff table.
        names.add('drv_signoff')
    table = {row[0]: row for row in R._DECLARED_SIGNOFF_GATES}
    table.update({row[0]: row for row in R._PRESTREAM_GATES})
    rows = []
    for name in ('sta_signoff', 'sta_corner', 'sta_record', 'sta_architectural_residual', 'drv_signoff', 'ir_drop', 'em_signoff', 'antenna'):
        if name not in names:
            continue
        _, program, output, extra = table[name]
        capture_args = ({'drv_final_state': result['drv_final_state']}
                        if name == 'drv_signoff' and result.get('drv_final_state') is not None
                        else {})
        rows.append(R._run_declared_signoff_gate(
            project, name, program, output, extra, **capture_args))
    if sid == '23' and params.get('execution_mode') == 'default':
        # These writers just replaced the sign-off records. Restore the
        # assumption disclosure before the independent backend consumer.
        import clock_target_provenance as provenance
        provenance.stamp_signoff_records(project)
    if any(row.status == 'FAIL' for row in rows):
        result['verdict'] = 'FAIL'
    elif result['verdict'] == 'PASS' and any(row.status != 'PASS' for row in rows):
        result['verdict'] = 'NOT_MEASURED'
    failed_details = [f'{row.name}: {row.detail}' for row in rows if row.status != 'PASS']
    if failed_details:
        result['detail'] = '\n'.join([str(result.get('detail', '')), *failed_details]).strip()
    # This is the producer's own current-tree evidence, not a fabricated native
    # tool receipt.  Native receipts remain an empty, separately named field;
    # the worker can therefore distinguish source evidence from EDA execution.
    result['canonical_receipts'] = [{
        'schema': 'vibeic/backend-producer-receipt/1',
        'producer': 'execution_backend_producers.produce',
        'step_id': sid,
        'verdict': result.get('verdict', 'NOT_MEASURED'),
        'detail': result.get('detail', ''),
        'current_step_declared_producers': current,
    }]
    if result.get('retained_drc_checkpoint'):
        result['canonical_receipts'][0]['retained_drc_checkpoint'] = result['retained_drc_checkpoint']
    result.setdefault('native_receipts', [])
    return result
