"""Bounded execution-policy controller and common receipt chain.

This module has no built-in EDA executors or second production scheduler. Legacy
direct/librelane/dual switches remain owned by librelane_contract. Adapters
are trusted source-owned code, not executable commands imported from the public
portfolio. An adapter must validate its actual outputs and every required gate.
The controller binds that evidence to the inputs, implementation and process.

Production adapters register with the existing ``Registry`` and execute only
through ``Controller``.  Each run issues the frozen-work, arm, comparison and
program-adoption receipts below; the receipts add provenance to the controller
without changing canonical DAG ownership or selecting a step.
"""
from __future__ import annotations

# `programs/` is a flat directory whose modules import each other by bare name
# (vibe-ic#2104): restore the condition a by-path load does not provide.
import os as _os
import sys as _sys

if _os.path.dirname(_os.path.abspath(__file__)) not in _sys.path:
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from _execution_manifest import (ISSUED_MANIFEST_ENV, issued_manifest_path,
                                 is_exclusive_regular)

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field, replace
import ctypes
import hashlib
import hmac
import inspect
import ast
import json
import math
import fnmatch
import multiprocessing
import os
from pathlib import Path
import re
import secrets
import shutil
import signal
import subprocess
import threading
import time
from typing import Callable, Iterable, Mapping
from types import MappingProxyType
import uuid
from functools import lru_cache, wraps

import os as _os                                                    # noqa: E402
import sys as _sys                                                  # noqa: E402

if _os.path.dirname(_os.path.abspath(__file__)) not in _sys.path:
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))

from _atomic_artefact import write_bytes, write_json
from execution_source_snapshot import SourceSnapshot, active as _active_source_snapshot


def required_gate_satisfied(step_id, gate, verdict):
    """Honor the template checker's documented exit-zero applicability case.

    NOT_APPLICABLE remains visible in evidence. No physical gate or other
    step can use it to satisfy an obligation. Execution and input authority
    are still verified separately before eligibility and adoption.
    """
    return verdict == 'PASS' or (
        step_id == '0.5ic' and gate == 'submission_template_check' and
        verdict == 'NOT_APPLICABLE')


# The issuer is owned by this live controller process, never a caller-supplied
# digest or a secret serialized beside editable run receipts. A new interpreter
# cannot adopt a previous issuer's run: durable external supervision is not wired.
# A live invocation reference, installed only in the Controller's forked
# frontend child. No file, environment variable or new certificate grants it.
_ISSUED_FRONTEND_CHILD = None
# Load the small Linux syscall binding before a fork inherits a bounded
# address space. Late dlopen can fail when the parent has large mappings.
_FRONTEND_LIBC = ctypes.CDLL(None, use_errno=True)
def _make_authority_ledger():
    """Read-only public index; enrollment stays in supervisor call closures.

    This is an in-process API boundary, not isolation against arbitrary Python
    reflection or replacement of trusted controller code. Workers receive only
    serialized facts, never the live enrollment capability.
    """
    entries: dict[str, str] = {}
    lock = threading.Lock()
    signing_key = secrets.token_bytes(32)

    class AuthorityLedger:
        __slots__ = ()

        def __setitem__(self, path: str, payload: str) -> None:
            code = 'ISSUED_AUTHORITY_REWRITE' if path in entries else 'ISSUED_AUTHORITY_UNAVAILABLE'
            raise Refusal(code, path)

        def __getitem__(self, path: str) -> str:
            return entries[path]

        def get(self, path: str, default=None):
            return entries.get(path, default)

    def supervised(method):
        def invoke(self, *args, **kwargs):
            if '_issue' in kwargs:
                raise Refusal('ISSUED_AUTHORITY_UNAVAILABLE', 'caller supplied enrollment')

            def issue(path, payload):
                path = str(path)
                with lock:
                    if payload is None:
                        entries.pop(path, None)
                        return
                    if path in entries and entries[path] != payload:
                        raise Refusal('ISSUED_AUTHORITY_REWRITE', path)
                    entries[path] = payload
                    body = json.loads(payload)
                    return dict(payload=body, signature=hmac.new(
                        signing_key, _hash(body).encode(), hashlib.sha256).hexdigest())

            return method(self, *args, **kwargs, _issue=issue)
        return invoke

    def consume(path):
        document = json.loads(Path(path).read_text())
        observed = entries.get(str(path))
        if observed is None:
            raise Refusal('ISSUED_AUTHORITY_UNAVAILABLE', str(path))
        expected = hmac.new(signing_key, _hash(document['payload']).encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, document.get('signature', '')):
            raise Refusal('ISSUED_AUTHORITY_INVALID', str(path))
        if json.loads(observed) != document['payload']:
            raise Refusal('ISSUED_AUTHORITY_CHANGED', str(path))
        return document['payload']

    return AuthorityLedger(), supervised, consume


_component_index, _supervised, _consume_provisional = _make_authority_ledger()
def _record_authority(path: Path | str, payload: str,
                      ledger=_component_index) -> None:
    """Compatibility boundary: callers cannot enroll first issuance."""
    ledger[str(path)] = payload


def _authority_payload(path: Path | str, default=None,
                       ledger=_component_index):
    return ledger.get(str(path), default)


_CONTROL_NAMES = frozenset({'.', '..', 'plan.json', 'result.json', 'adoption.json',
                            'refusal.json', 'issued-plan.json', 'selected'})


def _sealed_authority_store():
    key = secrets.token_bytes(32)
    ledger = {}

    def issue(path: Path, payload: dict) -> dict:
        document = json.loads(json.dumps(payload))
        prior = ledger.get(str(path))
        if prior is not None and prior != document:
            raise Refusal('ISSUED_AUTHORITY_REISSUE', str(path))
        ledger[str(path)] = document
        signature = hmac.new(key, _hash(document).encode(), hashlib.sha256).hexdigest()
        return dict(payload=document, signature=signature)

    def consume(path: Path) -> dict:
        document = json.loads(path.read_text())
        issued = ledger.get(str(path))
        if issued is not None and issued != document.get('payload'):
            if document.get('signature') == _hash(document.get('payload')):
                raise Refusal('ISSUED_AUTHORITY_INVALID', str(path))
            raise Refusal('ISSUED_AUTHORITY_CHANGED', str(path))
        expected = hmac.new(key, _hash(document['payload']).encode(), hashlib.sha256).hexdigest()
        if (not isinstance(document.get('signature'), str) or
                not hmac.compare_digest(expected, document['signature']) or
                issued != document['payload']):
            raise Refusal('ISSUED_AUTHORITY_INVALID', str(path))
        return document['payload']

    return issue, consume


del _component_index

_issue_sealed, _consume_sealed = _sealed_authority_store()


class Refusal(RuntimeError):
    def __init__(self, code: str, detail: str):
        self.code = code
        super().__init__(f'{code}: {detail}')


def mode(value: str | None = None) -> str:
    if value is None:
        return 'default-mode'
    if value not in ('default-mode', 'ultra-mode'):
        raise Refusal('INVALID_EXECUTION_MODE', repr(value))
    return value


def digest(path: Path) -> str:
    snapshot = _active_source_snapshot()
    if snapshot is not None:
        return snapshot.digest(path)
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def _hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True,
                                     separators=(',', ':')).encode()).hexdigest()


_REPO_ROOT = Path(__file__).resolve().parents[4]


