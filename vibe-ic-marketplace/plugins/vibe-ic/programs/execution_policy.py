"""Typed transport for the common production execution policy.

The policy is intentionally separate from the native implementation selector
(``direct``, ``librelane`` or ``dual``).  Front doors configure one request in
their live parent and pass the same typed values to children; children cannot
silently replace a parent request with shell text or a conflicting flag.
"""
from __future__ import annotations


# `programs/` is a flat directory whose modules import each other by bare name
# (vibe-ic#2104): restore the condition a by-path load does not provide.
import os as _os
import sys as _sys

if _os.path.dirname(_os.path.abspath(__file__)) not in _sys.path:
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import argparse
from contextlib import contextmanager
from dataclasses import dataclass, replace
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import stat
import struct
import sys
import tempfile
import threading
import time
import uuid

from execution_modes import Budget, Refusal, _verify_route_authority

ENV = 'VIBEIC_EXECUTION_REQUEST'
_CAPABILITY_FD_ENV = 'VIBEIC_EXECUTION_CAP_FD'
PROGRAM_DEFAULT = 'PROGRAM_DEFAULT'
USER_EXPLICIT_ULTRA = 'USER_EXPLICIT_ULTRA'
DEFAULT_MODE = 'default-mode'
ULTRA_MODE = 'ultra-mode'
_CANONICAL_FRONTDOOR = (Path(__file__).with_name('vibe_ic_one_shot_runner.py').resolve())
_BACKEND_MANIFEST_LOCK = threading.RLock()


@dataclass(frozen=True)
class _ProgramFirstFallbackHandoff:
    """Opaque, request-bound authority for one canonical producer scope."""

    site: str
    project: str
    request_digest: str


def _host_cpus() -> int:
    return len(os.sched_getaffinity(0)) if hasattr(os, 'sched_getaffinity') else (os.cpu_count() or 1)


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _process_start_ticks(pid: int) -> str:
    try:
        tail = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
        return tail[19]
    except (OSError, IndexError, ValueError) as exc:
        raise Refusal('REQUEST_CAPABILITY_INVALID', f'process {pid} has no start time') from exc


def _canonical_source_sha256() -> str:
    try:
        return hashlib.sha256(_CANONICAL_FRONTDOOR.read_bytes()).hexdigest()
    except OSError as exc:
        raise Refusal('ULTRA_ISSUER_NOT_ALLOWED', str(_CANONICAL_FRONTDOOR)) from exc


def _canonical_process_cmdline(pid: int) -> str:
    try:
        return Path(f'/proc/{pid}/cmdline').read_bytes().replace(b'\0', b' ').decode()
    except (OSError, UnicodeDecodeError) as exc:
        raise Refusal('REQUEST_CAPABILITY_INVALID', f'process {pid} command line unavailable') from exc


def _process_identity(pid: int) -> dict:
    """Read the live process object, including its exact script invocation.

    A substring in ``/proc/<pid>/cmdline`` is not an authority: an attacker can
    run ``python - <canonical-runner>`` and make that substring appear while
    executing code from stdin.  The capability is therefore bound to the
    executable object, the canonical script object, and the exact argv shape
    the front door uses (the script must be argv[1], never ``-`` or ``-c``).
    """
    try:
        executable = Path(os.readlink(f'/proc/{pid}/exe')).resolve()
        raw = b''
        for _ in range(10):
            raw = Path(f'/proc/{pid}/cmdline').read_bytes()
            if raw:
                break
            time.sleep(.01)
        argv = tuple(item.decode() for item in raw.split(b'\0') if item)
        if not argv:
            raise ValueError('empty command line')
        executable_sha = hashlib.sha256(executable.read_bytes()).hexdigest()
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise Refusal('REQUEST_CAPABILITY_INVALID', f'process {pid} identity unavailable') from exc
    # A canonical issuer must not be running with an import-injection path.
    # ``sitecustomize`` executes before the runner's first line and can answer
    # a socket challenge while presenting the runner's argv.  The live process
    # environment is therefore part of the process object and any injected
    # Python search path is refused before a capability handshake.
    try:
        environment = Path(f'/proc/{pid}/environ').read_bytes().split(b'\0')
        environment_names = tuple(sorted(
            item.split(b'=', 1)[0].decode(errors='ignore')
            for item in environment if b'=' in item))
    except (OSError, UnicodeDecodeError) as exc:
        raise Refusal('REQUEST_CAPABILITY_INVALID', f'process {pid} environment unavailable') from exc
    return dict(pid=pid, start_ticks=_process_start_ticks(pid),
                source_path=str(_CANONICAL_FRONTDOOR),
                source_sha256=_canonical_source_sha256(),
                executable_path=str(executable),
                executable_sha256=executable_sha,
                environment_names=list(environment_names),
                argv=list(argv),
                argv_sha256=hashlib.sha256(
                    json.dumps(list(argv), separators=(',', ':')).encode()).hexdigest())


def _default_payload() -> dict:
    payload = dict(schema=1, mode='default', mode_label=DEFAULT_MODE,
                   intent_label=PROGRAM_DEFAULT, ultra_match=False,
                   issuer='program-default')
    payload['request_digest'] = _digest(payload)
    return payload


def _verify_parent_capability(request_digest: str, receipt: dict) -> None:
    from execution_authority import consume
    issued = consume()['request']
    if issued != receipt or issued['request_digest'] != request_digest:
        raise Refusal('REQUEST_CAPABILITY_INVALID', 'request not issued by this live launcher')


def _load_parent_receipt(value: dict) -> dict:
    """Validate a parent-issued transport without trusting its labels."""
    digest = value.get('request_digest')
    receipt = value.get('request_receipt')
    path = value.get('request_receipt_path')
    if receipt is None and path:
        try:
            receipt = json.loads(Path(path).read_text())
        except (OSError, ValueError) as exc:
            raise Refusal('REQUEST_RECEIPT_INVALID', str(path)) from exc
    if (not isinstance(digest, str) or len(digest) != 64 or not isinstance(receipt, dict)
            or _digest({k: v for k, v in receipt.items() if k != 'request_digest'}) != digest
            or receipt.get('request_digest') != digest):
        raise Refusal('REQUEST_RECEIPT_INVALID', 'digest-bound parent receipt required')
    if path:
        receipt_path = Path(path)
        try:
            path_payload = json.loads(receipt_path.read_text())
            path_sha = hashlib.sha256(receipt_path.read_bytes()).hexdigest()
        except (OSError, ValueError) as exc:
            raise Refusal('REQUEST_RECEIPT_INVALID', str(receipt_path)) from exc
        if (not receipt_path.is_absolute() or receipt_path.is_symlink() or not receipt_path.is_file()
                or _digest(path_payload) != _digest(receipt)
                or value.get('request_receipt_sha256') != path_sha):
            raise Refusal('REQUEST_RECEIPT_INVALID', str(receipt_path))
    _verify_parent_capability(digest, receipt)
    return receipt


