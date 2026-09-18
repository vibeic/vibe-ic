#!/usr/bin/env python3
r"""dynamic_module_load_registers_before_exec_check.py — a module loaded by
path must be in ``sys.modules`` BEFORE ``exec_module`` when the loaded file
defines a module-level ``@dataclass``.

THE DEFECT
----------
``spec_from_file_location`` + ``module_from_spec`` + ``loader.exec_module`` is
how this tree loads a program by path. The module object ``module_from_spec``
returns is NOT in ``sys.modules``; putting it there is a separate line that is
easy to leave out, and for most modules leaving it out costs nothing.

For a module that defines a ``@dataclass`` it costs the load. While the
decorator processes the class it asks the import table for the defining
module. MEASURED on CPython 3.12.3, loading a dataclass out of an unregistered
module::

    File ".../dataclasses.py", line 749, in _is_type
        ns = sys.modules.get(cls.__module__).__dict__
    AttributeError: 'NoneType' object has no attribute '__dict__'

The traceback names ``dataclasses.py`` and the decorated class. It does not
name the loader, and the loader is where the one-line cause is — so the reader
goes hunting in the wrong file. ``sys.modules[spec.name] = mod`` between the
two calls fixes it.

EXACTLY WHAT FAILS
------------------
All four clauses, in one scope, or the site is not a FAIL:

  1. ``spec_from_file_location`` → ``module_from_spec`` → ``exec_module`` in
     ONE function (or one module body / one class body), by line order;
  2. NO registration of THIS spec, as a STATEMENT OF THE LOADER'S OWN SCOPE,
     between the ``module_from_spec`` and the ``exec_module``;
  3. the loaded path is derivable from the syntax of the loading file;
  4. the file at the far end has, at its MODULE TOP LEVEL, a ``@dataclass``
     with an annotated field whose stored annotation is a string carrying no
     module prefix — i.e. the exact branch of ``dataclasses._is_type`` that
     dereferences ``sys.modules.get(cls.__module__)``.

Clause 2 is deliberately POSITIVE: it asks whether THIS spec was registered,
not whether anything at all was written to the import table. A registration is
``sys.modules[K] = <this module object>`` or ``sys.modules.setdefault(K, <this
module object>)``, and all three parts of that are checked.

THE KEY ``K`` may be spelled three ways, all of which denote the same string at
the moment the line runs: the SAME expression this site passed as the spec's
NAME argument; ``<specvar>.name``; or ``<modvar>.__name__``, which
``module_from_spec`` assigns from ``spec.name`` while it builds the object.
``sys.modules["something_else"] = mod`` was MEASURED to crash exactly like no
registration at all, and does not satisfy clause 2.

THE VALUE must be the module object this site is about: the bare name, or any
bare-name co-target of the chained ``mod = sys.modules[spec.name] =
<anything>``, whose two targets receive ONE object — the table cannot disagree
with ``mod`` there, whatever built it. (And if what it built is not a module
named ``spec.name``, the loader's own name check raises ``ImportError: loader
for target cannot handle other`` — MEASURED — which is a loud failure of a
different kind, not this silent one.) A subscript with no such co-target and a
value the syntax cannot follow (``sys.modules[k] = make()``) is read as no
registration.

THE STATEMENT must belong to the loader's scope, not to an ``if`` / ``for`` /
``try`` / ``with`` / ``match`` inside it. Nothing here proves a nested
registration runs on the path that reaches the exec — an earlier revision
credited ``if 0: sys.modules[spec.name] = mod``. A site whose only registration
is nested gets NO VERDICT: it is printed by file and line, kept out of the
denominator, and is never REGISTERED and never FAIL. MEASURED on this tree:
of 310 sites that used to read as registered, 284 register scope-directly and
26 do not — every one of the 26 a memoising loader whose whole
spec/register/exec sequence sits inside one ``if _cached is None:`` block. So
this deletion of credit costs 26 verdicts, changes no other verdict on the
tree, and exists for the site that has not been written yet.

Clause 4 is why the gate does not fire on the tree's many correct unregistered
loads. MEASURED on CPython 3.12.3 with the same three-line loader — each of
these loads CLEANLY out of an unregistered module, and each is a PASS here:

  * ``@dataclass class F: path: str`` with NO future import — the stored
    annotation is a live object, ``_is_type`` is never reached;
  * ``@dataclass class F: a: t.List[int]`` under the future import — the
    stored string carries the prefix ``t``, which takes the guarded branch;
  * ``@dataclass class Marker: pass`` — no annotated field, no loop body;
  * a ``@dataclass`` written inside a ``def``, or under ``if TYPE_CHECKING:``
    — the decorator does not run during ``exec_module``. Only ``tree.body`` is
    read here, never ``ast.walk``, so neither is visible to clause 4.

SOURCE IS READ AS SYNTAX, NEVER AS TEXT
---------------------------------------
Every decision comes from the AST. 976 files in this tree contain the string
``spec_from_file_location`` and only 482 CALL it; the rest carry a comment
block naming the function. Comments and string literals cannot satisfy this
checker and cannot trip it, so editing prose cannot move a verdict.

KNOWN CONSERVATISM — shapes this rule declines to judge
-------------------------------------------------------
Each can hide a real defect. Missing one is the accepted cost. Every line
below was MEASURED by building the shape, running it, and running this gate:

  * THE THREE CALLS AND THE DECORATOR MUST BE SPELLED BY NAME. The rule reads
    ``spec_from_file_location`` / ``module_from_spec`` / ``exec_module`` and
    the decorator name ``dataclass``, through any module alias
    (``iu.spec_from_file_location``, ``@dataclasses.dataclass`` and a bare
    ``from importlib.util import …`` all read). Rebound spellings do not:
    ``getattr(spec.loader, "exec_module")(mod)``, ``run = spec.loader.
    exec_module; run(mod)`` and ``from dataclasses import dataclass as dc``
    each make the site (or the target's dataclass) invisible and the load
    still dies. Closing that needs alias/dataflow tracking, which is more
    machinery than the rule is worth;
  * likewise only ``spec_from_file_location`` opens a site; the same defect
    reached via ``spec_from_loader(name, SourceFileLoader(...))`` is not seen;
  * A NESTED REGISTRATION BUYS SILENCE, NOT GREEN — and this is the one edit
    that still moves a real FAIL off the board. MEASURED: inserting
    ``if os.environ.get("X"): sys.modules[spec.name] = mod`` into a convicted
    loader leaves the runtime crashing at ``dataclasses.py:749`` and moves the
    site from FAIL to the no-verdict above — rc 1 -> 2 in a run where that was
    the only site, rc 1 -> 0 in a run that still has another resolved site.
    What it does not do is disappear: the site is printed with its file, its
    exec line, the line the registration is on, and the fact that the target
    holds the fatal kind of dataclass. The tighter rule — require the
    registration to be at least as direct as the exec — was MEASURED and NOT
    taken. It would cost none of the 26 sites here (all 26 also exec from
    inside their own block), but it convicts
    ``try: sys.modules[spec.name] = mod`` / ``except Exception: pass``
    followed by a scope-direct exec, which runs correctly. A false positive on
    working code is worse than a softening that prints its own name;
  * a loader split across two functions (``module_from_spec`` in one,
    ``exec_module`` in another) forms no site at all;
  * clause 4 reads the target's ``tree.body`` and nothing else, so a
    module-level ``@dataclass`` written under an ``if`` or a ``try`` at module
    level is not read (MEASURED: that load still dies). ``ast.walk`` was tried
    and reverted — it also returns classes inside a ``def`` and under
    ``if TYPE_CHECKING:``, which do NOT die, and failing those is worse;
  * a quoted annotation in a file with NO future import is the crash too, and
    is not read here — clause 4 requires the future import;
  * a ``@dataclass`` nested inside another class, or built by
    ``dataclasses.make_dataclass``, is not read;
  * where the loaded path is a parameter, a loop variable, a value from the
    environment or anything else the syntax does not pin down, the site is
    UNRESOLVED: named on stdout with its file and line, kept out of the
    denominator, never counted as clean. A run in which NO site resolves
    exits 2 rather than passing.

KNOWN FALSE POSITIVES — what clause 2 cannot read
--------------------------------------------------
This is NOT a list of exceptions to the rule; it IS the rule, sampled. Clause 2
reads two syntactic shapes only — ``sys.modules[K] = mod`` and
``sys.modules.setdefault(K, mod)`` — written in the loader's own scope against
a subscript whose base is spelled ``modules``. Every OTHER way of putting a
module into the import table is a false positive here: the code runs and the
gate calls it a defect. The class is open; these seven were built, RUN, and put
through this gate, and each one loads cleanly and is reported as a FAIL:

  * ``_register(spec, mod)`` — a helper in the same file does the write. The
    helper's body is a different scope;
  * ``with _in_import_table(spec, mod):`` — same, via a context manager;
  * ``sys.modules.update({spec.name: mod})``;
  * ``_tbl = sys.modules`` and then ``_tbl[spec.name] = mod`` — an alias of
    the table;
  * ``from sys import modules as _m`` and then ``_m[spec.name] = mod`` — the
    same alias, bound at import time;
  * ``sys.modules |= {spec.name: mod}``;
  * ``dict.__setitem__(sys.modules, spec.name, mod)``.

An eighth, for the letter of it: ``sys.modules[spec.name] = <some OTHER real
module>`` also survives the load (MEASURED — the decorator finds a ``__dict__``
and simply does not find the name in it) and is convicted here, because the
value is not this module object.

What bounds the class is the other measurement, not this list: swept over the
whole tree this gate reports ZERO FAILs, so zero of these shapes is live today.

They are deliberately not papered over. The previous revision carried an escape
hatch for the first two — "the module variable is handed to some call before
the exec, so I cannot prove anything" — and a reviewer measured that inserting
one ``print("loading", mod)`` line turned a real FAIL into a cannot-check while
the runtime still crashed. An escape hatch a debug print can open is worth less
than the false positive it removes. In every case above the remedy is the same
single line this gate asks for, written in the loader itself.

VERSION SENSITIVITY
-------------------
Clause 4 models ``dataclasses._is_type`` as it stands in CPython 3.12.3,
validated against the running interpreter case by case. PEP 649 changes when
annotations become strings; on an interpreter that ships it, clause 4 has to
be re-measured rather than assumed.

USAGE
-----
    dynamic_module_load_registers_before_exec_check.py [ROOT ...]

EXIT CODES
----------
    0 = PASS          every resolved site registers this spec, or loads a file
                      with no import-time-fatal dataclass
    1 = FAIL          a proven-fatal unregistered load was found
    2 = CANNOT-CHECK  a named root was absent, no file was read, or no site
                      resolved (the findings are printed first either way).
                      A site carries no verdict when the loaded path is not
                      derivable, when nothing is at the end of it, when it does
                      not parse, or when this spec's only registration is
                      nested in a compound statement.

chip-AGNOSTIC.
"""
from __future__ import annotations

