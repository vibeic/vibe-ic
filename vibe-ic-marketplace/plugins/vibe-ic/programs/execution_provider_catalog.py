"""Source-owned provider census for the backend and release adapter families.

The catalogue is deliberately descriptive.  It names the real producer
callables and the canonical consumers, while the adapters keep native
qualification ``NOT_MEASURED`` until a current receipt exists.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import ast
from functools import lru_cache
import json
from pathlib import Path
import subprocess
from typing import Iterable

HERE = Path(__file__).resolve().parent
BACKEND_POLICY = json.loads((HERE / "data/execution_backend_policy.json").read_text())
BACKEND_ROWS = BACKEND_POLICY["rows"]

try:
    from execution_release_rows import ROWS as RELEASE_ROWS
except ModuleNotFoundError:  # backend-first commit remains independently importable
    RELEASE_ROWS = {}


@lru_cache(maxsize=1)
def current_source_identity() -> str:
    """Return the current checked-out commit identity; caller labels are ignored."""
    try:
        value = subprocess.check_output(
            ["git", "-C", str(HERE), "rev-parse", "HEAD"],
            text=True, stderr=subprocess.DEVNULL).strip().lower()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RuntimeError("SOURCE_IDENTITY_UNAVAILABLE") from exc
    if len(value) != 40 or any(ch not in "0123456789abcdef" for ch in value):
        raise RuntimeError("SOURCE_IDENTITY_INVALID")
    return value


@lru_cache(maxsize=1)
def current_source_tree_identity() -> str:
    """Return the HEAD tree identity used beside the commit binding."""
    try:
        value = subprocess.check_output(
            ["git", "-C", str(HERE), "rev-parse", "HEAD^{tree}"],
            text=True, stderr=subprocess.DEVNULL).strip().lower()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RuntimeError("SOURCE_TREE_IDENTITY_UNAVAILABLE") from exc
    if len(value) != 40 or any(ch not in "0123456789abcdef" for ch in value):
        raise RuntimeError("SOURCE_TREE_IDENTITY_INVALID")
    return value


@lru_cache(maxsize=2048)
def _import_names(text: str) -> tuple[str, ...]:
    """Cache syntax only; filesystem resolution must remain current."""
    from execution_source_snapshot import python_import_syntax
    try:
        imports = python_import_syntax(text)
    except (OSError, SyntaxError):
        return ()
    found: set[str] = set()
    for kind, _level, module, names, _optional in imports:
        if kind == 'import':
            found.update(names)
        elif kind == 'from':
            found.update([module] if module else names)
        else:
            found.add(module)
    return tuple(sorted(found))


def _local_imports(path: str, text: str) -> tuple[Path, ...]:
    """Resolve live, or reuse a transaction whose path probes finalize afresh."""
    from execution_source_snapshot import active
    snapshot = active()
    source = Path(path).absolute()
    cache_key = ('provider-local-imports', str(source), text)
    if snapshot is not None:
        cached = snapshot.value_get(cache_key)
        if cached is not None:
            snapshot.stats['provider_import_hits'] += 1
            return cached
        snapshot.stats['provider_import_misses'] += 1
    found: set[Path] = set()
    for name in _import_names(text):
        base = name.split(".")[0]
        for directory in (source.parent, HERE):
            candidates = (directory / (base + ".py"), directory / base / "__init__.py")
            if snapshot is not None:
                probes = [snapshot.import_candidate(p) for p in candidates]
                local = [state[3] for state in probes if state[2] and not state[1]]
            else:
                local = [p.resolve() for p in candidates if p.is_file() and not p.is_symlink()]
            if local:
                found.update(local)
                break
    result = tuple(sorted(found))
    if snapshot is not None:
        snapshot.value_put(cache_key, result)
    return result


def source_closure(paths: Iterable[Path]) -> set[Path]:
    """Collect local Python imports reachable from the supplied entrypoints.

    The closure is source identity, so every transitive local import remains
    bound, while the per-file parse cache keeps registering the 37 adapters
    from repeatedly reparsing the same runner modules.
    """
    pending = [Path(p).resolve() for p in paths]
    try:
        from execution_source_snapshot import active
        snapshot = active()
    except ImportError:
        snapshot = None
    cache_key = ('provider-source-closure', tuple(sorted(map(str, pending))))
    if snapshot is not None:
        cached = snapshot.closure_get(cache_key)
        if cached is not None:
            for path in cached:
                snapshot.read_bytes(path)
            return cached
    seen: set[Path] = set()
    while pending:
        path = pending.pop()
        if path in seen or not path.is_file() or path.is_symlink():
            continue
        seen.add(path)
        if path.suffix == ".py":
            text = snapshot.read_text(path) if snapshot is not None else path.read_text()
            pending.extend(_local_imports(str(path), text))
    if snapshot is not None:
        for path in seen:
            snapshot.read_bytes(path)
        snapshot.closure_put(cache_key, seen)
    return seen


def dispatcher_closure(entry: Path, dispatcher: Path) -> set[Path]:
    """Prove a transparent Python alias, or refuse opaque dispatch.

    Only imports of ``main``, literal path bootstraps and a direct main call
    are admitted. Import reachability alone does not prove what executes.
    Copied workers and arbitrary loader code are refused: their relative
    import resolution is not proven by matching the entry's bytes.
    """
    seen: set[Path] = set()

    def visit(path: Path, *, entrypoint: bool = False):
        path = path.resolve()
        if path == dispatcher:
            seen.add(path)
            return
        if path in seen or not path.is_file():
            raise ValueError(f"unproven dispatcher: {path}")
        seen.add(path)
        search = [path.parent]
        symbols = set()
        libraries = {}
        invoked = False

        def call(node):
            if not isinstance(node, ast.Call) or node.args or node.keywords:
                raise ValueError(f"unproven main call: {path}")
            if isinstance(node.func, ast.Name) and node.func.id in symbols:
                return
            fn = node.func
            if (isinstance(fn, ast.Attribute) and fn.attr == "main" and
                isinstance(fn.value, ast.Call) and not fn.value.keywords and
                len(fn.value.args) == 1 and isinstance(fn.value.args[0], ast.Constant) and
                isinstance(fn.value.args[0].value, str) and
                isinstance(fn.value.func, ast.Attribute) and fn.value.func.attr == "import_module" and
                isinstance(fn.value.func.value, ast.Name) and
                libraries.get(fn.value.func.value.id) == "importlib"):
                imported(fn.value.args[0].value)
                return
            raise ValueError(f"unproven main call: {path}")

        def imported(name):
            if not name.isidentifier():
                raise ValueError(f"unproven module: {name}")
            target = next((d / (name + ".py") for d in search if (d / (name + ".py")).is_file()), None)
            if target is None or target.is_symlink():
                raise ValueError(f"unresolved module: {name}")
            visit(target)

        for node in ast.parse(path.read_text()).body:
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                continue
            if isinstance(node, ast.Import) and all(a.name in ("sys", "importlib") for a in node.names):
                if any(a.name == "importlib" for a in node.names) and any(
                        (d / "importlib.py").exists() or (d / "importlib" / "__init__.py").exists() for d in search):
                    raise ValueError(f"shadowed loader: {path}")
                libraries.update({a.asname or a.name: a.name for a in node.names})
            elif (isinstance(node, ast.Expr) and isinstance(node.value, ast.Call) and
                  isinstance(node.value.func, ast.Attribute) and
                  ast.unparse(node.value.func) == "sys.path.insert" and libraries.get("sys") == "sys" and
                  not node.value.keywords and len(node.value.args) == 2 and
                  isinstance(node.value.args[0], ast.Constant) and node.value.args[0].value == 0 and
                  isinstance(node.value.args[1], ast.Constant) and isinstance(node.value.args[1].value, str) and
                  Path(node.value.args[1].value).is_absolute()):
                search.insert(0, Path(node.value.args[1].value).resolve())
            elif (isinstance(node, ast.ImportFrom) and node.level == 0 and node.module and
                  len(node.names) == 1 and node.names[0].name == "main"):
                imported(node.module)
                symbols.add(node.names[0].asname or "main")
            elif (isinstance(node, ast.FunctionDef) and node.name == "main" and
                  not node.decorator_list and not node.args.args and not node.args.posonlyargs and
                  not node.args.kwonlyargs and not node.args.vararg and not node.args.kwarg and
                  node.returns is None and len(node.body) == 1 and isinstance(node.body[0], ast.Return)):
                call(node.body[0].value)
                symbols.add("main")
            elif (entrypoint and isinstance(node, ast.Raise) and node.cause is None and
                  isinstance(node.exc, ast.Call) and isinstance(node.exc.func, ast.Name) and
                  node.exc.func.id == "SystemExit" and len(node.exc.args) == 1 and not node.exc.keywords):
                call(node.exc.args[0])
                invoked = True
            else:
                raise ValueError(f"opaque dispatcher: {path}:{node.lineno}")
        if not (invoked if entrypoint else "main" in symbols):
            raise ValueError(f"missing dispatcher call: {path}")

    visit(entry, entrypoint=True)
    return seen


def python_entrypoint(argv: tuple[str, ...], cwd: Path | None) -> Path:
    """Resolve supported Python script invocations without executing them.

    Options that alter import resolution, inline code and module launch are
    deliberately unsupported. Refusal precedes launch and identity deduplication.
    """
    # Share registration's option/value parsing. Import-path-changing options
    # remain outside this provider's modeled search policy.
    from execution_modes import _python_entry, Refusal
    try:
        argument, _, _ = _python_entry(argv[1:], allowed_options="BuqOWX")
    except Refusal as exc:
        raise ValueError(f"unsupported Python invocation: {exc}") from exc
    path = Path(argument)
    if not path.is_absolute():
        if cwd is None:
            raise ValueError('Python entrypoint needs execution cwd')
        path = cwd / path
    path = path.resolve()
    if not path.is_file():
        raise ValueError(f'missing Python entrypoint: {path}')
    return path


def _python_search(entry: Path, cwd: Path | None) -> list[Path]:
    """Model the local part of the child interpreter's actual search path."""
    import os
    search = [entry.parent]
    for text in os.environ.get('PYTHONPATH', '').split(os.pathsep) if 'PYTHONPATH' in os.environ else ():
        path = Path(text) if text else Path('.')
        if not path.is_absolute():
            if cwd is None:
                raise ValueError('relative PYTHONPATH needs execution cwd')
            path = cwd / path
        if path.is_file():
            raise ValueError(f'unsupported Python search-path importer: {path}')
        search.append(path.resolve())
    return search


