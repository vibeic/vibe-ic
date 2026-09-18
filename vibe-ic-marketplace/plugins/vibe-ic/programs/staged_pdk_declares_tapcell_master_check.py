#!/usr/bin/env python3
"""staged_pdk_declares_tapcell_master_check.py — a load-bearing sentinel
default may not be INHERITED. Every construction site has to SAY it.

THE DEFECT CLASS (vibe-ic#2360, and #586 before it)
---------------------------------------------------
`PdkConfig` declares `tapcell_master: Optional[str] = None`, and that `None`
is not "unset" — it is a VALUE with a meaning: *this PDK ships no tapcell
master*. The flow reads it and routes the latch-up verification down the
tapless-cell branch, which is correct for a genuinely tapless library and
wrong for a tapcell-methodology one, where it downgrades "the tapcell step was
skipped" from a conclusive FAIL to a non-blocking indeterminate. A real
latch-up exposure reported as a shrug is, in #586's own words, strictly worse
than the false FAIL it replaced.

So the dangerous state is not a wrong value. It is an OMISSION that is
indistinguishable from a deliberate declaration: a construction site that never
mentions the field inherits the dataclass default and produces the same object
as a site that meant it. The omitting site in the incident carried the MOST
keyword arguments of any site in the file, so it read as exhaustive.

`pdk_registry_selectable_check.py` enforces the same invariant on the DATA
side and walks registry entries ONLY. A PDK staged into a project has no
registry entry, so it is resolved by code that builds the config directly —
outside that gate's venue. This checker is the code-side half.

THE RULE, IN FULL. IT IS THIS SHORT ON PURPOSE.
----------------------------------------------
Over every shipped NON-TEST `.py` file under the scanned root, by AST.

  ONE PRECONDITION, and it can only REFUSE: the name `PdkConfig` must denote
  exactly ONE class in the venue. None means it was renamed and the contract is
  stale; more than one means a call could be constructing either and this rule
  could not tell. Either way rc 2, before a single site is judged.

  A CONSTRUCTION SITE is a call whose callee is
      * the bare name `PdkConfig`, or
      * an attribute `<anything>.PdkConfig`, or
      * a name that a MODULE-LEVEL statement of the SAME FILE binds directly
        to one of those two (`X = PdkConfig`, `X = mod.PdkConfig`,
        `from m import PdkConfig as X`). ONE HOP. `Y = X` is not followed.

  Each site is judged by ONE question — is `tapcell_master` among the
  keywords the call writes down?

      yes                                            -> DECLARED
      no, and the call passes NO positional argument,
          no `*a` and no `**d`                       -> OMITTED, rc 1
      anything else                                  -> UNDECIDABLE, rc 2

AST, never text. The sites span 17-36 keyword arguments over dozens of lines,
so no line-oriented pattern sees one whole; and a rule that reads TEXT is
satisfiable by writing `# tapcell_master=x` beside the call. Comments are not
in the AST at all and a string is a `Constant`, never a `keyword`.

WHY UNDECIDABLE IS rc 2 AND NOT A GREEN CENSUS LINE
---------------------------------------------------
`C(**d)` may or may not carry the key; `C(*a)` and `C(x, y)` may or may not
reach the field's position. This file will not guess, and it will not call any
of them a defect. But answering rc 0 over them is not neutral either: rc 0 is
this gate's certificate, and `PdkConfig(name=..., ...)` -> `PdkConfig(..., **{})`
is a ONE-TOKEN edit that leaves the omission exactly where it was. A gate you
can switch off by typing two braces is not a gate. So an undecidable site is
named, is never called a defect, and returns CANNOT-CHECK — the same answer
this file gives a root it cannot read. CANNOT-CHECK IS NOT PASS: wire it with a
runner that blocks on rc 2, or this ratchet dies in silence.

The three star/positional forms get the SAME answer, with no exceptions: a rule
that calls `**d` undecidable and `*a` a defect is not applying a principle.

Measured: all five sites on this tree pass 0 positional arguments, so rc 2 is
not reachable from today's shape by anything but an edit that means to reach it.

NOT A FINDING, DELIBERATELY
---------------------------
TEST SOURCE. A fixture that omits the field is exercising the tapless branch on
purpose — that IS the fixture. Measured on this tree: 106 construction sites
exist, 101 of them under `programs/tests/`, many omitting the field by design.
Test trees, `test_*.py` / `*_test.py` / `conftest.py`, and `gate_fixtures/` are
out of venue. The venue is decided by the path BELOW the scanned root, never by
an ancestor of it, so a checkout that happens to live under a directory called
`test/` is not a test tree.

KNOWN CONSERVATISM — cases this rule KNOWS it misses, and will not grow to catch
-------------------------------------------------------------------------------
Each of the following is a FALSE NEGATIVE that is accepted so that the rule
stays sound and undisarmable. Every one of them was measured to occur ZERO
times in this tree's venue. None is closed by adding machinery here: the
machinery added to close them in an earlier round is what opened the holes this
version deletes.

  * VALUE SOURCE IS NOT CHECKED. `tapcell_master=decl.get("tapcell_master")`
    states the keyword and PASSES, yet reproduces the incident exactly when the
    key is absent from `decl` — the omission has moved from the call into the
    mapping. So does a literal `tapcell_master=None`, which is the LEGITIMATE
    way to declare taplessness and which this gate must accept for the same
    reason `pdk_registry_selectable_check` accepts a null. This gate reads
    DECLARATION, not DERIVATION. Do NOT cite it as covering #2360 end to end;
    the behavioural half is `programs/tests/
    test_issue2360_staged_pdk_is_asked_for_its_tapcell_master.py`.
  * ANY INDIRECTION BUT ONE MODULE-LEVEL HOP. `cls = PdkConfig` inside a
    function, `Y = X` where `X` is itself an alias, a constructor stored in a
    dict or returned by a factory — none is a site here. Following names into
    function scopes is what made a PARAMETER named `cls` in an unrelated
    function report a defect against an object that was not this class at all.
    The scope model that fixed that had a bug of its own. Both are gone; the
    rule is one hop at module level, where a reader can see the binding.
  * A COMPUTED CALLEE IS THE SHARP EDGE OF THAT, AND IT IS MEASURED. Rewriting
    `return PdkConfig(` as `return globals()["PdkConfig"](` or
    `return getattr(sys.modules[__name__], "PdkConfig")(` is ONE line, is
    runtime-identical, leaves the omission exactly where it was, and takes this
    gate from rc 1 to rc 0 — the site simply stops being one, and the printed
    denominator drops from 5 to 4 with nothing to say it moved. Both were run
    against the pre-fix source and both returned `[PASS] all 4 construction
    site(s)`. It is NOT closed here and this file does not pretend otherwise:
    closing it needs a model of computed callees, which is exactly the kind of
    machinery whose last two rounds each opened a worse hole than they shut,
    and a blanket "an unresolvable callee in a file that names the class is
    rc 2" would refuse on every `handlers[k](...)` in that file forever. What
    actually covers it is the BEHAVIOURAL half, which does not care how the
    constructor is spelled: `programs/tests/
    test_issue2360_staged_pdk_is_asked_for_its_tapcell_master.py` drives
    `_detect_pdk` on a staged PDK and asserts the RESOLVED value. Wire both or
    neither; this file alone is the syntactic half and says so.
  * POSITIONAL ARGUMENTS ARE NEVER READ AS A DECLARATION. Deriving the field's
    positional index from a class body was wrong in BOTH directions at once — a
    `ClassVar` pushed it up and fired at a site that DID pass the field, a base
    class pushed it down and stayed silent at one that did not. The index model
    is deleted, not repaired: a call with positional arguments is out of this
    rule's scope and returns rc 2.
  * A MODULE NAMED `test_*.py` THAT IS IMPORTED AS A LIBRARY is excluded with
    the fixtures. Measured: 4 production modules import one; none constructs
    this class.
  * UNTRACKED FILES, under `git-tracked` enumeration. `git add` is enough — it
    need not be committed — so nothing that reaches CI or a landing is affected.
  * A NAME ALSO BOUND AS A PARAMETER takes the whole module's sites for that
    name to rc 2, not to a verdict. `def build(PdkConfig): return
    PdkConfig(a=1)` constructs whatever the caller passed, and telling that
    call apart from a real one needs the scope model this file has twice got
    wrong. It refuses instead, at file granularity, which is coarse and safe:
    the answer can only become CANNOT-CHECK, never green. Measured: 0 modules
    in this venue bind the contracted name that way.
  * A FILE THAT DOES NOT CONTAIN THE TOKEN `PdkConfig` IS NOT PARSED. Under a
    name-keyed rule it cannot hold a site: the bare name, the attribute and the
    one-hop alias all spell the token. It is therefore also not reported as
    unparseable, because it could not have been examined either way.

MEASURED, BOTH SIDES OF THE FIX
-------------------------------
This tree (2026-09-18, `git-tracked` enumeration): 1510 shipped non-test `.py`
files scanned in 1.5s, 4 of them naming the class, ONE defining it, 5
construction sites, 5 declaring, 0 omitting, 0 undecidable, 0 unparseable —
rc 0. That is the state AFTER 5fe6b688b landed, so this gate DISCOVERS nothing
today and does not pretend to. Run against the source one commit earlier it
returns rc 1 and names the site: `phase3_one_shot_runner.py:11494`, 34 keyword
arguments, no `tapcell_master`. That site was the staged-PDK lane — the one of
the five carrying the MOST keyword arguments, which is why the omission read as
deliberate to every reader it passed.

The value of this file is a RATCHET, not a discovery: the sixth construction
site cannot re-enter that state in silence.

BEFORE THIS LANDS
-----------------
`checker_execution_wiring_audit.py` BLOCKS (rc 1) on a checker that nothing but
its own test runs. Wire it into `tools/ci/repo_hygiene_gates.sh` with `run`,
NOT `run_tolerating_uncheckable` — rc 2 is load-bearing here and a runner that
treats CANNOT-CHECK as non-blocking hands back the `**{}` hole this file
refuses to have. Ship the `can_pass`/`can_fail` pair beside it
(`tools/ci/gate_fixtures/staged_pdk_declares_tapcell_master.py`) per
`tools/ci/gate_fixture_debt.json`, and regenerate the derived-file ratchets
with `gatekeeper_prepare_landing.py`.

USAGE
-----
    staged_pdk_declares_tapcell_master_check.py [ROOT] [--json OUT]

EXIT CODES
----------
    0 = PASS          at least one construction site, and every one declares it
    1 = FAIL          at least one site inherits the default in silence
    2 = CANNOT-CHECK  the name does not denote exactly one class / no site
                      found / a site this rule cannot decide / a file that
                      mentions the class would not parse / bad root.
                      Never returned for "I looked and it was clean".

chip-AGNOSTIC: names a class and a field, never a foundry, a library or a part.
"""
from __future__ import annotations

