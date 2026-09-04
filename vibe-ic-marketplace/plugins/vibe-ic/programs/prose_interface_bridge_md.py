#!/usr/bin/env python3
"""prose_interface_bridge_md.py — read a MARKDOWN-table interface block.

A GENERAL prose-port-block reader, sibling to `prose_port_block_read` (which
reads the indented-bullet form). `port_parser.parse_ports` already understands
two interface shapes; a spec that states its ports as a markdown table is a
third, and this bridges it to a form the shared parser reads.

WHY THE NAME CHANGED. This shipped as `prose_interface_bridge_md` because a CVDP capture
campaign is where the markdown-table form was first hit. Its own first line
called it "a GENERAL prose-port-block reader" — and it is: `bridge_prompt(text)
-> str` takes prose and returns prose, with no record field anywhere. Under the
benchmark prefix, nothing outside that benchmark could find it: it had ZERO
importers, which is not evidence it is useless but evidence it was never wired.
The sibling with the same signature has 13.

WHY (owner directive 2026-06-23, "program-first PARSING on CVDP"):
The shared `port_parser.parse_ports` understands two interface forms — the
VerilogEval-v2 bullet (` - input a (8 bits)`) and the Verilog module header
(`module TopModule ( input [7:0] a, ... );`). CVDP `Specification to RTL
Translation` prompts state their interface in a THIRD family of regular markdown
forms that `parse_ports` returns ([],[]) on:

    ### Inputs                          <- a section header scopes the direction
    - [7:0] in: An 8-bit input vector.  <- range-prefix bullet
    ### Outputs
    - **`data_out`** (8-bits, [7:0]): ...   <- bold name + width-paren + range
    - **`clk`** (1-bit): ...                <- bold name + width-paren (1-bit)
    - `q ([3:0])`: ...                      <- backticked name + parenthesized range

Because `parse_ports` returned ([],[]) on these, every registry deterministic
recognizer (which first calls `parse_ports`) SKIPped them, and the dual_pass
interface extraction was empty/wrong for these forms. This module reads the CVDP
section-scoped markdown interface and RE-EMITS it as the VerilogEval bullet form,
so `bridge_prompt(text)` can be fed straight into the existing
`spec_artifact_registry.detect/generate` or `spec_artifact_dual_pass` chain
WITHOUT touching any existing file — the consumers keep seeing the full original
prose for their body semantics; they additionally now see a leading bullet port
block they can parse.

This is a GENERAL FORMAT READER, not keyed to any CVDP design name:
  * Direction comes from a SECTION HEADER ("### Inputs" / "#### Outputs:" /
    "Inputs:" / "Input ports:"), never from a module name. Per-line bullets
    inside a section inherit that section's direction.
  * The COMPLETE-audit reader resolves literal ranges, numeric/spelled widths,
    prompt-declared parameter expressions, and scalar declarations. Unresolved or
    contradictory expressions are dropped. The historical solver bridge retains
    its narrower literal-width policy, so this audit does not silently broaden a
    downstream RTL generator.
  * It NEVER reads a golden/reference solution: input is the prompt text only.

HONEST SCOPE (measured, not claimed): bridging the CVDP port form makes the
interface readable, but on the CVDP corpus it does NOT, by itself, unlock the
registry's deterministic RTL generators — the registry body recognizers
(priority encoder = LSB-first-only, vector_ops, shift_register, …) are tightly
§4.05-bound to the VerilogEval phrasings and SKIP CVDP's bodies (e.g. CVDP's 8x3
priority encoder is MSB-first, outside the synth envelope). The win here is
correct INTERFACE structured-JSON for the dual_pass extraction tier, plus making
any genuinely-in-envelope body (should one appear) reachable. See the module's
self-test (`--measure`) and the FINAL REPORT for the exact numbers.

Pure-function module. chip-AGNOSTIC, deterministic, prompt-blind.
"""
from __future__ import annotations

import re
import sys
from functools import lru_cache
from pathlib import Path
from typing import List, Optional, Tuple

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import verilog_width_resolve as _width  # noqa: E402

