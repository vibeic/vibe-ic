#!/usr/bin/env python3
"""spec_complete_extract.py — the GENERAL (benchmark-agnostic) complete-spec
extraction + completeness engine.

WHY (owner directive 2026-06-26): the per-record completeness machinery that drove
CVDP from 210→229 COMPLETE is GENERAL — it parses Verilog/SystemVerilog SPEC PROSE
(widths, register maps, FSMs, enum sets, numeric packing, worked examples, reset
semantics, timing) and rolls every port into a COMPLETE / EXTRACTION_GAP /
SPEC_ABSENT verdict. None of that is CVDP-specific. The only CVDP-specific part is
RECOVERING THE INTERFACE from a CVDP record (its cocotb `dut.<sig>` harness + .env
TOPLEVEL + skeleton header). So the benchmark-convergence work BENEFITS GENERAL
PHASE-1 INPUT once the engine is callable with a plainly-supplied interface.

This module is that general engine. `cvdp_complete_extract` (and any future
VerilogEval / RTLLM / Phase-1 caller) becomes a THIN ADAPTER: recover the interface
in whatever way that source provides it, then call `assess_spec(...)`.

DESIGN — the interface signal set is an INPUT, not read from a harness:
  * CVDP adapter:    inputs/outputs = the cocotb `dut.<sig>` driven/read sets.
  * Phase-1 / doc:   inputs/outputs = the port list the L-docs / prose state.
  * VerilogEval:     inputs/outputs = the prose `### Inputs/Outputs` port list.
The cocotb harness TEXT (`tb`) is an OPTIONAL interface oracle (it pins a port to
1-bit when it drives {0,1}); when absent (`tb=""`) the engine relies on the prose
width forms + the universal clk/rst/1-bit naming convention + the param table.

§4.05 NO-LEAK / NO-CHEAT (inherited from the proven helpers): every emitted field
is anchored to a real structural source in the prose / supplied interface; a width
is resolved only from a stated form or a recognised parameter; an unresolved DATA
width is recorded as an honest gap, never fabricated.

The structural helpers themselves are the already-shipped, individually-tested
general extractors (`verilog_width_resolve`, `spec_{regmap,fsm,enumset,numeric_pack,
worked_example}_extract`) plus the width/reset/timing/one-bit readers. To avoid
duplicating ~800 proven lines, this engine IMPORTS those helpers from
`cvdp_complete_extract` (which is being thinned to an adapter over THIS module); the
helpers operate purely on strings, so the import carries no record coupling.

chip-AGNOSTIC: every decision keys on STRUCTURE + generic vocabulary, never on a
design name, a problem id, a dataset, or a SKU literal.

Public API
    assess_spec(prompt, inputs, outputs, *, module_name="", skeleton_iface=None,
                param_defaults=None, table=None, tb="", record_id=None) -> dict
        same shape as the old cvdp extract() spec dict (interface / structures /
        reset / timing / params / completeness / completeness_reason / gaps), but
        the interface is SUPPLIED, not recovered from a record.
"""
from __future__ import annotations

import os
import re
import sys
from typing import Dict, List, Optional, Tuple

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

# The proven general helpers live in cvdp_complete_extract (being thinned to an
# adapter over THIS engine). They are pure-string functions — no record coupling.
import cvdp_complete_extract as _impl  # noqa: E402
import verilog_width_resolve as _W  # noqa: E402
from _atomic_artefact import write_text as atomic_write_text  # vibe-ic#1082 (helper from PR #1094)


