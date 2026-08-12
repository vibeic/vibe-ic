#!/usr/bin/env python3
"""A DIRECTION argued in prose and left unpinned by every test. vibe-ic.

THIS GATE BLOCKS (rc=1).

WHY IT EXISTS
-------------
A call site writes a literal into a parameter that selects between named,
mutually exclusive alternatives -- `on_conflict="richer"` rather than
`"sparser"`, `mode="strict"` rather than `"lenient"`. Somebody argued for that
direction: the callee's own documentation for the parameter says which way to
go and why, or a comment beside the call does.

MEASURED, on a real review: flipping ONE such word at ONE call site --
`on_conflict="richer"` to `"sparser"` -- left all 25 tests in the suite that
shipped with it PASSING. The suite even contained a test named for the policy.
That test drove the HELPER and asserted it behaves correctly under BOTH values,
which is a property of the helper. Nothing asserted WHICH value the call site
hands it. The prose said the two directions are not interchangeable -- one keeps
a declared blockage, the other drops it and lets supply metal land on blocked
metal -- and the executable record said they are.

The asymmetry is the whole point. A test that exercises the helper under both
values gets GREENER the more thorough it is, and stays green under the flip. A
test at the CALL SITE is the only kind that dies when the direction changes.

WHAT IT MEASURES
----------------
An ARGUED DIRECTION call site is a call that satisfies all three:

  D1  CHOSE TO SPEAK.  The callee gives the parameter a DEFAULT, so the call
      site did not have to mention it at all. Writing it anyway -- even writing
      the default back -- is a recorded decision. This clause is what separates
      a decision from an ordinary parameter: `report_path(p, "final_summary.md")`
      names WHICH report it wants and has no choice but to say so; that is an
      argument, not a decision, and it is excluded here. Required parameters are
      out of scope by construction.

      D1 IS THE EXPENSIVE CLAUSE AND HERE IS WHAT IT COST, measured on this
      corpus: without it, 144 parameters and 50 production call sites, 9 of
      which D3 calls argued. With it, 17 and 2, and 1 argued. The 48 sites it
      removes are the difference between a finding and a wall, and 8 of the 9
      it removes from the argued list are one function, `_p0_gate_record`,
      whose `verdict=` is the verdict being RECORDED rather than a direction
      being chosen.

      It is not free, and pretending otherwise would be the same dishonesty
      this gate is about. `_p0_gate_record(verdict="SKIP")` where the branch
      could have recorded "FAIL" is, to a human reader, exactly the kind of
      direction this repo cares about -- and D1 drops it because the call site
      had no choice but to say something. The program cannot tell a value
      DERIVED from the branch it sits in ("this gate was not invocable, so:
      NOT_INVOCABLE") from a value CHOSEN against the same inputs ("both
      directions would run; I picked this one") -- both are a literal in an
      argument position. `--include-required` prints the wider population so
      that trade is inspectable instead of buried.

  D2  NAMED ALTERNATIVES.  The callee constrains the parameter to a closed set
      of >= 2 string alternatives, and the literal is one of them. Evidence is
      any of: a `Literal[...]` annotation; a membership guard against an inline
      collection or a module-level constant collection; equality branching
      against >= 2 distinct string literals; indexing a module-level dispatch
      table. All four are the callee stating, in code, that these values are
      alternatives to each other.

  D3  SOMEBODY WROTE DOWN THE ROAD NOT TAKEN.  Either the callee's docstring
      ENTRY for that parameter names >= 2 members of the set, or a comment
      inside the calling function names the parameter together with a member of
      the set OTHER than the one passed. Nobody writes down the alternative they
      rejected unless they had to choose.

PINNED, and it is verified by EXECUTION, not by reading
-------------------------------------------------------
A site is PINNED when flipping its literal to another member of the set makes at
least one test FAIL. That is exactly the reviewer's move, run as a program.
There is no static approximation here on purpose: "a test that mentions the
value" is satisfied by a test that asserts nothing, and a checker that accepted
it would hand out the same false clean bill of health this gate exists to end.

WHAT THIS GATE CANNOT DECIDE, STATED PLAINLY
--------------------------------------------
It cannot see that somebody ARGUED. Argument happens in review threads and in
people's heads; the program sees a syntax tree, docstrings and comments. D3 is a
PROXY: it detects that the author wrote down an alternative they did not take.
The proxy fails in both directions and here is how:

  * A direction fought over for an hour and then committed with a bare
    `on_conflict="richer"` and no prose is INVISIBLE to this gate. Deleting your
    own comment removes the finding. That is a real hole and it is not closable
    from source alone -- so the gate reports its D1+D2 population too, as the
    denominator D3 selected from, and that number is the honest upper bound on
    what it could ever have looked at.
  * Prose that names two alternatives for a reason other than choosing between
    them -- a docstring listing every accepted value of an ordinary lookup
    parameter -- is a FALSE POSITIVE, and D1 is what keeps most of those out:
    a lookup parameter is usually required, not defaulted.

It also cannot decide, from source, which tests observe a given call site. It
derives a candidate set textually (below), which is a LOWER bound on coverage:
under-selection makes a site look UNPINNED, never PINNED. The error direction is
toward demanding more pinning, never toward a false clean.

Booleans are OUT OF SCOPE. `strict=True` is a two-valued decision by this
definition and demanding a test for every defaulted boolean keyword in the
corpus would bury the finding in noise. Named string alternatives are the shape
where somebody bothered to name the directions.

chip-AGNOSTIC, PDK-AGNOSTIC, vendor-AGNOSTIC: pure Python grammar. No design,
PDK, vendor, process or part literal appears in the logic or can affect it.

USAGE
-----
    policy_direction_pin_check.py [PROGRAMS_DIR] [--json OUT]
                                  [--verify-pins] [--max-test-files N]
                                  [--only SUBSTR] [--include-required]
                                  [--pytest-arg ARG]...

    Default (no --verify-pins) is the INVENTORY: it prints every argued
    direction site and the ratio, and exits 0. Inventory alone cannot say
    whether a site is pinned, and it does not pretend to.

    --verify-pins runs the mutation and BLOCKS:
      exit 0 = every argued direction site is pinned at its call site
      exit 1 = at least one is not
      exit 2 = could not be determined -- no corpus, no tests directory, or a
               site the gate ABSTAINED on. An abstention is deliberately NOT a
               pass: a gate that goes green by declining to look is the shape
               this one was written against.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

RC_OK = 0
RC_UNPINNED = 1
RC_UNDETERMINED = 2

# A site whose candidate test set is larger than this is ABSTAINed rather than
# guessed at: running it would cost more than the gate is worth, and calling it
# unpinned without running would be a claim the gate did not earn. 40 is the
# smallest round number that DECIDES every argued site in this corpus (the
# largest selection here is 32); a cap that abstained on the one site the sweep
# found would be a gate that goes green by declining to look.
DEFAULT_MAX_TEST_FILES = 40


# ---------------------------------------------------------------------------
# D2 -- the callee states that these values are alternatives to each other
# ---------------------------------------------------------------------------

def module_string_collections(tree: ast.Module) -> Dict[str, List[str]]:
    """Module-level ``NAME = (...)`` / ``[...]`` / ``{...}`` of >= 2 str.

    A dict literal contributes its KEYS, because ``TABLE[param]`` is dispatch
    over exactly those keys.
    """
    out: Dict[str, List[str]] = {}
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        value = node.value
        if value is None:
            continue
        if (isinstance(value, ast.Call) and isinstance(value.func, ast.Name)
                and value.func.id in ("frozenset", "set", "tuple", "list")
                and value.args):
            value = value.args[0]
        members: Optional[List[str]] = None
        if isinstance(value, (ast.Tuple, ast.List, ast.Set)):
            got = [e.value for e in value.elts
                   if isinstance(e, ast.Constant) and isinstance(e.value, str)]
            if value.elts and len(got) == len(value.elts):
                members = got
        elif isinstance(value, ast.Dict):
            got = [k.value for k in value.keys
                   if isinstance(k, ast.Constant) and isinstance(k.value, str)]
            if value.keys and len(got) == len(value.keys):
                members = got
        if members is None or len(set(members)) < 2:
            continue
        for t in targets:
            if isinstance(t, ast.Name):
                out[t.id] = sorted(set(members))
    return out


def closed_alternatives(fn: ast.AST, param: str, consts: Dict[str, List[str]],
                        annotation: Optional[ast.AST]) -> Tuple[List[str], str]:
    """The closed set the callee declares for ``param``, and the evidence kind.

    Returns ``([], "")`` when the callee does not treat the parameter as a set
    of named alternatives.
    """
    if annotation is not None and "Literal[" in ast.unparse(annotation):
        vals = [e.value for e in ast.walk(annotation)
                if isinstance(e, ast.Constant) and isinstance(e.value, str)]
        if len(set(vals)) >= 2:
            return sorted(set(vals)), "Literal"

    eq_literals: List[str] = []
    for node in ast.walk(fn):
        if isinstance(node, ast.Compare):
            if isinstance(node.left, ast.Name) and node.left.id == param:
                for op, cmp in zip(node.ops, node.comparators):
                    if isinstance(op, (ast.In, ast.NotIn)):
                        if isinstance(cmp, (ast.Tuple, ast.List, ast.Set)):
                            got = [e.value for e in cmp.elts
                                   if isinstance(e, ast.Constant)
                                   and isinstance(e.value, str)]
                            if cmp.elts and len(got) == len(cmp.elts) and len(set(got)) >= 2:
                                return sorted(set(got)), "membership-guard"
                        if isinstance(cmp, ast.Name) and cmp.id in consts:
                            return consts[cmp.id], "membership-guard:" + cmp.id
                    elif isinstance(op, (ast.Eq, ast.NotEq)):
                        if isinstance(cmp, ast.Constant) and isinstance(cmp.value, str):
                            eq_literals.append(cmp.value)
        if isinstance(node, ast.Subscript):
            sl = node.slice
            if isinstance(sl, ast.Name) and sl.id == param and isinstance(node.value, ast.Name):
                if node.value.id in consts:
                    return consts[node.value.id], "dispatch-table:" + node.value.id
    if len(set(eq_literals)) >= 2:
        return sorted(set(eq_literals)), "equality-branch"
    return [], ""


# ---------------------------------------------------------------------------
# D3 -- prose that names the road not taken
# ---------------------------------------------------------------------------

_WORD_CACHE: Dict[str, "re.Pattern[str]"] = {}


def _names(text: str, token: str) -> bool:
    """``token`` appears in ``text`` not glued to an identifier character.

    Values like ``"1'b0"`` or ``"met1"`` are matched by their whole text, so the
    boundary is only enforced where the value's own edge is an identifier char.
    """
    if not text or not token:
        return False
    pat = _WORD_CACHE.get(token)
    if pat is None:
        left = r"(?<![A-Za-z0-9_])" if re.match(r"[A-Za-z0-9_]", token) else ""
        right = r"(?![A-Za-z0-9_])" if re.search(r"[A-Za-z0-9_]$", token) else ""
        pat = re.compile(left + re.escape(token) + right)
        _WORD_CACHE[token] = pat
    return bool(pat.search(text))


_SECTION_UNDERLINE = re.compile(r"^\s*[-=~^]{3,}\s*$")


def param_doc_entry(doc: str, param: str) -> str:
    """The docstring text that documents ``param``, or "".

    Handles numpydoc (``param :`` then an indented body), Google (``param:`` or
    ``param (type):`` inside ``Args:``) and Sphinx (``:param param:``). Falls
    back to the blank-line-delimited paragraph(s) that name the parameter, which
    is what an unstructured docstring gives you.
    """
    if not doc:
        return ""
    lines = doc.splitlines()

    sphinx = re.compile(r"^\s*:param\s+" + re.escape(param) + r"\s*:")
    header = re.compile(r"^(\s*)" + re.escape(param) + r"\s*(\([^)]*\))?\s*:(.*)$")
    other_header = re.compile(r"^(\s*)([A-Za-z_][A-Za-z_0-9]*)\s*(\([^)]*\))?\s*:\s*$")

    for i, line in enumerate(lines):
        m = sphinx.match(line) or header.match(line)
        if not m:
            continue
        indent = len(line) - len(line.lstrip())
        body = [line]
        for j in range(i + 1, len(lines)):
            nxt = lines[j]
            if not nxt.strip():
                # numpydoc entries are not blank-separated; a blank line ends a
                # Google-style entry. Stop either way -- taking more would let a
                # neighbouring parameter's prose count as this one's.
                break
            nxt_indent = len(nxt) - len(nxt.lstrip())
            if nxt_indent <= indent:
                if other_header.match(nxt) or sphinx.match(nxt) or _SECTION_UNDERLINE.match(nxt):
                    break
                if nxt_indent < indent:
                    break
            body.append(nxt)
        return "\n".join(body)

    paras: List[str] = []
    cur: List[str] = []
    for line in lines:
        if line.strip():
            cur.append(line)
        else:
            if cur:
                paras.append("\n".join(cur))
            cur = []
    if cur:
        paras.append("\n".join(cur))
    return "\n".join(p for p in paras if _names(p, param))


def enclosing_function_comments(source_lines: Sequence[str], fn: Optional[ast.AST]) -> str:
    """Every full-line and trailing ``#`` comment inside ``fn`` (module if None).

    Comments are not in the AST, so this is textual by necessity. Restricting it
    to the calling function is what stops a comment 900 lines away from
    excusing a call site.
    """
    if fn is None:
        lo, hi = 1, len(source_lines)
    else:
        lo = getattr(fn, "lineno", 1)
        hi = getattr(fn, "end_lineno", None) or len(source_lines)
    out: List[str] = []
    for idx in range(lo - 1, min(hi, len(source_lines))):
        line = source_lines[idx]
        stripped = line.strip()
        if stripped.startswith("#"):
            out.append(stripped)
        elif "#" in line:
            # Trailing comment. Quotes are not parsed here; a '#' inside a
            # string would over-collect, which can only ADD prose and so can
            # only make the gate look at MORE sites, never fewer.
            out.append(line[line.index("#"):].strip())
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Inventory
# ---------------------------------------------------------------------------

class PolicyParam(Dict[str, Any]):
    pass


def _iter_python(root: Path) -> List[Path]:
    return sorted(p for p in root.rglob("*.py") if p.is_file())


def collect_policy_params(root: Path, require_default: bool = True
                          ) -> Tuple[List[Dict[str, Any]], Dict[str, List[Dict[str, Any]]], Dict[Path, str]]:
    """Every DEFAULTED, closed-set string parameter defined anywhere in root.

    ``require_default=False`` drops D1 and widens the population to required
    parameters as well. That is not the blocking population -- see the module
    docstring for what D1 buys and what it costs -- but it is inspectable,
    because a clause that removes 48 of 50 sites should be something a reviewer
    can look at rather than take on trust.
    """
    defs: List[Dict[str, Any]] = []
    by_name: Dict[str, List[Dict[str, Any]]] = {}
    sources: Dict[Path, str] = {}
    for path in _iter_python(root):
        try:
            src = path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(src)
        except (SyntaxError, ValueError, OSError):
            continue
        sources[path] = src
        consts = module_string_collections(tree)
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            a = fn.args
            positional = list(a.posonlyargs) + list(a.args)
            every = positional + list(a.kwonlyargs)
            defaults: Dict[str, ast.AST] = {}
            if a.defaults:
                for p, d in zip(positional[len(positional) - len(a.defaults):], a.defaults):
                    defaults[p.arg] = d
            for p, d in zip(a.kwonlyargs, a.kw_defaults):
                if d is not None:
                    defaults[p.arg] = d
            doc = ast.get_docstring(fn) or ""
            for p in every:
                default_node = defaults.get(p.arg)
                if require_default and p.arg not in defaults:
                    continue                                    # D1
                default_node = defaults.get(p.arg)
                alts, evidence = closed_alternatives(fn, p.arg, consts, p.annotation)
                if len(alts) < 2:
                    continue                                    # D2
                rec = {
                    "callee": fn.name,
                    "param": p.arg,
                    "alternatives": alts,
                    "evidence": evidence,
                    "default": (default_node.value
                                if isinstance(default_node, ast.Constant) else None),
                    "callee_file": str(path.relative_to(root)),
                    "callee_line": fn.lineno,
                    "param_doc": param_doc_entry(doc, p.arg),
                    "pos_index": positional.index(p) if p in positional else None,
                    "kwonly": p in a.kwonlyargs,
                }
                defs.append(rec)
                by_name.setdefault(fn.name, []).append(rec)
    return defs, by_name, sources


def collect_sites(root: Path, by_name: Dict[str, List[Dict[str, Any]]],
                  sources: Dict[Path, str]) -> List[Dict[str, Any]]:
    """Call sites that hand one of those parameters a string literal."""
    sites: List[Dict[str, Any]] = []
    for path in _iter_python(root):
        src = sources.get(path)
        if src is None:
            continue
        try:
            tree = ast.parse(src)
        except (SyntaxError, ValueError):
            continue
        lines = src.splitlines()
        parents: Dict[int, Optional[ast.AST]] = {}
        for fn in ast.walk(tree):
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for node in ast.walk(fn):
                    if isinstance(node, ast.Call) and id(node) not in parents:
                        parents[id(node)] = fn
        rel = str(path.relative_to(root))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Attribute):
                name = node.func.attr
            elif isinstance(node.func, ast.Name):
                name = node.func.id
            else:
                continue
            for rec in by_name.get(name, []):
                hit = _literal_for(node, rec)
                if hit is None:
                    continue
                value, how, arg_line, arg_col = hit
                enclosing = parents.get(id(node))
                comments = enclosing_function_comments(lines, enclosing)
                others = [a for a in rec["alternatives"] if a != value]
                doc_named = [a for a in rec["alternatives"] if _names(rec["param_doc"], a)]
                doc_argued = len(doc_named) >= 2
                comment_argued = bool(
                    _names(comments, rec["param"])
                    and any(_names(comments, a) for a in others))
                sites.append({
                    "file": rel,
                    "line": node.lineno,
                    "arg_line": arg_line,
                    "arg_col": arg_col,
                    "how": how,
                    "callee": rec["callee"],
                    "callee_file": rec["callee_file"],
                    "param": rec["param"],
                    "value": value,
                    "alternatives": rec["alternatives"],
                    "evidence": rec["evidence"],
                    "in_tests": rel.startswith("tests" + os.sep) or rel.startswith("tests/"),
                    "argued_by_doc": doc_argued,
                    "argued_by_comment": comment_argued,
                    "argued": doc_argued or comment_argued,
                })
    sites.sort(key=lambda s: (s["file"], s["line"], s["param"]))
    return sites


def _literal_for(node: ast.Call, rec: Dict[str, Any]):
    for kw in node.keywords:
        if kw.arg == rec["param"] and isinstance(kw.value, ast.Constant) \
                and isinstance(kw.value.value, str) and kw.value.value in rec["alternatives"]:
            return kw.value.value, "keyword", kw.value.lineno, kw.value.col_offset
    if rec["pos_index"] is None or rec["kwonly"]:
        return None
    # A method definition counts `self`; the attribute call site does not pass
    # it. Both offsets are tried and the literal must still be in the set, so a
    # wrong guess cannot invent a site out of an unrelated argument.
    for shift in (0, 1):
        j = rec["pos_index"] - shift
        if 0 <= j < len(node.args):
            arg = node.args[j]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str) \
                    and arg.value in rec["alternatives"]:
                return arg.value, "positional", arg.lineno, arg.col_offset
    return None


# ---------------------------------------------------------------------------
# Pin verification -- run the flip
# ---------------------------------------------------------------------------

def select_tests(site: Dict[str, Any], tests_dir: Path) -> List[Path]:
    """Test files that plausibly observe this call site.

    A LOWER bound, textually derived: files naming the call site's module AND
    naming either the parameter or the callee. Under-selection can only make a
    site look UNPINNED. There is no selection that makes an unpinned site look
    pinned, which is the direction that matters.

    Files that also name the LITERAL are returned first. That is an ordering
    heuristic and nothing else -- it changes how fast a kill is found, never
    whether one is found, because every selected file is run until one fails.
    """
    stem = Path(site["file"]).stem
    out: List[Tuple[int, str, Path]] = []
    for p in sorted(tests_dir.glob("test_*.py")):
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if not _names(text, stem):
            continue
        if _names(text, site["param"]) or _names(text, site["callee"]):
            out.append((0 if _names(text, site["value"]) else 1, p.name, p))
    out.sort()
    return [p for _, _, p in out]


def _literal_span(src: str, arg_line: int, arg_col: int):
    """``(lines, idx, start_body, end_body)`` for the literal at that position.

    Factored out of ``flip_source`` so that the WRITE path and the
    read-HEAD path below cannot drift into two slightly different ideas of
    where the literal is. Raises ``ValueError`` with a reason, never guesses.
    """
    lines = src.splitlines(keepends=True)
    idx = arg_line - 1
    if idx < 0 or idx >= len(lines):
        raise ValueError("argument line out of range")
    line = lines[idx]
    rest = line[arg_col:]
    m = re.match(r"""(?P<p>[rbuRBU]{0,2})(?P<q>'''|\"\"\"|'|")""", rest)
    if not m:
        raise ValueError("no string literal at the recorded column")
    quote = m.group("q")
    start_body = arg_col + m.end()
    end_body = line.find(quote, start_body)
    if end_body < 0:
        raise ValueError("string literal is not closed on its own line")
    return lines, idx, start_body, end_body


def flip_source(src: str, site: Dict[str, Any], new_value: str) -> str:
    """Replace exactly the literal at (arg_line, arg_col) with ``new_value``."""
    lines, idx, start_body, end_body = _literal_span(
        src, site["arg_line"], site["arg_col"])
    line = lines[idx]
    if line[start_body:end_body] != site["value"]:
        raise ValueError("literal at the recorded column is not the recorded value")
    lines[idx] = line[:start_body] + new_value + line[end_body:]
    return "".join(lines)


_FAILED_LINE = re.compile(r"^(?:FAILED|ERROR)\s+(\S+?)(?:::|\s|$)")


def failing_files(output: str) -> List[str]:
    """The test files pytest named as FAILED/ERROR in a short-summary run."""
    out: List[str] = []
    for line in output.splitlines():
        m = _FAILED_LINE.match(line.strip())
        if m and m.group(1) not in out:
            out.append(m.group(1))
    return out


# ---------------------------------------------------------------------------
# The mutation is written into the SHIPPED SOURCE, so it must survive the
# process dying (vibe-ic#1025 follow-up, #1029 family)
# ---------------------------------------------------------------------------
# `verify_pin` flips a literal in the real file and restores it in a `finally`.
# A `finally` does not run on SIGTERM, and SIGTERM is not hypothetical here:
# `gatekeeper_review._run_hygiene` invokes the hygiene script through
# `subprocess.run(..., timeout=...)`, and on `TimeoutExpired` the child is
# killed. This gate needs ~10 minutes on this corpus, so it is the gate most
# likely to be inside its own mutation window when that happens.
#
# MEASURED on a clean detached origin/main worktree: a mutation is on disk 23 s
# after start, and one SIGTERM there (child rc 143) leaves
#
#     M programs/atpg_untestable_fault_classify.py
#     -        on_conflict="richer",
#     +        on_conflict="sparser",
#
# in the shipped tree. Separately, a run killed at 550 s left
# `phase3_one_shot_runner.py` with its PDK default rewritten
# `sky130A` -> `nangate45`.
#
# THE REASON THIS IS WORSE THAN AN ORDINARY DIRTY FILE: the damage is
# SELF-CONCEALING. The next run RE-DERIVES the site from whatever the source
# now says, so it reads `nangate45` as the argued value, flips it, and reports
# a perfectly self-consistent verdict over a corrupted tree. Two consecutive
# runs agreed byte-for-byte on exactly that. Nothing in the output is wrong;
# the subject is.
#
# Two mechanisms, because they cover different deaths:
#   * SIGTERM/SIGINT -> handlers restore and re-raise, so the ordinary kill
#     (and `timeout`, and Ctrl-C) leaves the tree clean;
#   * SIGKILL / power loss -> a JOURNAL written OUTSIDE the tree BEFORE the
#     mutation, so the NEXT run finds it, repairs the file, and SAYS SO. A
#     journal cannot prevent the damage; what it removes is the concealment.
_INFLIGHT: Dict[str, Any] = {}


def journal_for(root: Path) -> Path:
    """Journal path for `root`, outside the tree and keyed to it.

    Outside, because a gate that journals INTO the tree it audits is the very
    thing the corpus-write guard exists to catch. Keyed, so two worktrees of
    this repo cannot repair each other's files.
    """
    key = hashlib.sha256(str(root.resolve()).encode("utf-8")).hexdigest()[:16]
    return Path(tempfile.gettempdir()) / f"policy_pin_inflight-{key}.json"


def _arm(journal: Path, target: Path, original: str, mutated: str) -> None:
    """Record the pending mutation BEFORE it reaches disk."""
    journal.write_text(json.dumps({
        "file": str(target), "original": original, "mutated": mutated}),
        encoding="utf-8")
    _INFLIGHT.update({"file": target, "original": original,
                      "journal": journal})


def _disarm(journal: Path) -> None:
    _INFLIGHT.clear()
    try:
        journal.unlink()
    except OSError:
        pass


def _restore_inflight() -> None:
    """Put the file back. Safe to call twice; never raises."""
    tgt, orig = _INFLIGHT.get("file"), _INFLIGHT.get("original")
    if tgt is not None and orig is not None:
        try:
            Path(tgt).write_text(orig, encoding="utf-8")
        except OSError:
            pass
    jrn = _INFLIGHT.get("journal")
    if jrn is not None:
        try:
            Path(jrn).unlink()
        except OSError:
            pass
    _INFLIGHT.clear()


def install_signal_restore() -> None:
    """Restore on the deaths a `finally` does not see, then die as asked."""
    def _handler(signum, _frame):
        _restore_inflight()
        signal.signal(signum, signal.SIG_DFL)
        os.kill(os.getpid(), signum)
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        try:
            signal.signal(sig, _handler)
        except (ValueError, OSError, AttributeError):
            # Not the main thread, or the platform lacks it. The journal below
            # is the backstop; it is not conditional on this working.
            pass


def recover_journal(journal: Path) -> Tuple[int, List[str]]:
    """Repair a file a previous run died on. Returns (rc, lines to print).

    rc 0  nothing to repair, or repaired
    rc 2  a journal exists and the file matches NEITHER what we wrote NOR what
          we would restore — someone has edited it since. Refused rather than
          clobbered: this function's job is to undo THIS gate's write, and it
          cannot prove that is all it would be undoing.
    """
    if not journal.is_file():
        return RC_OK, []
    try:
        rec = json.loads(journal.read_text(encoding="utf-8"))
        target = Path(rec["file"])
        original, mutated = rec["original"], rec["mutated"]
    except (OSError, ValueError, KeyError) as exc:
        return RC_UNDETERMINED, [
            f"[UNDETERMINED] policy_direction_pin_check: unreadable in-flight "
            f"journal {journal}: {exc}. A previous run died mid-mutation and "
            f"this one cannot tell what it left behind."]
    if not target.is_file():
        journal.unlink()
        return RC_OK, []
    now = target.read_text(encoding="utf-8")
    if now == original:
        journal.unlink()
        return RC_OK, []
    if now != mutated:
        return RC_UNDETERMINED, [
            f"[UNDETERMINED] policy_direction_pin_check: {target} was left "
            f"MUTATED by a previous run of this gate, and has been edited "
            f"since. Refusing to overwrite it — restore it by hand, then "
            f"delete {journal}."]
    target.write_text(original, encoding="utf-8")
    journal.unlink()
    return RC_OK, [
        f"[REPAIRED] policy_direction_pin_check: a previous run died inside "
        f"its mutation window and left {target} rewritten. Restored. Left "
        f"alone, the next sweep would have re-derived the argued value FROM "
        f"THE MUTATION and reported a consistent verdict over a corrupt tree."]


# --------------------------------------------------------------------------
# THE LEFTOVER THIS GATE CANNOT REPAIR, AND MUST THEREFORE REFUSE (#1089)
# --------------------------------------------------------------------------
# The journal above repairs a mutation whose run died while the journal was on
# disk. That is the crash this gate causes. It is not the only way its own
# mutant ends up in a tree:
#
#   * a leftover from a run that PRE-DATES the journal — every checkout carrying
#     one today, which is the population #1089 was filed about;
#   * `/tmp` cleared by a reboot or a tmp reaper while the working tree survives;
#   * the journal is keyed by `sha256(root.resolve())`, so MOVING or renaming a
#     worktree orphans it while the leftover stays exactly where it was.
#
# In every one of those the file is mutated and no journal exists, and
# `recover_journal` returns `RC_OK, []` — "nothing to repair" — which is true
# and useless. The sweep then re-derives the argued value FROM the leftover,
# flips *that*, watches the tests pass, and reports the site UNPINNED.
#
# MEASURED 2026-08-12 against the FIXED tool on `4b22e36e` + #1090, journal
# confirmed absent, one site (`--only matrix_mutation_ledger`):
#
#   clean         md5 f572930b…   [PINNED]   mode='witness'   rc 0
#   leftover      md5 28b755fe…   [UNPINNED] mode='all'       rc 1
#
# Note the second line reports `mode='all'` — the gate is naming the leftover as
# the authored value. `UNPINNED` reads as "this argued direction is unprotected,
# go write a test", and the direction is fine; the tree is dirty.
#
# WHY REFUSE RATHER THAN REPAIR. Without a journal this gate cannot prove the
# difference is its own — an author editing that literal produces byte-identical
# evidence — and `recover_journal` already draws exactly this line for the case
# it CAN see. So the residue is converted from a false finding into a named
# refusal, which is what `run` at `repo_hygiene_gates.sh:964` should block on.
#
# WHY THE SIGNATURE IS NARROW. Refusing on "the file differs from HEAD" would
# refuse on every in-flight edit anywhere in a 2000-line module and make the
# gate permanently red for anyone mid-change — the failure mode
# `run_tolerating_uncheckable` exists to avoid. It refuses only when the
# difference is AT THE ARGUED LITERAL and HEAD's value is one of the closed
# alternatives this gate itself flips between. That is this gate's own
# fingerprint and nothing else's.

#: Sites whose HEAD copy could not be read, and why. Reported once, because
#: "I could not look" must never reach a reader as "I looked and it matched".
_HEAD_BLIND: List[str] = []


def _git_show_head(repo: Path, rel: str) -> str:
    p = subprocess.run(["git", "-C", str(repo), "show", f"HEAD:{rel}"],
                       capture_output=True, text=True, timeout=30)
    if p.returncode != 0:
        raise ValueError((p.stderr or "").strip().splitlines()[-1:][0]
                         if (p.stderr or "").strip() else "git show failed")
    return p.stdout


def leftover_signature(root: Path, site: Dict[str, Any]) -> Optional[str]:
    """Why this site cannot be measured, or ``None`` to go ahead.

    Returns a sentence naming both values and the remedy — never a bare bool,
    because the whole defect is a verdict a reader cannot act on.
    """
    target = root / site["file"]
    try:
        repo = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=30)
        if repo.returncode != 0:
            raise ValueError("not inside a git work tree")
        repo_root = Path(repo.stdout.strip())
        rel = target.resolve().relative_to(repo_root.resolve()).as_posix()
        head_src = _git_show_head(repo_root, rel)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        _HEAD_BLIND.append(f"{site['file']}: {exc}")
        return None
    try:
        lines, idx, start, end = _literal_span(
            head_src, site["arg_line"], site["arg_col"])
        head_value = lines[idx][start:end]
    except ValueError:
        # The line moved, or HEAD has something else there. Then the difference
        # is NOT a bare literal flip and this is not the shape being detected.
        return None
    if head_value == site["value"]:
        return None
    # BOTH ends must be in the closed set, and the working-tree end is the one
    # that is easy to forget. This gate only ever writes a value FROM
    # `alternatives`, so a literal that is not one cannot be its leftover no
    # matter what HEAD says — that is somebody's real edit, and refusing it
    # would be a guess. Caught by
    # `test_an_edit_to_the_literal_outside_the_closed_set_is_not_refused`,
    # which failed against the first version of this condition.
    if (head_value not in site["alternatives"]
            or site["value"] not in site["alternatives"]):
        return None
    return (f"this file differs from HEAD AT THIS CALL SITE and HEAD carries "
            f"{head_value!r}, another of this parameter's alternatives "
            f"{site['alternatives']} -- indistinguishable from a mutant this "
            f"gate left behind when a previous run was killed. Measuring it "
            f"would re-derive the argued value from the leftover. "
            f"Restore with: git checkout HEAD -- {site['file']}")


def run_pytest(paths: Sequence[Path], cwd: Path, basetemp: Path,
               extra: Sequence[str] = ()) -> Tuple[int, str]:
    env = dict(os.environ)
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    cmd = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
           "--basetemp", str(basetemp), "-x"]
    cmd += [str(p) for p in paths]
    cmd += list(extra)
    proc = subprocess.run(cmd, cwd=str(cwd), env=env,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          text=True)
    return proc.returncode, proc.stdout


def verify_pin(site: Dict[str, Any], root: Path, tests_dir: Path,
               max_test_files: int, basetemp: Path,
               extra: Sequence[str] = ()) -> Dict[str, Any]:
    """Flip the literal and see whether anything dies."""
    candidates = select_tests(site, tests_dir)
    result: Dict[str, Any] = {
        "candidate_tests": [str(p.relative_to(root)) for p in candidates],
    }
    # BEFORE the no-candidates branch, not after it. A site with no candidate
    # tests over a leftover reports UNPINNED just as confidently, and that
    # verdict is exactly as untrustworthy.
    stale = leftover_signature(root, site)
    if stale is not None:
        result["state"] = "ABSTAIN"
        result["why"] = stale
        return result
    if not candidates:
        result["state"] = "UNPINNED"
        result["why"] = "no test file names this program together with the parameter or callee"
        return result
    if len(candidates) > max_test_files:
        result["state"] = "ABSTAIN"
        result["why"] = (f"{len(candidates)} candidate test files exceeds "
                         f"--max-test-files {max_test_files}")
        return result

    target = root / site["file"]
    original = target.read_text(encoding="utf-8")
    journal = journal_for(root)
    killed_by: List[Dict[str, Any]] = []
    survivors: List[str] = []
    try:
        for other in [a for a in site["alternatives"] if a != site["value"]]:
            try:
                mutated = flip_source(original, site, other)
            except ValueError as exc:
                result["state"] = "ABSTAIN"
                result["why"] = f"could not rewrite the literal: {exc}"
                return result
            _arm(journal, target, original, mutated)
            target.write_text(mutated, encoding="utf-8")
            rc, out = run_pytest(candidates, root.parent, basetemp, extra)
            if rc != 0:
                killed_by.append({"flipped_to": other, "rc": rc,
                                  "killed_files": failing_files(out),
                                  "tail": out.strip().splitlines()[-1:] or [""]})
            else:
                survivors.append(other)
    finally:
        target.write_text(original, encoding="utf-8")
        _disarm(journal)

    if killed_by:
        # A RED test kills every mutant, including one nobody wrote a pin for.
        # Crediting that would hand out exactly the false clean bill of health
        # this gate exists to end, so the baseline is checked before a kill is
        # believed -- and checked LAZILY, because a surviving mutant is already
        # proof enough of UNPINNED and needs no baseline at all.
        #
        # Only the files that actually died are re-run. Baselining the whole
        # selection would answer a question nobody asked -- whether some OTHER
        # test is red -- and it is the dominant cost of this gate.
        named = [root.parent / f for k in killed_by for f in k.get("killed_files", [])]
        baseline_set = [p for p in dict.fromkeys(named) if p.exists()] or list(candidates)
        result["baseline_files"] = [str(p) for p in baseline_set]
        rc0, out0 = run_pytest(baseline_set, root.parent, basetemp, extra)
        result["baseline_rc"] = rc0
        if rc0 != 0:
            result["state"] = "ABSTAIN"
            result["why"] = ("candidate tests are RED before any flip, so a kill "
                             "proves nothing about this call site")
            result["baseline_tail"] = out0.strip().splitlines()[-1:] or [""]
            return result

    result["killed_by"] = killed_by
    result["survivors"] = survivors
    result["state"] = "PINNED" if killed_by else "UNPINNED"
    if not killed_by:
        result["why"] = ("every flip left the candidate tests green -- the value "
                         "at this call site is not asserted anywhere")
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_report(root: Path, require_default: bool = True) -> Dict[str, Any]:
    defs, by_name, sources = collect_policy_params(root, require_default)
    sites = collect_sites(root, by_name, sources)
    production = [s for s in sites if not s["in_tests"]]
    argued = [s for s in production if s["argued"]]
    return {
        "root": str(root),
        "files_swept": len(sources),
        "policy_params_defined": len(defs),
        "literal_sites_total": len(sites),
        "literal_sites_production": len(production),
        "argued_sites": len(argued),
        "sites": sites,
        "argued": argued,
        "require_default": require_default,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog="policy_direction_pin_check.py",
        description="A direction argued in prose and left unpinned by every test.")
    ap.add_argument("root", nargs="?", default=None,
                    help="programs directory to sweep (default: this file's directory)")
    ap.add_argument("--json", dest="json_out", default=None, help="write the full report here")
    ap.add_argument("--verify-pins", action="store_true",
                    help="flip each argued literal and run the candidate tests (BLOCKING)")
    ap.add_argument("--max-test-files", type=int, default=DEFAULT_MAX_TEST_FILES,
                    help="abstain rather than run more candidate test files than this")
    ap.add_argument("--only", default=None,
                    help="verify only sites whose file path contains this substring")
    ap.add_argument("--include-required", action="store_true",
                    help="drop D1 and widen the population to required parameters "
                         "(inspection only -- see the module docstring)")
    ap.add_argument("--basetemp", default=None, help="pytest --basetemp for the mutation runs")
    ap.add_argument("--pytest-arg", action="append", default=[],
                    help="extra argument forwarded to the mutation pytest runs")
    args = ap.parse_args(list(argv) if argv is not None else None)

    root = Path(args.root).resolve() if args.root else Path(__file__).resolve().parent
    if not root.is_dir():
        print(f"[UNDETERMINED] policy_direction_pin_check: {root} is not a directory",
              file=sys.stderr)
        return RC_UNDETERMINED

    report = build_report(root, require_default=not args.include_required)
    argued = report["argued"]

    print(f"[INFO] policy_direction_pin_check: swept {report['files_swept']} python file(s) "
          f"under {root}")
    print(f"[INFO]   defaulted closed-set string parameters defined : "
          f"{report['policy_params_defined']}")
    print(f"[INFO]   call sites passing one a literal (production)  : "
          f"{report['literal_sites_production']}"
          f"   (+{report['literal_sites_total'] - report['literal_sites_production']} in tests)")
    print(f"[INFO]   of those, ARGUED (D3 -- prose names the road not taken): {len(argued)}")

    if not args.verify_pins:
        for s in argued:
            print(f"  {s['file']}:{s['line']}  {s['callee']}({s['param']}={s['value']!r})"
                  f"  alternatives={s['alternatives']}"
                  f"  argued_by={'doc' if s['argued_by_doc'] else ''}"
                  f"{'+comment' if s['argued_by_comment'] else ''}")
        print("[INFO] inventory only; pass --verify-pins to run the flip and block")
        if args.json_out:
            Path(args.json_out).write_text(json.dumps(report, indent=1), encoding="utf-8")
        return RC_OK

    tests_dir = root / "tests"
    if not tests_dir.is_dir():
        print("[UNDETERMINED] policy_direction_pin_check: no tests/ directory to select from",
              file=sys.stderr)
        return RC_UNDETERMINED

    selected = [s for s in argued if (args.only or "") in s["file"]]

    # BEFORE anything is measured. A leftover mutation from a previous run is
    # not a dirty file this run can measure around: the sweep would re-derive
    # the argued value FROM it and report a self-consistent verdict over a
    # corrupt tree. Repair first, or refuse.
    rc_rec, lines = recover_journal(journal_for(root))
    for ln in lines:
        print(ln, file=sys.stderr if rc_rec else sys.stdout)
    if rc_rec:
        return rc_rec
    install_signal_restore()

    basetemp = Path(args.basetemp) if args.basetemp else Path(tempfile.mkdtemp(prefix="pdpc-"))
    basetemp.mkdir(parents=True, exist_ok=True)

    unpinned: List[Dict[str, Any]] = []
    abstained: List[Dict[str, Any]] = []
    pinned: List[Dict[str, Any]] = []
    try:
        for s in selected:
            verdict = verify_pin(s, root, tests_dir, args.max_test_files, basetemp,
                                 args.pytest_arg)
            s["pin"] = verdict
            bucket = {"PINNED": pinned, "UNPINNED": unpinned}.get(verdict["state"], abstained)
            bucket.append(s)
            print(f"  [{verdict['state']}] {s['file']}:{s['line']} "
                  f"{s['callee']}({s['param']}={s['value']!r})"
                  f"  tests={len(verdict['candidate_tests'])}"
                  + (f"  -- {verdict.get('why')}" if verdict.get("why") else ""))
    finally:
        if not args.basetemp:
            shutil.rmtree(basetemp, ignore_errors=True)

    if _HEAD_BLIND:
        # Never folded into a pass. A site whose HEAD copy could not be read was
        # measured WITHOUT the leftover check, so its verdict carries the risk
        # this check exists to remove — and a reader has to be told which ones.
        print(f"[INFO] policy_direction_pin_check: {len(_HEAD_BLIND)} site(s) "
              f"could not be compared against HEAD, so a leftover mutant there "
              f"would not have been noticed: "
              + "; ".join(_HEAD_BLIND[:5]), file=sys.stderr)

    report["verified"] = {"pinned": len(pinned), "unpinned": len(unpinned),
                          "abstained": len(abstained), "selected": len(selected)}
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(report, indent=1), encoding="utf-8")

    denom = len(pinned) + len(unpinned)
    ratio = f"{len(pinned)}/{denom}" if denom else "0/0"
    print(f"[INFO] pinned at their call site: {ratio}"
          f"   (abstained {len(abstained)} of {len(selected)} argued sites)")
    if unpinned:
        print(f"[FAIL] policy_direction_pin_check: {len(unpinned)} argued direction(s) "
              f"survive being flipped")
        for s in unpinned:
            print(f"  {s['file']}:{s['line']} {s['callee']}({s['param']}={s['value']!r}) "
                  f"-> {[a for a in s['alternatives'] if a != s['value']]} changes nothing "
                  f"any test can see")
        return RC_UNPINNED
    if abstained:
        # An abstention is NOT a pass. A gate that goes green by declining to
        # look is the shape this one was written against.
        print(f"[UNDETERMINED] policy_direction_pin_check: {len(abstained)} argued "
              f"direction(s) could not be decided", file=sys.stderr)
        for s in abstained:
            print(f"  {s['file']}:{s['line']} {s['callee']}({s['param']}={s['value']!r}) "
                  f"-- {s['pin'].get('why')}", file=sys.stderr)
        return RC_UNDETERMINED
    print("[PASS] policy_direction_pin_check: every argued direction dies when flipped")
    return RC_OK


if __name__ == "__main__":
    sys.exit(main())
