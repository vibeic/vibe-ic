#!/usr/bin/env python3
"""signoff_config_parse_failure_is_named_check.py — a config read may not
answer "I could not parse it" with "nothing was declared".

THE DEFECT THIS IS THE REGRESSION GUARD FOR
-------------------------------------------
A sign-off declaration file was read like this::

    cfg: Dict[str, Any] = {}        # (1) the ABSENT default
    if (staged_dir / "signoff_config.json").is_file():
        try:
            cfg = json.loads(cfg_f.read_text())
        except Exception:
            cfg = {}                # (2) LEAVES cfg at that same default

and every decision downstream was pulled out of it key by key
(``cfg.get("lvs_engine", "<default>")``, ``cfg.get("dummy_fill")``, twelve
more). One misplaced comma therefore reverted FOURTEEN declared sign-off
decisions to defaults nobody chose — including which implementation runs —
with nothing on stderr and nothing in any report, while a dozen lines away the
same function printed ``[WARN] ...`` to stderr about other declarations.

WHAT THIS CHECKER LOOKS FOR — five requirements, all read off ONE FUNCTION of
ONE FILE
---------------------------------------------------------------------------
1. CONFIG READ — a ``try`` whose body calls a structured-config parser
   (``json.load(s)``, ``yaml.load``/``safe_load``, ``toml``/``tomllib``
   ``load(s)``) RIGHT THERE, filling a plain name by assignment or by
   ``update()`` / ``setdefault()`` / ``extend()``. No bound on that body's
   size: what the failure branch does is not a function of how many
   statements precede it.
2. UNREADABLE == ABSENT — the LAST assignment to that name before the ``try``
   gives it an EMPTY CONTAINER (``{}``, ``[]``, ``()``, ``set()``, or the
   no-argument ``dict()`` / ``list()`` / ``tuple()`` forms). That line is this
   code's answer for "there is nothing to read", and it is what the name still
   holds when the parse raises. If the last thing assigned was a real value,
   a failed parse does not land on "absent": a different program.
3. SILENT HANDLER — a handler on that ``try`` that RAISES NOTHING, EMITS
   NOTHING, and LEAVES THE NAME AT THAT EMPTY DEFAULT, so "the file exists and
   is broken" becomes indistinguishable from "there is no file" with nobody
   told. Leaving it is ONE condition, not a list of shapes: re-assigning the
   same empty value, assigning some OTHER name, and ``pass`` all end with the
   name holding exactly what requirement 2 established. Bookkeeping beside the
   default (``ok = False``, ``seen.append(p)``) does not excuse it; a ``raise``
   or an emit does, because those NAME the failure and nothing else does.
4. DECLARATION SOURCE — that name is then READ, in this same function and
   outside this ``try``, for at least ``MIN_KEY_READS`` DISTINCT keys named by
   a LITERAL: ``name.get("k")`` or a LOAD of ``name["k"]``. A value merely
   passed along may legitimately be empty; a value mined key by key is a set
   of declared DECISIONS, and each key silently taking its default is a
   decision nobody made. A non-literal key and a STORE are not such reads;
   each was a wrong verdict on correct code (see ``_mined_keys``).
5. CONTRAST — somewhere among this function's OWN statements (a nested
   ``def``'s refusals are that inner function's position, not this one's) and
   outside this ``try``, the code already RAISES or writes to stderr /
   logging / ``warnings``. The function demonstrably knows how to speak up, so
   this silence is a defect and not a house style. No distance bound: it only
   picks WHICH contrast the message names.

MEASURED — this repo at 549f02433, 5798 Python files, each requirement added
in turn
---------------------------------------------------------------------------
    1 + the raise/emit half of 3 ... 1319 sites
    + 2 (unreadable == absent) .....   51 sites
    + the rest of 3 (leaves it) ....   44 sites
    + 4 (declaration source) .......   10 sites
    + 5 (contrast) .................    0 sites   <- shipped, rc 0

Requirements 2, 4 and 5 are NARROWING: each is there because the step above
it fires on legitimate code in this tree. Requirement 4's key COUNT is not
what keeps the tree clean — it is clean at 1 too — but it says what the
defect IS.

NOTHING HERE EXEMPTS A SITE
---------------------------
No skip list, no overlay exemption, no distance bound, no ``try``-body size
bound, no tuning flags, no cross-module loader index, no "the handler ASSIGNS
an empty container" — each was a one-edit way to make a live defect invisible:

* a SKIP LIST certified a subtree on one token: one directory name dropped
  94% of this tree while the run still printed ``[PASS]``;
* an OVERLAY EXEMPTION ("this function writes the file back") was entered by
  one added ``write_text`` call, and covered exactly the sites where the
  silence destroys the only copy;
* a LOADER INDEX keyed modules on ``Path.stem``, so two same-named files in
  different packages impersonated each other;
* a DISTANCE BOUND on requirement 5 was closed by inserting a COMMENT;
* a SIZE BOUND on the ``try`` body (``MAX_READ_STMTS``, was 4) was crossed by
  four dead assignments, and held nothing back: deleting it left rc 0;
* "ANY CALL IN THE HANDLER" was excused by one ``_failures.append(path)``;
* TUNING FLAGS narrowed the gate at the call site: the one number is now a
  module constant and the only arguments are the roots and ``--json``;
* "THE HANDLER ASSIGNS AN EMPTY CONTAINER" was requirement 3 until this round:
  requirement 2 already guarantees the name is at ``{}``, so ``pass`` — and
  ``_cfg_err = {}``, which rebinds a different name — each took rc 1 to rc 0
  with the defect bit-identical. Closed by asking what the name HOLDS rather
  than what the handler WRITES, not by adding a case for ``pass``.

THE CENSUS — a shrunken scan cannot be read as a pass
-----------------------------------------------------
Every ``*.py`` under every root is read and every file read is judged; one
that cannot be read or parsed makes the whole run CANNOT-CHECK rather than
quietly leaving the denominator. A root that does not exist, and a root
holding no Python, are each CANNOT-CHECK on their own even beside a full
sibling. "files scanned" is the whole census, in the message and ``--json``.

REACHABILITY — what edit turns this red
---------------------------------------
Writing the shape above — inline parse, a same-name empty default standing
when the ``try`` starts, a handler that neither raises nor speaks nor changes
that name, two literal keys READ out of it, and a refusal or a stderr line
anywhere in the function — turns this red anywhere in the scanned tree, at any
``try``-body length. Asserted against the real defect, not only fixtures:
pointed at the source file as it stood at the PARENT of the commit that fixed
it, this checker FAILS and names the handler line, the name it reverts, the
line where that same empty value already means "absent", and the fourteen
declared keys that go quiet; pointed at the fixed file it PASSES. On that same
source none of these bought green: ``pass`` for the default, ``_cfg_err = {}``
beside it, ``_cfg_err = None`` after it, ``_seen.append(cfg_f)`` in it,
``dict()`` for ``{}`` on either default, 1/4/40 dead assignments above the
parse, a statement appended to the ``try`` body, a comment before the ``try``,
and a comment in the handler claiming it raises. The edits that DO buy green
are under KNOWN CONSERVATISM, with their cost.

DISCLOSED — the ten sites one refusal away
------------------------------------------
Ten sites satisfy requirements 1-4 and are held out by requirement 5 alone:
nobody in those functions raises or writes to stderr. If one gains an
unrelated refusal this gate reddens there, so the list is not hidden (all
under ``vibe-ic-marketplace/plugins/vibe-ic/``)::


    benchmark/gates_atomic.py:574               main()    programs/benchmark_clean_room_check.py:138  audit()
    programs/benchmark_evidence_publish.py:1722 collect_step_records()
    programs/design_one_shot_runner.py:10406    step_full_stack_tb_gen()
    programs/design_one_shot_runner.py:11649    _merge_oracle_into_full_...()
    programs/design_one_shot_runner.py:17809    step_fpga_burn()
    programs/design_one_shot_runner.py:18189    step_phase3()
    programs/design_one_shot_runner.py:19843    step_dft_lec_chain()
    programs/formal_property_run.py:1510        _attach_property_contract()
    programs/formal_property_run.py:1555        _attach_property_contract()
Four are new this round and are exactly what requirement 3 used to miss:
their handlers are ``pass``, or they rebind some other name. Several read a
file they then rewrite, which is not innocent — the silence destroys the only
copy. Two sites LEFT the list: ``step_preflight.py:812`` when store subscripts
stopped counting as key reads, and ``backlog_severity_classify.py:93`` this
round, because the last assignment before its ``try`` is ``data = loaded``.

KNOWN FALSE POSITIVE — one, disclosed, not excluded
---------------------------------------------------
A MEMO CACHE READ FOR LITERAL KEYS is reported and should not be::

    cache = {}
    try:
        cache = json.loads(cache_f.read_text())
    except Exception:
        cache = {}
    ...  cache.get("wns") ...  cache.get("tns") ...
Recomputing on a corrupt cache is correct: those values are derivable, so
nothing was declared and nothing was reverted. This rule cannot separate that
from a declaration file, because the difference — "the caller can recompute
these" — is not in the syntax, and the one signal that looked structural
("this function writes the file back") is the deleted overlay exemption above.
Cache reads whose keys are NOT literals are already out of requirement 4 and
are the common spelling; this hits the fixed-key kind, of which this tree
holds none today. IF IT FIRES ON A CACHE, do what the finding asks: one line
above the default, ``print("[WARN] discarding unreadable %s: %s" % (cache_f,
exc), file=sys.stderr)``. That is right for a cache too — one that silently
goes cold is a performance cliff nobody can see — and nothing here can be
edited to exempt the site instead.

KNOWN CONSERVATISM (documented false negatives, deliberately not chased)
------------------------------------------------------------------------
Each is a shape this rule does NOT see, missed on purpose: catching it cost
either a wrong verdict on correct code or a one-edit way out of the rule.
* LOADER FORM. ``cfg = load_signoff_config(d)`` in the ``try`` — the parse one
  call away — is invisible, and so is that loader's own ``except: return {}``.
  It is the spelling the guarded defect's own fix moved to, so a one-hunk
  softening AT THAT SITE is not caught: the price of deleting the loader
  index, and the largest single thing this rule gave up.
* RETURN FORM. A handler containing a ``return`` is out of scope: control
  leaves, so the name's value is not what this function goes on to read.
* A REASSIGNMENT BETWEEN THE DEFAULT AND THE ``try``: ``data = {}`` … ``if
  isinstance(loaded, dict): data = loaded`` … ``if not data: try:``. The last
  ASSIGNMENT is not the empty one, and reading control flow to decide what a
  name holds is not what a structural rule does. One site, above.
* ``None`` AND OTHER SCALAR DEFAULTS are out of scope: code receiving ``None``
  must test it before reading a key, whereas ``{}`` answers every ``.get``
  with a default nobody chose. This is what let the distance bound go — the
  one legitimate site this rule ever reached, at 45 lines, was a
  ``prior = None`` read, now out of bounds by DEFINITION, not by a number.
* FIXTURE TREES. No directory is skipped, fixture trees included: firing on
  another gate's deliberate demonstration is a false alarm, but a skip list is
  worse. Fixtures for this shape belong in test source strings.
* PARSER BINDING. A config read is recognised by a structured-parser call, so
  ``configparser``, a hand-rolled parser, or ``read_text()`` plus string
  surgery is out of scope: recognising ``.json`` in a string literal would let
  prose move this verdict.
* NON-NAME HANDLER TARGETS — ATTRIBUTE, SUBSCRIPT AND TUPLE. ``self._cfg``,
  ``state["cfg"]`` and ``globals()["cfg"]`` are not plain names, so nothing
  sees such a site. A TUPLE target (``_cfg, _err = {}, None``) puts a matched
  site back out of reach: nothing reads through the unpacking, so requirement
  3 declines. On the real pre-fix source that rewrite takes rc 1 to rc 0.
* A DELIBERATE FAKE FIX. Requirement 3 asks whether the handler CONTAINS a
  ``raise`` or an emit, not whether it can run, so ``if False: raise ...``
  beside the default excuses it — rc 1 to rc 0 on the real pre-fix source.
  Deciding what a branch can reach is not what a structural rule does, a
  constant-folding case is itself respellable (``if _DEBUG:``, ``if 0:``), and
  unlike a size bound this is not an edit that passes for maintenance.
* EMPTY-VALUE VOCABULARY. A handler mention of the name is accounted only when
  it assigns the SAME literal empty container or the bare no-argument
  ``dict()`` / ``list()`` / ``tuple()`` / ``set()``. ``cfg = {}.copy()``,
  ``cfg = {**{}}``, ``cfg = json.loads("{}")``, ``cfg = cfg`` and
  ``cfg.clear()`` are the same silence spelled so this rule declines rather
  than guesses; each was ATTEMPTED against the real pre-fix source and each
  worked. Stated rather than chased: the ways to respell an empty dict have no
  end, and they differ in kind from what was deleted this round, which let the
  defect stay written EXACTLY as it is and pass for maintenance.
* SCALAR EXTRACTION. ``declared = (json.loads(...) or {}).get("tech_lef")``
  reads one key, inside the ``try``. Requirement 4 does not see it.
* KEY READS THAT DO NOT NAME THEIR KEY. ``cfg.get(_k)`` in a loop,
  ``_pick(cfg, "fill")`` and ``(cfg or {}).get("fill")`` are real reads of a
  real declaration and none counts, so at a site with exactly
  ``MIN_KEY_READS`` literal reads, respelling ONE buys green with the silent
  default still there. The alternative — crediting a read whose key cannot be
  named — reported a sha memo cache as "2 declared key(s): <line 18>, <line
  19>". The guarded defect mines FOURTEEN literal keys.
* UNUSUAL LOGGER NAMES. A channel bound outside ``logging`` / ``log`` /
  ``logger`` / ``LOG`` / ``warnings`` (or a ``.log`` / ``.logger`` receiver)
  is not recognised, so requirement 5 will not credit it.
* SIBLING HANDLERS. A ``raise`` in ANOTHER ``except`` clause of the SAME
  ``try`` is not contrast: everything inside the ``try`` is excluded from
  requirement 5.

COMMENTS AND STRINGS CANNOT MOVE THIS VERDICT
---------------------------------------------
Every predicate is evaluated on the parsed syntax tree: statement kinds, call
targets, assignment targets and literal emptiness. ``ast`` discards comments,
no rule inspects the CONTENT of a string literal, and with the distance bound
deleted no rule compares line numbers to decide anything. chip-AGNOSTIC: the
rule knows no vendor, foundry, technology, design or product — it is about the
shape of a failure branch.

USAGE
-----
    signoff_config_parse_failure_is_named_check.py [ROOT ...] [--json OUT]

EXIT CODES
----------
    0 = PASS          every config read names its own parse failure
    1 = FAIL          at least one silent-default config read (listed)
    2 = CANNOT-CHECK  a root does not exist, a root held no Python, or a file
                      could not be read/parsed. Never a PASS, in the message
                      OR in --json: "I could not look" is not "I looked and it
                      is clean".
"""
from __future__ import annotations

