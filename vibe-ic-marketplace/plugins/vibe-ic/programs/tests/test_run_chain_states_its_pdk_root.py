"""Every LibreLane step run states its PDK root (FX_RUN_CHAIN_PDK_ROOT, W22).

THE DEFECT. `librelane_contract.run_chain` passed `--pdk-root` only when a
caller gave one, and most production callers gave none, so LibreLane's per-step
CLI took `--pdk-root` from the IMAGE's `PDK_ROOT` at import time -- a value
nothing in the run stated or recorded -- on the default chip path (steps 15,
15.5ic, 17, 19-21, 26, 26.5ic, 32, 34, 37 and sign-off).

THE RULE. `run_chain` refuses a missing root (`LL_PDK_ROOT_UNSTATED`), always
passes it to the CLI, and records it per step (`pdk_root.json`). The ratchet
below finds every call of `librelane_contract.run_chain` from the AST by what
the callee IS (its import binding), not by its name -- `fault_scan_chain_insert`
has its own, unrelated `run_chain` -- and requires each to pass `pdk_root`.
"""
import ast
import json
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))
import librelane_contract as ll  # noqa: E402

TARGET_MODULE, TARGET = "librelane_contract", "run_chain"


def _pairs(node):
    """(target, value) pairs of an assignment, tuples zipped element-wise."""
    if isinstance(node, ast.Assign):
        targets, value = node.targets, node.value
    elif isinstance(node, ast.AnnAssign) and node.value is not None:
        targets, value = [node.target], node.value
    else:
        return []
    out = []
    for t in targets:
        if (isinstance(t, (ast.Tuple, ast.List)) and isinstance(value, (ast.Tuple, ast.List))
                and len(t.elts) == len(value.elts)):
            out += list(zip(t.elts, value.elts))
        else:
            out.append((t, value))
    return out


_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)


def _is_import_module_call(value) -> bool:
    return (isinstance(value, ast.Call)
            and (getattr(value.func, "attr", None) == "import_module"
                 or getattr(value.func, "id", None) in ("import_module", "__import__"))
            and bool(value.args) and isinstance(value.args[0], ast.Constant)
            and value.args[0].value == TARGET_MODULE)


