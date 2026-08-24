#!/usr/bin/env python3
r"""rtl_interface_recover.py — recover a module's PORT INTERFACE from RTL text.

THE GENERAL CORE. A module's port header (`module foo(input [7:0] a, output b);`)
is the INTERFACE — the contract anything binding to the design must honour — and
is therefore part of the SPECIFICATION, not the answer. Recovering it is plain
Verilog/SystemVerilog header parsing: it needs RTL text and a target module name,
nothing else.

WHY THIS IS ITS OWN FILE (§ 0 GENERAL-CORE / THIN-ADAPTER). This parser lived
only inside `cvdp_context_interface_recover.py`, behind a CLI that accepted a
dataset `--jsonl` and nothing else — so a plain project holding its own RTL had
no way to reach it. Measured 2026-08-25: four of the five task natures operate ON
existing RTL (completion, functional-modification, optimization, debug), and for
every one of them L9 came back `top_ports=[]` even though the ports were sitting
in the supplied header — which then SKIPped every testbench generator downstream.

NO-CHEAT BOUNDARY (unchanged from where this came from): only the port-list
HEADER is read — direction, width, name. Parsing stops at the first `);` or the
first behavioural statement, and the body is NEVER read. A gate built from these
ports enforces INTERFACE conformance only; no functional answer can leak through
a port list.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
import verilog_width_resolve as _wr       # param_defaults / eval_width_expr
from _prose_polarity import is_denied     # "not driven" / "unused" screening

_RTL_SUFFIXES = (".v", ".sv", ".vh", ".svh")


_DIR_RE = re.compile(r"^(input|output|inout)\b")
_PORT_KW = re.compile(r"\b(input|output|inout)\b")



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
    """`[hi:lo]` -> width int, resolving param expressions via verilog_width_resolve.
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


def _extract_param_value(text: str, start: int) -> str:
    """Extract a parameter value starting at `start` until a top-level `,`, `;`
    or `)`. Handles balanced parentheses so `$clog2(N)` is captured whole."""
    i = start
    depth = 0
    while i < len(text):
        c = text[i]
        if c == "(":
            depth += 1
        elif c == ")":
            if depth == 0:
                break
            depth -= 1
        elif c in ",;" and depth == 0:
            break
        i += 1
    return text[start:i].strip()


def _norm_sized_literal(expr: str) -> Optional[int]:
    """A Verilog/SystemVerilog sized integer literal -> int value.

    Handles:
      - sized:   8'd8, 12'hFF, 'b1010, 4'b1111, 'd255
      - unsized: '16, 'd16, 'hFF, '1, '0
    Comments are stripped by the caller; this sees the bare RHS.
    §4.05: a literal is an anchored structural fact; a non-literal returns None
    so the fixed-point expression pass can try it.
    """
    expr = expr.strip()
    # sized / unsized with explicit base
    m = re.fullmatch(
        r"(\d*)\s*'\s*[sS]?\s*([dDbBhHoO])\s*([0-9a-fA-F_xXzZ]+)", expr)
    if m:
        digits = m.group(3).replace("_", "")
        base = m.group(2).lower()
        if base == "d":
            return int(digits)
        if base == "h":
            return int(digits, 16)
        if base == "b":
            return int(digits, 2)
        if base == "o":
            return int(digits, 8)
    # unsized decimal literal: `'16` (SystemVerilog default decimal)
    m = re.fullmatch(r"(\d*)\s*'\s*[sS]?\s*([0-9a-fA-F_xXzZ]+)", expr)
    if m and m.group(1) == "":
        return int(m.group(2))
    # fill literals: '1, '0, 'x, 'z — magnitude is 1 for width calculations
    if re.fullmatch(r"'\s*[01xXzZ]", expr):
        return 1
    return None