@lru_cache(maxsize=1)
def _python_trusted_roots() -> tuple[Path, ...]:
    import sysconfig
    return tuple(Path(sysconfig.get_path(key)).resolve() for key in ('stdlib', 'platstdlib', 'purelib', 'platlib'))


def _python_module(name: str, search: list[Path], package: str = '',
                   level: int = 0) -> list[tuple[Path, str]]:
    """Resolve complete dotted names with Python package-before-module rules.

    No helper is imported while proving its identity. Namespace packages,
    local extension modules and unresolved local dotted names fail closed.
    External modules belong to the separately pinned interpreter/image.
    """
    if level:
        parts = package.split('.') if package else []
        if level > len(parts):
            raise ValueError(f'unresolved relative import: {name}')
        name = '.'.join(parts[:len(parts) - level + 1] + ([name] if name else []))
    if not name or any(not part.isidentifier() for part in name.split('.')):
        raise ValueError(f'unresolved Python module: {name}')
    from importlib.machinery import BuiltinImporter, FrozenImporter, EXTENSION_SUFFIXES
    top = name.split('.')[0]
    if BuiltinImporter.find_spec(top) is not None or FrozenImporter.find_spec(top) is not None:
        return []
    trusted = _python_trusted_roots()
    directories = search
    result = []; prefix = []
    parts = name.split('.')
    for index, part in enumerate(parts):
        prefix.append(part)
        target = None; is_package = False; namespace = False
        suffixes = [*EXTENSION_SUFFIXES, '.py', '.pyc']
        for directory in directories:
            package_dir = directory / part
            if package_dir.is_dir():
                namespace = True
                for suffix in suffixes:
                    candidate = package_dir / ('__init__' + suffix)
                    if candidate.is_file():
                        target = candidate; is_package = True; break
            if target is None:
                for suffix in suffixes:
                    candidate = directory / (part + suffix)
                    if candidate.is_file():
                        target = candidate; break
            if target is not None:
                break
        if target is None:
            if result or namespace:
                raise ValueError(f'incomplete or namespace Python package: {name}')
            return []
        resolved_target = target.resolve()
        if not result and any(resolved_target.is_relative_to(root) for root in trusted):
            return []
        if target.is_symlink() or target.suffix != '.py':
            raise ValueError(f'unsupported local Python module: {name}')
        owner = '.'.join(prefix) if is_package else '.'.join(prefix[:-1])
        result.append((resolved_target, owner))
        if not is_package and index < len(parts) - 1:
            raise ValueError(f'non-package dotted Python module: {name}')
        directories = [target.parent] if is_package else []
    return result


