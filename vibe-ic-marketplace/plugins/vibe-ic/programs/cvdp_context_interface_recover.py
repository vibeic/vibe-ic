#!/usr/bin/env python3
"""cvdp_context_interface_recover.py — recover the TARGET module's PORT INTERFACE
from the PROVIDED `input['context']` RTL header (CONVERGE lever: Tier4 -> Tier3).

WHY THIS IS THE SPEC, NOT THE ANSWER (§3.9 + the existing bridge doctrine):
  * A module's PORT HEADER (`module foo(input [7:0] a, output b);`) is the
    INTERFACE — the contract the testbench binds to — and is, by definition,
    part of the specification chain, NOT the functional answer. The
    `cvdp_atomic_bridge` already reads the `output['context']` skeleton's
    module HEADER (header-only, never the body) as a legitimate interface
    source; this module only widens that same header-only recovery to the
    PROVIDED `input['context']` RTL (also spec, also not the golden output).
  * We read ONLY the port-list header (dir/width/name) — we STOP at the first
    `);` / first behavioural statement and NEVER parse the body. Even when a
    record's `input.context` ships a full reference implementation, the gate
    built from these ports enforces only INTERFACE conformance; the AI still
    authors the function. No functional answer can leak through a port list.
  * `output['response']` (the golden answer) is NEVER touched.

NO-CHEAT BOUNDARY (enforced here):
  * recover ONLY for the module whose name == the harness TOPLEVEL (the exact
    target the scorer binds). Helper / sub-modules in `input.context` (building
    blocks the AI is meant to INSTANTIATE — e.g. a leaf primitive provided under
    a larger composite target) are SKIPPED — their header is not the target's.
  * if the target module's header is NOT literally present in `input.context`,
    return [] (recover nothing — §4.05 SKIP, never fabricate an interface).

API:
  recover_interface(record, target=None) -> List[{name,dir,width}]
      [] when the target header is absent / unparseable.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Dict, List, Optional

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import cvdp_atomic_bridge as _bridge  # toplevel_name
import cvdp_width_resolve as _wr       # param_defaults / eval_width_expr


_DIR_RE = re.compile(r"^(input|output|inout)\b")
_PORT_KW = re.compile(r"\b(input|output|inout)\b")


def _context_rtl(record: dict) -> Dict[str, str]:
    """The PROVIDED RTL files (input.context). Never output/harness."""
    ctx = (record.get("input") or {}).get("context") or {}
    if not isinstance(ctx, dict):
        return {}
    return {k: v for k, v in ctx.items()
            if isinstance(v, str) and (k.endswith(".v") or k.endswith(".sv"))}


def _find_module_span(text: str, target: str) -> Optional[str]:
    """Return the source of `module <target> ... endmodule` (or to EOF), else
    None. Word-boundary match so `foo` never matches `foo_bar`."""
    m = re.search(rf"\bmodule\s+{re.escape(target)}\b", text)
    if not m:
        return None
    start = m.start()
    em = re.search(r"\bendmodule\b", text[start:])
    end = start + em.end() if em else len(text)
    return text[start:end]


def _balanced(text: str, open_idx: int) -> Optional[int]:
    """Index just past the ')' that matches the '(' at open_idx."""
    depth = 0
    for i in range(open_idx, len(text)):
        c = text[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return i
    return None


def _split_top_commas(s: str) -> List[str]:
    """Split on commas not nested in (), [] or {}."""
    out, depth, cur = [], 0, []
    for c in s:
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        if c == "," and depth == 0:
            out.append("".join(cur))
            cur = []
        else:
            cur.append(c)
    if "".join(cur).strip():
        out.append("".join(cur))
    return out


def _strip_comments(s: str) -> str:
    s = re.sub(r"/\*.*?\*/", " ", s, flags=re.S)
    s = re.sub(r"//[^\n]*", " ", s)
    return s


def _width_from_range(span: str, params: Dict[str, int]) -> Optional[int]:
    """`[hi:lo]` -> width int, resolving param expressions via cvdp_width_resolve.
    A scalar (no range) -> 1. Unresolvable param expr -> None (presence only)."""
    span = span.strip()
    if not span:
        return 1
    m = re.match(r"\[\s*(.+?)\s*:\s*(.+?)\s*\]\s*$", span)
    if not m:
        return None
    hi, lo = m.group(1).strip(), m.group(2).strip()
    if re.fullmatch(r"\d+", hi) and re.fullmatch(r"\d+", lo):
        return abs(int(hi) - int(lo)) + 1
    # param expression like WIDTH-1 : 0  -> eval (hi-lo)+1 symbolically
    hv = _wr.eval_width_expr(hi, params)
    lv = _wr.eval_width_expr(lo, params)
    if hv is not None and lv is not None:
        return abs(hv - lv) + 1
    return None


def _module_params(span: str) -> Dict[str, int]:
    """localparam / parameter integer defaults declared in the module source."""
    params: Dict[str, int] = {}
    for m in re.finditer(
        r"\b(?:localparam|parameter)\b[^;]*?\b([A-Za-z_]\w*)\s*=\s*(\d+)", span):
        params.setdefault(m.group(1), int(m.group(2)))
    return params


def _parse_ansi_ports(header: str, params: Dict[str, int]) -> List[dict]:
    """ANSI header: `input [7:0] a, output reg b, ...`. Verilog ANSI inheritance:
    a chunk that omits the direction inherits the previous chunk's direction AND
    (when it also omits the range) its width — so `output [3:0] a, b` makes BOTH
    4-bit. A chunk that states a NEW direction starts a fresh group: its width is
    its own range, or scalar (1) when it carries none (the range does NOT bleed
    across a direction change)."""
    ports: List[dict] = []
    last_dir = None
    last_width: Optional[int] = 1
    for chunk in _split_top_commas(header):
        c = _strip_comments(chunk).strip()
        if not c:
            continue
        dm = _DIR_RE.match(c)
        new_dir = bool(dm)
        if dm:
            last_dir = dm.group(1)
            c = c[dm.end():].strip()
        if last_dir is None:
            # a leading non-port token (e.g. a stray param) — skip
            continue
        # strip type keywords + signedness
        c = re.sub(r"^\s*(?:wire|reg|logic|bit|signed|unsigned|var|tri)\b", " ", c)
        c = re.sub(r"\b(?:signed|unsigned)\b", " ", c)
        rng = ""
        rm = re.search(r"\[[^\]]*\]", c)
        if rm:
            rng = rm.group(0)
            c = (c[:rm.start()] + " " + c[rm.end():])
        names = [n for n in re.split(r"[\s]+", c.strip()) if re.fullmatch(r"[A-Za-z_]\w*", n)]
        if rng:
            w = _width_from_range(rng, params)        # explicit range wins
        elif new_dir:
            w = 1                                      # new group, no range -> scalar
        else:
            w = last_width                             # pure continuation -> inherit
        last_width = w
        for nm in names:
            ports.append({"name": nm, "dir": last_dir, "width": w})
    return ports


def _parse_nonansi_ports(span: str, header_names: List[str],
                         params: Dict[str, int]) -> List[dict]:
    """Non-ANSI: header is a bare name list; dir/width come from separate
    `input [7:0] a;` declarations in the body (read BEFORE any behavioural
    statement — declarations only, never logic)."""
    # cut the span at the first behavioural construct so we never read the body
    body = span
    cut = re.search(r"\b(always|assign|initial|generate|function|task)\b", body)
    decl_region = body[:cut.start()] if cut else body
    decls: Dict[str, dict] = {}
    for m in re.finditer(
        r"\b(input|output|inout)\b\s*(?:wire|reg|logic|signed|unsigned|\s)*"
        r"(\[[^\]]*\])?\s*([A-Za-z_]\w*(?:\s*,\s*[A-Za-z_]\w*)*)\s*;",
        _strip_comments(decl_region)):
        d, rng, names = m.group(1), m.group(2) or "", m.group(3)
        w = _width_from_range(rng, params)
        for nm in re.split(r"\s*,\s*", names):
            decls[nm] = {"name": nm, "dir": d, "width": w}
    # preserve header order; only emit ports the header actually listed
    out = []
    for nm in header_names:
        if nm in decls:
            out.append(decls[nm])
    return out


def recover_interface(record: dict, target: Optional[str] = None) -> List[dict]:
    """Recover [{name,dir,width}] for the harness-TOPLEVEL target module from the
    provided input.context RTL header. [] if the target header is absent."""
    if not isinstance(record, dict):
        return []
    target = target or _bridge.toplevel_name(record)
    if not target:
        return []
    files = _context_rtl(record)
    if not files:
        return []
    for _name, text in files.items():
        span = _find_module_span(text, target)
        if span is None:
            continue
        # isolate the port-list header: module <target> [#(...)] ( ... ) ;
        mh = re.search(rf"\bmodule\s+{re.escape(target)}\b", span)
        i = mh.end()
        # skip an optional parameter block  #( ... )
        pm = re.match(r"\s*#\s*\(", span[i:])
        if pm:
            close = _balanced(span, i + pm.end() - 1)
            if close is None:
                continue
            i = close + 1
        # the port-list '('
        op = span.find("(", i)
        if op == -1:
            # no port list — nothing to recover
            return []
        close = _balanced(span, op)
        if close is None:
            return []
        header = span[op + 1:close]
        params = _module_params(span)
        if _PORT_KW.search(header):
            ports = _parse_ansi_ports(header, params)
        else:
            header_names = [n for n in re.split(r"[\s,]+", _strip_comments(header).strip())
                            if re.fullmatch(r"[A-Za-z_]\w*", n)]
            ports = _parse_nonansi_ports(span, header_names, params)
        # de-dup by name (first wins), drop empties
        seen, out = set(), []
        for p in ports:
            if p["name"] and p["name"] not in seen:
                seen.add(p["name"])
                out.append(p)
        return out
    return []


def main(argv=None) -> int:
    import argparse, json
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--jsonl", required=True)
    ap.add_argument("--id", help="recover only this record id")
    ap.add_argument("--count", action="store_true",
                    help="count records whose target interface is recoverable")
    a = ap.parse_args(argv)
    recs = [json.loads(l) for l in open(a.jsonl)]
    if a.id:
        r = next((x for x in recs if x.get("id") == a.id), None)
        if not r:
            print("id not found", file=sys.stderr)
            return 2
        print(json.dumps(recover_interface(r), indent=2, ensure_ascii=False))
        return 0
    n = sum(1 for r in recs if recover_interface(r))
    print(f"recoverable target interfaces: {n} / {len(recs)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
