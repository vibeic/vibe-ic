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
      * `from librelane_contract import run_chain [as Y]` binds the function.
    A call is `<module ref>.run_chain(...)` or `Y(...)`. Everything else that
    could reach the function is returned as an UNRESOLVABLE use, which fails
    the ratchet: `.run_chain` read off a base that is not some OTHER imported
    module and not a resolved call, the bound function used as a value, and a
    module reference handed on other than by an attribute read or a resolved
    assignment (e.g. as an argument, or stored in a container)."""
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

    names, mod_attrs, pairs = set(), set(), []

    def is_module(e):
        if isinstance(e, ast.Name):
            return "module" in kinds_of(e)
        return isinstance(e, ast.Attribute) and e.attr in mod_attrs

    for node in nodes:
        sc = scope_of[id(node)]
        if isinstance(node, ast.Import):
            for alias in node.names:
                bind(sc, alias.asname or alias.name.split(".")[0],
                     "module" if alias.name == TARGET_MODULE else "other_module")
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if node.module == TARGET_MODULE and alias.name == TARGET:
                    names.add(alias.asname or alias.name)
                else:
                    bind(sc, alias.asname or alias.name, "other_module")
        elif isinstance(node, _SCOPES):
            for a in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs,
                      *filter(None, (node.args.vararg, node.args.kwarg))):
                bind(node, a.arg, "other")   # parameters bind in their function
        for target, value in _pairs(node):
            pairs.append((sc, target, value))
            if isinstance(target, ast.Name) and _is_import_module_call(value):
                bind(sc, target.id, "module")
    consumed, changed = set(), True
    while changed:                           # bindings may chain
        changed = False
        for sc, target, value in pairs:
            if not is_module(value):
                continue
            consumed.add(id(value))
            if isinstance(target, ast.Name):
                changed |= bind(sc, target.id, "module")
            elif isinstance(target, ast.Attribute) and target.attr not in mod_attrs:
                mod_attrs.add(target.attr)
                changed = True
    for node in nodes:                       # every other Store binds a non-module
        if (isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)
                and "module" not in binds.get(id(scope_of[id(node)]), {}).get(node.id, ())):
            bind(scope_of[id(node)], node.id, "other")
    uses = [value for _, target, value in pairs
            if id(value) in consumed and not isinstance(target, (ast.Name, ast.Attribute))]
    calls, called = [], set()
    for node in nodes:
        if isinstance(node, ast.Call):
            f = node.func
            if ((isinstance(f, ast.Attribute) and f.attr == TARGET and is_module(f.value))
                    or (isinstance(f, ast.Name) and f.id in names)):
                calls.append(node)
                called.add(id(f))
    for node in nodes:
        if id(node) in called:
            continue
        if isinstance(node, ast.Attribute) and node.attr == TARGET:
            base = node.value
            if not (isinstance(base, ast.Name) and kinds_of(base) == {"other_module"}):
                uses.append(node)            # a value, or a base we cannot resolve
        elif isinstance(node, ast.Name) and node.id in names and isinstance(node.ctx, ast.Load):
            uses.append(node)
        elif (isinstance(getattr(node, "ctx", None), ast.Load) and id(node) not in consumed
              and is_module(node)):
            up = parent.get(id(node))
            if not (isinstance(up, ast.Attribute) and up.value is node):
                uses.append(node)            # the module handed on as a value
    calls.sort(key=lambda c: (c.lineno, c.col_offset))
    uses.sort(key=lambda u: (u.lineno, u.col_offset))
    return calls, uses


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
    if value is None or (isinstance(value, ast.Constant) and value.value in (None, "")):
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
#: one of them). 31 calls in 27 functions.
EXPECTED_CALL_SITES = {
    '_ppa/synthesis.py::run_exploration': 1,
    'analog_a6_librelane_drc.py::_Arm.run': 1,
    'analog_a7_post_layout_emit.py::run': 1,
    'design_one_shot_runner.py::step_rtl_lint_tool': 1,
    'librelane_cts_hold.py::execute': 2,
    'librelane_eqy.py::run_eqy': 1,
    'librelane_fill_dfm.py::run_density': 1,
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