# A section header that scopes the direction of the bullets beneath it.
# Markdown headings (### Inputs), bold (**Inputs**:), a bullet header (- Inputs:),
# or a plain "Inputs:" / "Input ports:" label on its own line.
_SEC_RE = re.compile(
    r"^\s*(?:#{1,6}\s*|[-*]\s*)?\*{0,2}\s*(Input|Output)s?(?:\s+ports?)?\s*\*{0,2}\s*:?\s*$",
    re.I)
# Verilog direction keywords that can lead a backticked/bold port decl
# (`input [31:0] num_in`); when present they BOTH set the line's direction AND
# must be skipped to reach the real identifier.
_DIR_KW_RE = re.compile(r"\b(input|output|inout)\b", re.I)
# Any OTHER markdown heading ends the current section's scope.
_OTHER_HEADING_RE = re.compile(r"^\s*#{1,6}\s+\S")
# A bullet line (markdown - or *).
_BULLET_RE = re.compile(r"^\s*[-*]\s+(.*\S)\s*$")
# Explicit literal bus range [hi:lo], plus the general bracket-range shape used
# to distinguish a scalar declaration from a parameter-sized declaration.
_RANGE_RE = re.compile(r"\[\s*(\d+)\s*:\s*(\d+)\s*\]")
_ANY_RANGE_RE = re.compile(r"\[[^\]\n]*:[^\]\n]*\]")
# Width paren token "(8-bit)" / "(8 bits)" / "(1-bit)".
_PAREN_W_RE = re.compile(r"\(\s*(\d+)\s*-?\s*bits?\b", re.I)
# Inline "N-bit" width token.
_NBIT_RE = re.compile(r"\b(\d+)\s*-?\s*bits?\b", re.I)
# Spelled single-bit.
_ONEBIT_RE = re.compile(r"\b(one|single)\s*-?\s*bit\b", re.I)
# A parenthesized parameter width: (`DATA_WIDTH` bits), (`N*IN_WIDTH`), or
# (DATA_WIDTH). Upper-case parameter grammar is deliberate: ordinary prose
# parentheticals such as "(active low)" are not width declarations.
_PARAM_WIDTH_RE = re.compile(
    r"\(\s*`?([A-Z][A-Z0-9_]*(?:\s*[*+/\-]\s*[A-Z0-9_]+)*)`?"
    r"\s*(?:bits?)?\s*\)")
# A Verilog sized number literal: 14'b001.. / 8'hAB / 2'd3 (a VALUE, never a port name).
_VERILOG_LITERAL_RE = re.compile(r"\d+\s*'\s*[bBoOdDhH]", re.I)
# A header-label word we must never treat as a port name (markdown table headers).
_HEADER_WORDS = {"name", "width", "description", "signal", "port", "direction",
                 "bit", "bits", "type", "default", "constraint", "constraints"}

# Sentinel: a width token is present but ambiguous (>=2 contradictory). Distinct
# from None (no width token at all -> drop, we never default-guess in CVDP since a
# missing width here usually means a parameter expression we cannot resolve).
_AMBIGUOUS = object()


def _strip_lead_dir(token_region: str) -> str:
    """Drop a leading Verilog `input/output/inout` keyword (and an optional
    net-type + [hi:lo] range) so the FIRST remaining identifier is the port name,
    not the direction keyword. `input [31:0] num_in` -> `[31:0] num_in`."""
    return re.sub(r"^\s*(?:input|output|inout)\b\s*", "", token_region, flags=re.I)