# --- sibling-import path (vibe-ic#2104) ------------------------------------
import os as _os                                                    # noqa: E402
import sys as _sys                                                  # noqa: E402

if _os.path.dirname(_os.path.abspath(__file__)) not in _sys.path:
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
# ---------------------------------------------------------------------------

import argparse
import ast
import json
import sys
import warnings
from collections import deque
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

NAME = "signoff_config_parse_failure_is_named_check"

RC_PASS, RC_FAIL, RC_CANNOT_CHECK = 0, 1, 2

#: Structured-config parsers. A call to one of these is what makes a `try`
#: body a CONFIG READ rather than an arbitrary guarded block.
_PARSE_CALLS = {
    ("json", "load"), ("json", "loads"),
    ("yaml", "load"), ("yaml", "safe_load"), ("yaml", "full_load"),
    ("toml", "load"), ("toml", "loads"),
    ("tomllib", "load"), ("tomllib", "loads"),
}

#: Emitting attribute calls that count as "this code spoke up" — but only on a
#: LOGGING receiver. `result.error(...)` / `report.warn(...)` are domain
#: methods on a result object, not a channel anybody reads.
_LOG_METHODS = {"warning", "warn", "error", "critical", "exception", "fatal"}
_LOG_RECEIVERS = {"logging", "logger", "log", "LOG", "LOGGER",
                  "_log", "_logger", "_LOG", "_LOGGER",
                  "warnings", "_warnings"}
