"""Bounded parent-side analog installation facts, never execution authority.

The exact image, declared model/deck bytes and actual native tool commands are
measured through the existing ephemeral container supervisor. No recursive PDK
census, caller qualification bit, Controller, capability or waiver.
"""
from dataclasses import asdict, dataclass, field
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
from typing import Mapping

import execution_modes as em
import librelane_contract as lc
import _docker_memory as _dmem


@dataclass(frozen=True)
class InstallationRequest:
    schema: int
    step_id: str
    project: str
    top: str
    image_ref: str
    image_id: str
    image_manifest_digest: str
    image_repo_digests: tuple
    source_sha: str
    source_files: Mapping[str, str]
    input_hashes: Mapping[str, str]
    pdk_name: str
    pdk_root: str
    pdk_tree_sha256: str
    config_hashes: Mapping[str, str]
    model_hashes: Mapping[str, str]
    engine_contract: Mapping[str, object]
    pdk_export: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self):
        # JSON descriptions carry lists; live typed requests use one canonical
        # tuple so qualification compares the same observed membership.
        object.__setattr__(self, 'image_repo_digests', tuple(sorted(self.image_repo_digests)))


@dataclass(frozen=True)
class InstallationReceipt:
    schema: int
    status: str
    request_sha256: str
    request: Mapping[str, object]
    image_id: str
    tool_commands: tuple
    model_hashes: Mapping[str, str]
    not_measured: tuple
    raw_stdout: str
    raw_stderr: str
    process_rc: int | None
    image_facts: Mapping[str, object]

    def record(self):
        return asdict(self)


# Version probes are explicit source-owned contracts. A tool's presence alone
# is insufficient; its resolved executable, bytes, actual exit and text join
# the receipt. Netgen's Tcl batch interpreter reports its package version.
TOOL_COMMANDS = {
    'magic': ('magic', '--version'), 'klayout': ('klayout', '-v'),
    'ngspice': ('ngspice', '-v'), 'svrfdrc': ('svrfdrc', '--version'),
    'netgen': ('netgen', '-batch'),
}
PROBE = r'''
import hashlib, json, pathlib, shutil, subprocess, sys
request=json.loads(sys.argv[1]); tools=[]; missing=[]; fail=False
for name, argv in request['commands'].items():
    executable=shutil.which(argv[0])
    if not executable:
        missing.append('TOOL_UNAVAILABLE:'+name); continue
    path=pathlib.Path(executable).resolve()
    try:
        run=subprocess.run([str(path), *argv[1:]], capture_output=True, text=True, timeout=8,
                           input='puts [package require netgen]; quit\n' if name == 'netgen' else None)
        version=(run.stdout+run.stderr).strip()
        row=dict(tool=name, argv=[str(path), *argv[1:]], executable=str(path),
                 executable_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                 rc=run.returncode, version=version)
        fail |= run.returncode != 0
        if not version: missing.append('VERSION_UNAVAILABLE:'+name)
    except (OSError, subprocess.TimeoutExpired) as exc:
        row=dict(tool=name, argv=argv, executable=str(path), rc=None, detail=type(exc).__name__)
        missing.append('TOOL_NOT_MEASURED:'+name)
    tools.append(row)
models={}
for name, expected in request['models'].items():
    path=pathlib.Path(name)
    if not path.is_file(): missing.append('MODEL_UNAVAILABLE:'+name); continue
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1048576), b''): digest.update(chunk)
    models[name]=digest.hexdigest()
    if models[name] != expected: missing.append('MODEL_CHANGED:'+name)
print(json.dumps(dict(tools=tools, models=models, missing=missing,
                     status='FAIL' if fail else 'NOT_MEASURED' if missing else 'MEASURED')))
'''