@lru_cache(maxsize=2048)
def _python_import_specs(text: str) -> tuple:
    """Cache syntax, never filesystem resolution or dependency bytes."""
    from execution_source_snapshot import python_import_syntax
    found = []
    for kind, level, module, names, optional_relative in python_import_syntax(text):
        if kind == 'import':
            found.extend((name, 0, (), False) for name in names)
        elif kind == 'from':
            found.append((module, level, names, optional_relative))
        else:
            found.append((module, 0, (), False))
    return tuple(found)


def implementation_closure(entry: Path, *, cwd: Path | None = None,
                           search: list[Path] | None = None, source_text: str | None = None) -> set[Path]:
    """Bind actual local dotted/relative imports using active search paths.

    This is separate from the legacy declaration scanner ``source_closure``;
    a declaration is not a proof of what the interpreter will execute.
    """
    import importlib
    try:
        from execution_source_snapshot import active
        snapshot = active()
    except ImportError:
        snapshot = None
    importlib.invalidate_caches()
    entry = entry.resolve()
    search = list(search) if search is not None else _python_search(entry, cwd)
    cache_key = ('provider-implementation-closure', str(entry),
                 str(Path(cwd).resolve()) if cwd is not None else None,
                 tuple(map(str, search)), source_text)
    if snapshot is not None:
        cached = snapshot.closure_get(cache_key)
        if cached is not None:
            for path in cached:
                snapshot.read_bytes(path)
            return cached - {entry} if source_text is not None else cached
    pending = [(entry, '')]
    seen = set()
    while pending:
        path, package = pending.pop()
        if path in seen:
            continue
        if not path.is_file() and not (path == entry and source_text is not None):
            raise ValueError(f'missing Python source: {path}')
        seen.add(path)
        text = source_text if path == entry and source_text is not None else (
            snapshot.read_text(path) if snapshot is not None else path.read_text())
        for name, level, names, optional_relative in _python_import_specs(text):
            # An unqualified module's relative import raises before executing
            # any helper. Its explicit ImportError fallback is scanned too.
            if level and not package and optional_relative:
                continue
            try:
                resolved = _python_module(name, search, package, level)
            except ValueError as exc:
                raise ValueError(f'{path}: {exc}') from exc
            pending.extend(resolved)
            if names and resolved:
                base, base_package = resolved[-1]
                if base.name == '__init__.py':
                    for alias in names:
                        if alias != '*':
                            child = base.parent / (alias + '.py')
                            child_init = base.parent / alias / '__init__.py'
                            if child.is_file() or child_init.is_file():
                                pending.extend(_python_module(base_package + '.' + alias, search))
    if snapshot is not None:
        for path in seen:
            if path.is_file():
                snapshot.read_bytes(path)
        snapshot.closure_put(cache_key, seen)
    return seen - {entry} if source_text is not None else seen