def _place_interface(prompt: str, inputs: List[str], outputs: List[str],
                     params: set, param_defaults: Dict[str, int],
                     table: Dict[str, int], ctx_widths: Dict[str, int],
                     tb: str) -> Tuple[List[dict], List[dict]]:
    """The GENERAL port-placement + gap-classification core (extracted verbatim
    from the proven `_complete_interface` body): for each interface signal, resolve
    its width from prose / param-expression / context header / clk-rst-1bit
    convention / harness 1-bit pin, else record an honest width gap. Returns
    (interface, gaps). Pure over the SUPPLIED interface — no record access."""
    import re
    signed = bool(re.search(
        r"(?i)\bsigned\b|two'?s?\s+complement|2'?s?\s+complement", prompt))
    config_params = set(params) | set(param_defaults) | set(
        re.findall(r"\bparameter\b\s+(?:\w+\s+)?([A-Za-z_]\w*)", prompt))
    iface: List[dict] = []
    gaps: List[dict] = []

    def _place(name: str, direction: str):
        if name in params or name in param_defaults:
            return  # a config parameter — not a port
        w, src = _impl._resolve_width(prompt, table, name, param_defaults)
        if w is not None:
            iface.append({"name": name, "dir": direction, "width": w,
                          "signed": signed, "source": src})
            return
        if name in ctx_widths:
            iface.append({"name": name, "dir": direction, "width": ctx_widths[name],
                          "signed": signed, "source": "context_header"})
            return
        if src == "param_expression_width":
            iface.append({"name": name, "dir": direction, "width": None,
                          "signed": signed, "source": "param_expression_width"})
            idents = _W.param_expr_idents(prompt, name)
            if idents and idents <= config_params:
                return  # PARAMETERISED-COMPLETE
            gaps.append({"kind": "INCOMPLETE_EXTRACTION_GAP",
                         "type": "param_expression_width",
                         "detail": f"{direction} port `{name}` width is a parameter "
                                   f"expression with no resolvable default",
                         "evidence": _impl._evidence_line(prompt, name)})
            return
        if _impl._is_clk(name) or _impl._is_rst(name):
            iface.append({"name": name, "dir": direction, "width": 1,
                          "signed": False, "source": "clk_rst_convention"})
            return
        # §3.9 HARNESS-as-source: the cocotb test drives this port with values
        # provably in {0,1} -> it is a 1-bit port pinned by the harness interface,
        # not a spec-absent fact. Check BEFORE the generic 1-bit naming convention
        # so the source tag reflects the STRONGER harness evidence (e.g. `serial_in`
        # driven by `random.randint(0,1)` is credited to the harness, not just the
        # name containing `serial`).
        if _impl._harness_one_bit(tb, name):
            iface.append({"name": name, "dir": direction, "width": 1,
                          "signed": False, "source": "harness_one_bit"})
            return
        if _impl._ONE_BIT_RE.match(name):
            iface.append({"name": name, "dir": direction, "width": 1,
                          "signed": False, "source": "one_bit_convention"})
            return
        gkind, gtype = _impl._classify_width_gap(prompt, name, params, param_defaults)
        gaps.append({"kind": gkind, "type": gtype,
                     "detail": f"{direction} port `{name}` width unresolved",
                     "evidence": _impl._evidence_line(prompt, name)})

    for n in inputs:
        _place(n, "input")
    for n in outputs:
        _place(n, "output")
    # de-dup by name (a signal read AND written keeps first dir)
    seen, dedup = set(), []
    for p in iface:
        if p["name"] in seen:
            continue
        seen.add(p["name"])
        dedup.append(p)
    return dedup, gaps


def _verdict(iface: List[dict], inputs: List[str], outputs: List[str],
             gaps: List[dict], have_oracle: bool) -> Tuple[str, str]:
    """Roll per-signal gaps into ONE completeness verdict (general; extracted from
    the proven `_completeness`). `have_oracle` is True when SOME interface source
    was present (a harness or a supplied port list) — distinguishes 'no interface
    to bind' (SPEC_ABSENT) from 'interface present but a width missed' (GAP)."""
    has_ext = any(g["kind"] == "INCOMPLETE_EXTRACTION_GAP" for g in gaps)
    has_abs = any(g["kind"] == "INCOMPLETE_SPEC_ABSENT" for g in gaps)
    if not inputs and not outputs and not iface:
        if not have_oracle:
            return "INCOMPLETE_SPEC_ABSENT", "no interface source to bind the ports"
        return ("INCOMPLETE_EXTRACTION_GAP",
                "interface source present but no port recovered")
    if has_ext:
        types = sorted({g["type"] for g in gaps
                        if g["kind"] == "INCOMPLETE_EXTRACTION_GAP"})
        return "INCOMPLETE_EXTRACTION_GAP", "missed fact(s): " + ", ".join(types)
    if has_abs:
        types = sorted({g["type"] for g in gaps
                        if g["kind"] == "INCOMPLETE_SPEC_ABSENT"})
        return ("INCOMPLETE_SPEC_ABSENT",
                "fact(s) absent from prompt prose + interface + convention: "
                + ", ".join(types))
    return ("COMPLETE",
            "every port placed (prose/param-expr/interface); stated structures captured")


