#!/usr/bin/env python3
"""_seal_ring_margin — how far a DIE's core must stay back from the die edge on
a technology that ships its own seal ring.  vibe-ic#2122

THE DEFECT THIS EXISTS FOR (measured, vibeic-eda#189 / vibe-ic#2122)
--------------------------------------------------------------------
On a `deliverable=DIE` run the flow sized the die to the core and then sealed
the ring onto it IN PLACE. The ring is a band at the die edge and the deck
requires a clearance between its marker and every prime-die layer, so a core
that reaches the die edge is inside both. Measured on one gf180mcuD die:

    ring alone, 503 um die                                    16, all density
    the run's own core (filling 0,0;503,503) + that ring    1,359,531
    the same core moved 28.5 um inward, 560 um die                    0

19,826 core shapes sat inside the 16 um ring band. The ring was correct, the
generator was correct and the deck was correct; the DIE was too small by
exactly the band plus the deck's own clearance, on every edge.

WHAT THIS MODULE IS, AND WHAT IT IS NOT
---------------------------------------
It is the ONE derivation of that margin, read out of the TECHNOLOGY, for the
two places that need it — `phase3_one_shot_runner.step_pnr`, which sizes the
die before the ring exists, and `die_finishing_gen`, which must refuse to seal
a core that reaches into the band. It carries NO number of its own:

    band       the seal-ring generator's OWN cell library says how deep its
               edge is (`<something>_width`, discovered by name, never a
               literal here) — or, better where it exists, the MEASURED inner
               extent of the ring the generator actually built
               (`sealring_verify.ring_extent`), which is a measurement of this
               die and not a reading of a parameter.
    clearance  the PDK's own DRC deck, in its own words: the separation every
               prime-die layer owes the guard-ring marker
               (`<layer>.separation(<guard-ring marker>, N.um)`).

EVERY UNREADABLE LINK IS A NAMED `NOT_MEASURED`, never a default. A margin
this module invented would be this flow deciding where the foundry's ring
goes, which is the whole defect one level up.

chip/PDK-AGNOSTIC: no foundry, node, PDK name, layer number or design name
appears here. The layer VARIABLES are discovered from the deck's own text by
what they are (a guard-ring marker), not by what they are called in any one
process.
"""
from __future__ import annotations

import ast
import json
import math
import posixpath
import re
import shlex
from typing import Any, Callable, Dict, List, Optional, Tuple

#: `run_sh(cmd) -> (rc, stdout)`. The PDK lives where the tools live, which on
#: this flow is inside a container, so every read goes through the caller's own
#: shell rather than through `open()`.
ShellFn = Callable[[str], Tuple[int, str]]

NOT_MEASURED = "NOT_MEASURED"

#: How `_read_files` frames each file in one shell round trip.
_SEP = "=== VIC_SEAL_FILE "
#: A cap on how much PDK text is pulled back at once. A deck is a few hundred
#: lines; anything past this is not the file we are looking for.
_MAX_BYTES = 400000


# ── pure parsers ────────────────────────────────────────────────────────────

_RE_ASSIGN = re.compile(
    r"^[ \t]*([A-Za-z_][A-Za-z0-9_]*)[ \t]*=[ \t]*([0-9]+(?:\.[0-9]+)?)[ \t]*$",
    re.M)


def _is_band_name(name: str) -> bool:
    """A seal-ring generator's own declaration of how deep its edge is.

    BY WHAT IT IS, not by what one PDK calls it: a name that speaks of the SEAL
    and states a WIDTH. `sealring_edge_width` matches; `sealring_corner_radius`
    and `metal1_width` do not.
    """
    low = name.lower()
    return "seal" in low and low.endswith("width")


def band_declarations(text: str) -> List[Tuple[str, float]]:
    """Every `<seal…width> = <number>` this generator library declares."""
    out: List[Tuple[str, float]] = []
    for m in _RE_ASSIGN.finditer(text or ""):
        if _is_band_name(m.group(1)):
            out.append((m.group(1), float(m.group(2))))
    return out


_IDENT = r"[A-Za-z_][A-Za-z0-9_]*"
_RE_SEPARATION = re.compile(
    rf"\b({_IDENT})\s*\.\s*(?:sep|separation)\s*\(\s*([^,]+)\s*,\s*([^,\n)]*)")
_RE_GUARD_RING_VAR = re.compile(
    r"guard[A-Za-z0-9_]*ring|ring[A-Za-z0-9_]*guard", re.I)
_RE_SEAL_RING_VAR = re.compile(
    _RE_GUARD_RING_VAR.pattern + r"|"
    r"edge[A-Za-z0-9_]*seal|seal[A-Za-z0-9_]*ring", re.I)
_RE_RULE_ID = re.compile(r"\.output\s*\(\s*['\"]([^'\"]+)['\"]")
_RE_CLEAR_ASSIGN = re.compile(rf"^[ \t]*({_IDENT})[ \t]*=[ \t]*([^\n]*)", re.M)
_RE_RULE_VALUE = re.compile(
    rf"({_IDENT})\s*\[\s*['\"]([^'\"]+)['\"]\s*\]\s*\.\s*to_[fi]\b(?![!?])")
_RE_NUMBER = re.compile(r"(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")
_RE_DECK_LITERAL = re.compile(r'''"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|\#[^\n]*''')


def _clearance_code(text: str) -> Tuple[str, str]:
    body = _RE_DECK_LITERAL.sub(
        lambda m: re.sub(r"[^\n]", " ", m.group()) if m.group().startswith("#") else m.group(), text)
    code = _RE_DECK_LITERAL.sub(lambda m: re.sub(r"[^\n]", " ", m.group()), body)
    return body, code


