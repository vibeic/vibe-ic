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
    hdl_declaration_scan_strips_comments_check.py [--root .] [--json OUT]
                                                  [--write-baseline]

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


def _strips_comments_inline(call: ast.Call) -> bool:
    """`re.sub(<a comment pattern>, ...)` — a strip written in place."""
    fn = call.func
    if not (isinstance(fn, ast.Attribute) and fn.attr == "sub" and call.args):
        return False
    src = "".join(n.value for n in ast.walk(call.args[0])
                  if isinstance(n, ast.Constant) and isinstance(n.value, str))
    return bool(_COMMENT_PAT.search(src.replace("\\", "")))


def declares_hdl(pattern: str) -> bool:
    """Does this regex SOURCE name an HDL declaration keyword?

    Path-token occurrences are blanked FIRST, on the ORIGINAL pattern: `_META`
    blanks the class brackets, so after it runs a path separator can no longer
    be told from whitespace.
    """
    p = _KW_PATH_TOKEN.sub(lambda m: " " * len(m.group(0)), pattern or "")
    return bool(_KW.search(_META.sub(" ", p)))


def _pattern_of(node: ast.AST) -> Optional[str]:
    if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == "compile" and node.args):
        return None
    parts = [n.value for n in ast.walk(node.args[0])
             if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    return "".join(parts) if parts else None


def declaration_regexes(tree: ast.Module) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for n in ast.walk(tree):
        if isinstance(n, ast.Assign) and len(n.targets) == 1 \
                and isinstance(n.targets[0], ast.Name):
            p = _pattern_of(n.value)
            if p and declares_hdl(p):
                out[n.targets[0].id] = p
    return out


def stripped_locals(fn: ast.AST) -> Set[str]:
    """Locals whose value passed through a stripper, transitively.

    Per-NAME, which is the point: a sibling variable being stripped does not
    make this one safe.

    Three binding forms carry a value into a name, and all three propagate:
    assignment, a `for` target, and a comprehension target. Handling only
    assignment made `for line in stripped.splitlines():` read as unstripped,
    because the loop variable never inherited the iterable's status -- a false
    positive on correct code, and the common shape for a line-by-line scan.
    """
    ok: Set[str] = set()

    def _from_stripper(value: ast.AST) -> bool:
        """Does this expression derive from a stripper, or from a safe name?"""
        for sub in ast.walk(value):
            if isinstance(sub, ast.Call):
                try:
                    fname = ast.unparse(sub.func)
                except Exception:
                    fname = ""
                if _STRIPPER.search(fname) or _strips_comments_inline(sub):
                    return True
            if isinstance(sub, ast.Name) and sub.id in ok:
                return True
        return False

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
        for n in ast.walk(fn):
            names, value = _bindings(n)
            if not names or value is None:
                continue
            if all(t in ok for t in names):
                continue
            if _from_stripper(value):
                ok.update(names)
                grew = True
    return ok


def scan_source(src: str, label: str) -> List[str]:
    """`label::function::REGEX(arg)` for every unstripped declaration scan."""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []
    regs = declaration_regexes(tree)
    if not regs:
        return []
    out: List[str] = []
    for fn in [x for x in ast.walk(tree)
               if isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef))]:
        safe = stripped_locals(fn)
        for n in ast.walk(fn):
            if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and n.func.attr in _SCAN
                    and isinstance(n.func.value, ast.Name)):
                continue
            if n.func.value.id not in regs or not n.args:
                continue
            arg = n.args[-1] if n.func.attr in ("sub", "split") else n.args[0]
            if isinstance(arg, ast.Name) and arg.id not in safe:
                out.append(f"{label}::{fn.name}::{n.func.value.id}({arg.id})")
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
_OFFENDER_REGISTER = {
    "design_one_shot_runner::_chip_top_resolve_excluded_variant_params::"
    "pat(param_block)":
        "OWNER: lane czaes1. ADDED BY v1.17.85 (af94a508b). The same function is "
        "also the polarity gate's offender — two independent hygiene gates, one "
        "function, which is a stronger signal about that landing than either "
        "gate gives alone. Delete this entry in the commit that fixes it.",
    "lec_run::lec_proved_points_from_output::_INDUCT_FOUND_RE(raw)":
        "OWNER: lane czlecresume. ADDED BY v1.17.62 (364d3cc75). Also the "
        "polarity gate's offender — same pairing as above. Delete this entry in "
        "the commit that fixes it.",
    "phase1_doc_one_shot_runner::_doc_module_name_label_or_inline::"
    "_RE_DOC_TOP_MODULE_TOP_IS_NAMED(text)":
        "OWNER: lane czadcl10, which owns the phase-1 doc path. The function "
        "dates from v1.3.12 (f3172263f); what changed is the text that now "
        "reaches it. Delete this entry in the commit that fixes it.",
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
    ap.add_argument("--root", default=None)
    ap.add_argument("--json", dest="json_out")
    ap.add_argument("--ratchet", action="store_true",
                    help="verdict by MEMBERSHIP against the offender register: "
                         "fail when an offender is unregistered (a landing "
                         "added one) or when an entry outlived its offender")
    ap.add_argument("--baseline", default=None)
    ap.add_argument("--write-baseline", action="store_true")
    a = ap.parse_args(argv)

    root = Path(a.root).resolve() if a.root else Path(__file__).resolve().parents[1]
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
