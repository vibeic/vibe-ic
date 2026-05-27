#!/usr/bin/env python3
"""_specrtl_common.py — shared Spec↔RTL parsing primitives.

Single source of truth for the Spec↔RTL *contract conformance* family
(`spec_conformance_check.py`, `spec_rtl_port_fidelity_check.py`). A "spec
contract" is what the datasheet / L-docs / natural-language prompt *declares*
the design must be; the RTL must *conform* to it. This module extracts that
contract from prose/markdown/JSON and parses the matching facts out of RTL.

It is deliberately dependency-free (stdlib only) and chip-AGNOSTIC: every
matcher is structural (sensitivity lists, `if`-polarity, port declarations,
reset-mode keywords). No vendor / IC / SKU / signal-name literals.

Exposed:
  strip_comments(src)                      -> str
  Port(name, direction, width)             dataclass
  parse_rtl_ports(src, top)                -> (module_name, [Port])
  classify_rtl_resets(module_body)         -> {signal: {"mode":set,"polarity":set}}
  SpecContract(module, ports, reset, latency_registered)  dataclass
  extract_spec_contract(text)              -> SpecContract
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple


# ---------------------------------------------------------------------------
# Comment stripping (preserves newlines for line tracking)
# ---------------------------------------------------------------------------
def strip_comments(src: str) -> str:
    out, i, n = [], 0, len(src)
    while i < n:
        if src[i:i + 2] == '/*':
            end = src.find('*/', i + 2)
            if end == -1:
                break
            out.append(''.join('\n' if c == '\n' else ' ' for c in src[i:end + 2]))
            i = end + 2
        elif src[i:i + 2] == '//':
            end = src.find('\n', i)
            if end == -1:
                break
            out.append(' ' * (end - i))
            i = end
        else:
            out.append(src[i])
            i += 1
    return ''.join(out)


# ---------------------------------------------------------------------------
# Ports
# ---------------------------------------------------------------------------
@dataclass
class Port:
    name: str
    direction: str   # input / output / inout
    width: int       # 1 for scalar


_PORT_DECL = re.compile(
    r'\b(input|output|inout)\b\s*(?:reg|wire|logic|signed|unsigned|\s)*'
    r'(?:\[\s*(\d+)\s*:\s*(\d+)\s*\]\s*)?'
    r'([A-Za-z_]\w*(?:\s*,\s*(?!(?:input|output|inout)\b)[A-Za-z_]\w*)*)')


# function/task argument declarations use the same input/output keywords as module
# ports but are lexically scoped to the subprogram — blank their bodies (preserving
# newlines) before port extraction so they are not mistaken for module ports.
_SUBPROGRAM = re.compile(
    r'\bfunction\b.*?\bendfunction\b|\btask\b.*?\bendtask\b', re.S | re.I)


def _strip_subprograms(text: str) -> str:
    return _SUBPROGRAM.sub(
        lambda m: ''.join('\n' if c == '\n' else ' ' for c in m.group(0)), text)


def parse_verilog_ports(text: str) -> List[Port]:
    """Parse Verilog `input/output/inout [msb:lsb] a, b` declarations."""
    ports: List[Port] = []
    for m in _PORT_DECL.finditer(text):
        direction = m.group(1)
        if m.group(2) is not None:
            width = abs(int(m.group(2)) - int(m.group(3))) + 1
        else:
            width = 1
        for nm in re.split(r'\s*,\s*', m.group(4)):
            nm = nm.strip()
            if nm:
                ports.append(Port(nm, direction, width))
    return ports


def parse_rtl_ports(src: str, top: Optional[str]) -> Tuple[str, List[Port]]:
    """Return (module_name, ports) for the chosen/first module in RTL `src`."""
    mods = list(re.finditer(r'\bmodule\s+(\w+)\b', src))
    if not mods:
        return '', []
    chosen = None
    if top:
        for m in mods:
            if m.group(1) == top:
                chosen = m
                break
    chosen = chosen or mods[0]
    name = chosen.group(1)
    nxt = re.search(r'\bendmodule\b', src[chosen.end():])
    region = src[chosen.end():chosen.end() + (nxt.start() if nxt else len(src))]
    # Ignore input/output declarations inside function/task bodies (not module ports).
    region = _strip_subprograms(region)
    return name, parse_verilog_ports(region)


# ---------------------------------------------------------------------------
# Reset classification in RTL (per sequential always block)
# ---------------------------------------------------------------------------
_OPENERS = re.compile(r'\b(begin|case[zx]?|fork)\b')
_CLOSERS = re.compile(r'\b(end|endcase|join(?:_any|_none)?)\b')
_ALWAYS = re.compile(r'\balways(?:_ff)?\b')
_SENS = re.compile(r'@\s*\(([^)]*)\)', re.S)
_RST_EDGE = re.compile(r'\b(?:pos|neg)edge\s+(\w+)')
# Generic (chip-AGNOSTIC) reset-name shapes used only to gate SYNC-reset
# classification so an enable (`if(en)`) is never mistaken for a reset.
_RESET_NAME = re.compile(r'rst|reset|clr|clear|\bpor\b', re.I)


def _extract_block(src: str, after: int) -> Tuple[str, int]:
    m = re.compile(r'\S').search(src, after)
    if not m:
        return '', len(src)
    if not re.match(r'begin\b', src[m.start():]):
        semi = src.find(';', m.start())
        end = semi if semi != -1 else len(src)
        return src[m.start():end + 1], end + 1
    depth, pos, tok, last = 0, m.start(), re.compile(r'\b\w+\b'), len(src)
    while pos < last:
        t = tok.search(src, pos)
        if not t:
            break
        w = t.group(0)
        if _OPENERS.fullmatch(w):
            depth += 1
        elif _CLOSERS.fullmatch(w):
            depth -= 1
            if depth == 0:
                return src[m.start():t.end()], t.end()
        pos = t.end()
    return src[m.start():], len(src)


def _classify_polarity(cond: str) -> Tuple[Optional[str], Optional[str]]:
    """Parse (reset_signal, polarity) from a reset `if` condition."""
    cond = cond.strip()
    m = re.match(r'^[!~]\s*(\w+)\s*$', cond)
    if m:
        return m.group(1), 'active-low'
    m = re.match(r'^(\w+)\s*==\s*1?\'?[bdh]?0+\s*$', cond) or \
        re.match(r"^(\w+)\s*==\s*0\s*$", cond)
    if m:
        return m.group(1), 'active-low'
    m = re.match(r'^(\w+)\s*==\s*1?\'?[bdh]?0*1\s*$', cond) or \
        re.match(r"^(\w+)\s*==\s*1\s*$", cond)
    if m:
        return m.group(1), 'active-high'
    m = re.match(r'^(\w+)\s*$', cond)
    if m:
        return m.group(1), 'active-high'
    return None, None


def classify_rtl_resets(body: str) -> Dict[str, Dict[str, Set[str]]]:
    """Per reset signal, the set of modes ('synchronous'/'asynchronous') and
    polarities ('active-high'/'active-low') it is used with across the module's
    sequential blocks."""
    out: Dict[str, Dict[str, Set[str]]] = {}
    pos = 0
    while True:
        am = _ALWAYS.search(body, pos)
        if not am:
            break
        sm = _SENS.search(body, am.end())
        if not sm or sm.start() > am.end() + 8:
            pos = am.end()
            continue
        edges = _RST_EDGE.findall(sm.group(1))
        if not edges:                       # not sequential
            pos = sm.end()
            continue
        block, end_pos = _extract_block(body, sm.end())
        ifm = re.search(r'\bif\s*\(([^)]*)\)', block)
        rst_sig, pol = (None, None)
        if ifm:
            rst_sig, pol = _classify_polarity(ifm.group(1))
        mode = None
        if rst_sig and rst_sig in edges:
            mode = 'asynchronous'
        elif (rst_sig and rst_sig not in edges and pol is not None and ifm
              and ifm.start() < 60 and _RESET_NAME.search(rst_sig)):
            mode = 'synchronous'
        if rst_sig and mode:
            rec = out.setdefault(rst_sig, {'mode': set(), 'polarity': set()})
            rec['mode'].add(mode)
            if pol:
                rec['polarity'].add(pol)
        pos = end_pos
    return out


# ---------------------------------------------------------------------------
# Spec contract extraction (prose / markdown / JSON  ->  declared intent)
# ---------------------------------------------------------------------------
@dataclass
class SpecContract:
    module: Optional[str] = None
    ports: List[Port] = field(default_factory=list)
    reset_mode: Optional[str] = None        # synchronous / asynchronous
    reset_polarity: Optional[str] = None    # active-high / active-low
    reset_signal: Optional[str] = None      # if the spec names it
    latency_registered: Optional[bool] = None
    fsm_output_style: Optional[str] = None  # 'moore'/'mealy' if the spec declares one
    source: str = ''                        # how ports were parsed: nl/verilog/json
    # LLM double-confirm records for the prose-inferred SEMANTIC fields above
    # (asdict of llm_semantic_confirm.Confirmation). Empty when no semantic field
    # was declared or no LLM backend was reachable to confirm.
    semantic_confirmations: List[dict] = field(default_factory=list)


# Natural-language interface bullet:  " - input  d   (8 bits)"  /  " - output q"
# Line-anchored with [ \t] (never \s) so a greedy match cannot swallow the next
# bullet's newline and skip ports.
_NL_PORT = re.compile(
    r'^[ \t]*[-*][ \t]*(input|output|inout)\b[ \t]+'
    r'([A-Za-z_]\w*)[ \t]*(?:\([ \t]*(\d+)[ \t]*bits?[ \t]*\))?',
    re.I | re.M)


def _parse_nl_ports(text: str) -> List[Port]:
    ports: List[Port] = []
    for m in _NL_PORT.finditer(text):
        direction = m.group(1).lower()
        name = m.group(2)
        width = int(m.group(3)) if m.group(3) else 1
        ports.append(Port(name, direction, width))
    return ports


def _module_port_region(text: str, prefer: str = "TopModule") -> Optional[str]:
    """Return the ANSI port-list inside `module name ( ... )`, or None.

    Lets a markdown spec carry a fenced ```verilog module(...)``` header without
    prose ("...provides valid outputs...") leaking false ports.

    When the spec embeds MULTIPLE module declarations (e.g. a reference or buggy
    module shown before the real target header — common in code-completion and
    bug-fix prompts), prefer the one named `prefer` (default TopModule, the target)
    so the contract is taken from the target header, not the embedded example."""
    headers = list(re.finditer(r'\bmodule\s+(\w+)\s*(?:#\s*\([^)]*\)\s*)?\(', text))
    if not headers:
        return None
    m = next((h for h in headers if h.group(1) == prefer), headers[0])
    i = text.index('(', m.start())
    depth, n = 0, len(text)
    while i < n:
        if text[i] == '(':
            depth += 1
        elif text[i] == ')':
            depth -= 1
            if depth == 0:
                return text[m.start():i]
        i += 1
    return None


def _detect_reset(text: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Return (mode, polarity, signal) the spec declares for reset, if any."""
    low = text.lower()
    mode = None
    # Look only in sentences that mention reset, to avoid false matches.
    reset_ctx = ' '.join(s for s in re.split(r'(?<=[.\n])', low) if 'reset' in s) or low
    if re.search(r'asynchronous(?:ly)?', reset_ctx):
        mode = 'asynchronous'
    elif re.search(r'synchronous(?:ly)?', reset_ctx):
        mode = 'synchronous'
    polarity = None
    if re.search(r'active[\s-]*high', reset_ctx) or re.search(r'\bactive\s+high\b', reset_ctx):
        polarity = 'active-high'
    elif re.search(r'active[\s-]*low', reset_ctx) or re.search(r'\bactive\s+low\b', reset_ctx):
        polarity = 'active-low'
    # named reset signal (best-effort): a reset-shaped token near "reset"
    signal = None
    m = re.search(r'`?\b(rst_n|resetn|reset_n|nrst|arst|srst|rst|reset)\b`?', reset_ctx)
    if m:
        signal = m.group(1)
    return mode, polarity, signal