def inspect_image(image_ref: str, *, docker='docker') -> dict:
    """Bind the immutable manifest ref to the actual local runnable image.

    Registry manifest digests and Docker configuration IDs are separate
    identities. Inspect only local metadata; never pull an image here.
    """
    import _eda_pin as pin
    manifest = pin.reference_digest(image_ref)
    if not manifest or not re.fullmatch(r'sha256:[0-9a-f]{64}', manifest):
        raise em.Refusal('ANALOG_PINNED_IMAGE_REQUIRED', image_ref)
    done = subprocess.run([docker, 'image', 'inspect', '--format',
                           '{{.Id}}\t{{json .RepoDigests}}', image_ref],
                          capture_output=True, text=True, timeout=20)
    if done.returncode != 0:
        raise em.Refusal('ANALOG_IMAGE_UNAVAILABLE', image_ref)
    try:
        image_id, raw = done.stdout.strip().split('\t', 1)
        digests = json.loads(raw)
    except (ValueError, TypeError):
        raise em.Refusal('ANALOG_IMAGE_METADATA_UNAVAILABLE', image_ref)
    if (not re.fullmatch(r'sha256:[0-9a-f]{64}', image_id)
            or not isinstance(digests, list) or image_ref not in digests
            or any(not isinstance(ref, str) for ref in digests)):
        raise em.Refusal('ANALOG_IMAGE_REF_ID_UNBOUND', image_ref)
    return dict(image_ref=image_ref, image_id=image_id,
                image_manifest_digest=manifest, image_repo_digests=sorted(digests))


def export_inputs(project: Path, exported: Mapping[str, object], image: Mapping[str, object]) -> dict:
    """Recheck the frozen helper's exact receipt, image and copied population."""
    import execution_analog_pdk_export as export
    digest = exported.get('receipt_digest', '')
    root = exported.get('output_root')
    if (exported.get('status') != 'MEASURED' or exported.get('schema') != export.SCHEMA
            or not re.fullmatch(r'[0-9a-f]{64}', str(digest))
            or root != (export.OUTPUT_BASE / digest).as_posix()):
        raise em.Refusal('ANALOG_PDK_EXPORT_RECEIPT_UNBOUND', str(root))
    relative = em._relative(root)
    receipt_path = project / relative / '_receipt.json'
    if any((project / p).is_symlink() for p in (relative, *relative.parents)) or receipt_path.is_symlink():
        raise em.Refusal('ANALOG_PDK_EXPORT_OUTPUT_CHANGED', str(root))
    receipt = json.loads(receipt_path.read_text())
    body = {k: v for k, v in receipt.items() if k not in ('receipt_digest', 'output_root')}
    if (receipt.get('receipt_digest') != digest or receipt.get('output_root') != root
            or hashlib.sha256(export._canonical(body)).hexdigest() != digest
            or receipt_path.read_bytes() != export._canonical(receipt) + b'\n'):
        raise em.Refusal('ANALOG_PDK_EXPORT_RECEIPT_UNBOUND', str(root))
    for key in ('image_ref', 'image_id', 'image_manifest_digest'):
        if receipt.get(key) != image.get(key) or exported.get(key) != image.get(key):
            raise em.Refusal('ANALOG_PDK_EXPORT_IMAGE_UNBOUND', key)
    if (tuple(sorted(receipt.get('image_repo_digests', ()))) != tuple(sorted(image.get('image_repo_digests', ())))
            or image.get('image_ref') not in receipt.get('image_repo_digests', ())):
        raise em.Refusal('ANALOG_PDK_EXPORT_IMAGE_UNBOUND', 'RepoDigests')
    limits = receipt['limits']
    if (type(limits.get('max_files')) is not int or not 1 <= limits['max_files'] <= 512
            or type(limits.get('max_bytes')) is not int or not 1 <= limits['max_bytes'] <= 67108864):
        raise em.Refusal('ANALOG_PDK_EXPORT_POPULATION_INVALID', 'limits')
    export._validate_population(project / relative, receipt['files'], receipt['pdk_root'],
                                limits['max_files'], limits['max_bytes'])
    current = export._result_from_receipt(receipt, project, bool(exported.get('reused')))
    if any(exported.get(k) != v for k, v in current.items() if k != 'reused'):
        raise em.Refusal('ANALOG_PDK_EXPORT_RECEIPT_UNBOUND', 'returned fields')
    if (exported.get('helper_sha256') != em.digest(Path(export.__file__))
            or exported.get('receipt_sha256') != em.digest(receipt_path)):
        raise em.Refusal('ANALOG_PDK_EXPORT_SOURCE_OR_RECEIPT_CHANGED', str(root))
    return {**{(relative / row['relative_path']).as_posix(): row['sha256'] for row in receipt['files']},
            (relative / '_receipt.json').as_posix(): em.digest(receipt_path)}


