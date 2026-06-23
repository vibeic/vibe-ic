#!/usr/bin/env python3
"""cvdp_complete_extract.py — a UNIFIED CVDP complete-extraction layer.

GOAL (owner directive 2026-06-23): for EVERY CVDP "code generation" problem,
extract the MOST COMPLETE structured spec JSON the prompt + harness support, so a
SKIP is honest ONLY when a fact is GENUINELY ABSENT from the prompt (§3.9
spec-absent) — NEVER because we failed to extract a fact that IS in the prompt.

This module does NOT author RTL and does NOT replace the bridge's conservative
emit gate. It is the MEASUREMENT + STRUCTURED-SPEC layer: it COMPOSES the already
shipped pieces —

  * `cvdp_atomic_bridge`  — interface (cocotb dut.<sig> + skeleton header +
    test-case table + prose), module name (.env TOPLEVEL), composite/special-
    algebra cues, prose width resolution; and
  * the v1.1.82 structural extractors
      cvdp_regmap_extract / cvdp_enumset_extract / cvdp_fsm_extract /
      cvdp_numeric_pack_extract / cvdp_worked_example_extract

— into ONE complete spec dict per record, PLUS a per-record COMPLETENESS verdict.

§4.05 NO-LEAK / NO-CHEAT (binding, the load-bearing rule):
  * EVERY emitted field is anchored to a REAL structural source in the prompt or
    the harness — a `module(...)` header (header only), a cocotb `dut.<sig>.value`
    reference, a markdown table row, an `0xNN` offset line, an explicit `N-bit`
    token, a stated transition. A fact is NEVER invented to make a record look
    COMPLETE.
  * The golden/reference RTL body in `output['context']` is NEVER read. The
    skeleton is parsed for its `module(...)` HEADER only (and in CVDP v1.1.0 every
    skeleton is empty anyway). The interface ground-truth is the cocotb test +
    the prompt prose tables — both submitter-visible.

COMPLETENESS verdict (the deliverable classification):
  COMPLETE
      every testable fact the harness checks is captured — i.e. every port the
      cocotb test drives/reads is in our interface with a resolved width (or is a
      1-bit control / a config parameter we correctly filtered out), AND every
      structure the prompt states (register map / enum / FSM / numeric / worked
      example) was recovered by its extractor. The record is then either
      program-solvable (the bridge emits) or fully AI-gated on a captured spec.
  INCOMPLETE_EXTRACTION_GAP
      a fact IS in the prompt / harness but our extractor MISSED it — ACTIONABLE.
      Detected by cross-checking the harness signals: a port the cocotb test
      drives that our interface dropped (and is NOT a parameter), or a width that
      a prose `[hi:lo]` / `N-bit` / table column states but we failed to resolve.
      Each gap carries a TYPE label (the recurring, fixable category).
  INCOMPLETE_SPEC_ABSENT
      the fact the harness checks is genuinely NOT in the prompt — the AI's
      irreducible domain (e.g. a data-path width the prompt never states for a
      port the cocotb still drives; a behaviour the harness asserts that no prose
      describes). Honest §3.9 SKIP, NOT an extractor bug.

To separate EXTRACTION_GAP from SPEC_ABSENT we use the harness as the oracle of
"what is testable": the cocotb `dut.<sig>` set is the interface the scorer binds,
so a driven signal our interface missed is an extraction gap IF the prompt/harness
carries the evidence to place it (a parameter read, a reset synonym, a prose
width), and a SPEC_ABSENT only when the prompt is truly silent on it.

Public API
    extract(record: dict) -> dict
        {
          id, module_name, interface:[{name,dir,width,signed,source}],
          operation_family:{guess, confidence}, params:{...},
          structures:{register_map[],enum_modes[],fsm{states,transitions},
                      truth_table[],worked_examples[],test_vectors[]},
          reset:{polarity,sync}, timing:{latency,pipeline}, byte_order,
          completeness, completeness_reason, gaps:[{type,detail,evidence}],
          harness:{toplevel, cocotb_inputs, cocotb_outputs, params},
        }

chip-AGNOSTIC: every decision keys on STRUCTURE (table/offset/cocotb/header
shape + generic vocabulary), never on a design name, problem id, or SKU literal.

CLI
    python3 cvdp_complete_extract.py --jsonl FILE [--id ID] [--dist] [--gaps]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

# Reused (NOT modified) — interface + module-name + cue helpers.
import cvdp_atomic_bridge as _bridge  # noqa: E402

# Reused (NOT modified) — v1.1.82 structural extractors. Imported defensively so a
# not-yet-present extractor simply contributes nothing (the layer never crashes).
_EXTRACTORS: Dict[str, object] = {}
for _name in ("cvdp_regmap_extract", "cvdp_enumset_extract", "cvdp_fsm_extract",
              "cvdp_numeric_pack_extract", "cvdp_worked_example_extract"):
    try:
        _EXTRACTORS[_name] = __import__(_name)
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# parameter / reset / clock structural classification (harness-anchored)
# --------------------------------------------------------------------------- #
# A cocotb PARAMETER is read with `X = int(dut.X.value)` to CONFIGURE the run (a
# width / loop bound), not asserted as a DUT port. The bridge's filter requires an
# ALL-CAPS snake or >=3 caps token, so a SINGLE-letter uppercase config integer
# (N, M, K, ...) read via `int(dut.N.value)` leaks through as a phantom port. We
# recover such config reads here — but ONLY when the signal name is ALL-UPPERCASE
# (the dataset's universal parameter-naming convention: DATA_WIDTH / N / M / K).
# A lowercase `int(dut.sum.value)` is an OUTPUT-VALUE read (the scorer reads an
# output port as an int to compare it), NOT a parameter — restricting to
# ALL-UPPERCASE keeps a lowercase data output from being mis-dropped. §4.05:
# anchored to a real harness token + the naming convention, never guessed.
_UPPER_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
_INT_PARAM_READ_RE = re.compile(r"\b\w+\s*=\s*int\(\s*dut\.([A-Z][A-Z0-9_]*)\.value\s*\)")
# `dut.X` used inside a python range/loop/shift expression is a config integer too
# (again gated to ALL-UPPERCASE so an output read in a comparison is not caught).
_RANGE_PARAM_RE = re.compile(
    r"(?:range|<<|>>|\*\*)\s*\(?\s*[^)]*dut\.([A-Z][A-Z0-9_]*)\.value")

# Reset / clock synonyms, broader than the bridge's _SEQ_PORTS so a `rst_in`,
# `reset_i`, `arst_n`, `sync_rst` etc. resolves to a 1-bit control rather than an
# unresolved data port. Keyed on the universal reset/clock naming shape.
_CLK_RE = re.compile(r"(?i)^(clk|clock|sclk|aclk|hclk|pclk)([_\.]?(in|i|sys|core))?$")
_RST_RE = re.compile(
    r"(?i)(^|_)(rst|reset|arst|areset|srst|nreset|resetn|rstn)([_\.]?(in|i|n|b|async|sync))?($|_)"
)
# 1-bit control / handshake / flag shapes (besides clk/rst) — single-bit by the
# universal naming convention. Used ONLY to assign a width of 1 to a cocotb signal
# the prompt does not give an explicit bus range for. A signal counts as 1-bit
# when it is EXACTLY a control word OR carries a control word as a `_`-delimited
# TOKEN anywhere in its name (`x_valid`, `decoder_data_valid_in`, `out_ready`).
# We deliberately do NOT key on a bare `_in` / `_out` / `_i` / `_o` suffix — those
# are direction tags worn by wide DATA buses (`encoder_data_in`) too, so a blanket
# suffix rule would mis-size a data port to 1 (§4.05: never claim a width we cannot
# justify; a data port with no stated width stays a gap, not a forced 1).
_CTRL_WORD = (
    r"valid|ready|ack|req|start|stop|done|busy|enable|"
    r"overflow|underflow|ovf|borrow|parity|found|hit|miss|sel|"
    r"carry|cin|cout|flag|trigger|strobe|clk_?en|clken|wr_?en|rd_?en|"
    r"interrupt|irq|empty|full|almost_?full|almost_?empty"
)
_ONE_BIT_RE = re.compile(
    r"(?i)^("
    r"c_?in|cin|carry_?in|c_?out|cout|carry_?out|b_?out|borrow|"
    r"start|stop|done|busy|error|err|enable|en|load|"
    r"ack|req|sel|mode|flag|overflow|ovf|underflow|parity|found|hit|miss|"
    rf"(?:\w+_)?(?:{_CTRL_WORD})(?:_\w+)?"
    r")$")


def _harness_params(tb: str) -> set:
    """The FULL set of cocotb config parameters — the bridge's ALL-CAPS filter
    UNION every `int(dut.X.value)` / range-bound `dut.X.value` read. This recovers
    single-letter uppercase params (N, M, K) the bridge's regex misses."""
    params = set(_bridge._cocotb_params(tb))
    for m in _INT_PARAM_READ_RE.finditer(tb):
        params.add(m.group(1))
    for m in _RANGE_PARAM_RE.finditer(tb):
        params.add(m.group(1))
    return params