# ===========================================================================
# GENERAL ADDITIVE PROSE-FACT EXTRACTORS (no gate / no block — pure readers).
#
# Each operates on a PLAIN prompt string and returns a structured fact (or None
# when the fact is absent / ambiguous), so a downstream conformance or authoring
# step carries the EXACT stated contract instead of guessing. Benchmark-agnostic:
# a Phase-1 doc with the same prose shape yields the same extraction. §4.05: every
# emitted value is anchored to a literal phrase in the prose; an unstated /
# unit-laden / ambiguous value is dropped (under-fire), never fabricated.
# ===========================================================================

# --- (1) EXPLICIT LATENCY CONTRACT ----------------------------------------
# A spec that pins its timing ("Total latency = WIDTH + 2 cycles", possibly with
# a per-step decomposition "1 cycle to register the inputs + N cycles in COMPUTE
# + 1 cycle to assert the output") states a CONTRACT the latency gate (#705) can
# resolve against the RTL. This surfaces it from prose as {total_expr, steps}.
# The total expression is kept VERBATIM (it may be a parameter expression the
# gate resolves later); never reduced to a number here.
# The total is a TIGHT expression: numbers / number-words / PARAMETER tokens
# (UPPER-case by convention — `(?-i:…)` keeps the case-sensitivity inside the
# overall case-insensitive pattern) joined by + - *. This refuses to swallow an
# English sentence fragment ("the module introduces a total latency of two") —
# only a real latency expression ("WIDTH + 2", "3", "two") matches.
_LAT_NUMWORD = r"(?:one|two|three|four|five|six|seven|eight|nine|ten)"
_LAT_TERM = r"(?:\d+|" + _LAT_NUMWORD + r"|(?-i:[A-Z][A-Za-z0-9_]*))"
_LAT_EXPR = (r"\(?\s*" + _LAT_TERM + r"(?:\s*[-+*]\s*" + _LAT_TERM + r")*\s*\)?")
_LATENCY_TOTAL_RE = re.compile(
    r"(?i)\b(?:total|overall|end[-\s]to[-\s]end|combined|aggregate)?\s*latency\b"
    r"\s*(?:=|:|is|of|equals?|will\s+be|shall\s+be|amounts?\s+to)\s*"
    r"(" + _LAT_EXPR + r")\s*(?:clock\s+)?cycles?\b")
# A per-step clause: "<count> cycle(s) <to|in|for|during> <description>". The
# count is a literal number, a number-word, or a PARAMETER token (UPPER_CASE /
# single capital, optionally `+N`) — never a lowercase quantifier like "few" /
# "several", which would not be an exact latency step.
_LATENCY_STEP_RE = re.compile(
    r"(?i)\b(?P<cyc>\d+|one|two|three|four|five|six|seven|eight|nine|ten"
    r"|[A-Z][A-Z0-9_]*(?:\s*[+\-]\s*\d+)?)\s+(?:clock\s+)?cycles?\s+"
    r"(?:to|in|for|during|spent)\s+"
    r"(?P<desc>[A-Za-z][^.,;\n+]{1,58}?)"
    r"(?=\s*(?:[.,;\n+]|\band\b|\bplus\b|\bthen\b|$))")


