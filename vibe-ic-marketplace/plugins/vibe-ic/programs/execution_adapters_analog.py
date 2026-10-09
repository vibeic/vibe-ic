"""Source-bound A6/A7/A8 adapters for the ordinary outer Controller route.

Native availability is measured before the ordinary Registry is finalized.
Software availability, protocol eligibility and silicon verdict are separate.
No portfolio/runner/shared-supervisor state is changed by this module.
"""
from __future__ import annotations

from dataclasses import dataclass
import fnmatch
import json
import os
from pathlib import Path
import sys
from typing import Mapping

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
import execution_modes as em

PROGRAMS = Path(__file__).resolve().parent
WORKER = PROGRAMS / 'execution_analog_worker.py'
CONTRACT_FILE = PROGRAMS / 'data/execution_analog_contracts.json'
CONTRACTS = {r['step_id']: r for r in json.loads(CONTRACT_FILE.read_text())['steps']}
STEP_IDS = ('A6', 'A7', 'A8')
ALL_STEP_IDS = tuple(CONTRACTS)
ANALOG_STEPS = dict(zip(ALL_STEP_IDS[:9], (
    'A1_spec_extract', 'A2_topology_select', 'A3_netlist_gen', 'A4_corner_sweep',
    'A5_layout', 'A6_block_pv', 'A7_post_layout_resim', 'A8_hardmacro_gen', 'A9_hw_verify')))
PRODUCERS = {
    'A1': ('analog_a1_spec_emit.py',), 'A2': ('analog_a2_topology_emit.py',),
    'A3': ('analog_a3_netlist_emit.py',), 'A4': ('analog_real_corner_sweep.py',),
    'A5': ('analog_a5_layout_emit.py',), 'A6': ('analog_a6_native_pv.py',),
    'A7': ('analog_a7_post_layout_emit.py',),
    'A8': ('analog_a8_hardmacro_emit.py', 'analog_hardmacro_gds_emit.py'),
    'A9': ('analog_a9_cosim_emit.py',), 'M1': ('mixed_signal_top_lvs_run.py',),
    'M2': ('execution_analog_mixed_worker.py',),
    'M3': ('analog_a9_cosim_emit.py', 'execution_analog_mixed_worker.py'),
    'M4': ('execution_analog_mixed_worker.py',),
}
ENGINE_FAMILIES = {
    'A1': ('structured-spec-binding',), 'A2': ('topology-sizing',),
    'A3': ('spice-netlist-generation', 'ngspice'), 'A4': ('ngspice',),
    'A5': ('magic',), 'A6': ('klayout', 'magic', 'netgen'),
    'A7': ('magic', 'ngspice'), 'A8': ('magic', 'ngspice'),
    'A9': ('ngspice', 'iverilog'), 'M1': ('klayout', 'magic', 'netgen'),
    'M2': ('openroad', 'yosys'), 'M3': ('ngspice', 'iverilog', 'opensta'),
    'M4': ('klayout', 'magic', 'netgen'),
}


def producer_work_contract(step: str) -> dict:
    """Existing complete providers; component tools are complementary work.

    There is no source contract for a second interchangeable analog simulator.
    Keep the real family identity so the F1 scheduler can reject duplicate
    wrappers. Neither an availability payload nor ultra creates a provider.
    """
    entrypoints = {
        'A3': ['analog_a3_netlist_emit.main'], 'A4': ['analog_real_corner_sweep.run_block'],
        'A5': ['analog_a5_layout_emit.main'], 'A6': ['analog_a6_native_pv.run_block_pv'],
        'A7': ['analog_a7_post_layout_emit.run'],
        'A8': ['analog_a8_hardmacro_emit.main', 'analog_hardmacro_gds_emit.main'],
        'A9': ['analog_a9_cosim_emit.run'], 'M1': ['mixed_signal_top_lvs_run.run'],
        'M2': ['execution_analog_mixed_worker.power_domains'],
        'M3': ['analog_a9_cosim_emit.run', 'execution_analog_mixed_worker.interface_si'],
        'M4': ['execution_analog_mixed_worker.signoff'],
    }
    return dict(step_id=step, producer_sources=list(PRODUCERS[step]),
        entrypoints=entrypoints.get(step, [Path(PRODUCERS[step][0]).stem + '.main']),
        optional_entrypoints=['execution_analog_mixed_worker.characterize'] if step == 'A8' else [],
        engine_families=list(ENGINE_FAMILIES[step]),
        source_owned=step in ('A1', 'A2'), complete_source_provider_count=1,
        interchangeable_external_provider_contracts=[],
        work_kind='structured_generation' if step in ('A1', 'A2') else
            'corner_simulation' if step == 'A4' else 'complete_complementary_chain',
        all_current_canonical_obligations_required=True,
        distinct_provider_claim=False)