def _port_name(bullet: str) -> Optional[str]:
    """The Verilog identifier a CVDP port bullet names — read ONLY from a DELIMITED
    token so a prose sentence is never mistaken for a port (§4.05). Accepted forms,
    in order:
      * a backticked id `name` / `input [31:0] name` / `name ([..])`  (incl. inside
        bold **`name`**, since the backtick is what we key on);
      * a `[hi:lo] name` range-prefix at the START of the bullet.
    A bold-WITHOUT-backtick phrase (**OUTPUT state**) or a bare leading word is
    REJECTED — those are prose, not a port declaration. Returns None if no
    delimited identifier is present (bullet dropped, not guessed)."""
    # The name token must LEAD the bullet (a port decl names the port first, before
    # its ':' description) — a backtick buried mid-sentence (a value reference such
    # as "lower 14 bits of `0x1234`") is never a port name. An optional leading
    # bold/`**` wrapper is allowed.
    head = re.match(r"^\s*\**\s*`([^`]*)`", bullet)   # leading (bold) backtick span
    if head:
        span = head.group(1)
        if _VERILOG_LITERAL_RE.search(span) or "=" in span or "0x" in span.lower():
            return None                   # value literal/assignment, not an identifier
        inner = _strip_lead_dir(span)
        # inner may now be "[31:0] num_in" / "[WIDTH-1:0] num_in" /
        # "num_in[31:0]" / "num_in".  A range-prefix declaration's NAME is
        # after the whole bracket span; taking the first identifier would return
        # WIDTH/DATA_WIDTH, turning a parameter into a phantom port.
        nm = re.match(
            r"\s*(?:\[[^\]\n]*:[^\]\n]*\]\s*)?([A-Za-z_]\w*)", inner)
        if nm:
            return nm.group(1)
        return None
    # range-prefix at the start of the bullet: [7:0] name
    m = re.match(r"^\s*\[\s*\d+\s*:\s*\d+\s*\]\s*([A-Za-z_]\w*)", bullet)
    if m:
        return m.group(1)
    return None


def _line_direction(bullet: str) -> Optional[str]:
    """An explicit per-line direction keyword INSIDE the port token (backtick/bold),
    e.g. `input [31:0] num_in` -> 'input'. Returns None when the bullet carries no
    such keyword (then the enclosing section's direction applies)."""
    m = re.search(r"`([^`]*)`", bullet) or re.search(r"\*\*\s*(.+?)\s*\*\*", bullet)
    region = m.group(1) if m else ""
    dm = re.match(r"^\s*(input|output|inout)\b", region, re.I)
    return dm.group(1).lower() if dm else None


def _port_width(bullet: str, prompt: str, name: str, params):
    """Single positive-integer width for a CVDP port bullet, or _AMBIGUOUS, or None.

    Literal and prompt-resolvable symbolic declarations are accepted. Conflicting
    tokens return _AMBIGUOUS; unresolved symbolic declarations return None. A
    delimited port declaration with no packed range is a scalar declaration."""
    widths = set()
    rm = _RANGE_RE.search(bullet)
    if rm:
        widths.add(abs(int(rm.group(1)) - int(rm.group(2))) + 1)
    elif _ANY_RANGE_RE.search(bullet):
        # A parameter expression is usable only when every identifier resolves
        # from a default stated in this same prompt. `symbolic_width` handles
        # both `[P-1:0] name` and `name[P-1:0]`, including arithmetic such as
        # `[(DATA_WIDTH/8)-1:0]`; an unresolved expression drops the port.
        resolved = _width.symbolic_width(prompt, name, params)
        if resolved is None:
            return None
        _symbolic, value, _source = resolved
        widths.add(value)
    pm = _PAREN_W_RE.search(bullet)
    if pm:
        widths.add(int(pm.group(1)))
    if not widths:
        # only consult spelled / inline tokens when no explicit range/paren width
        if _ONEBIT_RE.search(bullet):
            widths.add(1)
        for m in _NBIT_RE.finditer(bullet):
            widths.add(int(m.group(1)))
    if not widths:
        pm = _PARAM_WIDTH_RE.search(bullet)
        if pm:
            value = _width.eval_width_expr(pm.group(1), params)
            if value is None or value < 1:
                return None
            widths.add(value)
    if not widths:
        # A delimited name under an explicit Inputs/Outputs section with no
        # packed range is a scalar port declaration. The width is therefore
        # stated by the absence of a range (one bit), not guessed from a signal
        # naming convention. `_port_name` has already rejected undelimited
        # prose/category bullets and value literals before this point.
        return 1
    if len(widths) > 1:
        return _AMBIGUOUS
    w = next(iter(widths))
    return w if w >= 1 else _AMBIGUOUS


