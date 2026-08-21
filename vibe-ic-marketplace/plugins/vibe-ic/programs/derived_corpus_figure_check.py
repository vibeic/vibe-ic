#!/usr/bin/env python3
"""A checker's docstring may not state a corpus funnel it does not compute.

    "This clause alone takes 113 syntactic matches down to 13."

That sentence justifies a scope decision with two numbers. The second one
reproduces exactly. The first one reproduces under no reading of the predicate
it describes -- reconstructing the same clause against b85d68ac on 2026-08-05
measured 41, 49, 71, 440 and 595, and none of them is 113. The conclusion the
sentence supports is correct; the sentence is still not evidence, because a
reader cannot get 113 back out of the program.

Those five reconstruction figures are PINNED to the date and commit above, by
this file's own rule. They record what was measured when this gate was argued
for. They are not a claim about any later tree, and nothing here maintains
them.

That is the whole rule. A stated justification must be checkable. A funnel
figure is checkable exactly when the program derives it, and a program that
walks the tree can always derive a figure about the tree.

WHAT BLOCKS
-----------
1. ``funnel-literal`` -- a module that walks a tree states, in its module
   docstring, two population figures joined by an explicit narrowing relation
   ("N ... down to M", "narrows N to M", "N -> M"), with neither a
   ``{figure:}`` placeholder nor a pinning handle anywhere in that paragraph.
   The narrowing relation is what makes this form unambiguous: it is a claim
   about THIS predicate's selectivity over THIS tree, and nothing else is
   spelled that way.

2. ``figure-unbound`` -- a ``{figure:NAME}`` with no binding. A placeholder
   that cannot render is worse than a literal: it reads as derived.

3. ``figure-unused`` -- a declared binding no docstring names. Dead bindings
   rot silently and then get cited.

4. ``figure-uncomputable`` -- a binding that raises, or returns a non-int,
   against the live root. This is the anti-drift core: it is what makes the
   placeholder a promise the tree keeps rather than a promise the author made.

5. ``half-adopted`` -- a bare population integer inside a paragraph that also
   carries a placeholder. Half a derived table is a table a reader will trust
   whole.

WHAT THIS PROGRAM CANNOT DECIDE, STATED AS A BOUNDARY AND NOT AS A GAP
-----------------------------------------------------------------------
It cannot decide whether a stated figure is a claim about the corpus NOW or a
record of a measurement THEN. Both are the same token sequence:

    "there are 464 tracked JSON files carrying a personal home path"   -- now
    "Measured, both ways, before choosing: population 533 ..."         -- then

The first must be derived or it will quietly stop being true. The second must
NOT be derived -- re-deriving it would destroy the record of what was actually
measured when the decision was taken, which is the only thing that makes the
decision reviewable. Tense, aspect and the intent behind a past-tense verb are
not in the AST, and a guard that guessed would be wrong in the direction that
erases evidence.

So the third clause here is ADVISORY and says so in its own output. It reports
the population it cannot triage and hands it to a human, rather than blocking
on a judgement it is not entitled to make or -- worse -- narrowing its
predicate until the count reaches zero and calling that clean.

The same boundary bounds the wider rule this file was written for. "A universal
claim used to justify a scope exclusion must be falsifiable against the corpus"
is NOT implementable here. Falsifying "a scalar value has no present-but-empty
state" requires mapping an English noun phrase onto the set of AST sites some
other clause excludes, and then deciding whether a runtime harm follows for
each -- from an annotation, which does not carry runtime semantics. Three
natural-language steps, none of them decidable. What IS decidable, and what
this file does, is the numeric half: a figure offered in support of such a
claim must reproduce.

DELIBERATELY NOT PRESENT: any list of file or function names. Every clause is a
property of shape or of a declared binding, so a site stops being reported only
by actually changing.

Exit codes
----------
    0  no blocking finding (advisory findings do not change this)
    1  at least one blocking finding
    2  bad usage, unreadable root, or an EMPTY population -- "no funnel found"
       over zero files is not a clean result, it is the absence of one, and the
       umbrella that aggregates this reads the exit code, not the prose
       (vibe-ic#564). This gate is subject to its own rule.

chip-AGNOSTIC: reads Python source and counts files. No PDK, vendor, process or
design literal appears here or can affect any result.
"""
from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _derived_corpus_figure import (  # noqa: E402
    FIGURES_ATTR,
    PIN_RE,
    PLACEHOLDER_RE,
    CorpusFigures,
    FigureError,
    anchored_figures,
    paragraphs,
    placeholder_names,
    population_figures,
    render,
)

RC_CLEAN, RC_FOUND, RC_USAGE = 0, 1, 2