def write_json(path: Path, value: object) -> None:
    from _atomic_artefact import write_json as atomic
    atomic(path, value)










def covered(name: str, paths: tuple[str, ...]) -> bool:
    return any(name == p or name.startswith(p.rstrip('/') + '/')
               or fnmatch.fnmatchcase(name, p) for p in paths)


def gate_specs(step: str) -> tuple[dict, ...]:
    out = []
    def visit(node):
        if not isinstance(node, dict):
            return
        for kind in ('program_exit_zero', 'optional_program_exit_zero', 'advisory_program_exit_zero'):
            if kind in node:
                item = node[kind]
                row = {'command': item} if isinstance(item, str) else dict(item)
                row['kind'] = kind
                out.append(row)
        for key in ('all_of', 'any_of'):
            if isinstance(node.get(key), list):
                for child in node[key]:
                    visit(child)
    visit(CONTRACTS[step]['canonical_row']['gate'])
    return tuple(out)




@dataclass(frozen=True)
class AnalogContext:
    """Domain state around the exact concrete Controller Context."""
    context: em.Context
    registry: em.Registry
    project: Path
    source_files: Mapping[str, str]
    binding_at_prepare: dict

    @property
    def step_id(self):
        return self.context.step_id

    @property
    def source_sha(self):
        return self.context.source_sha

    def binding(self):
        for name, expected in self.source_files.items():
            path = Path(name)
            if path.is_symlink() or not path.is_file() or em.digest(path) != expected:
                raise em.Refusal('ADAPTER_SOURCE_MISMATCH', name)
        binding = self.context.binding()
        if binding != self.binding_at_prepare:
            raise em.Refusal('CURRENT_INPUT_CHANGED', self.step_id)
        return binding


DECLARATIONS = ('phase1/analog/analog_block_list.json',
                'phase3/analog/analog_block_list.json', 'analog/analog_block_list.json')


def declaration_path(project: Path) -> Path:
    """Name the existing declaration; never synthesize a Phase-1 copy."""
    return next((project / rel for rel in DECLARATIONS
                 if (project / rel).exists() or (project / rel).is_symlink()),
                project / DECLARATIONS[0])


def _blocks(project: Path, declaration: Path) -> tuple[str, ...]:
    if (declaration not in tuple(project / rel for rel in DECLARATIONS)
            or not declaration.is_file() or any(p.is_symlink() for p in
                (declaration, *declaration.parents))):
        raise em.Refusal('ANALOG_DECLARATION_REQUIRED', str(declaration_path(project)))
    try:
        data = json.loads(declaration.read_text())
    except (OSError, ValueError, TypeError) as exc:
        raise em.Refusal('ANALOG_DECLARATION_MALFORMED', str(declaration)) from exc
    rows = data.get('blocks') if isinstance(data, dict) else data
    if not isinstance(rows, list) or any(not isinstance(b, dict) for b in rows):
        raise em.Refusal('ANALOG_DECLARATION_MALFORMED', str(declaration))
    if isinstance(data, dict) and 'block_count' in data and (
            type(data['block_count']) is not int or data['block_count'] != len(rows)):
        raise em.Refusal('ANALOG_DECLARATION_MALFORMED', str(declaration))
    names = tuple(b.get('name') for b in rows)
    if any(not isinstance(n, str) or not n or '/' in n or n in ('.', '..') for n in names) or len(set(names)) != len(names):
        raise em.Refusal('ANALOG_BLOCK_IDENTITY_INVALID', repr(names))
    # Alternate current roots must name the same population. The selected
    # on-disk declaration itself remains a consumed, hash-bound INPUT.
    for rel in DECLARATIONS:
        candidate = project / rel
        if candidate == declaration:
            continue
        if candidate.is_symlink() or any(p.is_symlink() for p in candidate.parents):
            raise em.Refusal('ANALOG_DECLARATION_CONFLICT', rel)
        if candidate.is_file():
            try:
                other = json.loads(candidate.read_text())
            except (OSError, ValueError, TypeError) as exc:
                raise em.Refusal('ANALOG_DECLARATION_MALFORMED', str(candidate)) from exc
            count = other.get('block_count') if isinstance(other, dict) and 'block_count' in other else None
            has_count = isinstance(other, dict) and 'block_count' in other
            other = other.get('blocks') if isinstance(other, dict) else other
            if (not isinstance(other, list) or any(not isinstance(row, dict) for row in other)
                    or (has_count and (type(count) is not int or count != len(other)))
                    or tuple(row.get('name') for row in other) != names):
                raise em.Refusal('ANALOG_DECLARATION_CONFLICT', rel)
    return names


