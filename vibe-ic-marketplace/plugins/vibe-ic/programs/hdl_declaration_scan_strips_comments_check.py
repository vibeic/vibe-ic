#!/usr/bin/env python3
"""An HDL declaration scanned out of text nobody stripped the comments from.

THIS GATE BLOCKS (rc=1) on a NEW one. vibe-ic#731.

WHY IT EXISTS
-------------
`// This module controls the round counter` matches `\\bmodule\\s+(\\w*)` and
mints a module named `controls`. MEASURED on a real cell (vibe-ic#729): 24
phantom modules across the staged RTL, `_module_ports` then spanning from a
comment into a real header, and FS1 reporting `DC=UNMEASURED (0 faults
injected)` on a design shipping a genuine SEC-DED ECC.

IT IS A DATAFLOW QUESTION, NOT A PRESENCE ONE — and that distinction is the
whole reason this program exists rather than a one-line grep. The defect
function CALLS the stripper:

    code = _strip_hdl_comments(t)      # for combined_code
    ...
    for mod in _MODULE_RE.findall(t):  # on the RAW t

So "does this function reach a comment stripper" answers YES for the one
instance it was written for. Three detectors were built and retracted on that
basis before this one; see the issue. What is asked here is whether the STRING
FLOWING INTO THIS CALL passed a stripper, resolved by a local def-use walk.

READING THE PATTERN
-------------------
From the AST `Constant`, never from `ast.unparse`, and the metacharacters are
normalised before the keyword is matched. `ast.unparse` re-escapes, so
`r"\\bmodule\\s+"` renders with `b` immediately before `module` and a
`\\bmodule\\b` probe finds no word boundary — an artefact that silently produced
two confident, wrong populations (252 and 10, neither containing the known
instance).

THE CONTROLS ARE PART OF THE GATE
---------------------------------
`test_hdl_declaration_scan_strips_comments` drives both, and they are the
acceptance criterion recorded in the issue:

    POSITIVE  fmeda_fault_injection_coverage.detect_safety_mechanism at the
              commit before its fix MUST be flagged.
    NEGATIVE  the same function after the fix MUST NOT be.

A detector that does not flag the known instance is not measuring the right
thing, however plausible its output.

BASELINE
--------
Call sites that scan a declaration regex over an unstripped local. Most are
harmless — a netlist has no comments, a prompt is not HDL — and failing all of
them on day one is how a gate gets switched off. The set may only shrink;
anything NEW fails from the first run.

The live number is in `hdl_declaration_scan_baseline.json`, not here: a count
written into prose stops tracking the thing it counts. This docstring said 174
while the register held 171, and neither figure was challenged because nothing
compares them.

chip-AGNOSTIC: pure AST structure. No design, PDK or vendor literal.

USAGE
-----
    hdl_declaration_scan_strips_comments_check.py --root <plugin> [--json OUT]
                                                  [--write-baseline]

    --root is REQUIRED and has no default (vibe-ic#2199): a gate that
    substitutes its own tree for the one it was asked about answers
    confidently about the wrong subject.

    exit 0 = no NEW unstripped declaration scan
    exit 1 = a new one, or the baseline grew (BLOCKING)
    exit 2 = could not be determined — never a vacuous pass
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
import symtable
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

_BASELINE_NAME = "hdl_declaration_scan_baseline.json"

#: Regex metacharacters, blanked before the keyword search. See the docstring:
#: matching a keyword in a regex SOURCE without this is how the retracted
#: populations were produced.
_META = re.compile(r"\\[a-zA-Z]|\(\?[^)]*\)|[\[\]()+*?{}^$|]")
_KW = re.compile(r"\b(?:module|input|output|inout)\b")
#: A keyword GLUED TO A CHARACTER CLASS THAT CONTAINS A PATH SEPARATOR is
#: matching a path token, not a declaration. An HDL declaration is
#: `keyword <whitespace> identifier` and is never followed by `/`.
#:
#: MEASURED: `input[\\/]+docs|input_doc|\.(?:txt|pdf|...)` is a FILE-PATH and
#: EXTENSION matcher. `_META` blanks the brackets before the keyword search, so
#: it normalises to `input \\/  docs` and the bare `input` matched — the regex
#: was classified as an HDL declaration scan and its call site was reported for
#: not stripping comments it can never see. The value it scans is a provenance
#: SOURCE LABEL (a key of `extraction_evidence`), never HDL.
#:
#: THE SEPARATOR MUST BE A LITERAL `/`, not "any backslash in the class". Two
#: broader rules were written and measured against the whole tree first, and
#: both were WRONG in the direction that matters — they made the gate blind:
#:
#:   keyword followed by whitespace syntax   243 -> 90   lost `\bmodule\s+(\w*)`
#:   class containing `[\\/]`                243 -> 238  lost `inout[ \t]+`,
#:                                                       `module[ \t]+`,
#:                                                       `module[\s_-]?list`
#:                                                       (the backslash of `\t`
#:                                                        and `\s` is inside the
#:                                                        class)
#:
#: This rule removes EXACTLY the two path matchers tree-wide and gains nothing:
#: 243 -> 241, the two being this pattern in `stage_on_pass_review` and in
#: `phase1_evidence_grounding_check`. Proven by diffing the SETS, never counts —
#: a smaller population is what both wrong rules produced too.
_KW_PATH_TOKEN = re.compile(
    r"\b(?:module|input|output|inout)\b(?=\[[^\]]*/[^\]]*\])")
#: A keyword in ATTRIBUTE POSITION — `\.output\s*\(` — is a METHOD CALL, and
#: no Verilog declaration production can wear one: `output` is a reserved word,
#: so `.output(` cannot even be a port connection to a port of that name. The
#: instance is `_seal_ring_margin::_RE_RULE_ID`, which reads the rule NAME out
#: of a KLayout deck's own `extent.output('COV1.a', …)` and never parses HDL.
#:
#: MEASURED THE WAY `_KW_PATH_TOKEN` above was, by DIFFING THE SETS and not the
#: counts, over every `*.py` in the plugin at v1.19.60 (czmainred9):
#:
#:     population 254 -> 253
#:     DROPPED  {_seal_ring_margin::_RE_RULE_ID}
#:     ADDED    {}
#:
#: Exactly one entry, and it is the intended one. A rule that dropped more than
#: it named would be the same mistake the two retracted rules above made.
_KW_ATTRIBUTE_TOKEN = re.compile(
    r"\\\.\s*(?:module|input|output|inout)\b")
#: A name that means "comments are gone".
_STRIPPER = re.compile(r"strip.*comment|_strip_hdl|decomment|no_comment", re.I)
#: A regex SOURCE that removes comments by naming a comment INTRODUCER. Stripping
#: is an operation, not a function name: `re.sub(r"//[^\n]*", " ", txt)` removes
#: comments just as surely as a helper called `strip_comments`, and recognising
#: only the latter made this gate report a call site that was already correct.
#:
#: Backslashes are dropped before the search because the pattern is read as
#: SOURCE: `/\*.*?\*/` carries `/\*`, not `/*`. Reading it from the AST Constant
#: rather than `ast.unparse` matters for the same reason — unparse re-escapes.
#:
#: HONEST LIMIT: this accepts a call that strips only ONE comment form. A site
#: that removes `//` but never `/* */` will read as stripped here and is not.
#: That is a narrower hole than the one it closes, and naming it is better than
#: a stricter rule that fails every file whose HDL has only line comments.
_COMMENT_PAT = re.compile(r"//|/\*|\*/")
_SCAN = {"search", "finditer", "findall", "match", "fullmatch", "split", "sub"}

#: Exact false positives where the regex contains an HDL keyword but does not
#: parse HDL. This is deliberately not a wider pattern exception: widening
#: `declares_hdl` would also remove real declaration scans from the debt
#: population. Every row must remain a live raw finding and carry an argument.
_EXEMPT_REASON_MIN = 80
_NOT_HDL_DECLARATION: Dict[str, str] = {
    "librelane_prelayout::black_boxes::_BLACK_BOX_RE(sta_log)":
        "The regex reads OpenSTA's own link diagnostic in a STAPrePNR sta.log, "
        "'Warning 198: <file> line N, module X not found. Creating black box "
        "for Y.' The word 'module' is part of the tool message, not a Verilog "
        "declaration; the log is not HDL and has no comments to strip.",
    "_flow_reason_taxonomy::infer_nonverdict_reason::_BLOCKED_RE(text)":
        "The regex classifies English non-verdict reasons such as 'required "
        "output missing' and 'input docs absent'. Its input/output words are "
        "prose nouns, not Verilog declaration productions, and stripping HDL "
        "comments from a reason string would corrupt URLs and diagnostics.",
    "_flow_reason_taxonomy::infer_nonverdict_reason::_DECLARED_NA_RE(text)":
        "The regex classifies the English reason 'no inout' as a declared "
        "design N/A. It never extracts an HDL declaration; treating that prose "
        "word as one would require comment-stripping diagnostic text that is "
        "not HDL and may legitimately contain slash characters.",
}


_COMPREHENSIONS = (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)
_SCOPES = (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef,
           ast.Lambda) + _COMPREHENSIONS


def _definition_expressions(node: ast.AST, eager_annotations: bool):
    """Expressions evaluated before entering a function or class body."""
    yield from getattr(node, "decorator_list", ())
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
        yield from node.args.defaults
        yield from (value for value in node.args.kw_defaults if value is not None)
        if eager_annotations:
            args = (node.args.posonlyargs + node.args.args + node.args.kwonlyargs
                    + [arg for arg in (node.args.vararg, node.args.kwarg) if arg])
            yield from (arg.annotation for arg in args if arg.annotation is not None)
            if getattr(node, "returns", None) is not None:
                yield node.returns
    elif isinstance(node, ast.ClassDef):
        yield from node.bases
        yield from (keyword.value for keyword in node.keywords)


def _scope_nodes(scope: ast.AST, eager_annotations: bool = True):
    """Walk this scope, leaving nested scopes to their own binding context."""
    yield scope
    if isinstance(scope, _COMPREHENSIONS):
        # Python evaluates the first iterable in the enclosing scope. Targets,
        # filters, later iterables and the result live inside the comprehension.
        for field in ("elt", "key", "value"):
            if hasattr(scope, field):
                yield from _scope_nodes(getattr(scope, field), eager_annotations)
        for i, generator in enumerate(scope.generators):
            yield generator
            yield from _scope_nodes(generator.target, eager_annotations)
            if i:
                yield from _scope_nodes(generator.iter, eager_annotations)
            for condition in generator.ifs:
                yield from _scope_nodes(condition, eager_annotations)
        return
    if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        children = scope.body
    elif isinstance(scope, ast.Lambda):
        children = [scope.body]
    else:
        children = ast.iter_child_nodes(scope)
    for child in children:
        if isinstance(child, _SCOPES):
            yield child
            if isinstance(child, _COMPREHENSIONS):
                yield from _scope_nodes(child.generators[0].iter, eager_annotations)
            else:
                for expression in _definition_expressions(child, eager_annotations):
                    yield from _scope_nodes(expression, eager_annotations)
        else:
            yield from _scope_nodes(child, eager_annotations)


def compiled_patterns(tree: ast.AST, eager_annotations: bool = True) -> Dict[str, str]:
    """`NAME -> pattern source` for `re.compile(...)` in ONE lexical scope.

    Wider than `declaration_regexes`, and deliberately: a stripper's pattern is
    a COMMENT pattern, never a declaration one, so the map that recognises a
    strip cannot be the map that recognises a scan.
    """
    out: Dict[str, str] = {}
    for n in _scope_nodes(tree, eager_annotations):
        if isinstance(n, ast.Assign) and len(n.targets) == 1 \
                and isinstance(n.targets[0], ast.Name):
            p = _pattern_of(n.value)
            if p is not None:
                out[n.targets[0].id] = p
    return out


def _strips_comments_inline(call: ast.Call,
                            compiled: Optional[Dict[str, str]] = None) -> bool:
    """`re.sub(<a comment pattern>, ...)` — a strip written in place.

    TWO SPELLINGS, and recognising only the first made this gate accuse a call
    site that had already done the work. MEASURED at v1.19.60 (czmainred9):

        re.sub(r"//[^\n]*", " ", txt)          the module function: the
                                               pattern is `args[0]`
        _RPT_HDL_LINE_COMMENT_RE.sub("", txt)  a COMPILED regex's own method:
                                               `args[0]` is the REPLACEMENT and
                                               the pattern is not in the call

    `lec_equivalence_check.parse_rpt` opens with the second — it drops the
    Verilog line comments a tool echoes into its own log, and the reason is
    written above the pattern: a design carrying
    `// Found 999 unproven $equiv cells in module equiv:` would otherwise have
    written this gate's verdict out of its own source file, which the spoof arm
    of `test_lec_rpt_point_reading_precedence` catches. The strip is there, it
    is the right one, and this gate could not see it because the repository
    pre-compiles its regexes and the recogniser only knew `re.sub`.
    """
    fn = call.func
    if not (isinstance(fn, ast.Attribute) and fn.attr == "sub" and call.args):
        return False
    src = "".join(n.value for n in ast.walk(call.args[0])
                  if isinstance(n, ast.Constant) and isinstance(n.value, str))
    if _COMMENT_PAT.search(src.replace("\\", "")):
        return True
    # The compiled form: the receiver names the pattern.
    if compiled and isinstance(fn.value, ast.Name):
        pat = compiled.get(fn.value.id)
        if pat is not None and _COMMENT_PAT.search(pat.replace("\\", "")):
            return True
    return False


def declares_hdl(pattern: str) -> bool:
    """Does this regex SOURCE name an HDL declaration keyword?

    Path-token occurrences are blanked FIRST, on the ORIGINAL pattern: `_META`
    blanks the class brackets, so after it runs a path separator can no longer
    be told from whitespace.
    """
    p = _KW_PATH_TOKEN.sub(lambda m: " " * len(m.group(0)), pattern or "")
    p = _KW_ATTRIBUTE_TOKEN.sub(lambda m: " " * len(m.group(0)), p)
    return bool(_KW.search(_META.sub(" ", p)))


def _pattern_of(node: ast.AST) -> Optional[str]:
    if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == "compile" and node.args):
        return None
    parts = [n.value for n in ast.walk(node.args[0])
             if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    return "".join(parts) if parts else None


def declaration_regexes(tree: ast.AST) -> Dict[str, str]:
    return {name: pattern for name, pattern in compiled_patterns(tree).items()
            if declares_hdl(pattern)}


class _InlineSymbol:
    """The small symbol-table surface needed by an inlined comprehension."""

    def __init__(self, name: str, local: bool):
        self._name = name
        self._local = local

    def get_name(self):
        return self._name

    def is_global(self):
        return False

    def is_local(self):
        return self._local

    def is_parameter(self):
        return False


def _inline_comprehension_names(node: ast.AST,
                                eager_annotations: bool) -> Tuple[Set[str], Set[str]]:
    """Names visible in a comprehension whose scope PEP 709 inlined.

    The first iterable is evaluated in the enclosing scope. Every target and
    the remaining expressions belong to the comprehension scope. Nested scopes
    retain their own tables; only definition-time expressions and a nested
    comprehension's first iterable are evaluated here.
    """
    local: Set[str] = {
        name.id
        for generator in node.generators
        for name in ast.walk(generator.target)
        if isinstance(name, ast.Name)
    }
    names = set(local)

    class _Names(ast.NodeVisitor):
        def visit_Name(self, name):  # noqa: N802 — ast visitor spelling
            names.add(name.id)

        def visit_ListComp(self, child):  # noqa: N802
            self.visit(child.generators[0].iter)

        def visit_SetComp(self, child):  # noqa: N802
            self.visit(child.generators[0].iter)

        def visit_DictComp(self, child):  # noqa: N802
            self.visit(child.generators[0].iter)

        def visit_GeneratorExp(self, child):  # noqa: N802
            self.visit(child.generators[0].iter)

        def visit_Lambda(self, child):  # noqa: N802
            for expression in _definition_expressions(child, eager_annotations):
                self.visit(expression)

        def visit_FunctionDef(self, child):  # noqa: N802
            for expression in _definition_expressions(child, eager_annotations):
                self.visit(expression)

        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_ClassDef(self, child):  # noqa: N802
            for expression in _definition_expressions(child, eager_annotations):
                self.visit(expression)

    visitor = _Names()
    for field in ("elt", "key", "value"):
        if hasattr(node, field):
            visitor.visit(getattr(node, field))
    for index, generator in enumerate(node.generators):
        visitor.visit(generator.target)
        if index:
            visitor.visit(generator.iter)
        for condition in generator.ifs:
            visitor.visit(condition)
    return names, local


class _InlineComprehensionScope:
    """A lexical scope for PEP 709 list/set/dict comprehensions."""

    def __init__(self, node: ast.AST, parent, eager_annotations: bool):
        self._node = node
        names, local = _inline_comprehension_names(node, eager_annotations)
        self._symbols = [_InlineSymbol(name, name in local)
                         for name in sorted(names)]
        self._by_name = {symbol.get_name(): symbol for symbol in self._symbols}

    def get_type(self):
        return "function"

    def get_name(self):
        return type(self._node).__name__.lower()

    def get_lineno(self):
        return self._node.lineno

    def get_symbols(self):
        return list(self._symbols)

    def lookup(self, name):
        try:
            return self._by_name[name]
        except KeyError:
            raise KeyError(name) from None



def _comment_masker(node: ast.AST) -> bool:
    """Recognise the existing bounded character-mask loop, not its name.

    Both comment arms advance over their entire token before the common loop
    blanks that span. Only the resulting character list may be returned.
    Other helper shapes stay unknown; this is not a Python interpreter.
    """
    if (not isinstance(node, ast.FunctionDef) or node.decorator_list
            or not node.args.args or node.args.args[0].arg != 'src'):
        return False
    body = node.body
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        body = body[1:]
    def same(actual, text):
        expected = ast.parse(text).body
        actual = actual if isinstance(actual, list) else [actual]
        return [ast.dump(n, include_attributes=False) for n in actual] == [
            ast.dump(n, include_attributes=False) for n in expected]
    if (len(body) != 4 or not same(body[0], 'out = list(src)')
            or not same(body[1], 'i = 0')
            or not same(body[3], "return ''.join(out)")):
        return False
    loop = body[2]
    if (not isinstance(loop, ast.While) or loop.orelse or len(loop.body) != 3
            or ast.unparse(loop.test) != 'i < len(src)'
            or not same(loop.body[0], 'start = i')):
        return False
    line = loop.body[1]
    if (not isinstance(line, ast.If)
            or ast.unparse(line.test) != "src.startswith('//', i)"
            or not same(line.body, "end = src.find('\\n', i + 2)\ni = len(src) if end < 0 else end")
            or len(line.orelse) != 1 or not isinstance(line.orelse[0], ast.If)):
        return False
    block = line.orelse[0]
    if (ast.unparse(block.test) != "src.startswith('/*', i)"
            or not same(block.body, "end = src.find('*/', i + 2)\nif end < 0:\n    raise ValueError('unterminated_comment')\ni = end + 2")
            or not same(loop.body[2], "for j in range(start, i):\n    out[j] = '\\n' if src[j] == '\\n' else ' '")):
        return False
    # Remaining token arms cannot alter the input/output or escape the common
    # blanking loop. Their final fallback consumes one ordinary character.
    tail = block.orelse
    for child in ast.walk(ast.Module(body=tail, type_ignores=[])):
        if isinstance(child, (ast.Return, ast.Delete, ast.Break)):
            return False
        if isinstance(child, ast.Name) and (child.id == 'out' or (
                isinstance(child.ctx, ast.Store) and child.id not in {'i', 'end'})):
            return False
    while len(tail) == 1 and isinstance(tail[0], ast.If):
        tail = tail[0].orelse
    return same(tail, 'i += 1\ncontinue')


class _LexicalBindings:
    """Use Python's symbol table to resolve locals, globals and free names.

    Pattern extraction and the existing stripper rule remain shallow. This
    supplies lexical ownership and compiled-pattern arguments at source-bound
    named calls, not execution-order or arbitrary interprocedural analysis.
    """

    def __init__(self, tree: ast.Module, src: str):
        self.module = symtable.symtable(src, "<declaration-scan>", "exec")
        self.eager_annotations = not any(
            isinstance(node, ast.ImportFrom) and node.module == "__future__"
            and any(alias.name == "annotations" for alias in node.names)
            for node in tree.body)
        self.parents = {self.module: None}
        index = {}

        def collect(table):
            for child in table.get_children():
                key = (child.get_type(), child.get_name(), child.get_lineno())
                index.setdefault(key, []).append(child)
                self.parents[child] = table
                collect(child)

        collect(self.module)
        self.nodes = {self.module: tree}
        self.owners = {self.module: None}
        anonymous = {ast.Lambda: "lambda", ast.ListComp: "listcomp",
                     ast.SetComp: "setcomp", ast.DictComp: "dictcomp",
                     ast.GeneratorExp: "genexpr"}

        def attach(node, owner=None, parent_table=None):
            definitions = isinstance(
                node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda))
            if definitions:
                for expression in _definition_expressions(node, self.eager_annotations):
                    attach(expression, owner, parent_table)
            elif isinstance(node, _COMPREHENSIONS):
                attach(node.generators[0].iter, owner, parent_table)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                owner = node.name
            scope_table = parent_table
            if node is tree:
                scope_table = self.module
            elif isinstance(node, _SCOPES):
                kind = "class" if isinstance(node, ast.ClassDef) else "function"
                name = getattr(node, "name", anonymous.get(type(node)))
                key = (kind, name, node.lineno)
                try:
                    table = index[key].pop(0)
                except (KeyError, IndexError):
                    if not isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp)):
                        raise
                    table = _InlineComprehensionScope(
                        node, parent_table, self.eager_annotations)
                self.nodes[table] = node
                self.parents[table] = parent_table
                self.owners[table] = owner
                scope_table = table
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                children = node.body
            elif isinstance(node, ast.Lambda):
                children = [node.body]
            elif isinstance(node, _COMPREHENSIONS):
                children = list(ast.iter_child_nodes(node))
                for child in children:
                    if isinstance(child, ast.comprehension) and child is node.generators[0]:
                        for sub in [child.target] + child.ifs:
                            attach(sub, owner, scope_table)
                    else:
                        attach(child, owner, scope_table)
                return
            else:
                children = ast.iter_child_nodes(node)
            for child in children:
                attach(child, owner, scope_table)

        attach(tree, parent_table=None)
        self.patterns = {table: compiled_patterns(node, self.eager_annotations)
                         for table, node in self.nodes.items()}
        self.supplied_patterns = {}
        self._resolve_supplied_patterns()
        self.safe = {}
        self.maskers = set()
        for table, node in self.nodes.items():
            if not _comment_masker(node):
                continue
            owner = self.binding(self.parents[table], node.name)
            writes = sum(
                (isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                 and n.name == node.name)
                or (isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)
                    and n.id == node.name)
                or (isinstance(n, ast.alias) and (n.asname or n.name) == node.name)
                for n in _scope_nodes(self.nodes[owner], self.eager_annotations))
            if writes == 1:
                self.maskers.add((owner, node.name))

    def binding(self, table, name):
        """The defining scope; an unknown local still shadows outer regexes."""
        if table is self.module:
            return table
        try:
            symbol = table.lookup(name)
        except KeyError:
            symbol = None
        if symbol is not None:
            if symbol.is_global():
                return self.module
            if symbol.is_local() or symbol.is_parameter():
                return table
        parent = self.parents[table]
        # Class attributes are not lexical bindings available to a method.
        while parent is not self.module and parent.get_type() == "class":
            parent = self.parents[parent]
        return self.binding(parent, name)

    def pattern_candidates(self, table, name):
        owner = self.binding(table, name)
        pattern = self.patterns[table].get(name, self.patterns[owner].get(name))
        if pattern is not None:
            return {pattern}
        return self.supplied_patterns.get((owner, name), set())

    def _resolve_supplied_patterns(self):
        """Follow only compiled actuals to parameters of resolved named functions."""
        functions = {}
        for table, node in self.nodes.items():
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                owner = self.binding(self.parents[table], node.name)
                functions[(owner, node.name)] = table
        names = {name for _owner, name in functions}
        calls = []
        for caller, node in self.nodes.items():
            for call in _scope_nodes(node, self.eager_annotations):
                if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
                        and call.func.id in names):
                    continue
                target = functions.get((self.binding(caller, call.func.id), call.func.id))
                if target is None:
                    continue
                args = self.nodes[target].args
                pairs = []
                if not any(isinstance(arg, ast.Starred) for arg in call.args):
                    pairs += list(zip(args.posonlyargs + args.args, call.args))
                keyword_params = {arg.arg: arg for arg in args.args + args.kwonlyargs}
                pairs += [(keyword_params[keyword.arg], keyword.value)
                          for keyword in call.keywords if keyword.arg in keyword_params]
                calls += [(caller, target, formal.arg, actual) for formal, actual in pairs]
        grew = True
        while grew:
            grew = False
            for caller, target, name, actual in calls:
                pattern = _pattern_of(actual)
                patterns = ({pattern} if pattern is not None else
                            self.pattern_candidates(caller, actual.id)
                            if isinstance(actual, ast.Name) else set())
                slot = self.supplied_patterns.setdefault((target, name), set())
                added = patterns - slot
                if added:
                    slot.update(added)
                    grew = True

    def visible_patterns(self, table):
        out = {}
        for symbol in table.get_symbols():
            name = symbol.get_name()
            patterns = self.pattern_candidates(table, name)
            # A mixed set of actuals cannot establish that a sub strips comments.
            if len(patterns) == 1 or (patterns and all(
                    _COMMENT_PAT.search(pattern.replace("\\", "")) for pattern in patterns)):
                out[name] = "\n".join(sorted(patterns))
        return out

    def declaration_names(self, table):
        return {symbol.get_name() for symbol in table.get_symbols()
                if any(declares_hdl(pattern) for pattern in
                       self.pattern_candidates(table, symbol.get_name()))}

    def visible_maskers(self, table):
        return {symbol.get_name() for symbol in table.get_symbols()
                if (self.binding(table, symbol.get_name()), symbol.get_name())
                in self.maskers}

    def stripped(self, table):
        if table not in self.safe:
            inherited = set()
            for symbol in table.get_symbols():
                name = symbol.get_name()
                owner = self.binding(table, name)
                if owner is not table and name in self.stripped(owner):
                    inherited.add(name)
            node = self.nodes[table]
            if isinstance(node, _COMPREHENSIONS):
                first = node.generators[0]
                parent = self.parents[table]
                if _from_stripper(first.iter, self.visible_patterns(parent),
                                  self.stripped(parent), self.eager_annotations,
                                  self.visible_maskers(parent)):
                    inherited.update(n.id for n in ast.walk(first.target)
                                     if isinstance(n, ast.Name))
            self.safe[table] = stripped_locals(
                node, self.visible_patterns(table), inherited, self.eager_annotations,
                self.visible_maskers(table))
        return self.safe[table]


def _from_stripper(value: ast.AST, compiled: Optional[Dict[str, str]],
                   safe: Set[str], eager_annotations: bool = True,
                   maskers: Optional[Set[str]] = None) -> bool:
    """The existing value-flow rule, evaluated in the value's lexical scope."""
    if isinstance(value, _COMPREHENSIONS):
        if _from_stripper(value.generators[0].iter, compiled, safe, eager_annotations, maskers):
            return True
        bound = {n.id for generator in value.generators
                 for n in ast.walk(generator.target) if isinstance(n, ast.Name)}
        safe = safe - bound
        maskers = (maskers or set()) - bound
        compiled = {name: pattern for name, pattern in (compiled or {}).items()
                    if name not in bound}
    for sub in _scope_nodes(value, eager_annotations):
        if isinstance(sub, ast.Call):
            try:
                fname = ast.unparse(sub.func)
            except Exception:
                fname = ""
            if (_STRIPPER.search(fname)
                    or (isinstance(sub.func, ast.Name) and sub.func.id in (maskers or set()))
                    or _strips_comments_inline(sub, compiled)):
                return True
        if isinstance(sub, ast.Name) and sub.id in safe:
            return True
    return False