_LOG_RECEIVER_ATTRS = {"log", "logger", "_log", "_logger"}

#: In-place reads: `cfg.update(json.loads(...))` fills `cfg` as surely as
#: `cfg = json.loads(...)` does.
_INPLACE_FILLS = {"update", "setdefault", "extend"}

#: Not a flag: a gate the call site can narrow is a gate the call site can
#: disarm. There is no companion size bound; see NOTHING HERE EXEMPTS A SITE.
MIN_KEY_READS = 2


@dataclass
class Finding:
    file: str
    line: int
    function: str
    name: str
    default: str
    absent_default_line: int
    key_reads: List[str]
    contrast_line: int
    contrast_kind: str

    def render(self) -> str:
        keys = ", ".join(self.key_reads[:6])
        more = "" if len(self.key_reads) <= 6 else f", +{len(self.key_reads)-6} more"
        return (
            f"{self.file}:{self.line}: in {self.function}() the parse-failure "
            f"branch leaves {self.name} at {self.default} and says nothing.\n"
            f"      {self.name} already means \"nothing declared\" at "
            f"{self.file}:{self.absent_default_line}, so an unparseable file "
            f"is recorded as an absent one.\n"
            f"      {len(self.key_reads)} declared key(s) then take their "
            f"defaults unannounced: {keys}{more}.\n"
            f"      This function already {self.contrast_kind} at "
            f"{self.file}:{self.contrast_line} — name this failure the same "
            f"way (raise, or say it on stderr) instead of defaulting."
        )


