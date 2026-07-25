#!/usr/bin/env python3
"""l1_param_bus_width_resolve.py — bind PARAMETRIC port widths to their
declared defaults, so the port-list consumer gets an actionable integer.

VERDICT SEMANTICS: **REPAIRS** (exit 0 unless the docs are unreadable).
This is not a gate. It is the deterministic JOIN that
`l1_pin_bus_width_actionable_check` proves is missing.

The measured defect
------------------------------------------------------------------
Phase 1 already extracts BOTH halves of the answer, into two typed
fields of its OWN output, and never joins them. Measured on a real
run (spm, plugin v1.6.1, phase1 doc mode):

    L1_DATASHEET.pin_table[i] = {"name": "x",
        "width": "N-bit(`[size-1:0]`,parameter `size` 預設 32)",
        "width_symbolic": "size-1:0", "msb": null, "lsb": null}

    L8_RTL_CONSTANTS.parameters = [
        {"name": "size", "default": "32", ...}]
    L9_INTEGRATION_SPEC.parameters = [   # same row
        {"name": "size", "default": "32", ...}]

`_parse_port_width` (phase1_doc_one_shot_runner.py) resolves the
bracket `[size-1:0]` to `width_symbolic="size-1:0"` and returns
width=None — correct as far as it goes, it has only the cell string.
But by the time every L-doc is emitted, the binding `size=32` IS
present, in machine-readable form, in a sibling doc. Nothing ever
substitutes it. Downstream, phase2 emits a 1-bit scalar `x` for what
the design's own interface table declares as an N-bit multiplicand
bus, and `l1_pin_bus_width_actionable_check` FAILs the run.

This is a Bucket A defect in its purest form. The exact input the
program sees is two typed JSON fields; the decision is
`substitute name -> default, evaluate the arithmetic`. There is no
judgement anywhere in it.

Why resolve to the DEFAULT
------------------------------------------------------------------
A parameter's declared default IS the concrete elaboration the
top-level port list is emitted at — that is what "default" means. The
parametric form is NOT discarded: `width_symbolic` is preserved on the
entry, so an elaboration-time consumer can still re-bind. The
resolution is additive.

Refusals (never silently pick)
------------------------------------------------------------------
  * A parameter name bound to CONFLICTING defaults across sibling
    L-docs is NOT resolved — it is reported as `ambiguous_binding`.
    Silently taking the first is the exact failure class this
    campaign keeps measuring; a wrong bus width is worse than an
    unresolved one, because the unresolved one still trips the gate.
  * An expression referencing a parameter with NO binding is left
    alone and reported. The program does not invent a width.
  * A pin that ALREADY carries a resolvable integer width is never
    touched, in either direction.
  * Only `+ - * // % ()` and integer literals are evaluated, via an
    AST whitelist. No `eval` of arbitrary text.

chip-AGNOSTIC: no design name, port name, PDK name or vendor literal
appears in this file. Everything is keyed on document STRUCTURE.

Usage:
    python3 l1_param_bus_width_resolve.py <project_dir> [--json OUT]
                                          [--dry-run]
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _path_layout as _pl  # noqa: E402

TOOL = "l1_param_bus_width_resolve"

# Every generated doc is scanned for a `parameters[]` list; these are the
# containers a port-width expression may legally be bound from. Keyed on
# STRUCTURE (a list of {name, default}), not on which L-doc it came from,
# so a future doc that carries the same shape participates automatically.
_PARAM_LIST_KEYS = ("parameters", "design_parameters", "rtl_parameters")

# Port-carrying containers that may hold an unresolved parametric width.
# L1.pin_table is what the gate reads; L9.top_ports / ports /
# top_module_pins are the mirrors phase2 and l9_rtl_pin_consistency read.
_PORT_CONTAINERS = (
    ("L1_DATASHEET.json", ("pin_table",)),
    ("L9_INTEGRATION_SPEC.json",
     ("top_ports", "ports", "top_module_pins")),
)

# `<msb_expr> : <lsb_expr>` — the shape `width_symbolic` is stored in.
_RE_RANGE = re.compile(r"^\s*(?P<msb>[^:]+?)\s*:\s*(?P<lsb>[^:]+?)\s*$")
# A bracketed range embedded in a prose width cell.
_RE_BRACKET_RANGE = re.compile(r"\[\s*([^\]\[]{1,64}?)\s*\]")
# An integer default, possibly written `32`, `'d32`, `32'd32`, `0x20`.
_RE_INT_DEFAULT = re.compile(
    r"^\s*(?:\d+\s*'\s*[dD])?\s*(?P<v>\d+)\s*$")
_RE_HEX_DEFAULT = re.compile(r"^\s*0[xX](?P<v>[0-9a-fA-F]+)\s*$")

_MAX_WIDTH = 1 << 20          # sanity bound on a resolved bus width


def _as_int(val: Any) -> Optional[int]:
    """Parse a declared parameter default into a non-negative int."""
    if isinstance(val, bool):
        return None
    if isinstance(val, int):
        return val if val >= 0 else None
    if not isinstance(val, str):
        return None
    s = val.strip().strip("`").strip()
    m = _RE_HEX_DEFAULT.match(s)
    if m:
        return int(m.group("v"), 16)
    m = _RE_INT_DEFAULT.match(s)
    if m:
        return int(m.group("v"))
    return None


# --------------------------------------------------------------------
# Safe arithmetic evaluation
# --------------------------------------------------------------------
_ALLOWED_BINOP = (ast.Add, ast.Sub, ast.Mult, ast.FloorDiv,
                  ast.Div, ast.Mod)
_ALLOWED_UNARY = (ast.UAdd, ast.USub)


def _eval_node(node: ast.AST, binds: Dict[str, int]) -> Optional[int]:
    if isinstance(node, ast.Expression):
        return _eval_node(node.body, binds)
    if isinstance(node, ast.Constant):
        return node.value if isinstance(node.value, int) and not isinstance(
            node.value, bool) else None
    if isinstance(node, ast.Name):
        return binds.get(node.id)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, _ALLOWED_UNARY):
        v = _eval_node(node.operand, binds)
        if v is None:
            return None
        return +v if isinstance(node.op, ast.UAdd) else -v
    if isinstance(node, ast.BinOp) and isinstance(node.op, _ALLOWED_BINOP):
        a, b = _eval_node(node.left, binds), _eval_node(node.right, binds)
        if a is None or b is None:
            return None
        try:
            if isinstance(node.op, ast.Add):
                return a + b
            if isinstance(node.op, ast.Sub):
                return a - b
            if isinstance(node.op, ast.Mult):
                return a * b
            if isinstance(node.op, (ast.FloorDiv, ast.Div)):
                return a // b if b else None
            if isinstance(node.op, ast.Mod):
                return a % b if b else None
        except (ZeroDivisionError, OverflowError, ValueError):
            return None
    return None


def safe_eval(expr: str, binds: Dict[str, int]) -> Optional[int]:
    """Evaluate an integer arithmetic expression under `binds`.

    Returns None for anything outside the whitelist, for an unbound
    identifier, or for a non-integer result. Never raises."""
    if not isinstance(expr, str) or not expr.strip():
        return None
    if len(expr) > 256:
        return None
    try:
        tree = ast.parse(expr.strip(), mode="eval")
    except (SyntaxError, ValueError, MemoryError, RecursionError):
        return None
    try:
        return _eval_node(tree, binds)
    except RecursionError:
        return None


def free_names(expr: str) -> List[str]:
    """Identifiers referenced by `expr` (for reporting unbound ones)."""
    try:
        tree = ast.parse(expr.strip(), mode="eval")
    except Exception:
        return []
    return sorted({n.id for n in ast.walk(tree) if isinstance(n, ast.Name)})


# --------------------------------------------------------------------
# Binding collection
# --------------------------------------------------------------------
def collect_bindings(
    project: Path,
) -> Tuple[Dict[str, int], Dict[str, List[Any]], List[Dict[str, Any]]]:
    """Scan every generated L-doc for `parameters[]` rows.

    Returns (bindings, sources, conflicts). A name whose declared
    defaults DISAGREE across docs is excluded from `bindings` and
    listed in `conflicts` — refusing beats guessing."""
    gd = _pl.generated_docs_dir(project)
    seen: Dict[str, Dict[int, List[str]]] = {}
    sources: Dict[str, List[Any]] = {}
    if not gd.is_dir():
        return {}, {}, []
    for path in sorted(gd.glob("*.json")):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(doc, dict):
            continue
        for key in _PARAM_LIST_KEYS:
            rows = doc.get(key)
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                name = row.get("name")
                if not isinstance(name, str) or not name.strip():
                    continue
                name = name.strip().strip("`")
                val = _as_int(row.get("default"))
                if val is None:
                    val = _as_int(row.get("value"))
                if val is None:
                    continue
                seen.setdefault(name, {}).setdefault(val, []).append(
                    f"{path.name}:{key}")
    bindings: Dict[str, int] = {}
    conflicts: List[Dict[str, Any]] = []
    for name, byval in seen.items():
        if len(byval) == 1:
            val = next(iter(byval))
            bindings[name] = val
            sources[name] = sorted(set(byval[val]))
        else:
            conflicts.append({
                "parameter": name,
                "candidates": {str(k): sorted(set(v))
                               for k, v in byval.items()},
                "action": "NOT_RESOLVED — conflicting declared defaults; "
                          "refusing to pick one silently.",
            })
    return bindings, sources, conflicts


# --------------------------------------------------------------------
# Port repair
# --------------------------------------------------------------------
def _already_actionable(pin: Dict[str, Any]) -> bool:
    """Mirror of the gate's `_resolved_width` acceptance test."""
    w = pin.get("width")
    if isinstance(w, int) and not isinstance(w, bool) and w > 0:
        return True
    if isinstance(w, str) and re.fullmatch(r"\s*\d+\s*", w) and int(w) > 0:
        return True
    msb, lsb = pin.get("msb"), pin.get("lsb")
    return (isinstance(msb, int) and not isinstance(msb, bool)
            and isinstance(lsb, int) and not isinstance(lsb, bool))