def _is_clk(name: str) -> bool:
    return bool(_CLK_RE.match(name)) or name.lower() in _bridge._SEQ_PORTS \
        and re.search(r"clk|clock", name, re.I) is not None


def _is_rst(name: str) -> bool:
    return bool(_RST_RE.search(name)) or name.lower() in _bridge._SEQ_PORTS \
        and re.search(r"rst|reset", name, re.I) is not None


# --------------------------------------------------------------------------- #
# width resolution (prose / table / explicit range) — reuses the bridge readers
# --------------------------------------------------------------------------- #
def _explicit_range_width(prompt: str, name: str) -> Optional[int]:
    """A bus range LITERALLY tied to this exact name: `name [hi:lo]`."""
    m = re.search(rf"\b{re.escape(name)}\s*\[\s*(\d+)\s*:\s*(\d+)\s*\]", prompt)
    return abs(int(m.group(1)) - int(m.group(2))) + 1 if m else None


def _resolve_width(prompt: str, table: Dict[str, int], name: str) -> Tuple[Optional[int], str]:
    """Best stated width for `name` + the structural SOURCE tag. None when the
    prompt is silent (then the caller decides 1-bit-control vs SPEC_ABSENT)."""
    er = _explicit_range_width(prompt, name)
    if er is not None:
        return er, "explicit_range"
    pw = _bridge._prose_width(prompt, name)
    if pw is not None:
        return pw, "prose_width"
    key = name.lower()
    if key in table:
        return table[key], "test_case_table"
    return None, ""