def _module_params(span: str) -> Dict[str, int]:
    """localparam / parameter integer defaults declared in the module source.

    Captures:
      * literal integer defaults (`parameter N = 7`);
      * sized literals (`parameter NBW = 'd8`, `parameter C = 8'hFF`);
      * derived expressions (`parameter NWIDTH = $clog2(N)`);
      * ternary expressions (`localparam CNT = (M <= 1) ? 1 : $clog2(M)`).

    Iterates until no new parameter resolves, so chains of derived values are
    computed safely."""
    params: Dict[str, int] = {}
    param_re = re.compile(
        r"\b(?:localparam|parameter)\b\s*(?:\w+\s+)?\b([A-Za-z_]\w*)\s*=")

    def _rhs(m) -> str:
        # strip end-of-line / inline comments from the captured RHS so a sized
        # literal like `'d8 // comment` does not poison parsing.
        raw = _extract_param_value(span, m.end())
        return re.sub(r"//.*$", "", re.sub(r"/\*.*?\*/", "", raw,
                                           flags=re.S), count=1).strip()

    # First pass: literal / sized-literal defaults.
    for m in param_re.finditer(span):
        name = m.group(1)
        expr = _rhs(m)
        if re.fullmatch(r"\d+", expr):
            params.setdefault(name, int(expr))
            continue
        val = _norm_sized_literal(expr)
        if val is not None:
            params.setdefault(name, val)

    # Second pass: expression defaults (including $clog2, arithmetic, ternary).
    # Re-scan until fixed-point so `NWIDTH = $clog2(N)` resolves after N is known.
    changed = True
    while changed:
        changed = False
        for m in param_re.finditer(span):
            name = m.group(1)
            if name in params:
                continue
            expr = _rhs(m)
            if re.fullmatch(r"\d+", expr):
                continue
            val = _wr.eval_width_expr(expr, params)
            if val is not None:
                params[name] = val
                changed = True
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


def _parse_one_span(span: str, target: str) -> List[dict]:
    """Parse a single `module <target> ... endmodule` span into [{name,dir,width}].
    Returns [] if the header is unparseable."""
    mh = re.search(rf"\bmodule\s+{re.escape(target)}\b", span)
    if not mh:
        return []
    i = mh.end()
    # skip an optional parameter block  #( ... )
    pm = re.match(r"\s*#\s*\(", span[i:])
    if pm:
        close = _balanced(span, i + pm.end() - 1)
        if close is None:
            return []
        i = close + 1
    # the port-list '('
    op = span.find("(", i)
    if op == -1:
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


_IFACE_SECTION_RE = re.compile(
    r"#+\s*[^\n]*?\b(?:Input\s*/\s*Output\s+Interface|I/?O\s+Interface|"
    r"Interface\s+Update|Updated\s+Interface|Port\s+List|Top[- ]?Level\s+Port)"
    r"[^\n]*\n", re.IGNORECASE)
# a bulleted/numbered port item:  `name[range]` : description   (backticks required)
_IFACE_PORT_RE = re.compile(
    r"[-*\d.]+\s*`(?P<name>[A-Za-z_]\w*)\s*(?P<range>\[[^\]]*\])?`\s*[:：-]?\s*"
    r"(?P<desc>[^\n]*)")
# sub-list direction headers inside the section
_IFACE_DIR_HDR_RE = re.compile(
    r"\b(?P<dir>Inputs?|Outputs?|Inouts?|Bidirectional(?:\s+Ports?)?)\b\s*[:：]?",
    re.IGNORECASE)