@dataclass(frozen=True)
class ExportReference:
    """Small integrity facts; the staged receipt remains the full population."""
    schema: int
    project: str
    step_id: str
    output_root: str
    receipt_digest: str
    receipt_sha256: str
    helper_sha256: str
    image_ref: str
    image_id: str
    image_manifest_digest: str
    image_repo_digests: tuple
    pdk_root_binding: Mapping[str, object]
    population_count: int
    population_digest: str


def transport_parameters(project: Path, step: str, parameters: dict) -> dict:
    """Keep the normal objective small without reducing its frozen inputs."""
    exported = parameters.get('pdk_export')
    if not exported:
        return dict(parameters)
    population = export_inputs(project, exported, parameters)
    population.pop(exported['output_root'] + '/_receipt.json')
    receipt = json.loads((project / exported['output_root'] / '_receipt.json').read_text())
    reference = ExportReference(1, str(project.resolve()), step,
        exported['output_root'], exported['receipt_digest'], exported['receipt_sha256'],
        exported['helper_sha256'], parameters['image_ref'], parameters['image_id'],
        parameters['image_manifest_digest'], tuple(parameters['image_repo_digests']),
        receipt.get('pdk_root_binding', {}), len(population), em._hash(population))
    small = {k: v for k, v in parameters.items()
             if k not in ('pdk_export', 'model_hashes', 'config_hashes')}
    small['pdk_export_reference'] = dict(asdict(reference),
        image_repo_digests=list(reference.image_repo_digests))
    if len(json.dumps(small).encode()) > 8192:
        raise em.Refusal('ANALOG_TRANSPORT_PARAMETERS_TOO_LARGE', step)
    return small


def worker_parameters(inputs: Path, binding: dict, parameters: dict) -> dict:
    """Reconstruct producer facts from current frozen bytes, never authority."""
    raw = parameters.get('pdk_export_reference')
    if raw is None:
        return dict(parameters)
    try:
        reference = ExportReference(**raw)
    except (TypeError, ValueError) as exc:
        raise em.Refusal('ANALOG_EXPORT_REFERENCE_INVALID', str(exc)) from exc
    if (reference.schema != 1 or reference.step_id != binding['step_id']
            or reference.project != binding['objective']['original_project']
            or reference.output_root != parameters['pdk_root']
            or any(getattr(reference, key) != parameters.get(key) for key in
                   ('image_ref', 'image_id', 'image_manifest_digest'))
            or tuple(reference.image_repo_digests) != tuple(parameters.get('image_repo_digests', ()))):
        raise em.Refusal('ANALOG_EXPORT_REFERENCE_CONTEXT_MISMATCH', binding['step_id'])
    relative = em._relative(reference.output_root) / '_receipt.json'
    path = inputs / relative
    if (not path.is_file() or any((inputs / part).is_symlink() for part in
            (relative, *relative.parents)) or em.digest(path) != reference.receipt_sha256
            or binding['inputs'].get(relative.as_posix()) != reference.receipt_sha256):
        raise em.Refusal('ANALOG_EXPORT_REFERENCE_RECEIPT_CHANGED', str(relative))
    import execution_analog_pdk_export as export
    receipt = json.loads(path.read_text())
    if (receipt.get('receipt_digest') != reference.receipt_digest
            or receipt.get('output_root') != reference.output_root
            or receipt.get('pdk_root_binding', {}) != reference.pdk_root_binding):
        raise em.Refusal('ANALOG_EXPORT_REFERENCE_ROOT_OR_GENERATION_CHANGED', str(relative))
    exported = dict(export._result_from_receipt(receipt, inputs, False),
        helper_sha256=reference.helper_sha256, receipt_sha256=reference.receipt_sha256)
    population = export_inputs(inputs, exported, asdict(reference))
    if any(binding['inputs'].get(name) != digest for name, digest in population.items()):
        raise em.Refusal('ANALOG_EXPORT_REFERENCE_INPUT_UNBOUND', reference.step_id)
    population.pop(relative.as_posix())
    if (len(population) != reference.population_count
            or em._hash(population) != reference.population_digest
            or parameters['pdk_tree_sha256'] != reference.population_digest):
        raise em.Refusal('ANALOG_EXPORT_REFERENCE_POPULATION_CHANGED', reference.step_id)
    result = dict(parameters, pdk_export=exported, model_hashes=population, config_hashes={})
    result['pv_resolution'] = {key: value for key, value in exported['resolver_fields'].items()
                               if key in ('drc_deck', 'lvs_deck')}
    return result