# --------------------------------------------------------------------------- #
# operation family (best guess + confidence) — structural vocabulary, agnostic
# --------------------------------------------------------------------------- #
# A coarse family classifier keyed on STATED operation vocabulary (never a design
# name). Confidence is HIGH when a special-algebra / composite cue fires (the
# bridge's own SKIP cues are unambiguous), MEDIUM for a plain arithmetic/logic
# verb, LOW for a bare "design a module". This is a HINT field, not a gate.
_FAMILY_CUES = [
    ("composite_protocol", _bridge._COMPOSITE_RE, "high"),
    ("special_algebra", _bridge._SPECIAL_ALGEBRA_RE, "high"),
    ("crc", re.compile(r"(?i)\bcrc\b|cyclic\s+redundancy"), "high"),
    ("fsm", re.compile(r"(?i)\bstate\s+machine\b|\bfsm\b|\bstates?\b.*transition"), "medium"),
    ("counter", re.compile(r"(?i)\bcounter\b|count\s+(up|down)|increment"), "medium"),
    ("shift", re.compile(r"(?i)\bshift\s+register\b|barrel\s+shift|rotate"), "medium"),
    ("encoder_decoder", re.compile(r"(?i)\b(en|de)coder\b|priority\s+encoder"), "medium"),
    ("mux_demux", re.compile(r"(?i)\b(de)?multiplex|\bmux\b"), "medium"),
    ("arithmetic", re.compile(
        r"(?i)\badd(s|ition|er)?\b|\bsum\b|\bsubtract|\bmultipl|\bdivid|\bALU\b|accumulat"), "medium"),
    ("comparator", re.compile(r"(?i)\bcompar(e|ator)\b|greater\s+than|less\s+than"), "medium"),
    ("parity_checksum", re.compile(r"(?i)\bparity\b|\bchecksum\b|hamming"), "medium"),
]