def proven_dispatcher_closure(entry: Path, dispatcher: Path, *,
                              cwd: Path | None = None) -> set[Path]:
    """Prove transparent execution through actual packages and active paths.

    Path mutations persist across nested imports, as in the interpreter.
    Package initializers are executed and checked, including every intermediate
    package in a dotted import. Opaque initializers cannot qualify a wrapper.
    """
    entry, dispatcher = entry.resolve(), dispatcher.resolve()
    search = _python_search(entry, cwd)
    seen = set()
    active = set()
    exported = {}

    def imported(name, package, level=0):
        resolved = _python_module(name, search, package, level)
        if not resolved:
            raise ValueError(f'unresolved dispatcher module: {name}')
        for path, owner in resolved[:-1]:
            visit(path, owner, initializer=True)
        path, owner = resolved[-1]
        return visit(path, owner)

    def visit(path, package='', *, entrypoint=False, initializer=False):
        if path == dispatcher:
            actual = implementation_closure(path, cwd=cwd, search=search)
            canonical_search = _python_search(path, cwd)
            if list(dict.fromkeys(search)) != list(dict.fromkeys(canonical_search)):
                canonical = implementation_closure(path, cwd=cwd, search=canonical_search)
                if actual != canonical:
                    raise ValueError(f'dispatcher dependency resolution differs: {path}')
            seen.update(actual)
            return True
        if path in active:
            if initializer:
                return False
            raise ValueError(f'cyclic dispatcher import: {path}')
        if path in seen:
            return exported.get(path, False)
        active.add(path); seen.add(path)
        symbols = set(); libraries = {}; invoked = False

        def call(node):
            if not isinstance(node, ast.Call) or node.args or node.keywords:
                raise ValueError(f'unproven main call: {path}')
            if isinstance(node.func, ast.Name) and node.func.id in symbols:
                return
            fn = node.func
            if (isinstance(fn, ast.Attribute) and fn.attr == 'main' and
                isinstance(fn.value, ast.Call) and not fn.value.keywords and
                len(fn.value.args) == 1 and isinstance(fn.value.args[0], ast.Constant) and
                isinstance(fn.value.args[0].value, str) and
                isinstance(fn.value.func, ast.Attribute) and fn.value.func.attr == 'import_module' and
                isinstance(fn.value.func.value, ast.Name) and
                libraries.get(fn.value.func.value.id) == 'importlib'):
                if imported(fn.value.args[0].value, package):
                    return
            raise ValueError(f'unproven main call: {path}')

        for node in ast.parse(path.read_text()).body:
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                continue
            if isinstance(node, ast.Import) and all(a.name in ('sys', 'importlib') for a in node.names):
                if any(a.name == 'importlib' for a in node.names) and _python_module('importlib', search):
                    raise ValueError(f'shadowed loader: {path}')
                libraries.update({a.asname or a.name: a.name for a in node.names})
            elif (isinstance(node, ast.Expr) and isinstance(node.value, ast.Call) and
                  isinstance(node.value.func, ast.Attribute) and
                  ast.unparse(node.value.func) == 'sys.path.insert' and libraries.get('sys') == 'sys' and
                  not node.value.keywords and len(node.value.args) == 2 and
                  isinstance(node.value.args[0], ast.Constant) and node.value.args[0].value == 0 and
                  isinstance(node.value.args[1], ast.Constant) and isinstance(node.value.args[1].value, str)):
                directory = Path(node.value.args[1].value)
                if not directory.is_absolute():
                    if cwd is None:
                        raise ValueError('dispatcher search path needs execution cwd')
                    directory = cwd / directory
                search.insert(0, directory.resolve())
            elif (isinstance(node, ast.ImportFrom) and node.module and
                  len(node.names) == 1 and node.names[0].name == 'main'):
                if not imported(node.module, package, node.level):
                    raise ValueError(f'missing imported main: {path}')
                symbols.add(node.names[0].asname or 'main')
            elif (isinstance(node, ast.FunctionDef) and node.name == 'main' and
                  not node.decorator_list and not node.args.args and not node.args.posonlyargs and
                  not node.args.kwonlyargs and not node.args.vararg and not node.args.kwarg and
                  node.returns is None and len(node.body) == 1 and isinstance(node.body[0], ast.Return)):
                call(node.body[0].value); symbols.add('main')
            elif (entrypoint and isinstance(node, ast.Raise) and node.cause is None and
                  isinstance(node.exc, ast.Call) and isinstance(node.exc.func, ast.Name) and
                  node.exc.func.id == 'SystemExit' and len(node.exc.args) == 1 and not node.exc.keywords):
                call(node.exc.args[0]); invoked = True
            else:
                raise ValueError(f'opaque dispatcher: {path}:{node.lineno}')
        active.remove(path)
        if not (invoked if entrypoint else initializer or 'main' in symbols):
            raise ValueError(f'missing dispatcher call: {path}')
        exported[path] = 'main' in symbols
        return exported[path]

    if entry != dispatcher and entry.read_bytes() == dispatcher.read_bytes():
        # A copied worker is transparent only when its actual import resolution
        # matches the canonical worker, rather than merely matching entry bytes.
        actual_search = [entry.parent, *search]
        canonical_search = [dispatcher.parent, *search]
        actual = implementation_closure(entry, cwd=cwd, search=actual_search)
        canonical = implementation_closure(dispatcher, cwd=cwd, search=canonical_search)
        # Exact entry bytes were checked above. A transitive import may reach
        # the canonical dispatcher again; normalize only that proven root pair.
        # Every other dependency must still resolve to the identical file.
        if (actual - {entry}) | {dispatcher} != canonical:
            raise ValueError(f'copied worker import resolution differs: {entry}')
        return {entry, dispatcher, *actual}
    visit(entry, entrypoint=True)
    if dispatcher not in seen:
        raise ValueError(f'actual dispatcher not reached: {entry}')
    return seen