def run_chain_calls(tree: ast.AST):
    """(calls of librelane_contract.run_chain, other uses of it) in `tree`.

    Resolved through BINDINGS, never names, and per Python SCOPE -- a name is
    the module only where the nearest function binding it binds it to the
    module (`_ll` is the module in one phase-3 function and a dict in another):
      * `import librelane_contract [as X]` and `X = importlib.import_module(
        "librelane_contract")` bind the module to a name;
      * an assignment of a module reference binds the module to its target:
        a name (`lc2 = lc`) or an attribute (`self.lc = lc`, tuples zipped),
        and an attribute so bound is the module wherever its NAME is read
        (`self.lc`, `arm.lc`) -- a conservative over-approximation, which the
        member pin below makes visible if it ever over-reaches;
      * local function return tuples and arguments carry those same bindings;
      * `from librelane_contract import run_chain [as Y]` binds the function,
        as does an alias that is actually called;
      * an installed tracing wrapper may forward the original callable's
        arguments unchanged. Its forwarding call remains in the population.
    A call is `<module ref>.run_chain(...)` or `Y(...)`. Everything else that
    could reach the function is returned as an UNRESOLVABLE use, which fails
    the ratchet: `.run_chain` read off a base that is not some OTHER imported
    module and not a resolved call, the bound function used as a value, and a
    module reference handed on other than by an attribute read or a resolved
    assignment/known local handoff (e.g. given to an opaque callable, or
    stored in a container)."""
    parent, scope_of, nodes = {}, {}, []
    stack = [(tree, tree)]
    while stack:                             # one pass: parents and scopes
        node, scope = stack.pop()
        nodes.append(node)
        inner = node if isinstance(node, _SCOPES) else scope
        for child in ast.iter_child_nodes(node):
            parent[id(child)] = node
            scope_of[id(child)] = inner
            stack.append((child, inner))
    scope_of[id(tree)] = tree
    chains = {}

    def chain(scope):
        key = id(scope)
        if key not in chains:
            chains[key] = [scope] if scope is tree else [scope] + chain(scope_of[id(scope)])
        return chains[key]

    binds: dict = {}                         # {id(scope): {name: {kinds}}}

    def bind(scope, name, kind) -> bool:
        kinds = binds.setdefault(id(scope), {}).setdefault(name, set())
        if kind in kinds:
            return False
        kinds.add(kind)
        return True

    def kinds_of(e):
        for sc in chain(scope_of[id(e)]):
            k = binds.get(id(sc), {}).get(e.id)
            if k:
                return k
        return set()

    def binding_scope(e):
        return next((sc for sc in chain(scope_of[id(e)])
                     if e.id in binds.get(id(sc), {})), None)

    mod_attrs, pairs, functions, returns, return_values = {}, [], {}, {}, {}

    def is_module(e):
        if isinstance(e, ast.Name):
            kinds = kinds_of(e)
            return "module" in kinds and not kinds - {"module", "parameter"}
        if isinstance(e, ast.Attribute):
            kinds = mod_attrs.get(e.attr, set())
            return "module" in kinds and not kinds - {"module", "parameter"}
        return False

    def is_chain(e):
        if isinstance(e, ast.Name):
            kinds = kinds_of(e)
            return "chain" in kinds and not kinds - {"chain", "parameter"}
        return isinstance(e, ast.Attribute) and e.attr == TARGET and is_module(e.value)

    def local_functions(e):
        if not isinstance(e, ast.Name):
            return []
        kinds = kinds_of(e)
        if any(k != "parameter" and k not in functions for k in kinds):
            return []
        return [functions[k] for k in kinds if k in functions]

    def merge(a, b):
        if not a:
            return b
        if not b:
            return a
        if isinstance(a, tuple) and isinstance(b, tuple) and len(a) == len(b):
            return tuple(merge(x, y) for x, y in zip(a, b))
        if isinstance(a, set) and isinstance(b, set):
            return a | b
        return {"opaque"}                    # incompatible return shapes

    def value_of(e):
        if isinstance(e, ast.Name):
            return kinds_of(e)
        if isinstance(e, (ast.Tuple, ast.List)):
            return tuple(value_of(x) for x in e.elts)
        if is_module(e) or _is_import_module_call(e):
            return {"module"}
        if is_chain(e):
            return {"chain"}
        if isinstance(e, ast.Attribute):
            return set()                    # another assignment may bind it
        if isinstance(e, ast.Call):
            callees = local_functions(e.func)
            if not callees:
                return {"opaque"} if isinstance(e.func, ast.Name) and kinds_of(e.func) else set()
            value = set()
            for func in callees:
                value = merge(value, returns.get(id(func), set()))
            return value
        return {"other"}

    def bind_value(sc, target, value):
        if isinstance(target, (ast.Tuple, ast.List)):
            if isinstance(value, tuple) and len(target.elts) == len(value):
                return any_changed([bind_value(sc, t, v) for t, v in zip(target.elts, value)])
            return False
        if isinstance(target, ast.Name) and isinstance(value, set):
            return any_changed([bind(sc, target.id, k) for k in value])
        if (isinstance(target, ast.Attribute) and isinstance(value, set)
                and ("module" in value or target.attr in mod_attrs)):
            prior = mod_attrs.get(target.attr, set())
            if prior | value != prior:
                mod_attrs[target.attr] = prior | value
                return True
        return False

    def contains_module(value):
        return (any(contains_module(v) for v in value) if isinstance(value, tuple)
                else "module" in value)

    def binding_shape(target, value):
        if isinstance(target, (ast.Tuple, ast.List)):
            return (isinstance(value, tuple) and len(target.elts) == len(value)
                    and all(binding_shape(t, v) for t, v in zip(target.elts, value)))
        return (isinstance(target, (ast.Name, ast.Attribute)) and isinstance(value, set)
                and ("module" not in value or not value - {"module", "parameter"}))

    def any_changed(changes):
        return any(changes)                  # all bindings must be evaluated

    def arguments(call, func):
        pos = [*func.args.posonlyargs, *func.args.args]
        out = []
        for param, value in zip(pos, call.args):
            if isinstance(value, ast.Starred):
                break                       # following positions are unknown
            out.append((param, value))
        named = {p.arg: p for p in [*pos, *func.args.kwonlyargs]}
        out += [(named[k.arg], k.value) for k in call.keywords if k.arg in named]
        return out

    for node in nodes:
        sc = scope_of[id(node)]
        if isinstance(node, ast.Import):
            for alias in node.names:
                bind(sc, alias.asname or alias.name.split(".")[0],
                     "module" if alias.name == TARGET_MODULE else "other_module")
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if node.module == TARGET_MODULE and alias.name == TARGET:
                    bind(sc, alias.asname or alias.name, "chain")
                else:
                    bind(sc, alias.asname or alias.name, "other_module")
        elif isinstance(node, _SCOPES):
            if not isinstance(node, ast.Lambda):
                key = f"local:{id(node)}"
                if node.decorator_list:
                    bind(sc, node.name, "opaque")
                else:
                    functions[key] = node
                    bind(sc, node.name, key)
            for a in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs,
                      *filter(None, (node.args.vararg, node.args.kwarg))):
                bind(node, a.arg, "parameter")
        for target, value in _pairs(node):
            pairs.append((sc, target, value))
            if isinstance(target, ast.Name) and _is_import_module_call(value):
                bind(sc, target.id, "module")
        if isinstance(node, ast.Return):
            return_values.setdefault(id(sc), []).append(node.value)
    def finish(value):
        return tuple(finish(v) for v in value) if isinstance(value, tuple) else value or {"opaque"}

    consumed, changed, finished = set(), True, False
    while changed:                           # bindings may chain
        changed = False
        for sc, target, value in pairs:
            changed |= bind_value(sc, target, value_of(value))
            if is_module(value) and isinstance(target, (ast.Name, ast.Attribute)):
                consumed.add(id(value))
        for node in nodes:
            if isinstance(node, ast.Call):
                for func in local_functions(node.func):
                    for param, value in arguments(node, func):
                        changed |= bind_value(func, ast.Name(id=param.arg), value_of(value))
                        if is_module(value) or is_chain(value):
                            consumed.add(id(value))
        for func in functions.values():
            value = set()
            for expression in return_values.get(id(func), ()):
                value = merge(value, value_of(expression))
            if value != returns.get(id(func), set()):
                returns[id(func)] = value
                changed = True
        if not changed and not finished:
            # Delay unknown assignments until known return/argument bindings
            # have settled, then propagate their ambiguity through aliases.
            for sc, target, value in pairs:
                changed |= bind_value(sc, target, finish(value_of(value)))
            finished = True
    for node in nodes:                       # every other Store binds a non-module
        if (isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)
                and not binds.get(id(scope_of[id(node)]), {}).get(node.id)):
            bind(scope_of[id(node)], node.id, "other")
    # A producer-call value must reach a binding we actually model. Knowing
    # what it returns cannot excuse handing that value to an unknown consumer.
    for _, target, value in pairs:
        if isinstance(value, ast.Call) and binding_shape(target, value_of(value)):
            consumed.add(id(value))
    for node in nodes:
        if isinstance(node, ast.Call):
            for func in local_functions(node.func):
                for param, value in arguments(node, func):
                    if (isinstance(value, ast.Call)
                            and binding_shape(ast.Name(id=param.arg), value_of(value))):
                        consumed.add(id(value))
    uses = [value for _, target, value in pairs
            if id(value) in consumed and contains_module(value_of(value))
            and not binding_shape(target, value_of(value))]
    calls, called = [], set()
    for node in nodes:
        if isinstance(node, ast.Call):
            if hasattr(node, "_run_chain_root_forwarded"):
                del node._run_chain_root_forwarded
            f = node.func
            if is_chain(f):
                calls.append(node)
                called.add(id(f))
    # A callable alias is resolved only when it reaches an actual call.
    # Orphaned aliases and unknown consumers still appear as opaque uses.
    for _, target, value in pairs:
        if isinstance(target, ast.Name) and is_chain(value):
            if any(isinstance(c.func, ast.Name) and c.func.id == target.id
                   and binding_scope(c.func) is scope_of[id(target)]
                   for c in calls):
                consumed.add(id(value))
    reached = {id(f) for n in nodes if isinstance(n, ast.Call) for f in local_functions(n.func)}

    def returned_modules(e):
        if is_module(e):
            return [e]
        if isinstance(e, ast.Call) and contains_module(value_of(e)):
            return [e]                      # a known local producer return
        if isinstance(e, (ast.Tuple, ast.List)):
            return [m for one in e.elts for m in returned_modules(one)]
        return []                           # opaque calls are not return slots

    for node in nodes:
        if isinstance(node, ast.Return) and id(scope_of[id(node)]) in reached and node.value:
            consumed.update(id(e) for e in returned_modules(node.value))
    # Accept a wrapper installation only after proving its sole original-call
    # invocation forwards *args/**kwargs untouched. This is a binding proof,
    # not an exemption for a worker filename or a callable's spelling.
    for _, target, value in pairs:
        if not (isinstance(target, ast.Attribute) and target.attr == TARGET
                and is_module(target.value)):
            continue
        for func in local_functions(value):
            forwarded = [c for c in calls if scope_of[id(c)] is func]
            if len(forwarded) == 1 and _unchanged_forwarding(forwarded[0], func):
                forwarded[0]._run_chain_root_forwarded = True
                consumed.add(id(target))
    for node in nodes:
        if id(node) in called or id(node) in consumed:
            continue
        if isinstance(node, ast.Attribute) and node.attr == TARGET:
            base = node.value
            if not (isinstance(base, ast.Name)
                    and kinds_of(base) - {"parameter"} == {"other_module"}):
                uses.append(node)            # a value, or a base we cannot resolve
        elif (isinstance(node, ast.Name) and "chain" in kinds_of(node)
              and isinstance(node.ctx, ast.Load)):
            uses.append(node)
        elif (isinstance(getattr(node, "ctx", None), ast.Load) and id(node) not in consumed
              and (is_module(node) or isinstance(node, ast.Name) and "module" in kinds_of(node))):
            up = parent.get(id(node))
            if not (isinstance(up, ast.Attribute) and up.value is node):
                uses.append(node)            # the module handed on as a value
        elif isinstance(node, ast.Call) and contains_module(value_of(node)):
            up = parent.get(id(node))
            if not (isinstance(up, ast.Attribute) and up.value is node):
                uses.append(node)            # a producer value handed on opaquely
    calls.sort(key=lambda c: (c.lineno, c.col_offset))
    uses.sort(key=lambda u: (u.lineno, u.col_offset))
    return calls, uses