def stripped_locals(fn: ast.AST,
                    compiled: Optional[Dict[str, str]] = None,
                    inherited: Optional[Set[str]] = None,
                    eager_annotations: bool = True,
                    maskers: Optional[Set[str]] = None) -> Set[str]:
    """Locals whose value passed through a stripper, transitively.

    Per-NAME, which is the point: a sibling variable being stripped does not
    make this one safe.

    Three binding forms carry a value into a name, and all three propagate:
    assignment, a `for` target, and a comprehension target. Handling only
    assignment made `for line in stripped.splitlines():` read as unstripped,
    because the loop variable never inherited the iterable's status -- a false
    positive on correct code, and the common shape for a line-by-line scan.
    """
    ok: Set[str] = set(inherited or ())

    def _bindings(n: ast.AST):
        """(names bound, expression bound from) for every binding form."""
        if isinstance(n, ast.Assign) and len(n.targets) == 1 \
                and isinstance(n.targets[0], ast.Name):
            return [n.targets[0].id], n.value
        if isinstance(n, (ast.For, ast.AsyncFor)):
            return [x.id for x in ast.walk(n.target)
                    if isinstance(x, ast.Name)], n.iter
        if isinstance(n, ast.comprehension):
            return [x.id for x in ast.walk(n.target)
                    if isinstance(x, ast.Name)], n.iter
        return [], None

    grew = True
    while grew:
        grew = False
        for n in _scope_nodes(fn, eager_annotations):
            names, value = _bindings(n)
            if not names or value is None:
                continue
            if all(t in ok for t in names):
                continue
            if _from_stripper(value, compiled, ok, eager_annotations, maskers):
                ok.update(names)
                grew = True
    return ok