def source_requirements(step: str) -> tuple[str, ...]:
    """F1 builds this common manifest before constructing StepRequest."""
    return tuple(str(p) for p in (Path(__file__).resolve(), WORKER,
        PROGRAMS / 'execution_analog_mixed_worker.py',
        PROGRAMS / 'execution_analog_local_transport.py', CONTRACT_FILE,
        PROGRAMS / 'execution_step_protocol.py', PROGRAMS / 'execution_modes.py',
        PROGRAMS / 'execution_analog_contract.py', PROGRAMS / 'execution_analog_installation.py',
        PROGRAMS / 'analog_one_shot_runner.py', Path(sys.executable).resolve(),
        *(PROGRAMS / name for name in PRODUCERS[step]),
        *(PROGRAMS / (g['command'].split()[0] + '.py') for g in gate_specs(step))))


def source_dependencies() -> tuple[Path, ...]:
    # Bind the actual three producer paths, their gates and transitive imports.
    # Mixed and unrelated analog factories are never registered or imported.
    names = {Path(name) for step in STEP_IDS for name in source_requirements(step)}
    names.update((PROGRAMS / 'execution_policy.py',
                  PROGRAMS / 'execution_analog_caller.py',
                  PROGRAMS / 'flow_compliance_check.py',
                  PROGRAMS.parent / 'flow/phase1_phase2_phase3.yaml'))
    return tuple(sorted(names))