def _unchanged_forwarding(call, func):
    """A tracing wrapper preserves the original callable's root keyword."""
    args, kwargs = func.args.vararg, func.args.kwarg
    if (not args or not kwargs or func.args.posonlyargs or func.args.args or func.args.kwonlyargs
            or len(call.args) != 1 or len(call.keywords) != 1):
        return False
    positional, keyword = call.args[0], call.keywords[0]
    if not (isinstance(positional, ast.Starred) and isinstance(positional.value, ast.Name)
            and positional.value.id == args.arg and keyword.arg is None
            and isinstance(keyword.value, ast.Name) and keyword.value.id == kwargs.arg):
        return False
    if not any(isinstance(n, ast.Return) and n.value is call for n in ast.walk(func)):
        return False
    forwarded = {id(positional.value), id(keyword.value)}
    return all(id(n) in forwarded for n in ast.walk(func)
               if isinstance(n, ast.Name) and n.id in {args.arg, kwargs.arg})


def call_sites(tree: ast.AST, rel: str):
    """`{"<rel>::<enclosing qualname>": n_calls}` for every resolved call."""
    calls, _ = run_chain_calls(tree)
    wanted = {id(c) for c in calls}
    sites = {}

    def visit(node, scope):
        if id(node) in wanted:
            key = f"{rel}::{'.'.join(scope) or '<module>'}"
            sites[key] = sites.get(key, 0) + 1
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                visit(child, scope + [child.name])
            else:
                visit(child, scope)
    visit(tree, [])
    return sites


