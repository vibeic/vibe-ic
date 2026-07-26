#!/usr/bin/env python3
"""l_doc_symbolic_width_resolve.py — perform the parameter join the L-doc
corpus already has every input for, and nobody performs.

VERDICT SEMANTICS: this is a RESOLVER, not a gate. It never returns 1.
------------------------------------------------------------------
rc 0 = ran (whether or not anything resolved); rc 2 = I/O error. There is
deliberately no FAIL exit: the defect this addresses is NOT "somebody failed
to check", it is "everything needed was present and nobody joined it". A gate
for that already exists and blocks — `l1_pin_bus_width_actionable_check`.
Writing a second gate here would repeat verbatim the failure the measurement
recorded: a FAILing gate was written, the resolver never was.

The measured defect
------------------------------------------------------------------
ONE L-doc corpus carries both halves of a fact and joins neither:

    L9_INTEGRATION_SPEC.json  parameters[]  [{"name": "size",
                                              "default": "32", ...}]
    L1_DATASHEET.json         pin_table[]   [{"name": "x",
                                              "width": "N-bit(`[size-1:0]`,
                                                        parameter `size` ...)",
                                              "width_symbolic": "size-1:0",
                                              "msb": null, "lsb": null}]

`size` IS declared, with default 32, in the same corpus as the expression that
references it. `phase1_doc_one_shot_runner._parse_port_width` returns
`(None, None, 0, "size-1:0")` and its docstring says the textual form is kept
"so downstream consumers can resolve at elaboration time". Measured: no
consumer does. The sharpest form of it is that the string
`'...parameter `size` default 32)'` goes IN and the default comes back OUT
discarded. `l1_pin_bus_width_actionable_check.py:31` records the shape was
measured on ONE cell across THIRTEEN independent runs
(campaign_v1544..v1578); it never reads `parameters[]` at all — it only
demands SOME positive integer width. The gate exists; the join did not.

Consequence downstream: phase2 derives every port DECLARATION from
`L1.pin_table[]`, so an unresolvable width is emitted as a 1-bit scalar port —
a 32-bit multiplicand bus silently becomes a wire.

What this program does
------------------------------------------------------------------
For every entry ANYWHERE in the L-doc corpus that carries a symbolic width
expression (`width_symbolic`) and NO integer width, resolve that expression
against the parameter defaults the SAME corpus already declares, and write
back `width` / `msb` / `lsb` plus a `width_resolution` provenance record.

    width_symbolic "size-1:0"  +  parameters[{name: size, default: "32"}]
        -> hi = size-1 = 31, lo = 0
        -> width 32, msb 31, lsb 0

Nothing is invented. The parameter environment is DERIVED from the design's
own sibling L-docs; no design name, PDK name, vendor literal or pin literal
appears in this file. The arithmetic is `_specrtl_common._safe_eval_int` /
`_resolve_bracket_width` — a whitelisted-operator AST walk (never `eval()`,
handles `$clog2`) that already ships and that, before this program, nothing
outside `_specrtl_common.py` and one test imported. Its
`_parse_module_params` builds an env from VERILOG TEXT ONLY and is never fed
an L-doc's declared `parameters[]`; that was the entire missing link.

NEVER GUESS — the no-op rule
------------------------------------------------------------------
An entry is left BYTE-IDENTICAL whenever anything at all is uncertain:

  * any identifier in the expression has no resolvable default;
  * the same parameter name is declared with CONFLICTING defaults in two
    L-docs (ambiguous -> excluded from the environment entirely);
  * the expression is not a single `hi:lo` span (a ternary, a multi-colon
    bound, a bare identifier with no range);
  * either bound resolves negative, or the span resolves to <= 0 bits;
  * the entry ALREADY has an actionable integer width (then it is a no-op by
    definition — this program never overwrites a width that exists).

This mirrors `WIDTH_UNKNOWN` semantics exactly: unknown is UNKNOWN, never a
literal 1 and never a plausible-looking number. A resolver that guesses is
worse than no resolver, because the wrong width passes the gate.

NOT a duplicate of `verilog_width_resolve.py`
------------------------------------------------------------------
That module resolves parameterised widths out of BENCHMARK PROMPT TEXT
(CVDP/VerilogEval prose + a partial module header). This one joins two
structured fields of the L-doc JSON corpus. Different input medium, different
consumer; the shared arithmetic is deliberately taken from `_specrtl_common`
rather than adding a third evaluator.

WIRING — recorded debt, stated rather than implied
------------------------------------------------------------------
This program is a standalone CLI. It is NOT wired into
`phase1_one_shot_runner` / the flow definition by this change, because doing
so changes what a REAL run emits (port widths), and that is the flow owner's
call, not a side effect of adding the resolver. Declaring an intent is not
wiring it. Until it is wired, the join happens only when invoked.

Usage:
    python3 l_doc_symbolic_width_resolve.py <project_dir>            # dry run
    python3 l_doc_symbolic_width_resolve.py <project_dir> --apply
    python3 l_doc_symbolic_width_resolve.py <project_dir> --json OUT
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _path_layout as _pl              # noqa: E402
import _specrtl_common as _sc           # noqa: E402

PROGRAM = "l_doc_symbolic_width_resolve"

# Container keys under which an L-doc declares its parameters. Same synonym
# set `l9_completeness_check` already uses, so the resolver sees a parameter
# wherever an existing gate would call one present.
_PARAM_CONTAINERS = ("parameters", "params", "generics")
# Value keys carrying a parameter's DEFAULT. `default` is the shape every
# measured L8/L9 emitter writes; the other two are accepted so a differently
# spelled emitter is joined rather than silently skipped.
_PARAM_VALUE_KEYS = ("default", "default_value", "value")

# The one reference shape this program joins: the canonical field
# `_parse_port_width` already writes for a parametric bound.
_SYMBOLIC_KEY = "width_symbolic"
_PROVENANCE_KEY = "width_resolution"

_IDENT_RE = re.compile(r"[A-Za-z_]\w*")
# Names that are operators/functions in the expression grammar, not parameters.
_NON_PARAM_IDENTS = frozenset({"clog2"})

_MAX_NODES = 200_000                    # runaway-recursion guard


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


# ─────────────────────────────────────────────────────────────────────
# Corpus access
# ─────────────────────────────────────────────────────────────────────

def _l_doc_paths(project: Path) -> List[Path]:
    gd = _pl.generated_docs_dir(project)
    if not gd.is_dir():
        return []
    return sorted(p for p in gd.glob("L*.json") if p.is_file())


def _walk(node: Any, path: str, budget: List[int]):
    """Yield (container_or_entry, path) for every dict/list node, depth-first.

    `budget` is a one-element list used as a mutable counter so a pathological
    document cannot spin forever.
    """
    if budget[0] <= 0:
        return
    budget[0] -= 1
    if isinstance(node, dict):
        yield node, path
        for k, v in node.items():
            if isinstance(v, (dict, list)):
                yield from _walk(v, f"{path}.{k}" if path else str(k), budget)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            if isinstance(v, (dict, list)):
                yield from _walk(v, f"{path}[{i}]", budget)


# ─────────────────────────────────────────────────────────────────────
# Parameter environment, derived from the corpus itself
# ─────────────────────────────────────────────────────────────────────

def collect_parameter_exprs(docs: Dict[str, Any]) -> Tuple[
        Dict[str, List[Tuple[str, str]]], List[Dict[str, Any]]]:
    """Harvest `<name> = <default-expression>` from every L-doc.

    Returns (by_name, records) where by_name[NAME] is the list of
    (doc_filename, default_expression_as_text) sightings.
    """
    by_name: Dict[str, List[Tuple[str, str]]] = {}
    records: List[Dict[str, Any]] = []
    for fname, doc in docs.items():
        budget = [_MAX_NODES]
        for node, path in _walk(doc, "", budget):
            if not isinstance(node, dict):
                continue
            for key in _PARAM_CONTAINERS:
                seq = node.get(key)
                if not isinstance(seq, list):
                    continue
                for entry in seq:
                    if not isinstance(entry, dict):
                        continue
                    name = entry.get("name")
                    if not isinstance(name, str) or not name.strip():
                        continue
                    name = name.strip()
                    raw = None
                    for vk in _PARAM_VALUE_KEYS:
                        if vk in entry and entry[vk] is not None:
                            raw = entry[vk]
                            break
                    if raw is None:
                        continue
                    text = str(raw).strip()
                    if not text:
                        continue
                    by_name.setdefault(name, []).append((fname, text))
                    records.append({"name": name, "expr": text,
                                    "doc": fname,
                                    "at": f"{path}.{key}" if path else key})
    return by_name, records


def _sightings_values(sightings: List[Tuple[str, str]],
                      env: Dict[str, int]) -> Dict[int, List[str]]:
    values: Dict[int, List[str]] = {}
    for fname, text in sightings:
        v = _sc._safe_eval_int(text, env)
        if v is not None:
            values.setdefault(v, []).append(fname)
    return values


def _fixpoint(by_name: Dict[str, List[Tuple[str, str]]],
              excluded: Dict[str, Any]) -> Dict[str, int]:
    """Resolve declared defaults to integers, to a fixpoint, skipping any name
    already known to be ambiguous. A parameter whose default references another
    parameter resolves once that one has."""
    env: Dict[str, int] = {}
    for _ in range(len(by_name) + 1):
        progressed = False
        for name, sightings in by_name.items():
            if name in env or name in excluded:
                continue
            values = _sightings_values(sightings, env)
            if len(values) == 1:
                env[name] = next(iter(values))
                progressed = True
        if not progressed:
            break
    return env


def resolve_parameter_env(
    by_name: Dict[str, List[Tuple[str, str]]]
) -> Tuple[Dict[str, int], Dict[str, Any]]:
    """Derive the corpus' parameter environment, refusing every ambiguity.

    A parameter declared with CONFLICTING resolved values anywhere in the
    corpus is AMBIGUOUS: the corpus contradicts itself and there is no correct
    answer to pick, so the name is excluded from the environment entirely —
    which also drops every parameter whose own default referenced it.

    The conflict test is applied to the CONVERGED environment, not to the
    round in which a name first resolved. A sighting that only becomes
    evaluable late (because it referenced a parameter resolved later) must
    still be able to contradict one that resolved early; testing mid-fixpoint
    would let the first resolution win by arriving first. On conflict the whole
    resolution is redone with the conflicting names excluded, because a value
    derived from a name that turned out to be ambiguous is itself a guess.
    """
    ambiguous: Dict[str, Any] = {}
    for _ in range(4):
        env = _fixpoint(by_name, ambiguous)
        conflicts: Dict[str, Any] = {}
        for name, sightings in by_name.items():
            if name in ambiguous:
                continue
            values = _sightings_values(sightings, env)
            if len(values) > 1:
                conflicts[name] = {
                    "values": {str(k): v for k, v in sorted(values.items())},
                    "reason": "declared with conflicting defaults in the "
                              "corpus — excluded, never picked",
                }
        if not conflicts:
            return env, ambiguous
        ambiguous.update(conflicts)
    # Did not settle: refuse the whole environment rather than pick a round.
    return {}, ambiguous


# ─────────────────────────────────────────────────────────────────────
# The join
# ─────────────────────────────────────────────────────────────────────

def actionable_width(entry: Dict[str, Any]) -> Optional[int]:
    """Bit width a port-list consumer can already emit, or None.

    Same acceptance as `l1_pin_bus_width_actionable_check._resolved_width`:
    an integer `width`, a pure-numeric `width` string, or an integer
    `msb`/`lsb` pair. Prose is NOT actionable.
    """
    w = entry.get("width")
    if _is_int(w) and w > 0:
        return w
    if isinstance(w, str) and re.fullmatch(r"\s*\d+\s*", w):
        n = int(w.strip())
        if n > 0:
            return n
    msb, lsb = entry.get("msb"), entry.get("lsb")
    if _is_int(msb) and _is_int(lsb):
        return abs(msb - lsb) + 1
    return None


def resolve_span(expr: str, env: Dict[str, int]) -> Tuple[
        Optional[Tuple[int, int, int]], str, List[str]]:
    """Resolve a `hi:lo` span to (width, msb, lsb).

    Returns (result_or_None, reason, unresolved_identifiers). `reason` is
    filled only when the result is None — every no-op says why in the report.
    """
    span = expr.strip()
    if span.startswith("[") and span.endswith("]"):
        span = span[1:-1].strip()
    idents = [i for i in _IDENT_RE.findall(span)
              if i not in _NON_PARAM_IDENTS]
    unresolved = sorted({i for i in idents if i not in env})
    if span.count(":") != 1:
        return None, ("not a single `hi:lo` span — no unique width follows "
                      "from it"), unresolved
    if unresolved:
        return None, ("identifier(s) not declared with a resolvable default "
                      "anywhere in the corpus"), unresolved
    hi_s, lo_s = span.split(":", 1)
    hi = _sc._safe_eval_int(hi_s, env)
    lo = _sc._safe_eval_int(lo_s, env)
    if hi is None or lo is None:
        return None, "bound not evaluable by the whitelisted-operator AST walk", unresolved
    if hi < 0 or lo < 0:
        return None, f"bound resolves negative (hi={hi}, lo={lo})", unresolved
    # Cross-check against the shipped evaluator: if the two disagree, this
    # program does NOT get to pick one. That is a no-op, not a coin flip.
    width = _sc._resolve_bracket_width(f"[{span}]", env)
    if width == _sc.WIDTH_UNKNOWN or width <= 0:
        return None, "shared evaluator returned WIDTH_UNKNOWN", unresolved
    if width != abs(hi - lo) + 1:
        return None, "bound arithmetic disagrees with the shared evaluator", unresolved
    return (width, hi, lo), "", unresolved


def _params_used(expr: str, env: Dict[str, int]) -> Dict[str, int]:
    return {i: env[i] for i in sorted(set(_IDENT_RE.findall(expr)))
            if i in env}


def plan(project: Path) -> Dict[str, Any]:
    """Compute every resolution WITHOUT writing anything."""
    paths = _l_doc_paths(project)
    if not paths:
        return {"program": PROGRAM, "verdict": "SILENT_SKIP", "rc": 2,
                "reason": (f"no L*.json under "
                           f"{_pl.generated_docs_dir(project)} "
                           f"(phase1 hasn't run?)")}
    docs: Dict[str, Any] = {}
    for p in paths:
        try:
            docs[p.name] = json.loads(p.read_text(encoding="utf-8"))
        except Exception as exc:
            return {"program": PROGRAM, "verdict": "ERROR", "rc": 2,
                    "reason": f"cannot parse {p.name}: {exc}"}

    by_name, param_records = collect_parameter_exprs(docs)
    env, ambiguous = resolve_parameter_env(by_name)

    resolved: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    candidates = 0
    for fname, doc in docs.items():
        budget = [_MAX_NODES]
        for node, path in _walk(doc, "", budget):
            if not isinstance(node, dict):
                continue
            expr = node.get(_SYMBOLIC_KEY)
            if not isinstance(expr, str) or not expr.strip():
                continue
            candidates += 1
            name = node.get("name") if isinstance(node.get("name"), str) else None
            already = actionable_width(node)
            if already is not None:
                skipped.append({
                    "doc": fname, "at": path, "name": name, "expr": expr,
                    "reason": "already carries an actionable integer width "
                              f"({already}) — never overwritten",
                    "unresolved_identifiers": [],
                })
                continue
            got, reason, unresolved = resolve_span(expr, env)
            if got is None:
                # Distinguish "never declared" from "declared, contradictorily".
                clashing = [i for i in unresolved if i in ambiguous]
                if clashing:
                    reason = (f"identifier(s) {clashing} are declared with "
                              f"CONFLICTING defaults in the corpus — there is "
                              f"no correct value to pick")
                skipped.append({
                    "doc": fname, "at": path, "name": name, "expr": expr,
                    "reason": reason,
                    "unresolved_identifiers": unresolved,
                })
                continue
            width, msb, lsb = got
            resolved.append({
                "doc": fname, "at": path, "name": name, "expr": expr,
                "width": width, "msb": msb, "lsb": lsb,
                "parameters_used": _params_used(expr, env),
                "was_width": node.get("width"),
            })

    verdict = "RESOLVED" if resolved else "NO_OP"
    return {
        "program": PROGRAM,
        "verdict": verdict,
        "rc": 0,
        "reason": (
            f"{len(resolved)} symbolic width(s) joined against the corpus' own "
            f"parameter defaults; {len(skipped)} left untouched."
            if resolved else
            f"nothing to join: {candidates} symbolic-width entry(s) seen, "
            f"{len(skipped)} left untouched."),
        "l_docs_scanned": len(docs),
        "symbolic_candidates": candidates,
        "parameter_env": dict(sorted(env.items())),
        "ambiguous_parameters": ambiguous,
        "parameter_declarations": param_records,
        "resolved": resolved,
        "skipped": skipped,
        "applied": False,
    }


def apply_plan(project: Path, report: Dict[str, Any]) -> Dict[str, Any]:
    """Write the planned resolutions back into the L-docs.

    A document with zero resolutions is not rewritten at all — not even
    re-serialised — so "no-op" means the file is byte-identical, not merely
    semantically unchanged.
    """
    if report.get("rc") != 0 or not report.get("resolved"):
        report["applied"] = False
        return report
    gd = _pl.generated_docs_dir(project)
    by_doc: Dict[str, List[Dict[str, Any]]] = {}
    for r in report["resolved"]:
        by_doc.setdefault(r["doc"], []).append(r)

    written: List[str] = []
    for fname, items in sorted(by_doc.items()):
        path = gd / fname
        doc = json.loads(path.read_text(encoding="utf-8"))
        wanted = {(i["at"], i["expr"]): i for i in items}
        budget = [_MAX_NODES]
        hits = 0
        for node, npath in _walk(doc, "", budget):
            if not isinstance(node, dict):
                continue
            expr = node.get(_SYMBOLIC_KEY)
            if not isinstance(expr, str):
                continue
            item = wanted.get((npath, expr))
            if item is None:
                continue
            node["width"] = item["width"]
            node["msb"] = item["msb"]
            node["lsb"] = item["lsb"]
            node[_PROVENANCE_KEY] = {
                "resolver": PROGRAM,
                "expression": item["expr"],
                "parameters_used": item["parameters_used"],
                "parameter_sources": sorted(
                    {d["doc"] for d in report["parameter_declarations"]
                     if d["name"] in item["parameters_used"]}),
                "previous_width": item["was_width"],
            }
            hits += 1
        if hits:
            path.write_text(
                json.dumps(doc, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8")
            written.append(fname)
    report["applied"] = True
    report["documents_written"] = written
    return report


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog=PROGRAM, description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project_dir", type=Path)
    ap.add_argument("--apply", action="store_true",
                    help="write the resolutions back (default: dry run)")
    ap.add_argument("--json", default=None, help="write the JSON report here")
    args = ap.parse_args(argv)

    project = args.project_dir.resolve()
    if not project.is_dir():
        print(f"ERROR: not a directory: {project}", file=sys.stderr)
        return 2

    report = plan(project)
    if args.apply:
        report = apply_plan(project, report)

    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                       encoding="utf-8")

    rc = int(report.get("rc", 2))
    line = f"{report['verdict']}: {report['reason']}"
    if rc != 0:
        print(line, file=sys.stderr)
        return rc
    print(line)
    for r in report.get("resolved", [])[:12]:
        print(f"  + {r['doc']} {r['at']} {r['name']}: "
              f"`{r['expr']}` -> width={r['width']} msb={r['msb']} "
              f"lsb={r['lsb']} via {r['parameters_used']}"
              f"{'' if report.get('applied') else '  (dry run)'}")
    for s in report.get("skipped", [])[:12]:
        print(f"  . {s['doc']} {s['at']} {s['name']}: "
              f"`{s['expr']}` untouched — {s['reason']}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