def _json_member_offset(text: str, key: str, start: int = 0) -> Tuple[int, int]:
    decoder = json.JSONDecoder()
    cursor = text.index("{", start) + 1
    while True:
        while text[cursor].isspace() or text[cursor] == ",":
            cursor += 1
        key_offset = cursor
        name, cursor = decoder.raw_decode(text, cursor)
        cursor = text.index(":", cursor) + 1
        while text[cursor].isspace():
            cursor += 1
        value_offset = cursor
        _, cursor = decoder.raw_decode(text, cursor)
        if name == key:
            return value_offset, key_offset


def _ruby_scope_depth(code: str, before: int) -> int:
    depth = 0
    for line in code[:before].splitlines():
        stripped = line.strip()
        if re.match(r"^(?:def|if|unless|begin|case|while|until|for|class|module)\b", stripped):
            depth += 1
        if re.search(r"\bdo(?:\s*\|[^|]*\|)?\s*$", stripped):
            depth += 1
        if stripped == "end":
            depth -= 1
    return depth


RuleSource = Tuple[str, str, str, bool]


def _clearance_value(expression: str, files: Dict[str, str],
                     sources: Optional[List[RuleSource]] = None) -> Tuple[Optional[float], str, Optional[Tuple[str, str]]]:
    if _RE_NUMBER.fullmatch(expression):
        value = float(expression)
        return (value, "", None) if math.isfinite(value) else (None, f"nonfinite clearance {expression}", None)
    reference = _RE_RULE_VALUE.fullmatch(expression)
    if not reference:
        return None, f"clearance expression `{expression}` could not be read", None
    table, key = reference.groups()
    if "#{" in key:
        return None, "unsupported interpolation in JSON rule key", (table, key)
    winner = None
    evidence = []

    def pairs(items):
        result = {}
        for name, value in items:
            if name in result:
                raise ValueError(f"duplicate JSON key {name}")
            result[name] = value
        return result

    for path, json_table, binding_basis, empty_fallback in sources or []:
        if path not in files:
            return None, f"required JSON source {path} was not read; {binding_basis}", (table, key)
        text = files[path]
        try:
            payload = json.loads(text, object_pairs_hook=pairs)
        except (ValueError, TypeError) as exc:
            return None, f"{path} is not readable JSON: {exc}", (table, key)
        if not isinstance(payload, dict):
            return None, f"{path} has no JSON object to read {json_table} from", (table, key)
        candidate = payload.get(json_table)
        if empty_fallback and (candidate is None or candidate is False):
            candidate = {}
        if not isinstance(candidate, dict):
            return None, f"{path} has no readable {json_table} rule table", (table, key)
        evidence.append(f"{binding_basis}; loaded {path}[{json_table!r}]")
        if key in candidate:
            winner = (path, candidate[key], text, json_table)
    if winner is None:
        return None, f"{table}[{key!r}] was not read from a declared JSON rule table", (table, key)
    path, raw, text, json_table = winner
    try:
        value = float(raw) if not isinstance(raw, bool) and isinstance(raw, (int, float, str)) else math.nan
    except (ValueError, TypeError, OverflowError):
        value = math.nan
    if not math.isfinite(value) or value < 0:
        return None, f"{path} has no finite nonnegative {json_table}[{key!r}]", (table, key)
    if expression.endswith("to_i"):
        if isinstance(raw, str) and not re.fullmatch(r"[+]?[0-9]+", raw.strip()):
            return None, f"unsupported string to_i conversion of {table}[{key!r}]", (table, key)
        value = float(math.trunc(value))
    table_offset, _ = _json_member_offset(text, json_table)
    _, key_offset = _json_member_offset(text, key, table_offset)
    line = text.count("\n", 0, key_offset) + 1
    return value, "; ".join(evidence + [f"winner {path}:{line} {json_table}[{key!r}] = {value} um"]), (table, key)


_RE_INCLUDE = re.compile(r"^[ \t]*#[ \t]*%include[ \t]+([^\s'\";]+)[ \t]*$", re.M)
_RUBY_STRING = r"(?:'[^'\\\n]*'|\"[^\"\\\n]*\")"


def _deck_includes(text: str):
    masked = _RE_DECK_LITERAL.sub(
        lambda match: match.group() if match.group().startswith("#") else
        re.sub(r"[^\n]", " ", match.group()), text)
    return _RE_INCLUDE.finditer(masked)


def _relative_source(source_path: str, literal: str) -> Optional[str]:
    if not literal or posixpath.isabs(literal) or "#{" in literal or "\\" in literal:
        return None
    return posixpath.normpath(posixpath.join(posixpath.dirname(source_path), literal))


def _source_at(offset: int, origins: List[Tuple[int, int, str, int]], fallback: str) -> Tuple[str, int]:
    for start, end, path, line in origins:
        if start <= offset < end:
            return path, line
    return fallback, 1