def _program_trees():
    """Every shipped program that can reach the function at all.

    A file whose text never spells `run_chain` can neither call it nor read
    it off anything; a module object it hands elsewhere is read as
    `<x>.run_chain` in the receiving file, which is parsed and reports an
    unresolvable base. So the text filter drops nothing the rule can see."""
    for path in sorted(PROGRAMS.rglob("*.py")):
        if "tests" in path.relative_to(PROGRAMS).parts or path.name == "librelane_contract.py":
            continue
        text = path.read_text(encoding="utf-8")
        if TARGET in text:
            yield path, ast.parse(text)


def _none_default_params(func) -> set:
    """Parameters of `func` whose default is the literal None (or "")."""
    if not isinstance(func, _SCOPES):
        return set()
    a = func.args
    pos = [*a.posonlyargs, *a.args]
    out = {p.arg for p, d in zip(pos[len(pos) - len(a.defaults):], a.defaults)
           if isinstance(d, ast.Constant) and d.value in (None, "")}
    out |= {p.arg for p, d in zip(a.kwonlyargs, a.kw_defaults)
            if isinstance(d, ast.Constant) and d.value in (None, "")}
    return out


def _states_root(call: ast.Call, func=None) -> bool:
    """`pdk_root=` is passed, is not a None/"" literal, and -- when `func`
    (the enclosing function) is given -- is not forwarded from a parameter
    of it whose default is None: such a call can still pass None, and only
    the runtime refusal would say so."""
    kw = {k.arg: k.value for k in call.keywords}
    value = kw.get("pdk_root")
    if value is None:
        return bool(getattr(call, "_run_chain_root_forwarded", False))
    if isinstance(value, ast.Constant) and value.value in (None, ""):
        return False
    return not (isinstance(value, ast.Name) and value.id in _none_default_params(func))


def _enclosing_functions(tree: ast.AST) -> dict:
    """{id(call): nearest enclosing function node} for every Call."""
    out = {}

    def visit(node, func):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.Call):
                out[id(child)] = func
            visit(child, child if isinstance(child, _SCOPES) else func)
    visit(tree, None)
    return out