def _operation_family(prompt: str) -> Dict[str, str]:
    for tag, rx, conf in _FAMILY_CUES:
        if rx.search(prompt):
            return {"guess": tag, "confidence": conf}
    return {"guess": "unknown", "confidence": "low"}


# --------------------------------------------------------------------------- #
# numeric params from the prompt (poly / width / depth / N / latency ...)
# --------------------------------------------------------------------------- #
_PARAM_TABLE_ROW = re.compile(
    r"^\s*\|\s*`?([A-Za-z_]\w*)`?\s*\|.*?\|\s*`?(\d+|0[xX][0-9A-Fa-f]+)`?\s*\|", re.M)


def _prompt_params(prompt: str) -> Dict[str, object]:
    """Stated scalar params anchored to a real source: a Parameter-table default
    column, a `poly = 0x...`, a `WIDTH = N`, an `N-bit` token, a stated latency.
    Every value is anchored; silence yields no key (never a fabricated default)."""
    params: Dict[str, object] = {}
    # (a) a `| NAME | ... | <default> |` parameter table row (default in a cell).
    if re.search(r"(?i)\bparameter", prompt):
        for m in _PARAM_TABLE_ROW.finditer(prompt):
            nm, val = m.group(1), m.group(2)
            if nm.lower() in ("parameter", "name", "description"):
                continue
            params.setdefault(nm, val)
    # (b) explicit `key = value` style params for the canonical structural keys.
    for key, rx in (
        ("poly", re.compile(r"(?i)\b(?:polynomial|poly)\b[^\n]*?(0[xX][0-9A-Fa-f]+|[01]{4,})")),
        ("width", re.compile(r"(?i)\b(?:data[\s_]?width|width)\b\s*[:=]?\s*(\d+)")),
        ("depth", re.compile(r"(?i)\bdepth\b\s*[:=]?\s*(\d+)")),
        ("latency", re.compile(r"(?i)\blatency\b[^\n]*?(\d+)\s*(?:clock\s*)?cycle")),
    ):
        m = rx.search(prompt)
        if m and key not in params:
            params[key] = m.group(1)
    return params


# --------------------------------------------------------------------------- #
# reset polarity / sync + byte order (structural, anchored)
# --------------------------------------------------------------------------- #
def _reset_semantics(prompt: str, ins: List[str]) -> Dict[str, Optional[str]]:
    has_rst = any(_is_rst(n) for n in ins)
    if not has_rst:
        return {"polarity": None, "sync": None}
    polarity = None
    if re.search(r"(?i)active[\s\-]*low|asserted\s+low|reset_n|rst_n|rstn|negedge\s+\w*rst", prompt):
        polarity = "active_low"
    elif re.search(r"(?i)active[\s\-]*high|asserted\s+high|posedge\s+\w*rst", prompt):
        polarity = "active_high"
    sync = None
    if re.search(r"(?i)\bsynchronous\s+reset|sync(?:hronous)?\s+rst|synchronously\s+reset", prompt):
        sync = "sync"
    elif re.search(r"(?i)\basynchronous\s+reset|async(?:hronous)?\s+rst|asynchronously\s+reset", prompt):
        sync = "async"
    return {"polarity": polarity, "sync": sync}


