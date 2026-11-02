"""Conservative reader for executable density bounds, never deck prose.

Only supported expressions/reports can prove a maximum-only rule. Every
predicate and opaque operation is accounted for; unknown keeps fill required.
No code is evaluated. Ruby forms outside this expression subset stay unknown.
"""
import ast
import math
import re


_UNKNOWN = None
_REPORTS = {'output_global', 'output_global_density_violation'}
_NUMERIC = {'area', 'to_f', 'to_i'}


def _parse(expression):
    expression = re.sub(r'(?<![:\w]):(min|max)\b', r'__density_bound_\1', expression)
    expression = expression.replace('&&', ' and ').replace('||', ' or ')
    expression = re.sub(r'!(?!=)', ' not ', expression)
    expression = re.sub(r'\bnil\b', 'None', expression)
    # deck_code_only has blanked strings while preserving positions. Restore
    # inert placeholders for empty string arguments/subscripts, not their text.
    expression = re.sub(r'\[\s*\]', '[None]', expression)
    expression = re.sub(r'(?<=[(,])\s*(?=[,)])', ' None ', expression)
    return ast.parse(expression.strip(), mode='eval').body


def _statements(code):
    pending = ''
    depth = 0
    for character in code:
        pending += character
        if character in '([':
            depth += 1
        elif character in ')]':
            depth -= 1
        if character in '\n;' and depth <= 0:
            if pending.strip():
                yield pending.strip(' \t\r\n;')
            pending, depth = '', 0
    if pending.strip():
        yield pending.strip(' \t\r\n;')