def _legacy_port_width(bullet: str):
    """The deliberately narrow width policy used by the historical bridge.

    Keep the bridge byte-for-byte conservative for existing solver callers; the
    COMPLETE reader below is an audit surface and does not silently broaden every
    solver that imports the bridge chain."""
    widths = set()
    rm = _RANGE_RE.search(bullet)
    if rm:
        widths.add(abs(int(rm.group(1)) - int(rm.group(2))) + 1)
    pm = _PAREN_W_RE.search(bullet)
    if pm:
        widths.add(int(pm.group(1)))
    if not widths:
        if _ONEBIT_RE.search(bullet):
            widths.add(1)
        for m in _NBIT_RE.finditer(bullet):
            widths.add(int(m.group(1)))
    if not widths:
        return None
    if len(widths) > 1:
        return _AMBIGUOUS
    w = next(iter(widths))
    return w if w >= 1 else _AMBIGUOUS


def _legacy_md_table_ports(text: str):
    """Historical bridge parse: literal widths only, preserved for callers."""
    ins: List[Tuple[str, int]] = []
    outs: List[Tuple[str, int]] = []
    seen = set()
    cur: Optional[str] = None
    for raw in text.splitlines():
        sm = _SEC_RE.match(raw)
        if sm:
            cur = "input" if sm.group(1).lower().startswith("input") else "output"
            continue
        if cur and _OTHER_HEADING_RE.match(raw):
            cur = None
            continue
        bm = _BULLET_RE.match(raw)
        if not bm:
            continue
        bullet = bm.group(1)
        direction = _line_direction(bullet) or cur
        if not direction:
            continue
        name = _port_name(bullet)
        if not name or name.lower() in _HEADER_WORDS or name in seen:
            continue
        w = _legacy_port_width(bullet)
        if w is None or w is _AMBIGUOUS:
            continue
        (ins if direction == "input" else outs).append((name, w))
        seen.add(name)
    return ins, outs


@lru_cache(maxsize=64)
def parse_md_table_ports(text: str) -> Tuple[List[Tuple[str, int]], List[Tuple[str, int]]]:
    """A COMPLETE section-scoped Markdown interface read.

    Scalar declarations are one bit; parameter ranges resolve only from defaults
    in ``text``. Within one section, only the shallowest parseable bullet depth is
    an interface declaration. This retains grouped lists (all ports at one nested
    depth) while rejecting deeper enum/example bullets under a real port."""
    ins: List[Tuple[str, int]] = []
    outs: List[Tuple[str, int]] = []
    seen = set()
    params = _width.param_defaults(text)
    cur: Optional[str] = None
    section: List[Tuple[int, str, str, int]] = []

    def _flush():
        nonlocal section
        if not section:
            return
        min_indent = min(row[0] for row in section)
        for indent, direction, name, width in section:
            if indent != min_indent or name in seen:
                continue
            (ins if direction == "input" else outs).append((name, width))
            seen.add(name)
        section = []

    for raw in text.splitlines():
        sm = _SEC_RE.match(raw)
        if sm:
            _flush()
            cur = "input" if sm.group(1).lower().startswith("input") else "output"
            continue
        if cur and _OTHER_HEADING_RE.match(raw):
            _flush()
            cur = None
            continue
        bm = _BULLET_RE.match(raw)
        if not bm:
            continue
        bullet = bm.group(1)
        # An inline direction keyword (`input [31:0] num_in`) is authoritative and
        # also lets a directionless prompt body work even outside a section.
        line_dir = _line_direction(bullet)
        direction = line_dir or cur
        if not direction:
            continue
        name = _port_name(bullet)
        if not name or name.lower() in _HEADER_WORDS or name in seen:
            continue
        w = _port_width(bullet, text, name, params)
        if w is None or w is _AMBIGUOUS:
            continue                      # §4.05: never fabricate a width
        indent = len(raw) - len(raw.lstrip())
        if cur:
            section.append((indent, direction, name, w))
        elif name not in seen:
            (ins if direction == "input" else outs).append((name, w))
            seen.add(name)
    _flush()
    return ins, outs