# --- sibling-import path (vibe-ic#2104) ------------------------------------
# `programs/` is a flat directory whose modules import each other by BARE name.
# Python puts a file's own directory on `sys.path` only when that file is run
# as `__main__`; under `importlib.util.spec_from_file_location` — how the gates
# and much of the suite load a program — it does not.
import os as _os                                                    # noqa: E402
import sys as _sys                                                  # noqa: E402

if _os.path.dirname(_os.path.abspath(__file__)) not in _sys.path:
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
# ---------------------------------------------------------------------------

import argparse                                                     # noqa: E402
import ast                                                          # noqa: E402
import json                                                         # noqa: E402
import warnings                                                     # noqa: E402
from pathlib import Path                                            # noqa: E402
from typing import Any, Dict, List, Optional, Set, Tuple            # noqa: E402

try:                                    # optional — published (git-tracked)
    import _published_tree as _pt       # type: ignore
except ImportError:                     # pragma: no cover — standalone use
    _pt = None                          # type: ignore


RC_PASS, RC_FAIL, RC_CANNOT_CHECK = 0, 1, 2

#: The one contract. A class whose default for this field is a load-bearing
#: sentinel, so every construction site must state it. Not a table and not a
#: CLI override: a second pair is a second measured argument, not a parameter.
CONTRACT_CLASS = "PdkConfig"
CONTRACT_FIELD = "tapcell_master"