def _range_expr(pin: Dict[str, Any]) -> Optional[str]:
    """The `msb:lsb` expression this pin carries, if any.

    Prefers the typed `width_symbolic` field; falls back to a bracket
    embedded in a prose `width` string."""
    ws = pin.get("width_symbolic")
    if isinstance(ws, str) and ":" in ws:
        return ws.strip()
    w = pin.get("width")
    if isinstance(w, str):
        for cand in _RE_BRACKET_RANGE.findall(w):
            if ":" in cand:
                return cand.strip()
    return None


def resolve_pin(
    pin: Dict[str, Any], binds: Dict[str, int]
) -> Optional[Dict[str, Any]]:
    """Try to bind one pin's parametric range. Returns a record of what
    happened, or None when the pin is not a parametric-width candidate."""
    if _already_actionable(pin):
        return None
    expr = _range_expr(pin)
    if not expr:
        return None
    m = _RE_RANGE.match(expr)
    if not m:
        return {"pin": pin.get("name"), "status": "unparsed_range",
                "expr": expr}
    msb = safe_eval(m.group("msb"), binds)
    lsb = safe_eval(m.group("lsb"), binds)
    if msb is None or lsb is None:
        unbound = sorted(
            set(free_names(m.group("msb")) + free_names(m.group("lsb")))
            - set(binds))
        return {"pin": pin.get("name"), "status": "unbound",
                "expr": expr, "unbound_parameters": unbound}
    width = abs(msb - lsb) + 1
    if width <= 0 or width > _MAX_WIDTH:
        return {"pin": pin.get("name"), "status": "out_of_range",
                "expr": expr, "computed_width": width}
    before = {"width": pin.get("width"), "msb": pin.get("msb"),
              "lsb": pin.get("lsb")}
    pin["width"] = width
    pin["msb"] = msb
    pin["lsb"] = lsb
    pin["width_symbolic"] = expr        # parametric form PRESERVED
    strat = pin.get("extraction_strategy")
    tag = f"+param_bound_{TOOL}"
    if isinstance(strat, str) and tag not in strat:
        pin["extraction_strategy"] = strat + tag
    return {"pin": pin.get("name"), "status": "resolved", "expr": expr,
            "width": width, "msb": msb, "lsb": lsb, "before": before}