BACKEND_IDS = (
    "15", "15.5ic", "17", "18", "19", "20", "21", "22", "23", "24",
    "25", "26", "26.5ic", "27", "28", "29", "30", "32", "33", "34",
    "37", "37.3", "31",
)
RELEASE_IDS = (
    "14", "16", "35", "36", "37.4", "37.5ip", "37.5ic", "38", "39",
    "40", "41", "42", "43", "44",
)

# These are the producer sites used by the reviewed candidate.  A checker is
# listed only as a downstream consumer; it never becomes a second arm.
BACKEND_SITES = {
    "15": ("phase3_one_shot_runner.py:step_prepnr", "librelane_contract.py:run_chain"),
    "15.5ic": ("phase3_one_shot_runner.py:step_pad_ring_gen",),
    "17": ("librelane_contract.py:run_chain",),
    "18": ("librelane_contract.py:run_chain",),
    "19": ("librelane_cts_hold.py:execute",),
    "20": ("librelane_cts_hold.py:execute",),
    "21": ("librelane_route.py:execute", "librelane_postroute_repair.py:run"),
    "22": ("phase3_one_shot_runner.py:_librelane_rcx_publish",),
    "23": ("phase3_one_shot_runner.py:_emit_spef_sta", "librelane_signoff.py:run"),
    "24": ("phase3_one_shot_runner.py:_librelane_step24_record",),
    "25": ("phase3_one_shot_runner.py:_emit_ir_em_reports", "phase3_one_shot_runner.py:_emit_em_current_authority"),
    "26": ("phase3_one_shot_runner.py:_librelane_antenna_router",),
    "26.5ic": ("phase3_one_shot_runner.py:_die_finishing",),
    "27": ("phase3_one_shot_runner.py:_emit_si_timing_json", "si_signoff_timing_aware.py:run_si_signoff_timing_aware", "si_mcf_sta.py:run"),
    "28": ("phase3_one_shot_runner.py:_emit_perc_equivalent",),
    "29": ("phase3_one_shot_runner.py:_emit_sdf", "phase3_one_shot_runner.py:_step29_tool_arm"),
    "30": ("path_spice_tool.py:run_step30",),
    "32": ("phase3_one_shot_runner.py:step_postroute_repair_librelane",),
    "33": ("phase3_one_shot_runner.py:_step33_tool_arm", "librelane_signoff.py:run"),
    "34": ("phase3_one_shot_runner.py:_emit_metal_fill", "phase3_one_shot_runner.py:_emit_metal_density_report", "librelane_fill_dfm.py:run_fill_insertion"),
    "37": ("phase3_one_shot_runner.py:step_gds", "librelane_step37.py:run"),
    "37.3": ("gds_xor_check.py:main",),
    "31": ("phase3_one_shot_runner.py:step_drc", "phase3_one_shot_runner.py:step_lvs", "phase3_one_shot_runner.py:_emit_erc_report", "perc_corpus_sweep.py:main"),
}