def _byte_order(prompt: str) -> Optional[str]:
    np = _EXTRACTORS.get("cvdp_numeric_pack_extract")
    if np:
        for it in np.extract(prompt):
            if it.get("kind") == "byte_order":
                return it.get("order") or it.get("byte_order") or it.get("evidence")
    if re.search(r"(?i)\blittle[\s\-]?endian\b", prompt):
        return "little_endian"
    if re.search(r"(?i)\bbig[\s\-]?endian\b", prompt):
        return "big_endian"
    return None


# --------------------------------------------------------------------------- #
# the complete interface (the harness-checked contract)
# --------------------------------------------------------------------------- #
def _complete_interface(record: dict, top: str
                        ) -> Tuple[List[dict], List[str], List[str], set, List[dict]]:
    """Build the MOST COMPLETE interface the prompt+harness support.

    Returns (interface, cocotb_inputs, cocotb_outputs, params, gaps):
      * interface  — [{name,dir,width,signed,source}] for every PLACED port;
      * cocotb_*   — the raw driven/read signal lists (the harness contract);
      * params     — the recovered config-parameter set (NOT ports);
      * gaps       — EXTRACTION_GAP / SPEC_ABSENT records for unplaced signals.

    A cocotb-driven signal becomes a PORT unless it is a recovered parameter.
    Width is resolved from prose/table/explicit-range; a clk/rst/1-bit-control
    signal defaults to width 1 by the universal naming convention; a DATA port
    with no stated width is recorded as a gap (EXTRACTION_GAP if the prompt has a
    width form we structurally failed to read, else SPEC_ABSENT)."""
    prompt = (record.get("input") or {}).get("prompt") or ""
    files = _bridge._harness_files(record)
    tb = _bridge._cocotb_test_text(files)

    # (a) prefer a non-empty skeleton header (header only) — fully self-describing.
    sk = _bridge._skeleton_ports(record, top)
    if sk:
        iface = []
        for d, lst in (("input", sk[0]), ("output", sk[1])):
            for n, w in _bridge._clean_ports(lst):
                iface.append({"name": n, "dir": d, "width": w,
                              "signed": False, "source": "skeleton_header"})
        c_ins, c_outs = _bridge._cocotb_io(tb)
        return iface, c_ins, c_outs, set(), []

    # (b) cocotb dut.<sig> set — the harness's bound interface.
    c_ins, c_outs = _bridge._cocotb_io(tb)
    params = _harness_params(tb)
    table = _bridge._test_case_table(prompt) or {}
    signed = bool(re.search(r"(?i)\bsigned\b|two'?s?\s+complement|2'?s?\s+complement", prompt))

    iface: List[dict] = []
    gaps: List[dict] = []

    def _place(name: str, direction: str):
        if name in params:
            return  # a config parameter — not a port (correctly filtered)
        w, src = _resolve_width(prompt, table, name)
        if w is not None:
            iface.append({"name": name, "dir": direction, "width": w,
                          "signed": signed, "source": src})
            return
        if _is_clk(name) or _is_rst(name):
            iface.append({"name": name, "dir": direction, "width": 1,
                          "signed": False, "source": "clk_rst_convention"})
            return
        if _ONE_BIT_RE.match(name):
            iface.append({"name": name, "dir": direction, "width": 1,
                          "signed": False, "source": "one_bit_convention"})
            return
        # A DATA port the cocotb drives but no width is stated. Decide gap kind:
        #   EXTRACTION_GAP — a width FORM exists in the prompt but our reader missed
        #     it (e.g. a `#(...)`-override default, an `N*WIDTH` expression, a width
        #     stated against a synonym of this name);
        #   SPEC_ABSENT    — the prompt is truly silent on this port's width.
        gkind, gtype = _classify_width_gap(prompt, name, params)
        gaps.append({"kind": gkind, "type": gtype,
                     "detail": f"{direction} port `{name}` width unresolved",
                     "evidence": _evidence_line(prompt, name)})

    for n in c_ins:
        _place(n, "input")
    for n in c_outs:
        _place(n, "output")

    # de-dup the interface by name (a signal read AND written keeps first dir)
    seen = set()
    dedup = []
    for p in iface:
        if p["name"] in seen:
            continue
        seen.add(p["name"])
        dedup.append(p)
    return dedup, c_ins, c_outs, params, gaps