def scan_source(src: str, label: str) -> List[str]:
    """`label::function::REGEX(arg)` for every unstripped declaration scan."""
    try:
        tree = ast.parse(src)
        bindings = _LexicalBindings(tree, src)
    except SyntaxError:
        return []
    out: List[str] = []
    for table, scope in bindings.nodes.items():
        owner = bindings.owners[table]
        if owner is None or isinstance(scope, ast.ClassDef):
            continue
        regs = bindings.declaration_names(table)
        if not regs:
            continue
        safe = bindings.stripped(table)
        for n in _scope_nodes(scope, bindings.eager_annotations):
            if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and n.func.attr in _SCAN
                    and isinstance(n.func.value, ast.Name)):
                continue
            if n.func.value.id not in regs or not n.args:
                continue
            arg = n.args[-1] if n.func.attr in ("sub", "split") else n.args[0]
            if isinstance(arg, ast.Name) and arg.id not in safe:
                out.append(f"{label}::{owner}::{n.func.value.id}({arg.id})")
    return sorted(set(out))


def scan(root: Path) -> List[str]:
    out: List[str] = []
    for p in sorted((root / "programs").glob("*.py")):
        if p.stem.startswith("test_") or p.stem == Path(__file__).stem:
            continue
        try:
            out += scan_source(p.read_text(errors="replace"), p.stem)
        except OSError:
            continue
    return sorted(set(out))