RELEASE_SITES = {
    "14": ("flow_compliance_check.py:main", "synth_handoff_netlist_check.py:main"),
    "16": ("phase3_one_shot_runner.py:emit_clock_plan",),
    "35": ("dfm_screen_check.py:main",),
    "36": ("tapeout_checklist_gen.py:main",),
    "37.4": ("signoff_metrics_aggregate.py:aggregate",),
    "37.5ip": ("digital_hardmacro_gen.py:run", "phase3_one_shot_runner.py:step_ip_release_docs_gen"),
    "37.5ic": ("tapeout_precheck.py:main", "tapeout_docs_gen.py:main", "ic_release_docs_gen.py:main"),
    "38": ("foundry_handoff_pack_gen.py:main",),
    # 39 has a checker but no software producer when FPGA hardware is absent.
    "39": (),
    # 40--44 are physical handoffs.  They are intentionally not represented
    # by a fake Python producer.
    "40": (), "41": (), "42": (), "43": (), "44": (),
}

ENGINE_FAMILIES = {
    "15": ("openroad",), "15.5ic": ("openroad",), "17": ("openroad",),
    "18": ("openroad",), "19": ("openroad",), "20": ("openroad",),
    "21": ("openroad",), "22": ("openroad",), "23": ("opensta",),
    "24": ("openroad",), "25": ("openroad",), "26": ("openroad",),
    "26.5ic": ("openroad",), "27": ("opensta",), "28": ("openroad",),
    "29": ("iverilog",), "30": ("opensta", "ngspice"), "32": ("openroad",),
    "33": ("opensta",), "34": ("openroad",), "37": ("magic", "klayout"),
    "37.3": ("klayout",), "31": ("magic", "klayout", "netgen"),
}
RELEASE_FAMILIES = {
    "14": ("yosys",), "16": ("opensta",), "35": ("klayout",),
    "36": ("vibeic",), "37.4": ("vibeic",), "37.5ip": ("magic", "opensta"),
    "37.5ic": ("vibeic",), "38": ("vibeic",), "39": ("fpga",),
    "40": ("foundry",), "41": ("ate",), "42": ("assembly",),
    "43": ("ate",), "44": ("qualification",),
}