def request() -> dict:
    try:
        value = json.loads(os.environ[ENV]) if ENV in os.environ else {}
    except (TypeError, json.JSONDecodeError) as exc:
        raise Refusal('INVALID_EXECUTION_REQUEST', str(exc)) from exc
    if not isinstance(value, dict):
        raise Refusal('INVALID_EXECUTION_REQUEST', repr(value))
    if not value:
        if _CAPABILITY_FD_ENV in os.environ:
            from execution_authority import consume
            issued = consume()['request']
            value = dict(mode=issued['mode'], request_digest=issued['request_digest'], request_receipt=issued)
    if not value:
        payload = _default_payload()
        return dict(mode='default', mode_label=DEFAULT_MODE,
                    intent_label=PROGRAM_DEFAULT, ultra_match=False,
                    mode_intent='default', mode_explicit=False,
                    request_digest=payload['request_digest'], request_receipt=payload,
                    request_receipt_path=None, request_receipt_sha256=None,
                    cpus=min(4, _host_cpus()), ram_mb=4096,
                    workers=min(4, _host_cpus()), licenses={}, choice=None,
                    choice_wait_s=60, authority='PROGRAM_DEFAULT')
    selected = value.get('mode', 'default')
    if selected not in ('default', 'ultra'):
        raise Refusal('INVALID_EXECUTION_MODE', repr(selected))
    host = _host_cpus()
    cpus = value.get('cpus', min(4, host))
    ram = value.get('ram_mb', 4096)
    workers = value.get('workers', min(4, cpus) if isinstance(cpus, int) else 1)
    licenses = value.get('licenses', {})
    if (not isinstance(licenses, dict) or
            any(not isinstance(k, str) or not k or type(v) is not int or v < 0
                for k, v in licenses.items())):
        raise Refusal('INVALID_LICENSE_BUDGET', repr(licenses))
    Budget(cpus, ram, workers=workers, licenses=licenses)
    if cpus > host:
        raise Refusal('HOST_CPU_BUDGET_UNAVAILABLE', str(cpus))
    wait = value.get('choice_wait_s', 60)
    if type(wait) is not int or not 0 <= wait <= 3600:
        raise Refusal('INVALID_CHOICE_WAIT', repr(wait))
    choice = value.get('choice')
    if choice is not None and (not isinstance(choice, str) or not Path(choice).is_absolute()):
        raise Refusal('INVALID_CHOICE_PATH', repr(choice))
    if selected == 'ultra':
        receipt = _load_parent_receipt(value)
        if receipt.get('intent_label') != USER_EXPLICIT_ULTRA or not receipt.get('ultra_match'):
            raise Refusal('ULTRA_INTENT_MISSING', 'parent receipt is not explicit Ultra evidence')
        intent = USER_EXPLICIT_ULTRA
        authority = USER_EXPLICIT_ULTRA
        ultra_match = True
    else:
        if _CAPABILITY_FD_ENV in os.environ:
            receipt = _load_parent_receipt(value)
            if receipt.get('mode') != 'default' or receipt.get('intent_label') != PROGRAM_DEFAULT:
                raise Refusal('REQUEST_RECEIPT_INVALID', 'default intent relabelled')
        else:
            if (value.get('authority') not in (None, PROGRAM_DEFAULT) or
                    value.get('intent_label') not in (None, PROGRAM_DEFAULT) or
                    value.get('request_receipt_path')):
                raise Refusal('REQUEST_RECEIPT_INVALID', 'unbound default metadata')
            receipt = value.get('request_receipt') or _default_payload()
            if receipt != _default_payload() or value.get('request_digest', receipt['request_digest']) != receipt['request_digest']:
                raise Refusal('REQUEST_RECEIPT_INVALID', 'default transport relabelled')
        intent, authority, ultra_match = PROGRAM_DEFAULT, PROGRAM_DEFAULT, False
    return dict(mode=selected, mode_label=ULTRA_MODE if selected == 'ultra' else DEFAULT_MODE,
                mode_intent=selected, intent_label=intent, ultra_match=ultra_match,
                mode_explicit=intent == USER_EXPLICIT_ULTRA,
                request_digest=value.get('request_digest') or receipt.get('request_digest'),
                request_receipt=receipt, request_receipt_path=value.get('request_receipt_path'),
                request_receipt_sha256=value.get('request_receipt_sha256'),
                cpus=cpus, ram_mb=ram, workers=workers, licenses=dict(licenses),
                choice=choice, choice_wait_s=wait,
                authority=authority)


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument('--execution-mode', choices=('default', 'ultra'), default=None,
                        help='Production adapter policy; omitted means default.')
    parser.add_argument('--execution-cpus', type=int, default=None)
    parser.add_argument('--execution-ram-mb', type=int, default=None)
    parser.add_argument('--execution-workers', type=int, default=None)
    parser.add_argument('--execution-licenses', default=None,
                        help='JSON object of bounded license-seat counts.')
    parser.add_argument('--execution-choice', default=None,
                        help='Absolute JSON choice file for this live invocation.')
    parser.add_argument('--execution-choice-wait-s', type=int, default=None)
    parser.add_argument('--execution-request-digest', default=None, help=argparse.SUPPRESS)
    parser.add_argument('--execution-request-receipt', default=None, help=argparse.SUPPRESS)


def configure(args: argparse.Namespace, *, _issuer=None, _entry_capability=None) -> dict:
    """Normalize the live request and transport it to a child.

    ``vibe_ic_one_shot_runner`` is the only issuer. Its live private authority
    is an object identity held by that front door; child calls have no issuer
    argument and can only consume an inherited capability endpoint.
    """
    # A child may receive a custom environment from its parent, so reconstruct
    # only a digest-bound parent transport before parsing local flags.
    if ENV not in os.environ and _CAPABILITY_FD_ENV in os.environ:
        from execution_authority import consume
        issued = consume()['request']
        if issued['mode'] == 'ultra':
            os.environ[ENV] = json.dumps(dict(mode='ultra', request_digest=issued['request_digest'],
                                               request_receipt=issued))
    had_transport = ENV in os.environ
    parent_digest = getattr(args, 'execution_request_digest', None)
    parent_receipt = getattr(args, 'execution_request_receipt', None)
    local_policy_fields = ('execution_mode', 'execution_cpus', 'execution_ram_mb',
                           'execution_workers', 'execution_licenses',
                           'execution_choice', 'execution_choice_wait_s')
    local_non_mode = tuple(field for field in local_policy_fields
                           if field != 'execution_mode')
    if (ENV not in os.environ and not parent_digest and not parent_receipt and
            getattr(args, 'execution_mode', None) in (None, 'default') and
            not any(getattr(args, field, None) is not None for field in local_non_mode)):
        # Omitted policy is observationally inert: do not create an
        # environment activation that changes a canonical child's argv/env.
        return request()
    if ENV not in os.environ and (parent_digest or parent_receipt):
        had_transport = True
        if not parent_digest or not parent_receipt:
            raise Refusal('PARENT_REQUEST_MISSING', f"configure args.parent_request_digest={parent_digest!r}, args.parent_request_receipt={parent_receipt!r}: both are required together; no receipt file opened")
        receipt_path = Path(parent_receipt)
        if not receipt_path.is_absolute():
            raise Refusal('REQUEST_RECEIPT_INVALID', str(receipt_path))
        try:
            receipt_sha = hashlib.sha256(receipt_path.read_bytes()).hexdigest()
        except OSError as exc:
            raise Refusal('REQUEST_RECEIPT_INVALID', str(receipt_path)) from exc
        os.environ[ENV] = json.dumps(dict(mode=getattr(args, 'execution_mode', None) or 'ultra',
                                           request_digest=parent_digest,
                                           request_receipt_path=str(receipt_path),
                                           request_receipt_sha256=receipt_sha),
                                      sort_keys=True)
    value = request()
    inherited_mode = value.get('mode')
    for key, attr in (('mode', 'execution_mode'), ('cpus', 'execution_cpus'),
                      ('ram_mb', 'execution_ram_mb'), ('workers', 'execution_workers'),
                      ('choice', 'execution_choice'),
                      ('choice_wait_s', 'execution_choice_wait_s')):
        given = getattr(args, attr, None)
        if given is not None:
            value[key] = str(Path(given).resolve()) if key == 'choice' else given
    if getattr(args, 'execution_licenses', None) is not None:
        try:
            value['licenses'] = json.loads(args.execution_licenses)
        except (TypeError, json.JSONDecodeError) as exc:
            raise Refusal('INVALID_LICENSE_BUDGET', str(exc)) from exc
    requested = getattr(args, 'execution_mode', None)
    inherited = value.get('intent_label') == USER_EXPLICIT_ULTRA
    if requested == 'ultra' and not inherited:
        raise Refusal('ULTRA_ISSUER_NOT_ALLOWED', 'only the isolated canonical CLI issues Ultra')
    if requested == 'default' and inherited:
        raise Refusal('PARENT_REQUEST_CONFLICT', 'child cannot downgrade Ultra')
    os.environ[ENV] = json.dumps(value, sort_keys=True)
    # Reparse after normalization so all validation occurs on the actual child
    # transport, not merely on argparse's local values.
    value = request()
    os.environ[ENV] = json.dumps(value, sort_keys=True)
    return value


def require_explicit_ultra() -> dict:
    value = request()
    if value['mode'] == 'ultra' and value['authority'] != 'USER_EXPLICIT_ULTRA':
        raise Refusal('ULTRA_INTENT_MISSING', f"${ENV}: request.mode={value['mode']!r}, request.authority={value['authority']!r}; explicit --execution-mode ultra is required")
    return value


def controller_fields(*, ic_ip_path: str | None = None,
                      route_receipt: dict | None = None) -> dict:
    """Typed fields a production adapter passes into the existing Context.

    Production construction must resolve its IC/IP route at the adapter
    boundary.  Keeping a default here would silently turn an IP request into
    an IC run; neutral controller tests can continue constructing ``Context``
    directly with its compatibility default.
    """
    if ic_ip_path is None or not isinstance(route_receipt, dict) or not route_receipt:
        raise Refusal('PRODUCTION_ROUTE_REQUIRED', 'resolved ic_ip_path and route receipt are required')
    if ic_ip_path not in ('IC', 'IP'):
        raise Refusal('INVALID_IC_IP_PATH', repr(ic_ip_path))
    if (route_receipt.get('kind') != 'issued-route' or
            route_receipt.get('schema') != 1 or
            route_receipt.get('ic_ip_path') != ic_ip_path or
            any(key not in route_receipt for key in
                ('source_sha', 'project_digest', 'request_digest', 'route_digest'))):
        raise Refusal('IC_IP_ROUTE_MISMATCH', ic_ip_path)
    route_body = {k: v for k, v in route_receipt.items() if k != 'route_digest'}
    if (not isinstance(route_receipt.get('route_digest'), str) or
            _digest(route_body) != route_receipt['route_digest']):
        raise Refusal('ROUTE_RECEIPT_DIGEST_MISMATCH', ic_ip_path)
    _verify_route_authority(route_receipt)
    value = request()
    if (route_receipt.get('intent_label') != value['intent_label'] or
            route_receipt.get('mode_intent') != value['mode_intent'] or
            route_receipt.get('request_digest') != value['request_digest']):
        raise Refusal('ROUTE_INTENT_MISMATCH', ic_ip_path)
    return dict(ic_ip_path=ic_ip_path,
                route_receipt=dict(route_receipt or {}),
                intent_label=value['intent_label'],
                request_digest=value['request_digest'])