# ---------------------------------------------------------------------------
# structural predicates — every one of them reads syntax, never text
# ---------------------------------------------------------------------------
def _is_parse_call(call: ast.Call) -> bool:
    f = call.func
    return (isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name)
            and (f.value.id, f.attr) in _PARSE_CALLS)


def _empty_value(value: Optional[ast.AST]) -> Optional[str]:
    """Canonical spelling of an EMPTY default, or None if not one."""
    if isinstance(value, ast.Dict) and not value.keys:
        return "{}"
    if isinstance(value, ast.List) and not value.elts:
        return "[]"
    if isinstance(value, ast.Tuple) and not value.elts:
        return "()"
    if (isinstance(value, ast.Call) and isinstance(value.func, ast.Name)
            and not value.args and not value.keywords):
        return {"dict": "{}", "list": "[]", "tuple": "()",
                "set": "set()"}.get(value.func.id)
    return None


def _name_assigns(stmt: ast.stmt) -> List[Tuple[ast.Name, ast.AST]]:
    """(target node, value) for plain-Name assignment targets in one stmt."""
    out: List[Tuple[ast.Name, ast.AST]] = []
    if isinstance(stmt, ast.Assign):
        for tgt in stmt.targets:
            if isinstance(tgt, ast.Name):
                out.append((tgt, stmt.value))
    elif (isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name)
            and stmt.value is not None):
        out.append((stmt.target, stmt.value))
    return out