import argparse
import ast
import functools
import os
import re
import sys
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

RC_PASS, RC_FAIL, RC_CANNOT_CHECK = 0, 1, 2

#: What ONE unit is, in this gate's own terms. NOT "site whose path resolved":
#: a site whose path resolves but whose only registration is nested carries no
#: verdict either, and counting it would make PASS mean less than it says.
DENOMINATOR_UNIT = "dynamic module-load site this gate reached a verdict on"

_SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", "node_modules",
              ".mypy_cache", ".venv", "venv", ".tox"}

_SPEC_FN = "spec_from_file_location"
_MODULE_FN = "module_from_spec"
_EXEC_FN = "exec_module"

#: Copied verbatim from ``dataclasses._MODULE_IDENTIFIER_RE`` (CPython 3.12.3).
#: Clause 4's whole boundary is this regex plus the ``if not module_name:``
#: branch beneath it, so it is mirrored rather than approximated.
_MODULE_IDENTIFIER_RE = re.compile(r"^(?:\s*(\w+)\s*\.)?\s*(\w+)")

#: `sys.modules`, `_sys.modules` and `from sys import modules` all present as
#: this attribute (or as a bare name).
_MODULES_ATTR = "modules"

_MAX_EVAL_DEPTH = 16


@dataclass
class Site:
    """One ``spec_from_file_location`` → ``exec_module`` sequence."""
    file: str
    spec_line: int
    exec_line: int
    module_var: str
    registered: bool
    target: Optional[str] = None
    verdict: str = "UNRESOLVED"
    reason: str = ""