def installation_facts(project: Path | None, step: str, source: str, files: dict, *, prepared=None) -> tuple[dict, dict | None, list[str]]:
    """Requests are INPUT; only the shared parent verifier qualifies a receipt.

    The deployment description is project-relative so the complete PDK/model
    population joins the Controller's ordinary frozen input census.
    """
    import shutil
    missing = []
    params = dict(timeout_s=120, cpus=1, ram_mb=512, image_id='', pdk_name='',
                  pdk_root='', pv_resolution={}, extraction_styles=None)
    deployment = project / 'input/analog_native.json' if project else None
    if prepared is not None:
        data = dict(prepared)
        if data.pop('_origin', None) != 'analog-normal-entry' or data.pop('_project', None) != str(project.resolve()):
            raise em.Refusal('ANALOG_ENTRY_REQUEST_UNBOUND', str(project))
        params['entry_request_sha256'] = em._hash(prepared)
        params['entry_origin'] = 'analog-normal-entry'
        missing.extend(data.pop('_missing', []))
        missing.extend(data.pop('_step_missing', {}).get(step, []))
        request_inputs = data.pop('_input_hashes', {})
        exported = data.pop('_step_exports', {}).get(step)
        if exported:
            import execution_analog_installation as installation
            try:
                request_inputs = installation.export_inputs(project, exported, data)
            except (em.Refusal, OSError, ValueError, KeyError) as exc:
                missing.append('PDK_EXPORT_UNAVAILABLE:' + getattr(exc, 'code', type(exc).__name__))
                return params, None, missing
            data['pdk_export'] = exported
            data['pdk_root'] = exported['output_root']
            data['model_hashes'] = {k: v for k, v in request_inputs.items() if not k.endswith('/_receipt.json')}
            data['config_hashes'] = {}
            data['pdk_tree_sha256'] = em._hash(data['model_hashes'])
            data['pv_resolution'] = {k: v for k, v in exported['resolver_fields'].items()
                                     if k in ('drc_deck', 'lvs_deck')}
        configs = data.pop('_step_config_hashes', {}).get(step)
        if configs is not None:
            data['config_hashes'] = configs
            data['pdk_tree_sha256'] = em._hash({**configs, **data.get('model_hashes', {})})
            request_inputs = {k: v for k, v in request_inputs.items()
                              if k in configs or k in data.get('model_hashes', {})}
    else:
        if not deployment or not deployment.is_file() or deployment.is_symlink():
            return params, None, ['ANALOG_INSTALLATION_REQUEST_ABSENT']
        data = json.loads(deployment.read_text())
        request_inputs = {'input/analog_native.json': em.digest(deployment)}
    allowed = {'image_ref', 'image_id', 'image_manifest_digest', 'image_repo_digests',
               'pdk_name', 'pdk_root', 'pv_resolution',
               'extraction_styles', 'timeout_s', 'cpus', 'ram_mb',
               'model_hashes', 'config_hashes', 'pdk_tree_sha256', 'pdk_export'}
    if not isinstance(data, dict) or set(data) - allowed:
        raise em.Refusal('ANALOG_INSTALLATION_REQUEST_INVALID', str(deployment))
    params.update(data)
    import re
    if not re.fullmatch(r'sha256:[0-9a-f]{64}', params['image_id']):
        missing.append('PINNED_IMAGE_REQUIRED')
    for name, maximum in (('timeout_s', 1800), ('cpus', 8), ('ram_mb', 16384)):
        if type(params[name]) is not int or not 0 < params[name] <= maximum:
            raise em.Refusal('ANALOG_FINITE_BUDGET_REQUIRED', name)
    pdk = em._relative(params['pdk_root']) if params['pdk_root'] else None
    if not pdk or (not pdk.is_relative_to(Path('input')) and not params.get('pdk_export')):
        missing.append('FROZEN_PDK_ROOT_REQUIRED')
    root = project / pdk if pdk else None
    model_hashes = data.get('model_hashes', {})
    config_hashes = data.get('config_hashes', {})
    import re
    for label, manifest in (('MODEL', model_hashes), ('CONFIG', config_hashes)):
        if not isinstance(manifest, dict) or len(manifest) > 512:
            raise em.Refusal('ANALOG_DECLARED_MANIFEST_INVALID', label)
        for name, expected in manifest.items():
            relative = em._relative(name)
            if (not pdk or not relative.is_relative_to(pdk)
                    or not isinstance(expected, str) or not re.fullmatch(r'[0-9a-f]{64}', expected)):
                raise em.Refusal('ANALOG_DECLARED_MANIFEST_INVALID', name)
            path = project / relative
            if (any((project / ancestor).is_symlink() for ancestor in (relative, *relative.parents))
                    or not path.is_file() or em.digest(path) != expected):
                missing.append(label + '_UNAVAILABLE:' + name)
    if not model_hashes:
        missing.append('PDK_MODELS_UNAVAILABLE')
    # Identity is the declared bounded population, not a rescan of a cache.
    # Literal dependencies are closed before admission; native processes use
    # the same separately verified immutable image for same-root guest paths.
    pdk_tree_sha256 = em._hash({**config_hashes, **model_hashes})
    if data.get('pdk_tree_sha256') != pdk_tree_sha256:
        missing.append('PDK_MANIFEST_IDENTITY_UNBOUND')
    decks = params['pv_resolution']
    if not isinstance(decks, dict):
        raise em.Refusal('ANALOG_SIGNOFF_DECKS_REQUIRED', step)
    if step == 'A6':
        for kind in ('drc_deck', 'lvs_deck'):
            value = decks.get(kind)
            if not isinstance(value, str) or value not in {**model_hashes, **config_hashes}:
                missing.append(kind.upper() + '_UNAVAILABLE')
    docker = shutil.which('docker')
    if not docker:
        missing.append('DOCKER_UNAVAILABLE')
    params['docker'] = str(Path(docker).resolve()) if docker else ''
    if missing:
        return params, None, missing
    request_fields = dict(schema=1, step_id=step, project=str(project.resolve()), top='analog',
        image_ref=params.get('image_ref', params['image_id']), image_id=params['image_id'],
        image_manifest_digest=params.get('image_manifest_digest', ''),
        image_repo_digests=tuple(params.get('image_repo_digests', ())),
        source_sha=source, source_files=files,
        input_hashes={**request_inputs, **config_hashes, **model_hashes},
        pdk_name=params['pdk_name'], pdk_root=str(root.resolve()),
        pdk_tree_sha256=pdk_tree_sha256,
        config_hashes=config_hashes,
        model_hashes=model_hashes, engine_contract=producer_work_contract(step),
        pdk_export=params.get('pdk_export', {}))
    import execution_analog_installation as installation
    tools = ['magic', 'ngspice'] if step in ('A7', 'A8') else ['magic', 'klayout', 'netgen']
    if step == 'A6':
        from analog_a6_native_pv import deck_kind
        if deck_kind(decks.get('drc_deck', '')) == 'svrf':
            tools.append('svrfdrc')
    request_fields['engine_contract'] = dict(request_fields['engine_contract'], installation_tools=tools)
    request = installation.InstallationRequest(**request_fields)
    measured = installation.measure_installation(request, docker=params['docker'])
    if measured.status == 'NOT_MEASURED':
        return params, None, list(measured.not_measured) or ['NATIVE_INSTALLATION_NOT_MEASURED']
    try:
        receipt = installation.verify_installation(measured, request, docker=params['docker'])
    except em.Refusal as exc:
        return params, None, [exc.code]
    params['installation_verdict'] = receipt.status
    params['installation_sha256'] = em._hash(receipt.record())
    if receipt.status == 'FAIL':
        return params, receipt.record(), ['MEASURED_INSTALLATION_FAIL']
    if receipt.status != 'MEASURED' or receipt.not_measured:
        return params, None, ['NATIVE_INSTALLATION_RECEIPT_INCOMPLETE']
    return params, receipt.record(), []