def child_arguments(argv: list[str], *, supports_execution_policy: bool = True) -> list[str]:
    """Append typed request values for children that declare the policy CLI.

    A legacy child that has not adopted the typed options receives its exact
    original argv.  Passing policy flags to such a parser would turn a valid
    explicit request into an argparse rc2 before the child can consume its
    inherited receipt.
    """
    if not supports_execution_policy:
        return list(argv)
    if ENV not in os.environ:
        return list(argv)
    value = request()
    result = list(argv)
    options = [('--execution-mode', value['mode']), ('--execution-cpus', value['cpus']),
               ('--execution-ram-mb', value['ram_mb']), ('--execution-workers', value['workers']),
               ('--execution-choice-wait-s', value['choice_wait_s'])]
    if value['choice']:
        options.append(('--execution-choice', value['choice']))
    if value.get('request_digest') and value.get('request_receipt_path'):
        options.extend((('--execution-request-digest', value['request_digest']),
                        ('--execution-request-receipt', value['request_receipt_path'])))
    if value['licenses']:
        options.append(('--execution-licenses', json.dumps(value['licenses'], sort_keys=True)))
    for flag, expected in options:
        existing = None
        for i, item in enumerate(result):
            if item == flag:
                existing = result[i + 1] if i + 1 < len(result) else ''
            elif item.startswith(flag + '='):
                existing = item.split('=', 1)[1]
        if existing is not None and existing != str(expected):
            raise Refusal('CHILD_EXECUTION_POLICY_CONFLICT', flag)
        if existing is None:
            result += [flag, str(expected)]
    return result


def child_pass_fds() -> tuple[int, ...]:
    """Return only the live parent capability FD for subprocess inheritance."""
    raw_fd = os.environ.get(_CAPABILITY_FD_ENV)
    if raw_fd is None:
        return ()
    try:
        fd = int(raw_fd)
        os.fstat(fd)
    except (OSError, TypeError, ValueError):
        raise Refusal('REQUEST_CAPABILITY_INVALID', raw_fd)
    return (fd,)

# One live runtime per ordinary runner process. Contexts stay fixed to their row;
# all rows reuse this Registry and Controller, never a second scheduler.
_ordinary_runtime = None


def _register_analog_adapters(registry, project: Path, source_sha: str,
                              parameters: dict) -> None:
    """Register analog rows only for a route that did not explicitly skip them."""
    # Absence by itself is not permission to classify an unknown design as
    # digital-only.  Only the canonical caller's explicit boolean may omit the
    # analog registrations; every other value follows the declaration-bound,
    # fail-closed registration path.
    if parameters.get('skip_analog') is True:
        return
    import execution_adapters_analog as analog
    analog.register_adapters(
        registry, project=project, request=parameters.get('analog_request'))
    import execution_adapters_analog_front as analog_front
    analog_front.register_front_adapters(
        registry, project=project, source_sha=source_sha)


def bootstrap(project: Path, *, parameters: dict | None = None,
              phase1_only: bool = False):
    global _ordinary_runtime
    value = request()
    # A local Default run needs only its project and mode. Its existing
    # producers write directly into that project and retain their own gates.
    # Candidate authority and Registry construction belong to Ultra.
    if value['mode'] == 'default' and _CAPABILITY_FD_ENV not in os.environ:
        project = Path(project).resolve(strict=True)
        _ordinary_runtime = dict(
            identity=(str(project), value['request_digest'], None, bool(phase1_only)),
            project=project, policy=value, route={},
            parameters=dict(parameters or {}), contexts={}, bindings={}, runs={},
            phase1_only=bool(phase1_only))
        return _ordinary_runtime
    from execution_authority import consume
    issued = consume()
    project = Path(project).resolve(strict=True)
    route = issued['route']
    if route['project'] != str(project):
        raise Refusal('ORDINARY_PROJECT_UNBOUND', str(project))
    identity = (str(project), value['request_digest'], route['source_sha'],
                bool(phase1_only))
    if _ordinary_runtime is not None:
        if _ordinary_runtime['identity'] != identity:
            raise Refusal('ORDINARY_RUNTIME_REENTRY', str(project))
        return _ordinary_runtime
    params = dict(parameters or {})

    # Default is a canonical-producer route.  Keep only the current issued
    # route metadata for disclosure and caller-owned handoffs; constructing a
    # Registry or Controller here would create the Ultra scheduler before the
    # canonical producer runs and would reintroduce policy-owned Step 9/15
    # side effects.  Ultra continues through the full adapter bootstrap below.
    if value['mode'] == 'default':
        _ordinary_runtime = dict(
            identity=identity, project=project, policy=value, route=route,
            parameters=params, contexts={}, bindings={}, runs={},
            phase1_only=bool(phase1_only))
        return _ordinary_runtime

    import execution_modes as em
    from execution_frontend_providers import register_factories
    from execution_adapters_backend import register_backend_adapters, BACKEND_PARAMETER_DEFAULTS
    from execution_adapters_release import register_release_adapters, RELEASE_PARAMETER_DEFAULTS
    from execution_source_snapshot import SourceSnapshot, using
    declaration_path = project / 'reports/phase1/tapeout_declaration.json'
    if declaration_path.is_file():
        declaration = json.loads(declaration_path.read_text())
    else:
        # Phase1 may not have emitted its report yet. The issued route already
        # binds the actual owner INPUT; use the existing attestation reader.
        from _tapeout_declaration import read_owner_delivery
        declaration, _ = read_owner_delivery(project, 'input/step_0_5ic_answers.json')
    snapshot = SourceSnapshot(em._REPO_ROOT, route['source_sha'])
    with using(snapshot):
        registry = em.Registry(snapshot=snapshot)
        # Phase 1 owns only the route/declaration producer. Its later products
        # cannot be prerequisites for entering that producer. Subsequent phase
        # processes build their complete registry after those products exist.
        register_factories(registry, project=project, parameters=params,
                           step_ids=('0.5ic',) if phase1_only else None)
        if not phase1_only:
            common = dict(source_sha=route['source_sha'], path=route['ic_ip_path'],
                          available=True, route_receipt=route, declaration=declaration)
            register_backend_adapters(registry, **common, execution_mode=value['mode'], parameters={
                k: v for k, v in params.items() if k in BACKEND_PARAMETER_DEFAULTS})
            register_release_adapters(registry, **common, parameters={
                k: v for k, v in params.items() if k in RELEASE_PARAMETER_DEFAULTS})
            # ``--skip-analog`` is the canonical front door's explicit routing
            # decision for a digital-only invocation.  Do not make that route
            # manufacture an empty Phase-1 declaration merely so the Ultra
            # Registry can be constructed.
            _register_analog_adapters(registry, project, route['source_sha'], params)
            from execution_adapters_mixed import register_mixed_adapters
            register_mixed_adapters(registry, source_sha=route['source_sha'],
                path=route['ic_ip_path'], project=project, parameters=params)
        controller = em.Controller(registry, Budget(value['cpus'], value['ram_mb'],
                             workers=value['workers'], licenses=value['licenses']))
    _ordinary_runtime = dict(identity=identity, project=project, policy=value,
        route=route, parameters=params, registry=registry, controller=controller,
        contexts={}, bindings={}, runs={}, phase1_only=bool(phase1_only))
    return _ordinary_runtime