_SKIP_DIR_PARTS = {".git", "__pycache__", ".pytest_cache", "node_modules",
                   ".mypy_cache", ".ruff_cache", "gate_fixtures"}
_TEST_DIR_PARTS = {"tests", "test"}


# ---------------------------------------------------------------------------
# VENUE
# ---------------------------------------------------------------------------
def venue_parts(path: Path, root: Optional[Path]) -> Tuple[str, ...]:
    """The path components the VENUE may be decided by: those BELOW the root.

    `path.parts` includes every ancestor of the checkout, so a tree cloned into
    `~/test/` would have its whole venue classified as fixture source and the
    gate switched off by where somebody put it, reported as `0 files scanned`.
    """
    if root is None:
        return path.parts
    try:
        return path.relative_to(root).parts
    except ValueError:                  # pragma: no cover — caller error
        return path.parts


def is_test_source(path: Path, root: Optional[Path] = None) -> bool:
    """True for source whose omissions are fixture intent, not production."""
    name = path.name
    if name == "conftest.py" or name.startswith("test_") or name.endswith("_test.py"):
        return True
    return any(part in _TEST_DIR_PARTS for part in venue_parts(path, root))


def iter_source_files(root: Path) -> Tuple[List[Path], str]:
    """(shipped non-test ``*.py`` under ``root``, HOW they were enumerated).

    Published means COMMITTED, not "on this disk": a working checkout also
    holds whatever the last local run left behind, so a filesystem walk and a
    tracked enumeration give different answers for byte-identical code. The
    mode is RETURNED and printed, because a fallback nobody can see is how that
    difference stays invisible — and a git enumeration that RAISED is a third
    state that says so rather than degrading to "off" while reporting success.
    """
    candidates = [p for p in sorted(root.rglob("*.py"))
                  if p.is_file()
                  and not any(part in _SKIP_DIR_PARTS
                              for part in venue_parts(p, root))
                  and not is_test_source(p, root)]
    if _pt is None:                     # pragma: no cover — standalone use
        return candidates, "filesystem-walk (no _published_tree module)"
    try:
        published = _pt.published_paths(root)
    except Exception as exc:            # pragma: no cover — never fail-open
        return candidates, (f"filesystem-walk (git enumeration raised "
                            f"{type(exc).__name__}: {exc})")
    if published is None:
        return candidates, "filesystem-walk (not a published tree)"
    return list(_pt.filter_to_published(root, candidates)), "git-tracked"


