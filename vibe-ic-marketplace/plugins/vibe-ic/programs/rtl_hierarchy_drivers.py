"""Resolve hierarchy driver credit over the linter's exact supplied RTL files.

Structural, BLOCKING: only a declared child output/inout, with a valid binding,
may drive a parent actual. Unsupported discovery/selection is reported instead
of becoming an empty driver set or an inferred PASS. This is a bounded source
reader, not an HDL elaborator; generate-for/case and unresolved conditions are
refused. No external tools or design-specific names are used.
"""
from __future__ import annotations

import ast
import operator
import re
from dataclasses import dataclass
from pathlib import Path

import module_port_audit as ports
from verilog_width_resolve import _ternary_to_python


def constant(expr, params):
    """Evaluate only explicitly supported constant syntax; None means unknown."""
    def literal(m):
        size, signed, base, digits = m.groups()
        if re.search(r'[xz?]', digits, re.I):
            raise ValueError('unknown literal')
        value = int(digits.replace('_', ''), {'b': 2, 'o': 8, 'd': 10, 'h': 16}[base.lower()])
        if size:
            width = int(size)
            if not 0 < width <= 4096:
                raise ValueError('literal width')
            value &= (1 << width) - 1
            if signed and value & (1 << (width - 1)):
                value -= 1 << width
        return str(value)

    def divide(left, right):
        quotient = abs(left) // abs(right)
        return -quotient if (left < 0) != (right < 0) else quotient

    binary = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
              ast.FloorDiv: divide, ast.Mod: lambda a, b: a - divide(a, b) * b,
              ast.LShift: operator.lshift, ast.RShift: operator.rshift,
              ast.BitAnd: operator.and_, ast.BitOr: operator.or_, ast.BitXor: operator.xor}
    compare = {ast.Eq: operator.eq, ast.NotEq: operator.ne, ast.Lt: operator.lt,
               ast.LtE: operator.le, ast.Gt: operator.gt, ast.GtE: operator.ge}

    def visit(n):
        if isinstance(n, ast.Constant) and type(n.value) in (int, str):
            return n.value
        if isinstance(n, ast.Name) and n.id in params:
            return params[n.id]
        if isinstance(n, ast.BinOp) and type(n.op) in binary:
            left, right = visit(n.left), visit(n.right)
            if not isinstance(left, int) or not isinstance(right, int):
                raise ValueError('noninteger arithmetic')
            if isinstance(n.op, (ast.LShift, ast.RShift)) and not 0 <= right <= 4096:
                raise ValueError('shift budget')
            if isinstance(n.op, (ast.LShift, ast.RShift)) and left < 0:
                raise ValueError('unresolved signed shift width')
            return binary[type(n.op)](left, right)
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, (ast.Not, ast.USub, ast.UAdd)):
            value = visit(n.operand)
            return (int(not value) if isinstance(n.op, ast.Not) else
                    -value if isinstance(n.op, ast.USub) else +value)
        if isinstance(n, ast.BoolOp):
            values = [bool(visit(v)) for v in n.values]
            return int(all(values) if isinstance(n.op, ast.And) else any(values))
        if isinstance(n, ast.Compare) and len(n.ops) == 1 and type(n.ops[0]) in compare:
            return int(compare[type(n.ops[0])](visit(n.left), visit(n.comparators[0])))
        if isinstance(n, ast.IfExp):
            return visit(n.body if visit(n.test) else n.orelse)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == 'clog2':
            if len(n.args) != 1 or n.keywords:
                raise ValueError('clog2 arguments')
            value = visit(n.args[0])
            if not isinstance(value, int) or value <= 0:
                raise ValueError('clog2 domain')
            return (value - 1).bit_length()
        if isinstance(n, ast.Subscript) and isinstance(n.value, ast.Name):
            value = visit(n.value)
            if not isinstance(value, int) or value < 0:
                raise ValueError('select domain')
            if isinstance(n.slice, ast.Slice):
                hi, lo = visit(n.slice.lower), visit(n.slice.upper)
                if n.slice.step is not None or not 0 <= lo <= hi <= 4096:
                    raise ValueError('select range')
                return (value >> lo) & ((1 << (hi - lo + 1)) - 1)
            bit = visit(n.slice)
            if not 0 <= bit <= 4096:
                raise ValueError('select index')
            return (value >> bit) & 1
        raise ValueError('unsupported constant syntax')

    try:
        text = re.sub(r"(\d*)'([sS]?)([bBoOdDhH])([0-9a-fA-F_xXzZ?]+)", literal, expr.strip())
        text = re.sub(r"'0\b", '0', text)
        text = re.sub(r'\$clog2\b', 'clog2', text)
        text = _ternary_to_python(text)
        if text is None:
            return None
        if re.match(r'^\s*\|(?!\|)', text):
            result = constant(text.lstrip()[1:], params)
            return int(bool(result)) if result is not None else None
        text = text.replace('&&', ' and ').replace('||', ' or ')
        text = re.sub(r'!(?!=)', ' not ', text)
        text = re.sub(r'(?<!/)/(?!/)', '//', text)
        return visit(ast.parse(text.strip(), mode='eval').body)
    except (ValueError, TypeError, SyntaxError, KeyError, ZeroDivisionError, OverflowError):
        return None