#: Every state a site can end in. Exhaustive on purpose.
CLASSIFICATIONS = (
    "REGISTERED",           # this spec is written to the import table first
    "NO_FATAL_DATACLASS",   # unregistered, but the load does not die
    "FAIL",                 # unregistered and proven to die
    "UNRESOLVED",           # the loaded path is not derivable from the syntax
    "TARGET_MISSING",       # the path resolved but no file is there
    "TARGET_UNPARSEABLE",   # the file is there and does not parse
    "REGISTRATION_NOT_SCOPE_DIRECT",
                            # registered, but only inside a compound statement
)

#: Verdicts that say something about the site — the gate's denominator.
_JUDGED = ("REGISTERED", "NO_FATAL_DATACLASS", "FAIL")
_NO_VERDICT = tuple(c for c in CLASSIFICATIONS if c not in _JUDGED)


# ---------------------------------------------------------------------------
# Scope partitioning
# ---------------------------------------------------------------------------
_SCOPE_NODES = (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                ast.ClassDef)


def _scope_bodies(tree: ast.AST) -> List[Tuple[ast.AST, List[ast.stmt]]]:
    """Return (scope-node, statements-of-that-scope) for every scope.

    Statements nested in ``if`` / ``for`` / ``try`` / ``with`` / ``match``
    belong to the enclosing scope and are included; statements inside a nested
    ``def`` or ``class`` belong to that scope and are not. Every statement
    appears EXACTLY ONCE.
    """
    out: List[Tuple[ast.AST, List[ast.stmt]]] = []

    def collect(stmts: Sequence[ast.stmt], acc: List[ast.stmt]) -> None:
        for s in stmts:
            if isinstance(s, _SCOPE_NODES):
                continue          # its own scope; it gets its own entry
            acc.append(s)
            for _fname, fval in ast.iter_fields(s):
                if isinstance(fval, list):
                    inner = [x for x in fval if isinstance(x, ast.stmt)]
                    if inner:
                        collect(inner, acc)
            for handler in getattr(s, "handlers", []) or []:
                collect(handler.body, acc)
            for case in getattr(s, "cases", []) or []:
                collect(getattr(case, "body", []) or [], acc)

    for node in ast.walk(tree):
        if isinstance(node, _SCOPE_NODES):
            acc: List[ast.stmt] = []
            collect(node.body, acc)
            out.append((node, acc))
    return out