def _emit_bullets(ins, outs) -> str:
    lines = []
    for name, w in ins:
        lines.append(f" - input {name} ({w} bits)" if w != 1 else f" - input {name}")
    for name, w in outs:
        lines.append(f" - output {name} ({w} bits)" if w != 1 else f" - output {name}")
    return "\n".join(lines)


def bridge_prompt(text: str) -> str:
    """Return `text` with an equivalent VerilogEval bullet port block PREPENDED, so
    the existing `port_parser.parse_ports` reads the interface while every consumer
    still sees the full original prose for its body semantics.

    If no CVDP interface section with parseable bullets is found, returns `text`
    unchanged (a no-op bridge — the consumer chain then behaves exactly as before,
    e.g. falls back to a Verilog header it may already contain)."""
    ins, outs = _legacy_md_table_ports(text)
    if not ins and not outs:
        return text
    return _emit_bullets(ins, outs) + "\n\n" + text


def interface_json(text: str) -> dict:
    """Structured interface JSON for the dual_pass extraction tier:
    {inputs:[{name,width}], outputs:[...]}. Empty lists when nothing parses."""
    ins, outs = parse_md_table_ports(text)
    return {"inputs": [{"name": n, "width": w} for n, w in ins],
            "outputs": [{"name": n, "width": w} for n, w in outs]}


def main(argv=None) -> int:
    import argparse
    import json
    from pathlib import Path
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--prompt", help="CVDP-style prompt text file")
    ap.add_argument("--emit-bridged", action="store_true",
                    help="print the bridged prompt (bullets + original) instead of JSON")
    ap.add_argument("--measure", metavar="JSONL",
                    help="measure interface-extraction + registry-emit over a "
                         "prompts_export.jsonl (id/system/user rows)")
    a = ap.parse_args(argv)
    if a.measure:
        return _measure(a.measure)
    if not a.prompt:
        ap.error("--prompt or --measure required")
    text = Path(a.prompt).read_text(errors="replace")
    if a.emit_bridged:
        print(bridge_prompt(text))
        return 0
    print(json.dumps(interface_json(text), indent=2))
    return 0


def _measure(jsonl_path: str) -> int:
    """Self-measurement harness (also the data behind the FINAL REPORT). For each
    prompt: does the bridge extract a both-sided interface? Does the registry now
    emit RTL (it should not, on this corpus — reported honestly)?"""
    import json
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    rows = [json.loads(l) for l in Path(jsonl_path).read_text().splitlines() if l.strip()]

    def cat(r):
        s = r.get("system", "")
        for key, c in (("Specification to RTL Translation", "spec2rtl"),
                       ("RTL Code Completion", "completion"),
                       ("RTL Code Modification", "modification"),
                       ("RTL Lint Improvement or Power-Performance", "lint_ppa"),
                       ("RTL Debugging and Bug Fixing", "debug")):
            if key in s:
                return c
        return "other"

    try:
        import spec_artifact_registry as REG
    except Exception:
        REG = None
    from collections import Counter
    tot, both, emit = Counter(), Counter(), Counter()
    for r in rows:
        c = cat(r)
        tot[c] += 1
        text = r.get("user", "")
        ins, outs = parse_md_table_ports(text)
        if ins and outs:
            both[c] += 1
        if REG is not None:
            bridged = bridge_prompt(text)
            try:
                k, rtl = REG.generate(bridged, "TopModule")
            except Exception:
                rtl = None
            if rtl:
                emit[c] += 1
    out = {"total": dict(tot),
           "interface_both_sided": dict(both),
           "registry_rtl_emitted_after_bridge": dict(emit)}
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