def _own_nodes(fn: ast.AST) -> List[ast.AST]:
    """Every node belonging to this function, excluding nested definitions.

    So "the same function" means one thing across requirements 2, 4 and 5.
    """
    out: List[ast.AST] = []
    queue = deque(getattr(fn, "body", []))
    while queue:
        node = queue.popleft()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef, ast.Lambda)):
            continue
        out.append(node)
        queue.extend(ast.iter_child_nodes(node))
    return out


def _handler_is_silent(handler: ast.ExceptHandler) -> bool:
    """The handler neither refuses nor speaks: no ``raise``, no emit.

    Half of requirement 3. "No CALL at all" was the earlier reading and it was
    a door: one ``_failures.append(path)`` tells nobody anything.
    """
    if not handler.body:
        return False
    for stmt in handler.body:
        for node in ast.walk(stmt):
            if isinstance(node, ast.Raise):
                return False
            if isinstance(node, ast.Call) and _is_emit_call(node):
                return False
    return True


def _read_targets(node: ast.Try) -> Set[str]:
    """Names the ``try`` body fills — by assignment or by in-place fill."""
    names: Set[str] = set()
    for stmt in node.body:
        for sub in ast.walk(stmt):
            if isinstance(sub, (ast.Assign, ast.AnnAssign)):
                for tgt, _ in _name_assigns(sub):
                    names.add(tgt.id)
            elif (isinstance(sub, ast.Call)
                  and isinstance(sub.func, ast.Attribute)
                  and sub.func.attr in _INPLACE_FILLS
                  and isinstance(sub.func.value, ast.Name)):
                names.add(sub.func.value.id)
    return names