def _loader_methods(text: str, origins: List[Tuple[int, int, str, int]], source_path: str):
    """Recognize only the shipped read/parse/table/default.merge(tech) method schema."""
    body, code = _clearance_code(text)
    lines = code.splitlines(keepends=True)
    offsets = []
    cursor = 0
    for line in lines:
        offsets.append(cursor)
        cursor += len(line)
    methods = {}
    ranges = []
    i = 0
    while i < len(lines):
        declaration = re.fullmatch(r"\s*def\s+(" + _IDENT + r")\((" + _IDENT + r")\)\s*", lines[i])
        if not declaration:
            i += 1
            continue
        start = i
        depth = 1
        i += 1
        while i < len(lines) and depth:
            stripped = lines[i].strip()
            if re.match(r"^(?:def|if|unless|begin|case|while|until|for|class|module)\b", stripped):
                depth += 1
            if re.search(r"\bdo(?:\s*\|[^|]*\|)?\s*$", stripped):
                depth += 1
            if stripped == "end":
                depth -= 1
            i += 1
        if depth:
            methods[declaration.group(1)] = (None, "unsupported unterminated loader method")
            continue
        ranges.append((offsets[start], offsets[i] if i < len(offsets) else len(text)))
        if _ruby_scope_depth(code, offsets[start]) != 0:
            methods[declaration.group(1)] = (None, "unsupported conditional loader definition")
            continue
        logger = declaration.group(2)
        raw = body[offsets[start + 1]:offsets[i - 1]]
        statements = []
        if any(not re.fullmatch(r"\$?" + _IDENT + r"(?:\.message)?", interpolation)
               for interpolation in re.findall(r"#\{([^}]*)\}", raw)):
            methods[declaration.group(1)] = (None, "unsupported interpolation in JSON loader")
            continue
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            if re.fullmatch(re.escape(logger) + r"\.(?:info|warn|error)\(" + _RUBY_STRING + r"\)", line):
                if any(not re.fullmatch(r"\$?" + _IDENT + r"(?:\.message)?", value)
                       for value in re.findall(r"#\{([^}]*)\}", line)):
                    statements.append(line)
                    continue
                continue
            if re.fullmatch(_IDENT + r"\.each \{ \|" + _IDENT + r"\| " + re.escape(logger) + r"\.warn\(" + _RUBY_STRING + r"\) \}", line):
                continue
            statements.append(line)
        normalized = "\n".join(statements)
        pattern = (
            rf"(?P<dir>{_IDENT}) = File\.expand_path\(File\.dirname\(__FILE__\)\)\n"
            rf"(?P<default>\${_IDENT}) = (?P=default) \|\| File\.expand_path\(File\.join\((?P=dir), ['\"](?P<default_path>[^'\"\\]+)['\"]\)\)\n"
            rf"(?P<tech>\${_IDENT}) = (?P=tech) \|\| File\.expand_path\(File\.join\((?P=dir), ['\"](?P<tech_path>[^'\"\\]+)['\"]\)\)\n"
            rf"(?P<tech_rules>{_IDENT}) = \{{\}}\n"
            r"if (?P=tech) && (?P=tech) != (?P=default)\nbegin\n"
            rf"(?P<tech_content>{_IDENT}) = File\.read\((?P=tech)\)\n"
            rf"(?P<tech_data>{_IDENT}) = JSON\.parse\((?P=tech_content)\)\n"
            rf"(?P=tech_rules) = (?P=tech_data)\[['\"](?P<table>[^'\"\\]+)['\"]\] \|\| \{{\}}\n"
            rf"rescue StandardError => (?P<tech_error>{_IDENT})\nraise {_RUBY_STRING}\nend\nend\nbegin\n"
            rf"(?P<default_content>{_IDENT}) = File\.read\((?P=default)\)\n"
            rf"(?P<default_data>{_IDENT}) = JSON\.parse\((?P=default_content)\)\n"
            r"(?P<default_rules>" + _IDENT + r") = (?P=default_data)\[['\"](?P=table)['\"]\] \|\| \{\}\n"
            rf"rescue StandardError => (?P<default_error>{_IDENT})\nraise {_RUBY_STRING}\nend\n"
            rf"(?P<merged>{_IDENT}) = (?P=default_rules)\.merge\((?P=tech_rules)\)\n"
            rf"(?P<missing>{_IDENT}) = (?P=default_rules)\.keys - (?P=tech_rules)\.keys\nunless (?P=missing)\.empty\?\nend\n(?P=merged)"
        )
        match = re.fullmatch(pattern, normalized)
        if not match:
            methods[declaration.group(1)] = (None, "unsupported JSON loader structure")
            continue
        data = match.groupdict()
        names = [data[k] for k in ("dir", "tech_rules", "tech_content", "tech_data", "default_content", "default_data", "default_rules", "merged", "missing")]
        path, _ = _source_at(offsets[start], origins, source_path)
        default = _relative_source(path, data["default_path"])
        tech = _relative_source(path, data["tech_path"])
        if len(set(names)) != len(names) or data["tech"] == data["default"] or not default or not tech:
            methods[declaration.group(1)] = (None, "unsupported ambiguous JSON loader names or paths")
            continue
        globals_used = [data["default"], data["tech"]]
        outside = code[:offsets[start]] + code[offsets[i] if i < len(offsets) else len(code):]
        outside_body = body[:offsets[start]] + body[offsets[i] if i < len(offsets) else len(body):]
        if any(re.search(r"#\{[^}]*" + re.escape(name) + r"\b", outside_body)
               for name in globals_used):
            methods[declaration.group(1)] = (None, "unsupported source-global interpolation outside JSON loader")
            continue
        if any(re.search(re.escape(name) + r"\s*(?:[|&+*/-]?=|\[|\.)", outside) for name in globals_used):
            methods[declaration.group(1)] = (None, "unsupported external mutation of source-default JSON path")
            continue
        basis = f"{path} loader {declaration.group(1)}; source-default global fallbacks assumed (runtime overrides unavailable); default.merge(TECH), TECH overrides per key"
        methods[declaration.group(1)] = ([(default, data["table"], basis, True), (tech, data["table"], basis, True)], "")
    return methods, ranges