def _fixed_inputs(runtime, step_id: str, *, parameters=None) -> dict:
    if str(step_id) == "9":
        from execution_production import current_step9_input_files
        issued = current_step9_input_files(runtime['project'])
        if issued is not None:
            return issued
    import _flow_yaml
    from step_required_inputs_check import expand
    root = runtime['project']
    by_id = {str(r['id']): r for r in _flow_yaml.load()['steps']}
    row = by_id.get(step_id)
    if row is None:
        raise Refusal('UNKNOWN_CANONICAL_STEP', step_id)
    declarations = list(row.get('required_inputs') or ())
    from execution_provider_catalog import BACKEND_IDS
    if str(step_id) in BACKEND_IDS:
        from execution_adapters_backend import backend_canonical_input_contract
        declarations = list(backend_canonical_input_contract(
            root, str(step_id), declarations,
            execution_mode=runtime.get('policy', {}).get('mode', 'ultra')))
    if step_id == '0.5ic' and runtime.get('policy', {}).get('mode', 'default') == 'default':
        import _submission_template as template_contract
        import submission_template_fetch as template_fetch
        import area_budget_basis_gen as area_basis
        # These are the original owner inputs. The ingest/declaration tree
        # is this row's mutable output, not an input to freeze before it runs.
        declarations.append(template_contract.DESIGN_ANSWERS_REL)
        declarations.extend(template_fetch._FAMILY_SEARCH_ROOTS)
        declarations.extend(rel for rel, _path, _text in area_basis.design_docs(root))
        # The producer's auto-PDK fallback may read a declared layer/config.
        # Bind that reader's selected file, not the entire generated-doc tree.
        import declared_pdk_is_the_pdk_used_check as pdk_declaration
        _target, source = pdk_declaration.declared_target(root)
        if source:
            rel = source.rsplit(':', 1)[0]
            declarations.extend(candidate for candidate in (rel, 'run/' + rel)
                                if (root / candidate).is_file())
        template = (parameters or {}).get('template')
        if template is None:
            try:
                own = json.loads((root / template_contract.DESIGN_ANSWERS_REL).read_text())
            except (OSError, ValueError):
                own = None  # The existing producer still refuses unreadable answers.
            operator = own.get('operator_template') if isinstance(own, dict) else None
            template = operator.get('path') if isinstance(operator, dict) else None
        if template:
            # An explicitly staged operator source is an input; the default
            # fetch destination is not invented as a pre-existing input.
            path = Path(template)
            unbound_reason = None
            try:
                source = path if path.is_absolute() else root / path
                source.resolve().relative_to(root.resolve())
                # Keep the contained lexical alias: its target may change
                # later, and current-input checks must reopen that same name.
                path = source.relative_to(root.resolve())
            except ValueError:
                unbound_reason = 'EXTERNAL_TEMPLATE_OUTSIDE_PROJECT'
            else:
                if '..' in path.parts:
                    # Preserve the existing external-source reason above;
                    # contained parent traversal still has unknown freshness.
                    unbound_reason = 'TEMPLATE_PARENT_COMPONENT_UNBOUND'
            if unbound_reason:
                # Preserve the existing producer route when its source cannot
                # be bound by the collector's safe project-local namespace.
                if parameters is not None:
                    parameters['resolved_input_manifest'] = {
                        'files': {}, 'declarations': declarations, 'missing': [],
                        'input_freshness': 'NOT_MEASURED',
                        'input_freshness_reason': unbound_reason,
                    }
                return {}
            declarations.append(str(path))
    else:
        declarations.extend(('input/step_0_5ic_answers.json', 'input/submission_template'))
        if step_id == '0.5ic':
            declarations.append('input/docs')
            if (parameters or {}).get('template'):
                declarations.append(parameters['template'])
    if str(step_id) == '19':
        import flow109
        try:
            selected = flow109.active_native_predecessor(root, '19')
        except flow109.Flow109Error as exc:
            raise Refusal(exc.code, exc.detail) from exc
        if selected is not None:
            old = {'from': 18, 'path': 'phase3/stage3/pnr/post_spare.def'}
            matches = [index for index, item in enumerate(declarations) if item == old]
            if len(matches) != 1:
                raise Refusal('FLOW109_NATIVE_PREDECESSOR_DECLARATION_INVALID', str(matches))
            declarations[matches[0]] = {
                'from': int(selected['native_step_id']), 'path': selected['output']}
    registry = runtime.get('registry')
    for arm in registry.adapters(step_id) if registry is not None else ():
        # String declarations are required by default.  A caller that intends
        # an optional edge must carry an explicit mapping with
        # ``required: false`` (or ``check: none``); do not erase absence by
        # rewriting the adapter's contract here.
        for item in arm.input_contract:
            declarations.append(item)
    # A conditional producer's output is not a mandatory input when the same
    # flow condition has been measured false and the producer left its exact
    # design-declared receipt.  Evaluate this before expanding producer edges;
    # unknown or malformed conditions remain mandatory.
    from execution_backend_worker import condition_aware_declarations
    declarations = condition_aware_declarations(root, declarations, by_id)
    # Backend adapters publish one current synthesis receipt namespace per
    # project.  Keep this dynamic set narrow; a static ``phase3/librelane``
    # directory declaration would snapshot stale outputs from unrelated rows
    # and could make the worker appear to consume its own prior result.
    if str(step_id) in BACKEND_IDS:
        from execution_adapters_backend import backend_project_input_contract
        for item in backend_project_input_contract(
                root, str(step_id), collect_missing=True,
                execution_mode=runtime.get('policy', {}).get('mode', 'ultra')):
            # These existing optional consumer edges keep their semantics.
            # The TB directory may be empty; its actual descendants are still
            # collected and hash-bound below, without requiring a dummy file.
            declarations.append(
                {'from': 'external', 'path': item, 'required': False}
                if isinstance(item, str) and item in {
                    'waivers.json', 'phase2/stage1/sim/tb'} else item)
    # Frontend adapters retain YAML mappings; native adapters declare paths.
    # Use the canonical expansion for upstream `outputs: all` and keep an
    # unchecked external declaration out of the filesystem search.
    patterns = []
    for entry in declarations:
        if isinstance(entry, dict):
            if entry.get('from') == 'external' and entry.get('check') == 'none':
                continue
            try:
                patterns.extend(spec for _, spec in expand(entry, by_id))
            except (KeyError, TypeError) as exc:
                raise Refusal('ORDINARY_INPUT_CONTRACT_INVALID', str(entry)) from exc
        elif isinstance(entry, str):
            patterns.append(entry)
        else:
            raise Refusal('ORDINARY_INPUT_CONTRACT_INVALID', repr(entry))
    inputs = {}
    for spec in patterns:
        if not isinstance(spec, str):
            raise Refusal('ORDINARY_INPUT_CONTRACT_INVALID', repr(spec))
        for pattern in str(spec).split(' OR '):
            pattern = pattern.strip()
            if not pattern or Path(pattern).is_absolute() or '..' in Path(pattern).parts:
                raise Refusal('ORDINARY_INPUT_PATH_UNSAFE', pattern)
            for match in root.glob(pattern):
                candidates = match.rglob('*') if match.is_dir() else (match,)
                for path in candidates:
                    if path.is_symlink() or not path.resolve().is_relative_to(root):
                        raise Refusal('ORDINARY_INPUT_PATH_UNSAFE', str(path))
                    if path.is_file():
                        inputs[str(path.relative_to(root))] = path
    # Keep the exact staged population and the declarations that produced it
    # together.  The worker receives this through its typed parameter envelope
    # so it cannot silently fall back to the row-only contract.
    from execution_backend_worker import resolve_input_contract
    # This issuer-side aggregate is a backend worker contract.  Frontend and
    # analog routes keep their established optional/search semantics here.
    if str(step_id) in BACKEND_IDS:
        import execution_backend_snapshot as _snapshot
        manifest_files = {
            name: _snapshot.sha(path) for name, path in sorted(inputs.items())
        }
        missing = resolve_input_contract(
            root, declarations, {'files': manifest_files, 'missing': []})
    else:
        missing = []
    if parameters is not None:
        import execution_backend_snapshot as _snapshot
        parameters['resolved_input_manifest'] = {
            'files': {name: _snapshot.sha(path)
                      for name, path in sorted(inputs.items())},
            'declarations': declarations,
            'missing': missing,
        }
    return inputs


def _manifest_for_explicit_inputs(runtime, step_id: str, parameters, supplied):
    """Bind an explicit population to the same issuer declarations as staging."""
    probe = dict(parameters or {})
    _fixed_inputs(runtime, step_id, parameters=probe)
    issued = probe.get('resolved_input_manifest')
    if not isinstance(issued, dict) or not isinstance(issued.get('declarations'), list):
        raise Refusal('ORDINARY_INPUT_MANIFEST_INVALID', str(step_id))
    root = runtime['project'].resolve()
    files = {}
    import execution_backend_snapshot as _snapshot
    for raw, source in dict(supplied or {}).items():
        rel = Path(raw) if isinstance(raw, str) else None
        path = Path(source) if isinstance(source, (str, Path)) else None
        if (rel is None or path is None or rel.is_absolute() or not raw or
                '..' in rel.parts or rel.as_posix() != raw):
            raise Refusal('ORDINARY_INPUT_PATH_UNSAFE', str(raw))
        try:
            resolved = path.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise Refusal('ORDINARY_INPUT_PATH_UNSAFE', str(raw)) from exc
        if (path.is_symlink() or not resolved.is_relative_to(root)
                or not path.is_file()):
            raise Refusal('ORDINARY_INPUT_PATH_UNSAFE', str(raw))
        files[raw] = _snapshot.sha(path)
    # Resolve against a temporary copy of the exact supplied population, not
    # the ambient project tree.  This keeps explicit dispatches on the same
    # complete declaration contract as ordinary fixed-input issuance.
    from execution_backend_worker import _resolve_input_contract
    with tempfile.TemporaryDirectory(prefix='vibeic-input-manifest-') as folder:
        staged = Path(folder)
        for raw, source in dict(supplied or {}).items():
            target = staged / raw
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.link(Path(source), target)
            except OSError:
                shutil.copyfile(Path(source), target)
        checked = _resolve_input_contract(
            staged, issued['declarations'], {'files': files})
    parameters['resolved_input_manifest'] = {
        'declarations': checked['declarations'],
        'files': files,
        'missing': checked['missing'],
    }
    return dict(supplied or {})