def _prior_empty_default(stmts: Sequence[ast.stmt], node: ast.Try,
                         name: str) -> Optional[Tuple[int, str]]:
    """Requirement 2: the EMPTY value this name holds entering the ``try``.

    The LAST assignment before the ``try`` is the one still standing, and it
    has to be empty. A bare ``return {}`` elsewhere carries no name and is no
    evidence about this one; a real value means a failed parse does not land
    on "absent", which is a different program.
    """
    best: Optional[Tuple[int, Optional[str]]] = None
    for stmt in stmts:
        if stmt.lineno >= node.lineno:
            continue
        for tgt, val in _name_assigns(stmt):
            if tgt.id == name and (best is None or stmt.lineno > best[0]):
                best = (stmt.lineno, _empty_value(val))
    if best is None or best[1] is None:
        return None
    return best[0], best[1]


def _leaves_name_empty(handler: ast.ExceptHandler, name: str,
                       spelled: str) -> bool:
    """The rest of requirement 3: ``name`` still holds that empty default.

    Re-assigning the same empty value, assigning some OTHER name, and ``pass``
    are ONE condition rather than three cases: requirement 2 has established
    what ``name`` holds when the parse raised and none of the three changes
    it. Any OTHER mention of the name — a rebind to a real value, an in-place
    fill, a ``del`` — and any ``return`` (control leaves, so what the name
    holds is not what this function goes on to read) are a different program,
    and this rule declines rather than guesses.
    """
    same = {id(tgt) for stmt in handler.body for tgt, val in _name_assigns(stmt)
            if _empty_value(val) == spelled}
    for stmt in handler.body:
        for sub in ast.walk(stmt):
            if isinstance(sub, ast.Return):
                return False
            if (isinstance(sub, ast.Name) and sub.id == name
                    and id(sub) not in same):
                return False
    return True


def _mined_keys(nodes: Sequence[ast.AST], name: str,
                exclude: Set[int]) -> List[str]:
    """Distinct LITERAL keys READ out of ``name`` (``.get("k")`` / ``["k"]``).

    Requirement 4. Two things this will not do, each because doing it produced
    a wrong verdict on correct code: a NON-LITERAL key is not a key
    (``memo.get(rel)`` names no declaration, and "2 declared key(s):
    <line 18>, <line 19>" is a count dressed as a name), and a WRITE is not a
    consultation (``doc["program"] = ...`` stores; only ``ast.Load``
    subscripts count).
    """
    keys: List[str] = []

    def _record(key: str) -> None:
        if key not in keys:
            keys.append(key)

    for sub in nodes:
        if id(sub) in exclude:
            continue
        if (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute)
                and sub.func.attr == "get"
                and isinstance(sub.func.value, ast.Name)
                and sub.func.value.id == name and sub.args
                and isinstance(sub.args[0], ast.Constant)):
            _record(repr(sub.args[0].value))
        elif (isinstance(sub, ast.Subscript) and isinstance(sub.value, ast.Name)
              and sub.value.id == name
              and isinstance(sub.slice, ast.Constant)
              and isinstance(sub.ctx, ast.Load)):
            _record(repr(sub.slice.value))
    return keys


def _is_stderr_print(call: ast.Call) -> bool:
    """``print(..., file=sys.stderr)`` — and nothing else.

    ``file=<any name>`` is NOT this: a report handle carrying progress lines
    is not a warning channel.
    """
    if not (isinstance(call.func, ast.Name) and call.func.id == "print"):
        return False
    for kw in call.keywords:
        if kw.arg == "file":
            v = kw.value
            if isinstance(v, ast.Attribute) and v.attr == "stderr":
                return True
            return isinstance(v, ast.Name) and v.id == "stderr"
    return False


def _is_log_receiver(value: ast.AST) -> bool:
    if isinstance(value, ast.Name):
        return value.id in _LOG_RECEIVERS
    if isinstance(value, ast.Attribute):
        return value.attr in _LOG_RECEIVER_ATTRS
    return False