def run(project: Path, dry_run: bool = False) -> Dict[str, Any]:
    binds, sources, conflicts = collect_bindings(project)
    gd = _pl.generated_docs_dir(project)
    records: List[Dict[str, Any]] = []
    touched_docs: List[str] = []

    for fname, keys in _PORT_CONTAINERS:
        path = gd / fname
        if not path.is_file():
            continue
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            records.append({"doc": fname, "status": "unreadable",
                            "error": str(exc)})
            continue
        if not isinstance(doc, dict):
            continue
        changed = False
        for key in keys:
            rows = doc.get(key)
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                rec = resolve_pin(row, binds)
                if rec is None:
                    continue
                rec["doc"], rec["container"] = fname, key
                records.append(rec)
                if rec["status"] == "resolved":
                    changed = True
        if changed and not dry_run:
            path.write_text(
                json.dumps(doc, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8")
            touched_docs.append(fname)

    resolved = [r for r in records if r.get("status") == "resolved"]
    unresolved = [r for r in records if r.get("status") != "resolved"]
    return {
        "tool": TOOL,
        "dry_run": dry_run,
        "bindings": binds,
        "binding_sources": sources,
        "ambiguous_bindings": conflicts,
        "resolved_count": len(resolved),
        "unresolved_count": len(unresolved),
        "resolved": resolved,
        "unresolved": unresolved,
        "docs_written": touched_docs,
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog=TOOL, description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project_dir", type=Path)
    ap.add_argument("--json", default=None, help="write JSON report here")
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would change; write nothing")
    args = ap.parse_args(argv)

    project = args.project_dir.resolve()
    if not project.is_dir():
        print(f"ERROR: not a directory: {project}", file=sys.stderr)
        return 2

    report = run(project, dry_run=args.dry_run)
    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2, ensure_ascii=False)
                       + "\n", encoding="utf-8")

    n, u = report["resolved_count"], report["unresolved_count"]
    if n:
        detail = ", ".join(
            f"{r['pin']}[{r['msb']}:{r['lsb']}]" for r in report["resolved"])
        print(f"{TOOL}: bound {n} parametric bus width(s) from declared "
              f"parameter defaults — {detail}")
    else:
        print(f"{TOOL}: no parametric bus width needed binding "
              f"({u} unresolved candidate(s))")
    for c in report["ambiguous_bindings"]:
        print(f"  AMBIGUOUS: parameter {c['parameter']!r} has conflicting "
              f"declared defaults {sorted(c['candidates'])} — not resolved",
              file=sys.stderr)
    for r in report["unresolved"][:8]:
        print(f"  UNRESOLVED: {r.get('pin')!r} {r.get('expr')!r} "
              f"({r.get('status')})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