def _bound(request: InstallationRequest) -> dict:
    if type(request) is not InstallationRequest or request.schema != 1 or request.step_id not in ('A6', 'A7', 'A8'):
        raise em.Refusal('ANALOG_INSTALLATION_REQUEST_INVALID', 'typed A6/A7/A8 request required')
    if not re.fullmatch(r'sha256:[0-9a-f]{64}', request.image_id):
        raise em.Refusal('ANALOG_PINNED_IMAGE_REQUIRED', request.image_id)
    import _eda_pin as pin
    if (pin.reference_digest(request.image_ref) != request.image_manifest_digest
            or not re.fullmatch(r'sha256:[0-9a-f]{64}', request.image_manifest_digest)
            or request.image_ref not in request.image_repo_digests):
        raise em.Refusal('ANALOG_IMAGE_REF_ID_UNBOUND', request.image_ref)
    if not re.fullmatch(r'[0-9a-f]{40}', request.source_sha):
        raise em.Refusal('ANALOG_INSTALLATION_SOURCE_UNBOUND', request.source_sha)
    from execution_synthesis_engines import source_sha
    if request.source_sha != source_sha():
        raise em.Refusal('ANALOG_INSTALLATION_SOURCE_UNBOUND', request.source_sha)
    for name, expected in request.source_files.items():
        path = Path(name)
        if path.is_symlink() or not path.is_file() or em.digest(path) != expected:
            raise em.Refusal('ANALOG_INSTALLATION_SOURCE_CHANGED', name)
    project = Path(request.project)
    if not project.is_absolute() or project.is_symlink():
        raise em.Refusal('ANALOG_INSTALLATION_PROJECT_UNBOUND', str(project))
    if request.pdk_export:
        current = export_inputs(project, request.pdk_export, asdict(request))
        if (request.pdk_root != str(project / request.pdk_export['output_root'])
                or any(request.input_hashes.get(k) != v for k, v in current.items())):
            raise em.Refusal('ANALOG_PDK_EXPORT_INPUT_UNBOUND', request.step_id)
    models = {**request.config_hashes, **request.model_hashes}
    if not models or len(models) > 512 or em._hash(models) != request.pdk_tree_sha256:
        raise em.Refusal('ANALOG_PDK_MANIFEST_UNBOUND', request.step_id)
    for name, expected in request.input_hashes.items():
        path = project / em._relative(name)
        if (any((project / part).is_symlink() for part in (Path(name), *Path(name).parents))
                or not path.is_file() or em.digest(path) != expected):
            raise em.Refusal('ANALOG_INSTALLATION_INPUT_CHANGED', name)
    for name, expected in models.items():
        path = project / em._relative(name)
        if request.input_hashes.get(name) != expected or not path.is_relative_to(Path(request.pdk_root)):
            raise em.Refusal('ANALOG_PDK_MANIFEST_UNBOUND', name)
    tools = request.engine_contract.get('installation_tools')
    required = {'A6': {'magic', 'klayout', 'netgen'}, 'A7': {'magic', 'ngspice'},
                'A8': {'magic', 'ngspice'}}[request.step_id]
    if (not isinstance(tools, list) or not required.issubset(tools)
            or len(set(tools)) != len(tools) or any(name not in TOOL_COMMANDS for name in tools)):
        raise em.Refusal('ANALOG_INSTALLATION_ENGINE_UNBOUND', request.step_id)
    return dict(commands={name: TOOL_COMMANDS[name] for name in tools},
                models={str(project / name): expected for name, expected in models.items()})