#: THE POPULATION, BY MEMBER: every production call of
#: `librelane_contract.run_chain`, as `{"<file>::<enclosing def>": n_calls}`.
#: A call that appears, disappears or moves changes this map and reddens the
#: ratchet until it is re-pinned by name -- a count floor let six members
#: leave the resolver's view unnoticed (analog_a6's `self.lc.run_chain` was
#: one of them). Includes the traced worker's unchanged forwarding call.
EXPECTED_CALL_SITES = {
    '_native373_current.py::produce': 2,
    '_ppa/synthesis.py::run_exploration': 1,
    'analog_a6_librelane_drc.py::_Arm.run': 1,
    'analog_a7_post_layout_emit.py::run': 1,
    'design_one_shot_runner.py::step_rtl_lint_tool': 1,
    'execution_backend_producers.py::_cts_split': 1,
    'execution_backend_producers.py::_state_chain': 1,
    'execution_backend_producers.py::produce_pnr': 1,
    'execution_native_worker.py::execute._traced_run_chain': 1,
    'librelane_cts_hold.py::execute': 2,
    'librelane_eqy.py::run_eqy': 1,
    'librelane_fill_dfm.py::run_density': 1,
    'librelane_fill_dfm.py::default_stream': 1,
    'librelane_fill_dfm.py::run_fill_insertion': 1,
    'librelane_ir_antenna.py::run_antenna_gds': 1,
    'librelane_ir_antenna.py::run_antenna_router': 1,
    'librelane_ir_antenna.py::run_ir': 2,
    'librelane_ir_antenna.py::run_sealring': 1,
    'librelane_ir_antenna.py::xor_sealed': 1,
    'librelane_postroute.py::gate_level_sim': 1,
    'librelane_postroute_repair.py::_candidate': 1,
    'librelane_prelayout.py::run_prelayout': 1,
    'librelane_pv_signoff.py::run_database_unit': 1,
    'librelane_pv_signoff.py::run_finishing_xor': 1,
    'librelane_pv_signoff.py::run_half': 1,
    'librelane_pv_signoff.py::run_mixed_top': 1,
    'librelane_route.py::execute._route': 1,
    'librelane_route.py::execute._route._ll_arm': 2,
    'librelane_signoff.py::run': 1,
    'librelane_step37.py::_run': 1,
    'phase3_one_shot_runner.py::_prepare_librelane_floorplan_for_route': 2,
    'phase3_one_shot_runner.py::_select_placement_arm.librelane_arm': 1,
    'phase3_one_shot_runner.py::_select_placement_arm.openroad_arm': 1,
    'phase3_one_shot_runner.py::_step_synth_librelane': 1,
}


def test_every_run_chain_call_states_its_pdk_root():
    missing, opaque, sites = [], [], {}
    for path, tree in _program_trees():
        rel = str(path.relative_to(PROGRAMS))
        calls, uses = run_chain_calls(tree)
        sites.update(call_sites(tree, rel))
        enclosing = _enclosing_functions(tree)
        missing += [f"{rel}:{c.lineno}" for c in calls
                    if not _states_root(c, enclosing.get(id(c)))]
        opaque += [f"{rel}:{u.lineno}" for u in uses]
    assert sites == EXPECTED_CALL_SITES, (
        f"the run_chain call population moved: added "
        f"{ {k: v for k, v in sites.items() if EXPECTED_CALL_SITES.get(k) != v} }, "
        f"removed or changed "
        f"{ {k: v for k, v in EXPECTED_CALL_SITES.items() if sites.get(k) != v} }")
    assert not missing, f"run_chain calls with no pdk_root: {missing}"
    assert not opaque, f"run_chain reachable other than by a resolved call: {opaque}"


def test_the_resolver_follows_bindings_not_names():
    tree = ast.parse(
        "import importlib\n"
        "import librelane_contract as _ll\n"
        "from librelane_contract import run_chain as rc\n"
        "def run_chain(*a): pass\n"               # a local function, not ours
        "_ll.run_chain(p, i, s, pdk_root='/pdk')\n"
        "rc(p, i, s)\n"
        "run_chain(p)\n"
        "f = _ll.run_chain\n"
        "c = importlib.import_module('librelane_contract')\n"
        "c.run_chain(p, i, s)\n")
    calls, uses = run_chain_calls(tree)
    assert [c.lineno for c in calls] == [5, 6, 10]
    assert [_states_root(c) for c in calls] == [True, False, False]
    assert [u.lineno for u in uses] == [8]
    fault = ast.parse((PROGRAMS / "fault_scan_chain_insert.py").read_text())
    assert run_chain_calls(fault) == ([], [])


def test_run_chain_refuses_an_unstated_root(tmp_path, monkeypatch):
    monkeypatch.setattr(ll, "image_capability", lambda *a, **k: pytest.fail(
        "nothing may run before the root is stated"))
    for root in (None, "", "pdk"):
        with pytest.raises(ll.Refusal, match="LL_PDK_ROOT_UNSTATED"):
            ll.run_chain(tmp_path, "img", [("OpenROAD.Floorplan", tmp_path / "c.json",
                                            tmp_path / "s.json")], pdk_root=root)