class _NumericExpression:
    """A bounded, non-executing model of numeric Ruby receivers and reads."""

    methods = {"to_f", "to_i", "um", "um2"}
    operators = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod, ast.Pow)

    def __init__(self, tables=(), names=()):
        self.tables = set(tables)
        self.names = set(names)
        self.opaque = set()

    @staticmethod
    def parse(expression, mode="eval"):
        for literal in reversed(list(_RE_DECK_LITERAL.finditer(expression))):
            raw = literal.group()
            if not raw.startswith("#") and "\n" in raw:
                expression = expression[:literal.start()] + repr(raw[1:-1]) + expression[literal.end():]
        _, code = _clearance_code(expression)
        for keyword in reversed(list(re.finditer(r"\b([A-Za-z_]\w*)\s*:(?![:=])", code))):
            expression = (expression[:keyword.start()] + "_" + keyword.group(1)
                          + "=" + expression[keyword.end():])
        _, code = _clearance_code(expression)
        edits = [(m.start(1), "_") for m in re.finditer(r"\.(and|or|not)\b", code)]
        edits.extend((m.end(1), " ") for m in re.finditer(r"(?<![\w.])([0-9]+)\.(?=[A-Za-z_])", code))
        for offset, addition in sorted(edits, reverse=True):
            expression = expression[:offset] + addition + expression[offset:]
        tree = ast.parse(expression.strip(), mode=mode)
        if sum(1 for _ in ast.walk(tree)) > 512:
            raise ValueError("numeric expression exceeds the node bound")
        return tree.body if mode == "eval" else tree.body

    def read(self, node, depth=0):
        if depth > 32:
            raise ValueError("numeric expression exceeds the nesting bound")
        descend = lambda child: self.read(child, depth + 1)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, str):
                for interpolation in re.findall(r"#\{([^}]*)\}", node.value):
                    if any(re.search(r"\b" + re.escape(n) + r"\b", interpolation)
                           for n in self.tables | self.names | self.opaque):
                        descend(self.parse(interpolation))
                return False
            return isinstance(node.value, (int, float)) and not isinstance(node.value, bool)
        if isinstance(node, ast.Name):
            if node.id in self.tables:
                raise ValueError(f"unsupported bare JSON table {node.id}")
            return None if node.id in self.opaque else node.id in self.names
        if isinstance(node, ast.Subscript):
            if (not isinstance(node.value, ast.Name) or node.value.id not in self.tables
                    or not isinstance(node.slice, ast.Constant)
                    or not isinstance(node.slice.value, str) or "#{" in node.slice.value):
                raise ValueError("unsupported numeric lookup")
            return True
        if isinstance(node, ast.Attribute):
            numeric = descend(node.value)
            if numeric is None:
                raise ValueError("unsupported method on an opaque numeric consumer result")
            if numeric and node.attr not in self.methods:
                raise ValueError(f"unsupported numeric method {node.attr}")
            return numeric
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute):
                numeric = descend(node.func.value)
                if numeric is None:
                    raise ValueError("unsupported method on an opaque numeric consumer result")
                if numeric and (node.func.attr not in self.methods or node.args or node.keywords):
                    raise ValueError(f"unsupported numeric method {node.func.attr}")
            else:
                if isinstance(node.func, ast.Name) and node.func.id in self.tables | self.names | self.opaque:
                    raise ValueError("unsupported numeric call")
                numeric = False
            arguments = [descend(child) for child in [*node.args, *(k.value for k in node.keywords)]]
            if (not isinstance(node.func, ast.Attribute)
                    and any(isinstance(child, ast.Name) and child.id in self.tables | self.names | self.opaque
                            for arg in node.args for child in ast.walk(arg))):
                return None
            return numeric
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub, ast.Not)):
            return descend(node.operand)
        if isinstance(node, ast.BinOp) and isinstance(node.op, self.operators):
            left, right = descend(node.left), descend(node.right)
            return left or right
        if isinstance(node, (ast.Compare, ast.BoolOp, ast.List, ast.Tuple, ast.Dict)):
            for child in ast.iter_child_nodes(node):
                if not isinstance(child, (ast.cmpop, ast.boolop)):
                    descend(child)
            return False
        raise ValueError(f"unsupported numeric syntax {type(node).__name__}")

    def audit(self, text):
        """Check related statements, retaining scalar aliases without executing Ruby."""
        body, code = _clearance_code(text)
        lines = body.splitlines(keepends=True)
        code_lines = code.splitlines(keepends=True)
        pending = ""
        depth = 0
        for index, line in enumerate(lines):
            masked = code_lines[index]
            delta = sum(masked.count(c) for c in "([{") - sum(masked.count(c) for c in ")]}")
            related = any(re.search(r"\b" + re.escape(n) + r"\b", line)
                          for n in self.tables | self.names | self.opaque)
            if not pending and not related and not (delta > 0 and re.search(r"\.\w+\(", masked)):
                continue
            pending += line
            depth += delta
            following = lines[index + 1].lstrip() if index + 1 < len(lines) else ""
            if depth > 0 or masked.rstrip().endswith("\\"):
                continue
            if following.startswith((".", "&.", "::")):
                pending = pending.rstrip() + " "
                continue
            statement, pending = pending.strip(), ""
            if not any(re.search(r"\b" + re.escape(n) + r"\b", statement)
                       for n in self.tables | self.names | self.opaque):
                continue
            statement = re.sub(r"^(?:if|unless|elsif|while|until|return)\s+", "", statement)
            try:
                for node in self.parse(statement, "exec"):
                    if isinstance(node, ast.Assign):
                        if (len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name)
                                or node.targets[0].id in self.tables | self.names | self.opaque):
                            raise ValueError("unsupported numeric write or rebinding")
                        numeric = self.read(node.value)
                        if numeric is True:
                            self.names.add(node.targets[0].id)
                        elif numeric is None:
                            self.opaque.add(node.targets[0].id)
                    elif isinstance(node, ast.Expr):
                        self.read(node.value)
                    else:
                        raise ValueError("unsupported numeric write or statement")
            except (SyntaxError, ValueError, RecursionError) as exc:
                return f"unsupported numeric expression: {exc}"
        if pending and any(re.search(r"\b" + re.escape(n) + r"\b", pending)
                           for n in self.tables | self.names | self.opaque):
            return "unsupported incomplete numeric expression"
        return ""

    @classmethod
    def references(cls, node, assigned, before, seen=()):
        if isinstance(node, ast.Subscript):
            if (not isinstance(node.value, ast.Name) or not isinstance(node.slice, ast.Constant)
                    or not isinstance(node.slice.value, str) or "#{" in node.slice.value):
                raise ValueError("unsupported numeric lookup")
            return [(node.value.id, node.slice.value, before)]
        if isinstance(node, ast.Name):
            if node.id in seen:
                raise ValueError("cyclic numeric binding")
            source = assigned(node.id, before)
            if source is None:
                raise ValueError(f"unbound numeric local {node.id}")
            return cls.references(cls.parse(source[0]), assigned, source[1], (*seen, node.id))
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return []
        if isinstance(node, ast.Attribute) and node.attr in cls.methods:
            return cls.references(node.value, assigned, before, seen)
        if (isinstance(node, ast.Call) and not node.args and not node.keywords
                and isinstance(node.func, ast.Attribute) and node.func.attr in cls.methods):
            return cls.references(node.func, assigned, before, seen)
        if isinstance(node, (ast.UnaryOp, ast.BinOp)):
            children = [node.operand] if isinstance(node, ast.UnaryOp) else [node.left, node.right]
            return [ref for child in children for ref in cls.references(child, assigned, before, seen)]
        raise ValueError("unsupported numeric clearance expression")

    @classmethod
    def evaluate(cls, node, assigned, lookup, before, seen=()):
        if len(seen) > 32:
            raise ValueError("numeric binding exceeds the nesting bound")
        evaluate = lambda child: cls.evaluate(child, assigned, lookup, before, seen)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            value = node.value
        elif isinstance(node, ast.Name):
            if node.id in seen:
                raise ValueError("cyclic numeric binding")
            source = assigned(node.id, before)
            if source is None:
                raise ValueError(f"unbound numeric local {node.id}")
            value = cls.evaluate(cls.parse(source[0]), assigned, lookup, source[1], (*seen, node.id))
        elif (isinstance(node, ast.Call) and not node.args and not node.keywords
              and isinstance(node.func, ast.Attribute) and node.func.attr in cls.methods):
            return evaluate(node.func)
        elif isinstance(node, ast.Attribute) and node.attr in cls.methods:
            if node.attr == "um2":
                raise ValueError("area units cannot state a linear clearance")
            if isinstance(node.value, ast.Subscript):
                ref = cls.references(node.value, assigned, before)[0]
                value = lookup(*ref, node.attr)
            else:
                value = evaluate(node.value)
                value = float(value) if node.attr == "to_f" else math.trunc(value) if node.attr == "to_i" else value
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = evaluate(node.operand)
            value = -value if isinstance(node.op, ast.USub) else value
        elif isinstance(node, ast.BinOp) and isinstance(node.op, cls.operators):
            left, right = evaluate(node.left), evaluate(node.right)
            if isinstance(node.op, ast.Add): value = left + right
            elif isinstance(node.op, ast.Sub): value = left - right
            elif isinstance(node.op, ast.Mult): value = left * right
            elif isinstance(node.op, ast.Div): value = left // right if isinstance(left, int) and isinstance(right, int) else left / right
            elif isinstance(node.op, ast.Mod): value = left % right
            else:
                if abs(right) > 4096 or (isinstance(left, int) and isinstance(right, int) and right > 0 and left.bit_length() * right > 4096):
                    raise ValueError("numeric power exceeds the resource bound")
                value = left ** right
        else:
            raise ValueError("unsupported numeric clearance expression")
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError("nonfinite or nonnumeric clearance")
        return value