def parameter_expressions(header, body):
    expressions = {}
    groups = []
    marker = re.search(r'#\s*\(', ports.lexical_mask(header))
    if marker:
        result = ports.extract_balanced(header, marker.end() - 1)
        if result:
            groups.append(result[0])
    groups += [m.group(1) for m in re.finditer(r'\blocalparam\b([^;]+);', body)]
    for group in groups:
        for item in ports.split_top_level(group):
            match = re.match(r'(.*?)\b([A-Za-z_]\w*)\s*=\s*(.+)$', item.strip(), re.S)
            if match:
                declaration = match.group(1)
                width = ''.join(re.findall(r'\[[^\]]+\]', declaration))
                signed = bool(re.search(r'\bsigned\b', declaration))
                if re.search(r'\b(?:int|integer)\b', declaration):
                    width, signed = '[31:0]', not bool(re.search(r'\bunsigned\b', declaration))
                expressions[match.group(2)] = (match.group(3).strip(), width, signed)
    return expressions


def resolve_parameters(expressions, overrides=None):
    resolved = {}
    overrides = overrides or {}
    for _ in range(len(expressions) + 1):
        changed = False
        for name, (expr, width_expr, signed) in expressions.items():
            if name in resolved:
                continue
            value = overrides[name] if name in overrides else constant(expr, resolved)
            if value is not None and width_expr:
                width = DriverContext.range_width(width_expr, resolved)
                if width is None or not isinstance(value, int) or not 0 < width <= 4096:
                    continue
                value &= (1 << width) - 1
                if signed and value & (1 << (width - 1)):
                    value -= 1 << width
            if value is not None:
                resolved[name] = value
                changed = True
        if not changed:
            break
    return resolved


def active_body(body, params, statement_end):
    """Blank inactive generate arms, preserving source offsets and line counts."""
    mask = ports.lexical_mask(body, attributes=True)
    chars = list(body)
    opaque = []
    for match in re.finditer(r'\b(?:always(?:_ff|_comb|_latch)?|initial)\b', mask):
        end = statement_end(mask, match.end())
        if end <= match.end():
            raise ValueError('unresolved procedural boundary')
        opaque.append((match.start(), end))
    opaque += [(m.start(), m.end()) for m in re.finditer(
        r'\b(function|task)\b.*?\bend\1\b', mask, re.S)]
    regions = [(m.start(), m.end()) for m in re.finditer(
        r'\bgenerate\b.*?\bendgenerate\b', mask, re.S)]

    def blank(lo, hi):
        for i in range(lo, hi):
            chars[i] = '\n' if body[i] == '\n' else ' '

    for match in re.finditer(r'\b(if|for|case|casez|casex)\b', mask):
        off = match.start()
        if chars[off].isspace() or any(lo <= off < hi for lo, hi in opaque):
            continue
        tail = match.end()
        while tail < len(mask) and mask[tail].isspace():
            tail += 1
        condition = ports.extract_balanced(mask, tail)
        if condition is None:
            continue
        after = condition[1] + 1
        in_generate = any(lo <= off < hi for lo, hi in regions)
        named = re.match(r'\s*begin\s*:', mask[after:])
        if not (in_generate or named):
            continue
        if match.group(1) != 'if':
            raise ValueError('unsupported generate selection: ' + match.group(1))
        value = constant(body[tail + 1:condition[1]], params)
        if value is None:
            raise ValueError('unresolved generate condition: ' + body[tail + 1:condition[1]])
        then_end = statement_end(mask, after)
        if then_end <= after:
            raise ValueError('unresolved generate arm')
        else_match = re.match(r'\s*else\b', mask[then_end:])
        if else_match:
            else_start = then_end + else_match.end()
            else_end = statement_end(mask, else_start)
            if else_end <= else_start:
                raise ValueError('unresolved generate else arm')
            if value:
                blank(then_end, else_end)
            else:
                blank(off, else_start)
        elif not value:
            blank(off, then_end)
    return ''.join(chars)