def component_sources(extra=()) -> dict:
    files = {str(p.resolve()): em.digest(p) for p in
             (*source_dependencies(), Path(sys.executable).resolve(), *extra)}
    from execution_provider_catalog import source_closure, implementation_closure
    closure = source_closure({Path(name) for name in files if Path(name).suffix == '.py'})
    for entry in (*PRODUCERS['A6'], *PRODUCERS['A7'], *PRODUCERS['A8'],
                  *(row['command'].split()[0] + '.py' for step in STEP_IDS for row in gate_specs(step))):
        closure.update(implementation_closure(PROGRAMS / entry))
    files.update({str(path.resolve()): em.digest(path) for path in closure})
    for path in em._source_closure(files):
        files[str(path.resolve())] = em.digest(path)
    return files


def gate_components(step: str) -> tuple:
    # The component rc is protocol completion. The actual gate rc/report and
    # measured FAIL are consumed by the parent validator, never demoted to
    # infrastructure NM by a generic subprocess rc1 branch.
    return tuple(em.Component(row['command'].split()[0],
        (str(Path(sys.executable).resolve()), str(WORKER), '--outputs', '{outputs}',
         '--observe-gate', row['command'].split()[0]), 125)
        for row in gate_specs(step) if row['kind'] == 'program_exit_zero')