def measure_installation(request: InstallationRequest, *, docker='docker') -> InstallationReceipt:
    probe = _bound(request)
    argv = [docker, 'run', *_dmem.docker_memory_flags(), '--rm', '--network', 'none', '--cpus', '1',
            '--user', f'{os.getuid()}:{os.getgid()}']
    # Only the enumerated regular files are exposed to this bounded probe.
    for name in sorted(probe['models']):
        argv.extend(('-v', name + ':' + name + ':ro'))
    argv.extend((request.image_ref, '--skip', 'python3', '-c', PROBE, json.dumps(probe, sort_keys=True)))
    safe_env = {k: v for k, v in os.environ.items() if not k.startswith('VIBEIC_EXECUTION')}
    raw, err, rc, missing, status, commands, models = '', '', None, (), 'NOT_MEASURED', (), {}
    image_facts = {}
    try:
        image_facts = inspect_image(request.image_ref, docker=docker)
        if (image_facts['image_id'] != request.image_id
                or image_facts['image_manifest_digest'] != request.image_manifest_digest
                or tuple(image_facts['image_repo_digests']) != request.image_repo_digests):
            raise em.Refusal('ANALOG_IMAGE_REF_ID_CHANGED', request.image_ref)
        done = lc.run_container(argv, probe_deadline_s=60, env=safe_env)
        raw, err, rc = done.stdout or '', done.stderr or '', done.returncode
        data = json.loads(raw.strip().splitlines()[-1]) if rc == 0 else {}
        commands = tuple(data.get('tools', ()))
        models = data.get('models', {})
        missing = tuple(data.get('missing', ()))
        status = data.get('status', 'NOT_MEASURED')
        wanted = set(probe['commands'])
        observed = {row.get('tool') for row in commands if isinstance(row, dict)}
        if any(type(row.get('rc')) is int and row['rc'] != 0 for row in commands):
            status = 'FAIL'
        elif (observed != wanted or models != probe['models'] or
              any(row.get('rc') != 0 or not row.get('version') or
                  not re.fullmatch(r'[0-9a-f]{64}', row.get('executable_sha256', '')) for row in commands)):
            status = 'NOT_MEASURED'
            missing = (*missing, 'INCOMPLETE_INSTALLATION_POPULATION')
        if not commands or status not in ('MEASURED', 'FAIL', 'NOT_MEASURED'):
            status, missing = 'NOT_MEASURED', (*missing, 'IMAGE_OR_TOOL_OUTPUT_UNAVAILABLE')
    except (em.Refusal, lc.Refusal, OSError, ValueError, IndexError, subprocess.SubprocessError) as exc:
        missing = (type(exc).__name__ + ':' + str(exc),)
    _bound(request)
    return InstallationReceipt(1, status, em._hash(asdict(request)), asdict(request),
                               request.image_id, commands, models, missing, raw, err, rc, image_facts)