#: A module that walks a tree can derive a figure about that tree. One that
#: does not, cannot, and is out of scope for the blocking funnel clause.
_WALKS_A_TREE = re.compile(r"\.rglob\(|\.glob\(|os\.walk\(|\.iterdir\(")

# THE POPULATION-FIGURE VOCABULARY NOW LIVES IN THE SEAM (vibe-ic#961).
#
# It was defined here, and this file was the only consumer -- until a second
# consumer appeared: the 63x8 census generator, which must report how many
# stated figures in the documents it guards are NOT derived. A coverage report
# that graded "is this a corpus figure?" by a second, private copy of these
# regexes could disagree with the gate whose coverage it reports, and a
# disagreement between a gate and its own coverage line is precisely what a
# coverage line exists to remove.
#
# The names below are re-bound, not re-implemented: `_PIN` and
# `population_figures` keep working for every existing caller and test.
_PIN = PIN_RE

#: An anchored figure (``63<!--figure:name-->``) is DERIVED, and
#: `population_figures` already drops it. Named here so a reader of the clauses
#: below can see why an anchored number is never reported as unbound.
_ANCHORED = anchored_figures

#: An explicit narrowing relation between two figures. This -- not the mere
#: presence of two numbers -- is what identifies a self-selectivity funnel.
#: Stays HERE, not in the seam: it is a property of clause 1's shape, and no
#: anchor adopter needs it.
_NARROWING = re.compile(
    r"\b(?:down\s+to|narrow(?:s|ed|ing)?\s+(?:it\s+|them\s+)?to|"
    r"reduc(?:es|ed|ing)?\s+(?:it\s+|them\s+)?to|cut(?:s|ting)?\s+(?:it\s+)?to|"
    r"takes?\s+.{0,60}?\s+to|leaves?|leaving)\b|(?:->|-->|→)",
    re.IGNORECASE | re.DOTALL)

#: A LOCATOR -- a glob, a `git ls-files` -- looks like a pin and is not one. It
#: tells a reader how to re-take the measurement; it does not say the figure
#: still holds. MEASURED, not assumed: `l_doc_path_portability_check` states
#: "which is exactly the 2554-document L corpus" one line under the very glob
#: that produces it, and that glob returns 2582 on this tree. A locator-backed
#: figure went stale in the presence of its own locator, so a locator does not
#: exempt. Kept as a named pattern because the ADVISORY tier reports it.
_LOCATOR = re.compile(
    r"\bgit\s+(?:ls-files|diff|log|grep|rev-parse|show)\b"
    r"|\*\*/|\*_[a-z]+\.py|\*\.[a-z]{1,5}\b",
    re.IGNORECASE)


# ------------------------------------------------------------------ helpers --
def all_docstrings(tree: ast.AST) -> List[Tuple[str, str, int]]:
    """(owner, docstring, lineno) for the module and every def/class."""
    out: List[Tuple[str, str, int]] = []
    doc = ast.get_docstring(tree)
    if doc:
        out.append(("<module>", doc, 1))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            d = ast.get_docstring(node)
            if d:
                out.append((node.name, d, node.lineno))
    return out


def _assigns_figures(tree: ast.AST) -> bool:
    """True only for a MODULE-LEVEL ``CORPUS_FIGURES = ...`` binding.

    Decided from the AST, not from a substring. A test module that merely
    quotes the name inside a fixture string mentions it too, and importing a
    test module to discover it declared nothing is a side effect the sweep has
    no business causing.
    """
    for node in getattr(tree, "body", []):
        targets = (node.targets if isinstance(node, ast.Assign)
                   else [node.target] if isinstance(node, ast.AnnAssign) else [])
        if any(isinstance(t, ast.Name) and t.id == FIGURES_ATTR for t in targets):
            return True
    return False