def register_adapters(registry: em.Registry, *, project: Path | None = None, request=None) -> None:
    """Register A6/A7/A8 once, before the existing Controller finalizes it."""
    from execution_synthesis_engines import source_sha
    source = source_sha()
    files = component_sources()
    for step in STEP_IDS:
        params, receipt, missing = installation_facts(project, step, source, files, prepared=request)
        population_params = params
        if project:
            from execution_analog_installation import transport_parameters
            params = transport_parameters(project, step, params)
        objective = dict(metric='canonical_evidence', direction='max', parameters=params,
                         parameters_sha256=em._hash(params), source_manifest_sha256=em._hash(files),
                         blocks=list(_blocks(project, declaration_path(project)))
                         if project and declaration_path(project).is_file() else [],
                         original_project=str(project.resolve()) if project else '',
                         declaration_sha256=em.digest(declaration_path(project))
                         if project and declaration_path(project).is_file() else '')
        required = ('producer.json', 'products.json', 'canonical-gates.json',
                    'native-launch.json', 'native-processes.jsonl',
                    'producer-work.json', 'producer-calls/calls.json')
        registry.register(em.Adapter(
            'analog-' + step.lower(), 'analog-worker', step, source, files,
            'verified-current-installation' if receipt else 'NOT_MEASURED:installation', ENGINE_FAMILIES[step],
            (em.Component('produce-and-semantic-gates',
                (str(Path(sys.executable).resolve()), str(WORKER),
                 '--inputs', '{inputs}', '--outputs', '{outputs}'), params['timeout_s'] + 180),
             *gate_components(step)),
            validate, required, objective,
            qualified=receipt is not None and not missing,
            available=receipt is not None and not missing,
            qualification_evidence=em._hash(receipt) if receipt else 'native_installation_receipt missing',
            availability_reason=','.join(missing), cpus=params['cpus'], ram_mb=params['ram_mb'],
            applicability=('inapplicable' if objective['declaration_sha256'] and
                           not objective['blocks'] else 'applicable'),
            applicability_reason=('declared analog block population is empty'
                                  if objective['declaration_sha256'] and not objective['blocks'] else ''),
            own_no_tool_reason='One complete complementary producer; no second interchangeable provider.',
            output_contract={key: required for key in
                CONTRACTS[step]['portfolio_policy']['required_output_contract']},
            input_contract=(*DECLARATIONS,
                *(() if params.get('entry_origin') == 'analog-normal-entry' else ('input/analog_native.json',)),
                *tuple(population_params.get('model_hashes', {})), *tuple(population_params.get('config_hashes', {})),
                *tuple([population_params['pdk_export']['output_root'] + '/_receipt.json'] if population_params.get('pdk_export') else []),
                *tuple('phase1/generated_docs/' + name + '.json' for name in
                    ('L5_ADI_SPEC', 'L9_INTEGRATION_SPEC', 'L19_CONSTRAINTS_PDK')),
                *tuple(f'phase3/analog/{block}/{name}'
                    for block in objective['blocks'] if step == 'A8'
                    for name in ('pre_vs_post.json', 'a5_stdcell_pg.lef')),
                *tuple(f'phase3/analog/{block}/{name}' for block in objective['blocks']
                    for name in ('spec.json', 'topology.json', 'topology.md', 'layout.mag',
                        block + '.gds', block + '.sp', 'tb_' + block + '.sp',
                        'layout_provenance.json', 'netlist_provenance.json',
                        'corner_results.json', 'characterization_plan.json')))))



def prepare(context: em.Context, *, project: Path, registry: em.Registry,
            controller: em.Controller) -> AnalogContext:
    """BLOCKING: prepare within the ordinary live outer Controller invocation.

    The issuer request, source, route and current INPUT are the concrete
    Context's existing binding. The finalized Registry is reused unchanged;
    no worker lease, inner issuer or native qualification is manufactured.
    """
    if type(context) is not em.Context or context.step_id not in STEP_IDS:
        raise em.Refusal('ANALOG_STEP_CONTEXT_UNBOUND', str(getattr(context, 'step_id', None)))
    if type(controller) is not em.Controller or controller.registry is not registry:
        raise em.Refusal('PRODUCTION_CHILD_SCOPE_UNBOUND', 'ordinary live Controller required')
    binding = controller._context_binding(context)
    # Controller serializes this exact value into one environment entry.
    # Keep margin below Linux MAX_ARG_STRLEN without reducing frozen INPUT.
    if len(json.dumps(binding).encode()) >= 120 * 1024:
        raise em.Refusal('ANALOG_BINDING_TRANSPORT_TOO_LARGE', context.step_id)
    if str(project.resolve()) != context.route_receipt.get('project'):
        raise em.Refusal('ANALOG_FRONTDOOR_PROJECT_DISAGREES', str(project))
    declaration = declaration_path(project)
    if (not declaration.is_file() or declaration.is_symlink()
            or em.digest(declaration) != context.objective.get('declaration_sha256')
            or list(_blocks(project, declaration)) != context.objective.get('blocks')):
        raise em.Refusal('ANALOG_DECLARATION_CHANGED', str(declaration))
    adapters = registry.adapters(context.step_id)
    if len(adapters) != 1 or adapters[0].arm_id != 'analog-' + context.step_id.lower():
        raise em.Refusal('ANALOG_REGISTERED_PROVIDER_UNBOUND', context.step_id)
    adapter = adapters[0]
    if adapter.source_sha != context.source_sha:
        raise em.Refusal('SOURCE_AUTHORITY_STALE', context.step_id)
    for filename in source_requirements(context.step_id):
        if filename not in adapter.source_files:
            raise em.Refusal('ANALOG_SOURCE_DEPENDENCY_UNBOUND', filename)
    prepared = AnalogContext(context, registry, project.resolve(), adapter.source_files, binding)
    prepared.binding()
    return prepared


