"""Bounded source admission for asserted professional helper observations.

This is not Python execution or functional qualification. It follows only
uniquely bound callables and plain classes in this exact bundle. Unknown data
flow earns no observation credit; native JUnit and tool activity still decide
whether an admitted source actually ran. No import or marker is trusted alone.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, field
import hashlib
from pathlib import Path

_DUT = object()
_UNKNOWN = object()
_BOUND_AGGREGATE = object()


@dataclass(frozen=True)
class _Data:
    reads: frozenset = frozenset()
    literal: object = _UNKNOWN


@dataclass(frozen=True)
class _Port:
    name: str


@dataclass
class _Object:
    module: Path
    node: ast.ClassDef
    fields: dict = field(default_factory=dict)


@dataclass(frozen=True)
class _Function:
    module: Path
    node: object
    receiver: object = None


class _Unestablished(Exception):
    pass


def _reads(value):
    return value.reads if isinstance(value, _Data) else frozenset()


def _joined(values):
    return _Data(frozenset().union(*(_reads(v) for v in values)))


class _Graph:
    def __init__(self, tb, ports, scope_nodes, bound_names, data_inputs):
        self.root = tb.resolve().parent
        self.entry = tb.resolve()
        self.ports = ports
        self.data_inputs = data_inputs
        self.scope_nodes = scope_nodes
        self.bound_names = bound_names
        self.modules = {}
        self.manifest = {}
        self.active = set()
        self.steps = 0
        self.asserted = set()
        self.writes = {}
        self.summaries = {}

    def module(self, path):
        path = Path(path)
        if (path.is_symlink() or path.resolve().parent != self.root
                or path.suffix != '.py'):
            raise _Unestablished('helper is not a regular same-bundle sibling')
        path = path.resolve()
        if path in self.modules:
            return self.modules[path]
        if len(self.modules) >= 16:
            raise _Unestablished('helper module budget exhausted')
        raw = path.read_bytes()
        tree = ast.parse(raw)
        nodes = list(self.scope_nodes(tree.body))
        if any(isinstance(n, ast.ImportFrom) and any(a.name == '*' for a in n.names)
               for n in nodes):
            raise _Unestablished('star-import namespace is ambiguous')
        counts = {}
        for statement in tree.body:
            for name in self.bound_names(list(self.scope_nodes([statement]))):
                counts[name] = counts.get(name, 0) + 1
            # An assignment to a module-level class/method can change the
            # callable without rebinding its bare name.
            for node in ast.walk(statement):
                if isinstance(node, ast.Attribute) and isinstance(node.ctx, (ast.Store, ast.Del)):
                    base = node.value
                    while isinstance(base, ast.Attribute):
                        base = base.value
                    if isinstance(base, ast.Name):
                        counts[base.id] = counts.get(base.id, 0) + 1
        globals_written = {name for node in ast.walk(tree) if isinstance(node, ast.Global)
                           for name in node.names}
        symbols = {name: _UNKNOWN for name in counts}
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if counts.get(node.name) == 1 and node.name not in globals_written:
                    symbols[node.name] = _Function(path, node)
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    name = alias.asname or alias.name.split('.')[0]
                    if counts.get(name) != 1 or name in globals_written:
                        continue
                    if isinstance(node, ast.ImportFrom):
                        if node.level > 1 or not node.module or '.' in node.module:
                            continue
                        sibling, member = node.module, alias.name
                    else:
                        if '.' in alias.name:
                            continue
                        sibling, member = alias.name, None
                    candidate = self.root / (sibling + '.py')
                    if candidate.is_file() and not candidate.is_symlink():
                        symbols[name] = ('import', candidate, member)
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                value = node.value
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    if isinstance(target, ast.Name) and counts.get(target.id) == 1:
                        try:
                            symbols[target.id] = _Data(literal=ast.literal_eval(value))
                        except (ValueError, TypeError):
                            pass
        self.modules[path] = (tree, symbols)
        if path != self.entry:
            self.manifest[path.name] = hashlib.sha256(raw).hexdigest()
        return self.modules[path]

    def name(self, module, env, name):
        value = env.get(name, self.module(module)[1].get(name, _UNKNOWN))
        if isinstance(value, tuple) and value and value[0] == 'import':
            _, path, member = value
            symbols = self.module(path)[1]
            return ('module', path) if member is None else symbols.get(member, _UNKNOWN)
        return value

    def expr(self, node, env, module, awaited=False):
        self.steps += 1
        if self.steps > 8192:
            raise _Unestablished('helper expression budget exhausted')
        if node is None:
            return _Data(literal=None)
        if isinstance(node, ast.Name):
            return self.name(module, env, node.id)
        if isinstance(node, ast.Constant):
            return _Data(literal=node.value)
        if isinstance(node, ast.Await):
            return self.expr(node.value, env, module, awaited=True)
        if isinstance(node, ast.Attribute):
            value = self.expr(node.value, env, module)
            if value is _DUT and node.attr in self.ports:
                return _Port(node.attr)
            if isinstance(value, _Port) and node.attr == 'value':
                return _Data(frozenset([value.name]))
            if isinstance(value, _Data) and node.attr == 'to_bytes':
                return ('data_method', value)
            if isinstance(value, _Object):
                if node.attr in value.fields:
                    return value.fields[node.attr]
                methods = [n for n in value.node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                           and n.name == node.attr]
                if len(methods) == 1:
                    return _Function(value.module, methods[0], value)
            if isinstance(value, tuple) and value and value[0] == 'module':
                return self.module(value[1])[1].get(node.attr, _UNKNOWN)
            return _UNKNOWN
        if isinstance(node, ast.Call):
            if any(isinstance(a, ast.Starred) for a in node.args) or any(k.arg is None for k in node.keywords):
                return _UNKNOWN
            function = self.expr(node.func, env, module)
            args = [self.expr(a, env, module) for a in node.args]
            kwargs = {k.arg: self.expr(k.value, env, module) for k in node.keywords}
            if any(v is _BOUND_AGGREGATE for v in [*args, *kwargs.values()]):
                raise _Unestablished('aggregate DUT aliases are unresolved')
            if len(kwargs) != len(node.keywords):
                return _UNKNOWN
            if isinstance(function, _Function):
                if isinstance(function.node, ast.ClassDef):
                    return self.construct(function, args, kwargs)
                if isinstance(function.node, ast.AsyncFunctionDef) and not awaited:
                    # Creating a coroutine does not execute its body. It earns
                    # neither read nor write credit; an awaited sibling path
                    # must independently establish the returned observation.
                    return _UNKNOWN
                return self.call(function, args, kwargs)
            if isinstance(function, tuple) and function and function[0] == 'data_method':
                return _Data(_reads(function[1]))
            # Only value-preserving builtin conversions propagate observed
            # data. An arbitrary imported function given a read is not trusted.
            builtin = (isinstance(node.func, ast.Name) and node.func.id not in env
                       and node.func.id not in self.module(module)[1])
            if builtin and node.func.id == 'hasattr' and len(args) == 2 and not kwargs:
                # Structural presence is not an observed value, and cannot
                # rebind the statically supplied DUT.
                return _UNKNOWN
            if builtin and node.func.id in {'int', 'bool', 'bytes', 'bytearray', 'list', 'tuple'}:
                return _joined(args)
            if builtin and node.func.id == 'range':
                try:
                    return _Data(literal=range(*(v.literal for v in args)))
                except (AttributeError, TypeError, ValueError):
                    return _UNKNOWN
            if any(v is _DUT or isinstance(v, _Object) for v in [*args, *kwargs.values()]):
                raise _Unestablished('unresolved call can change a DUT binding')
            return _UNKNOWN
        if isinstance(node, ast.IfExp):
            condition = self.expr(node.test, env, module)
            if isinstance(condition, _Data) and condition.literal is not _UNKNOWN:
                return self.expr(node.body if condition.literal else node.orelse, env, module)
            values = [self.expr(n, env, module) for n in [node.body, node.orelse]]
            return _joined(values) if all(_reads(v) for v in values) else _UNKNOWN
        if isinstance(node, ast.BoolOp):
            values = []
            for child in node.values:
                value = self.expr(child, env, module)
                values.append(value)
                if isinstance(value, _Data) and value.literal is not _UNKNOWN:
                    if (isinstance(node.op, ast.And) and not value.literal
                            or isinstance(node.op, ast.Or) and value.literal):
                        break
            return _joined(values)
        if isinstance(node, ast.Subscript):
            value = self.expr(node.value, env, module)
            if value is _BOUND_AGGREGATE:
                return _BOUND_AGGREGATE
            return _joined([value, self.expr(node.slice, env, module)])
        if isinstance(node, (ast.List, ast.Tuple, ast.Set, ast.Dict)):
            values = [self.expr(child, env, module) for child in ast.iter_child_nodes(node) if isinstance(child, ast.expr)]
            if any(v is _DUT or v is _BOUND_AGGREGATE or isinstance(v, _Object) for v in values):
                return _BOUND_AGGREGATE
            return _joined(values)
        if isinstance(node, (ast.BinOp, ast.UnaryOp, ast.Compare, ast.List, ast.Tuple, ast.Set, ast.Dict)):
            return _joined([self.expr(child, env, module) for child in ast.iter_child_nodes(node)
                            if isinstance(child, ast.expr)])
        return _UNKNOWN

    def assign(self, target, value, env, module):
        if isinstance(target, ast.Name):
            env[target.id] = value
        elif isinstance(target, ast.Attribute):
            owner = self.expr(target.value, env, module)
            if isinstance(owner, _Port) and target.attr == 'value':
                self.writes.setdefault(owner.name, []).append(value)
            elif isinstance(owner, _Object):
                # Plain instance data is not a second route for mutating its
                # constructor-bound DUT alias. Protected aliases are validated
                # class-wide before any method earns credit.
                owner.fields[target.attr] = value

    def driven(self):
        result = set()
        for name, values in self.writes.items():
            literals = {repr(v.literal) for v in values if isinstance(v, _Data) and v.literal is not _UNKNOWN}
            if len(literals) > 1 or any(not isinstance(v, _Data) or v.literal is _UNKNOWN for v in values):
                result.add(name)
        return result

    def statements(self, nodes, env, module, witness_boundary=False):
        returns = []
        for node in nodes:
            if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                value = self.expr(node.value, env, module)
                if isinstance(node, ast.AugAssign):
                    value = _joined([self.expr(node.target, env, module), value])
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    self.assign(target, value, env, module)
            elif isinstance(node, ast.Expr):
                self.expr(node.value, env, module)
            elif isinstance(node, ast.Assert):
                self.asserted.update(_reads(self.expr(node.test, env, module)))
            elif isinstance(node, ast.Return):
                returns.append(self.expr(node.value, env, module))
                break
            elif isinstance(node, (ast.Raise, ast.Break, ast.Continue)):
                break
            elif isinstance(node, ast.If):
                condition = self.expr(node.test, env, module)
                if not isinstance(condition, _Data) or condition.literal is _UNKNOWN:
                    left, right = dict(env), dict(env)
                    returns.extend(self.statements(node.body, left, module))
                    returns.extend(self.statements(node.orelse, right, module))
                    for name in set(left) | set(right):
                        a, b = left.get(name, _UNKNOWN), right.get(name, _UNKNOWN)
                        env[name] = (a if a is b else _joined([a, b])
                                     if _reads(a) and _reads(b) else _UNKNOWN)
                else:
                    selected = node.body if condition.literal else node.orelse
                    returns.extend(self.statements(selected, env, module))
            elif isinstance(node, (ast.For, ast.AsyncFor, ast.While)):
                if isinstance(node, ast.AsyncFor):
                    raise _Unestablished('async iterator binding is unresolved')
                if isinstance(node, ast.While):
                    condition = self.expr(node.test, env, module)
                    if isinstance(condition, _Data) and condition.literal is not _UNKNOWN and not condition.literal:
                        continue
                if isinstance(node, ast.For):
                    value = self.expr(node.iter, env, module)
                    if isinstance(value, _Data) and value.literal is not _UNKNOWN:
                        try:
                            if len(value.literal) == 0:
                                continue
                        except TypeError:
                            pass
                    self.assign(node.target, _UNKNOWN, env, module)
                returns.extend(self.statements(node.body, env, module))
            elif isinstance(node, ast.Try):
                if (node.handlers or node.orelse or any(isinstance(n, (ast.Return, ast.Break, ast.Continue))
                        for n in ast.walk(ast.Module(body=node.finalbody, type_ignores=[])))):
                    raise _Unestablished('exception handler or finally exit can suppress self-check')
                returns.extend(self.statements(node.body, env, module, witness_boundary))
                if not (witness_boundary and self.asserted and self.driven() & self.data_inputs):
                    self.statements(node.finalbody, env, module)
            elif isinstance(node, (ast.With, ast.AsyncWith, ast.Match)):
                # No guessed context-manager/exception binding semantics.
                raise _Unestablished('unsupported helper control binding')
            if witness_boundary and self.asserted and self.driven() & self.data_inputs:
                # A complete root statement has established a source witness.
                # Later vectors are not a Python abstract-interpretation task.
                # Enclosing exception/finally suppression was rejected before
                # entering its body; lexical and class bindings were validated.
                break
        return returns

    def binding_key(self, value, seen=None):
        """Finite abstract state, including each mutable instance's fields."""
        seen = set() if seen is None else seen
        if value is _DUT:
            return ('dut',)
        if value is _UNKNOWN:
            return ('unknown',)
        if isinstance(value, _Data):
            literal = ('unknown',) if value.literal is _UNKNOWN else (
                type(value.literal).__name__, hashlib.sha256(repr(value.literal).encode()).hexdigest())
            return ('data', tuple(sorted(value.reads)), literal)
        if isinstance(value, _Object):
            if id(value) in seen:
                raise _Unestablished('recursive instance binding')
            seen.add(id(value))
            result = ('instance', id(value), tuple(sorted(
                (name, self.binding_key(field, seen)) for name, field in value.fields.items())))
            seen.remove(id(value))
            return result
        if isinstance(value, _Port):
            return ('port', value.name)
        return ('unresolved',)

    def call(self, function, args, kwargs):
        node = function.node
        key = (function.module, node.lineno)
        if key in self.active or len(self.active) >= 24 or node.decorator_list:
            return _UNKNOWN
        parameters = [*node.args.posonlyargs, *node.args.args]
        if node.args.vararg or node.args.kwarg:
            return _UNKNOWN
        actual = ([function.receiver] if function.receiver is not None else []) + args
        if len(actual) > len(parameters):
            return _UNKNOWN
        env = dict(zip((a.arg for a in parameters), actual))
        for name, value in kwargs.items():
            if (name in env or name in {a.arg for a in node.args.posonlyargs}
                    or name not in {a.arg for a in [*parameters, *node.args.kwonlyargs]}):
                return _UNKNOWN
            env[name] = value
        defaults = dict(zip((a.arg for a in parameters[-len(node.args.defaults):]), node.args.defaults)) if node.args.defaults else {}
        defaults.update({a.arg: v for a, v in zip(node.args.kwonlyargs, node.args.kw_defaults) if v is not None})
        for arg in [*parameters, *node.args.kwonlyargs]:
            if arg.arg not in env:
                if arg.arg not in defaults:
                    return _UNKNOWN
                env[arg.arg] = self.expr(defaults[arg.arg], {}, function.module)
        lexical = list(self.scope_nodes(node.body))
        if any(isinstance(n, (ast.Global, ast.Nonlocal, ast.Yield, ast.YieldFrom)) for n in lexical):
            return _UNKNOWN
        rebound = self.bound_names(lexical)
        rebound.update(name for n in ast.walk(node) if isinstance(n, ast.Nonlocal) for name in n.names)
        if any(name in rebound and (value is _DUT or isinstance(value, _Object)) for name, value in env.items()):
            return _UNKNOWN
        for name in rebound:
            env.setdefault(name, _UNKNOWN)
        summary_key = (key, tuple(sorted((name, self.binding_key(value)) for name, value in env.items())))
        if summary_key in self.summaries:
            result, assertions, writes, fields = self.summaries[summary_key]
            self.asserted.update(assertions)
            for name, values in writes.items():
                self.writes.setdefault(name, []).extend(values)
            for instance, state in fields:
                instance.fields = dict(state)
            return result
        instances = {id(value): value for value in env.values() if isinstance(value, _Object)}
        previous_assertions = set(self.asserted)
        previous_writes = {name: len(values) for name, values in self.writes.items()}
        self.active.add(key)
        try:
            values = self.statements(node.body, env, function.module)
        finally:
            self.active.remove(key)
        result = _joined(values) if values and all(_reads(v) for v in values) else _UNKNOWN
        self.summaries[summary_key] = (
            result, self.asserted - previous_assertions,
            {name: values[previous_writes.get(name, 0):] for name, values in self.writes.items()},
            [(instance, dict(instance.fields)) for instance in instances.values()])
        return result

    def construct(self, function, args, kwargs):
        node = function.node
        if node.bases or node.keywords or node.decorator_list:
            return _UNKNOWN
        constructors = [n for n in node.body if isinstance(n, ast.FunctionDef) and n.name == '__init__']
        if any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
               and n.name in {'__new__', '__getattr__', '__getattribute__', '__setattr__'} for n in node.body):
            return _UNKNOWN
        if len(constructors) != 1:
            return _UNKNOWN
        constructor = constructors[0]
        if any(not isinstance(n, (ast.Assign, ast.AnnAssign, ast.Expr, ast.Pass)) for n in constructor.body):
            return _UNKNOWN
        instance = _Object(function.module, node)
        self.call(_Function(function.module, constructor, instance), args, kwargs)
        aliases = {name for name, value in instance.fields.items() if value is _DUT}
        if not aliases:
            return _UNKNOWN
        for method in node.body:
            if not isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)) or method is constructor:
                continue
            if not method.args.args:
                continue
            receiver = method.args.args[0].arg
            if method.name in aliases:
                return _UNKNOWN
            if any(isinstance(n, ast.Attribute) and n.attr in aliases
                   and isinstance(n.value, ast.Name) and n.value.id == receiver
                   and isinstance(n.ctx, (ast.Store, ast.Del)) for n in ast.walk(method)):
                return _UNKNOWN
            if any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                   and n.func.id in {'setattr', 'delattr'} and n.args
                   and isinstance(n.args[0], ast.Name) and n.args[0].id == receiver
                   for n in ast.walk(method)):
                return _UNKNOWN
        return instance


