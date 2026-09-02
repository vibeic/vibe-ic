#!/usr/bin/env python3
"""Refusals that do not name the channel a reader would fix them through.

ENFORCEMENT: CENSUS, not a gate. It reports counts and exits 0. `--strict`
restores a refusing exit for a caller who deliberately wants one, and NOTHING
in the flow wires it that way. The population it reports is overwhelmingly
PRE-EXISTING -- 273 of 300 sites on the tree it was written against -- and a
rule whose first act is to block main is a re-baselining argument, not a
finding. The count is the argument. This mirrors, deliberately, the contract
`checker_population_is_structural_not_filename_shaped_census.py` already sets
for the same situation. Kept in the first 4 kB: `declared_intent` reads only
`text[:4000]`.

WHY THIS EXISTS -- MEASURED, AND THE BILL WAS A FALSE REPORT
============================================================
`submission_template_check`'s NO_TEMPLATE_WITHOUT_REASON refused an absent
operator template and named its FLOOR and nothing else -- not the file the
design supplies the reason in, not the key, and not the fact that the gate had
ALREADY read the design's own declaration. On disk beside it sat
`SELF_TAPEOUT.txt`, written by that same step's generator, saying the design
targets no shuttle operator. A careful measurer concluded the gate had never
read it and published "no chip-path step can reach PASS on a self-tape-out" --
false; the route was reachable the whole time -- together with a patch that
would have deleted two guards the suite pins on purpose.

A REFUSAL THAT DISCLOSES NOTHING PRODUCES FALSE REPORTS ABOUT ITSELF. That is
the same failure `flow-change-acceptance` criterion 6 names for a silent
DECLINE; this is its other half, on the REFUSE path, and until now no program
measured it.

THE POPULATION IS DERIVED FROM SHAPE, NEVER FROM A NAME
=======================================================
A definition keyed on a message prefix would be blind to every other spelling.
Measured on this tree: `[REFUSED]` is printed at 11 sites in 8 files, out of
1058 bracketed-token print sites across 104 distinct tokens. A prefix rule
would have seen ~1% of the printed population and none of the record one.

So a REFUSAL SITE is recognised by what the code BUILDS:

    a call whose first argument is a rule-id literal (ALL_CAPS_WITH_UNDERSCORES)
    and whose second argument is a message (str or f-string), where the result
    FLOWS somewhere a refusal flows -- appended/extended into a collection,
    returned, raised, assigned, or placed in a returned list.

No callee name appears in this program. On the tree it was written against the
shape matched 15 distinct builder names it was never told about, including
`Finding`, `Refusal`, `TierResult`, `_fail`, `_refuse`, `_refusal` and
`AssignmentError`. `setdefault`/`get`/`pop`/`format`/`replace` are excluded because those are
str/dict access and transform, not construction -- a rule-id literal is an
ordinary argument to them. That is the one name-shaped exclusion in the file
and every member is a builtin method.

KNOWN UNDER-COUNT, STATED RATHER THAN HIDDEN. This shape is the POSITIONAL
convention. Refusals built with keyword arguments, or as bare dict literals,
are NOT counted: measured, the builders in this tree carry 41 distinct
(first-param, second-param) signatures, so a dict-literal rule keyed on field
names would either miss most of them or sweep in every opcode table in the
repository (2349 dict literals carry an ALL-CAPS value beside a string). The
reported figure is a floor on the defect, never a total, and
`examined.population_shape` says so in the record.

THE CRITERION IS MECHANICAL, AND ANSWERED PER REFUSAL
=====================================================
A gate must not decide whether prose is "helpful". So a refusal NAMES ITS
REMEDY when its message text carries at least one of three things a reader can
act on:

    PATH   a path-shaped token that is a DECLARED PLACE IN THIS SYSTEM -- it is
           the value of a module-level string constant under `programs/`, or it
           appears in the canonical flow document, or it exists on disk. A
           path-shaped string that names nowhere buys nothing.
    KEY    a backtick-quoted dotted identifier: a key the design can fill.
    FLAG   a `--long-flag` the caller can pass.

MESSAGES ARE RENDERED, NOT GREPPED. The text is assembled from the f-string's
literal parts WITH module-level string constants resolved through their import
alias, because the remedy is usually named through a constant
(`f"...{ST.DESIGN_ANSWERS_REL}..."`) and a source-text grep would score exactly
the well-behaved refusals as silent. Anything not statically resolvable renders
as empty, which can only ever make a refusal look MORE silent than it is --
the conservative direction for a census reporting debt.

TWO FIGURES, AND NEITHER IS CALLED THE ANSWER
=============================================
    WIDE     PATH or KEY or FLAG.
    STRICT   KEY or FLAG only -- an actionable channel, not merely a location.
Reporting one number would hide that PATH is the loosest of the three: on the
tree this was written against, WIDE names 27 and STRICT names 6.

RC CONTRACT
===========
    0  the census ran (whatever it counted); with --strict, 0 only when no
       refusal in the population is silent
    1  --strict and at least one refusal names no remedy channel
    2  UNDETERMINED -- no programs directory, or nothing parsed. NOT a pass:
       an empty scan is not a clean one.
    3  bad invocation

chip-AGNOSTIC: pure AST over this repository's own sources. No vendor, foundry,
process node, SKU or design name appears, and none could affect the count.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _atomic_artefact import write_text as atomic_write_text  # noqa: E402

PROGRAM = "refusal_names_its_remedy_census"

#: A rule id: ALL_CAPS with at least one underscore. This is the identity half
#: of a refusal, and it is what separates a refusal from an ordinary two-string
#: call.
RULE_ID = re.compile(r"^[A-Z][A-Z0-9]*(_[A-Z0-9]+)+$")

#: A path-SHAPED token. Being path-shaped is not enough; `_resolves` decides.
PATH_TOKEN = re.compile(r"[A-Za-z0-9_.\-]+/[A-Za-z0-9_./\-*]+")

#: A key the design can fill, quoted the way this repository quotes them.
KEY_TOKEN = re.compile(r"`([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+)`")

#: A long flag a caller can pass.
FLAG_TOKEN = re.compile(r"(?<![\w-])--[a-z][a-z0-9-]{2,}")

#: str/dict ACCESS AND TRANSFORM, not construction. These are the one
#: name-shaped exclusion in this file, and they are named because a rule-id
#: literal is a perfectly ordinary argument to them:
#:     m.group(0).replace("LSB_FIRST", "LSB_first")   <- not a refusal
#: Every one is a builtin method of str or dict. Nothing domain-specific, and
#: nothing that could hide a refusal builder somebody wrote.
_NOT_BUILDERS = frozenset({"setdefault", "get", "pop", "format", "replace"})

_FLOW_REL = "flow/phase1_phase2_phase3.yaml"


def _is_message(node: ast.AST) -> bool:
    return isinstance(node, ast.JoinedStr) or (
        isinstance(node, ast.Constant) and isinstance(node.value, str))


def _module_constants(programs: Path) -> Tuple[Dict[str, Dict[str, str]],
                                               Dict[str, Dict[str, str]]]:
    """(per-module string constants, per-module import aliases).

    Both are needed to render `f"...{ST.DESIGN_ANSWERS_REL}..."` back into the
    path it actually prints.
    """
    consts: Dict[str, Dict[str, str]] = {}
    alias: Dict[str, Dict[str, str]] = {}
    for f in sorted(programs.glob("*.py")):
        try:
            tree = ast.parse(f.read_text(encoding="utf-8", errors="replace"))
        except (OSError, SyntaxError, ValueError):
            continue
        c: Dict[str, str] = {}
        for n in tree.body:
            if (isinstance(n, ast.Assign) and len(n.targets) == 1
                    and isinstance(n.targets[0], ast.Name)
                    and isinstance(n.value, ast.Constant)
                    and isinstance(n.value.value, str)):
                c[n.targets[0].id] = n.value.value
        consts[f.stem] = c
        a: Dict[str, str] = {}
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                for x in n.names:
                    a[x.asname or x.name] = x.name
            elif isinstance(n, ast.ImportFrom) and n.module:
                for x in n.names:
                    a[x.asname or x.name] = n.module
        alias[f.stem] = a
    return consts, alias


def render(node: ast.AST, module: str, consts, alias) -> str:
    """The statically-known text of a message expression.

    Unresolvable pieces render as "", which can only make a refusal look more
    silent than it is. For a census reporting debt that is the safe direction.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        out = []
        for part in node.values:
            if isinstance(part, ast.Constant) and isinstance(part.value, str):
                out.append(part.value)
            elif isinstance(part, ast.FormattedValue):
                out.append(render(part.value, module, consts, alias))
        return "".join(out)
    if isinstance(node, ast.Name):
        return consts.get(module, {}).get(node.id, "")
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        mod = alias.get(module, {}).get(node.value.id, node.value.id)
        return consts.get(mod, {}).get(node.attr, "")
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return (render(node.left, module, consts, alias)
                + render(node.right, module, consts, alias))
    if isinstance(node, ast.IfExp):
        return (render(node.body, module, consts, alias)
                + render(node.orelse, module, consts, alias))
    return ""