@contextmanager
def _backend_manifest_parameters(runtime, step_id: str, manifest):
    """Bind the current issuer manifest to this run's worker argv only.

    Adapter registration is immutable source authority.  A dispatch-specific
    manifest therefore gets a short-lived dataclass copy under a lock and is
    restored after Controller execution/adoption, preventing a later run from
    inheriting another project's input census.
    """
    if not manifest:
        yield
        return
    from execution_provider_catalog import BACKEND_IDS
    if str(step_id) not in BACKEND_IDS:
        yield
        return
    with _BACKEND_MANIFEST_LOCK:
        registry = runtime['registry']
        originals = {}
        try:
            for arm in registry.adapters(str(step_id)):
                component = arm.components[0] if len(arm.components) == 1 else None
                if component is None or '--params-json' not in component.argv:
                    continue
                index = component.argv.index('--params-json') + 1
                typed = json.loads(component.argv[index])
                typed['resolved_input_manifest'] = manifest
                argv = tuple(component.argv[:index] +
                             (json.dumps(typed, sort_keys=True),) +
                             component.argv[index + 1:])
                originals[arm.arm_id] = registry._adapters[arm.arm_id]
                rebound = replace(component, argv=argv)
                # Controller source admission rechecks the immutable
                # invocation-source snapshot against the live component argv.
                # A dispatch manifest changes only the JSON transport token,
                # so refresh that derived snapshot for the same short-lived
                # arm and restore it with the arm afterward.
                rebound_fields = {'components': (rebound,)}
                if hasattr(arm, 'invocation_sources'):
                    import execution_modes as _execution_modes
                    from types import MappingProxyType
                    invocations = dict(arm.invocation_sources)
                    invocations[component.name] = _execution_modes._invocation_sources(rebound)
                    rebound_fields['invocation_sources'] = MappingProxyType(invocations)
                registry._adapters[arm.arm_id] = replace(arm, **rebound_fields)
            yield
        finally:
            for arm_id, original in originals.items():
                registry._adapters[arm_id] = original


def _ensure_default_prelayout(runtime: dict, step_id: str) -> None:
    """Publish the existing pre-layout producer before a Default backend row.

    Step 15 consumes the Step-8 gate, so a stale or absent gate must be
    repaired at its existing pre-layout owner before the input manifest is
    issued.  This hook never synthesises or places a design; it only reuses
    ``_prelayout_librelane`` at the existing producer boundary.  Reuse and
    currentness remain the producer's ``run_chain`` contract.
    """
    if str(step_id) != "15" or runtime.get("policy", {}).get("mode") != "default":
        return
    params = runtime.get("parameters", {})
    project = Path(runtime["project"])
    top = params.get("top")
    pdk = params.get("pdk")
    container = params.get("container")
    if not top or pdk is None or not container:
        return
    import phase3_one_shot_runner as phase3
    netlist = phase3._pl.synth_dir(project) / f"{top}_synth.v"
    record_path = project / "phase2/stage2/constraints/asic_sdc.json"
    if not netlist.is_file() or not record_path.is_file():
        return
    try:
        record = json.loads(record_path.read_text())
    except (OSError, ValueError, TypeError) as exc:
        raise Refusal("PRELAYOUT_STEP7_RECORD_INVALID", str(exc)) from exc
    issued_sdc = record.get("path") if isinstance(record, dict) else None
    if not isinstance(issued_sdc, str):
        raise Refusal("PRELAYOUT_STEP7_RECORD_INVALID", "missing path")
    issued = Path(issued_sdc)
    if issued.is_absolute() or '..' in issued.parts:
        raise Refusal("PRELAYOUT_STEP7_RECORD_INVALID", issued_sdc)
    step7_sdc = project / issued
    if not step7_sdc.is_file() or step7_sdc.is_symlink():
        raise Refusal("PRELAYOUT_CURRENT_SDC_MISSING", issued_sdc)
    # Step 7's declaration is the binding/source proof.  The actual producer
    # consumes the PnR deck after its unit/DRV derivation; comparing the gate
    # to the raw ASIC declaration rejects valid measured runs.
    sdc = project / "phase3/stage3/pnr/constraint.sdc"
    if not sdc.is_file() or sdc.is_symlink():
        raise Refusal("PRELAYOUT_CURRENT_SDC_MISSING", str(sdc.relative_to(project)))
    gate = project / "phase3/librelane/prelayout/gates/step8_sdc_opensta.json"
    notes = []
    try:
        result = phase3._prelayout_librelane(
            project, str(top), pdk, sdc, False,
            {"7": "librelane", "8": "librelane", "10": "librelane"}, notes)
    except Exception as exc:
        raise Refusal("PRELAYOUT_PUBLICATION_FAILED", str(exc)) from exc
    if not isinstance(result, dict) or not isinstance(result.get("sdc"), dict):
        raise Refusal("PRELAYOUT_PUBLICATION_FAILED", "native producer returned no SDC result")
    native_folder = result.get("folder")
    if not isinstance(native_folder, (str, os.PathLike)):
        raise Refusal("PRELAYOUT_PUBLICATION_FAILED", "native producer returned no folder")
    import librelane_contract as _prelayout_ll
    native_receipt = Path(native_folder) / "vibeic_receipt.json"
    if (native_receipt.is_symlink() or not native_receipt.is_file() or
            not native_receipt.stat().st_size):
        raise Refusal("PRELAYOUT_PUBLICATION_FAILED", "native producer returned no receipt")
    native_receipt_sha256 = _prelayout_ll.digest(native_receipt)
    # This is the actual Default Step-15 consumer seam.  The native producer
    # must first be proven current by Step 8, then its three real corner views
    # are published for Step 10, and only after that does dispatch_fixed_step
    # take the Step-15 input census below.
    import design_one_shot_runner as design
    postcheck = design.step_sdc_validation_post_prelayout(
        project, str(top), native_result={"folder": str(native_folder),
                                          "receipt_sha256": native_receipt_sha256})
    if getattr(postcheck, "status", None) != "PASS":
        raise Refusal("PRELAYOUT_STEP8_POSTCHECK_FAILED", str(getattr(postcheck, "detail", postcheck)))
    try:
        phase3.publish_prelayout_reports(project, Path(native_folder),
                                         receipt_sha256=native_receipt_sha256)
    except Exception as exc:
        raise Refusal("PRELAYOUT_STEP10_PUBLICATION_FAILED", str(exc)) from exc
    try:
        published = json.loads(gate.read_text())
    except (OSError, ValueError, TypeError) as exc:
        raise Refusal("PRELAYOUT_GATE_NOT_PUBLISHED", str(exc)) from exc
    if (result["sdc"].get("verdict") != "PASS"
            or not isinstance(published, dict)
            or published.get("verdict") != "PASS"):
        raise Refusal("PRELAYOUT_GATE_IDENTITY_MISMATCH", str(gate))


def _choice_file_state(path: Path, *, snapshot: bool = False):
    """Capture a response version and content digest without following symlinks."""
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    except OSError as exc:
        if snapshot:
            return ('UNREADABLE', exc.errno)
        raise Refusal('AI_CHOICE_FILE_UNREADABLE', f'{path}: {exc}') from exc
    base = (info.st_dev, info.st_ino, info.st_mode, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns)
    if not stat.S_ISREG(info.st_mode):
        return base + (None,)
    if info.st_size > 1024 * 1024:
        return base + ('TOO_LARGE',)
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0)
    try:
        fd = os.open(path, flags)
        with os.fdopen(fd, 'rb') as stream:
            before = os.fstat(stream.fileno())
            payload = stream.read(1024 * 1024 + 1)
            after = os.fstat(stream.fileno())
        current = path.lstat()
    except OSError as exc:
        if snapshot:
            return ('UNREADABLE', exc.errno)
        raise Refusal('AI_CHOICE_FILE_UNREADABLE', f'{path}: {exc}') from exc
    stable = lambda item: (item.st_dev, item.st_ino, item.st_mode, item.st_size,
                           item.st_mtime_ns, item.st_ctime_ns)
    if stable(before) != stable(after) or stable(after) != stable(current):
        return ('CHANGING',) + stable(current)
    if len(payload) > 1024 * 1024:
        return base + ('TOO_LARGE',)
    return base + (hashlib.sha256(payload).hexdigest(),)