def declared_figures(path: Path) -> Optional[CorpusFigures]:
    """Import ``path`` and return its ``CORPUS_FIGURES``, or None if it has none.

    Only modules that actually BIND the attribute at module level are imported,
    so the sweep does not execute the corpus to find out that it declared
    nothing.
    """
    try:
        src = path.read_text(errors="replace")
        if not _assigns_figures(ast.parse(src)):
            return None
    except (OSError, SyntaxError):
        return None
    spec = importlib.util.spec_from_file_location(f"_dcf_{path.stem}", path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        return None
    value = getattr(module, FIGURES_ATTR, None)
    return value if isinstance(value, CorpusFigures) else None


# ------------------------------------------------------------------- clauses --
def _finding(path: str, line: int, rule: str, detail: str,
             blocking: bool, **extra: Any) -> Dict[str, Any]:
    f = {"file": path, "line": line, "rule": rule, "detail": detail,
         "blocking": blocking}
    f.update(extra)
    return f


def scan_module(path: Path, rel: str, root: Path,
                evaluate: bool) -> List[Dict[str, Any]]:
    try:
        src = path.read_text(errors="replace")
        tree = ast.parse(src)
    except (OSError, SyntaxError):
        return []

    out: List[Dict[str, Any]] = []
    docs = all_docstrings(tree)
    walks = bool(_WALKS_A_TREE.search(src))

    # -- clauses 2/3/4/5: the declared-binding contract ---------------------
    named: List[str] = []
    for _owner, doc, lineno in docs:
        named.extend(n for n in placeholder_names(doc) if n not in named)

    figures = declared_figures(path) if (named or _assigns_figures(tree)) else None

    if named and figures is None:
        out.append(_finding(
            rel, 1, "figure-unbound",
            f"docstring names {', '.join('{figure:%s}' % n for n in named)} but "
            f"no importable {FIGURES_ATTR} was found (absent, not a "
            f"CorpusFigures, or the module raised on import); the placeholder "
            f"reads as derived and renders to nothing", True, figures=named))
    elif figures is not None:
        unbound = [n for n in named if n not in figures]
        if unbound:
            out.append(_finding(
                rel, 1, "figure-unbound",
                "no binding for "
                + ", ".join("{figure:%s}" % n for n in unbound), True,
                figures=unbound))
        unused = sorted(n for n in figures if n not in named)
        if unused:
            out.append(_finding(
                rel, 1, "figure-unused",
                "declared but named by no docstring: " + ", ".join(unused), True,
                figures=unused))
        if evaluate:
            for name in sorted(n for n in named if n in figures):
                try:
                    figures.evaluate(name, root)
                except FigureError as exc:
                    out.append(_finding(rel, 1, "figure-uncomputable",
                                        str(exc), True, figures=[name]))
                except Exception as exc:                       # noqa: BLE001
                    out.append(_finding(
                        rel, 1, "figure-uncomputable",
                        f"binding for {{figure:{name}}} raised "
                        f"{type(exc).__name__}: {exc}", True, figures=[name]))

        # clause 5 -- no half-derived paragraph
        for _owner, doc, lineno in docs:
            for offset, para in paragraphs(doc):
                if not PLACEHOLDER_RE.search(para):
                    continue
                bare = population_figures(PLACEHOLDER_RE.sub("", para))
                if bare:
                    out.append(_finding(
                        rel, lineno + offset - 1, "half-adopted",
                        "paragraph renders some figures and types others: "
                        + "; ".join(sorted(set(bare))), True, literals=sorted(set(bare))))

    # -- clauses 1 and advisory: module docstring only ----------------------
    if walks and docs and docs[0][0] == "<module>":
        paras = paragraphs(docs[0][1])
        for i, (offset, para) in enumerate(paras):
            # A pin is routinely written in the section HEADING and the figures
            # in the block under it ("THE CLASS (vibe-ic#447) ... <blank> ...
            # <evidence table>"). Splitting on blank lines would make the pin
            # invisible to its own evidence, so one paragraph of look-back is
            # part of the rule, not a loosening of it.
            scope = para if i == 0 else paras[i - 1][1] + "\n" + para
            if PLACEHOLDER_RE.search(scope) or _PIN.search(scope):
                continue
            figs = population_figures(para)
            if len(figs) < 2:
                continue
            if _NARROWING.search(para):
                out.append(_finding(
                    rel, offset, "funnel-literal",
                    "module docstring states a selectivity funnel over the tree "
                    "this module walks, as literals: " + " -> ".join(figs)
                    + " -- nothing recomputes it, and no pin says when it was "
                      "true", True, literals=figs))
            else:
                out.append(_finding(
                    rel, offset, "unbound-population-figure",
                    "population figures with neither a derivation nor a pin: "
                    + "; ".join(figs)
                    + (" (a locator is present; a locator is not a pin)"
                       if _LOCATOR.search(scope) else "")
                    + " -- ADVISORY: this program cannot tell a claim about the "
                      "corpus NOW from a record of a measurement THEN",
                    False, literals=figs))
    return out


def sweep(root: Path, programs: Path, skip: Tuple[str, ...] = (),
          evaluate: bool = True) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for path in sorted(programs.rglob("*.py")):
        rel = path.relative_to(programs).as_posix()
        if any(rel == s or rel.startswith(s.rstrip("/") + "/") for s in skip):
            continue
        out.extend(scan_module(path, rel, root, evaluate))
    return out


# ----------------------------------------------------------------------- CLI --
def _render_module(path: Path, root: Path) -> Tuple[int, str]:
    figures = declared_figures(path)
    if figures is None:
        return RC_USAGE, (f"[ERROR] {path.name} declares no {FIGURES_ATTR}")
    try:
        tree = ast.parse(path.read_text(errors="replace"))
    except (OSError, SyntaxError) as exc:
        return RC_USAGE, f"[ERROR] {path}: {exc}"
    doc = ast.get_docstring(tree) or ""
    try:
        return RC_CLEAN, render(doc, figures.evaluate_all(root))
    except FigureError as exc:
        return RC_FOUND, f"[FAIL] {path.name}: {exc}"


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    here = Path(__file__).resolve().parent
    ap.add_argument("--root", default=str(here.parent),
                    help="plugin root passed to every figure binding "
                         "(default: the parent of this programs/ dir)")
    ap.add_argument("--programs", default=str(here),
                    help="directory to sweep (default: this programs/ dir)")
    ap.add_argument("--skip", action="append", default=[],
                    help="relative path prefix left out of the sweep; reported "
                         "in the JSON so a narrowed sweep cannot read as a full one")
    ap.add_argument("--no-evaluate", action="store_true",
                    help="skip clause 4 (do not call the bindings)")
    ap.add_argument("--explain", metavar="MODULE",
                    help="render MODULE's docstring with live figures and exit")
    ap.add_argument("--figures", metavar="MODULE",
                    help="print MODULE's figures as JSON and exit")
    ap.add_argument("--json", help="write the full finding list here")
    args = ap.parse_args(argv)

    root, programs = Path(args.root).resolve(), Path(args.programs).resolve()
    if not programs.is_dir():
        print(f"[ERROR] derived_corpus_figure_check: no such programs dir: "
              f"{programs}", file=sys.stderr)
        return RC_USAGE

    if args.explain or args.figures:
        name = args.explain or args.figures
        target = Path(name) if Path(name).is_file() else programs / f"{name}.py"
        if not target.is_file():
            print(f"[ERROR] no such module: {name}", file=sys.stderr)
            return RC_USAGE
        if args.figures:
            figures = declared_figures(target)
            if figures is None:
                print(f"[ERROR] {target.name} declares no {FIGURES_ATTR}",
                      file=sys.stderr)
                return RC_USAGE
            print(json.dumps(figures.evaluate_all(root), indent=2, sort_keys=True))
            return RC_CLEAN
        rc, text = _render_module(target, root)
        print(text)
        return rc

    swept = sum(1 for _ in programs.rglob("*.py"))
    if swept == 0:
        # vibe-ic#564: a gate that read NOTHING must not exit 0. "No funnel
        # found" over an empty population is not a clean result, it is the
        # absence of a result, and the umbrella that aggregates this reads the
        # exit code rather than the prose.
        print(f"[ERROR] derived_corpus_figure_check: 0 Python file(s) under "
              f"{programs} — refusing to report a verdict over an empty "
              f"population", file=sys.stderr)
        return RC_USAGE

    findings = sweep(root, programs, tuple(args.skip), not args.no_evaluate)
    blocking = [f for f in findings if f["blocking"]]
    advisory = [f for f in findings if not f["blocking"]]
    adopters = sorted({f["file"] for f in findings if f["rule"].startswith("figure-")})

    if args.json:
        Path(args.json).write_text(json.dumps({
            "rule": "a-stated-justification-must-be-checkable",
            "programs_root": str(programs), "figure_root": str(root),
            "python_files_under_root": swept,
            "skipped_prefixes": list(args.skip),
            "evaluated_bindings": not args.no_evaluate,
            "findings": findings, "blocking_count": len(blocking),
            "advisory_count": len(advisory),
        }, indent=2))

    head = (f"derived_corpus_figure_check: {swept} file(s) under {programs}"
            + (f" (skipped: {', '.join(args.skip)})" if args.skip else ""))
    print(head)
    for f in blocking:
        print(f"  [FAIL] {f['file']}:{f['line']}  {f['rule']}")
        print(f"         {f['detail']}")
    if advisory:
        print(f"  [ADVISORY] {len(advisory)} unbound population figure(s) in "
              f"{len({f['file'] for f in advisory})} module(s) — reported, never "
              f"blocking: this program cannot tell a claim about the corpus NOW "
              f"from a record of a measurement THEN.")
        for f in advisory:
            print(f"      {f['file']}:{f['line']}  {'; '.join(f['literals'])}")
    if adopters:
        print(f"  bindings checked in: {', '.join(adopters)}")

    if blocking:
        print(f"[FAIL] derived_corpus_figure_check: examined {swept} file(s), "
              f"{len(blocking)} stated figure(s) that nothing recomputes")
        return RC_FOUND
    print(f"[PASS] derived_corpus_figure_check: examined {swept} file(s), no "
          f"unrecomputed corpus funnel ({len(advisory)} advisory)")
    return RC_CLEAN


if __name__ == "__main__":
    sys.exit(main())