def _is_emit_call(call: ast.Call) -> bool:
    if _is_stderr_print(call):
        return True
    f = call.func
    if isinstance(f, ast.Attribute):
        if f.attr in _LOG_METHODS and _is_log_receiver(f.value):
            return True
        if f.attr == "write":
            v = f.value
            if isinstance(v, ast.Attribute) and v.attr == "stderr":
                return True
            if isinstance(v, ast.Name) and v.id == "stderr":
                return True
    return False


def _contrast(nodes: Sequence[ast.AST], node: ast.Try,
              exclude: Set[int]) -> Optional[Tuple[int, str]]:
    """Requirement 5: a raise or an emit in this function, outside this try.

    No distance bound — a line window is closed by inserting a COMMENT.
    Distance only picks WHICH contrast the message names when there are
    several; it never decides whether there is one.
    """
    best: Optional[Tuple[int, str]] = None
    for sub in nodes:
        if id(sub) in exclude:
            continue
        kind = ""
        if isinstance(sub, ast.Raise):
            kind = "refuses outright"
        elif isinstance(sub, ast.Call) and _is_emit_call(sub):
            kind = "says its problems out loud"
        if not kind:
            continue
        line = getattr(sub, "lineno", None)
        if line is None:
            continue
        if best is None or abs(line - node.lineno) < abs(best[0] - node.lineno):
            best = (line, kind)
    return best


# ---------------------------------------------------------------------------
# file / tree scan
# ---------------------------------------------------------------------------
def scan_source(text: str, display: str, *,
                min_key_reads: int = MIN_KEY_READS) -> List[Finding]:
    """Findings for one module's source. Raises SyntaxError on bad source."""
    # An invalid escape sequence in a scanned module emits a SyntaxWarning at
    # parse time: a fact about the file being READ, not a verdict, and noise
    # next to the one line a reader is meant to act on. SyntaxError still
    # propagates: unparseable is CANNOT-CHECK, never PASS.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        tree = ast.parse(text)

    findings: List[Finding] = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        own = _own_nodes(fn)
        stmts = [n for n in own if isinstance(n, ast.stmt)]
        for node in [s for s in stmts if isinstance(s, ast.Try)]:
            if not any(isinstance(c, ast.Call) and _is_parse_call(c)
                       for st in node.body for c in ast.walk(st)):
                continue
            targets = _read_targets(node)
            inside = {id(n) for n in ast.walk(node)}
            for handler in node.handlers:
                if not _handler_is_silent(handler):
                    continue
                found = _judge_handler(
                    handler, node, fn, own, stmts, targets, inside, display,
                    min_key_reads=min_key_reads)
                if found is not None:
                    findings.append(found)
                    break
    return findings


def _judge_handler(handler, node, fn, own, stmts, targets, inside, display, *,
                   min_key_reads: int) -> Optional[Finding]:
    """Requirement 2, the rest of 3, and 4 and 5 for one silent handler."""
    for name in sorted(targets):
        prior = _prior_empty_default(stmts, node, name)
        if prior is None:
            continue
        absent_line, spelled = prior
        if not _leaves_name_empty(handler, name, spelled):
            continue
        keys = _mined_keys(own, name, inside)
        if len(keys) < min_key_reads:
            continue
        near = _contrast(own, node, inside)
        if near is None:
            continue
        return Finding(
            file=display, line=handler.lineno, function=fn.name, name=name,
            default=spelled, absent_default_line=absent_line, key_reads=keys,
            contrast_line=near[0], contrast_kind=near[1])
    return None


def iter_python_files(root: Path):
    """Every ``*.py`` under ``root``. There is no skip list; see THE CENSUS."""
    return sorted(root.rglob("*.py"))


