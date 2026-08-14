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
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
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


def flip_source(src: str, site: Dict[str, Any], new_value: str) -> str:
    """Replace exactly the literal at (arg_line, arg_col) with ``new_value``."""
    lines = src.splitlines(keepends=True)
    idx = site["arg_line"] - 1
    if idx < 0 or idx >= len(lines):
        raise ValueError("argument line out of range")
    line = lines[idx]
    col = site["arg_col"]
    rest = line[col:]
    m = re.match(r"""(?P<p>[rbuRBU]{0,2})(?P<q>'''|\"\"\"|'|")""", rest)
    if not m:
        raise ValueError("no string literal at the recorded column")
    quote = m.group("q")
    start_body = col + m.end()
    end_body = line.find(quote, start_body)
    if end_body < 0:
        raise ValueError("string literal is not closed on its own line")
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


# ---------------------------------------------------------------- sharding
# vibe-ic#1144. One landing run is 3399 s and this gate is 671 s of it. The six
# argued sites are INDEPENDENT -- each flips one literal in one file and runs
# that site's own candidate tests -- so they parallelise exactly, and the
# critical path becomes the single slowest SITE rather than their sum.
#
# EACH SHARD MUST RUN IN ITS OWN WORKTREE. Not a style note: this gate rewrites
# tracked source (`phase3_one_shot_runner.py` among them) and has a confirmed
# case of failing to restore it (#1089, #1029). Two shards in one tree would
# flip the same file underneath each other and both verdicts would be about a
# tree the other one wrote. The tool takes `root` as an argument precisely so
# the caller can point each shard at a different checkout; it cannot enforce
# that from inside, so `--shard` REFUSES unless the caller acknowledges it (see
# `--shard-worktree-ack`).

def site_key(s: Dict[str, Any]) -> str:
    """`file:line:param` — stable across runs and unambiguous.

    `--only` cannot address a site: it matches a substring of the FILE, and
    `phase3_one_shot_runner.py` carries TWO argued sites (`:4198` and `:8414`).
    Sharding on it would put the two heaviest halves of this gate in the same
    shard and buy nothing.
    """
    return f"{s['file']}:{s['line']}:{s['param']}"


def site_cost(s: Dict[str, Any], tests_dir: Path) -> int:
    """A cost PROXY: pytest invocations this site will need.

    One run per flip plus one baseline, each over the site's candidate test
    files -- so `(len(alternatives) - 1 + 1) * len(candidates)`.

    A proxy rather than a measured table ON PURPOSE. A table of seconds keyed by
    site name is a hand-maintained list, and this repo has watched that shape
    rot silently three times; the proxy is recomputed from the tree every run
    and cannot go stale. It is VALIDATED against measured wall clock rather than
    assumed -- see `test_the_cost_proxy_ranks_sites_the_way_the_clock_does`.
    """
    n_alt = max(1, len(s.get("alternatives") or []))
    return n_alt * max(1, len(select_tests(s, tests_dir)))


def site_weight(s: Dict[str, Any], tests_dir: Path,
                measured: Optional[Dict[str, float]] = None) -> float:
    """MEASURED seconds when we have them, the proxy when we do not.

    THE PROXY IS NOT GOOD ENOUGH ALONE, and this is measured rather than
    suspected. Running all six sites once, one per worktree:

        site                                   cost   secs
        matrix_mutation_ledger.py:2380            6    284
        phase3_one_shot_runner.py:8414          102    237
        payload_bit_position_check.py:111         2     67
        dft_test_coverage.py:180                  2     66
        phase3_one_shot_runner.py:4198            2     66
        atpg_untestable_fault_classify.py:331     2     65

    Spearman rho 0.89 -- the proxy sorts the two heavy sites above the four
    light ones correctly and then INVERTS THE TOP TWO, which is the only pair
    whose order changes the critical path. `cost` counts pytest invocations;
    what costs time is how slow those particular test FILES are, and three slow
    files beat thirty-four fast ones.

    So the weight is measured, and `--shard` says which source it used for each
    site. An unmeasured site falls back to the proxy and is NAMED, never
    silently assumed cheap -- a scheduler that quietly treats an unknown item as
    zero is how one host ends up holding the long pole.
    """
    if measured:
        v = measured.get(site_key(s))
        if isinstance(v, (int, float)) and v > 0:
            return float(v)
    return float(site_cost(s, tests_dir))