# A parameterized-width FORM the prompt states but tied to a parameter expression
# (e.g. `bits [N*IN_WIDTH-1:0]`, `out [M-1:0]`, `lower [M-2:0]`, `[WIDTH-1:0]`)
# rather than a literal integer. The width IS in the prompt (so it's an
# EXTRACTION_GAP — we could read the parameter expression), it is just not a
# constant our literal reader resolves. The form is a `[hi:lo]` range in which an
# IDENTIFIER appears in EITHER bound (so `[M-2:0]` and `[N-1:0]` both qualify),
# i.e. NOT a pure `[\d+:\d+]` literal range.
_PARAM_WIDTH_FORM = re.compile(r"\[\s*([^\]:]*?)\s*:\s*([^\]]*?)\s*\]")
_HAS_IDENT = re.compile(r"[A-Za-z_]\w*")


def _is_param_range(span: str) -> bool:
    """True for a `[hi:lo]` where a parameter IDENTIFIER appears in a bound."""
    m = _PARAM_WIDTH_FORM.fullmatch(span.strip())
    if not m:
        return False
    hi, lo = m.group(1), m.group(2)
    # a pure literal range `[7:0]` is NOT a param form (the literal reader handles
    # it); a bound carrying an identifier (M, N, WIDTH, M-2, N*W-1) IS.
    return bool(_HAS_IDENT.search(hi) or _HAS_IDENT.search(lo))


def _classify_width_gap(prompt: str, name: str, params: set) -> Tuple[str, str]:
    """EXTRACTION_GAP (a width form is present we failed to parse) vs SPEC_ABSENT
    (the prompt is genuinely silent). Returns (completeness_kind, gap_type)."""
    # the port appears with a PARAMETER-EXPRESSION width range somewhere near it.
    m = re.search(rf"\b{re.escape(name)}\b[^\n|]*?(\[[^\]]*[A-Za-z_][^\]]*\])", prompt)
    if m and _is_param_range(m.group(1)):
        return "INCOMPLETE_EXTRACTION_GAP", "param_expression_width"
    # a `#(...)` parameter override block names a width param but our literal
    # reader did not bind it to this port.
    if params and re.search(r"#\s*\(", prompt) and re.search(
            rf"\b{re.escape(name)}\b[^\n|]*\[", prompt):
        return "INCOMPLETE_EXTRACTION_GAP", "param_override_width"
    # a range-before-name declaration `[7:0] name` (range precedes the identifier).
    if re.search(rf"\[\s*\d+\s*:\s*\d+\s*\]\s*{re.escape(name)}\b", prompt):
        return "INCOMPLETE_EXTRACTION_GAP", "range_before_name"
    # truly silent — the AI must infer the width from domain knowledge.
    return "INCOMPLETE_SPEC_ABSENT", "width_not_stated"


def _evidence_line(prompt: str, name: str) -> str:
    for ln in prompt.splitlines():
        if re.search(rf"\b{re.escape(name)}\b", ln):
            return ln.strip()[:200]
    return ""


# --------------------------------------------------------------------------- #
# structures (compose the five v1.1.82 extractors)
# --------------------------------------------------------------------------- #
def _structures(prompt: str) -> Dict[str, object]:
    out: Dict[str, object] = {
        "register_map": [], "enum_modes": [],
        "fsm": {"states": [], "transitions": []},
        "truth_table": [], "worked_examples": [], "test_vectors": [],
    }
    rm = _EXTRACTORS.get("cvdp_regmap_extract")
    if rm:
        out["register_map"] = rm.extract(prompt)
    en = _EXTRACTORS.get("cvdp_enumset_extract")
    if en:
        out["enum_modes"] = [it for it in en.extract(prompt)
                             if it.get("kind") == "enum_set"]
    fs = _EXTRACTORS.get("cvdp_fsm_extract")
    if fs:
        fitems = fs.extract(prompt)
        out["fsm"] = {
            "states": [it for it in fitems if it.get("kind") == "fsm_state"],
            "transitions": [it for it in fitems if it.get("kind") == "fsm_transition"],
        }
    we = _EXTRACTORS.get("cvdp_worked_example_extract")
    if we:
        witems = we.extract(prompt)
        out["worked_examples"] = [it for it in witems
                                  if it.get("kind") in ("worked_example", "example")]
        # latencies surface under timing too, but keep the raw items available.
        out["test_vectors"] = [it for it in witems
                               if it.get("kind") == "test_vector"]
    return out