def apply_exemptions(raw: List[str], root: Path) -> Tuple[List[str], List[str]]:
    """Remove only argued, live non-HDL matches; report stale rows loudly."""
    live = set(raw)
    problems: List[str] = []
    in_scope = {
        name for name in _NOT_HDL_DECLARATION
        if (root / "programs" / f"{name.split('::', 1)[0]}.py").is_file()
    }
    for name in sorted(in_scope):
        reason = _NOT_HDL_DECLARATION[name]
        if len(reason.strip()) < _EXEMPT_REASON_MIN:
            problems.append(
                f"{name}: reason is {len(reason.strip())} chars, under the "
                f"{_EXEMPT_REASON_MIN} required")
        if name not in live:
            problems.append(
                f"{name}: exempted, but the raw scan no longer flags it; "
                "delete or re-derive the exemption")
    return sorted(live - in_scope), problems


def _load(p: Path) -> Optional[List[str]]:
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    v = d.get("known") if isinstance(d, dict) else d
    return sorted(v) if isinstance(v, list) else None


#: THE OFFENDER REGISTER — a RATCHET BY MEMBERSHIP, and it is SOURCE.
#:
#: Same shape as `prose_polarity_consulted_check._OFFENDER_REGISTER`, and for
#: the same measured reason: a COUNT is not the instrument. This population went
#: 166 -> 165 -> 163 across a handful of landings while offenders were both
#: entering and leaving, so the number moved DOWN in the same window that three
#: new offenders arrived. Only membership names them.
#:
#: THE RULE (`--ratchet`): fail when an offender is NOT in this register — that
#: is a landing ADDING one, and it is blocked. The entry is DELETED IN THE SAME
#: COMMIT that fixes the offender, and an entry left behind once its offender is
#: gone is itself an offender, so the register cannot rot into a list of things
#: that used to be true.
#:
#: THIS IS NOT THE BASELINE AND NO FLAG WRITES IT. `hdl_declaration_scan_
#: baseline.json` is the DEBT register — 160 scans that predate the rule and are
#: owed down. This is the much narrower claim that a KNOWN NEW offender has a
#: named owner who is going to fix it. Reviewed in the diff like any other
#: source; `--write-baseline` remains the thing this gate must not be told to do
#: on a lane's behalf.
_OFFENDER_REGISTER: Dict[str, str] = {
    # EMPTY, AND THAT IS THE RATCHET FINISHING ITS JOB RATHER THAN A DISABLED
    # GATE. It shipped in this branch with four entries — czaes1's
    # `_chip_top_resolve_excluded_variant_params`, czlecresume's
    # `lec_proved_points_from_output`, czadcl10's
    # `_doc_module_name_label_or_inline` and czfsm's `_module_at`, each naming
    # its owner and its landing. v1.18.24 (83af0e54b, "six unstripped
    # declaration scans", #731) fixed all four, so all four entries are DELETED
    # here as source, in the commit that observed it — an entry that outlives
    # its offender is itself an offender, and `_ratchet_verdict` refuses one.
    #
    # An empty register is the STRONGEST state this gate has, not the weakest:
    # `--ratchet` now fails on ANY declaration scan over unstripped text, with
    # no membership to fall through. Nothing here needs to be re-added for the
    # next landing to be judged.
}