def test_run_chain_passes_and_records_the_stated_root(tmp_path, monkeypatch):
    """The CLI gets `--pdk-root <stated>`, and the step folder records it
    with the host mount beneath it."""
    config = tmp_path / "c.json"
    config.write_text(json.dumps({"meta": {"step": "OpenROAD.Floorplan"}}))
    state = tmp_path / "s.json"
    state.write_text(json.dumps({}))
    host = tmp_path / "pdkroot" / "procA"
    host.mkdir(parents=True)
    argv = []

    def container(cmd, **_kw):
        argv.append(cmd)
        folder = Path(cmd[cmd.index("-o") + 1])
        (folder / "state_out.json").write_text(json.dumps({}))
        return ll.subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(ll, "image_capability", lambda *a, **k: {})
    monkeypatch.setattr(ll, "openroad_home", lambda *a, **k: None)
    monkeypatch.setattr(ll, "_check_state", lambda *a, **k: None)
    monkeypatch.setattr(ll, "run_container", container)
    folders = ll.run_chain(tmp_path, "img", [("OpenROAD.Floorplan", config, state)],
                           mounts=[(host, "/pdk/procA")], pdk_root="/pdk")
    cmd = argv[0]
    assert cmd[-2:] == ["--pdk-root", "/pdk"]
    assert cmd[cmd.index("--pdk-root") + 1] == "/pdk"
    record = json.loads((folders[0] / "pdk_root.json").read_text())
    assert record["cli_pdk_root"] == "/pdk"
    assert record["mounts_under_it"] == [[str(host.resolve()), "/pdk/procA"]]


def test_local_run_chain_resolves_the_cli_root_from_the_whole_root_mount(tmp_path, monkeypatch):
    config = tmp_path / "c.json"
    config.write_text(json.dumps({"meta": {"step": "OpenROAD.Floorplan"}}))
    state = tmp_path / "s.json"
    state.write_text(json.dumps({}))
    host_root = tmp_path / "pdkroot"
    (host_root / "pdkX").mkdir(parents=True)
    argv = []

    def local_tool(cmd, **_kw):
        argv.append(cmd)
        folder = Path(cmd[cmd.index("-o") + 1])
        (folder / "state_out.json").write_text(json.dumps({}))
        return ll.subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(ll, "image_capability", lambda *a, **k: {})
    monkeypatch.setattr(ll, "openroad_home", lambda *a, **k: None)
    monkeypatch.setattr(ll, "_check_state", lambda *a, **k: None)
    monkeypatch.setattr(ll, "run_container", local_tool)
    monkeypatch.setattr(ll._ce, "no_container_route", lambda: True)
    monkeypatch.setattr(ll, "local_image_attestation", lambda *a, **k: {"image": "img"})

    folders = ll.run_chain(tmp_path, "img", [("OpenROAD.Floorplan", config, state)],
                           mounts=[(host_root, "/pdk")], pdk_root="/pdk")
    cmd = argv[0]
    assert cmd[cmd.index("--pdk-root") + 1] == str(host_root.resolve())
    record = json.loads((folders[0] / "pdk_root.json").read_text())
    assert record["execution_route"] == "LOCAL"
    assert record["cli_pdk_root"] == str(host_root.resolve())
    assert record["requested_pdk_root"] == "/pdk"
    assert record["requested_mounts"] == [[str(host_root.resolve()), "/pdk"]]


def test_the_resolver_follows_module_bindings_through_attributes_and_scopes():
    """The a6 form: the module bound to an attribute and read back through
    it, on the same object and on another. And the phase-3 form: a name that
    is the module in one function and a dict in another."""
    tree = ast.parse(
        "class Arm:\n"
        "    def __init__(self):\n"
        "        import librelane_contract as lc\n"
        "        self.lc, self.x = lc, 1\n"
        "    def run(self):\n"
        "        return self.lc.run_chain(p, i, s)\n"            # 6: call, no root
        "def outer(arm):\n"
        "    lc = arm.lc\n"
        "    lc.run_chain(p, i, s, pdk_root='/pdk')\n"         # 9: call, root
        "def f():\n"
        "    import librelane_contract as _ll\n"
        "    _ll.run_chain(p, i, s, pdk_root=r)\n"             # 12: call, root
        "def g():\n"
        "    _ll = {'folder': 1}\n"
        "    return _ll['folder']\n"                           # 15: a dict, not ours
        "def h(obj):\n"
        "    return obj.run_chain(p)\n"                        # 17: unresolvable base
        "def k():\n"
        "    import librelane_contract as m\n"
        "    use(m)\n")                                        # 20: module handed on
    calls, uses = run_chain_calls(tree)
    assert [c.lineno for c in calls] == [6, 9, 12]
    assert [_states_root(c) for c in calls] == [False, True, True]
    assert [u.lineno for u in uses] == [17, 20]
    assert call_sites(tree, "x.py") == {"x.py::Arm.run": 1, "x.py::outer": 1,
                                        "x.py::f": 1}