def _detect_fsm_output_style(text: str) -> Optional[str]:
    """Return 'moore'/'mealy' iff the spec clearly DECLARES that FSM output style
    as a requirement, else None.

    This is a declared spec property — the sibling of reset-mode — NOT a bare
    keyword grep. To avoid the false triggers that make a naive substring match
    invalid (e.g. "Moore's law", "not a Moore machine"), it requires the term to
    be used as an FSM descriptor (machine/FSM/state-machine in the local window),
    is possessive-aware ("Moore's"), is negation-aware ("not a Moore ..."), and
    bails to None when both styles appear (ambiguous). Mealy-vs-Moore is a valid
    design choice, so this only fires when the spec itself picks one."""
    low = text.lower()

    def declares(word: str) -> bool:
        for m in re.finditer(r'\b' + word + r'\b', low):
            pre = low[max(0, m.start() - 18):m.start()]
            post = low[m.end():m.end() + 3]
            if word == 'moore' and post.startswith("'s"):            # "Moore's law"
                continue
            if re.search(r"\b(not|non|isn'?t|aren'?t|rather than|instead of)\s*(a|an)?\s*$", pre):
                continue
            window = low[max(0, m.start() - 24):m.end() + 32]
            if re.search(r'\b(machine|fsm|finite[\s-]*state|automat|state[\s-]*machine)\b', window):
                return True
        return False

    moore, mealy = declares('moore'), declares('mealy')
    if moore and not mealy:
        return 'moore'
    if mealy and not moore:
        return 'mealy'
    return None