def _read_new_choice(path: Path, baseline):
    """Read only a stable response whose state changed since the step began."""
    state = _choice_file_state(path)
    if state is None or state == baseline or (state and state[0] == 'CHANGING'):
        return None
    if state and state[0] == 'UNREADABLE':
        raise Refusal('AI_CHOICE_FILE_UNREADABLE', str(path))
    if len(state) > 6 and state[-1] == 'TOO_LARGE':
        raise Refusal('AI_CHOICE_TOO_LARGE', str(path))
    if not stat.S_ISREG(state[2]):
        raise Refusal('AI_CHOICE_NOT_REGULAR', str(path))
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
        with os.fdopen(fd, 'rb') as stream:
            before = os.fstat(stream.fileno())
            payload = stream.read(1024 * 1024 + 1)
            after = os.fstat(stream.fileno())
        current = path.lstat()
    except OSError as exc:
        raise Refusal('AI_CHOICE_FILE_UNREADABLE', f'{path}: {exc}') from exc
    stable = lambda item: (item.st_dev, item.st_ino, item.st_mode, item.st_size,
                           item.st_mtime_ns, item.st_ctime_ns)
    if (stable(before) != stable(after) or stable(after) != stable(current) or
            len(payload) > 1024 * 1024 or
            hashlib.sha256(payload).hexdigest() != state[-1]):
        return None
    try:
        return json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Refusal('INVALID_AI_CHOICE', f'{path}: {exc}') from exc