def _own_nodes(stmt: ast.stmt) -> List[ast.AST]:
    """``stmt`` plus its expression nodes, stopping at any nested statement.

    ``ast.walk`` descends through nested statements, so walking a flat scope
    list statement by statement visits an enclosed call once per enclosing
    block. Stopping at the boundary is what makes the scope list and the node
    walk agree on what ONE site is.
    """
    out: List[ast.AST] = [stmt]

    def rec(n: ast.AST) -> None:
        for ch in ast.iter_child_nodes(n):
            if isinstance(ch, (ast.stmt, ast.ExceptHandler)):
                continue
            if type(ch).__name__ == "match_case":
                continue
            out.append(ch)
            rec(ch)

    rec(stmt)
    return out


def _call_name(node: ast.AST) -> Optional[str]:
    if not isinstance(node, ast.Call):
        return None
    f = node.func
    if isinstance(f, ast.Attribute):
        return f.attr
    if isinstance(f, ast.Name):
        return f.id
    return None


def _assigned_names(stmt: ast.stmt) -> List[str]:
    targets: List[ast.expr] = []
    if isinstance(stmt, ast.Assign):
        targets = list(stmt.targets)
    elif isinstance(stmt, (ast.AnnAssign, ast.AugAssign)):
        targets = [stmt.target]
    names: List[str] = []
    for t in targets:
        names.extend(_target_names(t))
    return names


def _target_names(t: ast.expr) -> List[str]:
    if isinstance(t, ast.Name):
        return [t.id]
    if isinstance(t, (ast.Tuple, ast.List)):
        return [e.id for e in t.elts if isinstance(e, ast.Name)]
    return []


# ---------------------------------------------------------------------------
# Clause 2 — did THIS spec reach the import table before the exec?
# ---------------------------------------------------------------------------
def _is_modules_subscript(node: ast.expr) -> bool:
    """True for ``sys.modules[...]`` / ``_sys.modules[...]`` / ``modules[...]``."""
    if not isinstance(node, ast.Subscript):
        return False
    v = node.value
    if isinstance(v, ast.Attribute):
        return v.attr == _MODULES_ATTR
    if isinstance(v, ast.Name):
        return v.id == _MODULES_ATTR
    return False


def _same_object_names(assign: ast.Assign) -> Tuple[str, ...]:
    """Bare-name spellings that answer to the object this assignment stores.

    ``sys.modules[k] = mod`` stores what ``mod`` names. The chained
    ``mod = sys.modules[spec.name] = <anything>`` stores in the table EXACTLY
    what ``mod`` receives — one object, two targets — so every bare-name
    co-target names it too, whatever the value expression is. That spelling is
    mainstream and an earlier revision read its value (a Call) as "not a module
    variable" and convicted the correct fix.

    A subscript with no such co-target and a value the syntax cannot follow
    (``sys.modules[k] = make()``) yields NO names: it stays unreadable to this
    gate rather than laundering whichever variable sits beside it.
    """
    names = [assign.value.id] if isinstance(assign.value, ast.Name) else []
    for t in assign.targets:
        if isinstance(t, ast.Name):
            names.append(t.id)
    return tuple(names)


def _registration_lines(
        stmts: Sequence[ast.stmt], direct_ids: frozenset
) -> List[Tuple[int, Tuple[str, ...], Optional[ast.expr], bool]]:
    """``(lineno, names-of-the-stored-object, key-expression, scope-direct)``
    for every write to the import table: ``sys.modules[k] = mod`` and
    ``sys.modules.setdefault(k, mod)`` (both shapes ship in this tree).

    NAMES lets the caller require that THIS module object was the one stored.

    SCOPE-DIRECT is False when the registration is written inside an ``if`` /
    ``for`` / ``try`` / ``with`` / ``match`` of the loader's scope rather than
    as a statement of that scope. Nothing here proves such a registration runs
    on the path that reaches ``exec_module``, so the caller refuses to credit
    it — and refuses to convict on its absence either.
    """
    out: List[Tuple[int, Tuple[str, ...], Optional[ast.expr], bool]] = []
    for s in stmts:
        direct = id(s) in direct_ids
        if isinstance(s, ast.Assign):
            names = _same_object_names(s)
            for t in s.targets:
                if _is_modules_subscript(t):
                    out.append((s.lineno, names, t.slice, direct))  # type: ignore[union-attr]
            continue
        for sub in _own_nodes(s):
            if not isinstance(sub, ast.Call):
                continue
            f = sub.func
            if not isinstance(f, ast.Attribute) or f.attr != "setdefault":
                continue
            base = f.value
            if not ((isinstance(base, ast.Attribute) and base.attr == _MODULES_ATTR)
                    or (isinstance(base, ast.Name) and base.id == _MODULES_ATTR)):
                continue
            args = sub.args
            names = ((args[1].id,) if len(args) >= 2
                     and isinstance(args[1], ast.Name) else ())
            out.append((sub.lineno, names, args[0] if args else None, direct))
    return out


def _spec_name_arg(call: ast.Call) -> Optional[ast.expr]:
    """The ``name`` argument expression of ``spec_from_file_location``."""
    for kw in call.keywords:
        if kw.arg == "name":
            return kw.value
    return call.args[0] if call.args else None