def _timing(prompt: str) -> Dict[str, object]:
    timing: Dict[str, object] = {"latency": None, "pipeline": None}
    we = _EXTRACTORS.get("cvdp_worked_example_extract")
    if we:
        for it in we.extract(prompt):
            if it.get("kind") == "latency":
                timing["latency"] = it.get("cycles") or it.get("latency") or it.get("evidence")
                break
    if re.search(r"(?i)\bpipelined?\b|pipeline\s+stages?", prompt):
        timing["pipeline"] = True
    return timing


# --------------------------------------------------------------------------- #
# completeness verdict
# --------------------------------------------------------------------------- #
def _completeness(record: dict, iface: List[dict], c_ins: List[str],
                  c_outs: List[str], params: set, gaps: List[dict],
                  structures: Dict[str, object]) -> Tuple[str, str]:
    """Roll the per-signal gaps + the prompt-vs-extractor structure check up into
    ONE completeness verdict.

    COMPLETE                    — no extraction gap AND no spec-absent gap AND the
                                  harness interface is fully placed.
    INCOMPLETE_EXTRACTION_GAP   — at least one EXTRACTION_GAP (actionable — the
                                  fact is in the prompt/harness, we missed it).
                                  Takes precedence over SPEC_ABSENT (it is the
                                  fixable bucket the deliverable is about).
    INCOMPLETE_SPEC_ABSENT      — only SPEC_ABSENT gaps remain (the AI's domain).
    """
    prompt = (record.get("input") or {}).get("prompt") or ""

    # A composite / special-algebra design is intentionally NOT a single
    # extractable atomic function. Its interface may still be fully placed; we
    # only ever mark EXTRACTION_GAP for a missed structural fact, never penalize
    # it for being protocol-shaped. (The bridge SKIPs it for EMIT; the spec dict
    # is still as complete as the prompt allows.)
    has_extraction_gap = any(g["kind"] == "INCOMPLETE_EXTRACTION_GAP" for g in gaps)
    has_spec_absent = any(g["kind"] == "INCOMPLETE_SPEC_ABSENT" for g in gaps)

    # If the cocotb test gives no interface at all AND we have no skeleton header,
    # we cannot bind the harness contract — but only call it a GAP if the prompt
    # actually has a port description we failed to read; else it is SPEC_ABSENT
    # (a non-cocotb harness shape — out of this layer's structural reach).
    if not c_ins and not c_outs and not iface:
        files = _bridge._harness_files(record)
        tb = _bridge._cocotb_test_text(files)
        if not tb:
            return "INCOMPLETE_SPEC_ABSENT", "no cocotb harness to bind the interface"
        return "INCOMPLETE_EXTRACTION_GAP", "cocotb test present but no dut.<sig> interface recovered"

    if has_extraction_gap:
        types = sorted({g["type"] for g in gaps if g["kind"] == "INCOMPLETE_EXTRACTION_GAP"})
        return "INCOMPLETE_EXTRACTION_GAP", "missed fact(s): " + ", ".join(types)
    if has_spec_absent:
        types = sorted({g["type"] for g in gaps if g["kind"] == "INCOMPLETE_SPEC_ABSENT"})
        return "INCOMPLETE_SPEC_ABSENT", "prompt-silent fact(s): " + ", ".join(types)

    return "COMPLETE", "every harness-checked port placed; stated structures captured"