@dataclass
class Region:
    module: ports.ModuleDef
    header: str
    body: str
    body_line: int
    expressions: dict


def preprocess(source, defines):
    """Default compilation-unit `ifdef selection, preserving source offsets."""
    stack = []
    active = True
    output = []
    for line in source.splitlines(keepends=True):
        directive = re.match(r'\s*`(\w+)(?:\s+(.*?))?\s*$', line)
        if directive:
            word, argument = directive.group(1), (directive.group(2) or '').strip()
            if word in {'ifdef', 'ifndef'}:
                if not re.fullmatch(r'[A-Za-z_]\w*', argument):
                    raise ValueError('unsupported preprocessor condition')
                selected = argument in defines
                if word == 'ifndef':
                    selected = not selected
                stack.append([active, selected, False])
                active = active and selected
            elif word in {'else', 'elsif'}:
                if not stack or stack[-1][2]:
                    raise ValueError('unbalanced preprocessor branch')
                parent, selected, _ = stack[-1]
                if word == 'else':
                    active = parent and not selected
                    stack[-1][2] = True
                else:
                    if not re.fullmatch(r'[A-Za-z_]\w*', argument):
                        raise ValueError('unsupported preprocessor condition')
                    active = parent and not selected and argument in defines
                    stack[-1][1] = selected or argument in defines
            elif word == 'endif':
                if not stack:
                    raise ValueError('unbalanced preprocessor endif')
                active = stack.pop()[0]
            elif active and word == 'define':
                if not re.fullmatch(r'[A-Za-z_]\w*', argument):
                    raise ValueError('unsupported value/function macro')
                defines.add(argument)
            elif active and word == 'undef':
                defines.discard(argument)
            elif active and word not in {'default_nettype', 'timescale', 'resetall'}:
                raise ValueError('unsupported preprocessor directive: ' + word)
            output.append(''.join('\n' if ch == '\n' else ' ' for ch in line))
        else:
            output.append(line if active else ''.join('\n' if ch == '\n' else ' ' for ch in line))
    if stack:
        raise ValueError('unterminated preprocessor condition')
    result = ''.join(output)
    if re.search(r'`[A-Za-z_]', ports.lexical_mask(result)):
        raise ValueError('unresolved macro in source')
    return result