def _declared_places(consts) -> Set[str]:
    """Every path this system declares as a module constant. Derived, never typed.

    The other two ways a path can be a real place -- named in the flow document,
    or present on disk -- are tested directly in `_names_a_path`, because
    neither is enumerable into a set of reasonable size.
    """
    return {v for c in consts.values() for v in c.values() if "/" in v}


def _names_a_path(msg: str, places: Set[str], flow_text: str,
                  root: Optional[Path]) -> bool:
    """Does `msg` name a path that is a DECLARED PLACE in this system?

    SENTENCE PUNCTUATION IS NOT PART OF THE PATH, and forgetting that made this
    detector score its own positive control silent: `PATH_TOKEN` admits `.`, so
    a path ending a sentence is captured as `reports/phase1/x.json.` and
    matches nothing. Trailing punctuation is stripped, one character at a time,
    so `...x.json).` and `...x.json,` resolve too.
    """
    for m in PATH_TOKEN.finditer(msg):
        tok = m.group(0)
        while tok:
            if tok in places or (flow_text and tok in flow_text):
                return True
            if root is not None and (root / tok).exists():
                return True
            if tok[-1] not in ".,;:)]}'\"":
                break
            tok = tok[:-1]
    return False


def _flows_like_a_refusal(node: ast.AST, parent: Dict[ast.AST, ast.AST]) -> bool:
    p = parent.get(node)
    if isinstance(p, ast.Call) and getattr(p.func, "attr", None) in (
            "append", "extend", "add"):
        return True
    if isinstance(p, (ast.Return, ast.Raise, ast.Assign)):
        return True
    if isinstance(p, (ast.List, ast.Tuple)) and isinstance(
            parent.get(p), (ast.Return, ast.Call)):
        return True
    return False