def _selection_request(context, run: Path, result: dict, response: Path) -> dict:
    """Publish current Core receipts for an external AI; never choose an arm."""
    import execution_modes as em
    comparison_path = run / 'comparison.json'
    try:
        comparison = json.loads(comparison_path.read_text())
    except (OSError, ValueError) as exc:
        raise Refusal('AI_SELECTION_COMPARISON_UNAVAILABLE', str(comparison_path)) from exc
    comparison_sha = em.digest(comparison_path)
    if comparison_sha != result.get('comparison_digest'):
        raise Refusal('AI_SELECTION_COMPARISON_STALE', str(comparison_path))
    binding = context.binding()
    if comparison.get('step_id') != context.step_id:
        raise Refusal('AI_SELECTION_STEP_MISMATCH', context.step_id)
    eligible = comparison.get('eligible_arms')
    rows = comparison.get('arm_receipts')
    if not isinstance(eligible, list) or not eligible or not isinstance(rows, list):
        raise Refusal('AI_SELECTION_ELIGIBILITY_UNAVAILABLE', context.step_id)
    arms = []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get('arm_id'), str):
            raise Refusal('AI_SELECTION_RECEIPT_INVALID', context.step_id)
        item = dict(row, receipt_path=str((run / row['arm_id'] / 'receipt.json').resolve()))
        expected = row.get('receipt_sha256')
        receipt_path = Path(item['receipt_path'])
        if expected is not None and (not receipt_path.is_file() or em.digest(receipt_path) != expected):
            raise Refusal('AI_SELECTION_RECEIPT_STALE', row['arm_id'])
        arms.append(item)
    by_id = {arm['arm_id']: arm for arm in arms}
    if any(not isinstance(row, dict) or row.get('arm_id') not in by_id or
           by_id[row['arm_id']].get('status') != 'ELIGIBLE' or
           by_id[row['arm_id']].get('receipt_sha256') != row.get('receipt_sha256')
           for row in eligible):
        raise Refusal('AI_SELECTION_ELIGIBILITY_INVALID', context.step_id)
    request_path = run / 'selection-request.json'
    request = dict(schema='vibe-ic/ai-selection-request/1', step_id=context.step_id,
                   run_id=result.get('run_id'), binding=binding,
                   comparison_digest=comparison_sha,
                   frozen_work_digest=comparison.get('frozen_work_digest'),
                   required_choice_fields=['run_id', 'comparison_digest', 'frozen_work_digest',
                                           'arm_id', 'receipt_sha256', 'binding',
                                           'reviewer', 'rationale'],
                   request_path=str(request_path.resolve()), response_path=str(response.resolve()),
                   eligible_arms=[dict(arm_id=row['arm_id'],
                                       receipt_sha256=row['receipt_sha256'],
                                       receipt_path=by_id[row['arm_id']]['receipt_path'])
                                  for row in eligible],
                   arm_receipts=arms)
    encoded = json.dumps(request, sort_keys=True, indent=2) + '\n'
    if request_path.exists():
        if request_path.read_text() != encoded:
            raise Refusal('AI_SELECTION_REQUEST_CHANGED', str(request_path))
    else:
        fd = os.open(request_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
    event = dict(type='vibeic.ai_selection_request', request_path=str(request_path.resolve()),
                 response_path=str(response.resolve()), step_id=context.step_id,
                 binding=binding, eligible_arms=request['eligible_arms'], arm_receipts=arms)
    print(json.dumps(event, sort_keys=True), flush=True)
    return request


def _wait_for_choice(context, run: Path, result: dict, response: Path,
                     baseline, timeout_s: int):
    request = _selection_request(context, run, result, response)
    from _watchdog import loop_guard
    deadline = time.monotonic() + timeout_s
    # This wait admits an external response; it does not kill a running job.
    # Retain its deadline and bound polling even when the clock stops advancing.
    max_polls = max(1, int(timeout_s / 0.25) + 2)
    for _ in loop_guard('ai_selection_choice', max_iter=max_polls):
        choice = _read_new_choice(response, baseline)
        if choice is not None:
            # BLOCKING: the external reviewer must acknowledge the complete
            # current comparison, including candidates it did not select.
            # Selected-arm binding alone cannot attest what the AI reviewed.
            if not isinstance(choice, dict) or any(
                    not isinstance(choice.get(field), str) or
                    not request.get(field) or choice[field] != request[field]
                    for field in ('run_id', 'comparison_digest', 'frozen_work_digest')):
                raise Refusal('AI_COMPARISON_UNBOUND', context.step_id)
            return choice
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        time.sleep(min(0.25, remaining))
    return None


def _prepare_step9(runtime: dict, parameters: dict) -> None:
    """Bind current producer outputs before the fixed Controller creates a plan."""
    import execution_modes as em
    import execution_production as production
    project = runtime['project']
    if (type(runtime['controller']) is not em.Controller or
            runtime['controller'].registry is not runtime['registry']):
        raise em.Refusal('PRODUCTION_CHILD_SCOPE_UNBOUND', 'ordinary live Controller required')
    params = dict(runtime['parameters'], **parameters)
    # A bootstrap resolver refusal cannot be erased by a later caller value.
    if runtime['parameters'].get('pdk_refusal'):
        params['pdk_refusal'] = runtime['parameters']['pdk_refusal']
    identity = {key: params.get(key) for key in ('top', 'container', 'period_relax',
                                                'declaration', 'pdk_refusal')}
    identity['pdk'] = production._pdk_dict(params.get('pdk'))
    if 'step9_dispatch_parameters' in runtime:
        # Selection polls omit producer parameters; preserve the first dispatch
        # values while refusing any explicitly changed value.
        for key in identity:
            if key not in parameters:
                identity[key] = runtime['step9_dispatch_parameters'][key]
        if identity != runtime['step9_dispatch_parameters']:
            raise em.Refusal('STEP9_DISPATCH_PARAMETERS_CHANGED', '9')
        production.current_step9_input_files(project)
        return
    if '9' in runtime['contexts'] or '9' in runtime['runs']:
        raise em.Refusal('STEP9_BINDING_CLOSED', '9')
    runtime['registry'].bind_step9(project=project, parameters=params)
    runtime['step9_dispatch_parameters'] = identity


def _publish_dispatch_result(run: Path, result: dict) -> None:
    """Advance a pending current report after its real consumer succeeds.

    This report grants no adoption authority. Preserve its exact earlier
    bytes through the existing copy-aside writer; measured terminal reports
    and later refusal records keep their existing ownership.
    """
    path = run / 'result.json'
    if json.loads(path.read_text()).get('status') != 'AWAITING_AI_SELECTION':
        return
    from _auditor_write import copy_aside
    import execution_modes as em
    tag = time.strftime('%Y%m%dT%H%M%SZ', time.gmtime()) + '-' + str(time.time_ns())
    copy_aside(path, path.with_name('result.superseded-' + tag + '.json'))
    em._write(path, result)


def dispatch_fixed_step(project: Path, step_id: str, *, inputs=None,
                        parameters=None, choice=None) -> dict | None:
    """Dispatch one caller-selected canonical row; gates/adoption remain Core's.

    BLOCKING: a pending AI choice or unmeasured/failed result cannot publish
    canonical output bytes. Default returns before any provider construction.
    """
    import execution_modes as em
    explicit_choice = choice is not None
    if _ordinary_runtime is None:
        return None
    runtime = _ordinary_runtime
    if Path(project).resolve() != runtime['project']:
        raise Refusal('ORDINARY_PROJECT_UNBOUND', str(project))

    # Default is a single program-first route.  Its producer is the caller's
    # canonical function, so this policy seam must not construct a Controller
    # context, run a frontend worker, wait for a choice, adopt an arm, or run
    # producer preparation.  Ultra remains below this branch and keeps the
    # multi-arm selection lifecycle unchanged.
    if runtime.get('policy', {}).get('mode') == 'default':
        if choice is not None:
            raise Refusal('DEFAULT_SELECTION_NOT_ALLOWED', str(step_id))
        return None

    if step_id == '9':
        _prepare_step9(runtime, dict(parameters or {}))
    controller = runtime['controller']
    adapters = runtime['registry'].adapters(step_id)
    if not adapters:
        return dict(status='NOT_MEASURED', reason=('STEP9_REPLAY_PENDING' if step_id == '9'
                    else 'NO_REGISTERED_PROVIDER'), step_id=step_id, selected=None)
    applicable = [a for a in adapters if a.applicability != 'inapplicable']
    if not applicable:
        return dict(status='NOT_APPLICABLE', reason='DECLARED_ROUTE_INAPPLICABLE',
                    step_id=step_id, selected=None)
    row = next(r for r in controller.portfolio['steps'] if r['id'] == step_id)
    response_value = runtime['policy'].get('choice')
    response_path = Path(response_value) if isinstance(response_value, str) else None
    baselines = runtime.setdefault('choice_baselines', {})
    if step_id not in runtime['contexts'] and response_path is not None:
        if not response_path.is_absolute():
            raise Refusal('INVALID_CHOICE_PATH', str(response_path))
        # Snapshot before Controller.run: the manager publishes only after
        # seeing this step's current request.
        baselines[step_id] = _choice_file_state(response_path, snapshot=True)
    parameters = dict(parameters or {})
    from execution_provider_catalog import BACKEND_IDS
    is_backend = str(step_id) in BACKEND_IDS
    if inputs is not None:
        files = (_manifest_for_explicit_inputs(runtime, step_id, parameters, inputs)
                 if is_backend else dict(inputs))
    elif step_id == '0.5ic':
        files = _fixed_inputs(runtime, step_id)
    else:
        _ensure_default_prelayout(runtime, str(step_id))
        # Preserve the historical two-argument seam for every non-backend
        # provider; only backend dispatch receives the issuer manifest.
        files = (_fixed_inputs(runtime, step_id, parameters=parameters)
                 if is_backend else _fixed_inputs(runtime, step_id))
    # Ultra still records a controller run when the fixed row has no current
    # inputs.  The resulting receipt is the evidence of NOT_MEASURED and keeps
    # the row re-entry/adoption contract intact; Default has already returned
    # above and never reaches this controller path.
    manifest = parameters.get('resolved_input_manifest')
    # An explicit backend population is authoritative.  If the issuer could
    # not bind every required input, stop before constructing a Controller
    # context or invoking a worker.  Ambient files in the project tree must
    # not silently fill an omitted/zero-byte explicit input.
    if (inputs is not None and is_backend and isinstance(manifest, dict)
            and manifest.get('missing')):
        missing = sorted({str(item) for item in manifest['missing']})
        return {
            'status': 'NOT_MEASURED',
            'reason': 'ORDINARY_INPUT_ABSENT',
            'step_id': step_id,
            'selected': None,
            'missing_inputs': missing,
            'resolved_input_manifest': manifest,
        }
    frontend = all(a.tool_id == 'frontend-worker' for a in applicable)
    objective = (dict(parameters or {}) if step_id == '0.5ic' else
                 dict(runtime['parameters'], **dict(parameters or {}))) if frontend else dict(applicable[0].objective)
    if frontend:
        objective.setdefault('metric', 'source_boundary')
        if objective['metric'] == 'source_boundary':
            objective.setdefault('direction', 'max')
    from execution_backend_gates import canonical_family_row, required_programs
    canonical = canonical_family_row(step_id, adapters=adapters)
    required = (required_programs(canonical) if canonical is not None
                else tuple(row['mandatory_gate_programs']))
    context = em.Context(step_id, runtime['route']['source_sha'], files, objective,
        required, project_digest=runtime['route']['project_digest'],
        **controller_fields(ic_ip_path=runtime['route']['ic_ip_path'], route_receipt=runtime['route']))
    analog_prepared = None
    if step_id in ('A6', 'A7', 'A8'):
        import execution_adapters_analog as analog
        analog_prepared = analog.prepare(context, project=runtime['project'],
            registry=runtime['registry'], controller=controller)
    with _backend_manifest_parameters(runtime, step_id, manifest):
        if step_id in runtime['contexts']:
            if context.binding() != runtime['bindings'][step_id]:
                raise Refusal('FIXED_STEP_REENTRY_CHANGED', step_id)
            context = runtime['contexts'][step_id]
            run, result = runtime['runs'][step_id]
        else:
            run = runtime['project'] / 'reports/execution' / runtime['policy']['request_receipt']['invocation_id'] / step_id
            mode_label = runtime['policy'].get('mode_label')
            if mode_label is None:
                mode_label = ('ultra-mode' if runtime['policy'].get('mode') == 'ultra'
                              else 'default-mode')
            result = controller.run(context, run, mode_label)
            runtime['contexts'][step_id] = context
            runtime['bindings'][step_id] = context.binding()
            runtime['runs'][step_id] = (run, result)
    # Selection remains in Core. A configured path is read only after the
    # current fixed step has produced an awaiting Ultra result.
    if result.get('status') == 'AWAITING_AI_SELECTION' and choice is None:
        policy_value = runtime['policy']
        if (policy_value.get('mode') == 'ultra' and response_path is not None and
                type(policy_value.get('choice_wait_s')) is int and
                policy_value['choice_wait_s'] > 0):
            choice = _wait_for_choice(context, run, result, response_path,
                                      baselines.get(step_id), policy_value['choice_wait_s'])
    if choice is not None and (explicit_choice or result.get('status') == 'AWAITING_AI_SELECTION') and result.get('status') != 'ADOPTED':
        result = controller.adopt(context, run, choice)
    elif choice is not None and result.get('status') == 'ADOPTED' and choice != result.get('ai_choice'):
        raise Refusal('FIXED_STEP_SELECTION_CHANGED', step_id)
    if analog_prepared is not None:
        consumed = analog.consume(runtime['project'], analog_prepared, controller, run, result)
        reported = dict(consumed, execution_result=result)
        if result.get('status') == 'ADOPTED' and consumed.get('status') == 'PASS':
            _publish_dispatch_result(run, reported)
        return reported
    if result.get('status') == 'ADOPTED':
        if step_id == '9':
            # Step 9's immutable generation carries its arm-local outputs
            # below ``project/``.  Its existing product importer strips that
            # envelope before publishing into the ordinary project's current
            # phase2/phase3 paths and re-verifies the adoption around the
            # write.  Sending those names through the generic Journal below
            # instead creates ``<project>/project/...``: the Controller has
            # adopted real bytes, but the normal consumer cannot see them.
            from execution_production import import_selected
            imported = import_selected(runtime['project'], context, controller,
                                       run, result)
            result = dict(result, consumer=imported)
            runtime['runs'][step_id] = (run, result)
            reported = dict(result, step_id=step_id, run_root=str(run))
            _publish_dispatch_result(run, reported)
            return reported
        result = controller.verify_adoption(context, run)
        from execution_backend_snapshot import Journal
        generation = result['selected_generation']
        journal = Journal(runtime['project'])
        try:
            for name, expected in generation['outputs'].items():
                source = Path(generation['directory']) / name
                if em.digest(source) != expected:
                    raise Refusal('SELECTED_ARTIFACT_CHANGED', name)
                # Component envelopes are evidence, not canonical project inputs.
                if name not in ('backend_result.json', 'release-evidence.json'):
                    journal.write(name, source.read_bytes())
            controller.verify_adoption(context, run)
        except Exception:
            journal.rollback()
            raise
    runtime['runs'][step_id] = (run, result)
    reported = dict(result, step_id=step_id, run_root=str(run))
    if result.get('status') == 'ADOPTED':
        _publish_dispatch_result(run, reported)
    return reported


def dispatch_ordinary_site(project, runner: str, site: str, refusal_factory):
    if _ordinary_runtime is None:
        return None
    import step_preflight
    plan = step_preflight.RUNNER_PLANS.get(runner)
    span = dict(plan.sites).get(site, ()) if plan else ()
    runtime = _ordinary_runtime
    # Step 7's Default producer is the canonical program in
    # design_one_shot_runner.step_asic_sdc.  The frontend-worker row is a
    # source-bound qualification arm for Ultra; dispatching it first in
    # Default makes a measured-but-unadoptable qualification receipt look like
    # the producer result and strands the canonical emitter behind it.
    if (runner == 'design_one_shot_runner' and site == 'asic_sdc'
            and runtime.get('policy', {}).get('mode') == 'default'):
        return None
    if (runtime.get('phase1_only') is True and runtime['policy']['mode'] == 'default'
            and runner == 'phase1_one_shot_runner' and site == 'doc_extract'
            and span == ('D1',)):
        if _CAPABILITY_FD_ENV not in os.environ and not runtime['route']:
            if Path(project).resolve() != runtime['project']:
                raise Refusal('ORDINARY_PROJECT_UNBOUND', str(project))
            runtime['canonical_phase1_producer'] = dict(
                runner=runner, site=site, step_id='D1', mode='default',
                execution='single-local-driver',
                controller_qualification='NOT_MEASURED')
            return None
        # This exact Default site keeps its established producer and expert
        # handoff. It does not assert a qualified D1 Controller adapter.
        from execution_authority import consume
        issued = consume()
        if Path(project).resolve() != runtime['project']:
            raise Refusal('ORDINARY_PROJECT_UNBOUND', str(project))
        if (issued['request']['mode'] != 'default'
                or issued['request'] != runtime['policy']['request_receipt']
                or issued['route'] != runtime['route']
                or runtime['identity'] != (str(runtime['project']),
                    issued['request']['request_digest'], issued['route']['source_sha'], True)):
            raise Refusal('REQUEST_CAPABILITY_INVALID', 'canonical Phase1 route changed')
        runtime['canonical_phase1_producer'] = dict(
            runner=runner, site=site, step_id='D1', mode='default',
            source_sha=issued['route']['source_sha'],
            request_digest=issued['request']['request_digest'],
            route_digest=issued['route']['route_digest'],
            controller_qualification='NOT_MEASURED')
        return None

    # Every ordinary Default site is owned by the caller's canonical producer
    # function.  Returning here prevents the generic row dispatcher from
    # turning a source-bound worker receipt into the step's producer evidence.
    # The caller still executes its normal function and its own typed gates.
    if runtime.get('policy', {}).get('mode') == 'default':
        return None

    result = dispatch_ordinary_rows(project, span, site, refusal_factory)
    # These sites have real program-first producers in the Phase-2 runner.
    # Their ordinary Default frontend rows are source-bound qualification arms;
    # an explicit NOT_MEASURED placeholder must release control back to
    # step_preflight.gate so the caller can run the canonical producer.  Keep
    # Ultra and measured failures on the Controller path: only Default's
    # unmeasured placeholders are eligible for this fallback.
    _placeholder = False
    _rows = (getattr(result, 'extras', {}) or {}).get('execution_results', ())
    if isinstance(_rows, (list, tuple)) and len(_rows) == 1:
        _row = _rows[0]
        _allowed_reasons = {'NO_RUNNABLE_ADAPTER', 'NO_REGISTERED_PROVIDER'}
        if site == 'yosys_synth':
            _allowed_reasons.add('STEP9_REPLAY_PENDING')
        _placeholder = (
            isinstance(_row, dict)
            and _row.get('status') == 'NOT_MEASURED'
            and _row.get('reason') in _allowed_reasons)
    if (site in ('asic_sdc', 'yosys_synth')
            and runtime.get('policy', {}).get('mode') == 'default'
            and getattr(result, 'status', None) == 'NOT_MEASURED'
            and _placeholder):
        # Keep the fallback decision attached to this invocation.  Step 9's
        # canonical producer is reached after this ordinary placeholder is
        # released; it must not call the fixed Controller a second time with
        # producer parameters that were absent from the placeholder dispatch.
        # Step 7 already has an explicit producer bypass.  Step 9 reaches its
        # producer through phase3.step_synth, so that function consumes this
        # one-shot marker.  Ultra and measured failures never set it.
        request_digest = _request_digest(runtime)
        if request_digest is None:
            return result
        runtime.setdefault('program_first_fallback_sites', set()).add(
            (site, str(Path(project).resolve()), request_digest))
        return None
    return result


def _request_digest(runtime: dict) -> str | None:
    policy = runtime.get('policy') or {}
    receipt = policy.get('request_receipt')
    value = receipt.get('request_digest') if isinstance(receipt, dict) else None
    if not isinstance(value, str) or not value:
        value = policy.get('request_digest')
    return value if isinstance(value, str) and value else None


def consume_program_first_fallback(
        project: Path, site: str) -> _ProgramFirstFallbackHandoff | None:
    """Consume one scoped Default producer fallback token.

    The ordinary placeholder is allowed to release only its own bound project
    and request, and only once. The producer passes the opaque handoff down its
    whole synthesis scope, including an area retry, so a later call cannot
    inherit a stale bypass or skip Controller input/freshness checks.
    """
    runtime = _ordinary_runtime
    if runtime is None or runtime.get('policy', {}).get('mode') != 'default':
        return None
    bound = runtime.get('project')
    request_digest = _request_digest(runtime)
    if request_digest is None:
        return None
    try:
        current = Path(project).resolve()
        if bound is None or current != Path(bound).resolve():
            return None
    except (OSError, RuntimeError, TypeError, ValueError):
        return None
    markers = runtime.get('program_first_fallback_sites')
    token = (site, str(current), request_digest)
    if not isinstance(markers, set) or token not in markers:
        return None
    markers.remove(token)
    handoff = _ProgramFirstFallbackHandoff(site, str(current), request_digest)
    runtime.setdefault('_active_program_first_fallback_handoffs', set()).add(handoff)
    return handoff


def is_program_first_fallback_handoff(
        handoff: object, project: Path, site: str) -> bool:
    """Validate an active opaque handoff without accepting forged booleans."""
    runtime = _ordinary_runtime
    if runtime is None or runtime.get('policy', {}).get('mode') != 'default':
        return False
    active = runtime.get('_active_program_first_fallback_handoffs')
    if not isinstance(active, set) or handoff not in active:
        return False
    if not isinstance(handoff, _ProgramFirstFallbackHandoff):
        return False
    request_digest = _request_digest(runtime)
    if request_digest is None:
        return False
    try:
        return (handoff.site == site
                and handoff.project == str(Path(project).resolve())
                and handoff.project == str(Path(runtime['project']).resolve())
                and handoff.request_digest == request_digest)
    except (KeyError, OSError, RuntimeError, TypeError, ValueError):
        return False


def release_program_first_fallback(handoff: object) -> None:
    runtime = _ordinary_runtime
    if runtime is None:
        return
    active = runtime.get('_active_program_first_fallback_handoffs')
    if isinstance(active, set):
        active.discard(handoff)


def phase1_producer_disclosure(project: Path) -> dict | None:
    """Report an actual canonical-site selection, never Controller evidence."""
    runtime = _ordinary_runtime
    if runtime is None or Path(project).resolve() != runtime['project']:
        return None
    selected = runtime.get('canonical_phase1_producer')
    return dict(selected) if selected is not None else None


def dispatch_ordinary_rows(project, step_ids, site, result_factory):
    if _ordinary_runtime is None:
        return None
    # See dispatch_fixed_step: Default has one caller-owned producer per row.
    # This guard also covers Phase-3 window and direct row helpers that call
    # dispatch_ordinary_rows without first passing through dispatch_ordinary_site.
    if _ordinary_runtime.get('policy', {}).get('mode') == 'default':
        return None
    results = []
    for step_id in step_ids:
        result = dispatch_fixed_step(project, str(step_id))
        results.append(result)
        if result['status'] not in ('ADOPTED', 'NOT_APPLICABLE'):
            break
    if not results:
        return None
    status = ('FAIL' if any(r['status'] == 'FAIL' or 'FAIL' in r.get('candidate_statuses', {}).values() for r in results)
              else 'PASS' if all(r['status'] in ('ADOPTED', 'NOT_APPLICABLE') for r in results)
              else 'NOT_MEASURED')
    row = result_factory('Ultra fixed-row provider dispatch', {'execution_results': results})
    # Some ordinary sites return a single runner row, while the Phase-2 DFT
    # chain deliberately returns a one-element list so its caller can use
    # ``plan.extend``.  Keep that site contract: mutating ``.status`` on the
    # container itself turns a real DFT run into ``AttributeError: list has no
    # attribute status`` after its producers have already run.
    if isinstance(row, (list, tuple)):
        for item in row:
            item.status = status
        return row
    row.status = status
    return row