def asserted_helper_observations(tb, port_names, *, scope_nodes, bound_names, data_inputs):
    """Return finite source-bound observation facts, never a PASS verdict."""
    graph = _Graph(Path(tb), set(port_names), scope_nodes, bound_names, set(data_inputs))
    try:
        tree, _ = graph.module(graph.entry)
        for test in tree.body:
            if (isinstance(test, (ast.FunctionDef, ast.AsyncFunctionDef)) and test.args.args
                    and any(ast.unparse(d).startswith('cocotb.test') for d in test.decorator_list)):
                # The decorator identifies the root. Helpers must still be
                # undecorated; no decorator implementation is inferred.
                parameters = [a.arg for a in test.args.args]
                bound = bound_names(list(scope_nodes(test.body)))
                bound.update(name for n in ast.walk(test) if isinstance(n, ast.Nonlocal) for name in n.names)
                if parameters[0] in bound:
                    continue
                env = {name: _UNKNOWN for name in bound | set(parameters)}
                env[parameters[0]] = _DUT
                graph.statements(test.body, env, graph.entry, witness_boundary=True)
        return {'reads': sorted(graph.asserted & set(port_names)), 'driven': sorted(graph.driven()),
                'sources': [{'path': name, 'sha256': digest}
                            for name, digest in sorted(graph.manifest.items())]}
    except (OSError, SyntaxError, ValueError, TypeError, RecursionError, _Unestablished):
        return {'reads': [], 'driven': [], 'sources': []}