def _key_names_this_spec(key: Optional[ast.expr], spec_name: Optional[ast.expr],
                         spec_var: str, module_var: str) -> bool:
    """True when ``key`` is provably the name this spec was built under.

    Three spellings, all of which denote the SAME string at the moment the
    registration runs:

      * the SAME expression this site passed as the spec's name argument;
      * ``<specvar>.name``;
      * ``<modvar>.__name__`` — ``module_from_spec`` assigns
        ``module.__name__ = spec.name`` while it builds the object, so before
        ``exec_module`` the two are the same string by construction. This is a
        mainstream spelling of the fix and an earlier revision convicted it.

    Anything else — a different literal, a different variable, ``__name__``
    (the LOADING module's own name, not the loaded one's) — is not accepted,
    because registering under a name the class does not carry was MEASURED to
    crash exactly like no registration at all.
    """
    if key is None:
        return False
    if isinstance(key, ast.Attribute) and isinstance(key.value, ast.Name):
        if key.attr == "name" and spec_var and key.value.id == spec_var:
            return True
        if key.attr == "__name__" and module_var and key.value.id == module_var:
            return True
    if spec_name is None:
        return False
    return ast.dump(key) == ast.dump(spec_name)


# ---------------------------------------------------------------------------
# Clause 3 — static path resolution
# ---------------------------------------------------------------------------
@dataclass
class _Ctx:
    """Names this file binds, plus the file's own location for ``__file__``."""
    file: str
    names: Dict[str, List[ast.expr]]
    opaque: set


def _bind_names(stmts: Sequence[ast.stmt], ctx: _Ctx) -> None:
    for s in stmts:
        if isinstance(s, ast.Assign) and len(s.targets) == 1 \
                and isinstance(s.targets[0], ast.Name):
            ctx.names.setdefault(s.targets[0].id, []).append(s.value)
        elif isinstance(s, ast.AnnAssign) and isinstance(s.target, ast.Name) \
                and s.value is not None:
            ctx.names.setdefault(s.target.id, []).append(s.value)
        else:
            ctx.opaque.update(_assigned_names(s))
        if isinstance(s, (ast.For, ast.AsyncFor)):
            ctx.opaque.update(_target_names(s.target))
        if isinstance(s, (ast.With, ast.AsyncWith)):
            for item in s.items:
                if item.optional_vars is not None:
                    ctx.opaque.update(_target_names(item.optional_vars))


def _resolve(node: ast.expr, ctx: _Ctx, depth: int = 0) -> Optional[str]:
    """Best-effort filesystem path for an expression, or ``None``.

    ``None`` is the honest answer for a function parameter, a computed stem or
    anything else the syntax does not pin down; the caller turns it into a
    per-site CANNOT-CHECK rather than a pass.
    """
    if depth > _MAX_EVAL_DEPTH:
        return None

    if isinstance(node, ast.Constant):
        return node.value if isinstance(node.value, str) else None

    if isinstance(node, ast.Name):
        if node.id == "__file__":
            return ctx.file
        if node.id in ctx.opaque:
            return None
        bound = ctx.names.get(node.id) or []
        if not bound:
            return None
        # EVERY binding must agree. A name rebound to two different paths is
        # not resolvable.
        seen = {_resolve(b, ctx, depth + 1) for b in bound}
        return seen.pop() if len(seen) == 1 else None

    if isinstance(node, ast.Attribute):
        if node.attr == "parent":
            base = _resolve(node.value, ctx, depth + 1)
            return os.path.dirname(base) if base else None
        return None

    if isinstance(node, ast.Subscript):
        v = node.value
        if isinstance(v, ast.Attribute) and v.attr == "parents":
            base = _resolve(v.value, ctx, depth + 1)
            idx = node.slice.value if isinstance(node.slice, ast.Constant) else None
            if base is None or not isinstance(idx, int) or idx < 0:
                return None
            for _ in range(idx + 1):
                base = os.path.dirname(base)
            return base
        return None

    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        left = _resolve(node.left, ctx, depth + 1)
        right = _resolve(node.right, ctx, depth + 1)
        return None if left is None or right is None else os.path.join(left, right)

    if isinstance(node, ast.JoinedStr):
        parts: List[str] = []
        for v in node.values:
            if isinstance(v, ast.Constant) and isinstance(v.value, str):
                parts.append(v.value)
            elif isinstance(v, ast.FormattedValue):
                inner = _resolve(v.value, ctx, depth + 1)
                if (inner is None or v.format_spec is not None
                        or v.conversion not in (-1, 115)):
                    return None
                parts.append(inner)
            else:
                return None
        return "".join(parts)

    if isinstance(node, ast.Call):
        return _resolve_call(node, ctx, depth)

    return None