def validate(outputs: Path, binding: dict) -> em.Evidence:
    from execution_analog_worker import validate_outputs
    return validate_outputs(outputs, binding)




def consume(project: Path, context: AnalogContext, controller: em.Controller,
            run: Path, adopted: dict) -> dict:
    """Reconsume the live outer receipt chain; NM/FAIL never imports outputs."""
    if type(context) is not AnalogContext or type(controller) is not em.Controller:
        raise em.Refusal('PRODUCTION_CHILD_SCOPE_UNBOUND', 'ordinary live Controller required')
    if controller.registry is not context.registry or project.resolve() != context.project:
        raise em.Refusal('ANALOG_FRONTDOOR_PROJECT_DISAGREES', str(project))
    binding = context.binding()
    if controller._context_binding(context.context) != binding:
        raise em.Refusal('CURRENT_INPUT_CHANGED', context.step_id)
    plan = em._issued(run / 'issued-plan.json')
    if plan.get('binding') != binding or plan.get('run_root') != str(run.resolve()):
        raise em.Refusal('ANALOG_CURRENT_INVOCATION_UNBOUND', context.step_id)
    try:
        chain = controller._verify_receipt_chain(run, plan, context.context)
    except em.Refusal as exc:
        if exc.code != 'GATE_FAIL':
            raise
        return dict(status='FAIL', step_id=context.step_id, selected=None,
                    reason='GATE_FAIL', run_root=str(run), consumer='analog.consume')
    if adopted.get('status') != 'ADOPTED':
        comparison = chain['comparison']
        return dict(status='FAIL' if comparison['status'] == 'FAIL' or
                        binding['objective']['parameters'].get('installation_verdict') == 'FAIL' else 'NOT_MEASURED',
                    step_id=context.step_id, selected=None,
                    reason=adopted.get('reason', comparison['status']), run_root=str(run),
                    consumer='analog.consume', binding=binding,
                    comparison_sha256=chain['comparison_digest'])
    verified = controller.verify_adoption(context.context, run)
    if dict(adopted) != verified:
        raise em.Refusal('ANALOG_ADOPTION_PAYLOAD_CHANGED', context.step_id)
    generation = verified['selected_generation']
    from execution_analog_worker import checked_json, read_canonical_report, semantic_gates, canonical_report, report_obligations
    from execution_backend_snapshot import Journal
    selected = Path(generation['directory'])
    report = read_canonical_report(selected, binding,
        expected_sha256=generation['outputs']['canonical-gates.json'])
    manifest = checked_json(selected / 'products.json')
    producer = checked_json(selected / 'producer.json')
    journal = Journal(project)
    try:
        for name, expected in generation['outputs'].items():
            if em.digest(selected / em._relative(name)) != expected:
                raise em.Refusal('SELECTED_ARTIFACT_CHANGED', name)
        for name, expected in manifest['products'].items():
            if not covered(name, tuple(producer['adoption_paths'])) or generation['outputs'].get('project/' + name) != expected:
                raise em.Refusal('ANALOG_SELECTED_PRODUCT_UNBOUND', name)
            journal.write(name, (selected / 'project' / name).read_bytes())
        controller.verify_adoption(context.context, run)
        # Re-read through the existing canonical gate programs on the imported
        # project. Rehash products and selected generation after the read.
        fresh = semantic_gates(context.step_id, project, run / 'canonical-consumer')
        consumed = canonical_report(fresh, binding, project, run,
                                    report['source_files'], producer['design_verdict'],
                                    producer_work=report.get('producer_work'))
        report_obligations(consumed, binding, project)
        if consumed['steps'][0]['status'] != 'PASS':
            raise em.Refusal('ANALOG_CANONICAL_CONSUMER_REFUSED', context.step_id)
        for name, expected in manifest['products'].items():
            if em.digest(project / name) != expected:
                raise em.Refusal('ANALOG_CONSUMER_REWROTE_SELECTED_PRODUCT', name)
        controller.verify_adoption(context.context, run)
    except Exception:
        journal.rollback()
        raise
    return dict(verified, status='PASS', step_id=context.step_id, run_root=str(run),
                consumer='analog.consume', canonical_consumer=consumed)