def _table_sources(table: str, assignment, text: str, source_path: str,
                   origins: List[Tuple[int, int, str, int]], before: int):
    if not assignment:
        return [], f"unsupported JSON authority for {table}: no declared loader binding"
    expression, offset = assignment
    methods, ranges = _loader_methods(text, origins, source_path)
    _, code = _clearance_code(text)
    if sum(m.group(1) == table and m.start() < before
           for m in _RE_CLEAR_ASSIGN.finditer(code)) != 1:
        return [], f"unsupported reassigned JSON table {table}"
    depth = _ruby_scope_depth(code, offset)
    if depth != 0:
        return [], f"unsupported conditional or ambiguous JSON binding for {table}"
    if any(start <= offset < end for start, end in ranges):
        return [], f"unsupported JSON binding inside method for {table}"
    path, _ = _source_at(offset, origins, source_path)
    direct = re.fullmatch(r"JSON\.parse\(File\.read\(File\.join\(__dir__,\s*['\"]([^'\"\\]+)['\"]\)\)\)\[['\"]([^'\"\\]+)['\"]\]", expression)
    if direct:
        loaded = _relative_source(path, direct.group(1))
        sources, error = ([(loaded, direct.group(2), f"{path} direct JSON binding for {table}", False)], "") if loaded else ([], "unsupported non-relative JSON path")
    else:
        call = re.fullmatch(r"(" + _IDENT + r")\(" + _IDENT + r"\)", expression)
        sources, error = methods.get(call.group(1), (None, "unsupported JSON loader call")) if call else (None, "unsupported JSON table binding")
        if call:
            definitions = list(re.finditer(r"^[ \t]*def\s+" + re.escape(call.group(1)) + r"\b", code, re.M))
            if len(definitions) != 1 or definitions[0].start() >= offset:
                return [], "unsupported ambiguous or unavailable JSON loader definition"
    _, code = _clearance_code(text)
    if any(re.search(r"\b" + re.escape(table) + r"\b", interpolation)
           for interpolation in re.findall(r"#\{([^}]*)\}", text[offset:before])):
        return [], f"unsupported interpolated use of JSON table {table}"
    tail = text[offset:before]
    first_line_end = tail.find("\n")
    tail = tail[first_line_end + 1:] if first_line_end >= 0 else ""
    audit_error = _NumericExpression(tables=(table,)).audit(tail)
    if audit_error:
        return [], audit_error
    return list(sources or []), error