def test_a_root_forwarded_from_a_none_default_parameter_is_not_stated():
    tree = ast.parse(
        "import librelane_contract as ll\n"
        "def a(p, *, pdk_root=None):\n"
        "    ll.run_chain(p, i, s, pdk_root=pdk_root)\n"
        "def b(p, *, pdk_root):\n"
        "    ll.run_chain(p, i, s, pdk_root=pdk_root)\n"
        "def c(p, pdk_root=None):\n"
        "    ll.run_chain(p, i, s, pdk_root=pdk_root or ll.PDK_GUEST_ROOT)\n")
    calls, _ = run_chain_calls(tree)
    enclosing = _enclosing_functions(tree)
    assert [_states_root(c, enclosing.get(id(c))) for c in calls] == [False, True, True]


_MODULE_HANDOFF = """\
def supplier():
    import librelane_contract as contract
    return 'tag', contract
def consume(contract):
    return contract.run_chain(p, i, s, pdk_root='/pdk')
tag, contract = supplier()
consume(contract)
"""


def test_the_resolver_follows_local_module_returns_and_parameters():
    tree = ast.parse(_MODULE_HANDOFF)
    calls, uses = run_chain_calls(tree)
    assert call_sites(tree, 'neutral.py') == {'neutral.py::consume': 1}
    assert len(calls) == 1 and _states_root(calls[0])
    assert uses == []
    unrelated = ast.parse(_MODULE_HANDOFF.replace('librelane_contract', 'fault_scan_chain_insert'))
    assert run_chain_calls(unrelated) == ([], [])


@pytest.mark.parametrize('change', [
    'unknown_return', 'unknown_return_consumer', 'unknown_consumer', 'opaque_return_recipient',
    'mixed_argument', 'mixed_callable_argument',
    'expanded_argument', 'decorated_supplier',
])
def test_module_handoffs_do_not_resolve_opaque_paths(change):
    source = _MODULE_HANDOFF
    if change == 'unknown_return':
        source = source.replace("return 'tag', contract", "return 'tag', opaque_factory()")
    elif change == 'unknown_return_consumer':
        source = source.replace("return 'tag', contract", "return 'tag', opaque_consumer(contract)")
    elif change == 'unknown_consumer':
        source += 'opaque_consumer(contract)\n'
    elif change == 'opaque_return_recipient':
        source += 'opaque_consumer(supplier())\n'
    elif change == 'mixed_argument':
        source += 'consume(None)\n'
    elif change == 'mixed_callable_argument':
        source += 'consume(contract.run_chain)\n'
    elif change == 'expanded_argument':
        source = source.replace('consume(contract)\n', 'consume(*opaque_arguments, contract)\n')
    else:
        source = source.replace('def supplier():', '@opaque_decorator\ndef supplier():')
    calls, uses = run_chain_calls(ast.parse(source))
    assert uses, 'an unknown module or consumer must remain visible to the audit'
    if change not in ('unknown_consumer', 'opaque_return_recipient'):
        assert calls == []


_TRACED_CHAIN = """\
import librelane_contract as contract
original = contract.run_chain
def traced(*args, **kwargs):
    journal['entered'] = True
    return original(*args, **kwargs)
contract.run_chain = traced
"""


def test_an_installed_tracing_wrapper_preserves_the_root_contract():
    tree = ast.parse(_TRACED_CHAIN)
    calls, uses = run_chain_calls(tree)
    assert call_sites(tree, 'neutral.py') == {'neutral.py::traced': 1}
    assert len(calls) == 1 and _states_root(calls[0])
    assert uses == []
    unrelated = ast.parse(_TRACED_CHAIN.replace('librelane_contract', 'fault_scan_chain_insert'))
    assert run_chain_calls(unrelated) == ([], [])