def _defines_function(root, name: str) -> bool:
    """Does THIS tree define the `module::function` an entry names?

    Scoped the way `main` already scopes everything else: an entry naming a
    function this checkout does not define is a claim about a DIFFERENT tree,
    not a claim that has expired. Without it, a correct entry for an offender
    that arrives with a later landing reads as stale on every older tree — the
    verdict would depend on which tree the gate was aimed at.
    """
    import ast as _ast
    parts = name.split("::")
    if len(parts) < 2:
        return False
    module, fn = parts[0], parts[1]
    src = Path(root) / "programs" / f"{module}.py"
    if not src.is_file():
        return False
    try:
        tree = _ast.parse(src.read_text(errors="replace"))
    except (OSError, SyntaxError):
        return False
    return any(isinstance(n, (_ast.FunctionDef, _ast.AsyncFunctionDef))
               and n.name == fn for n in _ast.walk(tree))


def _ratchet_verdict(new, root) -> int:
    """`offenders == register`, by MEMBERSHIP. The landing gate's question."""
    registered = set(_OFFENDER_REGISTER)
    offenders = set(new)
    unregistered = sorted(offenders - registered)
    stale = sorted(n for n in registered - offenders
                   if _defines_function(root, n))
    if unregistered:
        print(f"[FAIL] {len(unregistered)} declaration regex(es) scan text no "
              f"stripper touched and are NOT in the offender register:")
        for n in unregistered:
            print(f"   {n}")
        print("\n  Strip comments on the value that reaches the scan. If this "
              "landing cannot,\n  the entry names an OWNER who will — it does "
              "not name the gate as wrong.")
        return 1
    if stale:
        print(f"[FAIL] {len(stale)} offender-register entry(ies) no longer name "
              f"an offender — delete the entry in the commit that fixed it:")
        for n in stale:
            print(f"   {n}")
        return 1
    print(f"[PASS] hdl_declaration_scan: offenders are exactly the "
          f"{len(registered)} in the register; no landing added one.")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=None,
                    help="THE PLUGIN ROOT UNDER TEST. Required: there is no "
                         "default, because the only default available is this "
                         "program's own location and a run that substitutes "
                         "the instrument's tree for the subject's answers "
                         "confidently about a tree nobody asked about "
                         "(vibe-ic#2199)")
    ap.add_argument("--json", dest="json_out")
    ap.add_argument("--ratchet", action="store_true",
                    help="verdict by MEMBERSHIP against the offender register: "
                         "fail when an offender is unregistered (a landing "
                         "added one) or when an entry outlived its offender")
    ap.add_argument("--baseline", default=None)
    ap.add_argument("--write-baseline", action="store_true")
    a = ap.parse_args(argv)

    # NO DEFAULT SUBJECT. vibe-ic#2199.
    #
    # This used to fall back to `Path(__file__).resolve().parents[1]` -- the
    # RUNTIME's plugin -- and `repo_hygiene_gates.sh` passed no `--root`.
    # MEASURED on 8HD-4 at a61a8e4b4778 over two trees, the subject carrying
    # one extra unstripped declaration scan: no --root reported 159 sites and
    # 2 new offenders, `--root <subject>` reported 160 and 3. The extra
    # offender was in the tree under test and in neither answer the runner
    # published.
    if not a.root:
        print("[CANNOT DETERMINE] hdl_declaration_scan: no --root. This gate "
              "has no default subject and will not invent one: the only tree "
              "it could reach without being told is its OWN, and a verdict "
              "about the instrument's tree is indistinguishable from a "
              "verdict about yours. Name the plugin root under test "
              "(vibe-ic#2199). NOT a pass.", file=sys.stderr)
        return 2
    root = Path(a.root).resolve()
    if not (root / "programs").is_dir():
        print(f"[CANNOT DETERMINE] hdl_declaration_scan: no programs/ under "
              f"{root}. NOT a pass.", file=sys.stderr)
        return 2

    raw = scan(root)
    now, exemption_problems = apply_exemptions(raw, root)
    if exemption_problems:
        print("[FAIL] stale or unargued non-HDL declaration-scan exemption:")
        for problem in exemption_problems:
            print(f"   {problem}")
        return 1
    bpath = Path(a.baseline) if a.baseline else root / "programs" / _BASELINE_NAME

    if a.write_baseline:
        prev = _load(bpath) or []
        if prev and len(now) > len(prev):
            print(f"[FAIL] refusing to write a baseline that GREW "
                  f"({len(prev)} -> {len(now)}).", file=sys.stderr)
            return 1
        bpath.write_text(json.dumps(
            {"_comment": "Declaration regexes scanned over text no stripper "
                         "touched (vibe-ic#731). MAY ONLY SHRINK. A comment "
                         "sentence matching `module\\s+(\\w+)` mints a module "
                         "that does not exist — 24 of them, measured, in #729.",
             "known": now}, indent=2) + "\n")
        print(f"wrote {bpath} ({len(now)} recorded)")
        return 0

    base = _load(bpath)
    if a.json_out:
        Path(a.json_out).write_text(json.dumps(
            {"unstripped_scans": now, "baseline": base}, indent=2) + "\n")
    if base is None:
        print(f"[CANNOT DETERMINE] hdl_declaration_scan: no readable baseline "
              f"at {bpath}; {len(now)} call site(s) scan a declaration regex "
              f"over unstripped text and there is nothing to compare against. "
              f"NOT a pass.", file=sys.stderr)
        return 2

    new = sorted(set(now) - set(base))
    gone = sorted(set(base) - set(now))
    if a.ratchet:
        return _ratchet_verdict(new, root)
    print(f"  declaration scans over unstripped text: {len(now)} "
          f"(baseline {len(base)})")
    if gone:
        # AN ERRAND IS NOT A FINDING (hygiene census #2066, CZH-12). This line
        # used to read "Re-run with --write-baseline", which invites the next
        # lane to bank every offender THIS run happened to see as accepted debt
        # — the shrink and the arrivals are written by one flag. The shrink is
        # reported, and the remedy is a reviewed deletion.
        print(f"  [NOTE] the recorded set shrank by {len(gone)}: "
              f"{', '.join(gone[:3])}{' …' if len(gone) > 3 else ''}")
        print(f"         DELETE those lines from programs/{_BASELINE_NAME} as "
              f"source, in the commit\n"
              f"         that fixed them. Reviewed like code, in the diff.")
    if new:
        print(f"\n[FAIL] {len(new)} declaration regex(es) newly scan text no "
              f"stripper touched:")
        for n in new:
            print(f"   {n}")
        print("\n  A comment sentence matching `module\\s+(\\w+)` mints a module "
              "that does not\n  exist. Strip comments on the value that reaches "
              "the scan — stripping a\n  SIBLING variable does not make this one "
              "safe, which is the whole reason\n  this gate reads dataflow and "
              "not presence.")
        return 1
    if len(now) > len(base):
        print(f"\n[FAIL] the set grew {len(base)} -> {len(now)} with no new "
              f"name — the baseline is stale.")
        return 1
    print("[PASS] hdl_declaration_scan: no declaration regex newly reads "
          "unstripped text.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