class DensityDirections:
    def __init__(self, code, die_names):
        self.die_names = set(die_names)
        self.definitions = {}
        for name, expression in re.findall(r'^\s*([A-Za-z_]\w*)\s*=(?!=)\s*([^\n]+)', code, re.M):
            self.definitions.setdefault(name, []).append(expression)

    def modes(self, code, layers):
        layers = set(layers)

        def references(expression):
            names = set(re.findall(r'[A-Za-z_]\w*', expression))
            while True:
                expanded = names | {word for name in names for value in self.definitions.get(name, [])
                                    for word in re.findall(r'[A-Za-z_]\w*', value)}
                if expanded == names:
                    return names
                names = expanded

        def dependent(node):
            names = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
            names |= {n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute)}
            return bool(references(' '.join(names)) & layers)

        def definition_sign(name, reader, seen):
            if name in seen or name not in self.definitions:
                return _UNKNOWN
            values = []
            for expression in self.definitions[name]:
                try:
                    values.append(reader(_parse(expression), seen | {name}))
                except (SyntaxError, ValueError):
                    return _UNKNOWN
            return values[0] if values and all(v == values[0] for v in values) else _UNKNOWN

        def scalar_sign(node, seen=frozenset()):
            if isinstance(node, ast.Constant) and type(node.value) in (int, float):
                if isinstance(node.value, float) and not math.isfinite(node.value):
                    return _UNKNOWN
                return (node.value > 0) - (node.value < 0)
            if isinstance(node, ast.Name):
                if node.id in self.die_names:
                    return 1
                return definition_sign(node.id, scalar_sign, seen)
            if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
                sign = scalar_sign(node.operand, seen)
                return sign if sign is None or isinstance(node.op, ast.UAdd) else -sign
            if isinstance(node, ast.BinOp):
                a, b = scalar_sign(node.left, seen), scalar_sign(node.right, seen)
                if a is None or b is None:
                    return _UNKNOWN
                if isinstance(node.op, (ast.Mult, ast.Div)):
                    return a * b if not isinstance(node.op, ast.Div) or b else _UNKNOWN
                if isinstance(node.op, ast.Sub):
                    b = -b
                if isinstance(node.op, (ast.Add, ast.Sub)) and (a == b or not a or not b):
                    return a or b
            return _UNKNOWN

        def slope(node, seen=frozenset()):
            # Sign of dependence on the ruled layer's coverage. Unsupported
            # transforms and opposing/multiple measured operands are unknown.
            if not dependent(node):
                return 0
            if isinstance(node, ast.Name):
                return definition_sign(node.id, slope, seen)
            if isinstance(node, ast.Attribute):
                region = node.value.id if isinstance(node.value, ast.Name) else getattr(node.value, 'attr', None)
                if node.attr == 'area' and region in layers:
                    return 1
                if node.attr in ('to_f', 'to_i'):
                    return slope(node.value, seen)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and not node.args:
                if node.func.attr in _NUMERIC:
                    return slope(node.func, seen)
            if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
                sign = slope(node.operand, seen)
                return sign if sign is None or isinstance(node.op, ast.UAdd) else -sign
            if isinstance(node, ast.BinOp):
                a, b = slope(node.left, seen), slope(node.right, seen)
                if a is None or b is None or (a and b):
                    return _UNKNOWN
                if isinstance(node.op, ast.Add):
                    return a or b
                if isinstance(node.op, ast.Sub):
                    return a or -b
                if isinstance(node.op, ast.Mult):
                    sign = scalar_sign(node.right if a else node.left, seen)
                    return (a or b) * sign if sign else _UNKNOWN
                if isinstance(node.op, ast.Div) and a and not b:
                    sign = scalar_sign(node.right, seen)
                    return a * sign if sign else _UNKNOWN
            return _UNKNOWN

        def predicate(node, negate=False):
            if isinstance(node, ast.BoolOp):
                return set().union(*(predicate(value, negate) for value in node.values))
            if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
                return predicate(node.operand, not negate)
            if not isinstance(node, ast.Compare):
                return {'unknown'} if dependent(node) else set()
            modes = set()
            for left, op, right in zip([node.left, *node.comparators], node.ops, node.comparators):
                if not dependent(left) and not dependent(right):
                    continue
                a, b = slope(left), slope(right)
                if a is None or b is None or bool(a) == bool(b) or not isinstance(op, (ast.Gt, ast.GtE, ast.Lt, ast.LtE)):
                    modes.add('unknown')
                    continue
                direction = (a if a else -b) * (1 if isinstance(op, (ast.Gt, ast.GtE)) else -1)
                if negate:
                    direction = -direction
                modes.add('max' if direction > 0 else 'min')
            return modes

        def comparisons(node, negate=False):
            if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
                return comparisons(node.operand, not negate)
            modes = predicate(node, negate) if isinstance(node, (ast.Compare, ast.BoolOp)) else set()
            for child in ast.iter_child_nodes(node):
                modes.update(comparisons(child, negate))
            return modes

        def expression_modes(expression, guard=False, negate=False, assignment=False):
            try:
                node = _parse(expression)
            except (SyntaxError, ValueError):
                return {'unknown'} if references(expression) & layers else set()
            modes = comparisons(node, negate)
            if guard:
                modes.update(predicate(node, negate))
            for child in ast.walk(node):
                if not isinstance(child, ast.Call):
                    continue
                function = child.func.id if isinstance(child.func, ast.Name) else getattr(child.func, 'attr', '')
                if isinstance(child.func, ast.Attribute) and function in (_NUMERIC | {'forget'}):
                    continue
                measured = dependent(child)
                if function in _REPORTS:
                    kinds = {arg.id.removeprefix('__density_bound_') for arg in child.args
                             if isinstance(arg, ast.Name) and arg.id in ('__density_bound_min', '__density_bound_max')}
                    if measured:
                        modes.update(kinds if len(kinds) == 1 else {'unknown'})
                elif isinstance(child.func, ast.Attribute) and function in ('output', 'info', 'warn', 'debug', 'error'):
                    # Known reporting APIs do not introduce a separate bound;
                    # their predicates and nested opaque calls are still read.
                    continue
                elif measured or not assignment:
                    modes.add('unknown')
            for child in ast.walk(node):
                if isinstance(child, ast.Attribute) and dependent(child) and child.attr not in (_NUMERIC | {'forget', 'output', 'info', 'warn', 'debug', 'error'}):
                    modes.add('unknown')
            supported = (ast.Name, ast.Constant, ast.Attribute, ast.Call, ast.BinOp,
                         ast.UnaryOp, ast.Compare, ast.BoolOp)
            for child in ast.walk(node):
                if isinstance(child, ast.expr) and dependent(child) and not isinstance(child, supported):
                    modes.add('unknown')
            return modes

        modes = set()
        for statement in _statements(code):
            conditional = re.search(r'\b(if|elsif|unless|while|until)\b', statement)
            if conditional:
                prefix, guard = statement[:conditional.start()], statement[conditional.end():]
                guard = re.sub(r'\bthen\s*$', '', guard).strip()
                if conditional[1] in ('while', 'until'):
                    if references(guard) & layers:
                        modes.add('unknown')
                else:
                    modes.update(expression_modes(guard, guard=True, negate=conditional[1] == 'unless'))
                if prefix.strip():
                    modes.update(expression_modes(prefix))
                continue
            assignment = re.match(r'^([A-Za-z_]\w*)\s*=(?!=)\s*(.*)', statement, re.S)
            expression = assignment[2] if assignment else statement
            modes.update(expression_modes(expression, assignment=bool(assignment)))
        return modes or {'unknown'}