def clearance_declarations(text: str, *, files: Optional[Dict[str, str]] = None,
                           source_path: str = "",
                           origins: Optional[List[Tuple[int, int, str, int]]] = None) -> List[Dict[str, Any]]:
    body, code = _clearance_code(text or "")
    assignments = list(_RE_CLEAR_ASSIGN.finditer(code))
    out: List[Dict[str, Any]] = []

    def assigned(name, before):
        found = [a for a in assignments if a.start() < before and a.group(1) == name]
        if not found:
            return None
        assignment = found[-1]
        end = assignment.end(2)
        while (code[assignment.start(2):end].count("(")
               > code[assignment.start(2):end].count(")") and end < len(code)):
            next_line = code.find("\n", end + 1)
            end = len(code) if next_line < 0 else next_line
        return body[assignment.start(2):end].strip(), assignment.start()

    def marker(expression, before, seen=(), intersected=False):
        if re.fullmatch(_IDENT, expression):
            if (_RE_GUARD_RING_VAR.search(expression)
                    or intersected and _RE_SEAL_RING_VAR.search(expression)):
                return expression
            if expression in seen:
                return None
            source = assigned(expression, before)
            if source:
                return marker(source[0], source[1], (*seen, expression), intersected)
        qualified = re.fullmatch(
            rf"({_IDENT})\s*\.\s*and\s*\(\s*({_IDENT})\s*\)", expression)
        if qualified and any(marker(v, before, seen, True) for v in qualified.groups()):
            return expression
        return None

    for match in _RE_SEPARATION.finditer(code):
        marker_expression = body[match.start(2):match.end(2)].strip()
        seal = marker(marker_expression, match.start())
        if not seal:
            continue
        expression = body[match.start(3):match.end(3)].strip()
        um = re.fullmatch(r"(.+?)\s*\.\s*um", expression)
        value_expression = um.group(1).strip() if um else expression
        seen = set()
        before = match.start()
        local_error = ""
        while re.fullmatch(_IDENT, value_expression) and value_expression not in seen:
            seen.add(value_expression)
            bindings = [a for a in assignments if a.start() < before and a.group(1) == value_expression]
            if len(bindings) > 1:
                local_error = f"unsupported reassigned clearance local {value_expression}"
                break
            source = assigned(value_expression, before)
            if not source:
                break
            local_error = _NumericExpression(names=(value_expression,)).audit(
                body[bindings[0].end(2):before])
            if local_error:
                break
            value_expression, before = source
        sources = []
        basis = ""
        reference = None
        value = None
        try:
            expression_node = _NumericExpression.parse(value_expression)
            refs = _NumericExpression.references(expression_node, assigned, before)
            identities = {(table, key) for table, key, _ in refs}
            if len(identities) > 1:
                raise ValueError("unsupported multiple JSON clearance references")
            source_tables = {}
            for table, key, binding_before in refs:
                table_sources, binding_error = _table_sources(
                    table, assigned(table, binding_before), body, source_path,
                    origins or [], match.start())
                if binding_error:
                    raise ValueError(binding_error)
                source_tables[table] = table_sources
                sources.extend(source for source in table_sources if source not in sources)
                reference = (table, key)

            def lookup(table, key, binding_before, method):
                nonlocal basis
                if method not in ("to_f", "to_i"):
                    raise ValueError("JSON lookup requires a numeric conversion")
                number, evidence, _ = _clearance_value(
                    f"{table}[{key!r}].{method}", files or {}, source_tables[table])
                basis = evidence
                if number is None:
                    raise ValueError(evidence)
                return math.trunc(number) if method == "to_i" else number

            if not um:
                raise ValueError(f"clearance `{expression}` has no readable um value")
            if local_error:
                raise ValueError(local_error)
            value = _NumericExpression.evaluate(expression_node, assigned, lookup, before)
            if value < 0:
                raise ValueError("negative clearance")
            value = float(value)
        except (SyntaxError, ValueError, TypeError, ZeroDivisionError, OverflowError, RecursionError) as exc:
            value, basis = None, str(exc)
        tail = _RE_RULE_ID.search(body, match.start(3), min(len(body), match.start(3) + 400))
        origin_path, origin_line = _source_at(match.start(), origins or [], source_path)
        segment = next((start for start, end, path, line in origins or [] if start <= match.start() < end), 0)
        if origins and origin_path != source_path:
            basis += f"; declared include ancestry rooted at {source_path}, clearance in {origin_path}"
        out.append({"file": origin_path, "prime_layer": match.group(1), "marker": seal, "um": value,
                    "rule": tail.group(1) if tail else None,
                    "line": origin_line + body.count("\n", segment, match.start()),
                    "value_basis": basis, "reference": reference, "json_source": sources[0][0] if len(sources) == 1 else None,
                    "json_sources": [source[0] for source in sources],
                    "json_bindings": [(source[0], source[1]) for source in sources],
                    "error": basis if value is None else ""})
    return out

# ── the technology reads ────────────────────────────────────────────────────