# ---------------------------------------------------------------------------
# THE RULE
# ---------------------------------------------------------------------------
def _callee_name(call: ast.Call) -> Optional[str]:
    """`C(..)` -> "C"; `m.C(..)` -> "C"; anything computed -> None."""
    f = call.func
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        return f.attr
    return None


def _is_the_constructor(value: Optional[ast.AST]) -> bool:
    """Does ``value`` spell the contracted class itself — ONE hop, no chain?"""
    if isinstance(value, ast.Name):
        return value.id == CONTRACT_CLASS
    if isinstance(value, ast.Attribute):
        return value.attr == CONTRACT_CLASS
    return False


def constructor_names(tree: ast.AST) -> Set[str]:
    """Names that construct the class in THIS module: the class, plus one hop.

    MODULE-LEVEL statements only. A binding inside a function is local to it,
    and reading those made a same-named PARAMETER of an unrelated function a
    construction site. The class's own name is in the set UNCONDITIONALLY: a
    rebinding may cancel an alias, never the rule itself, or `PdkConfig = None`
    in dead code would be a one-line way to switch this gate off.
    """
    alias: Set[str] = set()
    rebound: Set[str] = set()
    for stmt in getattr(tree, "body", []):
        if isinstance(stmt, (ast.Assign, ast.AnnAssign)):
            targets = (stmt.targets if isinstance(stmt, ast.Assign)
                       else [stmt.target])
            into = alias if _is_the_constructor(stmt.value) else rebound
            into.update(t.id for t in targets if isinstance(t, ast.Name))
        elif isinstance(stmt, ast.ImportFrom):
            for a in stmt.names:
                if a.name == CONTRACT_CLASS:
                    alias.add(a.asname or a.name)
    return {CONTRACT_CLASS} | (alias - rebound)


def parameter_names(tree: ast.AST) -> Set[str]:
    """Every name bound as a PARAMETER anywhere in this module.

    A parameter spelled like the class is not the class: calling it constructs
    whatever the caller passed. Which binding a given call reaches is a
    question about scope, and the two scope models this file has carried each
    shipped a bug of their own, so it does not answer — a file that binds the
    contracted name, or an alias of it, as a parameter has THAT name's sites
    reported UNDECIDABLE. rc 2: never a defect, never counted clean.
    """
    out: Set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            a = node.args
            out.update(x.arg for x in
                       list(a.posonlyargs) + list(a.args) + list(a.kwonlyargs))
            for v in (a.vararg, a.kwarg):
                if v is not None:
                    out.add(v.arg)
    return out