def _git_source_authority(source_sha: str) -> tuple[str, str]:
    """Resolve a source commit and tree from the clean repository object DB."""
    if not isinstance(source_sha, str) or not re.fullmatch(r'[0-9a-f]{40}', source_sha):
        raise Refusal('INVALID_SOURCE_SHA', str(source_sha))
    try:
        commit = subprocess.run(
            ['git', '-C', str(_REPO_ROOT), 'rev-parse', '--verify', f'{source_sha}^{{commit}}'],
            check=True, capture_output=True, text=True, timeout=5).stdout.strip()
        tree = subprocess.run(
            ['git', '-C', str(_REPO_ROOT), 'rev-parse', '--verify', f'{source_sha}^{{tree}}'],
            check=True, capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        raise Refusal('SOURCE_AUTHORITY_UNAVAILABLE', source_sha) from exc
    return commit, tree


@lru_cache(maxsize=4096)
def _git_blob_at_commit(source_sha: str, relative: str) -> str:
    """Return a tracked blob only from the verified source commit.

    A caller-editable portfolio and a caller-rehashed working file cannot
    authenticate one another.  The source commit must itself contain the
    canonical object that is currently being consumed.
    """
    if (not isinstance(relative, str) or not relative or relative.startswith('/') or
            '..' in Path(relative).parts):
        raise Refusal('SOURCE_AUTHORITY_UNAVAILABLE', relative)
    try:
        return subprocess.run(
            ['git', '-C', str(_REPO_ROOT), 'rev-parse', '--verify',
             f'{source_sha}:{relative}'],
            check=True, capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        raise Refusal('SOURCE_AUTHORITY_UNAVAILABLE', f'{source_sha}:{relative}') from exc


def _verified_current_source_commit(source_sha: str) -> str:
    """Require the source commit to contain this checkout's canonical flow.

    A well-formed commit id is only an object reference.  Binding it to the
    current canonical YAML prevents a caller from placing an unrelated
    historical or fabricated source id around an otherwise valid fixture.
    """
    snapshot = _active_source_snapshot()
    if snapshot is not None:
        if source_sha != snapshot.source_sha:
            raise Refusal('SOURCE_AUTHORITY_STALE', source_sha)
        return snapshot.commit
    commit, _ = _git_source_authority(source_sha)
    canonical = _canonical_flow_path()
    relative = str(canonical.relative_to(_REPO_ROOT))
    try:
        current_blob = subprocess.run(
            ['git', '-C', str(_REPO_ROOT), 'hash-object', str(canonical)],
            check=True, capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        raise Refusal('SOURCE_AUTHORITY_UNAVAILABLE', relative) from exc
    if _git_blob_at_commit(commit, relative) != current_blob:
        raise Refusal('SOURCE_AUTHORITY_STALE', source_sha)
    return commit


def _canonical_flow_path() -> Path:
    return _REPO_ROOT / 'vibe-ic-marketplace/plugins/vibe-ic/flow/phase1_phase2_phase3.yaml'


def _blob_bytes(path: Path) -> str:
    snapshot = _active_source_snapshot()
    content = snapshot.read_bytes(path) if snapshot is not None else path.read_bytes()
    return hashlib.sha1(b'blob ' + str(len(content)).encode() + b'\0' + content).hexdigest()


def _tracked_clean_file(path: Path) -> None:
    if path.is_symlink():
        raise Refusal('SOURCE_AUTHORITY_UNAVAILABLE', str(path))
    path = path.resolve()
    try:
        snapshot = _active_source_snapshot()
        if snapshot is not None:
            try:
                snapshot.verify_tracked(path)
            except RuntimeError as exc:
                code = str(exc).split(':', 1)[0]
                raise Refusal(code if code.startswith('SOURCE_AUTHORITY_') else
                              'SOURCE_AUTHORITY_UNAVAILABLE', str(path)) from exc
            return
        relative = str(path.relative_to(_REPO_ROOT))
        head = subprocess.check_output(['git', '-C', str(_REPO_ROOT), 'rev-parse', 'HEAD'], text=True).strip()
        expected = _git_blob_at_commit(head, relative)
        if _blob_bytes(path) != expected:
            raise Refusal('SOURCE_AUTHORITY_DIRTY', str(path))
    except (OSError, ValueError) as exc:
        raise Refusal('SOURCE_AUTHORITY_UNAVAILABLE', str(path)) from exc


def _git_source_blobs(commit: str, paths) -> dict[str, str]:
    """Read one immutable commit population; rehash working bytes separately.

    No source result is cached. This batches the same Git object reads used
    by per-file registration while preserving exact path/blob authority.
    """
    paths = tuple(sorted(Path(path) for path in paths))
    if not paths:
        return {}
    snapshot = _active_source_snapshot()
    if snapshot is not None:
        try:
            return snapshot.git_blobs(commit, paths)
        except (OSError, ValueError, RuntimeError) as exc:
            raise Refusal('SOURCE_AUTHORITY_UNAVAILABLE', 'source population') from exc
    try:
        relative = [str(path.relative_to(_REPO_ROOT)) for path in paths]
        result = subprocess.run(['git', '-C', str(_REPO_ROOT), 'ls-tree', '-r', '-z',
                                 commit, '--', *relative], check=True,
                                capture_output=True, timeout=10)
        blobs = {}
        for row in result.stdout.split(b'\0'):
            if not row:
                continue
            header, name = row.split(b'\t', 1)
            mode, kind, blob = header.decode().split()
            if kind == 'blob' and mode in ('100644', '100755'):
                blobs[name.decode()] = blob
        if any(name not in blobs for name in relative):
            raise Refusal('SOURCE_AUTHORITY_UNAVAILABLE', 'untracked source')
        return {str(path): blobs[name] for path, name in zip(paths, relative)}
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        raise Refusal('SOURCE_AUTHORITY_UNAVAILABLE', 'source population') from exc


def _canonical_flow_authority(flow_path: Path) -> str:
    if flow_path.resolve() != _canonical_flow_path().resolve():
        raise Refusal('PORTFOLIO_CANONICAL_UNAVAILABLE', str(flow_path))
    try:
        _tracked_clean_file(flow_path)
    except Refusal as exc:
        raise Refusal('PORTFOLIO_CANONICAL_UNTRUSTED', str(flow_path)) from exc
    return digest(flow_path)


@lru_cache(maxsize=2048)
def _python_import_requests(content: str) -> tuple:
    # Cache syntax by exact bytes; all path resolution and source authority
    # checks remain live, including an import becoming local after first use.
    from execution_source_snapshot import python_import_syntax
    requests = []
    for kind, level, module, names, _optional in python_import_syntax(content):
        if kind == 'import':
            requests.extend((0, name) for name in names)
        elif kind == 'from':
            requests.append((level, module))
            requests.extend((level, '.'.join(filter(None, (module, name))))
                            for name in names if name != '*')
    return tuple(requests)


def _local_python_imports(path: Path) -> set[Path]:
    """Resolve imports live, or provisionally within a verified snapshot."""
    snapshot = _active_source_snapshot()
    path = Path(path).absolute()
    cache_key = ('execution-modes-local-imports', str(path))
    if snapshot is not None:
        cached = snapshot.value_get(cache_key)
        if cached is not None:
            snapshot.stats['local_import_hits'] += 1
            return set(cached)
        snapshot.stats['local_import_misses'] += 1
    try:
        requests = _python_import_requests(snapshot.read_text(path) if snapshot else path.read_text())
    except (OSError, SyntaxError):
        return set()
    result = set()
    programs = Path(__file__).resolve().parent
    for level, name in requests:
        roots = [path.parent]
        if level:
            roots = [path.parent.joinpath(*(['..'] * (level - 1))).resolve()]
        else:
            roots += [programs, programs.parent]
        for root in roots:
            parts = name.split('.') if name else []
            candidate = root.joinpath(*parts)
            module = candidate.with_suffix('.py') if parts else candidate / '__init__.py'
            package = candidate / '__init__.py'
            if snapshot is not None:
                probes = [snapshot.import_candidate(p) for p in (module, package)]
                if any(state[1] for state in probes):
                    raise Refusal('ENTRY_SOURCE_UNBOUND', str(candidate))
                found = {state[3] for state in probes if state[2]}
            else:
                if any(p.is_symlink() for p in (module, package)):
                    raise Refusal('ENTRY_SOURCE_UNBOUND', str(candidate))
                found = {p.resolve() for p in (module, package) if p.is_file()}
            if found:
                result.update(found)
                for i in range(1, len(parts)):
                    init = root.joinpath(*parts[:i], '__init__.py')
                    if snapshot is not None:
                        state = snapshot.import_candidate(init)
                        if state[2]:
                            result.add(state[3])
                    elif init.is_file():
                        result.add(init.resolve())
                break
    if snapshot is not None:
        snapshot.value_put(cache_key, frozenset(result))
    return result


def _source_closure(paths: Mapping[str, str] | Iterable[str]) -> set[Path]:
    snapshot = _active_source_snapshot()
    if isinstance(paths, Mapping):
        key = ('execution-modes-mapping', tuple(sorted(
            (str(Path(path).resolve()), digest) for path, digest in paths.items())))
    else:
        key = ('execution-modes-paths', tuple(sorted(
            str(Path(path).resolve()) for path in paths)))
    if snapshot is not None:
        cached = snapshot.closure_get(key)
        if cached is not None:
            for path in cached:
                snapshot.read_bytes(path)
            return cached
    closure = set()
    pending = [Path(path).resolve() for path in paths if str(path).endswith('.py')]
    while pending:
        path = pending.pop()
        if path in closure:
            continue
        closure.add(path)
        pending.extend(_local_python_imports(path) - closure)
    if snapshot is not None:
        for path in closure:
            snapshot.read_bytes(path)
        snapshot.closure_put(key, closure)
    return closure


def _source_method(context_type: type, source: Path, method: str) -> Callable:
    """Require the method object itself to match its current tracked source."""
    _tracked_clean_file(source)
    compiled = compile(source.read_bytes(), str(source), 'exec', dont_inherit=True)
    def nested(code, name):
        return next(c for c in code.co_consts if inspect.iscode(c) and c.co_name == name)
    try:
        expected = nested(nested(compiled, context_type.__name__), method)
        actual = getattr(context_type, method)
        if actual.__code__ != expected:
            raise ValueError('method source identity changed')
    except (StopIteration, AttributeError, ValueError) as exc:
        raise Refusal('CONTEXT_IMPLEMENTATION_UNTRUSTED', context_type.__name__) from exc
    return actual


def _python_entry(arguments: tuple[str, ...], *,
                  allowed_options: str = "bBdEiIOPqsSuvxWX") -> tuple[str, list[str], int]:
    """Resolve the script using Python option semantics, never file existence.

    Only a bounded script invocation is supported. Unknown options, module,
    inline, stdin and exit-only invocations have no admitted entry here.
    Option values remain reproduction inputs, not implementation entries.
    """
    values = []
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if argument == '--':
            index += 1
            break
        if not argument.startswith('-'):
            break
        if argument == '--check-hash-based-pycs':
            index += 1
            if index >= len(arguments) or arguments[index] not in ('always', 'default', 'never'):
                raise Refusal('ENTRY_SOURCE_UNBOUND', 'invalid Python option value')
            values.append(arguments[index])
        else:
            options = argument[1:]
            if not options or argument.startswith('--'):
                raise Refusal('ENTRY_SOURCE_UNBOUND', argument)
            for offset, option in enumerate(options):
                if option not in allowed_options:
                    raise Refusal('ENTRY_SOURCE_UNBOUND', argument)
                if option in 'WX':
                    value = options[offset + 1:]
                    if not value:
                        index += 1
                        if index >= len(arguments):
                            raise Refusal('ENTRY_SOURCE_UNBOUND', argument)
                        value = arguments[index]
                    values.append(value)
                    break
                if option not in 'bBdEiIOPqsSuvx':
                    raise Refusal('ENTRY_SOURCE_UNBOUND', argument)
        index += 1
    if index >= len(arguments) or arguments[index] == '-':
        raise Refusal('ENTRY_SOURCE_UNBOUND', 'Python script entry required')
    return arguments[index], values, index


def _invocation_sources(component: Component) -> dict:
    """Bind executable, entry and every static file argument before execution.

    Extra argv files are reproduction inputs, not new independent engines.
    Interpreter code from stdin, inline code or an unresolved module is refused.
    """
    if not component.argv:
        raise Refusal('INVALID_COMPONENT', component.name)
    binary = shutil.which(component.argv[0])
    if not binary:
        raise Refusal('EXECUTABLE_UNBOUND', component.argv[0])
    executable = Path(binary).resolve()
    if not executable.is_relative_to(_REPO_ROOT) and executable != Path(_sys.executable).resolve():
        raise Refusal('EXECUTABLE_SOURCE_UNBOUND', str(executable))
    option_values = []
    entry_index = None
    if executable == Path(_sys.executable).resolve():
        if _sys.implementation.name != 'cpython':
            raise Refusal('ENTRY_SOURCE_UNBOUND', 'unsupported interpreter semantics')
        entry_argument, option_values, entry_index = _python_entry(component.argv[1:])
        entry_path = Path(entry_argument)
        if entry_path.is_absolute():
            if not entry_path.is_file():
                raise Refusal('ENTRY_SOURCE_UNBOUND', entry_argument)
            # Resolve aliases to the actual source whose bytes and complete
            # closure are bound.  A retargeted alias changes this identity and
            # the execution-time closure check refuses it.
            entry = entry_path.resolve()
        else:
            # Relative Python entries have an exact meaning only in the arm's
            # issued output cwd.  Registration records the argv unchanged;
            # plan/execution resolve and bind the entry against that cwd.
            entry = None
    elif executable.name.lower().startswith(('python', 'pypy')) or executable.name in ('sh', 'bash', 'dash'):
        raise Refusal('ENTRY_SOURCE_UNBOUND', 'unsupported interpreter semantics')
    else:
        entry = executable
    files = ([entry] if entry_index is not None and entry is not None else [])
    arguments = [
        argument for index, argument in enumerate(component.argv[1:])
        if index != entry_index
    ]
    arguments.extend(option_values)
    for argument in arguments:
        if '{inputs}' in argument or '{outputs}' in argument:
            continue
        value = argument.split('=', 1)[1] if argument.startswith('-') and '=' in argument else argument
        path = Path(value)
        # Relative argv names are resolved by the issued child inside its
        # frozen input/output tree.  Looking them up against the Controller's
        # ambient cwd makes registration depend on whether an unrelated
        # project file happens to exist there.  Relative Python entries are
        # separately resolved against the exact issued execution cwd; only
        # absolute static data arguments belong to this registration census.
        if not path.is_absolute():
            continue
        try:
            regular = path.is_file()
        except OSError as exc:
            # A data argument can exceed the filesystem component limit.
            # Absolute paths and every other filesystem error still refuse.
            if exc.errno == 36 and not path.is_absolute():
                continue
            raise Refusal('ENTRY_SOURCE_UNBOUND', value) from exc
        if regular:
            if path.is_symlink():
                raise Refusal('ENTRY_SOURCE_UNBOUND', value)
            files.append(path.resolve())
    implementation = ({} if entry is None else
                      (_source_closure({str(entry): digest(entry)})
                       if entry.suffix == '.py' else {entry}))
    arguments = set(files)
    closure = arguments | _source_closure({str(p): digest(p) for p in arguments})
    return dict(executable=str(executable), executable_sha256=digest(executable),
                argv=list(component.argv),
                entry=(entry_argument if entry is None else str(entry)),
                implementation={str(p): digest(p) for p in sorted(implementation)},
                argument_sources={str(p): digest(p) for p in sorted(closure)})


def _route_pointer(receipt: Mapping[str, object]) -> str:
    return _hash({key: receipt.get(key) for key in (
        'ic_ip_path', 'source_sha', 'project_digest', 'request_digest',
        'intent_label', 'mode_intent')})


def _canonical_issuer_consumer():
    """Bind the public issuer implementation and a private transport consumer.

    BLOCKING: module slots are locators, never authority. The private consumer
    executes the tracked verifier and requires the isolated launcher's live
    transport on every call, including planning and adoption.
    """
    import execution_authority as module
    from types import FunctionType, ModuleType
    source = Path(__file__).with_name('execution_authority.py').resolve()
    namespace = dict(__file__=str(source), __name__='_canonical_execution_issuer')
    content = source.read_bytes()
    exec(compile(content, str(source), 'exec', dont_inherit=True), namespace)
    functions = {name: value for name, value in namespace.items()
                 if type(value) is FunctionType and value.__globals__ is namespace}
    originals = {name: vars(module).get(name) for name in functions}
    constants = {name: namespace[name] for name in ('HERE', 'ROOT', 'FD_ENV', 'SOCKET_ENV')}
    consume = functions['consume']

    def require():
        _tracked_clean_file(source)
        if (source.read_bytes() != content or type(module) is not ModuleType or
                _sys.modules.get('execution_authority') is not module or
                vars(module).get('__file__') != str(source) or
                any(vars(module).get(name) != value for name, value in constants.items())):
            raise Refusal('ISSUER_IMPLEMENTATION_UNTRUSTED', str(source))
        for name, expected in functions.items():
            actual = vars(module).get(name)
            if (actual is not originals[name] or type(actual) is not FunctionType or
                    actual.__globals__ is not vars(module) or
                    actual.__code__ != expected.__code__ or
                    actual.__defaults__ != expected.__defaults__ or
                    actual.__kwdefaults__ != expected.__kwdefaults__ or actual.__closure__):
                raise Refusal('ISSUER_IMPLEMENTATION_UNTRUSTED', name)
        return consume()

    def bind(consumer):
        @wraps(consumer)
        def bound(*args, **kwargs):
            # Each authority boundary retains the verifier in its own closure.
            # There is no mutable module-level consumer slot to look up, and
            # a caller cannot supply this keyword as authority.
            kwargs['_issuer'] = require
            return consumer(*args, **kwargs)
        return bound

    return bind


_bind_canonical_issuer = _canonical_issuer_consumer()


@_bind_canonical_issuer
def _verify_route_authority(receipt: Mapping[str, object], *, _issuer) -> None:
    try:
        issued = _issuer()['route']
    except Refusal as exc:
        raise Refusal('ROUTE_AUTHORITY_UNAVAILABLE', str(exc)) from exc
    if dict(receipt) != issued:
        raise Refusal('ROUTE_AUTHORITY_UNAVAILABLE', 'not the current live issued route')
def _issued_manifest_payload(context: 'Context') -> dict:
    """Return the complete worker manifest from immutable controller input."""
    binding = context.binding()
    return {'step_id': context.step_id,
            'parameters': dict(context.objective),
            'files': dict(binding['inputs'])}


def _issued_manifest_bytes(payload: dict) -> bytes:
    return (json.dumps(payload, sort_keys=True) + '\n').encode()


def _issued_manifest_digest(payload: dict) -> str:
    return hashlib.sha256(_issued_manifest_bytes(payload)).hexdigest()


def _provider_identity(adapter: 'Adapter', *, cwd: Path | None = None,
                       include_execution: bool = False) -> tuple:
    """Identity of proven execution, with all executed local source bytes bound.

    Replay argv remains unchanged. Interpreter flags cannot invent another
    producer, and an opaque wrapper has no identity usable for deduplication.
    The complete execution closure is resolved afresh before launch/adoption.
    """
    from execution_provider_catalog import (source_closure, implementation_closure,
        proven_dispatcher_closure, python_entrypoint, _python_search, RELEASE_IDS, BACKEND_IDS)
    roots, executed, search_paths, closure = [], set(), [], set()
    observed = {}

    def bound_digest(path):
        if path not in observed:
            observed[path] = digest(path)
        return observed[path]
    family = ('execution_release_worker.py' if adapter.step_id in RELEASE_IDS else
              'execution_backend_worker.py' if adapter.step_id in BACKEND_IDS else None)
    worker = Path(__file__).resolve().parent / family if family else None
    for component in adapter.components:
        executable = Path(shutil.which(component.argv[0]) or component.argv[0]).resolve()
        files = [executable]
        interpreter = Path(_sys.executable).resolve()
        python = executable.name.startswith('python') or bound_digest(executable) == bound_digest(interpreter)
        if python and bound_digest(executable) != bound_digest(interpreter):
            raise Refusal('PROVIDER_DEPENDENCY_UNBOUND', 'unsupported Python interpreter layout')
        try:
            if python and len(component.argv) > 1 and component.argv[1] == '-c':
                # Source-owned inline controls bind their literal code and every
                # resolved helper. Inline canonical dispatch remains unsupported.
                if worker is not None or len(component.argv) < 3 or cwd is None:
                    raise ValueError('inline Python needs execution cwd and a supported producer')
                code = component.argv[2]
                tree = ast.parse(code)
                search = _python_search(cwd / '__inline__.py', cwd)
                search_paths.append([str(p) for p in search])
                component_closure = implementation_closure(cwd / '__inline__.py', cwd=cwd,
                    search=search, source_text=code)
                for node in ast.walk(tree):
                    if not isinstance(node, ast.Call):
                        continue
                    name = getattr(node.func, 'id', None) or getattr(node.func, 'attr', None)
                    if name in {'exec', 'eval', '__import__', 'import_module', 'run_module'}:
                        raise ValueError('unsupported dynamic inline Python dependency')
                    if name == 'run_path':
                        # A bounded runpy launcher may execute its first issued
                        # argv member after removing the inline-code sentinel.
                        statements = [ast.unparse(n) for n in tree.body]
                        prefix = ['import runpy, sys', 'sys.argv = sys.argv[1:]',
                                  "runpy.run_path(sys.argv[0], run_name='__main__')"]
                        final_exit = (len(tree.body) == 4 and
                            isinstance(tree.body[-1], ast.Expr) and
                            isinstance(tree.body[-1].value, ast.Call) and
                            ast.unparse(tree.body[-1].value.func) == 'sys.exit' and
                            len(tree.body[-1].value.args) == 1 and
                            isinstance(tree.body[-1].value.args[0], ast.Constant) and
                            type(tree.body[-1].value.args[0].value) is int and
                            not tree.body[-1].value.keywords)
                        if (statements[:3] != prefix or
                            (len(statements) != 3 and not final_exit) or
                            len(component.argv) < 4):
                            raise ValueError('unsupported inline runpy entrypoint')
                        target = Path(component.argv[3])
                        target = (target if target.is_absolute() else cwd / target).resolve()
                        component_closure.update(implementation_closure(target, cwd=cwd, search=search))
                component_closure.add(executable)
                files = [executable, 'python-inline:' + _hash(code)]
                closure.update(component_closure)
            elif python:
                entry = python_entrypoint(component.argv, cwd)
                search_paths.append([str(p) for p in _python_search(entry, cwd)])
                files.append(entry)
                tree = ast.parse(entry.read_text())
                alias = worker is not None and (entry == worker or
                    entry.read_bytes() == worker.read_bytes() or any(
                        isinstance(n, ast.ImportFrom) and any(a.name == 'main' for a in n.names) or
                        isinstance(n, ast.Call) and (getattr(n.func, 'attr', None) in
                            ('import_module', 'run_module', 'run_path') or
                            getattr(n.func, 'id', None) in ('__import__', 'exec', 'eval'))
                        for n in ast.walk(tree)))
                if alias:
                    component_closure = proven_dispatcher_closure(entry, worker, cwd=cwd)
                    files = [executable, worker]
                    identity_closure = implementation_closure(worker, cwd=cwd)
                else:
                    component_closure = implementation_closure(entry, cwd=cwd)
                    identity_closure = component_closure
                component_closure.add(executable)
                closure.update(identity_closure | {executable})
            else:
                for token in component.argv[1:2]:
                    path = Path(token)
                    if path.is_absolute() and path.is_file():
                        files.append(path.resolve())
                component_closure = source_closure(files)
                closure.update(component_closure)
        except (OSError, SyntaxError, ValueError) as exc:
            raise Refusal('PROVIDER_DEPENDENCY_UNBOUND', str(exc)) from exc
        executed.update(component_closure)
        roots.append(tuple(str(p) for p in files))
    for path in executed | closure:
        if adapter.source_files.get(str(path)) != bound_digest(path):
            raise Refusal('PROVIDER_DEPENDENCY_UNBOUND', str(path))
    identity = tuple(roots), tuple((str(path), bound_digest(path)) for path in sorted(closure))
    if include_execution:
        return identity + ({'files': {str(path): bound_digest(path) for path in sorted(executed | closure)},
                            'search_paths': search_paths,
                            'python_import_policy': 'isolated-source-only-v1'},)
    return identity


def _python_cache_policy(outputs: Path, process: dict | None = None) -> dict:
    """Force source imports without changing the issued caller argv.

    -B alone still reads timestamp-valid stale bytecode. A fresh private
    prefix redirects cache lookup before interpreter startup; disabling
    writes keeps that prefix empty. Recheck the issued prefix at eligibility
    and adoption instead of trusting source text to describe cached code.
    """
    if process is None:
        prefix = outputs.parent / ('.python-cache-' + uuid.uuid4().hex)
        prefix.mkdir(mode=0o700)
        return {'PYTHONPYCACHEPREFIX': str(prefix), 'PYTHONDONTWRITEBYTECODE': '1'}
    environment = process.get('issued_environment', {})
    value = environment.get('PYTHONPYCACHEPREFIX')
    if not isinstance(value, str) or environment.get('PYTHONDONTWRITEBYTECODE') != '1':
        raise Refusal('PYTHON_BYTECODE_POLICY_CHANGED', str(outputs))
    prefix = Path(value)
    if (prefix.parent != outputs.parent or not prefix.name.startswith('.python-cache-') or
            prefix.is_symlink() or not prefix.is_dir() or
            prefix.stat().st_mode & 0o077 or any(prefix.iterdir())):
        raise Refusal('PYTHON_BYTECODE_POLICY_CHANGED', value)
    return {'PYTHONPYCACHEPREFIX': value, 'PYTHONDONTWRITEBYTECODE': '1'}


def _frontend_chain_signatures():
    key = secrets.token_bytes(32)
    def sign(value):
        if _ISSUED_FRONTEND_CHILD is None:
            raise Refusal('ISSUED_FRONTEND_UNAVAILABLE', 'producer chain')
        payload = json.loads(json.dumps(value))
        return dict(payload=payload, signature=hmac.new(key, _hash(payload).encode(), hashlib.sha256).hexdigest())
    def consume(document):
        payload = document['payload']
        expected = hmac.new(key, _hash(payload).encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, document.get('signature', '')):
            raise Refusal('STAGED_CHAIN_INVALID', 'producer chain')
        return payload
    return sign, consume


_sign_frontend_chain, _consume_frontend_signature = _frontend_chain_signatures()


def _issued(path: Path) -> dict:
    # Only a supervisor-created provisional selected generation uses the
    # reversible component journal. Final manifests and receipts are immutable.
    if path.name == 'manifest.json' and path.parent.parent.name == 'selected':
        document = json.loads(path.read_text())
        if document.get('payload', {}).get('status') == 'PROVISIONAL':
            return _consume_provisional(path)
    return _consume_sealed(path)


def require_issued_frontend(project: Path, output: Path, step: str,
                            parameters: dict) -> None:
    """BLOCKING: reuse live Controller plan issuance before either producer.

    An exec-created CLI has neither the issuer's key/state nor its live child
    reference. Serialized plans and caller-owned digests cannot restore them.
    """
    invocation = _ISSUED_FRONTEND_CHILD
    if invocation is None:
        raise Refusal('ISSUED_FRONTEND_UNAVAILABLE', step)
    plan_path, arm, component, argv, pid, issuer_pid = invocation
    if os.getpid() != pid or os.getppid() != issuer_pid or pid == issuer_pid:
        raise Refusal('ISSUED_FRONTEND_WRONG_PROCESS', step)
    plan = _issued(plan_path)
    root = plan_path.parent
    if (plan != json.loads((root / 'plan.json').read_text()) or
            plan.get('run_root') != str(root) or
            arm.arm_id not in plan['arms'] or step != arm.step_id or
            step != plan['binding']['step_id'] or
            not any(all(row.get(k) == v for k, v in arm.identity().items())
                    and row.get('admission') == 'READY' for row in plan['portfolio'])):
        raise Refusal('ISSUED_FRONTEND_PLAN_MISMATCH', step)
    inputs, outputs = root / arm.arm_id / 'inputs', root / arm.arm_id / 'outputs'
    expected_argv = [v.replace('{inputs}', str(inputs)).replace('{outputs}', str(outputs))
                     for v in component.argv]
    expected_argv[0] = str(Path(shutil.which(expected_argv[0])).resolve())
    if (Path(project).absolute() != inputs or Path(output).absolute() != outputs or
            inputs.resolve() != inputs or outputs.resolve() != outputs or
            argv != expected_argv or _sys.argv != argv[1:] or
            str(Path(_sys.executable).resolve()) != argv[0] or
            parameters != plan['binding']['objective']):
        raise Refusal('ISSUED_FRONTEND_INVOCATION_MISMATCH', step)
    Controller._source_current(arm)
    if digest(Path(__file__)) != plan['binding']['controller_sha256']:
        raise Refusal('ISSUED_FRONTEND_CONTROLLER_CHANGED', step)
    payload = plan['issued_manifest_payload']
    manifest = issued_manifest_path(inputs)
    if (payload != {'step_id': step, 'parameters': parameters,
                    'files': plan['binding']['inputs']} or manifest.is_symlink() or
            manifest.read_bytes() != _issued_manifest_bytes(payload) or
            digest(manifest) != plan['issued_manifest_sha256']):
        raise Refusal('ISSUED_FRONTEND_MANIFEST_MISMATCH', step)
    paths = list(inputs.rglob('*'))
    files = {str(p.relative_to(inputs)): digest(p) for p in paths
             if p.is_file() and p != manifest}
    if (not is_exclusive_regular(manifest) or
            any(p.is_file() and not is_exclusive_regular(p) for p in paths) or
            any(p.is_symlink() for p in paths) or files != plan['binding']['inputs']):
        raise Refusal('FROZEN_INPUT_CHANGED', step)


def _frontend_tree(root: Path) -> dict:
    """Stable regular-file reads and inode versions; ctime detects restore/replay.

    Digests alone miss a writer restoring old bytes. lstat on every ancestor
    and inode versions also reject symlinks, directory swaps and replacements.
    """
    import stat
    result = {}
    for path in [root, *sorted(root.rglob('*'))]:
        before = path.lstat()
        version = lambda s: [s.st_dev, s.st_ino, s.st_mode, s.st_size,
                             s.st_mtime_ns, s.st_ctime_ns]
        if stat.S_ISDIR(before.st_mode):
            record = {'kind': 'directory', 'version': version(before)}
        elif stat.S_ISREG(before.st_mode):
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(fd, 'rb') as stream:
                if version(os.fstat(stream.fileno())) != version(before):
                    raise Refusal('STAGED_INPUT_CHANGED', str(path))
                content = stream.read()
                if version(os.fstat(stream.fileno())) != version(before):
                    raise Refusal('STAGED_INPUT_CHANGED', str(path))
            record = {'kind': 'file', 'version': version(before),
                      'sha256': hashlib.sha256(content).hexdigest()}
        else:
            raise Refusal('STAGED_PATH_UNSAFE', str(path))
        if version(path.lstat()) != version(before):
            raise Refusal('STAGED_INPUT_CHANGED', str(path))
        result[str(path.relative_to(root))] = record
    return result


def frontend_producer_main(main) -> int:
    """Run the real CLI and return its in-memory publication digests by pipe.

    The ordinary standalone CLI is unchanged. Controller workers request this
    observation so an intermediate is bound to producer bytes, never to whatever
    an external writer leaves on disk. A nondumpable child protects that private
    capture pipe against another same-user process opening /proc/PID/fd.
    """
    if os.environ.get('VIBEIC_CAPTURE_FRONTEND_WRITES') != '1':
        return main()
    from _atomic_artefact import observe_writes
    if _FRONTEND_LIBC.prctl(4, 0, 0, 0, 0) != 0:
        raise Refusal('PRODUCER_CAPTURE_UNAVAILABLE', 'PR_SET_DUMPABLE')
    with observe_writes() as records:
        rc = main()
    print('VIBEIC_PRODUCER_WRITES=' + json.dumps(records, sort_keys=True), flush=True)
    return rc


class FrontendSnapshot:
    """BLOCKING input lease for one real producer, issued from captured bytes.

    Original inputs never come from the mutable preceding project. A second
    snapshot adds only validated intermediate bytes. Linux directory watches
    close rename/restore races while a producer is running; final inode/ctime
    versions remain bound through gates and adoption after the watches close.
    """
    def __init__(self, root: Path, contents: dict, retired: tuple[str, ...] = ()):
        self.root, self.retired = root, retired
        root.mkdir()
        for name, content in contents.items():
            path = root / _relative(name)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('xb') as stream:
                stream.write(content)
        # Precreate the writable namespaces; they are outputs, never sources
        # from which the next producer's owner/template inputs are copied.
        for name in ('input/submission_template/slots', 'reports/phase1'):
            (root / name).mkdir(parents=True, exist_ok=True)
        self.before = _frontend_tree(root)
        self.inputs = {name: self.before[name] for name in contents}
        if {name: row['sha256'] for name, row in self.inputs.items()} != {
                name: hashlib.sha256(value).hexdigest() for name, value in contents.items()}:
            raise Refusal('STAGED_INPUT_CHANGED', str(root))
        self.protected = set(contents)
        for name in contents:
            self.protected.update(str(p) for p in Path(name).parents)
        self.libc = _FRONTEND_LIBC
        self.fd = self.libc.inotify_init1(os.O_NONBLOCK | os.O_CLOEXEC)
        if self.fd < 0:
            raise Refusal('STAGED_WATCH_UNAVAILABLE', str(ctypes.get_errno()))
        self.watches = {}
        self.events = []
        try:
            for name, row in self.before.items():
                if row['kind'] != 'directory':
                    continue
                wd = self.libc.inotify_add_watch(self.fd, os.fsencode(root / name), 0xFCE)
                if wd < 0:
                    raise Refusal('STAGED_WATCH_UNAVAILABLE', name)
                self.watches[wd] = name
            self.current()
        except BaseException:
            self.close()
            raise

    def current(self) -> dict:
        import struct
        while True:
            try:
                events = os.read(self.fd, 65536)
            except BlockingIOError:
                break
            offset = 0
            while offset < len(events):
                wd, mask, _, length = struct.unpack_from('iIII', events, offset)
                name = os.fsdecode(events[offset + 16:offset + 16 + length].split(b'\0')[0])
                offset += 16 + length
                rel = str(Path(self.watches.get(wd, '.')) / name)
                self.events.append((rel, mask))
                # Only the canonical retirement of the producer-1 absence
                # marker is allowed. Writing/restoring it is still refused.
                retirement = rel in self.retired and mask & 0x200 and not mask & ~0x40000200
                if mask & (0x4000 | 0xC00) or (rel in self.protected and not retirement):
                    raise Refusal('STAGED_INPUT_EVENT', rel)
        now = _frontend_tree(self.root)
        for name, expected in self.inputs.items():
            if name in self.retired and name not in now:
                continue
            if now.get(name) != expected:
                raise Refusal('STAGED_INPUT_CHANGED', name)
        for name in self.protected - set(self.inputs):
            if (now.get(name, {}).get('kind') != 'directory' or
                    now[name]['version'][:3] != self.before[name]['version'][:3]):
                raise Refusal('STAGED_PATH_CHANGED', name)
            if (name not in ('reports', 'reports/phase1', 'input/submission_template') and
                    now[name]['version'] != self.before[name]['version']):
                raise Refusal('STAGED_DIRECTORY_CHANGED', name)
        writable = ('reports/', 'input/submission_template/')
        for name in set(now) - set(self.before):
            if not any(name.startswith(prefix) for prefix in writable):
                raise Refusal('STAGED_UNISSUED_PATH', name)
        return now

    def close(self):
        if self.fd >= 0:
            os.close(self.fd)
            self.fd = -1

    def __del__(self):
        if getattr(self, 'fd', -1) >= 0:
            self.close()

    def protect_intermediate(self, expected: dict, versions: dict):
        """Extend the first input lease to its producer-owned intermediate."""
        now = self.current()
        for name, value in expected.items():
            if name.startswith(('input/submission_template/', 'reports/phase1/')):
                # These namespaces were watched before the producer began.
                # Canonical writers publish once by atomic rename. A second
                # publication, in-place mutation or restore/replay is refused,
                # even if the bytes once again match the producer's pipe.
                events = [mask for rel, mask in self.events if rel == name]
                # The observed writer retains its descriptor across rename,
                # then closes it: MOVED_TO followed by CLOSE_WRITE.
                if events != [0x80, 0x8]:
                    raise Refusal('STAGED_PUBLICATION_EVENT', name)
            if (now.get(name, {}).get('sha256') != value or
                    now[name]['version'] != versions[name]):
                raise Refusal('STAGED_INTERMEDIATE_CHANGED', name)
            self.inputs[name] = now[name]
            self.protected.add(name)
            self.protected.update(str(p) for p in Path(name).parents)
        self.before.update(now)
        for name, row in now.items():
            if row['kind'] == 'directory' and name not in self.watches.values():
                wd = self.libc.inotify_add_watch(self.fd, os.fsencode(self.root / name), 0xFCE)
                if wd < 0:
                    raise Refusal('STAGED_WATCH_UNAVAILABLE', name)
                self.watches[wd] = name
        self.current()


def issue_frontend_chain(output: Path, chain: dict) -> None:
    """Bind per-producer snapshots to the existing live Controller issuance."""
    plan_path, arm, _, _, _, _ = _ISSUED_FRONTEND_CHILD
    plan = _issued(plan_path)
    payload = dict(chain, run_id=plan['run_id'], binding=plan['binding'],
                   adapter=arm.identity(), plan_sha256=_hash(plan),
                   output_root=str(output))
    _write(output / 'issued-producer-chain.json', _sign_frontend_chain(payload))


def consume_frontend_chain(output: Path, facts: Mapping[str, object]) -> dict:
    """BLOCKING reconsumption before gates/selection; no caller digest authority."""
    path = output / 'issued-producer-chain.json'
    if path.is_symlink():
        raise Refusal('STAGED_CHAIN_UNSAFE', str(path))
    document = json.loads(path.read_text())
    payload = _consume_frontend_signature(document)
    plan = _issued(output.parent.parent / 'issued-plan.json')
    arm = payload['adapter']
    if (payload['binding'] != facts or payload['run_id'] != plan['run_id'] or
            payload['plan_sha256'] != _hash(plan) or payload['output_root'] != str(output) or
            output != Path(plan['run_root']) / arm['arm_id'] / 'outputs' or
            not any(all(row.get(k) == v for k, v in arm.items()) for row in plan['portfolio'])):
        raise Refusal('STAGED_CHAIN_UNBOUND', str(path))
    stages = payload['stages']
    if len(stages) != 2 or stages[0]['inputs'] != facts['inputs']:
        raise Refusal('STAGED_CHAIN_INPUT_MISMATCH', str(path))
    intermediate = stages[0]['outputs']
    if (stages[1]['inputs'] != {**facts['inputs'], **intermediate} or
            stages[1]['predecessor_sha256'] != _hash(stages[0]) or
            set(intermediate) & set(facts['inputs'])):
        raise Refusal('STAGED_INTERMEDIATE_MISMATCH', str(path))
    source = Path(__file__).parent
    for index, name in enumerate(('submission_template_ingest', 'tapeout_declaration_gen')):
        stage = stages[index]
        root = output / ('project' if index == 0 else 'producer2_project')
        argv = stage['argv']
        if (stage['root'] != str(root) or stage['rc'] != 0 or
                argv[:3] != [str(Path(_sys.executable).resolve()), str(source / (name + '.py')), str(root)] or
                digest(source / (name + '.py')) != arm['source_files'][str(source / (name + '.py'))] or
                _frontend_tree(root) != stage['final_tree']):
            raise Refusal('STAGED_SNAPSHOT_CHANGED', str(root))
        if {n: stage['issued_tree'][n]['sha256'] for n in stage['inputs']} != stage['inputs']:
            raise Refusal('STAGED_SNAPSHOT_UNBOUND', str(root))
    if stages[1]['outputs'] != payload['outputs']:
        raise Refusal('STAGED_CHAIN_OUTPUT_MISMATCH', str(path))
    for name, expected in facts['inputs'].items():
        if name.startswith('input/docs/'):
            target = output / _relative(name)
            if (target.is_symlink() or not target.is_file() or
                    not target.resolve().is_relative_to(output) or
                    digest(target) != expected):
                raise Refusal('STAGED_INPUT_COPY_CHANGED', name)
    for name, expected in payload['outputs'].items():
        target = output / _relative(name)
        if (target.is_symlink() or not target.resolve().is_relative_to(output) or
                digest(target) != expected or target.stat().st_ctime_ns != payload['output_ctimes'][name]):
            raise Refusal('STAGED_OUTPUT_CHANGED', name)
    return payload


def _issued_frontend_child(plan_path, arm, component, argv, cwd, out_fd,
                           err_fd, env, cpuset, issuer_pid):
    """Run the exact source-bound Python CLI without exec erasing issuance."""
    import resource
    import runpy
    import traceback
    global _ISSUED_FRONTEND_CHILD
    exitcode = 0
    try:
        os.setsid()
        os.dup2(out_fd, 1); os.dup2(err_fd, 2)
        _sys.stdout = os.fdopen(os.dup(1), 'w', buffering=1)
        _sys.stderr = os.fdopen(os.dup(2), 'w', buffering=1)
        os.chdir(cwd)
        resource.setrlimit(resource.RLIMIT_AS, (arm.ram_mb * 1024 * 1024,) * 2)
        os.sched_setaffinity(0, set(cpuset))
        os.environ.clear(); os.environ.update(env)
        _sys.argv = argv[1:]
        _ISSUED_FRONTEND_CHILD = (plan_path, arm, component, argv,
                                  os.getpid(), issuer_pid)
        require_issued_frontend(Path(argv[5]), Path(argv[7]), argv[3],
                                _issued(plan_path)['binding']['objective'])
        runpy.run_path(argv[1], run_name='__main__')
    except SystemExit as exc:
        exitcode = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
    except BaseException:
        traceback.print_exc()
        exitcode = 1
    finally:
        _ISSUED_FRONTEND_CHILD = None
        _sys.stdout.flush(); _sys.stderr.flush()
        # A forked worker must not run the parent's ThreadPoolExecutor exit
        # hooks, which would try to join the thread that became this child.
        os._exit(exitcode)


class _IssuedFrontendProcess:
    """A bounded Linux child retaining the existing process-local issuer.

    Only the exact registered 0.5ic and D1 workers use this path. Other components
    retain the exec launcher. No preexec_fn or external authorization service.
    """
    def __init__(self, plan_path, arm, component, argv, cwd, stdout, stderr,
                 env, cpuset):
        self._process = multiprocessing.get_context('fork').Process(
            target=_issued_frontend_child,
            args=(plan_path, arm, component, argv, cwd, stdout.fileno(),
                  stderr.fileno(), env, cpuset, os.getpid()))
        self._process.start()
        self.pid = self._process.pid

    @property
    def returncode(self):
        return self._process.exitcode

    def poll(self):
        return self.returncode

    def wait(self):
        self._process.join()
        return self.returncode


def _relative(value: str) -> Path:
    p = Path(value)
    if p.is_absolute() or not p.parts or '..' in p.parts or value == '.':
        raise Refusal('UNSAFE_RELATIVE_PATH', value)
    return p


def _write(path: Path, value: object) -> None:
    write_json(path, value)


@dataclass(frozen=True)
class Budget:
    cpus: int
    ram_mb: int
    workers: int = 4
    licenses: Mapping[str, int] = field(default_factory=dict)

    def __post_init__(self):
        if any(type(v) is not int or v <= 0 for v in
               (self.cpus, self.ram_mb, self.workers)) or any(
                type(v) is not int or v < 0 for v in self.licenses.values()):
            raise Refusal('INVALID_BUDGET', repr(self))


@dataclass(frozen=True)
class Context:
    step_id: str
    source_sha: str
    inputs: Mapping[str, Path]
    objective: Mapping[str, object]
    required_gates: tuple[str, ...]
    native_mode: str = 'direct'
    # Production contexts must resolve both fields at construction.  The
    # neutral controller fixtures pass an explicit ``neutral-test`` receipt.
    ic_ip_path: str | None = None
    route_receipt: Mapping[str, object] = field(default_factory=dict)
    project_digest: str = ''
    intent_label: str = 'PROGRAM_DEFAULT'
    request_digest: str = ''
    # Only the repository's explicit neutral test fixture may use the
    # compatibility route.  A caller-authored ``kind=neutral-test`` mapping
    # is not production authorization and cannot qualify or adopt.

    def binding(self) -> dict:
        if not re.fullmatch(r'[0-9a-f]{40}', self.source_sha):
            raise Refusal('INVALID_SOURCE_SHA', self.source_sha)
        if self.native_mode not in ('direct', 'librelane', 'dual'):
            raise Refusal('AMBIGUOUS_NATIVE_IDENTITY', self.native_mode)
        if self.ic_ip_path not in ('IC', 'IP'):
            raise Refusal('INVALID_IC_IP_PATH', self.ic_ip_path)
        if self.intent_label not in ('PROGRAM_DEFAULT', 'USER_EXPLICIT_ULTRA'):
            raise Refusal('INVALID_EXECUTION_INTENT', self.intent_label)
        if self.request_digest and not re.fullmatch(r'[0-9a-f]{64}', self.request_digest):
            raise Refusal('INVALID_REQUEST_DIGEST', self.request_digest)
        if self.intent_label == 'USER_EXPLICIT_ULTRA' and not self.request_digest:
            raise Refusal('REQUEST_INTENT_UNBOUND', 'explicit Ultra needs its issued request digest')
        if not self.route_receipt:
            raise Refusal('ROUTE_RECEIPT_REQUIRED', 'IC/IP context needs a bound route receipt')
        route_path = self.route_receipt.get('ic_ip_path')
        if route_path != self.ic_ip_path:
            raise Refusal('IC_IP_ROUTE_MISMATCH', self.step_id)
        route_kind = self.route_receipt.get('kind')
        if route_kind == 'issued-route':
            required = ('schema', 'route_digest', 'project_digest', 'source_sha',
                        'request_digest')
            if (any(key not in self.route_receipt for key in required) or
                    self.route_receipt.get('schema') != 1 or
                    not re.fullmatch(r'[0-9a-f]{64}', str(self.route_receipt['project_digest'])) or
                    not re.fullmatch(r'[0-9a-f]{64}', str(self.route_receipt['request_digest'])) or
                    not re.fullmatch(r'[0-9a-f]{64}', str(self.route_receipt['route_digest']))):
                raise Refusal('ROUTE_RECEIPT_INVALID', self.step_id)
            route_body = {k: v for k, v in self.route_receipt.items()
                          if k != 'route_digest'}
            if _hash(route_body) != self.route_receipt['route_digest']:
                raise Refusal('ROUTE_RECEIPT_DIGEST_MISMATCH', self.step_id)
            if self.route_receipt['source_sha'] != self.source_sha:
                raise Refusal('ROUTE_SOURCE_MISMATCH', self.step_id)
            if self.route_receipt['project_digest'] != self.project_digest:
                raise Refusal('ROUTE_PROJECT_MISMATCH', self.step_id)
            if self.route_receipt['request_digest'] != self.request_digest:
                raise Refusal('ROUTE_REQUEST_MISMATCH', self.step_id)
            route_intent = self.route_receipt.get('intent_label', 'PROGRAM_DEFAULT')
            route_mode = self.route_receipt.get('mode_intent', 'default')
            if (route_intent != self.intent_label or
                    route_mode != ('ultra' if self.intent_label == 'USER_EXPLICIT_ULTRA'
                                   else 'default')):
                raise Refusal('ROUTE_INTENT_MISMATCH', self.step_id)
            _verify_route_authority(self.route_receipt)
            _git_source_authority(self.source_sha)
        else:
            raise Refusal('ROUTE_RECEIPT_INVALID', self.step_id)
        if not self.inputs or not self.objective or not self.required_gates:
            raise Refusal('INCOMPLETE_CONTEXT', self.step_id)
        if len(set(self.required_gates)) != len(self.required_gates):
            raise Refusal('DUPLICATE_GATE', self.step_id)
        files = {}
        for name, path in self.inputs.items():
            _relative(name)
            if not Path(path).is_file() or Path(path).is_symlink():
                raise Refusal('INPUT_NOT_REGULAR', name)
            files[name] = digest(Path(path))
        return dict(step_id=self.step_id, source_sha=self.source_sha,
                    controller_sha256=digest(Path(__file__)),
                    inputs=files, objective=dict(self.objective),
                    required_gates=list(self.required_gates),
                    native_mode=self.native_mode,
                    ic_ip_path=self.ic_ip_path,
                    route_receipt=dict(self.route_receipt),
                    project_digest=self.project_digest,
                    route_receipt_sha256=_hash(self.route_receipt)
                    if self.route_receipt else None,
                    intent_label=self.intent_label,
                    request_digest=self.request_digest)


def _context_implementation_authority():
    # Capture the concrete class before any external module-slot replacement.
    # Its attribute dispatch and field descriptors are part of the authority,
    # alongside binding's tracked source; a borrowed method is insufficient.
    concrete = Context
    members = dict(vars(concrete))
    source = Path(__file__).resolve()

    def require() -> type:
        current = vars(concrete)
        if (current.keys() != members.keys() or
                any(current[name] is not value for name, value in members.items())):
            raise Refusal('CONTEXT_IMPLEMENTATION_UNTRUSTED', concrete.__name__)
        _source_method(concrete, source, 'binding')
        return concrete

    return require


_require_context_type = _context_implementation_authority()


def _source_protocol_context(context_type: type, fixture, concrete: type) -> Callable:
    """Verify the whole permitted fixture class before any context field read.

    The fixture's module slot is a locator, not class authority. The tracked
    declaration, exact base, member set, function globals and class closures
    must all agree; external descriptors or dispatch hooks are refused.
    """
    source = Path(__file__).parent / 'tests/test_execution_modes.py'
    if type(context_type) is not type or context_type.__bases__ != (concrete,):
        raise Refusal('CONTEXT_IMPLEMENTATION_UNTRUSTED', context_type.__name__)
    _tracked_clean_file(source)
    definition = next((node for node in ast.parse(source.read_bytes()).body
                       if isinstance(node, ast.ClassDef) and node.name == context_type.__name__), None)
    if definition is None:
        raise Refusal('CONTEXT_IMPLEMENTATION_UNTRUSTED', context_type.__name__)
    methods = [node.name for node in definition.body if isinstance(node, ast.FunctionDef)]
    if any(not isinstance(node, ast.FunctionDef) and not (
            isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and
            isinstance(node.value.value, str)) for node in definition.body):
        raise Refusal('CONTEXT_IMPLEMENTATION_UNTRUSTED', 'unsupported fixture declaration')
    members = vars(context_type)
    if (set(members) != {'__module__', '__doc__', *methods} or
            members['__module__'] != fixture.__name__ or
            members['__doc__'] != ast.get_docstring(definition, clean=False) or
            context_type.__qualname__ != definition.name):
        raise Refusal('CONTEXT_IMPLEMENTATION_UNTRUSTED', context_type.__name__)
    for name in methods:
        method = _source_method(context_type, source, name)
        if method.__globals__ is not vars(fixture):
            raise Refusal('CONTEXT_IMPLEMENTATION_UNTRUSTED', name)
        cells = dict(zip(method.__code__.co_freevars, method.__closure__ or ()))
        if any(name != '__class__' or cell.cell_contents is not context_type
               for name, cell in cells.items()):
            raise Refusal('CONTEXT_IMPLEMENTATION_UNTRUSTED', name)
    return members['binding']


@dataclass(frozen=True)
class Component:
    name: str
    argv: tuple[str, ...]
    timeout_s: float = 30


@dataclass(frozen=True)
class Evidence:
    """Produced by the adapter's output consumer; never inferred from rc0."""
    binding: Mapping[str, object]
    verdict: str
    gates: Mapping[str, str]
    outputs: Mapping[str, str]  # relative output filename -> measured sha256
    metrics: Mapping[str, float] = field(default_factory=dict)
    detail: str = ''
    provenance: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class Adapter:
    arm_id: str
    tool_id: str
    step_id: str
    source_sha: str
    source_files: Mapping[str, str]  # absolute local implementation -> digest
    tool_version: str
    engine_families: tuple[str, ...]
    components: tuple[Component, ...]
    validate: Callable[[Path, Mapping[str, object]], Evidence]
    required_outputs: tuple[str, ...]
    objective: Mapping[str, object]
    applicability: str = 'applicable'  # applicable | inapplicable | unknown
    applicability_reason: str = ''
    role: str = 'producer'  # checker/complementary never become candidates
    qualified: bool = True
    qualification_evidence: str = ''
    available: bool = True
    availability_reason: str = ''
    cpus: int = 1
    ram_mb: int = 128
    license_id: str | None = None
    own_no_tool_reason: str | None = None
    output_contract: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    input_contract: tuple[object, ...] = field(default_factory=tuple)

    verified_source_blobs: Mapping[str, str] = field(default_factory=dict)
    executable_receipts: Mapping[str, object] = field(default_factory=dict)
    invocation_sources: Mapping[str, object] = field(default_factory=dict)

    def identity(self) -> dict:
        return dict(arm_id=self.arm_id, tool_id=self.tool_id,
                    step_id=self.step_id, source_sha=self.source_sha,
                    source_files=dict(self.source_files),
                    verified_source_blobs=dict(self.verified_source_blobs),
                    executable_receipts=dict(self.executable_receipts),
                    invocation_sources=dict(self.invocation_sources),
                    tool_version=self.tool_version,
                    engine_families=list(self.engine_families),
                    components=[dict(name=c.name, argv=list(c.argv),
                                     timeout_s=c.timeout_s) for c in self.components],
                    required_outputs=list(self.required_outputs),
                    output_contract={k: list(v) for k, v in self.output_contract.items()},
                    input_contract=list(self.input_contract),
                    objective=dict(self.objective), role=self.role,
                    qualification_evidence=self.qualification_evidence)


class Registry:
    """Explicit source-bound executors. The shipped production registry is empty."""
    def __init__(self, snapshot: SourceSnapshot | None = None):
        self._adapters: dict[str, Adapter] = {}
        self._version_lock = threading.Lock()
        self.snapshot = snapshot
        self._finalized = False
        self._step9_reserved: Adapter | None = None
        self._step9_binding_closed = False

    def finalize(self) -> None:
        if self._finalized:
            return
        if self.snapshot is not None:
            try:
                self.snapshot.finalize()
            except RuntimeError as exc:
                code = str(exc).split(':', 1)[0]
                raise Refusal(code if code.startswith('SOURCE_AUTHORITY_') else
                              'SOURCE_AUTHORITY_UNAVAILABLE', str(exc)) from exc
        self._finalized = True

    def register(self, adapter: Adapter) -> None:
        if self._finalized:
            raise Refusal('REGISTRY_FINALIZED', adapter.arm_id)
        if adapter.arm_id in self._adapters:
            raise Refusal('DUPLICATE_ARM', adapter.arm_id)
        if not re.fullmatch(r'[A-Za-z0-9_.-]+', adapter.arm_id) or adapter.arm_id in _CONTROL_NAMES:
            raise Refusal('UNSAFE_ARM_ID', adapter.arm_id)
        if not adapter.source_files or not adapter.tool_version or not (
                adapter.engine_families and adapter.components and
                callable(adapter.validate)):
            raise Refusal('ADAPTER_INCOMPLETE', adapter.arm_id)
        if not adapter.qualification_evidence:
            raise Refusal('QUALIFICATION_UNBOUND', adapter.arm_id)
        _verified_current_source_commit(adapter.source_sha)
        snapshot_session = _active_source_snapshot()
        head = (snapshot_session.commit if snapshot_session is not None else
                subprocess.check_output(['git', '-C', str(_REPO_ROOT), 'rev-parse', 'HEAD'], text=True).strip())
        if head != adapter.source_sha:
            raise Refusal('SOURCE_AUTHORITY_STALE', adapter.source_sha)
        executable_paths = []
        for component in adapter.components:
            binary = shutil.which(component.argv[0])
            if binary:
                executable_paths.append(Path(binary).resolve())
        known_tool = adapter.tool_id in ('librelane', 'openroad', 'openroad_fork')
        if known_tool:
            # Priority is never granted to a caller's name/version or basename.
            # Native installations require an independently issued install
            # receipt; this source-only controller has no such issuer wired.
            raise Refusal('TOOL_ID_UNBOUND', 'verified native installation receipt required')
        invocations = {component.name: _invocation_sources(component) for component in adapter.components}
        if adapter.applicability not in ('applicable', 'inapplicable', 'unknown'):
            raise Refusal('INVALID_APPLICABILITY', adapter.arm_id)
        if adapter.role not in ('producer', 'checker', 'complementary'):
            raise Refusal('INVALID_ROLE', adapter.arm_id)
        if adapter.applicability != 'applicable' and not adapter.applicability_reason:
            raise Refusal('APPLICABILITY_UNEXPLAINED', adapter.arm_id)
        if not adapter.available and not adapter.availability_reason:
            raise Refusal('AVAILABILITY_UNEXPLAINED', adapter.arm_id)
        if any(type(v) is not int or v <= 0 for v in (adapter.cpus, adapter.ram_mb)):
            raise Refusal('INVALID_ARM_BUDGET', adapter.arm_id)
        for name in adapter.required_outputs:
            _relative(name)
        if not isinstance(adapter.input_contract, tuple):
            raise Refusal('INPUT_CONTRACT_INVALID', adapter.arm_id)
        if any(not paths or not set(paths).issubset(adapter.required_outputs)
               for paths in adapter.output_contract.values()):
            raise Refusal('OUTPUT_CONTRACT_UNBOUND', adapter.arm_id)
        for path, expected in adapter.source_files.items():
            p = Path(path)
            if not p.is_file() or p.is_symlink() or digest(p) != expected:
                raise Refusal('ADAPTER_SOURCE_MISMATCH', path)
        declared_sources = {Path(path).resolve() for path in adapter.source_files}
        external = set(executable_paths) - {p for p in executable_paths if p.is_relative_to(_REPO_ROOT)}
        source_blobs = _git_source_blobs(adapter.source_sha, declared_sources - external)
        for path in declared_sources - external:
            if source_blobs[str(path)] != _blob_bytes(path):
                raise Refusal('SOURCE_AUTHORITY_DIRTY', str(path))
        missing_dependencies = _source_closure(adapter.source_files) - declared_sources
        if missing_dependencies:
            raise Refusal('ADAPTER_SOURCE_CLOSURE_INCOMPLETE', str(sorted(missing_dependencies)[0]))
        for component in adapter.components:
            _relative(component.name)
            if len(Path(component.name).parts) != 1 or not component.argv or (
                    not math.isfinite(component.timeout_s) or component.timeout_s <= 0):
                raise Refusal('INVALID_COMPONENT', component.name)
            binary = shutil.which(component.argv[0])
            if not binary or str(Path(binary).resolve()) not in adapter.source_files:
                raise Refusal('EXECUTABLE_UNBOUND', component.argv[0])
            invocation = invocations[component.name]
            for name, expected in invocation['argument_sources'].items():
                path = Path(name)
                if not path.is_relative_to(_REPO_ROOT) or adapter.source_files.get(name) != expected:
                    raise Refusal('ENTRY_SOURCE_UNBOUND', name)
                if source_blobs.get(str(path)) != _blob_bytes(path):
                    raise Refusal('SOURCE_AUTHORITY_DIRTY', str(path))
            invocations[component.name] = invocation
            # Python workers and shell launchers carry their real script or
            # executable as a later absolute argv member.  Bind those files
            # too; checking argv[0] alone would let a changed producer run
            # under an unchanged interpreter identity.
            for token in component.argv[1:]:
                candidate = Path(token)
                if candidate.is_absolute() and candidate.is_file() and not candidate.is_symlink():
                    resolved = str(candidate.resolve())
                    if resolved not in adapter.source_files or digest(candidate) != adapter.source_files[resolved]:
                        raise Refusal('EXECUTABLE_UNBOUND', token)
        validator_file = inspect.getsourcefile(adapter.validate)
        if not validator_file or str(Path(validator_file).resolve()) not in adapter.source_files:
            raise Refusal('VALIDATOR_SOURCE_UNBOUND', adapter.arm_id)
        if len({c.name for c in adapter.components}) != len(adapter.components):
            raise Refusal('DUPLICATE_COMPONENT', adapter.arm_id)
        # The caller's dataclass may be frozen while its nested mappings remain
        # mutable.  Publish an immutable registration snapshot so a later
        # ``arm.source_files[path] = new_digest`` cannot rehash authority.
        current_head = (snapshot_session.commit if snapshot_session is not None else
                        subprocess.check_output(['git', '-C', str(_REPO_ROOT), 'rev-parse', 'HEAD'], text=True).strip())
        if current_head != adapter.source_sha:
            raise Refusal('SOURCE_AUTHORITY_STALE', adapter.source_sha)
        snapshot = replace(
            adapter,
            verified_source_blobs=MappingProxyType(source_blobs),
            executable_receipts=MappingProxyType({}),
            invocation_sources=MappingProxyType(invocations),
            source_files=MappingProxyType(dict(adapter.source_files)),
            engine_families=tuple(adapter.engine_families),
            components=tuple(adapter.components),
            required_outputs=tuple(adapter.required_outputs),
            objective=MappingProxyType(dict(adapter.objective)),
            output_contract=MappingProxyType({k: tuple(v)
                                              for k, v in adapter.output_contract.items()}),
        )
        self._adapters[adapter.arm_id] = snapshot

    def reserve_step9(self, adapter: Adapter) -> None:
        """Reserve only the native Step9 slot before upstream RTL exists."""
        from execution_synthesis_engines import LIBRELANE
        if (adapter.step_id != '9' or adapter.arm_id != LIBRELANE.arm_id or
                adapter.tool_id != 'step9-worker' or adapter.available or
                adapter.qualified or self.adapters('9') or
                adapter.availability_reason != 'STEP9_DISPATCH_PREPARATION_PENDING'):
            raise Refusal('STEP9_RESERVATION_UNBOUND', adapter.arm_id)
        self.register(adapter)
        self._step9_reserved = self._adapters[adapter.arm_id]

    def bind_step9(self, *, project: Path, parameters: dict) -> None:
        """Complete that exact reservation once, before any Step9 plan.

        Only the canonical installation producer can construct the replacement.
        It must pass ordinary registration and a fresh source snapshot. General
        registration remains closed; no other arm changes.
        """
        with self._version_lock:
            if self._step9_binding_closed:
                raise Refusal('STEP9_BINDING_CLOSED', '9')
            reserved = self._step9_reserved
            if (reserved is None or not self._finalized or
                    self.adapters('9') != [reserved] or
                    self._adapters.get(reserved.arm_id) is not reserved):
                raise Refusal('STEP9_RESERVATION_UNBOUND', '9')
            from execution_source_snapshot import using
            from execution_production import register_synthesis_adapter
            snapshot = SourceSnapshot(_REPO_ROOT, reserved.source_sha)
            with using(snapshot):
                prepared = Registry(snapshot=snapshot)
                register_synthesis_adapter(prepared, project=project,
                                           parameters=parameters)
                prepared.finalize()
            if len(prepared._adapters) != 1:
                raise Refusal('STEP9_PREPARATION_UNBOUND', '9')
            candidate = prepared._adapters.get(reserved.arm_id)
            fixed = ('arm_id', 'step_id', 'tool_id', 'source_sha', 'source_files',
                     'components', 'validate', 'required_outputs', 'input_contract',
                     'engine_families', 'cpus', 'ram_mb', 'license_id',
                     'output_contract', 'role', 'applicability', 'applicability_reason')
            if candidate is None or any(getattr(candidate, key) != getattr(reserved, key)
                                        for key in fixed):
                raise Refusal('STEP9_RESERVATION_CHANGED', '9')
            Controller._source_current(candidate)
            self._adapters[reserved.arm_id] = candidate
            self._step9_binding_closed = True
            self._step9_reserved = None

    def adapters(self, step_id: str) -> list[Adapter]:
        return [a for a in self._adapters.values() if a.step_id == step_id]


def load_portfolio(path: Path | None = None) -> dict:
    path = path or Path(__file__).parent / 'data/execution_modes_portfolio.json'
    data = json.loads(path.read_text())
    _validate_portfolio(data)
    return data


def _canonical_flow_requirements() -> tuple[str, dict[str, dict]]:
    flow_path = _canonical_flow_path()
    snapshot = _active_source_snapshot()
    cache_key = ('canonical-flow-requirements', str(flow_path.resolve()))
    if snapshot is not None:
        cached = snapshot.value_get(cache_key)
        if cached is not None:
            snapshot.read_bytes(flow_path)
            return cached
    try:
        import yaml
        flow = yaml.safe_load(snapshot.read_text(flow_path) if snapshot else flow_path.read_text())
    except (OSError, ValueError, ImportError) as exc:
        raise Refusal('PORTFOLIO_CANONICAL_UNAVAILABLE', str(flow_path)) from exc
    if not isinstance(flow, dict) or not isinstance(flow.get('steps'), list):
        raise Refusal('PORTFOLIO_CANONICAL_INVALID', str(flow_path))
    flow_sha = _canonical_flow_authority(flow_path)
    requirements = {}
    for step in flow['steps']:
        step_id = str(step.get('id'))
        gates = set()
        gate = step.get('gate') or {}
        for clause in [gate, *gate.get('all_of', [])]:
            for key in ('program_exit_zero', 'advisory_program_exit_zero',
                        'optional_program_exit_zero'):
                value = clause.get(key) if isinstance(clause, dict) else None
                command = value if isinstance(value, str) else (
                    value.get('command', '') if isinstance(value, dict) else '')
                if command:
                    gates.add(Path(command.split()[0]).name)
        requirements[step_id] = dict(
            gates=frozenset(gates),
            outputs=tuple(step.get('required_outputs') or ()),
        )
    if len(requirements) != 70:
        raise Refusal('PORTFOLIO_CANONICAL_INVALID', str(len(requirements)))
    result = (flow_sha, requirements)
    if snapshot is not None:
        snapshot.value_put(cache_key, result)
    return result


def _validate_portfolio(data: dict, *, snapshot=None) -> None:
    if not isinstance(data, dict) or data.get('meta', {}).get('test_only'):
        return
    flow_sha, requirements = _canonical_flow_requirements()
    snapshot = snapshot or _active_source_snapshot()
    meta = data.get('meta') or {}
    if meta.get('canonical_flow_sha256') != flow_sha:
        raise Refusal('PORTFOLIO_STALE_CANONICAL', str(meta.get('canonical_flow_sha256')))
    ids = [s['id'] for s in data['steps']]
    if len(ids) != 70 or len(set(ids)) != 70:
        raise Refusal('PORTFOLIO_IDS_INVALID', str(len(ids)))
    try:
        current_blob = (snapshot.git_blobs(snapshot.commit, (_canonical_flow_path(),))
                        .get(str(_canonical_flow_path().resolve())) if snapshot else None)
    except RuntimeError as exc:
        raise Refusal('PORTFOLIO_SOURCE_UNBOUND', str(_canonical_flow_path())) from exc
    for row in data['steps']:
        req = requirements.get(str(row.get('id')))
        if req is None:
            raise Refusal('PORTFOLIO_STEP_UNBOUND', str(row.get('id')))
        source = ((row.get('current_default') or {}).get('source') or {})
        expected_file = 'vibe-ic-marketplace/plugins/vibe-ic/flow/phase1_phase2_phase3.yaml'
        if ('sha' in source or source.get('canonical_file') != expected_file or
                str(source.get('canonical_step_id')) != str(row.get('id')) or
                source.get('canonical_blob') != meta.get('canonical_flow_git_blob')):
            raise Refusal('PORTFOLIO_SOURCE_UNBOUND', str(row.get('id')))
        row_current_blob = current_blob or subprocess.check_output(
            ['git', '-C', str(_REPO_ROOT), 'hash-object', str(_canonical_flow_path())],
            text=True).strip()
        if row_current_blob != meta.get('canonical_flow_git_blob'):
            raise Refusal('PORTFOLIO_SOURCE_UNBOUND', str(row.get('id')))
        for program in source.get('programs') or ():
            program_path = _REPO_ROOT / 'vibe-ic-marketplace/plugins/vibe-ic/programs' / f'{program}.py'
            _tracked_clean_file(program_path)
        if not req['gates'].issubset(set(row.get('mandatory_gate_programs') or ())):
            raise Refusal('PORTFOLIO_GATES_STALE', str(row.get('id')))
        declared_outputs = set(row.get('required_output_contract') or ())
        if not set(req['outputs']).issubset(declared_outputs):
            raise Refusal('PORTFOLIO_OUTPUTS_STALE', str(row.get('id')))


@dataclass(frozen=True)
class Superiority:
    """Previous measured comparison; candidate evidence must share this binding."""
    binding: Mapping[str, object]
    preferred: str
    reference: str
    metric: str
    direction: str
    receipts: Mapping[str, Path]


class Controller:
    def __init__(self, registry: Registry, budget: Budget, portfolio: dict | None = None):
        self.registry, self.budget = registry, budget
        self.portfolio = portfolio if portfolio is not None else load_portfolio()
        _validate_portfolio(self.portfolio, snapshot=registry.snapshot)
        registry.finalize()

    @_bind_canonical_issuer
    def _context_binding(self, context: Context, *, _issuer) -> dict:
        """BLOCKING: foreign implementations cannot speak for a live issuer.

        The tracked neutral protocol fixture has no production authority. Its
        exact implementation may exercise a test-only portfolio with default,
        empty transport fields; it cannot turn caller labels into a request.
        """
        concrete = _require_context_type()
        context_type = type(context)
        fixture = _sys.modules.get('programs.tests.test_execution_modes')
        neutral_type = getattr(fixture, 'NeutralContext', None) if fixture else None
        neutral = neutral_type is not None and context_type is neutral_type
        if context_type is not concrete and not neutral:
            raise Refusal('CONTEXT_IMPLEMENTATION_UNTRUSTED', context_type.__name__)
        if neutral:
            binding_method = _source_protocol_context(neutral_type, fixture, concrete)
            if (self.portfolio.get('meta', {}).get('test_only') is not True and
                    self.registry.adapters(context.step_id)):
                raise Refusal('CONTEXT_IMPLEMENTATION_UNTRUSTED', context_type.__name__)
            if context.route_receipt.get('kind') != 'neutral-test':
                context = concrete(**{name: getattr(context, name) for name in concrete.__dataclass_fields__})
            elif context.intent_label != 'PROGRAM_DEFAULT' or context.request_digest or context.project_digest:
                raise Refusal('CONTROLLER_ISSUANCE_REQUIRED', 'neutral fixture has no execution authority')
            if type(context) is neutral_type:
                return binding_method(context)
        try:
            issued = _issuer()
        except Refusal as exc:
            raise Refusal('CONTROLLER_ISSUANCE_REQUIRED', str(exc)) from exc
        binding = concrete.binding(context)
        if (dict(context.route_receipt) != issued['route'] or
                context.request_digest != issued['request']['request_digest'] or
                context.intent_label != issued['request']['intent_label']):
            raise Refusal('CONTROLLER_ISSUANCE_REQUIRED', 'context differs from canonical issued request')
        return binding

    @_bind_canonical_issuer
    def _execution_issuance(self, context: Context, plan: dict, *, _issuer) -> dict:
        binding = self._context_binding(context)
        if binding != plan['binding']:
            raise Refusal('CURRENT_INPUT_CHANGED', context.step_id)
        body = {k: v for k, v in plan.items() if k != 'execution_issuance'}
        if context.route_receipt.get('kind') == 'neutral-test':
            return dict(kind='neutral-protocol-only', plan_digest=_hash(body))
        issued = _issuer()
        return dict(kind='canonical-controller-issuance',
                    invocation_id=issued['request']['invocation_id'],
                    request_digest=issued['request']['request_digest'],
                    route_digest=issued['route']['route_digest'],
                    source_sha=issued['route']['source_sha'],
                    source_blobs=issued['source_blobs'], plan_digest=_hash(body),
                    inputs=dict(binding['inputs']),
                    argv_digest=_hash({row['arm_id']: row['components'] for row in plan['portfolio']}),
                    implementation_digest=_hash({row['arm_id']: row['invocation_sources'] for row in plan['portfolio']}))

    def _verify_execution_issuance(self, context: Context, plan: dict) -> None:
        if plan.get('execution_issuance') != self._execution_issuance(context, plan):
            raise Refusal('CONTROLLER_ISSUANCE_CHANGED', context.step_id)

    @staticmethod
    def _authority_refusal(root: Path, exc: Refusal) -> dict:
        result = dict(status='REFUSED', reason=exc.code, detail=str(exc),
                      selected=None, candidate_statuses={})
        _write(root / 'refusal.json', result)
        # A later consumer refusal cannot replace the producer's measured
        # terminal verdict. Preserve its receipt and record this call separately.
        if not (root / 'result.json').exists():
            _write(root / 'result.json', result)
        return result

    def _measure_versions(self, context: Context) -> None:
        # Even a --version process waits for admission. Registry construction
        # only binds files; a caller-authored Context cannot start a tool there.
        self._context_binding(context)
        with self.registry._version_lock:
            for arm in self.registry.adapters(context.step_id):
                if arm.executable_receipts:
                    continue
                receipts = {}
                for invocation in arm.invocation_sources.values():
                    path = Path(invocation['executable'])
                    if str(path) in receipts:
                        continue
                    if digest(path) != arm.source_files[str(path)]:
                        raise Refusal('ADAPTER_SOURCE_MISMATCH', str(path))
                    try:
                        measured = subprocess.run([str(path), '--version'], capture_output=True,
                                                  text=True, timeout=2)
                    except (OSError, subprocess.SubprocessError) as exc:
                        raise Refusal('TOOL_VERSION_UNBOUND', str(path)) from exc
                    version = (measured.stdout + measured.stderr).strip()
                    if measured.returncode != 0 or not version:
                        raise Refusal('TOOL_VERSION_UNBOUND', str(path))
                    receipts[str(path)] = dict(executable_sha256=digest(path), version=version,
                                              argv=[str(path), '--version'], rc=measured.returncode)
                self.registry._adapters[arm.arm_id] = replace(
                    arm, executable_receipts=MappingProxyType(receipts))

    def _validate_live_portfolio(self, plan: Mapping[str, object] | None = None) -> None:
        _validate_portfolio(self.portfolio)
        if (plan is not None and not self.portfolio.get('meta', {}).get('test_only') and
                (plan.get('public_portfolio_sha256') != _hash(self.portfolio) or
                 plan.get('public_portfolio') != self.portfolio)):
            raise Refusal('PORTFOLIO_AUTHORITY_CHANGED', str(plan.get('step_id')))

    def _admission(self, adapter: Adapter, context: Context) -> str:
        if adapter.role != 'producer':
            return 'COMPLEMENTARY_CHECKER'
        if adapter.source_sha != context.source_sha:
            return 'WRONG_SOURCE'
        if adapter.applicability != 'applicable':
            return 'APPLICABILITY_' + adapter.applicability.upper()
        if not adapter.available:
            return 'UNAVAILABLE'
        # A source-bound component may be executed when its tool/input/image
        # is explicitly available, but registration alone never grants native
        # qualification.  Native qualification remains a separate receipt
        # fact and is represented by ``qualified=True`` only when bound.
        if adapter.license_id and self.budget.licenses.get(adapter.license_id, 0) < 1:
            return 'LICENSE_UNAVAILABLE'
        if (adapter.cpus > min(self.budget.cpus, len(os.sched_getaffinity(0))) or
                adapter.ram_mb > self.budget.ram_mb):
            return 'BUDGET_UNAVAILABLE'
        return 'READY' if adapter.qualified else 'READY_SOURCE_BOUND'

    @staticmethod
    def _provider_identity(adapter: Adapter) -> tuple:
        """Underlying entry closure; aliases and appended files add no engine."""
        identities = set()
        for component in adapter.components:
            invocation = _invocation_sources(component)
            identities.add((invocation['executable_sha256'],
                            tuple(sorted(invocation['implementation'].values()))))
        return tuple(sorted(identities))

    @staticmethod
    def acceptance_contract(context: Context, step: Mapping[str, object]) -> dict:
        """Return the immutable contract every candidate must satisfy.

        The contract is deliberately derived from the canonical step row and
        the live request.  It is carried in receipts by digest, so changing a
        gate, objective, or output obligation cannot reuse an older result.
        """
        return dict(step_id=context.step_id,
                    required_gates=list(context.required_gates),
                    required_output_contract=list(step['required_output_contract']),
                    objective=dict(context.objective))

    @staticmethod
    def _mode_intent(selected_mode: str) -> str:
        return 'ultra' if selected_mode == 'ultra-mode' else 'default'

    def plan(self, context: Context, execution_mode: str | None = None,
             superiority: Superiority | None = None, *, execution_root: Path | None = None) -> dict:
        # Only the canonical Context may expose Step9 fields before binding.
        # Its first plan closes preparation even when later authority fails.
        if type(context) is _require_context_type() and context.step_id == '9':
            with self.registry._version_lock:
                self.registry._step9_binding_closed = True
        self._validate_live_portfolio()
        binding = self._context_binding(context)
        route_mode = context.route_receipt.get('mode_intent')
        if (execution_mode is None and context.intent_label == 'USER_EXPLICIT_ULTRA'):
            selected_mode = 'ultra-mode'
        else:
            selected_mode = mode(execution_mode)
        # A routed production context may enter Ultra only with the typed
        # intent issued by the canonical front door. Neutral controller
        # fixtures retain their historical direct Ultra API for protocol-only
        # tests because they carry no production route receipt.
        if (selected_mode == 'ultra-mode' and
                context.route_receipt.get('kind') != 'neutral-test' and
                context.intent_label != 'USER_EXPLICIT_ULTRA'):
            raise Refusal('ULTRA_INTENT_MISSING', context.step_id)
        if (context.route_receipt.get('kind') == 'issued-route' and
                route_mode != self._mode_intent(selected_mode)):
            raise Refusal('ROUTE_INTENT_MISMATCH', context.step_id)
        step = next((s for s in self.portfolio['steps'] if s['id'] == context.step_id), None)
        if step is None:
            raise Refusal('UNKNOWN_CANONICAL_STEP', context.step_id)
        if not set(step['mandatory_gate_programs']).issubset(context.required_gates):
            raise Refusal('REQUIRED_GATES_DROPPED', context.step_id)
        self._measure_versions(context)
        adapters = self.registry.adapters(context.step_id)
        rows = [{**a.identity(), 'admission': self._admission(a, context),
                 'applicability': a.applicability,
                 'applicability_reason': a.applicability_reason,
                 'availability_reason': a.availability_reason,
                 'available': a.available, 'qualified': a.qualified,
                 'own_no_tool_reason': a.own_no_tool_reason,
                 'cpus': a.cpus, 'ram_mb': a.ram_mb,
                 'license_id': a.license_id} for a in adapters]
        ready = [a for a, row in zip(adapters, rows)
                 if row['admission'] in ('READY', 'READY_SOURCE_BOUND')]
        external = [a for a in adapters if a.role == 'producer' and a.tool_id != 'vibeic']
        own = [a for a in ready if a.tool_id == 'vibeic']
        # An unavailable, unknown or failed external producer is still suitable;
        # it cannot justify an own implementation. Incomplete portfolio coverage
        # is NOT proof of no external tool, so the explicit scoped reason is needed.
        if own and (any(a.applicability != 'inapplicable' for a in external) or
                    any(not a.own_no_tool_reason for a in own)):
            ready = [a for a in ready if a.tool_id != 'vibeic']
            for row in rows:
                if row['tool_id'] == 'vibeic' and row['admission'] in ('READY', 'READY_SOURCE_BOUND'):
                    row['admission'] = 'OWN_TOOL_NOT_JUSTIFIED'
        acceptance = self.acceptance_contract(context, step)
        common = dict(mode=selected_mode, mode_intent=self._mode_intent(selected_mode),
                      intent_label=context.intent_label, request_digest=context.request_digest,
                      binding=binding, acceptance=acceptance,
                      acceptance_digest=_hash(acceptance),
                      route_receipt=dict(context.route_receipt),
                      route_receipt_sha256=_hash(context.route_receipt)
                      if context.route_receipt else None)
        if not ready:
            return dict(**common, arms=[], portfolio=rows,
                        status='NOT_MEASURED', reason='NO_RUNNABLE_ADAPTER')
        if any(dict(a.objective) != dict(context.objective) and not (
                a.tool_id == 'frontend-worker' and
                a.objective.get('parameters_from') == 'issued_manifest') for a in ready):
            raise Refusal('UNEQUAL_OBJECTIVES', context.step_id)
        if any(not set(step['required_output_contract']).issubset(a.output_contract)
               for a in ready):
            raise Refusal('OUTPUT_CONTRACT_UNBOUND', context.step_id)
        def rank(arm):
            from execution_provider_catalog import python_entrypoint, RELEASE_IDS, BACKEND_IDS, coverage_rows
            family = ('execution_release_worker.py' if arm.step_id in RELEASE_IDS else
                      'execution_backend_worker.py' if arm.step_id in BACKEND_IDS else None)
            canonical = Path(__file__).resolve().parent / family if family else None
            direct = False
            if canonical is not None:
                try:
                    direct = all(python_entrypoint(c.argv, None) == canonical for c in arm.components)
                except ValueError:
                    pass
            canonical_id = next((r['arm_id'] for r in coverage_rows() if r['step_id'] == arm.step_id), None)
            return (0 if arm.tool_id == 'librelane' else
                    1 if arm.tool_id in ('openroad', 'openroad_fork') else
                    3 if arm.tool_id == 'vibeic' else 2,
                    0 if direct and arm.arm_id == canonical_id else 1 if direct else 2, arm.arm_id)
        ready.sort(key=rank)
        reason = 'APPLICABLE_AVAILABLE_QUALIFIED_PRIORITY'
        if selected_mode == 'default-mode':
            if superiority:
                preferred = next((a for a in ready if a.arm_id == superiority.preferred), None)
                reference = next((a for a in ready if a.arm_id == superiority.reference), None)
                if not preferred or not reference or reference != ready[0] or (
                        dict(superiority.binding) != binding or
                        superiority.direction not in ('min', 'max') or
                        superiority.direction != context.objective.get('direction') or
                        superiority.metric != context.objective.get('metric')):
                    raise Refusal('SUPERIORITY_UNBOUND', context.step_id)
                measured = []
                for arm in (preferred, reference):
                    path = superiority.receipts.get(arm.arm_id)
                    if not path:
                        raise Refusal('SUPERIORITY_UNMEASURED', arm.arm_id)
                    receipt = json.loads(Path(path).read_text())
                    if receipt.get('adapter') != arm.identity() or receipt.get('binding') != binding:
                        raise Refusal('SUPERIORITY_STALE', arm.arm_id)
                    if receipt.get('status') != 'ELIGIBLE':
                        raise Refusal('SUPERIORITY_UNMEASURED', arm.arm_id)
                    self._eligible(receipt, context, arm)
                    if asdict(arm.validate(Path(receipt['output_root']), binding)) != receipt['evidence']:
                        raise Refusal('SUPERIORITY_EVIDENCE_CHANGED', arm.arm_id)
                    value = receipt.get('evidence', {}).get('metrics', {}).get(superiority.metric)
                    if type(value) not in (int, float) or not math.isfinite(value):
                        raise Refusal('SUPERIORITY_UNMEASURED', arm.arm_id)
                    measured.append(value)
                better = measured[0] < measured[1] if superiority.direction == 'min' else measured[0] > measured[1]
                if not better:
                    raise Refusal('SUPERIORITY_NOT_PROVEN', context.step_id)
                ready = [preferred]
                reason = 'CURRENT_INPUT_MEASURED_SUPERIORITY'
            else:
                ready = ready[:1]
        # Only successful transparent proofs can exclude another producer.
        # Refused wrappers remain scoped arms so execution emits their receipts.
        identities = {}
        for arm in ready:
            cwd = execution_root / arm.arm_id / 'outputs' if execution_root else None
            try:
                identities[arm.arm_id] = _provider_identity(arm, cwd=cwd)
            except Refusal as exc:
                # The existing declaration check remains a terminal boundary.
                # New execution-proof failures stay visible and cannot dedup.
                from execution_provider_catalog import source_closure, implementation_closure
                for component in arm.components:
                    for token in component.argv[:2]:
                        path = Path(shutil.which(token) or token)
                        if path.is_absolute() and path.is_file():
                            declared = source_closure([path])
                            try:
                                actual = implementation_closure(path, cwd=cwd) if path.suffix == '.py' else {path}
                            except (ValueError, SyntaxError, OSError):
                                actual = {path}
                            for dependency in declared & actual:
                                if arm.source_files.get(str(dependency)) != digest(dependency):
                                    raise Refusal('PROVIDER_DEPENDENCY_UNBOUND', str(dependency))
                identities[arm.arm_id] = None
        cwd_exclusions = []
        if selected_mode == 'ultra-mode':
            distinct = []
            for arm in ready:
                identity = identities[arm.arm_id]
                if identity is not None and any(identities[a.arm_id] is not None and (
                        set(arm.engine_families) & set(a.engine_families) or
                        identity == identities[a.arm_id]) for a in distinct):
                    for row in rows:
                        if row['arm_id'] == arm.arm_id:
                            row['admission'] = 'SAME_ENGINE_FAMILY'
                    # A cwd-dependent arm may have appeared in a caller's
                    # preflight. Retain its runtime exclusion as a refusal
                    # receipt, with no execution or adoption authority.
                    from execution_provider_catalog import python_entrypoint
                    for component in arm.components:
                        try:
                            python_entrypoint(component.argv, None)
                        except ValueError as exc:
                            if 'execution cwd' in str(exc):
                                cwd_exclusions.append(arm.arm_id)
                                break
                    continue
                distinct.append(arm)
            ready = distinct
        return dict(**common,
                    arms=[a.arm_id for a in ready], portfolio=rows,
                    status='PLANNED', reason=reason, cwd_exclusions=cwd_exclusions,
                    independence={a.arm_id: {
                        'sha256': _hash(identities[a.arm_id]) if identities[a.arm_id] is not None else None,
                        'dispatch_proof': 'PROVEN' if identities[a.arm_id] is not None else 'REFUSED',
                        'declared_families': list(a.engine_families),
                        'scope': 'SOURCE_COMPONENT_CLOSURE',
                        'native_independence': 'NOT_MEASURED'} for a in ready})

    @_supervised
    def run(self, context: Context, output: Path, execution_mode: str | None = None,
            *, cancel: threading.Event | None = None,
            superiority: Superiority | None = None, _issue=None) -> dict:
        output = Path(output).resolve()
        try:
            output.mkdir(parents=True, exist_ok=False)
        except OSError as exc:
            raise Refusal('RUN_OUTPUT_UNAVAILABLE', str(output)) from exc
        run_id = uuid.uuid4().hex
        cancel = cancel or threading.Event()
        try:
            plan = self.plan(context, execution_mode, superiority, execution_root=output)
        except Refusal as exc:
            _write(output / 'refusal.json', dict(status='REFUSED', reason=exc.code,
                                               detail=str(exc), run_id=run_id,
                                               portfolio=self.portfolio))
            if exc.code in ('CONTROLLER_ISSUANCE_REQUIRED', 'CONTEXT_IMPLEMENTATION_UNTRUSTED'):
                return self._authority_refusal(output, exc)
            raise
        plan.update(run_id=run_id, budget=asdict(self.budget),
                    public_portfolio=self.portfolio,
                    public_portfolio_sha256=_hash(self.portfolio),
                    run_root=str(output),
                    superiority=None if superiority is None else {
                        **asdict(superiority),
                        'receipts': {k: str(v) for k, v in superiority.receipts.items()}})
        frozen = dict(schema=1, run_id=run_id, step_id=context.step_id,
                      ic_ip_path=context.ic_ip_path,
                      intent_label=context.intent_label,
                      request_digest=context.request_digest,
                      source_sha=context.source_sha,
                      input_digest=_hash(plan['binding']['inputs']),
                      input_manifest=dict(plan['binding']['inputs']),
                      objective_digest=_hash(plan['binding']['objective']),
                      acceptance_digest=plan['acceptance_digest'],
                      acceptance=plan['acceptance'],
                      route_receipt=plan['route_receipt'],
                      route_receipt_sha256=plan['route_receipt_sha256'],
                      mode_intent=plan['mode_intent'])
        _write(output / 'frozen-work.json', frozen)
        plan['frozen_work_digest'] = digest(output / 'frozen-work.json')
        manifest_payload = _issued_manifest_payload(context)
        plan.update(issued_manifest_payload=manifest_payload,
                    issued_manifest_sha256=_issued_manifest_digest(manifest_payload))
        plan['execution_issuance'] = self._execution_issuance(context, plan)
        _write(output / 'plan.json', plan)
        _write(output / 'issued-plan.json', _issue_sealed(output / 'issued-plan.json', plan))
        for arm_id in plan.get('cwd_exclusions', ()):
            _write(output / arm_id / 'receipt.json', {
                'run_id': run_id, 'arm_id': arm_id, 'status': 'REFUSED',
                'reason': 'SAME_ENGINE_FAMILY', 'processes': [],
                'dispatch_proof': 'PROVEN', 'adoption_authority': 'NONE'})
        if not plan['arms']:
            comparison = self._comparison_receipt(output, plan, {})
            _write(output / 'result.json', plan)
            return plan
        arms = {a.arm_id: a for a in self.registry.adapters(context.step_id)}
        condition = threading.Condition()
        usage = {'cpus': 0, 'ram_mb': 0, 'licenses': {}}
        available_cpus = set(os.sched_getaffinity(0))
        wait_deadline = time.monotonic() + 1 + sum(
            c.timeout_s for i in plan['arms'] for c in arms[i].components)

        def work(arm: Adapter):
            with condition:
                admission = self._admission(arm, context)
                if admission not in ('READY', 'READY_SOURCE_BOUND'):
                    return self._run_arm(arm, context, plan, output, cancel,
                                         _issue=_issue, start_refusal=admission)
                def fits():
                    return (len(available_cpus) >= arm.cpus and
                            usage['cpus'] + arm.cpus <= self.budget.cpus and
                            usage['ram_mb'] + arm.ram_mb <= self.budget.ram_mb and
                            (not arm.license_id or usage['licenses'].get(arm.license_id, 0) <
                             self.budget.licenses[arm.license_id]))
                while not fits() and not cancel.is_set():
                    if time.monotonic() >= wait_deadline:
                        return self._run_arm(arm, context, plan, output, cancel,
                                             _issue=_issue, start_refusal='RESOURCE_WAIT_DEADLINE')
                    condition.wait(min(.02, max(0, wait_deadline - time.monotonic())))
                if not cancel.is_set():
                    usage['cpus'] += arm.cpus
                    usage['ram_mb'] += arm.ram_mb
                    if arm.license_id:
                        usage['licenses'][arm.license_id] = usage['licenses'].get(arm.license_id, 0) + 1
                    cpuset = sorted(available_cpus)[:arm.cpus]
                    available_cpus.difference_update(cpuset)
                else:
                    return self._run_arm(arm, context, plan, output, cancel, _issue=_issue)
            try:
                return self._run_arm(arm, context, plan, output, cancel, cpuset, _issue=_issue)
            finally:
                with condition:
                    usage['cpus'] -= arm.cpus
                    usage['ram_mb'] -= arm.ram_mb
                    if arm.license_id:
                        usage['licenses'][arm.license_id] -= 1
                    available_cpus.update(cpuset)
                    condition.notify_all()

        receipts = {}
        with ThreadPoolExecutor(max_workers=self.budget.workers) as pool:
            futures = {pool.submit(work, arms[i]): i for i in plan['arms']}
            for future in as_completed(futures):
                receipts[futures[future]] = future.result()
        comparison = self._comparison_receipt(output, plan, receipts)
        candidate_statuses = {i: r['status'] for i, r in receipts.items()}
        if plan['mode'] == 'default-mode':
            # Default is program-selected: the planner has already admitted
            # exactly one priority arm. A sole eligible result follows the
            # same sealed adoption chain, with a controller-issued choice
            # witness so no AI choice file or review callback is required.
            eligible = comparison['eligible_arms']
            if len(plan['arms']) != 1:
                raise Refusal('DEFAULT_ARM_CARDINALITY', context.step_id)
            if len(eligible) == 1:
                arm_id = eligible[0]['arm_id']
                choice = dict(arm_id=arm_id,
                              binding=plan['binding'],
                              receipt_sha256=eligible[0]['receipt_sha256'],
                              reviewer='program-default-controller',
                              rationale='Planner priority selected the sole default arm.')
                try:
                    adopted = self.adopt(context, output, choice,
                                         _candidate_statuses=candidate_statuses)
                except Refusal as exc:
                    refusal = json.loads((output / 'adoption.json').read_text())
                    refusal.update(candidate_statuses=candidate_statuses,
                                   mode=plan['mode'], mode_intent=plan['mode_intent'],
                                   selected=None, reason=exc.code)
                    _write(output / 'result.json', refusal)
                    return refusal
                _write(output / 'result.json', adopted)
                return adopted
            # A measured failure or an unavailable result remains terminal and
            # cannot be promoted into adoption by the default path.
            status = candidate_statuses.get(plan['arms'][0], 'NOT_MEASURED')
            summary = dict(run_id=run_id, status=status, candidate_statuses=candidate_statuses,
                           mode=plan['mode'], mode_intent=plan['mode_intent'], selected=None,
                           frozen_work_digest=plan['frozen_work_digest'],
                           comparison_digest=comparison['digest'])
            _write(output / 'result.json', summary)
            return summary
        terminal_status = ('FAIL' if 'FAIL' in candidate_statuses.values()
                           else ('AWAITING_AI_SELECTION' if comparison['eligible_arms']
                                 else 'NOT_MEASURED'))
        summary = dict(run_id=run_id,
                       status=terminal_status,
                       candidate_statuses=candidate_statuses,
                       mode=plan['mode'], mode_intent=plan['mode_intent'], selected=None,
                       frozen_work_digest=plan['frozen_work_digest'],
                       comparison_digest=comparison['digest'])
        _write(output / 'result.json', summary)
        return summary

    def _objective_winner(self, plan: dict, root: Path, eligible: list[dict],
                          context: Context) -> str | None:
        """Return the deterministic objective winner among current eligible arms."""
        objective = plan.get('acceptance', {}).get('objective') or {}
        metric = objective.get('metric')
        direction = objective.get('direction')
        order = {arm_id: index for index, arm_id in enumerate(plan.get('arms', []))}
        values = []
        for row in eligible:
            arm_id = row.get('arm_id')
            try:
                receipt_path = root / str(arm_id) / 'receipt.json'
                if digest(receipt_path) != row.get('receipt_sha256'):
                    raise Refusal('ARM_RECEIPT_DIGEST_MISMATCH', str(arm_id))
                receipt = json.loads(receipt_path.read_text())
                value = (receipt.get('evidence') or {}).get('metrics', {}).get(metric)
            except (OSError, ValueError, TypeError):
                raise Refusal('OBJECTIVE_EVIDENCE_INVALID', str(arm_id))
            arm = next((candidate for candidate in self.registry.adapters(context.step_id)
                        if candidate.arm_id == arm_id), None)
            if arm is None:
                raise Refusal('OBJECTIVE_EVIDENCE_INVALID', str(arm_id))
            self._eligible(receipt, context, arm)
            if type(value) not in (int, float) or not math.isfinite(value):
                raise Refusal('OBJECTIVE_EVIDENCE_INVALID', str(arm_id))
            values.append((value, order.get(arm_id, len(order)), arm_id))
        if not values:
            return None
        if direction == 'min':
            return min(values, key=lambda item: (item[0], item[1]))[2]
        if direction == 'max':
            return max(values, key=lambda item: (item[0], -item[1]))[2]
        raise Refusal('OBJECTIVE_INVALID', str(direction))

    @staticmethod
    def _comparison_receipt(root: Path, plan: dict, receipts: Mapping[str, dict]) -> dict:
        """Issue a complete, ordered comparison over this run's arm set.

        The comparison is descriptive until an explicit AI choice arrives.  A
        missing or edited arm cannot disappear from the ordered set without
        making adoption refuse.
        """
        ordered = []
        eligible = []
        for arm_id in plan['arms']:
            path = root / arm_id / 'receipt.json'
            if not path.is_file():
                ordered.append(dict(arm_id=arm_id, receipt_sha256=None, status='NOT_MEASURED'))
                continue
            observed = receipts.get(arm_id)
            if observed is None:
                observed = json.loads(path.read_text())
            sha = digest(path)
            item = dict(arm_id=arm_id, receipt_sha256=sha,
                        status=observed.get('status', 'NOT_MEASURED'))
            ordered.append(item)
            if item['status'] == 'ELIGIBLE':
                eligible.append(dict(arm_id=arm_id, receipt_sha256=sha))
        comparison = dict(schema=1, run_id=plan['run_id'], step_id=plan['binding']['step_id'],
                          frozen_work_digest=plan['frozen_work_digest'],
                          mode_intent=plan['mode_intent'], intent_label=plan['intent_label'],
                          request_digest=plan['request_digest'],
                          arm_receipts=ordered, eligible_arms=eligible,
                          selection_criterion=dict(objective=plan['acceptance']['objective'],
                                                   eligible_only=True,
                                                   ordered_by='objective.metric',
                                                   tie_break='plan.arm_order'),
                          status=('FAIL' if any(item['status'] == 'FAIL' for item in ordered)
                                  else ('AWAITING_AI_SELECTION'
                                        if plan['mode'] == 'ultra-mode' and eligible
                                        else ('PROGRAM_DEFAULT_READY' if eligible else 'NOT_MEASURED'))))
        _write(root / 'comparison.json', comparison)
        _write(root / 'issued-comparison.json', _issue_sealed(root / 'issued-comparison.json', comparison))
        comparison['digest'] = digest(root / 'comparison.json')
        return comparison

    def _run_arm(self, arm: Adapter, context: Context, plan: dict, root: Path,
                 cancel: threading.Event, cpuset: list[int] | None = None,
                 *, _issue=None, start_refusal: str | None = None) -> dict:
        if _issue is None:
            raise Refusal('ISSUED_AUTHORITY_UNAVAILABLE', 'arm execution outside Controller.run')
        directory = root / arm.arm_id
        try:
            directory.mkdir()
        except OSError as exc:
            raise Refusal('ARM_OUTPUT_UNAVAILABLE', str(directory)) from exc
        inputs, outputs = directory / 'inputs', directory / 'outputs'
        inputs.mkdir(); outputs.mkdir()
        receipt = dict(run_id=plan['run_id'], arm_id=arm.arm_id,
                       adapter=arm.identity(), binding=plan['binding'],
                       frozen_work_digest=plan['frozen_work_digest'],
                       intent_label=plan['intent_label'], request_digest=plan['request_digest'],
                       executor=dict(tool_id=arm.tool_id, tool_version=arm.tool_version,
                                     source_sha=arm.source_sha),
                       engine_source_families=list(arm.engine_families),
                       resource_facts=dict(cpus=arm.cpus, ram_mb=arm.ram_mb,
                                           budget=asdict(self.budget), cpuset=cpuset),
                       admission=next((row for row in plan['portfolio']
                                       if row.get('arm_id') == arm.arm_id), {}),
                       output_root=str(outputs), input_root=str(inputs),
                       status='NOT_MEASURED', reason='NOT_STARTED', processes=[],
                       evidence=None, manifest_payload=None, manifest_sha256=None,
                       producer_chain=None, execution_closure=None,
                       started_ns=time.monotonic_ns())
        def frozen_binding():
            actual = {str(p.relative_to(inputs)): digest(p) for p in inputs.rglob('*')
                      if p.is_file() and p != issued_manifest_path(inputs)}
            if (not is_exclusive_regular(issued_manifest_path(inputs)) or
                    any(p.is_file() and not is_exclusive_regular(p) for p in inputs.rglob('*')) or
                    actual != plan['binding']['inputs'] or any(p.is_symlink() for p in inputs.rglob('*'))):
                raise Refusal('FROZEN_INPUT_CHANGED', arm.arm_id)
        try:
            if start_refusal:
                raise Refusal(start_refusal, arm.arm_id)
            self._verify_execution_issuance(context, plan)
            if self._context_binding(context) != plan['binding']:
                raise Refusal('CURRENT_INPUT_CHANGED', arm.arm_id)
            targets = set()
            for name in context.inputs:
                target = inputs / _relative(name)
                authority = issued_manifest_path(inputs)
                if target == authority or authority in target.parents:
                    raise Refusal('RESERVED_INPUT_PATH', name)
                if target in targets:
                    raise Refusal('DUPLICATE_INPUT_PATH', name)
                targets.add(target)
            for name, source in context.inputs.items():
                target = inputs / _relative(name)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
                target.chmod(0o444)
            # Bind the worker's typed route and parameters to the exact frozen
            # input copy.  This manifest is metadata, not a mutable project
            # input, and is excluded from the byte-for-byte frozen census.
            manifest = issued_manifest_path(inputs)
            manifest_payload = plan.get('issued_manifest_payload')
            manifest_sha256 = plan.get('issued_manifest_sha256')
            if (not isinstance(manifest_payload, dict) or
                    manifest_payload != _issued_manifest_payload(context) or
                    manifest_sha256 != _issued_manifest_digest(manifest_payload)):
                raise Refusal('ISSUED_MANIFEST_PLAN_MISMATCH', arm.arm_id)
            manifest.write_bytes(_issued_manifest_bytes(manifest_payload))
            manifest.chmod(0o444)
            receipt['manifest_payload'] = manifest_payload
            receipt['manifest_sha256'] = digest(manifest)
            if receipt['manifest_sha256'] != manifest_sha256:
                raise Refusal('ISSUED_MANIFEST_DIGEST_MISMATCH', arm.arm_id)
            frozen_binding()
            for component in arm.components:
                if cancel.is_set():
                    raise Refusal('CANCELLED', arm.arm_id)
                closure = self._source_current(arm, outputs)
                if receipt['execution_closure'] is not None and receipt['execution_closure'] != closure:
                    raise Refusal('PROVIDER_CLOSURE_CHANGED', arm.arm_id)
                receipt['execution_closure'] = closure
                self._verify_execution_issuance(context, plan)
                frozen_binding()
                argv = [v.replace('{inputs}', str(inputs)).replace('{outputs}', str(outputs))
                        for v in component.argv]
                executable = shutil.which(argv[0])
                if not executable or str(Path(executable).resolve()) not in arm.source_files:
                    raise Refusal('EXECUTABLE_UNBOUND', argv[0])
                argv[0] = str(Path(executable).resolve())
                record = dict(component=component.name, argv=argv, rc=None,
                              executable_path=argv[0],
                              executable_sha256=digest(Path(argv[0])),
                              started_ns=time.monotonic_ns())
                receipt['processes'].append(record)
                stdout = directory / (component.name + '.stdout')
                stderr = directory / (component.name + '.stderr')
                # A separate Python launcher sets rlimits/affinity before exec.
                # No preexec_fn in a threaded parent (which can deadlock).
                launcher = ("import os,resource,sys; "
                            "resource.setrlimit(resource.RLIMIT_AS,(int(sys.argv[1]),int(sys.argv[1]))); "
                            "os.sched_setaffinity(0,set(map(int,sys.argv[2].split(',')))); "
                            "os.execvpe(sys.argv[3],sys.argv[3:],os.environ)")
                import sys
                cpuset = cpuset or sorted(os.sched_getaffinity(0))[:arm.cpus]
                child_env = {**os.environ, 'OMP_NUM_THREADS': str(arm.cpus),
                             'OPENBLAS_NUM_THREADS': str(arm.cpus),
                             'VIBEIC_EXECUTION_BINDING': json.dumps(plan['binding']),
                             'VIBEIC_ARM_ID': arm.arm_id}
                child_env.update(_python_cache_policy(outputs))
                child_env.pop('VIBEIC_STEP37_ROUTE', None)
                if arm.step_id == '37':
                    params = json.loads(component.argv[component.argv.index('--params-json') + 1])
                    route = params.get('streamout_route')
                    if route != 'librelane' or arm.arm_id != 'backend_37_' + route:
                        raise Refusal('BACKEND_STEP37_ROUTE_UNBOUND', arm.arm_id)
                    child_env['VIBEIC_STEP37_ROUTE'] = route
                record['issued_environment'] = {k: child_env[k] for k in
                    ('VIBEIC_ARM_ID', 'VIBEIC_STEP37_ROUTE',
                     'PYTHONPYCACHEPREFIX', 'PYTHONDONTWRITEBYTECODE') if k in child_env}
                with stdout.open('wb') as out, stderr.open('wb') as err:
                    child_env['VIBEIC_ISSUED_MANIFEST_SHA256'] = receipt['manifest_sha256']
                    child_env[ISSUED_MANIFEST_ENV] = str(manifest)
                    child_env['VIBEIC_MANIFEST_SHA256'] = receipt['manifest_sha256']
                    worker = str(Path(__file__).with_name('execution_frontend_worker.py').resolve())
                    if (arm.step_id in ('0.5ic', 'D1') and len(argv) == 8 and
                            argv[1:] == [worker, '--step', arm.step_id, '--inputs',
                                         str(inputs), '--outputs', str(outputs)]):
                        process = _IssuedFrontendProcess(
                            root / 'issued-plan.json', arm, component, argv,
                            outputs, out, err, child_env, cpuset)
                    else:
                        process = subprocess.Popen(
                            [sys.executable, '-c', launcher, str(arm.ram_mb * 1024 * 1024),
                             ','.join(map(str, cpuset)), *argv],
                            cwd=outputs, stdout=out, stderr=err, start_new_session=True,
                            env=child_env)
                    record['pid'] = process.pid
                    stop = None
                    try:
                        deadline = time.monotonic() + component.timeout_s
                        while process.poll() is None:
                            if cancel.is_set() or time.monotonic() >= deadline:
                                stop = 'CANCELLED' if cancel.is_set() else 'DEADLINE'
                                break
                            time.sleep(.01)
                    finally:
                        # Reap this component's process group, including any
                        # residual descendants after a parent exits normally.
                        try:
                            os.killpg(process.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                        process.wait()
                    record.update(rc=process.returncode, ended_ns=time.monotonic_ns(),
                                  stdout=str(stdout), stderr=str(stderr),
                                  stdout_sha256=digest(stdout), stderr_sha256=digest(stderr),
                                  stop_reason=stop)
                if stop:
                    raise Refusal(stop, component.name)
                if record['rc'] != 0:
                    raise Refusal('PROCESS_ERROR', f'{component.name}: rc={record["rc"]}')
                frozen_binding()
            if self._source_current(arm, outputs) != receipt['execution_closure']:
                raise Refusal('PROVIDER_CLOSURE_CHANGED', arm.arm_id)
            evidence = arm.validate(outputs, plan['binding'])
            receipt['evidence'] = asdict(evidence)
            receipt['status'] = evidence.verdict
            receipt['reason'] = 'ADAPTER_EVIDENCE'
            output_digest = _hash(receipt['evidence'].get('outputs', {}))
            receipt['gate_receipts'] = {
                process['component']: dict(
                    gate=process['component'], argv=list(process['argv']),
                    argv_sha256=_hash(process['argv']),
                    executable_path=process.get('executable_path'),
                    executable_sha256=process.get('executable_sha256'),
                    source_sha=arm.source_sha, tool_id=arm.tool_id,
                    tool_version=arm.tool_version,
                    source_manifest_sha256=_hash(dict(arm.source_files)),
                    inputs=dict(plan['binding']['inputs']), rc=process['rc'],
                    output_digest=output_digest)
                for process in receipt['processes']
            }
            composite = evidence.provenance.get('composite_gate_execution')
            if composite:
                worker = next((p for p in receipt['processes']
                               if p['component'] == composite.get('worker_component')), None)
                groups = composite.get('gate_records', {})
                if worker is None or set(groups) != set(plan['binding']['required_gates']):
                    raise Refusal('GATE_EXECUTION_UNBOUND', arm.arm_id)
                for gate, records in groups.items():
                    if gate in receipt['gate_receipts']:
                        raise Refusal('GATE_EXECUTION_UNBOUND', gate)
                    receipt['gate_receipts'][gate] = dict(
                        gate=gate, observation='canonical-composite',
                        argv=list(worker['argv']), argv_sha256=_hash(worker['argv']),
                        executable_path=worker['executable_path'],
                        executable_sha256=worker['executable_sha256'],
                        source_sha=arm.source_sha, tool_id=arm.tool_id,
                        tool_version=arm.tool_version,
                        source_manifest_sha256=_hash(dict(arm.source_files)),
                        inputs=dict(plan['binding']['inputs']), rc=worker['rc'],
                        output_digest=output_digest, nested_worker_component=worker['component'],
                        typed_receipt_name=composite['receipt_name'],
                        typed_receipt_sha256=composite['receipt_sha256'],
                        nested_record_sha256=_hash(records))
            nested_records = evidence.provenance.get('nested_gate_records', ())
            if nested_records:
                # Composite fixed-step adapters may expose gates run by their
                # single source-bound worker. The adapter validator binds the
                # exact command/record bytes; eligibility below additionally
                # binds these rows to that observed worker process.
                for nested in nested_records:
                    gate = nested.get('gate')
                    if not isinstance(gate, str) or gate in receipt['gate_receipts']:
                        raise Refusal('GATE_EXECUTION_UNBOUND', str(gate))
                    argv = nested.get('command')
                    receipt['gate_receipts'][gate] = dict(
                        gate=gate, argv=argv, argv_sha256=_hash(argv),
                        executable_path=argv[0] if isinstance(argv, list) and argv else None,
                        executable_sha256=digest(Path(argv[0])) if isinstance(argv, list) and argv and
                            Path(argv[0]).is_file() else None,
                        source_sha=arm.source_sha, tool_id=arm.tool_id,
                        tool_version=arm.tool_version,
                        source_manifest_sha256=_hash(dict(arm.source_files)),
                        inputs=dict(plan['binding']['inputs']), rc=nested.get('rc'),
                        output_digest=output_digest,
                        nested_worker_component=nested.get('worker_component'),
                        nested_record_sha256=_hash(nested))
            if arm.step_id == '0.5ic' and arm.tool_id == 'frontend-worker':
                receipt['producer_chain'] = evidence.provenance.get('producer_chain')
            self._eligible(receipt, context, arm)
            receipt['status'] = 'ELIGIBLE'
        except Refusal as exc:
            receipt.update(status='FAIL' if exc.code == 'GATE_FAIL' else 'NOT_MEASURED',
                           reason=exc.code, detail=str(exc))
        except Exception as exc:
            receipt.update(status='NOT_MEASURED', reason='ADAPTER_ERROR', detail=repr(exc))
        receipt['ended_ns'] = time.monotonic_ns()
        receipt['honest_verdict'] = receipt['status']
        receipt['outputs'] = (receipt.get('evidence') or {}).get('outputs', {})
        # This completion is issued from observed Popen.wait results. Gate
        # evidence remains separately reconsumed; a source-issued process rc0
        # does not grant PASS or replace a failed/unmeasured output consumer.
        completion = {k: receipt[k] for k in ('run_id', 'arm_id', 'binding',
                      'adapter', 'processes', 'input_root', 'output_root')}
        completion['evidence'] = receipt.get('evidence')
        completion['gate_receipts'] = receipt.get('gate_receipts')
        completion.update({k: receipt[k] for k in ('manifest_payload', 'manifest_sha256', 'producer_chain')})
        completion['execution_closure'] = receipt['execution_closure']
        completion.update(actual_status=receipt['status'], actual_reason=receipt['reason'],
                          evidence=receipt.get('evidence'),
                          ended_ns=receipt['ended_ns'], run_root=str(root))
        _write(directory / 'issued-completion.json', _issue_sealed(directory / 'issued-completion.json', completion))
        _write(directory / 'receipt.json', receipt)
        return receipt

    @staticmethod
    def _execution_authority(root: Path, plan: dict, receipt: dict, arm: Adapter) -> None:
        issued_plan = _issued(root / 'issued-plan.json')
        if issued_plan != plan or plan.get('run_root') != str(root):
            raise Refusal('ISSUED_PLAN_MISMATCH', arm.arm_id)
        completion = _issued(root / arm.arm_id / 'issued-completion.json')
        fields = ('run_id', 'arm_id', 'binding', 'adapter', 'processes', 'input_root', 'output_root',
                  'manifest_payload', 'manifest_sha256', 'producer_chain', 'execution_closure')
        if (completion.get('run_root') != str(root) or
                completion.get('run_id') != plan['run_id'] or
                completion.get('manifest_payload') != plan.get('issued_manifest_payload') or
                completion.get('manifest_sha256') != plan.get('issued_manifest_sha256') or
                any(completion.get(k) != receipt.get(k) for k in fields)):
            raise Refusal('EXECUTION_AUTHORITY_MISMATCH', arm.arm_id)
        processes = completion['processes']
        if len(processes) != len(arm.components) or any(
                p.get('rc') != 0 or p.get('stop_reason') or not p.get('pid') or
                not p.get('ended_ns') for p in processes):
            raise Refusal('ISSUED_EXECUTION_INCOMPLETE', arm.arm_id)
        if (completion.get('evidence') != receipt.get('evidence') or
                completion.get('gate_receipts') != receipt.get('gate_receipts')):
            raise Refusal('EVIDENCE_CHANGED', arm.arm_id)

    def _current_admission(self, context: Context, plan: dict, arm: Adapter) -> None:
        if self._admission(arm, context) not in ('READY', 'READY_SOURCE_BOUND'):
            raise Refusal('CURRENT_ADMISSION_REJECTED', arm.arm_id)
        override = plan.get('superiority')
        if override:
            override = Superiority(**{**override, 'receipts': {
                k: Path(v) for k, v in override['receipts'].items()}})
        current = self.plan(context, plan['mode'], override, execution_root=Path(plan['run_root']))
        if arm.arm_id not in current['arms']:
            raise Refusal('CURRENT_POLICY_REJECTED', arm.arm_id)

    def _verify_receipt_chain(self, root: Path, plan: dict, context: Context) -> dict:
        self._validate_live_portfolio(plan)
        self._verify_execution_issuance(context, plan)
        frozen_path = root / 'frozen-work.json'
        comparison_path = root / 'comparison.json'
        if not frozen_path.is_file() or not comparison_path.is_file():
            raise Refusal('RECEIPT_CHAIN_INCOMPLETE', plan.get('run_id', ''))
        if digest(frozen_path) != plan.get('frozen_work_digest'):
            raise Refusal('FROZEN_WORK_DIGEST_MISMATCH', str(frozen_path))
        frozen = json.loads(frozen_path.read_text())
        if (frozen.get('run_id') != plan.get('run_id') or
                frozen.get('step_id') != context.step_id or
                frozen.get('source_sha') != context.source_sha or
                frozen.get('mode_intent') != plan.get('mode_intent') or
                frozen.get('intent_label') != plan.get('intent_label') or
                frozen.get('request_digest') != plan.get('request_digest') or
                frozen.get('acceptance_digest') != plan.get('acceptance_digest') or
                frozen.get('input_manifest') != plan['binding'].get('inputs')):
            raise Refusal('FROZEN_WORK_UNBOUND', context.step_id)
        if self._context_binding(context) != plan.get('binding'):
            raise Refusal('CURRENT_INPUT_CHANGED', context.step_id)
        try:
            issued_comparison = _issued(root / 'issued-comparison.json')
        except Refusal as exc:
            raise Refusal('COMPARISON_AUTHORITY_INVALID', str(exc)) from exc
        comparison = json.loads(comparison_path.read_text())
        if issued_comparison != comparison:
            raise Refusal('COMPARISON_AUTHORITY_CHANGED', context.step_id)
        if (comparison.get('run_id') != plan.get('run_id') or
                comparison.get('frozen_work_digest') != plan.get('frozen_work_digest') or
                comparison.get('mode_intent') != plan.get('mode_intent') or
                comparison.get('intent_label') != plan.get('intent_label') or
                comparison.get('request_digest') != plan.get('request_digest')):
            raise Refusal('COMPARISON_UNBOUND', context.step_id)
        rows = comparison.get('arm_receipts')
        if not isinstance(rows, list) or [row.get('arm_id') for row in rows] != plan.get('arms'):
            raise Refusal('INCOMPLETE_ARM_SET', context.step_id)
        eligible = []
        for row in rows:
            arm_id = row.get('arm_id')
            receipt_path = root / str(arm_id) / 'receipt.json'
            if not receipt_path.is_file():
                raise Refusal('INCOMPLETE_ARM_SET', str(arm_id))
            observed = json.loads(receipt_path.read_text())
            if digest(receipt_path) != row.get('receipt_sha256'):
                if observed.get('status') == 'ELIGIBLE' and row.get('status') != 'ELIGIBLE':
                    raise Refusal('EVIDENCE_CHANGED', str(arm_id))
                raise Refusal('ARM_RECEIPT_DIGEST_MISMATCH', str(arm_id))
            if observed.get('status') == 'ELIGIBLE':
                eligible.append(dict(arm_id=arm_id, receipt_sha256=row['receipt_sha256']))
            elif row.get('status') == 'ELIGIBLE':
                raise Refusal('COMPARISON_ELIGIBILITY_CHANGED', str(arm_id))
        if comparison.get('eligible_arms') != eligible:
            raise Refusal('INCOMPLETE_ARM_SET', context.step_id)
        if (comparison.get('status') == 'FAIL' and
                any(row.get('status') == 'FAIL' for row in rows)):
            raise Refusal('GATE_FAIL', context.step_id)
        return dict(frozen=frozen, comparison=comparison,
                    comparison_digest=digest(comparison_path), eligible=eligible)

    @staticmethod
    def _selected_generation(root: Path, receipt: dict, _issue) -> dict:
        parent = root / 'selected'
        if parent.is_symlink():
            raise Refusal('SELECTED_NAMESPACE_UNSAFE', str(parent))
        parent.mkdir(exist_ok=True)
        generation = uuid.uuid4().hex
        target = parent / generation
        target.mkdir()
        try:
            hashes = receipt['evidence']['outputs']
            for name, expected in hashes.items():
                source = Path(receipt['output_root']) / _relative(name)
                content = source.read_bytes()
                if hashlib.sha256(content).hexdigest() != expected:
                    raise Refusal('SELECTED_ARTIFACT_CHANGED', name)
                dest = target / _relative(name)
                write_bytes(dest, content)
                dest.chmod(0o444)
            manifest = dict(generation=generation, directory=str(target), status='PROVISIONAL',
                            run_id=receipt['run_id'], arm_id=receipt['arm_id'],
                            binding=receipt['binding'], outputs=hashes)
            if receipt.get('producer_chain') is not None:
                manifest['producer_chain_sha256'] = _hash(receipt['producer_chain'])
            _write(target / 'manifest.json', _issue(target / 'manifest.json', json.dumps(manifest)))
            return manifest
        except Exception:
            _issue(target / 'manifest.json', None)
            shutil.rmtree(target)
            raise

    @staticmethod
    def _discard_generation(root: Path, generation: dict | None, _issue) -> dict | None:
        if generation is None:
            return None
        directory = Path(generation['directory'])
        if directory.parent != root / 'selected' or directory.name != generation['generation']:
            raise Refusal('SELECTED_NAMESPACE_UNSAFE', str(directory))
        # Revoke before removing files; restoring a valid signature cannot
        # resurrect this supervisor's rejected generation. Older commits stay.
        _issue(directory / 'manifest.json', None)
        shutil.rmtree(directory)
        return dict(generation=generation['generation'], directory=str(directory),
                    status='INVALIDATED', authority='REVOKED', removed=True)

    @staticmethod
    def _commit_generation(generation: dict, _issue) -> dict:
        Controller._generation_current(generation)
        committed = dict(generation, status='ADOPTED')
        path = Path(generation['directory']) / 'manifest.json'
        _issue(path, None)
        _issue(path, json.dumps(committed))
        _write(path, _issue_sealed(path, committed))
        return committed

    @staticmethod
    def _generation_current(generation: dict) -> None:
        directory = Path(generation['directory'])
        if _issued(directory / 'manifest.json') != generation:
            raise Refusal('SELECTED_MANIFEST_CHANGED', generation['generation'])
        for name, expected in generation['outputs'].items():
            path = directory / _relative(name)
            if path.is_symlink() or not path.is_file() or digest(path) != expected:
                raise Refusal('SELECTED_GENERATION_CHANGED', name)

    @staticmethod
    def _source_current(arm: Adapter, cwd: Path | None = None) -> dict:
        for name, blob in arm.verified_source_blobs.items():
            if _blob_bytes(Path(name)) != blob:
                raise Refusal('ADAPTER_SOURCE_MISMATCH', name)
        for name, expected in arm.source_files.items():
            path = Path(name)
            if not path.is_file() or path.is_symlink() or digest(path) != expected:
                raise Refusal('ADAPTER_SOURCE_MISMATCH', name)
        for component in arm.components:
            if arm.invocation_sources.get(component.name) != _invocation_sources(component):
                raise Refusal('ENTRY_SOURCE_CHANGED', component.name)
        # Re-resolve the closure at execution and adoption, including newly
        # introduced helpers. Registration and cached import paths are not
        # authority for today's executed source bytes.
        return _provider_identity(arm, cwd=cwd, include_execution=True)[2]

    def _eligible(self, receipt: dict, context: Context, arm: Adapter) -> None:
        binding = self._context_binding(context)
        if (receipt.get('binding') != binding or receipt.get('adapter') != arm.identity() or
                receipt.get('intent_label') != context.intent_label or
                receipt.get('request_digest') != context.request_digest):
            raise Refusal('STALE_OR_UNBOUND_RECEIPT', arm.arm_id)
        if Controller._source_current(arm, Path(receipt['output_root'])) != receipt.get('execution_closure'):
            raise Refusal('PROVIDER_CLOSURE_CHANGED', arm.arm_id)
        processes = receipt.get('processes', [])
        if len(processes) != len(arm.components) or any(
                p.get('rc') != 0 or p.get('stop_reason') or not p.get('pid') or
                not p.get('ended_ns') for p in processes):
            raise Refusal('PROCESS_NOT_COMPLETE', arm.arm_id)
        for process in processes:
            _python_cache_policy(Path(receipt['output_root']), process)
            for channel in ('stdout', 'stderr'):
                p = Path(process[channel])
                if not p.is_file() or digest(p) != process[channel + '_sha256']:
                    raise Refusal('PROCESS_LOG_CHANGED', arm.arm_id)
        frozen = Path(receipt['input_root'])
        manifest = issued_manifest_path(frozen)
        if manifest.is_symlink() or (manifest.is_file() and not is_exclusive_regular(manifest)):
            raise Refusal('FROZEN_INPUT_CHANGED', arm.arm_id)
        expected_manifest = _issued_manifest_payload(context)
        expected_manifest_sha256 = _issued_manifest_digest(expected_manifest)
        try:
            observed_manifest = json.loads(manifest.read_text())
        except (OSError, ValueError, TypeError):
            observed_manifest = None
        if (not manifest.is_file() or observed_manifest != expected_manifest or
                receipt.get('manifest_payload') != expected_manifest or
                receipt.get('manifest_sha256') != expected_manifest_sha256 or
                digest(manifest) != expected_manifest_sha256):
            raise Refusal('ISSUED_MANIFEST_CHANGED', arm.arm_id)
        if (not frozen.is_dir() or any(p.is_symlink() for p in frozen.rglob('*')) or
                any(p.is_file() and not is_exclusive_regular(p) for p in frozen.rglob('*')) or {
                str(p.relative_to(frozen)): digest(p) for p in frozen.rglob('*')
                if p.is_file() and p != manifest
                } != binding['inputs']):
            raise Refusal('FROZEN_INPUT_CHANGED', arm.arm_id)
        evidence = receipt.get('evidence') or {}
        if evidence.get('binding') != binding:
            raise Refusal('EVIDENCE_UNBOUND', arm.arm_id)
        gates = evidence.get('gates', {})
        verdict = evidence.get('verdict')
        # Bound measured failure stays terminal even when a separate gate
        # observation is absent. This cannot grant eligibility or adoption.
        if verdict == 'FAIL' or any(gates.get(k) == 'FAIL' for k in context.required_gates):
            raise Refusal('GATE_FAIL', arm.arm_id)
        gate_receipts = receipt.get('gate_receipts') or {}
        composite = evidence.get('provenance', {}).get('composite_gate_execution')
        composite_worker = None
        if composite:
            # A projected receipt is not authority. Reconsume the canonical
            # validator, then bind it to the actual source-owned worker Popen.
            here = Path(__file__).resolve().parent
            from execution_provider_catalog import RELEASE_IDS, BACKEND_IDS, python_entrypoint, proven_dispatcher_closure
            if arm.step_id in RELEASE_IDS:
                import execution_adapters_release as canonical
                worker_name, worker_file = 'release-producer', 'execution_release_worker.py'
            elif arm.step_id in BACKEND_IDS:
                import execution_adapters_backend as canonical
                worker_name, worker_file = 'producer', 'execution_backend_worker.py'
            else:
                raise Refusal('GATE_EXECUTION_UNBOUND', arm.arm_id)
            fresh = asdict(canonical.validate(Path(receipt['output_root']), binding))
            if fresh.get('verdict') == 'FAIL' or any(
                    fresh.get('gates', {}).get(g) == 'FAIL' for g in context.required_gates):
                raise Refusal('GATE_FAIL', arm.arm_id)
            composite_worker = next((p for p in processes if p.get('component') == worker_name), None)
            worker_source = str(here / worker_file)
            component = arm.components[0] if len(arm.components) == 1 else None
            expected_argv = ([arg.replace('{inputs}', receipt['input_root']).replace(
                '{outputs}', receipt['output_root']) for arg in component.argv] if component else [])
            try:
                if not component:
                    raise ValueError('canonical composite needs one registered component')
                expected_argv[0] = str(Path(shutil.which(expected_argv[0]) or expected_argv[0]).resolve())
                entry = python_entrypoint(tuple(expected_argv), Path(receipt['output_root']))
                _, _, entry_index = _python_entry(tuple(expected_argv[1:]), allowed_options='BuqOWX')
                worker_args = expected_argv[entry_index + 2:]
                proof = proven_dispatcher_closure(entry, Path(worker_source), cwd=Path(receipt['output_root']))
                if any(arm.source_files.get(str(path)) != digest(path) for path in proof):
                    raise ValueError('canonical dispatcher source is not bound')
            except (OSError, ValueError, Refusal) as exc:
                raise Refusal('GATE_EXECUTION_UNBOUND', str(exc)) from exc
            if (fresh != evidence or composite.get('schema') != 'vibeic/composite-gate-execution/1' or
                    component is None or component.name != worker_name or
                    len(worker_args) != 6 or
                    worker_args[:4] != [receipt['input_root'], receipt['output_root'], '--step-id', arm.step_id] or
                    worker_args[4] != '--params-json' or
                    composite_worker is None or composite_worker.get('argv') != expected_argv or
                    composite.get('worker_component') != worker_name or
                    composite.get('worker_source') != worker_source or
                    composite.get('required_gates') != list(context.required_gates) or
                    set(composite.get('gate_records', {})) != set(context.required_gates) or
                    set(gates) != set(context.required_gates) or
                    evidence.get('outputs', {}).get(composite.get('receipt_name')) != composite.get('receipt_sha256')):
                raise Refusal('GATE_EXECUTION_UNBOUND', arm.arm_id)
            for source, expected in {worker_source: digest(Path(worker_source)),
                                     **composite.get('gate_sources', {})}.items():
                if arm.source_files.get(source) != expected or digest(Path(source)) != expected:
                    raise Refusal('GATE_EXECUTION_UNBOUND', source)
        for gate in context.required_gates:
            gate_receipt = gate_receipts.get(gate)
            if not isinstance(gate_receipt, dict):
                raise Refusal('GATE_EXECUTION_UNBOUND', gate)
            matching = next((process for process in processes
                             if process.get('component') == gate), None)
            if matching is None and composite_worker is not None:
                if (gate_receipt.get('observation') != 'canonical-composite' or
                        gate_receipt.get('nested_worker_component') != composite_worker['component'] or
                        gate_receipt.get('typed_receipt_name') != composite['receipt_name'] or
                        gate_receipt.get('typed_receipt_sha256') != composite['receipt_sha256'] or
                        gate_receipt.get('nested_record_sha256') != _hash(composite['gate_records'][gate]) or
                        gate_receipt.get('rc') != 0):
                    raise Refusal('GATE_EXECUTION_UNBOUND', gate)
                matching = composite_worker
            if matching is None:
                # Narrow nested-gate path for the registered M1-M4 aggregate
                # worker only. Direct gate-process receipts retain the normal
                # observed-Popen checks below.
                nested = next((row for row in evidence.get('provenance', {}).get(
                    'nested_gate_records', ()) if row.get('gate') == gate), None)
                worker = next((process for process in processes
                               if process.get('component') == 'ordinary-mixed-producer'), None)
                if (arm.step_id not in ('M1', 'M2', 'M3', 'M4') or
                        arm.tool_id != 'vibeic' or len(arm.components) != 1 or
                        arm.components[0].name != 'ordinary-mixed-producer' or
                        nested is None or worker is None or worker.get('rc') != 0 or
                        nested.get('worker_component') != worker.get('component') or
                        nested.get('rc') != 0 or nested.get('verdict') != 'PASS' or
                        gate_receipt.get('nested_worker_component') != worker.get('component') or
                        gate_receipt.get('nested_record_sha256') != _hash(nested) or
                        gate_receipt.get('argv') != nested.get('command') or
                        gate_receipt.get('rc') != nested.get('rc')):
                    raise Refusal('GATE_EXECUTION_UNBOUND', gate)
            if (matching is not None and (gate_receipt.get('argv') != matching.get('argv') or
                    gate_receipt.get('argv_sha256') != _hash(matching.get('argv')) or
                    gate_receipt.get('executable_path') != matching.get('executable_path') or
                    gate_receipt.get('executable_sha256') != matching.get('executable_sha256') or
                    gate_receipt.get('source_sha') != arm.source_sha or
                    gate_receipt.get('tool_id') != arm.tool_id or
                    gate_receipt.get('tool_version') != arm.tool_version or
                    gate_receipt.get('source_manifest_sha256') != _hash(dict(arm.source_files)) or
                    gate_receipt.get('inputs') != binding['inputs'] or
                    gate_receipt.get('rc') != 0 or
                    gate_receipt.get('output_digest') != _hash(evidence.get('outputs', {})))):
                raise Refusal('GATE_EXECUTION_UNBOUND', gate)
            if matching is None and (
                    gate_receipt.get('argv_sha256') != _hash(gate_receipt.get('argv')) or
                    gate_receipt.get('executable_path') != gate_receipt.get('argv', [None])[0] or
                    gate_receipt.get('executable_sha256') != digest(Path(
                        gate_receipt['executable_path'])) or
                    gate_receipt.get('source_sha') != arm.source_sha or
                    gate_receipt.get('tool_id') != arm.tool_id or
                    gate_receipt.get('tool_version') != arm.tool_version or
                    gate_receipt.get('source_manifest_sha256') != _hash(dict(arm.source_files)) or
                    gate_receipt.get('inputs') != binding['inputs'] or
                    gate_receipt.get('output_digest') != _hash(evidence.get('outputs', {}))):
                raise Refusal('GATE_EXECUTION_UNBOUND', gate)
        if verdict != 'PASS' or any(not required_gate_satisfied(
                context.step_id, k, gates.get(k)) for k in context.required_gates):
            raise Refusal('GATE_NOT_MEASURED', arm.arm_id)
        if arm.step_id == '0.5ic' and arm.tool_id == 'frontend-worker':
            chain = consume_frontend_chain(Path(receipt['output_root']), binding)
            if (chain != receipt.get('producer_chain') or
                    chain != evidence.get('provenance', {}).get('producer_chain')):
                raise Refusal('STAGED_CHAIN_RECEIPT_MISMATCH', arm.arm_id)
        outputs = Path(receipt['output_root']).resolve()
        hashes = evidence.get('outputs', {})
        def output_contract_satisfied(spec):
            return any(any(fnmatch.fnmatch(name, alternative.strip())
                           for alternative in str(spec).split(' OR '))
                       for name in hashes)
        if not hashes or not all(output_contract_satisfied(spec)
                                 for spec in arm.required_outputs):
            raise Refusal('OUTPUT_INCOMPLETE', arm.arm_id)
        for name, expected in hashes.items():
            path = outputs / _relative(name)
            if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(outputs):
                raise Refusal('OUTPUT_OUTSIDE_ARM', name)
            if digest(path) != expected:
                raise Refusal('OUTPUT_DIGEST_MISMATCH', name)
        if any(type(v) not in (int, float) or not math.isfinite(v)
               for v in evidence.get('metrics', {}).values()):
            raise Refusal('INVALID_METRIC', arm.arm_id)
        metric = context.objective.get('metric')
        value = evidence.get('metrics', {}).get(metric)
        if type(value) not in (int, float) or not math.isfinite(value):
            raise Refusal('OBJECTIVE_EVIDENCE_INVALID', arm.arm_id)

    @_supervised
    def adopt(self, context: Context, root: Path, choice: Mapping[str, object] | None,
              *, _candidate_statuses: Mapping[str, str] | None = None, _issue=None) -> dict:
        """AI must supply an explicit receipt-bound decision; no rc0/PASS shortcut.

        All evidence is reconsumed at adoption, including the adapter's actual
        output validator. Receipt editing cannot change that validator's answer.
        Adoption records the result; it does not overwrite native project outputs.
        """
        root = Path(root).resolve()
        adoption = dict(run_id=None, status='REFUSED', selected=None,
                        ai_choice=dict(choice) if choice is not None else None)
        published = False

        def publish(value: dict) -> None:
            """Issue adoption exactly once from this live controller call.

            There is deliberately no importable writer.  Re-signing an
            existing path would let a caller co-update a selected manifest,
            winner and adoption document after the original producer receipt.
            The sealed store rejects any second payload for the same path.
            """
            nonlocal published
            if published:
                raise Refusal('ISSUED_AUTHORITY_REISSUE', str(root))
            _write(root / 'adoption.json', value)
            _write(root / 'program_adoption.json', value)
            _write(root / 'issued-adoption.json',
                   _issue_sealed(root / 'issued-adoption.json', value))
            published = True

        generation = None
        try:
            self._context_binding(context)
            plan = json.loads((root / 'plan.json').read_text())
            adoption['run_id'] = plan['run_id']
            if not choice or not all(isinstance(choice.get(k), str) and choice[k].strip()
                                     for k in ('arm_id', 'receipt_sha256', 'rationale', 'reviewer')):
                raise Refusal('AI_CHOICE_MISSING', context.step_id)
            if choice.get('binding') != self._context_binding(context) or plan['binding'] != self._context_binding(context):
                raise Refusal('AI_CHOICE_UNBOUND', context.step_id)
            arm_id = choice['arm_id']
            if arm_id not in plan['arms']:
                raise Refusal('AI_CHOICE_NOT_CANDIDATE', str(arm_id))
            path = root / str(arm_id) / 'receipt.json'
            if not path.is_file() or digest(path) != choice['receipt_sha256']:
                raise Refusal('AI_RECEIPT_DIGEST_MISMATCH', str(arm_id))
            # A default run may already have completed the program adoption
            # chain.  Re-consuming that immutable chain is allowed; issuing a
            # second payload for the same path is not.  Only take this fast
            # path when all three public adoption documents still equal the
            # original sealed payload.
            adoption_path = root / 'adoption.json'
            issued_path = root / 'issued-adoption.json'
            if adoption_path.is_file() and issued_path.is_file():
                try:
                    existing = _issued(issued_path)
                    current = json.loads(adoption_path.read_text())
                    program = json.loads((root / 'program_adoption.json').read_text())
                except (OSError, ValueError, KeyError):
                    existing = None
                if (isinstance(existing, dict) and existing.get('status') == 'ADOPTED' and
                        current == existing and program == existing):
                    self.verify_adoption(context, root)
                    return existing
            receipt = json.loads(path.read_text())
            arm = next((a for a in self.registry.adapters(context.step_id) if a.arm_id == arm_id), None)
            if arm is None or receipt.get('run_id') != plan['run_id'] or receipt.get('status') != 'ELIGIBLE':
                raise Refusal('AI_CHOICE_INELIGIBLE', str(arm_id))
            if (Path(receipt['output_root']).resolve() != root / str(arm_id) / 'outputs' or
                    Path(receipt['input_root']).resolve() != root / str(arm_id) / 'inputs'):
                raise Refusal('WRONG_ARM_OUTPUT_SPACE', str(arm_id))
            self._execution_authority(root, plan, receipt, arm)
            chain = self._verify_receipt_chain(root, plan, context)
            adoption.update(frozen_work_digest=plan.get('frozen_work_digest'),
                            comparison_digest=chain['comparison_digest'],
                            arm_receipts=chain['comparison']['arm_receipts'],
                            intent_label=plan.get('intent_label'),
                            request_digest=plan.get('request_digest'))
            eligible = {row['arm_id']: row['receipt_sha256'] for row in chain['eligible']}
            if arm_id not in eligible or digest(path) != eligible[arm_id]:
                # A measured FAIL remains primary; an unmeasured arm cannot be
                # rescued by a reviewer string or a forged status edit.
                raise Refusal('AI_CHOICE_INELIGIBLE', str(arm_id))
            if plan.get('mode') == 'ultra-mode' and len(eligible) > 1:
                winner = self._objective_winner(
                    plan, root, chain['eligible'], context)
                if arm_id != winner:
                    raise Refusal('AI_CHOICE_WORSE_OBJECTIVE', str(arm_id))
            self._current_admission(context, plan, arm)
            self._eligible(receipt, context, arm)
            fresh = asdict(arm.validate(Path(receipt['output_root']), self._context_binding(context)))
            if fresh != receipt['evidence']:
                raise Refusal('EVIDENCE_CHANGED', str(arm_id))
            completion = _issued(root / arm.arm_id / 'issued-completion.json')
            if (completion.get('actual_status') != receipt.get('status') or
                    completion.get('actual_reason') != receipt.get('reason') or
                    completion.get('evidence') != receipt.get('evidence')):
                raise Refusal('EXECUTION_AUTHORITY_MISMATCH', arm.arm_id)
            # A source validator can legitimately pause. Its return is not a
            # lease on the earlier input/executable/output bytes. Recheck after
            # it returns, then run the final consumer before capturing any
            # selected bytes. A callback that mutates an output after its first
            # answer is therefore observed by the second eligibility pass.
            self._eligible(receipt, context, arm)
            generation = self._selected_generation(root, receipt, _issue)
            self._execution_authority(root, plan, receipt, arm)
            self._current_admission(context, plan, arm)
            self._eligible(receipt, context, arm)
            # The validator is the final consumer of the original result. It
            # may observe a late transform/validator failure after the earlier
            # admission checks, so its final answer is checked before copying
            # bytes into the selected generation.
            final_evidence = asdict(arm.validate(
                Path(receipt['output_root']), self._context_binding(context)))
            if (final_evidence != receipt['evidence'] or
                    final_evidence.get('verdict') != 'PASS' or
                    any(not required_gate_satisfied(context.step_id, gate,
                        final_evidence.get('gates', {}).get(gate))
                        for gate in context.required_gates)):
                raise Refusal('FINAL_EVIDENCE_CHANGED', str(arm_id))
            self._eligible(receipt, context, arm)
            # Freeze/re-hash directly around publication. This catches a final
            # validator/transform that touched the selected generation and
            # leaves no successful adoption receipt in that case.
            self._generation_current(generation)
            if generation.get('outputs') != receipt['evidence'].get('outputs'):
                raise Refusal('SELECTED_GENERATION_UNBOUND', str(arm_id))
            adoption.update(status='PROVISIONAL', selected=arm_id,
                            evidence=receipt['evidence'],
                            independence=plan['independence'],
                            selected_generation=generation,
                            winner=dict(arm_id=arm_id, receipt_sha256=choice['receipt_sha256'],
                                        artifact_outputs=receipt['evidence']['outputs']),
                            acceptance_rerun=dict(acceptance_digest=plan['acceptance_digest'],
                                                  binding=self._context_binding(context),
                                                  evidence=final_evidence,
                                                  status='PASS'))
            if _candidate_statuses is not None:
                adoption.update(candidate_statuses=dict(_candidate_statuses),
                                mode=plan['mode'], mode_intent=plan['mode_intent'])
            # Backend rows have one canonical downstream consumer.  Invoke it
            # on the immutable selected generation before recording adoption;
            # no consumer may read the mutable run root after this boundary.
            if 'backend_result.json' in generation.get('outputs', {}):
                import execution_backend_consumer as _backend_consumer
                consumer = _backend_consumer.import_selected(
                    Path(generation['directory']), context, self, root, adoption)
                if not isinstance(consumer, dict) or consumer.get('status') != 'CONSUMED':
                    raise Refusal('BACKEND_CANONICAL_CONSUMER_REFUSED', str(arm_id))
                adoption['consumer'] = consumer
            adoption['selected_generation'] = self._commit_generation(generation, _issue)
            generation = adoption['selected_generation']
            adoption['status'] = 'ADOPTED'
            publish(adoption)
            try:
                self._generation_current(generation)
            except Refusal:
                adoption.update(status='REFUSED', selected=None,
                                reason='SELECTED_GENERATION_CHANGED',
                                detail='selected bytes changed during adoption publication')
                raise
        except Refusal as exc:
            adoption['discarded_generation'] = self._discard_generation(root, generation, _issue)
            adoption.pop('selected_generation', None)
            adoption.update(status='REFUSED', selected=None, reason=exc.code, detail=str(exc))
            if exc.code in ('CONTROLLER_ISSUANCE_REQUIRED', 'CONTEXT_IMPLEMENTATION_UNTRUSTED'):
                return self._authority_refusal(root, exc)
            if not published:
                try:
                    publish(adoption)
                except Refusal as recording:
                    if recording.code == 'ISSUED_AUTHORITY_REISSUE':
                        # Preserve a visible refusal for a second consumer
                        # attempt without replacing the original issued PASS.
                        _write(root / 'adoption.json', adoption)
                        _write(root / 'program_adoption.json', adoption)
                    else:
                        raise Refusal('ADOPTION_RECORD_UNAVAILABLE',
                                      f'{exc}; {recording}') from recording
                except OSError as recording:
                    raise Refusal('ADOPTION_RECORD_UNAVAILABLE', f'{exc}; {recording}') from recording
            raise
        except Exception as exc:
            adoption['discarded_generation'] = self._discard_generation(root, generation, _issue)
            adoption.pop('selected_generation', None)
            adoption.update(status='REFUSED', selected=None,
                            reason='INVALID_ADOPTION_EVIDENCE', detail=str(exc))
            if not published:
                try:
                    publish(adoption)
                except Refusal as recording:
                    if recording.code == 'ISSUED_AUTHORITY_REISSUE':
                        _write(root / 'adoption.json', adoption)
                        _write(root / 'program_adoption.json', adoption)
                    else:
                        raise Refusal('ADOPTION_RECORD_UNAVAILABLE',
                                      f'{exc}; {recording}') from recording
                except OSError as recording:
                    raise Refusal('ADOPTION_RECORD_UNAVAILABLE', f'{exc}; {recording}') from recording
            raise Refusal('INVALID_ADOPTION_EVIDENCE', str(exc)) from exc
        return adoption

    def verify_adoption(self, context: Context, root: Path) -> dict:
        """Reconsume a completed adoption chain without changing project bytes."""
        root = Path(root).resolve()
        self._context_binding(context)
        try:
            adoption = json.loads((root / 'adoption.json').read_text())
            program = json.loads((root / 'program_adoption.json').read_text())
            issued = _issued(root / 'issued-adoption.json')
        except (OSError, ValueError, KeyError) as exc:
            raise Refusal('PROGRAM_ADOPTION_INVALID', str(exc)) from exc
        if adoption != program or adoption != issued:
            raise Refusal('PROGRAM_ADOPTION_CHANGED', str(root))
        plan = json.loads((root / 'plan.json').read_text())
        chain = self._verify_receipt_chain(root, plan, context)
        if adoption.get('frozen_work_digest') != plan.get('frozen_work_digest') or \
                adoption.get('comparison_digest') != chain['comparison_digest'] or \
                adoption.get('intent_label') != plan.get('intent_label') or \
                adoption.get('request_digest') != plan.get('request_digest'):
            raise Refusal('PROGRAM_ADOPTION_UNBOUND', context.step_id)
        winner = adoption.get('winner') or {}
        row = next((item for item in chain['eligible'] if item['arm_id'] == winner.get('arm_id')), None)
        if row is None or row['receipt_sha256'] != winner.get('receipt_sha256'):
            raise Refusal('PROGRAM_ADOPTION_WINNER_MISMATCH', context.step_id)
        if adoption.get('status') != 'ADOPTED':
            raise Refusal('PROGRAM_ADOPTION_NOT_ADOPTED', context.step_id)
        generation = adoption.get('selected_generation')
        if not isinstance(generation, dict):
            raise Refusal('PROGRAM_ADOPTION_GENERATION_MISSING', context.step_id)
        if (generation.get('run_id') != plan.get('run_id') or
                generation.get('arm_id') != winner.get('arm_id') or
                generation.get('outputs') != winner.get('artifact_outputs')):
            raise Refusal('PROGRAM_ADOPTION_GENERATION_UNBOUND', context.step_id)
        # Rehash every selected output on every verification.  The immutable
        # adoption receipt is not evidence that the selected bytes still match
        # the issued generation; a post-adoption mutation must refuse.
        self._generation_current(generation)
        arm_id = winner.get('arm_id')
        receipt_path = root / str(arm_id) / 'receipt.json'
        if not receipt_path.is_file() or digest(receipt_path) != winner.get('receipt_sha256'):
            raise Refusal('PROGRAM_ADOPTION_WINNER_MISMATCH', context.step_id)
        receipt = json.loads(receipt_path.read_text())
        arm = next((candidate for candidate in self.registry.adapters(context.step_id)
                    if candidate.arm_id == arm_id), None)
        if (arm is None or receipt.get('run_id') != plan.get('run_id') or
                receipt.get('status') != 'ELIGIBLE' or
                Path(receipt.get('output_root', '')).resolve() != root / str(arm_id) / 'outputs' or
                Path(receipt.get('input_root', '')).resolve() != root / str(arm_id) / 'inputs'):
            raise Refusal('PROGRAM_ADOPTION_EXECUTION_INVALID', context.step_id)
        original_outputs = (receipt.get('evidence') or {}).get('outputs')
        if (winner.get('artifact_outputs') != original_outputs or
                generation.get('outputs') != original_outputs):
            raise Refusal('PROGRAM_ADOPTION_GENERATION_UNBOUND', context.step_id)
        self._execution_authority(root, plan, receipt, arm)
        self._current_admission(context, plan, arm)
        self._eligible(receipt, context, arm)
        final_evidence = asdict(arm.validate(Path(receipt['output_root']), self._context_binding(context)))
        if (final_evidence != receipt.get('evidence') or
                final_evidence.get('verdict') != 'PASS' or
                any(not required_gate_satisfied(context.step_id, gate,
                    final_evidence.get('gates', {}).get(gate))
                    for gate in context.required_gates)):
            raise Refusal('FINAL_EVIDENCE_CHANGED', str(arm_id))
        return adoption
# Do not expose a decorator that callers could use to mint enrollment.
del _supervised