def _read_files(run_sh: ShellFn, find_cmd: str) -> Tuple[Dict[str, str], str]:
    """({path: text}, why-not). `find_cmd` must print one path per line."""
    # `while read` rather than `for f in $(…)`: a path is a path, not a word
    # list. `head -c` caps what a mis-aimed search can drag back.
    cmd = (f"{{ {find_cmd} ; }} | while IFS= read -r f; do "
           f"echo \"{_SEP}$f\"; cat \"$f\"; echo; done | head -c {_MAX_BYTES}")
    try:
        rc, out = run_sh(cmd)
    except Exception as exc:                                   # noqa: BLE001
        return {}, f"the technology could not be read: {exc}"
    if not (out or "").strip():
        return {}, (f"nothing was returned by `{find_cmd}` (rc={rc}), so the "
                    f"technology has not been read")
    files: Dict[str, str] = {}
    cur: Optional[str] = None
    buf: List[str] = []
    for line in (out or "").splitlines():
        if line.startswith(_SEP):
            if cur is not None:
                files[cur] = "\n".join(buf)
            cur, buf = line[len(_SEP):].strip(), []
        elif cur is not None:
            buf.append(line)
    if cur is not None:
        files[cur] = "\n".join(buf)
    if not files:
        return {}, (f"`{find_cmd}` returned output that carried no file "
                    f"(rc={rc})")
    if len(out) >= _MAX_BYTES:
        # A CAP THAT FIRES IS A READ THAT DID NOT FINISH. The last file came
        # back cut in half and its declarations are missing from the parse; a
        # partial read that answers is worse than one that says it could not.
        return {}, (f"`{find_cmd}` returned {len(out)} bytes, at or over this "
                    f"module's {_MAX_BYTES}-byte cap, so the last file was cut "
                    f"and the technology has been read only in part")
    return files, ""


def ring_band_um(pdk_dir: str, run_sh: ShellFn) -> Tuple[Optional[float], str]:
    """(the seal ring's edge depth in um, the basis) or (None, why not).

    Read from the generator's OWN cell library — the same tree the PDK's
    `sealring.py` puts on `sys.path` before importing the cells it draws.
    Two different declared widths is NOT_MEASURED naming both: picking one
    would be this program choosing foundry data.
    """
    # `-L` / `-R`: a PDK directory is very often a SYMLINK into a versioned
    # store (measured: `gf180mcuD -> ciel/gf180mcu/versions/<sha>/gf180mcuD` in
    # this image), and a search that does not follow one reports an empty
    # technology with no error at all.
    find = (f"find -L {pdk_dir} -maxdepth 8 -type f -name '*.py' 2>/dev/null "
            f"| grep -i seal")
    files, why = _read_files(run_sh, find)
    if why:
        return None, (f"no seal-ring generator source could be read under "
                      f"{pdk_dir}: {why}")
    found: Dict[float, List[str]] = {}
    for path, text in sorted(files.items()):
        for name, val in band_declarations(text):
            found.setdefault(val, []).append(f"{path}:{name}")
    if not found:
        return None, (f"none of the seal-ring generator sources under "
                      f"{pdk_dir} ({', '.join(sorted(files))}) declares a seal "
                      f"width, so how deep the ring's edge is was not read")
    if len(found) > 1:
        detail = "; ".join(f"{v} um ({', '.join(w)})"
                           for v, w in sorted(found.items()))
        return None, (f"the seal-ring generator sources under {pdk_dir} "
                      f"declare more than one seal width — {detail} — and "
                      f"choosing between them here would be this flow deciding "
                      f"foundry data")
    val = next(iter(found))
    return val, (f"the seal-ring generator's own cell library declares "
                 f"{found[val][0]} = {val} um")


def _clearance_contexts(files: Dict[str, str]):
    edges = {}
    relevant = set()
    for path, text in files.items():
        edges[path] = [(m.start(), m.end(), _relative_source(path, m.group(1)))
                       for m in _deck_includes(text)]
        if clearance_declarations(text, source_path=path):
            relevant.add(path)
    changed = True
    while changed:
        changed = False
        for path, includes in edges.items():
            if path not in relevant and any(child in relevant for _, _, child in includes):
                relevant.add(path)
                changed = True
    children = {child for path in relevant for _, _, child in edges[path] if child in relevant}
    roots = sorted(relevant - children)
    if relevant and not roots:
        return [], "unsupported include cycle in seal clearance ancestry"
    contexts = []
    visited = set()

    def expand(path, stack):
        if path in stack:
            raise ValueError(f"unsupported include cycle at {path}")
        visited.add(path)
        chunks = []
        origins = []
        cursor = 0
        length = 0
        text = files[path]

        def append(part, line):
            nonlocal length
            chunks.append(part)
            origins.append((length, length + len(part), path, line))
            length += len(part)
            if length >= _MAX_BYTES:
                raise ValueError("include-expanded clearance context exceeds source read cap")

        for start, end, child in edges[path]:
            if child not in files:
                continue
            append(text[cursor:start], text.count("\n", 0, cursor) + 1)
            child_text, child_origins = expand(child, (*stack, path))
            chunks.append(child_text)
            origins.extend((a + length, b + length, p, line) for a, b, p, line in child_origins)
            length += len(child_text)
            append("\n", text.count("\n", 0, start) + 1)
            cursor = end
        append(text[cursor:], text.count("\n", 0, cursor) + 1)
        return "".join(chunks), origins

    try:
        for path in roots:
            text, origins = expand(path, ())
            contexts.append((path, text, origins))
    except ValueError as exc:
        return [], str(exc)
    if not relevant.issubset(visited):
        return [], "unsupported include cycle in seal clearance ancestry"
    return contexts, ""