@pytest.mark.parametrize('change', [
    'uninstalled', 'drop_kwargs', 'mutate_kwargs', 'replace_root',
    'named_root', 'rebound_original', 'decorated_wrapper', 'opaque_call',
])
def test_a_wrapper_cannot_hide_missing_or_replaced_root_arguments(change):
    source = _TRACED_CHAIN
    if change == 'uninstalled':
        source = source.replace('contract.run_chain = traced', '')
    elif change == 'drop_kwargs':
        source = source.replace('original(*args, **kwargs)', 'original(*args)')
    elif change == 'mutate_kwargs':
        source = source.replace("journal['entered'] = True", "kwargs.pop('pdk_root', None)")
    elif change == 'replace_root':
        source = source.replace('original(*args, **kwargs)', 'original(*args, pdk_root=None, **kwargs)')
    elif change == 'named_root':
        source = source.replace('def traced(*args, **kwargs):', 'def traced(*args, pdk_root=None, **kwargs):')
    elif change == 'rebound_original':
        source = source.replace('def traced(*args, **kwargs):',
                                'original = opaque_factory()\ndef traced(*args, **kwargs):')
    elif change == 'decorated_wrapper':
        source = source.replace('def traced(*args, **kwargs):', '@opaque_decorator\ndef traced(*args, **kwargs):')
    else:
        source = source.replace('original(*args, **kwargs)', 'opaque_call(*args, **kwargs)')
    tree = ast.parse(source)
    calls, uses = run_chain_calls(tree)
    enclosing = _enclosing_functions(tree)
    assert uses or any(not _states_root(c, enclosing.get(id(c))) for c in calls)


@pytest.mark.parametrize('rel', [
    '_native373_current.py', 'execution_backend_producers.py',
    'execution_native_worker.py', 'librelane_fill_dfm.py', 'librelane_pv_signoff.py',
])
@pytest.mark.parametrize('mutation', ['remove_root', 'unrelated_module'])
def test_real_handoffs_and_wrapper_cannot_leave_the_root_audit(rel, mutation):
    """Mutate shipped source ASTs, including the worker's forwarding call."""
    tree = ast.parse((PROGRAMS / rel).read_text())
    calls, uses = run_chain_calls(tree)
    expected = {k: v for k, v in EXPECTED_CALL_SITES.items() if k.startswith(rel + '::')}
    assert call_sites(tree, rel) == expected
    assert calls and not uses
    enclosing = _enclosing_functions(tree)
    assert all(_states_root(c, enclosing.get(id(c))) for c in calls)
    if mutation == 'remove_root':
        for call in calls:
            call.keywords = [k for k in call.keywords if k.arg not in ('pdk_root', None)]
        changed, _ = run_chain_calls(tree)
        assert call_sites(tree, rel) == expected, 'root removal must not hide the call'
        assert changed and all(not _states_root(c, enclosing.get(id(c))) for c in changed)
    else:
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == TARGET_MODULE:
                        alias.name = 'fault_scan_chain_insert'
            elif isinstance(node, ast.ImportFrom) and node.module == TARGET_MODULE:
                node.module = 'fault_scan_chain_insert'
        assert run_chain_calls(tree) == ([], [])
        assert call_sites(tree, rel) != expected, 'exact member equality must reject the replacement'


def test_a_step_folder_resumes_only_under_the_root_it_was_run_with(tmp_path, monkeypatch):
    """Resume reads `pdk_root.json`: a folder from before the root was recorded
    (the CLI then took the image's PDK_ROOT) or run under another root/mount
    is re-run under the stated one, never handed downstream as if it had been."""
    config = tmp_path / "c.json"
    config.write_text(json.dumps({"meta": {"step": "OpenROAD.Floorplan"}}))
    state = tmp_path / "s.json"
    state.write_text(json.dumps({}))
    host = tmp_path / "pdkroot" / "procA"
    host.mkdir(parents=True)
    runs = []

    def container(cmd, **_kw):
        runs.append(cmd[cmd.index("--pdk-root") + 1])
        folder = Path(cmd[cmd.index("-o") + 1])
        (folder / "state_out.json").write_text(json.dumps({}))
        return ll.subprocess.CompletedProcess(cmd, 0, "fixture native step completed\n", "")

    monkeypatch.setattr(ll, "image_capability", lambda *a, **k: {})
    monkeypatch.setattr(ll, "openroad_home", lambda *a, **k: None)
    monkeypatch.setattr(ll, "_check_state", lambda *a, **k: None)
    monkeypatch.setattr(ll, "run_container", container)

    def chain(root, guest):
        return ll.run_chain(tmp_path, "img", [("OpenROAD.Floorplan", config, state)],
                            mounts=[(host, guest)], pdk_root=root)

    folder = chain("/pdk", "/pdk/procA")[0]
    chain("/pdk", "/pdk/procA")
    assert runs == ["/pdk"], "the same stated root must resume, not re-run"
    if (folder / "pdk_root.json").exists():
        (folder / "pdk_root.json").unlink()  # a folder from before the fix
    chain("/pdk", "/pdk/procA")
    assert runs == ["/pdk", "/pdk"], "an unrecorded root must re-run"
    chain("/other", "/other/procA")
    assert runs == ["/pdk", "/pdk", "/other"], "another root must re-run"
    assert json.loads((folder / "pdk_root.json").read_text())["cli_pdk_root"] == "/other"