def scan_programs(programs: Path, flow_text: str = "",
                  root: Optional[Path] = None) -> Tuple[List[dict], Dict[str, Any]]:
    """Every refusal site under `programs`, and whether each names a remedy."""
    if not programs.is_dir():
        raise FileNotFoundError(f"no such programs dir: {programs}")
    consts, alias = _module_constants(programs)
    places = _declared_places(consts)

    sites: List[dict] = []
    parsed = 0
    for f in sorted(programs.glob("*.py")):
        try:
            tree = ast.parse(f.read_text(encoding="utf-8", errors="replace"))
        except (OSError, SyntaxError, ValueError):
            continue
        parsed += 1
        parent: Dict[ast.AST, ast.AST] = {}
        for n in ast.walk(tree):
            for c in ast.iter_child_nodes(n):
                parent[c] = n
        for n in ast.walk(tree):
            if not (isinstance(n, ast.Call) and len(n.args) >= 2):
                continue
            a0, a1 = n.args[0], n.args[1]
            if not (isinstance(a0, ast.Constant) and isinstance(a0.value, str)
                    and RULE_ID.match(a0.value) and _is_message(a1)):
                continue
            if not _flows_like_a_refusal(n, parent):
                continue
            callee = getattr(n.func, "id", None) or getattr(n.func, "attr", None)
            if callee in _NOT_BUILDERS:
                continue
            msg = "".join(render(x, f.stem, consts, alias) for x in n.args[1:])
            has_path = _names_a_path(msg, places, flow_text, root)
            has_key = bool(KEY_TOKEN.search(msg))
            has_flag = bool(FLAG_TOKEN.search(msg))
            sites.append({
                "file": f.name, "line": n.lineno, "rule": a0.value,
                "builder": callee,
                "names_path": has_path, "names_key": has_key,
                "names_flag": has_flag,
                "wide": has_path or has_key or has_flag,
                "strict": has_key or has_flag,
                "rendered_chars": len(msg),
            })

    examined = {
        "files_parsed": parsed,
        "refusal_sites": len(sites),
        "files_with_a_refusal": len({s["file"] for s in sites}),
        "distinct_rule_ids": len({s["rule"] for s in sites}),
        "distinct_builders": len({s["builder"] for s in sites}),
        "declared_places_read": len(places),
        "names_remedy_wide": sum(1 for s in sites if s["wide"]),
        "names_remedy_strict": sum(1 for s in sites if s["strict"]),
        "silent_wide": sum(1 for s in sites if not s["wide"]),
        "silent_strict": sum(1 for s in sites if not s["strict"]),
        "by_detector": {
            "path": sum(1 for s in sites if s["names_path"]),
            "key": sum(1 for s in sites if s["names_key"]),
            "flag": sum(1 for s in sites if s["names_flag"]),
        },
        "population_shape": (
            "positional (RULE_ID, message) construction flowing into a "
            "collection/return/raise. Keyword-built and dict-literal refusals "
            "are NOT counted: this figure is a floor on the defect, never a "
            "total."),
    }
    return sites, examined