def extract_latency_contract(prompt: str) -> Optional[dict]:
    """Parse an EXPLICIT latency contract from spec prose.

    Returns ``{"total_expr": <str|None>, "steps": [{"cycles": <str>,
    "desc": <str>}, ...]}`` or ``None`` when no contract is stated.

    Conservative: a single "<n> cycles to <x>" clause with no latency context is
    NOT a contract (returns None) — a contract needs either a stated total, two+
    enumerated steps, or one step co-occurring with the word "latency"."""
    if not prompt:
        return None
    totals = []
    for m in _LATENCY_TOTAL_RE.finditer(prompt):
        expr = re.sub(r"\s+", " ", m.group(1)).strip()
        expr = re.sub(r"^\(\s*|\s*\)$", "", expr).strip()  # drop a wrapping paren
        if expr:
            totals.append(expr)
    # one distinct total -> use it; contradictory totals -> ambiguous (None).
    distinct = []
    for t in totals:
        if t.lower() not in [d.lower() for d in distinct]:
            distinct.append(t)
    total_expr = distinct[0] if len(distinct) == 1 else None

    steps: List[dict] = []
    seen = set()
    for m in _LATENCY_STEP_RE.finditer(prompt):
        cyc = re.sub(r"\s+", "", m.group("cyc"))
        desc = re.sub(r"\s+", " ", m.group("desc")).strip(" .,:;-")
        key = (cyc.lower(), desc.lower())
        if desc and key not in seen:
            seen.add(key)
            steps.append({"cycles": cyc, "desc": desc})

    if total_expr is None and not steps:
        return None
    has_latency_word = re.search(r"(?i)\blatency\b", prompt) is not None
    if total_expr is None and len(steps) < 2 and not has_latency_word:
        return None  # one isolated step with no latency framing — under-fire
    return {"total_expr": total_expr, "steps": steps}


# --- shared signal/clock helpers ------------------------------------------
def _norm_dir(tok: str) -> Optional[str]:
    """Normalise a direction token to input/output/inout, else None."""
    t = tok.strip().strip("`*").lower()
    if t in ("input", "in"):
        return "input"
    if t in ("output", "out"):
        return "output"
    if t in ("inout", "bidir", "bidirectional", "bidirection"):
        return "inout"
    return None


def _looks_like_clock_name(tok: str) -> bool:
    """True iff `tok` is an identifier that reads as a CLOCK signal name — it
    carries the universal `clk` substring (clk, clk_i, hclk, pclk, aclk, …) or a
    `clock`-with-affix form (clock_a, sys_clock). The bare English word "clock"
    is rejected (it is not a signal name)."""
    t = tok.strip().strip("`").lower()
    if not re.fullmatch(r"[a-z_]\w*", t):
        return False
    if "clk" in t:
        return True
    return "clock" in t and t != "clock"