class DriverContext:
    def __init__(self, files, statement_end, lhs_collector):
        self.regions = {}
        self.by_file = {}
        self.cache = {}
        self.statement_end = statement_end
        self.lhs_collector = lhs_collector
        defines = set()
        for path in files:
            source = preprocess(ports.strip_comments(Path(path).read_text()), defines)
            issues = []
            bounds = list(ports.module_regions(source, issues))
            if issues:
                raise ValueError(f'{path}: ' + '; '.join(issues))
            definitions = ports.parse_modules(source, str(path))
            if not definitions and source.strip():
                raise ValueError(f'{path}: no safely parsed module')
            regions = []
            for module, (_, start, body_start, end) in zip(definitions, bounds):
                if module.name in self.regions:
                    raise ValueError('duplicate module definition: ' + module.name)
                region = Region(module, source[start:body_start], source[body_start:end],
                                source[:body_start].count('\n') + 1, {})
                region.expressions = parameter_expressions(region.header, region.body)
                self.regions[module.name] = region
                regions.append(region)
            self.by_file[str(path)] = regions

    def drivers(self, name, overrides=None, ancestors=()):
        region = self.regions[name]
        params = resolve_parameters(region.expressions, overrides)
        key = (name, tuple(sorted(params.items())))
        if key in self.cache:
            return self.cache[key]
        if name in ancestors:
            raise ValueError('recursive module hierarchy: ' + name)
        body = active_body(region.body, params, self.statement_end)
        driven = self.lhs_collector(region.header + body)
        coverage = {}
        for actual in re.findall(r'(?<![<>!=])\b(\w+(?:\[[^\]]+\])*)\s*(?:<=|=)(?!=)',
                                 region.header + body):
            self.add_coverage(actual, coverage, region, params)
        for actual in re.findall(r'(?:\bassign\s+)?(\{[^{}]*\})\s*(?:<=|=)(?!=)', body):
            self.add_coverage(actual, coverage, region, params)
        connections = {}
        candidate_connections = {}
        problems = []
        instances = ports.parse_instantiations(ports.lexical_mask(body, attributes=True),
                                               region.module.file, region.body_line)
        for inst in instances:
            def problem(reason):
                problems.append((inst.line, inst.instance_name, reason))

            child = self.regions.get(inst.module_name)
            if child is None:
                problem('unresolved child module: ' + inst.module_name)
                continue
            if inst.malformed_connections or inst.has_mixed_connections or child.module.discovery_issues:
                problem('ambiguous instance or child port declaration')
                continue
            # The parser retains port actuals, while parameter actuals are
            # read from this complete instance's balanced source statement.
            override_values = {}
            stmt = next((s for s, line in ports._collect_statements(body, preserve_literals=True)
                         if region.body_line + line == inst.line), '')
            prefix = re.match(r'\s*' + re.escape(inst.module_name) + r'\s*#\s*\(', stmt)
            if prefix:
                parameter_list = ports.extract_balanced(stmt, prefix.end() - 1)
                if parameter_list is None:
                    problem('unresolved parameter override')
                    continue
                override_items = ports.split_top_level(parameter_list[0])
                for position, item in enumerate(override_items):
                    binding = re.fullmatch(r'\s*\.\s*(\w+)\s*\((.*)\)\s*', item, re.S)
                    formal_name = binding.group(1) if binding else (
                        list(child.expressions)[position] if position < len(child.expressions) else '')
                    value = constant(binding.group(2) if binding else item, params)
                    if formal_name not in child.expressions or value is None or formal_name in override_values:
                        problem('unresolved or invalid parameter override: ' + item.strip())
                        break
                    override_values[formal_name] = value
                else:
                    pass
                if len(override_values) != len(override_items):
                    continue
            child_params = resolve_parameters(child.expressions, override_values)
            child_body, child_driven, _, child_problems = self.drivers(
                child.module.name, override_values, ancestors + (name,))
            if child_problems:
                problem('child hierarchy could not be resolved: ' + child.module.name)
                continue
            bindings = [(c.port_name, c.wire_expr) for c in inst.connections]
            if inst.positional_actuals:
                if len(inst.positional_actuals) > len(child.module.port_order):
                    problem('too many positional ports')
                    continue
                bindings = list(zip(child.module.port_order, inst.positional_actuals))
            if inst.is_implicit:
                used = {formal for formal, _ in bindings}
                bindings += [(formal, formal) for formal in child.module.ports if formal not in used]
            for formal_name, actual in bindings:
                formal = child.module.ports.get(formal_name)
                if formal is None:
                    problem('unknown formal port: ' + formal_name)
                    continue
                if formal.direction not in {'output', 'inout'} or not actual.strip():
                    continue
                actual_names = self.actual_names(actual)
                if not actual_names:
                    problem('unsupported output actual: ' + actual)
                    continue
                formal_width = self.range_width(formal.width_expr, child_params)
                actual_width = self.actual_width(actual, region, params)
                if formal_width is not None and actual_width is not None and formal_width != actual_width:
                    problem(f'output width mismatch: {formal_name} {formal_width} != {actual_width}')
                    continue
                if formal.direction == 'output' and formal_name not in child_driven:
                    problem('child output is not driven in selected configuration: ' + formal_name)
                    continue
                for signal in actual_names:
                    candidate_connections[signal] = formal_name
                self.add_coverage(actual, coverage, region, params)
        for signal, bits in coverage.items():
            bounds = self.signal_bounds(signal, region, params)
            if bits is None or (bounds is not None and
                                bits == set(range(bounds[0], bounds[1] + 1))):
                driven.add(signal)
                if signal in candidate_connections:
                    connections[signal] = candidate_connections[signal]
            else:
                driven.discard(signal)
        result = body, driven, connections, problems
        self.cache[key] = result
        return result

    @staticmethod
    def actual_names(actual):
        actual = actual.strip()
        if actual.startswith('{') and actual.endswith('}'):
            parts = ports.split_top_level(actual[1:-1])
            names = [DriverContext.actual_names(part) for part in parts]
            return set().union(*names) if all(names) else set()
        match = re.fullmatch(r'([A-Za-z_]\w*)(?:\s*\[[^\[\]]+\])*', actual)
        return {match.group(1)} if match else set()

    @staticmethod
    def range_width(expression, params):
        if not expression:
            return 1
        dimensions = re.findall(r'\[([^\]]+)\]', expression)
        width = 1
        for dimension in dimensions:
            parts = dimension.split(':')
            if len(parts) != 2:
                return None
            hi, lo = (constant(part, params) for part in parts)
            if not isinstance(hi, int) or not isinstance(lo, int):
                return None
            width *= abs(hi - lo) + 1
        return width if dimensions else None

    def actual_width(self, actual, region, params):
        actual = actual.strip()
        if actual.startswith('{') and actual.endswith('}'):
            widths = [self.actual_width(part, region, params)
                      for part in ports.split_top_level(actual[1:-1])]
            return sum(widths) if all(w is not None for w in widths) else None
        select = re.fullmatch(r'\w+\s*\[([^\]]+)\]', actual)
        if select:
            return self.range_width('[' + select.group(1) + ']', params) if ':' in select.group(1) else 1
        formal = region.module.ports.get(actual)
        if formal:
            return self.range_width(formal.width_expr, params)
        for match in re.finditer(r'\b(?:wire|reg|logic)\s+(?:signed\s+|unsigned\s+)?'
                                 r'((?:\[[^\]]+\]\s*)*)([^;]+);', region.body):
            for item in ports.split_top_level(match.group(2)):
                if re.match(r'\s*' + re.escape(actual) + r'\s*(?:=|$)', item):
                    return self.range_width(match.group(1), params)
        return None

    def signal_bounds(self, name, region, params):
        formal = region.module.ports.get(name)
        expressions = [formal.width_expr] if formal else []
        if not formal:
            for match in re.finditer(r'\b(?:wire|reg|logic)\s+(?:signed\s+|unsigned\s+)?'
                                     r'((?:\[[^\]]+\]\s*)*)([^;]+);', region.body):
                if any(re.match(r'\s*' + re.escape(name) + r'\s*(?:=|$)', item)
                       for item in ports.split_top_level(match.group(2))):
                    expressions.append(match.group(1))
        if len(expressions) != 1:
            return None
        if not expressions[0]:
            return (0, 0)
        dimensions = re.findall(r'\[([^\]]+)\]', expressions[0])
        if len(dimensions) != 1:
            return None
        parts = dimensions[0].split(':')
        if len(parts) != 2:
            return None
        values = [constant(part, params) for part in parts]
        if not all(isinstance(value, int) for value in values):
            return None
        lo, hi = sorted(values)
        return (lo, hi) if 0 <= hi - lo <= 4096 else None

    def add_coverage(self, actual, coverage, region, params):
        actual = actual.strip()
        if actual.startswith('{') and actual.endswith('}'):
            for part in ports.split_top_level(actual[1:-1]):
                self.add_coverage(part, coverage, region, params)
            return
        match = re.fullmatch(r'([A-Za-z_]\w*)(?:\s*\[([^\]]+)\])?', actual)
        if not match:
            return
        name, select = match.groups()
        if select is None:
            coverage[name] = None
            return
        if name in coverage and coverage[name] is None:
            return
        bits = coverage.setdefault(name, set())
        selected = [constant(part, params) for part in select.split(':')]
        if not all(isinstance(value, int) for value in selected) or len(selected) not in (1, 2):
            return
        lo, hi = min(selected), max(selected)
        bounds = self.signal_bounds(name, region, params)
        if bounds is not None and bounds[0] <= lo <= hi <= bounds[1]:
            bits.update(range(lo, hi + 1))