def _resolve_call(node: ast.Call, ctx: _Ctx, depth: int) -> Optional[str]:
    fn = node.func
    name = _call_name(node)
    if name in ("Path", "PurePath", "PosixPath", "PurePosixPath"):
        if not node.args:
            return None
        acc = _resolve(node.args[0], ctx, depth + 1)
        for a in node.args[1:]:
            nxt = _resolve(a, ctx, depth + 1)
            if acc is None or nxt is None:
                return None
            acc = os.path.join(acc, nxt)
        return acc
    if name == "str":
        return _resolve(node.args[0], ctx, depth + 1) if node.args else None
    if name in ("resolve", "absolute", "expanduser") and isinstance(fn, ast.Attribute):
        return _resolve(fn.value, ctx, depth + 1)
    if name == "joinpath" and isinstance(fn, ast.Attribute):
        acc = _resolve(fn.value, ctx, depth + 1)
        for a in node.args:
            nxt = _resolve(a, ctx, depth + 1)
            if acc is None or nxt is None:
                return None
            acc = os.path.join(acc, nxt)
        return acc
    if name == "join":                      # os.path.join
        parts = [_resolve(a, ctx, depth + 1) for a in node.args]
        if not parts or any(p is None for p in parts):
            return None
        return os.path.join(*parts)          # type: ignore[arg-type]
    if name == "dirname":
        base = _resolve(node.args[0], ctx, depth + 1) if node.args else None
        return os.path.dirname(base) if base else None
    if name in ("abspath", "realpath", "normpath"):
        return _resolve(node.args[0], ctx, depth + 1) if node.args else None
    return None


# ---------------------------------------------------------------------------
# Clause 4 — what the far end of the load contains
# ---------------------------------------------------------------------------
def _decorator_is_dataclass(dec: ast.expr) -> bool:
    if isinstance(dec, ast.Call):
        dec = dec.func
    if isinstance(dec, ast.Name):
        return dec.id == "dataclass"
    if isinstance(dec, ast.Attribute):
        return dec.attr == "dataclass"
    return False


def _future_annotations(tree: ast.Module) -> bool:
    for s in tree.body:
        if isinstance(s, ast.ImportFrom) and s.module == "__future__":
            if any(a.name == "annotations" for a in s.names):
                return True
    return False


def _consulting_field(cls: ast.ClassDef) -> Optional[Tuple[str, str]]:
    """``(field, stored-annotation)`` for the first field that reaches the
    crashing branch of ``dataclasses._is_type``, or ``None``.

    Under ``from __future__ import annotations`` the compiler stores the
    UNPARSED SOURCE of the annotation. The crashing branch is taken when the
    regex matches and captures NO module prefix: ``str`` crashes,
    ``t.List[int]`` captures ``t`` and takes the guarded branch, and a quoted
    ``"str"`` stores ``"'str'"`` — leading quote, no match. All measured.
    """
    for s in cls.body:
        if not isinstance(s, ast.AnnAssign) or not isinstance(s.target, ast.Name):
            continue
        try:
            stored = ast.unparse(s.annotation)
        except Exception:                                   # pragma: no cover
            continue
        m = _MODULE_IDENTIFIER_RE.match(stored)
        if m and not m.group(1):
            return s.target.id, stored
    return None


@functools.lru_cache(maxsize=None)
def _target_profile(path: str) -> Tuple[str, str]:
    """Classify the loaded file: ``(state, detail)``.

    ``state`` is ``fatal`` / ``none`` / ``missing`` / ``unparseable``.
    ``fatal`` means a NAMED field of a NAMED module-top-level ``@dataclass``
    is proven to send the decorator down the branch that dereferences
    ``sys.modules.get(cls.__module__)``.
    """
    p = Path(path)
    if not p.is_file():
        return "missing", f"no file at {path}"
    try:
        text = p.read_text(errors="replace")
    except OSError as exc:
        return "unparseable", f"{type(exc).__name__}: {exc}"
    tree = _parse(text)
    if tree is None:
        return "unparseable", "the target does not parse as a Python module"
    if not _future_annotations(tree):
        return "none", ""
    for node in tree.body:                  # module top level ONLY, not walk()
        if not isinstance(node, ast.ClassDef):
            continue
        if not any(_decorator_is_dataclass(d) for d in node.decorator_list):
            continue
        hit = _consulting_field(node)
        if hit is not None:
            fname, stored = hit
            return "fatal", (f"@dataclass {node.name} at line {node.lineno} "
                             f"whose field {fname} carries the string "
                             f"annotation {stored!r} (via from __future__ "
                             f"import annotations) with no module prefix")
    return "none", ""


# ---------------------------------------------------------------------------
# Per-file analysis
# ---------------------------------------------------------------------------
def _parse(src: str) -> Optional[ast.Module]:
    """Parse, silencing the parser's own advisory warnings.

    Reading someone else's source emits ``SyntaxWarning`` for things like an
    unrecognised escape. That is a fact about the file being read, not a
    finding of this gate.
    """
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            tree = ast.parse(src)
        except (SyntaxError, ValueError):
            return None
    return tree if isinstance(tree, ast.Module) else None


def _location_arg(call: ast.Call) -> Optional[ast.expr]:
    for kw in call.keywords:
        if kw.arg == "location":
            return kw.value
    return call.args[1] if len(call.args) >= 2 else None