def scan_roots(roots: Sequence[Path], **kw) -> Tuple[List[Finding], Dict[str, Any]]:
    """Read and judge every Python file under every root."""
    unreadable: List[str] = []
    per_root: List[Dict[str, Any]] = []
    findings: List[Finding] = []
    scanned = 0

    for root in roots:
        targets = [root] if root.is_file() else iter_python_files(root)
        count = 0
        for path in targets:
            try:
                text = path.read_text(encoding="utf-8", errors="strict")
            except (OSError, UnicodeDecodeError) as exc:
                unreadable.append(f"{path}: {exc.__class__.__name__}: {exc}")
                continue
            count += 1
            try:
                findings.extend(scan_source(text, str(path), **kw))
            except SyntaxError as exc:
                unreadable.append(f"{path}:{exc.lineno}: SyntaxError: {exc.msg}")
                continue
            scanned += 1
        per_root.append({"root": str(root), "python_files": count})

    empty_roots = [r["root"] for r in per_root if r["python_files"] == 0]
    return findings, {"files_scanned": scanned, "unreadable": unreadable,
                      "roots": [str(r) for r in roots],
                      "per_root": per_root, "empty_roots": empty_roots}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("roots", nargs="*", default=["."],
                    help="directories (or single .py files) to scan")
    ap.add_argument("--json", help="write a JSON report to this path")
    args = ap.parse_args(argv if argv is not None else sys.argv[1:])

    roots = [Path(r) for r in (args.roots or ["."])]
    missing = [str(r) for r in roots if not r.exists()]
    if missing:
        _write_json(args.json, "CANNOT_CHECK", [], {
            "files_scanned": 0, "unreadable": [], "empty_roots": [],
            "per_root": [], "roots": [str(r) for r in roots]},
            missing=missing)
        print(f"[REFUSE] {NAME}: no such path: {', '.join(missing)} — nothing "
              f"was scanned, so this run makes no claim about any tree.",
              file=sys.stderr)
        return RC_CANNOT_CHECK

    findings, stats = scan_roots(roots)

    scanned = stats["files_scanned"]
    where = ", ".join(stats["roots"])

    # The verdict is decided BEFORE it is written anywhere, so the machine
    # answer and the human answer cannot disagree. A CANNOT-CHECK that reports
    # itself as "PASS" in --json is the very defect this batch is about.
    if findings:
        verdict, rc = "FAIL", RC_FAIL
    elif stats["unreadable"] or stats["empty_roots"] or scanned == 0:
        verdict, rc = "CANNOT_CHECK", RC_CANNOT_CHECK
    else:
        verdict, rc = "PASS", RC_PASS

    if not _write_json(args.json, verdict, findings, stats):
        return RC_CANNOT_CHECK

    if rc == RC_FAIL:
        print(f"[FAIL] {NAME}: {len(findings)} config read(s) answer a parse "
              f"failure with an unannounced empty default "
              f"({scanned} file(s) scanned under {where})")
        for f in findings:
            print(f"  {f.render()}")
        return RC_FAIL

    if rc == RC_CANNOT_CHECK:
        if stats["unreadable"]:
            print(f"[REFUSE] {NAME}: {len(stats['unreadable'])} file(s) could "
                  f"not be read or parsed, so they were never judged "
                  f"({scanned} file(s) scanned under {where})", file=sys.stderr)
            for u in stats["unreadable"][:20]:
                print(f"  {u}", file=sys.stderr)
        else:
            blank = ", ".join(stats["empty_roots"]) or where
            print(f"[REFUSE] {NAME}: 0 Python file(s) under {blank} — a clean "
                  f"result over an empty scan is not a clean result; check the "
                  f"root argument.", file=sys.stderr)
        return RC_CANNOT_CHECK

    print(f"[PASS] {NAME}: {scanned} file(s) scanned under {where}; every "
          f"config read either names its parse failure or does not hide one")
    return RC_PASS


def _write_json(path: Optional[str], verdict: str, findings: List[Finding],
                stats: Dict[str, Any], missing: Optional[List[str]] = None
                ) -> bool:
    """Write the machine answer. False when it could not be written."""
    if not path:
        return True
    try:
        Path(path).write_text(json.dumps({
            "checker": NAME,
            "verdict": verdict,
            "count": len(findings),
            "files_scanned": stats.get("files_scanned", 0),
            "unreadable": stats.get("unreadable", []),
            "empty_roots": stats.get("empty_roots", []),
            "missing_roots": missing or [],
            "roots": stats.get("roots", []),
            "findings": [asdict(f) for f in findings],
        }, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        print(f"[REFUSE] {NAME}: cannot write --json: {exc}", file=sys.stderr)
        return False
    return True


if __name__ == "__main__":
    raise SystemExit(main())