def _resolve(root: Path) -> Tuple[Path, str]:
    plugin = root
    if not (plugin / "programs").is_dir():
        cand = root / "vibe-ic-marketplace" / "plugins" / "vibe-ic"
        if (cand / "programs").is_dir():
            plugin = cand
    flow = plugin / _FLOW_REL
    return plugin, (flow.read_text(encoding="utf-8", errors="replace")
                    if flow.is_file() else "")


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description="CENSUS: refusals that name no remedy channel.")
    p.add_argument("root", nargs="?", default=".",
                   help="plugin root, or a checkout root containing one")
    p.add_argument("--programs", default=None,
                   help="scan this programs/ directory directly")
    p.add_argument("--strict", action="store_true",
                   help="refuse (rc 1) when any refusal in the population is "
                        "silent. NOT how the flow runs this.")
    p.add_argument("--json", nargs="?", const="-", default=None)
    p.add_argument("--list-silent", action="store_true")
    try:
        args = p.parse_args(argv)
    except SystemExit:
        return 3

    if args.programs:
        programs, flow_text, root = Path(args.programs), "", None
    else:
        root = Path(args.root)
        plugin, flow_text = _resolve(root)
        programs, root = plugin / "programs", plugin

    try:
        sites, examined = scan_programs(programs, flow_text, root)
    except (FileNotFoundError, NotADirectoryError) as exc:
        print(f"[UNDETERMINED] {PROGRAM}: {exc}. An empty scan is not a clean "
              f"one.", file=sys.stderr)
        return 2
    if not examined["files_parsed"]:
        print(f"[UNDETERMINED] {PROGRAM}: nothing under {programs} parsed, so "
              f"nothing was measured. An empty scan is not a clean one.",
              file=sys.stderr)
        return 2

    doc = {"program": PROGRAM, "examined": examined, "sites": sites}
    if args.json is not None:
        payload = json.dumps(doc, indent=2, ensure_ascii=False) + "\n"
        if args.json == "-":
            print(payload, end="")
        else:
            target = Path(args.json)
            target.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_text(target, payload)

    if args.list_silent:
        for s in sites:
            if not s["wide"]:
                print(f"  SILENT {s['file']}:{s['line']}  {s['rule']}")

    e = examined
    print(f"[CENSUS] {PROGRAM}: {e['silent_wide']} of {e['refusal_sites']} "
          f"refusal(s) name no remedy channel "
          f"({e['files_with_a_refusal']} file(s), {e['distinct_rule_ids']} "
          f"distinct rule id(s), {e['distinct_builders']} builder name(s) "
          f"matched by shape).")
    print(f"  WIDE  (path|key|flag): {e['names_remedy_wide']} name one, "
          f"{e['silent_wide']} do not")
    print(f"  STRICT (key|flag)    : {e['names_remedy_strict']} name one, "
          f"{e['silent_strict']} do not")
    print(f"  by detector: path={e['by_detector']['path']} "
          f"key={e['by_detector']['key']} flag={e['by_detector']['flag']}")
    print(f"  population shape: {e['population_shape']}")

    if args.strict and e["silent_wide"]:
        print(f"[FAIL] {PROGRAM} --strict: {e['silent_wide']} refusal(s) "
              f"disclose no channel a reader could fix them through.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