def _summary(items: object) -> tuple[dict, ...]:
    if isinstance(items, dict):
        items = items.get("items", ())
    if not isinstance(items, list):
        return ()
    return tuple({"id": str(x.get("id")), "kind": x.get("kind"),
                  "destination": x.get("declared_destination")}
                 for x in items if isinstance(x, dict) and x.get("id"))


def _route_markers(route_receipt: dict | None) -> set[str]:
    """Normalize the route receipt's exact file markers without guessing a path."""
    receipt = route_receipt if isinstance(route_receipt, dict) else {}
    values = []
    for key in ("marker", "route_marker", "route_file", "selected_marker"):
        if receipt.get(key) is not None:
            values.append(receipt[key])
    for key in ("markers", "files", "route_files", "required_outputs", "outputs"):
        value = receipt.get(key)
        if isinstance(value, (list, tuple, set)):
            values.extend(value)
        elif isinstance(value, str):
            values.append(value)
    found = set()
    for value in values:
        text = str(value).replace("\\", "/")
        if text.endswith("NO_TEMPLATE.txt") or text == "NO_TEMPLATE":
            found.add("NO_TEMPLATE")
        if text.endswith("SELF_TAPEOUT.txt") or text == "SELF_TAPEOUT":
            found.add("SELF_TAPEOUT")
        if "/slots/" in "/" + text or text.startswith("slots/") or text == "slots":
            found.add("slots")
    return found


def _owner_attested(declaration: dict | None, value: object) -> bool:
    if not isinstance(declaration, dict):
        return False
    answers = declaration.get("answers")
    provenance = declaration.get("answer_provenance")
    record = provenance.get("deliverable") if isinstance(provenance, dict) else None
    answered_by = record.get("answered_by") if isinstance(record, dict) else None
    return (isinstance(answers, dict) and answers.get("deliverable") == value and
            answered_by in {"owner", "owner_attestation", "OWNER"})