def _split_md_row(line: str) -> List[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def _iter_md_tables(text: str):
    """Yield (header_cells, [row_cells, ...]) for every GitHub-flavoured pipe
    table — a header row, a `---|---` separator row, then data rows."""
    lines = text.splitlines()
    i, n = 0, len(lines)
    while i < n:
        line = lines[i]
        if (line.count("|") >= 1 and i + 1 < n
                and re.fullmatch(r"\s*\|?[\s:|-]*-[\s:|-]*\|?\s*", lines[i + 1])
                and "|" in lines[i + 1]):
            header = _split_md_row(line)
            rows = []
            j = i + 2
            while j < n and lines[j].strip() and lines[j].count("|") >= 1:
                rows.append(_split_md_row(lines[j]))
                j += 1
            yield header, rows
            i = j
        else:
            i += 1


def _col_index(header: List[str], pattern: str) -> Optional[int]:
    rx = re.compile(pattern, re.IGNORECASE)
    for idx, h in enumerate(header):
        if rx.search(h):
            return idx
    return None


def _clean_signal_name(cell: str) -> Optional[str]:
    """Strip backticks / a leading `[range]` width prefix and return a bare
    identifier, or None when the cell is not a single signal identifier."""
    s = cell.strip().strip("`").strip()
    s = re.sub(r"^\[[^\]]*\]\s*", "", s)            # drop a `[W-1:0]` prefix
    s = re.sub(r"\s*\[[^\]]*\]$", "", s)            # or a trailing `[W-1:0]`
    s = s.strip().strip("`")
    m = re.fullmatch(r"([A-Za-z_]\w*)", s)
    return m.group(1) if m else None


# --- (2) PORT-NAME / SIGNAL-NAME FROM A TABLE OR BULLET LIST ---------------
# A spec frequently NAMES its ports literally — in a signal-description table
# (| Signal | Dir | Width | Description |) or a backticked bullet list
# (- `s_ready`: handshake ready). Surfacing the EXACT name + direction (+ any
# clock binding) lets a downstream author/conformance step use the stated name
# rather than a guessed synonym (`s_ready` vs `ready_s`). chip-AGNOSTIC.
_PORT_BULLET_RE = re.compile(
    r"(?im)^\s*[-*]\s+(?P<body>.+?)\s*$")
_PORT_BODY_RE = re.compile(
    r"^(?P<bt>`)?(?P<wpre>\[[^\]]*\]\s*)?(?P<name>[A-Za-z_]\w*)`?"
    r"\s*(?:\((?P<dir1>[^)]*)\))?\s*[:\-–]\s*(?P<desc>.+)$")
_DESC_DIR_RE = re.compile(r"(?i)\b(input|output|inout)\b")
_DESC_CLK_RE = re.compile(
    r"(?i)\b(?:synchronous\s+to|sync(?:hronou)?s?\s+to|clocked\s+by|on\s+the|"
    r"in\s+the|driven\s+by)\s+`?(?P<clk>[A-Za-z_]\w*)`?")


def _desc_clock(desc: str, self_name: str) -> Optional[str]:
    m = _DESC_CLK_RE.search(desc)
    if m and _looks_like_clock_name(m.group("clk")) and m.group("clk") != self_name:
        return m.group("clk")
    return None


def extract_port_signals(prompt: str) -> Optional[dict]:
    """Extract literally-named ports from a signal table or a backticked bullet
    list. Returns ``{"ports": [{"name", "dir", "width"?, "clock"?, "desc"?,
    "source"}]}`` or ``None`` when none are named.

    Conservative: a table is read as a signal table only when it has a name/port
    column AND a direction OR width column; a bullet counts as a port only when
    the name is backticked, carries a `[width]` prefix, or a direction is stated
    — ordinary prose bullets ("- Note: …") are ignored."""
    if not prompt:
        return None
    ports: List[dict] = []
    seen = set()

    def _add(name, direction, width, clock, desc, source):
        if not name or name in seen:
            return
        seen.add(name)
        p = {"name": name, "dir": direction, "source": source}
        if width is not None:
            p["width"] = width
        if clock:
            p["clock"] = clock
        if desc:
            p["desc"] = desc
        ports.append(p)

    # -- table form --
    for header, rows in _iter_md_tables(prompt):
        name_col = _col_index(header, r"\b(signal|port|name|pin)\b")
        dir_col = _col_index(header, r"\b(direction|dir|i\s*/?\s*o|in\s*/?\s*out|mode)\b")
        width_col = _col_index(header, r"\b(width|bits?|size)\b")
        desc_col = _col_index(header, r"\b(description|desc|function|meaning|comment|notes?)\b")
        clk_col = _col_index(header, r"\b(clock|clk|domain)\b")
        if name_col is None or (dir_col is None and width_col is None):
            continue
        for cells in rows:
            if name_col >= len(cells):
                continue
            name = _clean_signal_name(cells[name_col])
            if not name:
                continue
            direction = None
            if dir_col is not None and dir_col < len(cells):
                direction = _norm_dir(cells[dir_col])
            if direction is None:
                for c in cells:
                    direction = _norm_dir(c)
                    if direction:
                        break
            width = None
            if width_col is not None and width_col < len(cells):
                wm = re.search(r"\d+", cells[width_col])
                if wm:
                    width = int(wm.group(0))
            desc = (cells[desc_col].strip() if desc_col is not None
                    and desc_col < len(cells) else None)
            clock = None
            if clk_col is not None and clk_col < len(cells):
                cand = _clean_signal_name(cells[clk_col])
                if cand and _looks_like_clock_name(cand) and cand != name:
                    clock = cand
            _add(name, direction, width, clock, desc or None, "table")

    # -- bullet form --
    for bm in _PORT_BULLET_RE.finditer(prompt):
        body = bm.group("body")
        if "|" in body:
            continue  # a table cell leaked through — handled above
        m = _PORT_BODY_RE.match(body)
        if not m:
            continue
        name = m.group("name")
        backticked = bool(m.group("bt"))
        has_wpre = bool(m.group("wpre"))
        desc = m.group("desc").strip()
        direction = _norm_dir(m.group("dir1") or "") if m.group("dir1") else None
        if direction is None:
            dm = _DESC_DIR_RE.search(desc)
            if dm:
                direction = _norm_dir(dm.group(1))
        if not (backticked or has_wpre or direction is not None):
            continue  # ordinary prose bullet, not a named port
        width = None
        if has_wpre:
            wm = re.search(r"\d+", m.group("wpre"))
            if wm:
                width = int(wm.group(0))
        clock = _desc_clock(desc, name)
        _add(name, direction, width, clock, desc, "bullet")

    return {"ports": ports} if ports else None


# --- (3) CLOCK-DOMAIN BINDING ---------------------------------------------
# A multi-clock spec binds each named clock to a protocol side / domain
# ("clk_i: Wishbone", "hclk: AHB clock", "clk_i: Clock for the Wishbone side").
# Returning {clock_name: domain} gives a CDC / unused-clock check ground truth
# for which clock belongs to which side. chip-AGNOSTIC: keyed on the universal
# clk naming convention + a stated domain label, never an IC/SKU literal.
_CLK_LINE_RE = re.compile(
    r"(?im)^\s*[-*]?\s*`?(?P<clk>[A-Za-z_]\w*)`?\s*[:\-–]\s*(?P<desc>.+?)\s*$")
_CLK_IS_DOMAIN_RE = re.compile(
    r"(?i)\b`?(?P<clk>[A-Za-z_]\w*)`?\s+is\s+(?:the\s+)?"
    r"(?P<dom>[A-Za-z][\w./-]*(?:\s+[A-Za-z][\w./-]*){0,2}?)"
    r"[\s-]+(?:side\s+)?clock\b")
_DOMAIN_CLOCKED_BY_RE = re.compile(
    r"(?i)\b(?P<dom>[A-Za-z][\w./-]*(?:\s+[A-Za-z][\w./-]*){0,2}?)\s+"
    r"(?:side\s+|domain\s+|interface\s+)?(?:is\s+)?clocked\s+by\s+"
    r"`?(?P<clk>[A-Za-z_]\w*)`?")
_NON_DOMAIN_RE = re.compile(
    r"(?i)\b(?:free|running|at|mhz|ghz|khz|hz|ns|ps|us|ms|cycles?|period|"
    r"frequency|freq|rate|edge|rising|falling|active|positive|negative|high|"
    r"low|global|main|internal|external|gated|divided|generated|derived|same|"
    r"reference|sequential|local)\b")
# trailing DESCRIPTION nouns ("Wishbone operations" / "AHB logic") that are not
# part of the domain name itself — stripped from the tail.
_DOMAIN_TRAIL_RE = re.compile(
    r"(?i)\s*\b(?:operations?|logic|functionality|function|processing|"
    r"access(?:es)?|controller|control|core|block|module|unit|engine|"
    r"transactions?|transfers?)\b\s*$")


def _clean_domain(desc: str) -> Optional[str]:
    """Reduce a clock's description to its protocol-side / domain LABEL, or None
    when the description is not a clean domain.

    A genuine domain is a PROPER NOUN / ACRONYM (Wishbone, AHB, GMII, SDRAM,
    System); so after stripping connectives, qualifier words ("clock"/"domain"/
    "side"), and trailing description nouns ("operations"/"logic"), the result
    must (a) be <=3 words and <=24 chars, (b) carry NO unit/edge/frequency/filler
    token, and (c) contain at least one UPPER-case letter. A lowercase phrase
    ("sequential operation", "the local") therefore drops (§4.05 under-fire)."""
    _conn = r"(?:the|a|an|for|of|to|on|in|with|its|used\s+by|driving|that|which)"
    d = desc.strip().strip(".").strip()
    # leading "clock for/of the …"
    d = re.sub(r"(?i)^(?:the\s+)?clock\s+(?:for|of|on|to|driving|used\s+by)\s+"
               r"(?:the\s+)?", "", d)
    # qualifier words anywhere ("clock"/"signal"/"input"/…) — may EXPOSE a
    # leading connective ("Clock signal for GMII" -> " for GMII").
    d = re.sub(r"(?i)\b(?:clock|clk|domain|side|interface|signal|bus|input|"
               r"output|line|port)\b", "", d)
    d = re.sub(r"\s{2,}", " ", d).strip(" ,;:_-")
    # strip leading connective words now possibly exposed
    for _ in range(3):
        nd = re.sub(r"(?i)^" + _conn + r"\s+", "", d)
        if nd == d:
            break
        d = nd
    # the domain NAME is the leading proper-noun token(s); a connective marks the
    # start of a description tail ("APB for synchronous" -> "APB") — truncate it.
    d = re.split(r"(?i)\s+" + _conn + r"\s+", d, 1)[0].strip()
    # trailing description nouns ("Wishbone operations" -> "Wishbone")
    for _ in range(3):
        nd = _DOMAIN_TRAIL_RE.sub("", d)
        if nd == d:
            break
        d = nd
    d = re.sub(r"^[\s.,;:_-]+|[\s.,;:_-]+$", "", re.sub(r"\s{2,}", " ", d))
    if not d or len(d) > 24 or len(d.split()) > 3:
        return None
    if _NON_DOMAIN_RE.search(d):
        return None
    if not re.match(r"[A-Za-z]", d):
        return None
    if not re.search(r"[A-Z]", d):   # a domain name is a proper noun / acronym
        return None
    return d


def extract_clock_domains(prompt: str) -> Optional[dict]:
    """Extract a ``{clock_name: domain}`` binding map from spec prose. Returns
    None when no clock is bound to a named domain.

    Conservative: the key must read as a clock signal name (`_looks_like_clock_name`)
    and the value must be a clean domain label (`_clean_domain` drops frequencies /
    edges / units). First binding for a clock wins."""
    if not prompt:
        return None
    out: Dict[str, str] = {}

    def _bind(clk, dom):
        if clk and dom and _looks_like_clock_name(clk) and clk not in out:
            out[clk] = dom

    # -- table form: a clock-domain table --
    for header, rows in _iter_md_tables(prompt):
        clk_col = _col_index(header, r"\b(clock|clk)\b")
        dom_col = _col_index(header, r"\b(domain|side|interface|protocol|bus|source)\b")
        if clk_col is None or dom_col is None:
            continue
        for cells in rows:
            if clk_col >= len(cells) or dom_col >= len(cells):
                continue
            clk = _clean_signal_name(cells[clk_col])
            dom = _clean_domain(cells[dom_col])
            _bind(clk, dom)

    # -- bullet / colon line form: `clk_i: Wishbone` / `hclk: AHB clock` --
    for m in _CLK_LINE_RE.finditer(prompt):
        clk = m.group("clk")
        if not _looks_like_clock_name(clk):
            continue
        dom = _clean_domain(m.group("desc"))
        _bind(clk, dom)

    # -- inline prose forms --
    for m in _CLK_IS_DOMAIN_RE.finditer(prompt):
        _bind(m.group("clk"), _clean_domain(m.group("dom")))
    for m in _DOMAIN_CLOCKED_BY_RE.finditer(prompt):
        _bind(m.group("clk"), _clean_domain(m.group("dom")))

    return out or None


def assess_spec(prompt: str, inputs: List[str], outputs: List[str], *,
                module_name: str = "", skeleton_iface: Optional[List[dict]] = None,
                param_defaults: Optional[Dict[str, int]] = None,
                table: Optional[Dict[str, int]] = None, tb: str = "",
                params: Optional[set] = None,
                ctx_widths: Optional[Dict[str, int]] = None,
                record_id=None) -> dict:
    """GENERAL completeness assessment over a SUPPLIED interface.

    prompt          — the design-doc / spec prose (any benchmark or Phase-1 doc).
    inputs/outputs  — the interface signal NAMES (however the caller obtained them:
                      cocotb dut.<sig>, an L-doc port list, prose ### Inputs/Outputs).
    skeleton_iface  — OPTIONAL fully-described port list [{name,dir,width,...}] (a
                      module header); when given it is the interface verbatim and
                      port placement is skipped (nothing to resolve).
    param_defaults  — OPTIONAL NAME->int param table; default: parsed from `prompt`.
    table           — OPTIONAL test-case hex-column width table; default: {}.
    tb              — OPTIONAL cocotb harness text (the 1-bit {0,1}-drive oracle).
    params          — OPTIONAL recognised config-parameter set (harness-driven).
    ctx_widths      — OPTIONAL name->width from a provided context module header.

    Returns the spec dict (same shape as the historical cvdp extract())."""
    if param_defaults is None:
        param_defaults = _W.param_defaults(prompt, tb)
    if table is None:
        table = {}
    if params is None:
        params = set()
    if ctx_widths is None:
        ctx_widths = {}

    structures = _impl._structures(prompt)
    timing = _impl._timing(prompt)

    if skeleton_iface is not None:
        iface = skeleton_iface
        gaps: List[dict] = []
    else:
        iface, gaps = _place_interface(
            prompt, inputs, outputs, params, param_defaults, table, ctx_widths, tb)

    have_oracle = bool(inputs or outputs or skeleton_iface or tb)
    completeness, reason = _verdict(iface, inputs, outputs, gaps, have_oracle)

    return {
        "id": record_id,
        "module_name": module_name or None,
        "interface": iface,
        "operation_family": _impl._operation_family(prompt),
        "params": _impl._prompt_params(prompt),
        "structures": structures,
        "reset": _impl._reset_semantics(prompt, inputs),
        "timing": timing,
        "byte_order": _impl._byte_order(prompt),
        "completeness": completeness,
        "completeness_reason": reason,
        "gaps": gaps,
        # additive prose-fact extractors (None when the fact is absent) — carry
        # the stated contract into downstream authoring/conformance, never gate.
        "latency_contract": extract_latency_contract(prompt),
        "port_signals": extract_port_signals(prompt),
        "clock_domains": extract_clock_domains(prompt),
        "interface_source": {
            "module_name": module_name or None,
            "inputs": list(inputs),
            "outputs": list(outputs),
            "params": sorted(params),
        },
    }


def main(argv: Optional[List[str]] = None) -> int:
    """CLI: assess a single design-doc file with an explicitly-supplied port list.
    For benchmark jsonl distributions, use the per-benchmark adapter's CLI (e.g.
    `cvdp_complete_extract.py --jsonl ...`)."""
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--doc", required=True, help="a design-doc / spec prose file")
    ap.add_argument("--inputs", default="", help="comma-separated input port names")
    ap.add_argument("--outputs", default="", help="comma-separated output port names")
    ap.add_argument("--json", default=None, help="write the spec dict here")
    a = ap.parse_args(argv)
    import json
    prompt = open(a.doc).read()
    ins = [s.strip() for s in a.inputs.split(",") if s.strip()]
    outs = [s.strip() for s in a.outputs.split(",") if s.strip()]
    spec = assess_spec(prompt, ins, outs)
    out = json.dumps(spec, indent=2, ensure_ascii=False)
    if a.json:
        atomic_write_text(a.json, out + "\n")
    print(f"completeness: {spec['completeness']}")
    print(f"reason: {spec['completeness_reason']}")
    if spec["gaps"]:
        print("gaps:")
        for g in spec["gaps"]:
            print(f"  {g['kind']} {g['type']}: {g['detail']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