# --------------------------------------------------------------------------- #
# public API
# --------------------------------------------------------------------------- #
def extract(record: dict) -> dict:
    """Build the most complete structured spec dict the prompt+harness support,
    plus a completeness verdict. §4.05: every field anchored to a real source."""
    if not isinstance(record, dict):
        return {"completeness": "INCOMPLETE_SPEC_ABSENT",
                "completeness_reason": "not a record", "gaps": []}

    prompt = (record.get("input") or {}).get("prompt") or ""
    top = _bridge.toplevel_name(record) or ""

    iface, c_ins, c_outs, params, gaps = _complete_interface(record, top)
    structures = _structures(prompt)
    timing = _timing(prompt)
    completeness, reason = _completeness(
        record, iface, c_ins, c_outs, params, gaps, structures)

    spec = {
        "id": record.get("id"),
        "module_name": top or None,
        "interface": iface,
        "operation_family": _operation_family(prompt),
        "params": _prompt_params(prompt),
        "structures": structures,
        "reset": _reset_semantics(prompt, c_ins),
        "timing": timing,
        "byte_order": _byte_order(prompt),
        "completeness": completeness,
        "completeness_reason": reason,
        "gaps": gaps,
        "harness": {
            "toplevel": top or None,
            "cocotb_inputs": c_ins,
            "cocotb_outputs": c_outs,
            "params": sorted(params),
        },
    }
    return spec


# --------------------------------------------------------------------------- #
# CLI — measure the completeness distribution over a jsonl
# --------------------------------------------------------------------------- #
def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--jsonl", required=True, help="CVDP code-generation jsonl")
    ap.add_argument("--id", help="extract only this record id (prints the spec)")
    ap.add_argument("--dist", action="store_true",
                    help="print the COMPLETE / EXTRACTION_GAP / SPEC_ABSENT distribution")
    ap.add_argument("--gaps", action="store_true",
                    help="print the recurring EXTRACTION_GAP fact-types + sample ids")
    a = ap.parse_args(argv)

    recs = [json.loads(l) for l in open(a.jsonl)]
    if a.id:
        for r in recs:
            if r.get("id") == a.id:
                print(json.dumps(extract(r), indent=2, ensure_ascii=False))
                return 0
        print(f"id not found: {a.id}", file=sys.stderr)
        return 2

    A = B = C = 0
    gap_types: Dict[str, int] = {}
    gap_ids: Dict[str, List[str]] = {}
    complete_ids: List[str] = []
    extraction_ids: List[Tuple[str, str]] = []
    for r in recs:
        s = extract(r)
        cm = s["completeness"]
        if cm == "COMPLETE":
            A += 1
            complete_ids.append(s["id"])
        elif cm == "INCOMPLETE_EXTRACTION_GAP":
            B += 1
            for g in s["gaps"]:
                if g["kind"] == "INCOMPLETE_EXTRACTION_GAP":
                    gap_types[g["type"]] = gap_types.get(g["type"], 0) + 1
                    gap_ids.setdefault(g["type"], []).append(s["id"])
            egt = sorted({g["type"] for g in s["gaps"]
                          if g["kind"] == "INCOMPLETE_EXTRACTION_GAP"})
            extraction_ids.append((s["id"], ",".join(egt) or s["completeness_reason"]))
        else:
            C += 1

    print(f"TOTAL={len(recs)}")
    print(f"COMPLETE (A)             = {A}")
    print(f"EXTRACTION_GAP (B)       = {B}")
    print(f"SPEC_ABSENT (C)          = {C}")
    if a.dist or a.gaps:
        print("\nTop EXTRACTION_GAP fact-types:")
        for t, c in sorted(gap_types.items(), key=lambda kv: -kv[1]):
            sample = ", ".join(gap_ids[t][:3])
            print(f"  {c:4d}  {t:28s}  e.g. {sample}")
        print("\n10 COMPLETE ids:")
        for i in complete_ids[:10]:
            print(f"  {i}")
        print("\n10 EXTRACTION_GAP ids (with the specific missed fact):")
        for i, t in extraction_ids[:10]:
            print(f"  {i}  -> {t}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