def analyse_source(src: str, filename: str) -> List[Site]:
    """Return every dynamic-load site in ``src``, already classified."""
    tree = _parse(src)
    if tree is None:
        return []
    fpath = os.path.abspath(filename)
    sites: List[Site] = []

    scopes = _scope_bodies(tree)
    # The module scope's own flat statement list IS the module binding set.
    # Binding it twice would record every top-level name twice, and a name
    # with two bindings is treated as unresolvable.
    module_ctx = _Ctx(file=fpath, names={}, opaque=set())
    for scope, stmts in scopes:
        if isinstance(scope, ast.Module):
            _bind_names(stmts, module_ctx)
            break

    for scope, stmts in scopes:
        if isinstance(scope, ast.Module):
            ctx = module_ctx
        else:
            ctx = _Ctx(file=fpath, names=dict(module_ctx.names),
                       opaque=set(module_ctx.opaque))
            _bind_names(stmts, ctx)
        if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)):
            a = scope.args
            for arg in (list(a.posonlyargs) + list(a.args) + list(a.kwonlyargs)
                        + ([a.vararg] if a.vararg else [])
                        + ([a.kwarg] if a.kwarg else [])):
                ctx.opaque.add(arg.arg)
                ctx.names.pop(arg.arg, None)

        specs: List[Tuple[int, str, ast.Call]] = []      # line, var, call
        mods: List[Tuple[int, str, Optional[str]]] = []  # line, var, spec var
        execs: List[Tuple[int, Optional[str]]] = []      # line, module var
        for s in stmts:
            names = _assigned_names(s)
            for sub in _own_nodes(s):
                if not isinstance(sub, ast.Call):
                    continue
                cn = _call_name(sub)
                if cn == _SPEC_FN:
                    specs.append((sub.lineno, names[0] if names else "", sub))
                elif cn == _MODULE_FN:
                    arg = sub.args[0] if sub.args else None
                    mods.append((sub.lineno, names[0] if names else "",
                                 arg.id if isinstance(arg, ast.Name) else None))
                elif cn == _EXEC_FN:
                    arg = sub.args[0] if sub.args else None
                    execs.append((sub.lineno,
                                  arg.id if isinstance(arg, ast.Name) else None))

        if not (specs and mods and execs):
            continue
        # Only statements of the scope ITSELF are scope-direct; anything the
        # walk collected out of an if/for/try/with/match is not.
        regs = _registration_lines(stmts, frozenset(id(s) for s in scope.body))

        for exec_line, mod_var in execs:
            cand = [m for m in mods if m[0] <= exec_line
                    and (mod_var is None or m[1] == mod_var)]
            if not cand:
                continue
            mod_line, mod_name, spec_var = max(cand, key=lambda m: m[0])
            scand = [s for s in specs if s[0] <= mod_line
                     and (spec_var is None or s[1] == spec_var)]
            if not scand:
                continue
            spec_line, spec_assigned, spec_call = max(scand, key=lambda s: s[0])

            target_var = mod_var or mod_name
            spec_name = _spec_name_arg(spec_call)
            matched = [(rline, direct) for rline, rnames, rkey, direct in regs
                       if mod_line <= rline < exec_line
                       and target_var and target_var in rnames
                       and _key_names_this_spec(rkey, spec_name, spec_assigned,
                                                target_var)]
            registered = any(direct for _rline, direct in matched)
            # A registration nested in a compound statement is not proven to
            # run on the path that reaches the exec. It is not credit, and it
            # is not a conviction either.
            nested_only = bool(matched) and not registered

            site = Site(file=filename, spec_line=spec_line, exec_line=exec_line,
                        module_var=target_var or "<expr>", registered=registered)

            loc = _location_arg(spec_call)
            resolved = _resolve(loc, ctx) if loc is not None else None
            why_unresolved = ("loaded path is not derivable from the syntax; "
                              "this site carries no verdict")
            if resolved is not None and not os.path.isabs(resolved):
                # A path relative to the PROCESS working directory names a
                # different file per caller, so the syntax does not pin it
                # down: cannot-check, not a finding about some file.
                site.target = resolved
                why_unresolved = ("loaded path is relative to the process "
                                  "working directory; this site carries no "
                                  "verdict")
                resolved = None

            if registered:
                site.target = resolved
                site.verdict = "REGISTERED"
                site.reason = "this spec is written to the import table before exec_module"
            elif nested_only:
                site.target = resolved
                line = min(l for l, _d in matched)
                fatal = (resolved is not None
                         and _target_profile(resolved)[0] == "fatal")
                site.verdict = "REGISTRATION_NOT_SCOPE_DIRECT"
                site.reason = (
                    f"this spec is registered at line {line}, but only inside a "
                    f"compound statement, so nothing here proves the "
                    f"registration runs on the path that reaches exec_module"
                    + (f" — and {resolved} defines the fatal kind of dataclass"
                       if fatal else "") + "; this site carries no verdict")
            elif resolved is None:
                site.verdict = "UNRESOLVED"
                site.reason = why_unresolved
            else:
                site.target = resolved
                state, detail = _target_profile(resolved)
                if state == "fatal":
                    site.verdict, site.reason = "FAIL", detail
                elif state == "none":
                    site.verdict = "NO_FATAL_DATACLASS"
                    site.reason = ("target defines no module-level dataclass "
                                   "that consults the import table")
                elif state == "missing":
                    site.verdict, site.reason = "TARGET_MISSING", detail
                else:
                    site.verdict, site.reason = "TARGET_UNPARSEABLE", detail
            sites.append(site)
    return sites