def _applicability(step: str, *, release: bool, route_receipt: dict | None = None,
                   declaration: dict | None = None) -> dict[str, str]:
    """Apply the flow's condition boundary from current route evidence.

    A source-only registration without those inputs is ``unknown``.  It is
    never silently converted to an IP/IC route by the catalogue.
    """
    answers = (declaration or {}).get("answers", {}) if isinstance(declaration, dict) else {}
    deliverable = answers.get("deliverable")
    markers = _route_markers(route_receipt)
    condition_seen = bool(markers & {"NO_TEMPLATE", "SELF_TAPEOUT", "slots"})
    if step == "37.5ip":
        if deliverable == "DIE" and _owner_attested(declaration, "DIE"):
            return {"IC": "inapplicable: owner-attested DIE", "IP": "inapplicable: owner-attested DIE"}
        if not condition_seen:
            return {"IC": "unknown: route marker and deliverable declaration required",
                    "IP": "unknown: route marker and deliverable declaration required"}
        return {"IC": "applicable", "IP": "applicable"}
    if step in {"15.5ic", "26.5ic", "37.5ic"}:
        if deliverable == "HARDMACRO":
            return {"IC": "inapplicable: owner-attested HARDMACRO",
                    "IP": "inapplicable: owner-attested HARDMACRO"}
        if not condition_seen:
            return {"IC": "unknown: route marker and deliverable declaration required",
                    "IP": "unknown: route marker and deliverable declaration required"}
        return {"IC": "applicable", "IP": "inapplicable: IC route row"}
    if step == "39":
        return {"IC": "applicable: design-dependent FPGA evidence; absent hardware is excluded/NOT_MEASURED",
                "IP": "applicable: design-dependent FPGA evidence; absent hardware is excluded/NOT_MEASURED"}
    if step in {"40", "41", "42", "43", "44"}:
        return {"IC": "applicable: external physical handoff", "IP": "inapplicable: physical IC delivery lane"}
    return {"IC": "applicable", "IP": "applicable"}


def _backend(step: str) -> dict:
    row = BACKEND_ROWS[step]
    p = row["portfolio_policy"]
    return {
        "family": "backend",
        "step_id": step,
        "arm_id": "backend_37_librelane" if step == "37" else "backend_" + step.replace(".", "_"),
        "tool_id": "opensta" if step == "33" else "ngspice" if step == "30" else "klayout" if step == "37.3" else "vibeic" if step == "31" else "librelane",
        "engine_families": list(ENGINE_FAMILIES[step]),
        "default_rank": 0,
        "disposition": "implemented",
        "runtime_status": "NOT_MEASURED",
        "producer_sites": list(BACKEND_SITES[step]),
        "consumer_gates": list(p["mandatory_gate_programs"]),
        "canonical_outputs": list(row["canonical_row"].get("required_outputs", ())),
        "applicability": _applicability(step, release=False),
        "harvest": list(_summary(row.get("original_harvest"))),
        "notes": "One complete producer; wrappers/checkers sharing an engine family are not additional Ultra arms.",
    }


def _release(step: str) -> dict:
    row = RELEASE_ROWS[step]
    p = row["policy"]
    disposition = "implemented" if RELEASE_SITES[step] else "external" if step in {"40", "41", "42", "43", "44"} else "unavailable"
    notes = {
        "37.5ip": "Magic WriteLEF/write_abstract_lef plus STAPostPNR; preserve PG annotation because GDS route drops USE. Native engine receipt required.",
        "39": "Existing absent-FPGA exclusion is retained; no software producer is invented.",
    }.get(step, "Source-owned release composition; runtime qualification remains receipt-bound.")
    return {
        "family": "release", "step_id": step, "arm_id": "release_" + step.replace(".", "_"),
        "tool_id": "magic" if step == "37.5ip" else "vibeic" if disposition == "implemented" else "external",
        "engine_families": list(RELEASE_FAMILIES[step]), "default_rank": 0,
        "disposition": disposition, "runtime_status": "NOT_MEASURED",
        "producer_sites": list(RELEASE_SITES[step]),
        "consumer_gates": list(p["mandatory_gate_programs"]),
        "canonical_outputs": list(row["canonical"].get("required_outputs", ())),
        "applicability": _applicability(step, release=True),
        "harvest": list(_summary(row.get("harvest"))), "notes": notes,
    }


def coverage_rows() -> list[dict]:
    return ([_backend(s) for s in BACKEND_IDS] +
            [_release(s) for s in RELEASE_IDS if s in RELEASE_ROWS])


def coverage_table() -> dict:
    rows = coverage_rows()
    return {"schema": "vibeic/provider-coverage/1", "row_count": len(rows),
            "backend_row_count": len(BACKEND_IDS), "release_row_count": len(RELEASE_IDS),
            "rows": rows}


__all__ = ["BACKEND_IDS", "RELEASE_IDS", "coverage_rows", "coverage_table"]