def guard_ring_clearance_um(pdk_dir: str,
                            run_sh: ShellFn) -> Tuple[Optional[float], str]:
    """Read clearances in their declared include and ordered JSON loader context."""
    discovery = _RE_SEAL_RING_VAR.pattern + r"|%include|JSON[.]parse|File[.]read"
    find = (f"grep -RIlEi {shlex.quote(discovery)} "
            f"--include='*.rb' --include='*.drc' --include='*.lydrc' "
            f"-- {shlex.quote(pdk_dir)} 2>/dev/null")
    files, why = _read_files(run_sh, find)
    if why:
        return None, (f"no DRC deck stating a guard-ring-marker separation "
                      f"could be read under {pdk_dir}: {why}")
    pending = {_relative_source(path, m.group(1))
               for path, text in files.items() for m in _deck_includes(text)}
    seen = set(files)
    while pending:
        path = pending.pop()
        if path is None or path in seen:
            continue
        seen.add(path)
        quoted = shlex.quote(path)
        included, why = _read_files(
            run_sh, f"if [ -f {quoted} ]; then printf '%s\\n' {quoted}; fi")
        if why:
            if "nothing was returned" in why:
                continue
            return None, why
        files.update(included)
        pending.update(_relative_source(path, m.group(1))
                       for text in included.values() for m in _deck_includes(text))
    contexts, why = _clearance_contexts(files)
    if why:
        return None, why

    def declarations(json_files):
        return [d for path, text, origins in contexts
                for d in clearance_declarations(text, files=json_files,
                                                source_path=path, origins=origins)]

    decls = declarations({})
    bindings = {}
    for declaration in decls:
        identity = (declaration["file"], declaration["line"])
        bindings.setdefault(identity, set()).add(tuple(declaration["json_bindings"]))
    if any(len(contexts) > 1 for contexts in bindings.values()):
        return None, "unsupported ambiguous JSON loader contexts for an included seal rule"
    if not decls:
        return None, (f"the deck files under {pdk_dir} that mention a "
                      f"seal-ring marker ({', '.join(sorted(files))}) state "
                      f"no readable marker separation in um")
    paths = sorted({path for d in decls for path in d["json_sources"]})
    if paths:
        json_files, why = _read_files(
            run_sh, "printf '%s\\n' " + " ".join(shlex.quote(p) for p in paths))
        if why:
            return None, f"the declared JSON rule sources could not be read: {why}"
        decls = declarations(json_files)
    unread = [f"{d['file']}:{d['line']} "
              f"{d['rule'] or 'seal clearance'}: {d['error']}"
              for d in decls if d["um"] is None]
    if unread:
        return None, "the seal-ring clearance could not be read: " + "; ".join(unread)
    worst = max(d["um"] for d in decls)
    evidence = sorted({f"{d['file']}:{d['line']}"
                       + (f" rule {d['rule']}" if d["rule"] else "")
                       + (f"; {d['value_basis']}" if d["value_basis"] else "")
                       for d in decls})
    values = sorted({d["um"] for d in decls})
    return worst, (
        f"the PDK's own deck requires {worst} um between the seal-ring "
        f"marker and the prime die; " + "; ".join(evidence)
        + (f", stating {values} um" if len(values) > 1 else ""))


def derive(pdk_dir: str, run_sh: ShellFn,
           band_um: Optional[float] = None,
           band_basis: str = "") -> Dict[str, Any]:
    """The margin a DIE's core owes its own seal ring, and how it was reached.

        {"margin_um": 26.0 | None,
         "band_um": …, "band_basis": …,
         "clearance_um": …, "clearance_basis": …,
         "not_measured": {"band_um": why, …},     # only what is missing
         "chain": [ …, … ]}                       # PDK text -> numbers

    `band_um` may be supplied by a caller that MEASURED it (the inner extent of
    the ring the generator actually built). That measurement outranks reading
    the generator's parameter, and the basis says which was used.
    """
    rec: Dict[str, Any] = {"pdk_dir": pdk_dir, "not_measured": {}, "chain": []}

    if band_um is None:
        band_um, why = ring_band_um(pdk_dir, run_sh)
        band_basis = why
    if band_um is None:
        rec["not_measured"]["band_um"] = band_basis
    rec["band_um"] = band_um
    rec["band_basis"] = band_basis
    rec["chain"].append(f"band: {band_basis}")

    clear_um, clear_basis = guard_ring_clearance_um(pdk_dir, run_sh)
    if clear_um is None:
        rec["not_measured"]["clearance_um"] = clear_basis
    rec["clearance_um"] = clear_um
    rec["clearance_basis"] = clear_basis
    rec["chain"].append(f"clearance: {clear_basis}")

    if band_um is None or clear_um is None:
        rec["margin_um"] = None
        rec["margin_basis"] = (
            f"{NOT_MEASURED}: " + "; ".join(
                f"{k} — {v}" for k, v in sorted(rec["not_measured"].items())))
    else:
        rec["margin_um"] = float(band_um) + float(clear_um)
        rec["margin_basis"] = (
            f"{band_um} um of seal-ring band plus {clear_um} um of deck "
            f"clearance = {rec['margin_um']} um on every edge")
        rec["chain"].append(f"margin: {rec['margin_basis']}")
    return rec


def shell_from_argv(run_argv: Callable[..., Any]) -> ShellFn:
    """Adapt a `runner.run_argv(argv, env, timeout=…) -> (rc, out, err)` to the
    `run_sh` this module wants. Kept here so both callers adapt identically."""
    def _sh(cmd: str) -> Tuple[int, str]:
        rc, out, _err = run_argv(["sh", "-c", cmd], {}, timeout=180)
        return int(rc), (out or "")
    return _sh