def verify_installation(receipt: InstallationReceipt, request: InstallationRequest, *, docker='docker') -> InstallationReceipt:
    _bound(request)
    if (type(receipt) is not InstallationReceipt or receipt.schema != 1
            or receipt.request_sha256 != em._hash(asdict(request))
            or receipt.request != asdict(request) or receipt.image_id != request.image_id):
        raise em.Refusal('ANALOG_INSTALLATION_RECEIPT_UNBOUND', request.step_id)
    if receipt.status in ('MEASURED', 'FAIL'):
        expected_image = dict(image_ref=request.image_ref, image_id=request.image_id,
            image_manifest_digest=request.image_manifest_digest,
            image_repo_digests=list(request.image_repo_digests))
        if receipt.image_facts != expected_image:
            raise em.Refusal('ANALOG_IMAGE_REF_ID_UNBOUND', request.image_ref)
        try:
            raw = json.loads(receipt.raw_stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            raise em.Refusal('ANALOG_INSTALLATION_RAW_CHANGED', request.step_id)
        if (receipt.process_rc != 0 or tuple(raw.get('tools', ())) != receipt.tool_commands
                or raw.get('models', {}) != receipt.model_hashes):
            raise em.Refusal('ANALOG_INSTALLATION_RAW_CHANGED', request.step_id)
    fresh = measure_installation(request, docker=docker)
    # Qualification is granted only by fresh measured facts. A measured
    # failure stays terminal even if a later sibling measurement is missing.
    if receipt.status == 'FAIL' or fresh.status == 'FAIL':
        return receipt if receipt.status == 'FAIL' else fresh
    if (fresh.status != 'MEASURED' or receipt.status != 'MEASURED'
            or fresh.tool_commands != receipt.tool_commands or fresh.model_hashes != receipt.model_hashes):
        raise em.Refusal('ANALOG_INSTALLATION_NOT_CURRENT', request.step_id)
    return fresh


def _command_text(line: str, *, slash_comments: bool = True) -> str:
    """Strip an inline comment outside quotes; keep literal path bytes."""
    quote, escaped = None, False
    for index, char in enumerate(line):
        if escaped:
            escaped = False
            continue
        if char == '\\':
            escaped = True
        elif quote:
            if char == quote:
                quote = None
        elif char in ('"', "'"):
            quote = char
        elif char == '#' or (slash_comments and line[index:index + 2] == '//'):
            return line[:index]
    return line


def prepare_entry_request(project: Path, args) -> dict:
    """Program-owned normal entry facts; never rewrite owner INPUT.

    Existing resolver paths are a seed, not proof of completeness. Close only
    explicit SPICE includes, refusing unknown/escaping references and model
    paths held only in a container/cache. No whole-PDK or worktree census.
    """
    import analog_one_shot_runner as runner
    import analog_pdk_availability as resolver
    import _eda_pin as pin
    project = project.resolve()
    target = runner._effective_analog_pdk(args, project)
    request = dict(_origin='analog-normal-entry', _project=str(project), _missing=[],
                   _step_missing={step: [] for step in ('A6', 'A7', 'A8')},
                   _step_config_hashes={}, _input_hashes={}, image_id='', image_ref='',
                   image_manifest_digest='', image_repo_digests=[], pdk_name=target,
                   pdk_root='input/pdk', pv_resolution={}, model_hashes={}, config_hashes={},
                   timeout_s=120, cpus=1, ram_mb=512)
    missing = request['_missing']
    if not target and not (project / 'input/pdk').is_dir():
        missing.extend(('PDK_TARGET_UNSTATED', 'BOUNDED_MODEL_POPULATION_UNAVAILABLE'))
        request['pdk_tree_sha256'] = em._hash({})
        return request
    try:
        image, reason = pin.pinned_image_present()
        if image:
            request.update(inspect_image(image))
        else:
            missing.append('PINNED_IMAGE_UNAVAILABLE:' + str(reason))
    except (em.Refusal, OSError, ValueError, subprocess.SubprocessError) as exc:
        missing.append('PINNED_IMAGE_UNAVAILABLE:' + str(exc))
    listing_deadline = time.monotonic() + 120
    listings = {}
    def pinned_lister(path):
        relative = Path(path).relative_to(resolver.DEFAULT_PDKS_ROOT)
        if '..' in relative.parts or len(listings) >= 64:
            raise em.Refusal('ANALOG_RESOLVER_LISTING_LIMIT', path)
        if path not in listings:
            remaining = min(20, listing_deadline - time.monotonic())
            if remaining <= 0 or not request['image_ref']:
                raise em.Refusal('ANALOG_RESOLVER_NOT_MEASURED', path)
            argv = ['docker', 'run', *_dmem.docker_memory_flags(), '--rm', '--network', 'none', '--cpus', '1',
                request['image_ref'], '--skip',
                'python3', '-c', 'import json,pathlib,sys; p=pathlib.Path(sys.argv[1]); '
                'print(json.dumps(sorted(x.name for x in p.iterdir()) if p.is_dir() else []))', path]
            env = {k: v for k, v in os.environ.items() if not k.startswith('VIBEIC_EXECUTION')}
            done = lc.run_container(argv, probe_deadline_s=remaining, env=env)
            if done.returncode != 0 or len(done.stdout or '') > 1048576:
                raise em.Refusal('ANALOG_RESOLVER_NOT_MEASURED', path)
            rows = json.loads(done.stdout.strip().splitlines()[-1])
            if not isinstance(rows, list) or len(rows) > 4096 or any(not isinstance(x, str) for x in rows):
                raise em.Refusal('ANALOG_RESOLVER_LISTING_LIMIT', path)
            listings[path] = rows
        return listings[path]
    try:
        facts = resolver.resolve_pdk(target or None, project=str(project), lister=pinned_lister)
    except Exception as exc:
        missing.append('RESOLVER_FACTS_UNAVAILABLE:' + type(exc).__name__)
        facts = {}
    models = facts.get('spice_libs') or []
    if not models:
        missing.append('BOUNDED_MODEL_POPULATION_UNAVAILABLE')
    if facts.get('source') != 'project_custom_pdk':
        import execution_analog_pdk_export as export
        def measured_export(resolved):
            try:
                value = export.export_bounded_pdk(project, target=target,
                    image_ref=request['image_ref'], image_id=request['image_id'], resolver_facts=resolved)
                if value.get('status') != 'MEASURED':
                    return None, value.get('not_measured') or value.get('refusal_reasons') or ['PDK_EXPORT_NOT_MEASURED']
                value = {**value, 'helper_sha256': em.digest(Path(export.__file__)),
                    'receipt_sha256': em.digest(project / value['output_root'] / '_receipt.json')}
                export_inputs(project, value, request)
                return value, []
            except (em.Refusal, lc.Refusal, OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
                return None, ['PDK_EXPORT_UNAVAILABLE:' + getattr(exc, 'code', type(exc).__name__)]
        # Keep an A6-only deck closure failure out of A7/A8 admission.
        common, reasons = measured_export({**facts, 'drc_deck': None, 'lvs_deck': None})
        if not common:
            missing.extend(reasons)
            request['pdk_tree_sha256'] = em._hash({})
            return request
        a6, reasons = measured_export(facts) if facts.get('drc_deck') or facts.get('lvs_deck') else (common, [])
        request['_step_missing']['A6'].extend(reasons)
        request['_step_exports'] = dict(A6=a6 or common, A7=common, A8=common)
        population = export_inputs(project, common, request)
        population.pop(common['output_root'] + '/_receipt.json')
        request.update(pdk_root=common['output_root'], model_hashes=population,
                       config_hashes={}, pdk_tree_sha256=em._hash(population))
        return request

    # Walk only explicitly resolved roots and their literal include edges.
    # Any import construct outside this literal subset refuses admission.
    # A read-write product mount is not proof of a consumed input population.
    def close(roots, kind, errors):
        manifest, seen, pending = {}, set(), list(roots)
        while pending:
            value = pending.pop()
            path = Path(value)
            path = path if path.is_absolute() else project / value
            original = path
            path = Path(os.path.normpath(str(path)))
            # Normalize lexically before IO; a parent edge may stay within the
            # one declared PDK root, but an escape never reaches the filesystem.
            if '..' in original.parts and not path.is_relative_to(project / 'input/pdk'):
                errors.append('DECLARED_INCLUDE_PATH_UNSAFE:' + value); continue
            try:
                name = str(path.relative_to(project))
            except ValueError:
                errors.append('PROJECT_BOUNDED_EXPORT_UNAVAILABLE:' + value); continue
            if name in seen:
                continue
            seen.add(name)
            if len(seen) > 512:
                errors.append('BOUNDED_MODEL_POPULATION_LIMIT'); break
            try:
                original_parts = original.relative_to(project).parts
            except ValueError:
                errors.append('DECLARED_INCLUDE_PATH_UNSAFE:' + value); continue
            # A symlink before an erased '..' changes the tool's actual target.
            # Check those original prefixes as well as the normalized target.
            if any((project / Path(*original_parts[:end])).is_symlink()
                   for end in range(1, len(original_parts) + 1)):
                errors.append('DECLARED_MODEL_OR_DECK_UNAVAILABLE:' + name); continue
            if (not path.is_relative_to(project / 'input/pdk') or not path.is_file()
                    or any((project / part).is_symlink() for part in (Path(name), *Path(name).parents))):
                errors.append('DECLARED_MODEL_OR_DECK_UNAVAILABLE:' + name); continue
            manifest[name] = em.digest(path)
            tcl = path.suffix.lower() in ('.tcl', '.magicrc', '.rc') or path.name in ('magicrc', '.magicrc')
            for line in path.read_text(errors='replace').splitlines():
                comments = ('*', '#', ';') if tcl else ('*', '#', '//', ';')
                if not line.strip() or line.lstrip().startswith(comments):
                    continue
                line = _command_text(line, slash_comments=not tcl)
                child = None
                match = re.match(r"\s*\.(?:include|inc|lib)\s+[\"']?([^\s\"']+)", line, re.I)
                if match and (kind == 'model' or path.suffix.lower() in ('.sp', '.spice', '.lib', '.mod', '.scs', '.cir')):
                    child = match.group(1)
                    # One-word .lib SECTION defines a local model section.
                    if re.match(r'\s*\.lib\s+\w+\s*$', line, re.I) and not Path(child).suffix:
                        continue
                if child is None:
                    match = re.fullmatch(r"\s*(?:%?INCLUDE|source|require_relative|load)\s*\(?[\"']([^\"']+)[\"']\)?\s*;?\s*(?:#.*)?", line, re.I)
                    if not match:
                        match = re.fullmatch(r'\s*(?:%?INCLUDE|source)\s+([^\s;]+)\s*;?\s*(?:#.*)?', line, re.I)
                    child = match.group(1) if match else None
                if child is None:
                    # SPICE element/node identifiers are not directives. For
                    # executable config, inspect calls outside quoted data,
                    # including unresolved calls embedded in expressions.
                    if kind == 'model' and path.suffix.lower() in ('.sp', '.spice', '.lib', '.mod', '.cir'):
                        unresolved = re.match(r'(?i)\s*\.(?:include|inc|lib|source|load)\b', line)
                    else:
                        code = re.sub(r'''"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*' ''', '""', line, flags=re.X)
                        unresolved = (re.match(r'(?i)\s*(?:%?include|inc|source|load|require(?:_relative)?)\b', code)
                            or re.search(r'(?i)\b(?:include|inc|source|load|require(?:_relative)?)\s*(?=\(|["\']|[A-Za-z_$])', code)
                            or ('#{' in line and re.search(r'(?i)\b(?:load|source|require(?:_relative)?)\b', line)))
                    if unresolved:
                        errors.append('DECLARED_IMPORT_UNRESOLVED:' + name)
                    continue
                if any(token in child for token in ('$', '{', '*', '~', '[', ']', '(', ')', '+')):
                    errors.append('DECLARED_INCLUDE_UNRESOLVED:' + name); continue
                childpath = Path(child)
                pending.append(str(childpath if childpath.is_absolute() else path.parent / childpath))
        return manifest

    request['model_hashes'] = close([str(path) for path in models], 'model', missing)
    common_configs = close([facts[key] for key in ('magicrc', 'magic_tech', 'netgen_setup')
                            if isinstance(facts.get(key), str) and facts[key]], 'config', missing)
    a6_configs = dict(common_configs)
    for key in ('drc_deck', 'lvs_deck'):
        value = facts.get(key)
        if not isinstance(value, str) or not value:
            request['_step_missing']['A6'].append(key.upper() + '_UNAVAILABLE'); continue
        path = Path(value)
        path = path if path.is_absolute() else project / value
        try:
            request['pv_resolution'][key] = str(path.relative_to(project))
        except ValueError:
            request['_step_missing']['A6'].append('PROJECT_DECK_EXPORT_UNAVAILABLE:' + key)
        a6_configs.update(close([value], 'config', request['_step_missing']['A6']))
    request['_step_config_hashes'] = dict(A6=a6_configs, A7=common_configs, A8=common_configs)
    request['config_hashes'] = a6_configs
    request['_input_hashes'] = {**a6_configs, **request['model_hashes']}
    request['pdk_tree_sha256'] = em._hash(request['_input_hashes'])
    return request