def recover_interface_from_prompt(record_or_prompt) -> List[dict]:
    """Recover [{name,dir,width}] from a prompt's explicit "Updated Interfaces"
    prose section, when present. Returns [] if the prompt has no such section
    (so callers can fall back to the context-RTL header). Direction comes from
    the enclosing Inputs/Outputs/Inout sub-list header, OVERRIDDEN to `inout`
    when the port's own description says 'bidirectional'. chip-AGNOSTIC."""
    prompt = record_or_prompt if isinstance(record_or_prompt, str) else (
        (record_or_prompt or {}).get("input", {}).get("prompt")
        if isinstance(record_or_prompt, dict) else None)
    if not isinstance(prompt, str) or not prompt:
        return []
    m = _IFACE_SECTION_RE.search(prompt)
    if not m:
        return []
    body = prompt[m.end():]
    # bound the section at the next same-or-higher markdown heading
    nxt = re.search(r"\n#+\s", body)
    if nxt:
        body = body[:nxt.start()]
    ports: List[dict] = []
    seen = set()
    cur_dir = None
    for line in body.splitlines():
        dh = _IFACE_DIR_HDR_RE.search(line)
        # a line that is ONLY a direction header (e.g. "- **Inputs**:") sets context
        if dh and not _IFACE_PORT_RE.search(line):
            d = dh.group("dir").lower()
            cur_dir = ("inout" if d.startswith("bidirectional") or d.startswith("inout")
                       else "output" if d.startswith("output") else "input")
            continue
        pm = _IFACE_PORT_RE.search(line)
        if not pm or cur_dir is None:
            continue
        name = pm.group("name")
        if name in seen:
            continue
        desc = (pm.group("desc") or "")
        # POLARITY, ON THE PORT'S OWN DESCRIPTION (vibe-ic#712). A prompt lists a
        # RETIRED port as readily as a live one, and this recovered it:
        #
        #     - `ready` (1 bit) — this port is no longer present
        #
        # came back as a live input, and this function feeds interface recovery,
        # so the phantom becomes a port on the generated module.
        #
        # THE DESCRIPTION, NOT A SENTENCE SCOPE. Each item here IS the record --
        # one port, one line, its own prose -- so the denial that belongs to this
        # port is the one written about it. A scope measured in characters would
        # reach into the neighbouring port's description and retire a live port
        # standing beside a dead one.
        if is_denied(desc):
            continue
        direction = "inout" if re.search(r"bidirectional", desc, re.IGNORECASE) else cur_dir
        width = None
        rng = pm.group("range")
        if rng:
            width = _width_from_range(rng, {})   # params unknown at prompt level; leave None if symbolic
        seen.add(name)
        ports.append({"name": name, "dir": direction, "width": width})
    # require at least a clk-ish + a data-ish port to trust it as a full interface
    return ports if len(ports) >= 2 else []


def recover_interface_from_text(text: str, target: str) -> List[dict]:
    """Recover [{name,dir,width}] for `target` from an ARBITRARY source text — the
    same header-only parse as `recover_interface`, but applied to a module header
    embedded anywhere (e.g. the partial RTL a cid002 completion ships INSIDE the
    prompt rather than in input.context). §4.05: this is still the INTERFACE the
    author is given (a real `module <target> ( … );` declaration in the input),
    never the golden body — we STOP at the port list. Returns [] when the target
    header is absent/unparseable. Chip-AGNOSTIC."""
    if not isinstance(text, str) or not text or not target:
        return []
    span = _find_module_span(text, target)
    if span is None:
        return []
    return _parse_one_span(span, target)




# ── general entry points ─────────────────────────────────────────────────────
def recover_from_files(paths: List[Path],
                       target: Optional[str] = None) -> Dict[str, object]:
    """Recover the port interface from RTL FILES. `target` names the module;
    when omitted, the first module declared across the files (in the given
    order) is used, which is the convention for a single-design directory."""
    texts = []
    for p in paths:
        try:
            texts.append(p.read_text(errors="replace"))
        except OSError:
            continue
    blob = "\n".join(texts)
    if not target:
        m = re.search(r"^\s*module\s+([A-Za-z_]\w*)", blob, re.M)
        target = m.group(1) if m else None
    if not target:
        return {"top_module": None, "top_ports": [], "source": "no-module-found"}
    ports = recover_interface_from_text(blob, target)
    return {"top_module": target, "top_ports": ports,
            "source": "rtl_header" if ports else "header-unparsed"}


def recover_from_dir(root: Path,
                     target: Optional[str] = None) -> Dict[str, object]:
    files = sorted(p for p in Path(root).rglob("*")
                   if p.is_file() and p.suffix in _RTL_SUFFIXES)
    return recover_from_files(files, target)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Recover a module's port interface from RTL.")
    ap.add_argument("--rtl", action="append", default=[],
                    help="RTL file (repeatable)")
    ap.add_argument("--rtl-dir", default=None, help="directory of RTL")
    ap.add_argument("--top", default=None, help="target module name")
    ap.add_argument("--json", default=None, help="write the result here")
    a = ap.parse_args(argv)
    if not a.rtl and not a.rtl_dir:
        print("ERROR: give --rtl or --rtl-dir", file=sys.stderr)
        return 2
    res = (recover_from_dir(Path(a.rtl_dir), a.top) if a.rtl_dir
           else recover_from_files([Path(x) for x in a.rtl], a.top))
    out = json.dumps(res, indent=2)
    print(out)
    if a.json:
        import _atomic_artefact as _atomic  # noqa: PLC0415
    _atomic.write_text(Path(a.json), out + "\n")
    return 0 if res["top_ports"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