# ---------------------------------------------------------------------------
# Sweep
# ---------------------------------------------------------------------------
def analyse_file(path: Path) -> List[Site]:
    try:
        src = path.read_text(errors="replace")
    except OSError:
        return []
    return analyse_source(src, str(path))


def sweep(roots: Sequence[str]) -> Tuple[List[Site], Dict[str, object]]:
    """Read every ``.py`` under ``roots``, THIS FILE INCLUDED.

    An earlier revision skipped its own path. Installed next to the code it
    judges, that made the file count and the verdict depend on which copy was
    executing — a gate that exempts itself is one edit away from a gate that
    exempts anything.
    """
    sites: List[Site] = []
    files_read = 0
    roots_present: List[str] = []
    roots_absent: List[str] = []
    for r in roots:
        base = Path(r)
        if not base.exists():
            roots_absent.append(str(r))
            continue
        roots_present.append(str(r))
        for p in ([base] if base.is_file() else sorted(base.rglob("*.py"))):
            if p.suffix != ".py" or not p.is_file():
                continue
            if any(part in _SKIP_DIRS for part in p.parts):
                continue
            files_read += 1
            sites.extend(analyse_file(p))
    stats: Dict[str, object] = {
        "files_read": files_read,
        "roots_present": roots_present,
        "roots_absent": roots_absent,
        "sites_total": len(sites),
    }
    for c in CLASSIFICATIONS:
        stats[c.lower()] = sum(1 for s in sites if s.verdict == c)
    return sites, stats


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("roots", nargs="*", default=["."],
                   help="directories (or files) of Python source to sweep")
    args = p.parse_args(list(argv) if argv is not None else sys.argv[1:])
    roots = [str(r) for r in (args.roots or ["."])]

    sites, stats = sweep(roots)
    fails = [s for s in sites if s.verdict == "FAIL"]
    # Every state that produced NO verdict, not just the one named UNRESOLVED:
    # a resolved path with no file at the end of it and a target that does not
    # parse are equally "I could not look". Counting only the first would make
    # `resolved + unresolved` stop adding up to the site total.
    unresolved = [s for s in sites if s.verdict in _NO_VERDICT]

    denom = sum(int(stats.get(k.lower(), 0)) for k in _JUDGED)
    absent = list(stats["roots_absent"])            # type: ignore[arg-type]
    scanned = (f"{stats['files_read']} file(s), {stats['sites_total']} load "
               f"site(s), {denom} resolved / {len(unresolved)} unresolved")

    # ---- findings first, always -------------------------------------------
    # Before any REFUSE: a run that had already FOUND a defect must not be
    # reduced to a bare "cannot check" with no finding on stdout at all.
    for s in fails:
        print(f"{s.file}:{s.exec_line}: exec_module({s.module_var}) with no "
              f"sys.modules registration of this spec since line "
              f"{s.spec_line}; {s.target} has {s.reason}")
    for s in unresolved:
        print(f"[cannot-check] {s.file}:{s.exec_line}: {s.reason}")

    # ---- the run's own preconditions --------------------------------------
    if absent:
        # A partial invocation used to print a clean PASS that never named the
        # path it could not open. A gate that silently narrows its own input
        # reports a clean bill for code it never read.
        print(f"[REFUSE] dynamic_module_load_registers_before_exec_check: "
              f"{len(absent)} of {len(roots)} requested root(s) absent: "
              f"{', '.join(absent)} — this run says nothing about them",
              file=sys.stderr)
        return RC_CANNOT_CHECK
    if stats["files_read"] == 0:
        print(f"[REFUSE] dynamic_module_load_registers_before_exec_check: "
              f"read 0 Python file(s) under {', '.join(stats['roots_present'])} "
              f"— nothing was searched, so this run says nothing about whether "
              f"an unregistered dataclass load ships", file=sys.stderr)
        return RC_CANNOT_CHECK
    if stats["sites_total"] and denom == 0:
        print(f"[REFUSE] dynamic_module_load_registers_before_exec_check: "
              f"{stats['sites_total']} load site(s) found and NONE resolved to "
              f"a verdict — see the cannot-check line(s) above", file=sys.stderr)
        return RC_CANNOT_CHECK

    if fails:
        print(f"[FAIL] dynamic_module_load_registers_before_exec_check: "
              f"{len(fails)} unregistered dataclass load(s); {scanned}")
        return RC_FAIL
    if not stats["sites_total"]:
        # A zero that names its own reason: files WERE read, and they contain
        # no dynamic module-load at all.
        print(f"[PASS] dynamic_module_load_registers_before_exec_check: "
              f"no dynamic module-load site exists under "
              f"{', '.join(stats['roots_present'])}; {scanned}")
        return RC_PASS
    print(f"[PASS] dynamic_module_load_registers_before_exec_check: "
          f"0 unregistered dataclass load(s); {scanned}")
    return RC_PASS


if __name__ == "__main__":
    raise SystemExit(main())