def plan_shards(sites: List[Dict[str, Any]], n: int, tests_dir: Path,
                measured: Optional[Dict[str, float]] = None
                ) -> List[List[Dict[str, Any]]]:
    """Longest-processing-time-first bin packing over `site_cost`.

    LPT, not round-robin and not an even split by COUNT: an even split by count
    is exactly the mistake #1144 names -- it leaves one host holding the
    heaviest item and the critical path does not move. Heaviest-first into the
    currently-lightest shard is the standard 4/3-approximation and is
    deterministic, so shard i is the same set on every host without any
    coordination.

    EVERY SITE LANDS IN EXACTLY ONE SHARD. That is the property `--merge`
    depends on to state its denominator, and it is pinned by a test.
    """
    shards: List[List[Dict[str, Any]]] = [[] for _ in range(n)]
    load = [0.0] * n
    for s in sorted(sites, key=lambda x: (-site_weight(x, tests_dir, measured),
                                          site_key(x))):
        i = load.index(min(load))
        shards[i].append(s)
        load[i] += site_weight(s, tests_dir, measured)
    return shards


def merge_shard_reports(paths: List[Path]) -> Tuple[int, List[str]]:
    """Aggregate shard reports into one verdict. Returns `(rc, lines)`.

    THE DENOMINATOR IS THE POINT (#1144 rule 3). A shard that died, was never
    started, or wrote an unreadable report must FAIL THE WHOLE RUN -- never
    silently reduce coverage. So this reads each shard's own declared
    `shard_total`/`shard_sites`, reconstructs the union, and refuses unless the
    union is exactly the inventory every shard agreed on.

    rc 0  every site verified and pinned
    rc 1  a site is UNPINNED
    rc 2  the run cannot state its own reach -- missing shard, unreadable
          report, disagreeing inventories, or a site nobody covered
    """
    lines: List[str] = []
    seen: Dict[str, str] = {}
    inventories: List[Tuple[str, ...]] = []
    unpinned: List[str] = []
    abstained: List[str] = []
    for p in paths:
        try:
            rec = json.loads(Path(p).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            lines.append(f"[UNDETERMINED] shard report unreadable: {p} ({exc})")
            return RC_UNDETERMINED, lines
        inv = rec.get("shard_inventory")
        if not isinstance(inv, list) or not inv:
            lines.append(f"[UNDETERMINED] {p} declares no shard_inventory — it "
                         f"was not produced by `--shard`, so its reach is unknown")
            return RC_UNDETERMINED, lines
        inventories.append(tuple(inv))
        for s in rec.get("sites", []):
            if not s.get("argued") or "pin" not in s:
                continue
            k = site_key(s)
            if k in seen:
                lines.append(f"[UNDETERMINED] site {k} appears in two shards — "
                             f"the partition is not disjoint")
                return RC_UNDETERMINED, lines
            st = s["pin"].get("state")
            seen[k] = st
            if st == "UNPINNED":
                unpinned.append(f"{k}: {s['pin'].get('why', '')}")
            elif st != "PINNED":
                abstained.append(f"{k}: {s['pin'].get('why', '')}")
    if len({tuple(sorted(i)) for i in inventories}) != 1:
        lines.append("[UNDETERMINED] the shards disagree about how many argued "
                     "sites exist — they were planned against different trees")
        return RC_UNDETERMINED, lines
    inventory = sorted(inventories[0])
    missing = [k for k in inventory if k not in seen]
    lines.append(f"[INFO] policy_direction_pin_check: {len(seen)} of "
                 f"{len(inventory)} argued site(s) verified across "
                 f"{len(paths)} shard(s); {len(abstained)} abstained")
    if missing:
        lines.append(f"[UNDETERMINED] {len(missing)} site(s) were covered by NO "
                     f"shard — a run that cannot state its own reach is not a "
                     f"result: " + ", ".join(missing))
        return RC_UNDETERMINED, lines
    for u in unpinned:
        lines.append(f"  [UNPINNED] {u}")
    for a in abstained:
        lines.append(f"  [ABSTAIN] {a}")
    if unpinned:
        lines.append(f"[FAIL] policy_direction_pin_check: {len(unpinned)} argued "
                     f"direction(s) survive being flipped")
        return RC_UNPINNED, lines
    if abstained:
        lines.append(f"[UNDETERMINED] policy_direction_pin_check: "
                     f"{len(abstained)} argued direction(s) could not be decided")
        return RC_UNDETERMINED, lines
    lines.append("[PASS] policy_direction_pin_check: every argued direction "
                 "dies when flipped")
    return RC_OK, lines


def run_pytest(paths: Sequence[Path], cwd: Path, basetemp: Path,
               extra: Sequence[str] = ()) -> Tuple[int, str]:
    """Run the candidate tests and report EVERY file that died.

    `-x` USED TO BE HERE, and it decided the verdict. It stops pytest at the
    first failure, so `failing_files()` could only ever name ONE file -- and
    which one depends on collection order across the candidate selection, not
    on the call site. On a tree with unrelated red in it (which is every tree
    this gate has ever run on during a repair) the sequence was:

        mutant run stops at the first RED file, whatever it is
        -> killed_files = [that unrelated file]
        -> baseline of that file is red
        -> ABSTAIN, while the test that genuinely pins the site is never reached

    MEASURED on `origin/main` @ 3febf537: `matrix_mutation_ledger.py:2380`
    reports PINNED, killed by `tests/test_matrix_mutation_ledger.py`, which
    sorts SECOND in its three-file selection. Appending one failing test to the
    file that sorts FIRST -- touching neither the call site nor the pinning
    test -- flipped the gate to `0/0 (abstained 1 of 1)`.

    A gate whose verdict is a function of which failure it happened to reach
    first is not measuring the call site. Both runs are now exhaustive, and
    the kill/baseline comparison below is per FILE.
    """
    env = dict(os.environ)
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    cmd = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
           "--basetemp", str(basetemp)]
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
        # PER FILE, not per RUN. "Some file in the baseline is red" is not a
        # reason to disbelieve a kill in a DIFFERENT file -- that inference is
        # what let one unrelated red test abstain a site whose pin was intact.
        # A kill is believed exactly when the file that died is GREEN at
        # baseline; the gate abstains only when every file that died was
        # already red, which is the case the baseline check was written for.
        red_at_baseline = set(failing_files(out0))
        killed_now = [f for k in killed_by for f in k.get("killed_files", [])]
        believable = [f for f in dict.fromkeys(killed_now) if f not in red_at_baseline]
        result["red_at_baseline"] = sorted(red_at_baseline)
        result["kills_believed"] = believable
        if not believable:
            result["state"] = "ABSTAIN"
            result["why"] = ("every candidate test that died under the flip was "
                             "already RED before any flip, so no kill proves "
                             "anything about this call site")
            result["baseline_tail"] = out0.strip().splitlines()[-1:] or [""]
            return result
        killed_by = [k for k in killed_by
                     if any(f in believable for f in k.get("killed_files", []))]

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
    # --- sharding (vibe-ic#1144) -------------------------------------------
    ap.add_argument("--list-sites", action="store_true",
                    help="print the argued-site inventory with each site's key "
                         "and cost weight, then exit (no flips)")
    ap.add_argument("--site", action="append", default=[], metavar="FILE:LINE",
                    help="verify exactly this site (repeatable). Addresses one "
                         "site, unlike --only which matches a whole FILE and "
                         "so cannot separate the two sites in "
                         "phase3_one_shot_runner.py")
    ap.add_argument("--shard", default=None, metavar="I/N",
                    help="verify shard I of N, time-balanced by cost weight")
    ap.add_argument("--weights", default=None, metavar="WEIGHTS.json",
                    help="{site_key: seconds} from a previous run, used to "
                         "balance --shard. Without it the cost PROXY is used, "
                         "which measurably mis-orders the two heaviest sites")
    ap.add_argument("--shard-worktree-ack", action="store_true",
                    help="acknowledge that THIS shard has its own worktree. "
                         "Required by --shard: this gate rewrites tracked "
                         "source, so two shards in one tree corrupt each other "
                         "(#1089, #1029)")
    ap.add_argument("--merge", nargs="+", default=None, metavar="REPORT.json",
                    help="aggregate shard reports into one verdict, refusing "
                         "unless every site in the inventory was covered")
    ap.add_argument("--only", default=None,
                    help="verify only sites whose file path contains this substring")
    ap.add_argument("--include-required", action="store_true",
                    help="drop D1 and widen the population to required parameters "
                         "(inspection only -- see the module docstring)")
    ap.add_argument("--basetemp", default=None, help="pytest --basetemp for the mutation runs")
    ap.add_argument("--pytest-arg", action="append", default=[],
                    help="extra argument forwarded to the mutation pytest runs")
    args = ap.parse_args(list(argv) if argv is not None else None)

    # --merge aggregates shard reports and never touches a tree, so it runs
    # before any of the discovery below.
    if args.merge:
        rc, lines = merge_shard_reports([Path(x) for x in args.merge])
        for ln in lines:
            print(ln, file=sys.stderr if rc else sys.stdout)
        return rc

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

    if args.list_sites:
        # The inventory a scheduler needs, and nothing else: no flips, no tree
        # writes. `cost` is the proxy `plan_shards` balances on.
        #
        # BEFORE the inventory-only early return below, which would otherwise
        # print the human listing and return first.
        tests_dir = root / "tests"
        if not tests_dir.is_dir():
            print("[UNDETERMINED] policy_direction_pin_check: no tests/ "
                  "directory, so no site cost can be computed", file=sys.stderr)
            return RC_UNDETERMINED
        inv = [{"key": site_key(x), "file": x["file"], "line": x["line"],
                "param": x["param"], "alternatives": x["alternatives"],
                "cost": site_cost(x, tests_dir)} for x in argued]
        if args.json_out:
            Path(args.json_out).write_text(
                json.dumps({"sites": inv}, indent=1), encoding="utf-8")
        for e in sorted(inv, key=lambda d: -d["cost"]):
            print(f"  cost={e['cost']:>4}  {e['key']}  "
                  f"alternatives={e['alternatives']}")
        print(f"[INFO] policy_direction_pin_check: {len(inv)} argued site(s), "
              f"total cost {sum(e['cost'] for e in inv)}")
        return RC_OK

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

    # --shard and --site address SITES; --only addresses a FILE and is kept
    # unchanged for callers that already use it.
    shard_inventory = [site_key(s) for s in argued]
    if args.shard:
        if not args.shard_worktree_ack:
            print("[UNDETERMINED] policy_direction_pin_check: --shard needs "
                  "--shard-worktree-ack. This gate rewrites tracked source, so "
                  "two shards sharing a checkout flip the same file underneath "
                  "each other and both verdicts describe a tree the other one "
                  "wrote (#1089, #1029). Give each shard its own worktree.",
                  file=sys.stderr)
            return RC_UNDETERMINED
        try:
            i_s, n_s = args.shard.split("/")
            i_shard, n_shard = int(i_s), int(n_s)
            if not (1 <= i_shard <= n_shard):
                raise ValueError
        except ValueError:
            print(f"[UNDETERMINED] --shard wants I/N with 1<=I<=N, got "
                  f"{args.shard!r}", file=sys.stderr)
            return RC_UNDETERMINED
        measured: Dict[str, float] = {}
        if args.weights:
            try:
                measured = {str(k): float(v) for k, v in
                            json.loads(Path(args.weights).read_text()).items()}
            except (OSError, ValueError, TypeError) as exc:
                print(f"[UNDETERMINED] --weights unreadable: {exc}",
                      file=sys.stderr)
                return RC_UNDETERMINED
        selected = plan_shards(argued, n_shard, tests_dir, measured)[i_shard - 1]
        # WHICH WEIGHT EACH SITE USED. A balance decision a reader cannot audit
        # is a balance decision nobody can fix when one host runs long.
        unmeasured = [site_key(s) for s in argued if site_key(s) not in measured]
        print(f"[INFO] shard {i_shard}/{n_shard}: {len(selected)} of "
              f"{len(argued)} argued site(s), weight "
              f"{sum(site_weight(s, tests_dir, measured) for s in selected):.0f}"
              f" of "
              f"{sum(site_weight(s, tests_dir, measured) for s in argued):.0f}"
              f" ({'measured' if measured else 'PROXY'})")
        if unmeasured:
            print(f"[INFO] {len(unmeasured)} site(s) had no measured weight and "
                  f"fell back to the proxy: " + ", ".join(sorted(unmeasured)))
    elif args.site:
        want = set(args.site)
        selected = [s for s in argued
                    if f"{s['file']}:{s['line']}" in want or site_key(s) in want]
        unknown = want - {f"{s['file']}:{s['line']}" for s in argued} \
                       - {site_key(s) for s in argued}
        if unknown:
            # A --site nobody matched is a caller asking about a site that does
            # not exist, and answering 0/0 PASS to that is the vacuous pass this
            # whole program is about.
            print(f"[UNDETERMINED] --site named {len(unknown)} site(s) this tree "
                  f"does not have: " + ", ".join(sorted(unknown)), file=sys.stderr)
            return RC_UNDETERMINED
    else:
        selected = [s for s in argued if (args.only or "") in s["file"]]
    basetemp = Path(args.basetemp) if args.basetemp else Path(tempfile.mkdtemp(prefix="pdpc-"))
    basetemp.mkdir(parents=True, exist_ok=True)

    unpinned: List[Dict[str, Any]] = []
    abstained: List[Dict[str, Any]] = []
    pinned: List[Dict[str, Any]] = []
    try:
        for s in selected:
            _t0 = time.monotonic()
            verdict = verify_pin(s, root, tests_dir, args.max_test_files, basetemp,
                                 args.pytest_arg)
            # Measured here and nowhere else, so `--weights` is fed by the same
            # code path it balances.
            s["pin_seconds"] = time.monotonic() - _t0
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

    report["verified"] = {"pinned": len(pinned), "unpinned": len(unpinned),
                          "abstained": len(abstained), "selected": len(selected)}
    # WHAT THIS SHARD BELIEVES THE WHOLE POPULATION IS. `--merge` compares every
    # shard's copy and refuses if they disagree, which is how a shard planned
    # against a different tree is caught instead of quietly shrinking the
    # denominator.
    report["shard_inventory"] = shard_inventory
    # SO THE NEXT RUN CAN BALANCE ON A FACT. `--weights` consumes exactly this.
    report["shard_seconds"] = {site_key(s): round(s.get("pin_seconds", 0.0), 1)
                               for s in selected}
    report["shard_selected"] = [site_key(s) for s in selected]
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