def _detect_latency(text: str) -> Optional[bool]:
    low = text.lower()
    if re.search(r'registered\s+output', low) or \
       re.search(r'one\s+clock\s+cycle', low) or \
       re.search(r'\b1\s*[- ]?clock[- ]?cycle', low) or \
       re.search(r'single[- ]cycle', low) or \
       re.search(r'output\s+is\s+registered', low):
        return True
    if re.search(r'combinational\s+output', low):
        return False
    return None


def extract_spec_contract(text: str, is_json: bool = False,
                          confirm: bool = True, client_factory=None) -> SpecContract:
    """Extract a declared contract from spec text.

    SEMANTIC double-confirm: prose-inferred fields (reset mode/polarity, output latency,
    FSM output style) are only deterministic CANDIDATES. When `confirm` is set (default)
    each is re-judged by an LLM via llm_semantic_confirm before it is trusted — the
    program's parse of meaning is inferior to the model's. On a host with no LLM backend
    this is a no-op that records the candidate as `unconfirmed-no-backend` (for agent-layer
    confirmation). JSON contracts are authoritative and skip confirmation.

    JSON form: {"module":..,"ports":[{"name","direction","width"}],
                "reset":{"mode","polarity","signal"},"latency_registered":bool}
    Else: natural-language bullets first; if none, Verilog port declarations
    (covers a markdown ```verilog module(...)``` block). Reset mode/polarity and
    output-latency are read from the prose either way.
    """
    if is_json:
        data = json.loads(text)
        if isinstance(data, list):          # bare port list [{...}, ...]
            port_dicts, rst, mod, lat = data, {}, None, None
        else:                               # {"ports":[...],"reset":{...},...}
            port_dicts = data.get('ports', [])
            rst = data.get('reset', {}) or {}
            mod = data.get('module')
            lat = data.get('latency_registered')
        ports = [Port(d['name'], d.get('direction', 'input'), int(d.get('width', 1)))
                 for d in port_dicts]
        return SpecContract(module=mod, ports=ports,
                            reset_mode=rst.get('mode'),
                            reset_polarity=rst.get('polarity'),
                            reset_signal=rst.get('signal'),
                            latency_registered=lat,
                            fsm_output_style=(data.get('fsm_output_style')
                                              if isinstance(data, dict) else None),
                            source='json')

    clean = strip_comments(text)
    ports = _parse_nl_ports(clean)
    source = 'nl'
    if not ports:
        region = _module_port_region(clean)
        if region is not None:                      # ANSI markdown module header
            ports = parse_verilog_ports(region)
            source = 'verilog'
        elif re.search(r'\bmodule\b', clean):       # non-ANSI module declaration
            # Prefer the TopModule target if the spec embeds several module decls.
            _, ports = parse_rtl_ports(clean, "TopModule")
            source = 'verilog'
        else:                                       # pure prose: no interface
            ports = []                               # declared — never scan raw
            source = 'none'                          # prose for "input/output" words
    # Module name: prefer the target `TopModule` when a spec embeds several module
    # headers (a reference/buggy example before the real target), else the first.
    mod = None
    names = re.findall(r'\bmodule\s+(\w+)', clean)
    if "TopModule" in names:
        mod = "TopModule"
    elif names:
        mod = names[0]
    else:
        mm = re.search(r'module\s+named\s+`?(\w+)`?', text, re.I)
        if mm:
            mod = mm.group(1)
    mode, polarity, signal = _detect_reset(text)
    contract = SpecContract(module=mod, ports=ports, reset_mode=mode,
                            reset_polarity=polarity, reset_signal=signal,
                            latency_registered=_detect_latency(text),
                            fsm_output_style=_detect_fsm_output_style(text), source=source)
    if confirm:
        # program PROPOSES (above) -> LLM CONFIRMS/CORRECTS the semantic candidates.
        try:
            from llm_semantic_confirm import confirm_contract, manifest
        except ImportError:
            from .llm_semantic_confirm import confirm_contract, manifest  # packaged
        contract.semantic_confirmations = manifest(
            confirm_contract(contract, text, client_factory=client_factory))
    return contract