def sites_in(tree: ast.AST) -> List[Dict[str, Any]]:
    """Every construction site in one module, each with its verdict."""
    names = constructor_names(tree)
    shadowed = parameter_names(tree) & names
    out: List[Dict[str, Any]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if _callee_name(node) not in names:
            continue
        kwnames = [k.arg for k in node.keywords]
        star_kw = any(a is None for a in kwnames)
        star_pos = any(isinstance(a, ast.Starred) for a in node.args)
        if _callee_name(node) in shadowed:
            verdict, why = "UNDECIDABLE", (
                f"calls {_callee_name(node)!r}, which this module also binds "
                f"as a PARAMETER, so whether this call reaches the contracted "
                f"class or whatever a caller passed is not decidable here")
        elif CONTRACT_FIELD in kwnames:
            verdict, why = "DECLARED", None
        elif node.args or star_kw:
            parts = []
            if star_pos:
                parts.append("passes *args, so whether a positional reaches "
                             "the field is not decidable here")
            elif node.args:
                parts.append(f"passes {len(node.args)} positional argument(s), "
                             f"and this rule does not read a positional as a "
                             f"declaration of any field")
            if star_kw:
                parts.append("passes **kwargs, so whether the mapping carries "
                             "the field is not decidable here")
            verdict, why = "UNDECIDABLE", " and ".join(parts)
        else:
            verdict, why = "OMITTED", None
        out.append({"line": node.lineno,
                    "kwarg_count": len([a for a in kwnames if a is not None]),
                    "positional_count": len(node.args),
                    "verdict": verdict, "undecidable_reason": why})
    return out


def audit(root: Path) -> Dict[str, Any]:
    """Scan ``root`` and judge every construction site under it.

    A file that does not contain the literal token is not parsed: under a
    name-keyed rule it cannot hold a site, so parsing it would change no
    verdict. A file that DOES contain it and will not parse is REPORTED, never
    dropped — dropping removes a site from the denominator while the verdict
    still counts the file as scanned, which is this gate's own defect class one
    level up.
    """
    files, enumeration = iter_source_files(root)
    sites: List[Dict[str, Any]] = []
    definitions: List[str] = []
    unparseable: List[Dict[str, str]] = []
    mentioning = 0
    for path in files:
        try:
            text = path.read_text(errors="replace")
        except OSError as exc:
            unparseable.append({"file": str(path),
                                "error": f"{type(exc).__name__}: {exc}"})
            continue
        if CONTRACT_CLASS not in text:
            continue
        mentioning += 1
        with warnings.catch_warnings():
            # Compiling someone else's module re-emits ITS warnings on this
            # gate's stderr. Nothing this gate DECIDES is suppressed:
            # SyntaxError is caught and REPORTED.
            warnings.simplefilter("ignore", SyntaxWarning)
            try:
                tree = ast.parse(text, filename=str(path))
            except (SyntaxError, ValueError) as exc:
                unparseable.append({"file": str(path),
                                    "error": f"{type(exc).__name__}: {exc}"})
                continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == CONTRACT_CLASS:
                definitions.append(f"{path}:{node.lineno}")
        for s in sites_in(tree):
            sites.append(dict(s, file=str(path)))
    sites.sort(key=lambda s: (s["file"], s["line"]))
    return {"root": str(root), "files_scanned": len(files),
            "files_mentioning": mentioning, "unparseable": unparseable,
            "enumeration": enumeration, "sites": sites,
            "definitions": sorted(definitions),
            "examined": len(sites),
            "omitted": [s for s in sites if s["verdict"] == "OMITTED"],
            "undecidable": [s for s in sites
                            if s["verdict"] == "UNDECIDABLE"]}


def name_is_not_one_class(rep: Dict[str, Any]) -> Optional[str]:
    """The ONE precondition, checked BEFORE any site is judged. Refusal only.

    This rule keys on a NAME, and a name is only a class while exactly one
    class answers to it. With none, the class was renamed and the contract is
    stale — a ratchet that reports PASS after its subject is gone is how this
    kind of gate dies quietly green. With more than one, a site could be
    constructing either, and judging it by THIS contract reports a defect
    against a class that may have no such field: a wrong verdict on code that
    works, which is the one thing this file may not do. Measured: the name
    denotes exactly one class in this venue.

    It cannot certify anything and it cannot report a defect. rc 2 either way.
    """
    seen = rep.get("definitions") or []
    if len(seen) == 1:
        return None
    if not seen:
        return (f"class {CONTRACT_CLASS} is not DEFINED anywhere under the "
                f"scanned root — it was renamed (and this contract is stale) "
                f"or the root is wrong. This gate did NOT check "
                f"{CONTRACT_CLASS}.{CONTRACT_FIELD}.")
    return (f"the name {CONTRACT_CLASS} denotes {len(seen)} different classes "
            f"under the scanned root ({', '.join(seen[:5])}"
            f"{', ...' if len(seen) > 5 else ''}). This rule keys on a name, so "
            f"it cannot tell which one a call constructs, and judging a site by "
            f"this contract could report a defect against a class that has no "
            f"such field. Give one of them a different name, or re-point the "
            f"contract.")


def refusals(rep: Dict[str, Any]) -> List[str]:
    """Why this run has NOT certified the tree. Empty means it has."""
    out: List[str] = []
    if rep["unparseable"]:
        out.append(
            f"{len(rep['unparseable'])} file(s) naming {CONTRACT_CLASS} would "
            f"not parse, so part of the venue was never read and a clean "
            f"answer over the rest would not be a clean answer: "
            + "; ".join(f"{u['file']} ({u['error']})"
                        for u in rep["unparseable"][:5])
            + ("; ..." if len(rep["unparseable"]) > 5 else ""))
    if rep["undecidable"]:
        out.append(
            f"{len(rep['undecidable'])} construction site(s) of "
            f"{CONTRACT_CLASS} are outside what this rule decides (listed "
            f"above). They are NOT defects and NOT clean: this run cannot say "
            f"whether they state {CONTRACT_FIELD!r}.")
    if not rep["sites"]:
        out.append(
            f"0 construction sites of {CONTRACT_CLASS} were found under the "
            f"scanned root, so the rule was applied to nothing. A clean result "
            f"over an empty scan is not a clean result.")
    return out


def main(argv: Optional[List[str]] = None) -> int:
    here = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("root", nargs="?", default=str(here.parent),
                    help="tree to scan (default: the shipped plugin root)")
    ap.add_argument("--json", dest="json_out")
    a = ap.parse_args(argv)

    root = Path(a.root).expanduser()
    if not root.is_dir():
        print(f"[REFUSE] staged_pdk_declares_tapcell_master_check: not a "
              f"directory: {root}")
        return RC_CANNOT_CHECK
    root = root.resolve()

    rep = audit(root)
    if a.json_out:
        try:
            Path(a.json_out).write_text(json.dumps(rep, indent=2) + "\n")
        except OSError as exc:
            print(f"[REFUSE] cannot write --json: {exc}")
            return RC_CANNOT_CHECK

    print(f"staged_pdk_declares_tapcell_master_check: {rep['files_scanned']} "
          f"shipped non-test .py file(s) scanned under {root} "
          f"[{rep['enumeration']}]; {rep['files_mentioning']} name "
          f"{CONTRACT_CLASS}; {len(rep['definitions'])} define it; "
          f"{rep['examined']} construction site(s)")
    print(f"  contract         : {CONTRACT_CLASS}.{CONTRACT_FIELD}")
    for u in rep["unparseable"]:
        print(f"  UNPARSEABLE      : {u['file']} — {u['error']}. NOT examined, "
              f"so this run did not read it.")
    for s in rep["undecidable"]:
        print(f"  UNDECIDABLE      : {s['file']}:{s['line']} "
              f"{s['undecidable_reason']}. NOT reported as a defect and NOT "
              f"counted clean.")

    stale = name_is_not_one_class(rep)
    if stale is not None:
        print(f"[REFUSE] {stale}")
        print("   CANNOT-CHECK is not PASS: this run has NOT certified "
              "anything.")
        return RC_CANNOT_CHECK

    if rep["omitted"]:
        for s in rep["omitted"]:
            print(f"[FAIL] {s['file']}:{s['line']} constructs {CONTRACT_CLASS} "
                  f"with {s['positional_count']} positional and "
                  f"{s['kwarg_count']} keyword argument(s) and never states "
                  f"{CONTRACT_FIELD!r}, so it INHERITS the class default. That "
                  f"default is a value with a meaning, not 'unset', and an "
                  f"omission is indistinguishable from a deliberate "
                  f"declaration of it. State it explicitly — the derived "
                  f"value, or the sentinel if that is genuinely what this site "
                  f"means.")
        print(f"   {len(rep['omitted'])} site(s) inherit a load-bearing "
              f"sentinel default in silence.")
        return RC_FAIL

    blockers = refusals(rep)
    if blockers:
        for b in blockers:
            print(f"[REFUSE] {b}")
        print("   CANNOT-CHECK is not PASS: this run has NOT certified "
              "anything.")
        return RC_CANNOT_CHECK

    print(f"[PASS] all {rep['examined']} construction site(s) of "
          f"{CONTRACT_CLASS} state {CONTRACT_FIELD!r} explicitly, and none "
          f"omits it.")
    return RC_PASS


if __name__ == "__main__":
    raise SystemExit(main())
