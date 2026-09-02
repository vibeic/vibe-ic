#!/usr/bin/env python3
"""formal_harness_gen.py — Step 5 DETERMINISTIC formal-property authoring.

Wires the formal step so a BARE run (no AI) still authors every property that
can be derived safely and records the denominator it could not author. It reads
the design's OWN L3/L6/L8 declarations plus top-module interface and reset logic
(design INPUT only, §4.05) and emits a `formal_<top>.sv` harness
carrying the always-valuable, construction-safe **reset-safety** invariant:

    one cycle after the design's declared reset is asserted, every registered
    output settles to the exact value the RTL's OWN reset branch assigns it.

`formal_property_run.py` then dispatches that harness to SymbiYosys with the
in-container `abc pdr` engine (`aigsmt none` — no external SMT solver needed),
producing a REAL unbounded proof + evidence that `formal_proof_evidence_check`
consumes. This closes the Step-5 "no formal tool ran" SKIP without any AI in
the loop, for any synchronous design with a clock, a reset and a registered
output whose reset value is a literal constant.

Why this is construction-safe (can never fabricate a proof OR a false FAIL):
  * The asserted value is LIFTED VERBATIM from the design's own reset branch —
    it is definitionally the value the FF holds after reset, so a correct
    design PROVES it and never counter-examples it.
  * When the interface / reset value cannot be determined with confidence the
    generator emits no assertion and returns INCOMPLETE, naming the missing
    declaration/property and the `formal-verify` expert route. It returns
    NOT_APPLICABLE only when the design explicitly declares formal inapplicable.

chip-AGNOSTIC: the mechanism keys off GENERIC hardware conventions (a clock /
reset port, a registered output) and the design's own RTL text. There is no
vendor / SKU / IC / PDK literal anywhere — the per-design names and reset values
come from the RTL, which is design INPUT.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).parent))
try:
    import _path_layout as _pl  # noqa: E402
except Exception:  # pragma: no cover - _path_layout always present in-tree
    _pl = None


PROPERTY_CONTRACT = "property_contract.json"
AUTHORING_REQUEST = "formal_authoring_request.json"


def _norm_applicability(value: Any) -> Tuple[str, str]:
    """Return (status, reason) from a small, explicit declaration dialect.

    A bare false is deliberately not enough: inapplicability needs a reason a
    reviewer can inspect. Unknown/malformed values remain UNDECLARED.
    """
    reason = ""
    status = value
    if isinstance(value, dict):
        status = value.get("status", value.get("applicability", ""))
        reason = str(value.get("reason", "")).strip()
    if status is False:
        status = "NOT_APPLICABLE"
    norm = str(status or "").upper().replace("-", "_").replace(" ", "_")
    if norm in {"NOT_APPLICABLE", "INAPPLICABLE", "N_A"} and reason:
        return "NOT_APPLICABLE", reason
    if norm in {"APPLICABLE", "REQUIRED", "YES", "TRUE"}:
        return "APPLICABLE", reason
    return "UNDECLARED", reason


def _read_l_docs(project: Optional[Path]) -> Dict[str, List[Tuple[Path, dict]]]:
    """Read only canonical Phase-1 L3/L6/L8/L22 declarations."""
    out: Dict[str, List[Tuple[Path, dict]]] = {
        "L3": [], "L6": [], "L8": [], "L22": []}
    if project is None or _pl is None:
        return out
    root = _pl.generated_docs_dir(project)
    for layer in out:
        for path in sorted(root.glob(f"{layer}*.json")):
            try:
                data = json.loads(path.read_text(errors="replace"))
            except (OSError, ValueError):
                continue
            if isinstance(data, dict):
                out[layer].append((path, data))
    return out


def _global_formal_applicability(
        docs: Dict[str, List[Tuple[Path, dict]]]) -> Optional[dict]:
    """A global NOT_APPLICABLE must be explicit in L22 and carry a reason."""
    for path, data in docs.get("L22", []):
        fields = data.get("fields") if isinstance(data.get("fields"), dict) else {}
        for value in (data.get("formal_applicability"),
                      fields.get("formal_applicability")):
            status, reason = _norm_applicability(value)
            if status == "NOT_APPLICABLE":
                return {"status": status, "reason": reason,
                        "source": str(path)}
    return None


def _layer_is_not_applicable(path: Path, data: dict) -> Optional[dict]:
    status, reason = _norm_applicability(data.get("formal_applicability"))
    if status == "NOT_APPLICABLE":
        return {"status": status, "reason": reason, "source": str(path)}
    return None


def _obligation(layer: str, key: str, description: str, path: Path) -> dict:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", key).strip("_") or "item"
    return {
        "id": f"{layer}.{safe}",
        "layer": layer,
        "source": str(path),
        "description": description[:500],
        "author": "formal-verify",
        "status": "UNAUTHORED",
    }


_TIMING_KEY_RE = re.compile(
    r"reset|latency|turnaround|timeout|cycle|holdoff|pulse", re.IGNORECASE)
# A leaf VALUE that itself states sequencing (prose declarations such as
# "synchronous, active-high; internals clear the cycle after assert").
_TIMING_VALUE_RE = re.compile(
    r"cycle|edge|assert|deassert|synchron|active[- ]?(high|low)|latency|"
    r"hold|after|before|同步|非同步|週期|邊緣", re.IGNORECASE)
# L-document PROVENANCE keys: every emitted layer carries them, and none of
# them states behaviour. ROUND-3 (subservient x gf180mcuD, 2026-09-02):
# `clock_and_reset_waveform.derived_from.0`, `.derived_from.1` and
# `.extraction_strategy` were enumerated as "declared temporal behavior"
# because the CONTAINER key contains "reset" — three of seven expert
# obligations that no property can discharge, on every design that ships
# an L8, so Step 5 could never complete honestly.
_PROVENANCE_KEYS = {
    "derived_from", "extraction_strategy", "provenance", "extracted_by",
    "emitter", "generator", "schema", "schema_version", "version",
    "generated_at", "generated_by",
}
_ARTEFACT_PATH_RE = re.compile(r"^[\w./-]+\.(json|md|txt|ya?ml)$")


def _own_and_group(prefix: str) -> Tuple[str, str]:
    """(leaf key, nearest non-index ancestor key) of a dotted path."""
    parts = [s for s in prefix.split(".") if s and not s.isdigit()]
    own = parts[-1] if parts else ""
    group = parts[-2] if len(parts) > 1 else ""
    return own, group


def _timing_semantics(value: Any, prefix: str = "") -> List[Tuple[str, str]]:
    """Find cycle/reset/latency semantics that can imply temporal properties.

    Absolute MHz/ns constraints are STA obligations, not cycle-accurate FPV
    properties. We therefore select only names that state RTL sequencing.

    A leaf qualifies when its OWN key or its nearest GROUP key names
    sequencing, or when its VALUE is a sequencing statement — not merely
    because some ancestor container carries "reset" in its name. Provenance
    keys and values that are artefact paths never qualify (see the ROUND-3
    note above `_PROVENANCE_KEYS`).
    """
    out: List[Tuple[str, str]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            k = str(key).lower()
            if k in {
                    "extraction_evidence", "evidence", "source", "source_doc",
                    "note", "description", "matched_substring"}:
                continue
            if k in _PROVENANCE_KEYS:
                continue
            p = f"{prefix}.{key}" if prefix else str(key)
            out.extend(_timing_semantics(child, p))
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            out.extend(_timing_semantics(child, f"{prefix}.{idx}"))
    else:
        text = str(value).strip()
        if not text or text.lower() in {"none", "null", "unspecified", "unknown"}:
            return out
        if _ARTEFACT_PATH_RE.match(text):
            return out
        own, group = _own_and_group(prefix)
        if (_TIMING_KEY_RE.search(own) or _TIMING_KEY_RE.search(group)
                or _TIMING_VALUE_RE.search(text)):
            out.append((prefix, text))
    return out


def declaration_obligations(project: Optional[Path]) -> dict:
    """Build the exact L3/L6/L8 formal-authoring denominator.

    This function does not translate prose into SVA. It only identifies the
    declarations whose semantic mapping needs an expert when no safe generic
    mapping exists; guessing signal names would be the false-proof path.
    """
    if project is None:
        # Pure/standalone authoring has no L-document denominator to assess.
        # The canonical in-flow caller always supplies a project.
        return {"applicability": "APPLICABLE", "obligations": [],
                "missing_declarations": [], "layer_not_applicable": []}
    docs = _read_l_docs(project)
    explicit_na = _global_formal_applicability(docs)
    if explicit_na:
        return {"applicability": "NOT_APPLICABLE",
                "declaration": explicit_na, "obligations": [],
                "missing_declarations": [], "layer_not_applicable": []}

    obligations: List[dict] = []
    missing = [layer for layer in ("L3", "L6", "L8") if not docs[layer]]
    layer_na: List[dict] = []
    for layer in ("L3", "L6", "L8"):
        for path, data in docs[layer]:
            na = _layer_is_not_applicable(path, data)
            if na:
                layer_na.append(dict(na, layer=layer))
                continue
            if layer == "L3":
                if data.get("no_opcodes_in_input") is False:
                    for idx, item in enumerate(data.get("opcodes") or []):
                        if not isinstance(item, dict):
                            continue
                        name = str(item.get("name") or item.get("hex") or idx)
                        desc = (f"command {name}: "
                                f"{item.get('purpose', 'declared command behavior')}")
                        obligations.append(_obligation(
                            "L3", f"opcode.{name}", desc, path))
                if (data.get("crc_parameters")
                        and data.get("no_crc_parameters_in_input") is False):
                    obligations.append(_obligation(
                        "L3", "crc_parameters",
                        "declared CRC acceptance/rejection behavior", path))
                for idx, rule in enumerate(data.get("reject_rules") or []):
                    obligations.append(_obligation(
                        "L3", f"reject_rule.{idx}", str(rule), path))
            elif layer == "L6":
                if data.get("no_fsm_in_input") is False:
                    for idx, state in enumerate(data.get("fsm_states") or []):
                        if not isinstance(state, dict):
                            continue
                        name = str(state.get("name") or idx)
                        detail = state.get("transitions") or state.get("actions") or []
                        obligations.append(_obligation(
                            "L6", f"fsm_state.{name}",
                            f"state {name}: {detail}", path))
                for idx, rule in enumerate(data.get("reject_rules") or []):
                    obligations.append(_obligation(
                        "L6", f"reject_rule.{idx}", str(rule), path))
            else:
                for key, text in _timing_semantics(data):
                    obligations.append(_obligation(
                        "L8", key, f"declared temporal behavior {key}={text}", path))

    # Stable IDs are part of the handoff contract. Multiple L8 files can carry
    # the same declaration; de-duplicate rather than inflate the denominator.
    uniq: Dict[str, dict] = {}
    for row in obligations:
        uniq.setdefault(row["id"], row)
    return {
        "applicability": "APPLICABLE",
        "obligations": list(uniq.values()),
        "missing_declarations": missing,
        "layer_not_applicable": layer_na,
    }


def _write_property_contract(project: Optional[Path], contract: dict) -> None:
    if project is None or _pl is None:
        return
    formal_dir = _pl.formal_dir(project)
    formal_dir.mkdir(parents=True, exist_ok=True)
    (formal_dir / PROPERTY_CONTRACT).write_text(
        json.dumps(contract, indent=2, ensure_ascii=False) + "\n")
    unresolved = contract.get("unresolved_obligations") or []
    if unresolved:
        request = {
            "program": "formal_harness_gen",
            "verdict": "INCOMPLETE",
            "fallback_skill": "formal-verify",
            "invocation_status": "REQUIRED_NOT_INVOKED",
            "property_denominator": contract.get("property_denominator", 0),
            "authored_property_count": contract.get("authored_property_count", 0),
            "unresolved_obligations": unresolved,
            "missing_declarations": contract.get("missing_declarations", []),
            "reason": (
                "applicable formal obligations remain without a sound property; "
                "invoke formal-verify on these exact IDs and record each authored "
                "property in property_contract.json before rerunning Step 5"),
        }
        (formal_dir / AUTHORING_REQUEST).write_text(
            json.dumps(request, indent=2, ensure_ascii=False) + "\n")
    else:
        stale = formal_dir / AUTHORING_REQUEST
        if stale.is_file():
            stale.unlink()


# ── comment / text hygiene ──────────────────────────────────────────────────
_LINE_COMMENT_RE = re.compile(r"//[^\n]*")
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)


def strip_comments(text: str) -> str:
    """Remove // and /* */ comments (pure). Keeps newlines so line structure
    (and the always-block sensitivity scan) stays intact."""
    text = _BLOCK_COMMENT_RE.sub(" ", text)
    text = _LINE_COMMENT_RE.sub("", text)
    return text


# ── generic hardware-convention name matchers (NOT chip literals) ───────────
# A clock / reset port is a universal RTL convention; matching the port name is
# design-independent (the actual spelling comes from the design's RTL).
_CLOCK_NAME_RE = re.compile(r"(^|_)(clk|clock|aclk|hclk|pclk|sclk|mclk)($|_|\d)",
                            re.IGNORECASE)
_RESET_NAME_RE = re.compile(
    r"(^|_)(rst|reset|resetn|rstn|nrst|nreset|arst|aresetn|por)($|_|\d|n)",
    re.IGNORECASE)
# active-low reset spellings: a trailing _n / n suffix or an `nreset`/`resetn`.
_ACTIVE_LOW_NAME_RE = re.compile(
    r"(_n$|_ni$|_n\d+$|n$|_b$)|^n(rst|reset)|reset_?n$|rst_?n$", re.IGNORECASE)


# ── module header parsing (params + ANSI ports) ─────────────────────────────
@dataclass
class Port:
    direction: str          # input / output / inout
    width: str              # e.g. "" (1-bit) or "[size-1:0]"
    name: str


@dataclass
class ModuleIface:
    name: str
    params: List[Tuple[str, str]] = field(default_factory=list)   # (name, default)
    ports: List[Port] = field(default_factory=list)
    body: str = ""


def _split_top_level(text: str, sep: str = ",") -> List[str]:
    """Split on `sep` at paren/brace/bracket depth 0 (pure)."""
    out, depth, cur = [], 0, []
    for ch in text:
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch == sep and depth == 0:
            out.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    if cur:
        out.append("".join(cur))
    return out


_MODULE_RE_TMPL = r"\bmodule\s+{name}\b"


def _find_module_span(text: str, name: str) -> Optional[Tuple[int, int, int]]:
    """Return (header_start, body_start, endmodule_start) for `module <name>`.
    body_start is the index just after the header's closing `);`."""
    m = re.search(_MODULE_RE_TMPL.format(name=re.escape(name)), text)
    if not m:
        return None
    start = m.start()
    # find the header's port-list close: the ')' that matches the first '(' after
    # the module name at depth 0, then the following ';'.
    i = m.end()
    # skip an optional parameter port list `#( ... )` and the main port list.
    depth = 0
    seen_paren = False
    header_end = None
    while i < len(text):
        ch = text[i]
        if ch == "(":
            depth += 1
            seen_paren = True
        elif ch == ")":
            depth -= 1
            if depth == 0 and seen_paren:
                # header ends at the next ';'
                j = text.find(";", i)
                header_end = (j + 1) if j != -1 else (i + 1)
                break
        i += 1
    if header_end is None:
        return None
    em = re.search(r"\bendmodule\b", text[header_end:])
    end = (header_end + em.start()) if em else len(text)
    return (start, header_end, end)


def _parse_params(header: str) -> List[Tuple[str, str]]:
    """Parse `#( parameter A = x, parameter B = y )` → [(A,x),(B,y)]."""
    mp = re.search(r"#\s*\((.*?)\)\s*\(", header, re.DOTALL)
    if not mp:
        return []
    inner = mp.group(1)
    out: List[Tuple[str, str]] = []
    for chunk in _split_top_level(inner):
        c = chunk.strip()
        if not c:
            continue
        # `parameter [type] NAME = VALUE`
        mm = re.search(
            r"(?:parameter|localparam)?\s*(?:\[[^\]]*\]\s*)?"
            r"(?:integer|int|logic|bit|signed|unsigned|\s)*"
            r"([A-Za-z_]\w*)\s*=\s*(.+)$", c)
        if mm:
            out.append((mm.group(1), mm.group(2).strip()))
    return out


def _parse_ansi_ports(header: str) -> List[Port]:
    """Parse the ANSI port list `( input wire [w] a, output b, ... )`."""
    # take the LAST top-level (...) group in the header (the port list).
    depth = 0
    last_open = None
    spans = []
    for idx, ch in enumerate(header):
        if ch == "(":
            if depth == 0:
                last_open = idx
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0 and last_open is not None:
                spans.append((last_open, idx))
    if not spans:
        return []
    open_i, close_i = spans[-1]
    inner = header[open_i + 1:close_i]
    ports: List[Port] = []
    last_dir = None
    last_width = ""
    for chunk in _split_top_level(inner):
        c = " ".join(chunk.split())
        if not c:
            continue
        md = re.match(r"^(input|output|inout)\b", c)
        if md:
            last_dir = md.group(1)
            rest = c[md.end():].strip()
            # strip net/var type keywords
            rest = re.sub(r"^(wire|reg|logic|bit|var|signed|unsigned|\s)+", "",
                          rest).strip()
            wm = re.match(r"^(\[[^\]]*\])\s*", rest)
            last_width = wm.group(1) if wm else ""
            if wm:
                rest = rest[wm.end():].strip()
            names = rest
        else:
            # continuation: same direction/width, just a name (ANSI list with
            # `input a, b` sharing the decl) — rare; keep width from previous.
            names = c
        if last_dir is None:
            continue
        for nm in _split_top_level(names):
            nm = nm.strip().rstrip(";")
            # a name may still carry its own width when list-shared
            wm2 = re.match(r"^(\[[^\]]*\])\s*(\w+)", nm)
            if wm2:
                ports.append(Port(last_dir, wm2.group(1), wm2.group(2)))
                continue
            mnm = re.match(r"^([A-Za-z_]\w*)", nm)
            if mnm:
                ports.append(Port(last_dir, last_width, mnm.group(1)))
    return ports


def parse_module(text: str, name: str) -> Optional[ModuleIface]:
    """Parse `module <name>` → ModuleIface (params + ANSI ports + body). Pure."""
    text = strip_comments(text)
    span = _find_module_span(text, name)
    if span is None:
        return None
    start, body_start, end = span
    header = text[start:body_start]
    body = text[body_start:end]
    return ModuleIface(name=name, params=_parse_params(header),
                       ports=_parse_ansi_ports(header), body=body)


# ── reset polarity + registered-output reset value analysis ─────────────────
def classify_clock(ports: List[Port]) -> Optional[str]:
    """Pick the design's clock: a 1-bit input whose name matches the clock
    convention. Returns the port name or None."""
    for p in ports:
        if p.direction == "input" and _is_scalar(p.width) \
                and _CLOCK_NAME_RE.search(p.name):
            return p.name
    return None


def classify_reset(ports: List[Port], body: str
                   ) -> Optional[Tuple[str, bool]]:
    """Pick the design's reset: a 1-bit input matching the reset convention.
    Returns (name, active_low). Polarity is decided by the name spelling and
    corroborated by how the body uses it (`if(!rst)` → active-low)."""
    for p in ports:
        if p.direction == "input" and _is_scalar(p.width) \
                and _RESET_NAME_RE.search(p.name) \
                and not _CLOCK_NAME_RE.search(p.name):
            active_low = bool(_ACTIVE_LOW_NAME_RE.search(p.name))
            # corroborate with usage: `if (!name` / `if (~name` / `if(name==0`
            if re.search(rf"if\s*\(\s*[!~]\s*{re.escape(p.name)}\b", body):
                active_low = True
            elif re.search(rf"if\s*\(\s*{re.escape(p.name)}\s*==\s*1'b0", body):
                active_low = True
            elif re.search(rf"if\s*\(\s*{re.escape(p.name)}\b\s*\)", body):
                # bare `if (name)` → active-high use (unless name says _n)
                if not _ACTIVE_LOW_NAME_RE.search(p.name):
                    active_low = False
            return (p.name, active_low)
    return None


def _is_scalar(width: str) -> bool:
    """A 1-bit port (no [..] range, or an explicit [0:0])."""
    w = width.strip()
    return w == "" or re.match(r"^\[\s*0\s*:\s*0\s*\]$", w) is not None


# an `always @( ... )` block: capture sensitivity + statement text.
_ALWAYS_RE = re.compile(
    r"always(?:_ff)?\s*@\s*\((?P<sens>[^)]*)\)\s*(?P<stmt>.*?)"
    r"(?=(?:\balways\b)|(?:\bassign\b)|(?:\bendmodule\b)|\Z)",
    re.DOTALL | re.IGNORECASE)

_ZERO_LIT_RE = re.compile(
    r"^(0|1'b0|1'h0|'0|\d+'[bhdo]0+|\{[^}]*1'b0[^}]*\}|\{[^}]*\{\s*1'b0\s*\}[^}]*\})$")
_ONE_BIT_ONE_RE = re.compile(r"^(1|1'b1|1'h1|'1)$")
_SIZED_LIT_RE = re.compile(r"^\d+'[bhdoBHDO][0-9a-fA-F_xXzZ]+$")


def _normalize_reset_const(val: str) -> Optional[str]:
    """Normalize a reset assignment RHS to a comparable Verilog constant, or
    None when it is not a plain literal (→ that output is skipped, fail-safe).
    All-zero forms collapse to `'0` (width-agnostic all-bits-zero)."""
    v = val.strip().rstrip(";").strip()
    v = " ".join(v.split())
    if _ZERO_LIT_RE.match(v.replace(" ", "")):
        return "'0"
    if _ONE_BIT_ONE_RE.match(v):
        return "1'b1"
    if _SIZED_LIT_RE.match(v):
        return v
    return None


@dataclass
class ResetFF:
    signal: str             # the registered signal reset here
    value: str              # normalized reset constant
    is_async: bool          # reset in the always sensitivity list


def _reset_branch_text(stmt: str, reset_name: str, active_low: bool
                       ) -> Optional[str]:
    """From an always block statement, return the text of the RESET branch (the
    body executed when reset is asserted), or None if no reset `if` is found."""
    # match `if ( <reset-cond> )` then capture the following statement/block.
    if active_low:
        cond = rf"[!~]\s*{re.escape(reset_name)}\b|{re.escape(reset_name)}\s*==\s*1'b0"
    else:
        cond = rf"{re.escape(reset_name)}\b(?!\s*==\s*1'b0)"
    m = re.search(rf"if\s*\(\s*(?:{cond})\s*\)", stmt)
    if not m:
        return None
    rest = stmt[m.end():].lstrip()
    if rest.startswith("begin"):
        # balanced begin..end
        depth = 0
        i = 0
        toks = re.finditer(r"\bbegin\b|\bend\b", rest)
        span_end = None
        for t in toks:
            if t.group() == "begin":
                depth += 1
            else:
                depth -= 1
                if depth == 0:
                    span_end = t.end()
                    break
        return rest[:span_end] if span_end else rest
    # single statement up to the first ';'
    j = rest.find(";")
    return rest[:j + 1] if j != -1 else rest


def find_reset_ffs(body: str, reset_name: str, active_low: bool
                   ) -> List[ResetFF]:
    """Scan clocked always blocks; for each reset-branch `sig <= const;` return
    a ResetFF(sig, normalized-const, async?). Non-literal resets are skipped."""
    out: List[ResetFF] = []
    seen = set()
    for m in _ALWAYS_RE.finditer(body):
        sens = m.group("sens")
        stmt = m.group("stmt")
        if not re.search(r"\bposedge\b|\bnegedge\b", sens):
            continue  # combinational always — no registered reset value
        is_async = bool(re.search(
            rf"(pos|neg)edge\s+{re.escape(reset_name)}\b", sens))
        branch = _reset_branch_text(stmt, reset_name, active_low)
        if branch is None:
            continue
        for am in re.finditer(
                r"([A-Za-z_]\w*)\s*<=\s*([^;]+);", branch):
            sig, rhs = am.group(1), am.group(2)
            val = _normalize_reset_const(rhs)
            if val is None or sig in seen:
                continue
            seen.add(sig)
            out.append(ResetFF(signal=sig, value=val, is_async=is_async))
    return out


def _alias_map(body: str) -> Dict[str, str]:
    """`assign out = reg;` (single identifier RHS) → {out: reg}. Only simple
    one-identifier aliases are resolved (an expression RHS is NOT a plain
    register alias and is left unmapped → that output is skipped)."""
    out: Dict[str, str] = {}
    for m in re.finditer(r"assign\s+([A-Za-z_]\w*)\s*=\s*([^;]+);", body):
        lhs, rhs = m.group(1), m.group(2).strip()
        if re.fullmatch(r"[A-Za-z_]\w*", rhs):
            out[lhs] = rhs
    return out


@dataclass
class ResetProp:
    output: str             # the OUTPUT port asserted
    target: str             # the registered signal that holds the value
    value: str              # normalized reset constant
    is_async: bool


def derive_reset_props(iface: ModuleIface, reset_name: str, active_low: bool
                       ) -> List[ResetProp]:
    """For each OUTPUT port, find its reset value (directly registered, or via a
    single `assign out = reg;` alias) → a construction-safe ResetProp. Outputs
    whose reset value cannot be pinned to a literal are omitted (fail-safe)."""
    ffs = {f.signal: f for f in find_reset_ffs(iface.body, reset_name, active_low)}
    aliases = _alias_map(iface.body)
    props: List[ResetProp] = []
    for p in iface.ports:
        if p.direction != "output":
            continue
        target = p.name
        if target not in ffs and target in aliases:
            target = aliases[target]
        ff = ffs.get(target)
        if ff is None:
            continue
        props.append(ResetProp(output=p.name, target=target, value=ff.value,
                               is_async=ff.is_async))
    return props


# ── harness emission ────────────────────────────────────────────────────────
def emit_harness(iface: ModuleIface, clock: str, reset_name: str,
                 active_low: bool, props: List[ResetProp]) -> str:
    """Emit `formal_<top>.sv`: instantiate the DUT with all ports, drive every
    non-clock input as free `(* anyseq *)`, and assert each output's reset-safety
    invariant under the guard appropriate to its FF's reset style. Pure."""
    top = iface.name
    hmod = f"formal_{top}"
    param_decl = ""
    param_conn = ""
    if iface.params:
        param_decl = " #(\n" + ",\n".join(
            f"    parameter {n} = {v}" for n, v in iface.params) + "\n)"
        param_conn = " #(" + ", ".join(
            f".{n}({n})" for n, _ in iface.params) + ")"

    in_decls, out_decls, conns = [], [], []
    for p in iface.ports:
        if p.name == clock:
            conns.append(f".{p.name}({p.name})")
            continue
        w = f"{p.width} " if p.width else ""
        if p.direction == "output":
            out_decls.append(f"    wire {w}{p.name};")
        else:
            in_decls.append(f"    (* anyseq *) wire {w}{p.name};")
        conns.append(f".{p.name}({p.name})")

    # reset-active expression (design's own polarity)
    rst_active = f"!{reset_name}" if active_low else reset_name

    # sync FFs assert one cycle after reset (rst_active_q); async FFs assert
    # while reset is currently asserted (rst_active). Both are construction-safe.
    sync_props = [p for p in props if not p.is_async]
    async_props = [p for p in props if p.is_async]

    # CONCURRENT form, and the equivalence is exact rather than approximate.
    #
    #     always @(posedge clk) if (G) assert (X);      the immediate form
    #     property p; @(posedge clk) G |-> X; endproperty
    #     assert property (p);                          the concurrent form
    #
    # Both sample G and X at the same edge and both are vacuously true when G is
    # false, so this is a change of spelling and not of meaning.  `|->` is the
    # OVERLAPPING implication on purpose: `|=>` would move the consequent one
    # cycle later and prove something the design does not claim.
    #
    # WHY THE SPELLING MATTERS.  Step 5's gate requires `property <name>` and
    # `assert property`, so the immediate form left it permanently red — and
    # until v0.2.31 of the EDA image there was no honest way out: our yosys fork
    # could not parse a named property at all (measured: 42/42 spellings
    # rejected, and a harness written to satisfy the gate returned rc=16 from
    # SymbiYosys).  Emitting it then would have traded a proof that ran for a
    # green light that did not.  The fork now parses it AND proves it — a false
    # property FAILs with a counterexample, a true one passes — so the gate can
    # be satisfied by real work rather than by relaxing it.
    prop_lines, assert_lines = [], []
    idx = 0
    for p, guard in ([(p, "rst_active_q") for p in sync_props]
                     + [(p, "rst_active") for p in async_props]):
        idx += 1
        name = f"p_reset_safety_{idx}"
        prop_lines.append(
            f"    property {name};\n"
            f"        @(posedge {clock})\n"
            f"            (f_past_valid && {guard}) |-> ({p.output} == {p.value});\n"
            f"    endproperty")
        assert_lines.append(f"    a_reset_safety_{idx}: assert property ({name});")

    body_parts = [
        "\n".join(in_decls),
        "\n".join(out_decls),
        f"    {top}{param_conn} dut ({', '.join(conns)});",
        "",
        "    reg f_past_valid = 1'b0;",
        f"    always @(posedge {clock}) f_past_valid <= 1'b1;",
        f"    wire rst_active = {rst_active};",
    ]
    if sync_props:
        body_parts += [
            "    reg rst_active_q = 1'b0;",
            f"    always @(posedge {clock}) rst_active_q <= rst_active;",
        ]
    body_parts.append("")
    body_parts += prop_lines
    if prop_lines:
        body_parts.append("")
    body_parts += assert_lines
    body = "\n".join(bp for bp in body_parts if bp is not None)

    return (
        f"// {hmod}.sv — AUTO-EMITTED deterministic reset-safety harness.\n"
        f"// Generated by formal_harness_gen.py from the design's OWN L-layer\n"
        f"// interface + reset branch (design INPUT, §4.05). No chip literal.\n"
        f"// Property: one cycle after reset, each registered output holds the\n"
        f"// exact value the RTL's reset branch assigns it (construction-safe).\n"
        f"`default_nettype none\n"
        f"module {hmod}{param_decl} (input wire {clock});\n"
        f"{body}\n"
        f"endmodule\n"
        f"`default_nettype wire\n"
    )


# ── driver ──────────────────────────────────────────────────────────────────
def _discover_rtl(rtl_dir: Path) -> List[Path]:
    if not rtl_dir.is_dir():
        return []
    files = [p for p in sorted(rtl_dir.rglob("*"))
             if p.suffix in (".v", ".sv") and p.is_file()]
    # exclude obvious testbench files (never synthesis inputs)
    return [f for f in files
            if not re.search(r"(^|_)(tb|testbench)(_|$)", f.stem, re.IGNORECASE)]


def _module_texts(rtl_files: List[Path]) -> Dict[str, Tuple[str, Path]]:
    """Map module name → (source text, file). First definition wins."""
    out: Dict[str, Tuple[str, Path]] = {}
    for f in rtl_files:
        txt = f.read_text(errors="replace")
        for name in re.findall(r"\bmodule\s+([A-Za-z_]\w*)", strip_comments(txt)):
            out.setdefault(name, (txt, f))
    return out


def _child_modules(body: str, known: List[str], self_name: str) -> List[str]:
    """Known module names INSTANTIATED in `body` (`M [#(..)] inst (`). Used to
    descend a thin rename wrapper to the leaf module that holds the logic."""
    found: List[str] = []
    for name in known:
        if name == self_name:
            continue
        if re.search(rf"\b{re.escape(name)}\b\s*(?:#\s*\([^;]*?\)\s*)?"
                     rf"[A-Za-z_]\w*\s*\(", body):
            found.append(name)
    return found


def _resolve_top(rtl_files: List[Path], top: Optional[str],
                 project: Optional[Path]) -> Optional[str]:
    if top:
        return top
    # L9 top_module
    if project is not None:
        base = project / "phase1"
        if base.is_dir():
            for cand in sorted(base.rglob("L9_INTEGRATION_SPEC.json")):
                try:
                    d = json.loads(cand.read_text(errors="replace"))
                    if d.get("top_module"):
                        return d["top_module"]
                except Exception:
                    pass
    # sole module across the RTL
    names: List[str] = []
    for f in rtl_files:
        names += re.findall(r"\bmodule\s+([A-Za-z_]\w*)",
                            strip_comments(f.read_text(errors="replace")))
    uniq = list(dict.fromkeys(names))
    return uniq[0] if len(uniq) == 1 else None


def _analyze(iface: ModuleIface) -> Optional[dict]:
    """Return the construction-safe reset-safety analysis of a parsed module, or
    None when no such property is derivable (no clock / no reset / inout / no
    registered output with a literal reset value)."""
    if any(p.direction == "inout" for p in iface.ports):
        return None
    clock = classify_clock(iface.ports)
    if not clock:
        return None
    rst = classify_reset(iface.ports, iface.body)
    if not rst:
        return None
    reset_name, active_low = rst
    props = derive_reset_props(iface, reset_name, active_low)
    if not props:
        return None
    return {"clock": clock, "reset": reset_name, "active_low": active_low,
            "props": props}


def _hierarchy_below(mtexts: Dict[str, Tuple[str, Path]], known: List[str],
                     start: str) -> List[str]:
    """Every module transitively instantiated under `start`, BFS, deterministic.

    The DESIGN, not the file set. A module that sits in the same directory but
    is instantiated nowhere under the declared top is not part of this design,
    and a property proven there describes something the flow was not asked
    about — the adjacent-measurement failure this whole line of work exists to
    remove. Children are sorted at each level so the pick is reproducible.
    """
    order: List[str] = []
    seen = {start}
    queue = [start]
    while queue:
        cur = queue.pop(0)
        entry = mtexts.get(cur)
        if entry is None:
            continue
        iface = parse_module(entry[0], cur)
        if iface is None:
            continue
        for child in sorted(_child_modules(iface.body, known, cur)):
            if child not in seen:
                seen.add(child)
                order.append(child)
                queue.append(child)
    return order


def _pick_provable(rtl_files: List[Path], top_name: Optional[str],
                   project: Optional[Path]
                   ) -> Optional[Tuple[ModuleIface, Path, dict, bool, str]]:
    """Pick a module with a construction-safe reset-safety property, PREFERRING
    the declared top and DESCENDING through thin single-child rename wrappers
    (e.g. an auto-emitted `chip_top` whose only job is to instantiate the leaf).
    Returns (iface, dut_file, analysis, descended?, basis) or None.

    THE SEARCH USED TO BE ONE PATH WHILE ITS ANSWER CLAIMED THE WHOLE DESIGN.
    ============================================================================
    The descent gives up the moment a module instantiates anything other than
    exactly one child, and `generate` then reports "no module with a
    construction-safe reset-safety property" — a statement about every module
    there is, derived from having examined a single chain of them.

    MEASURED (subservient x sky130A). `subservient` instantiates TWO children,
    `subservient_core` and `subservient_gpio`, so the walk broke at the top and
    the step reported NOT_APPLICABLE. Pointing the SAME program at
    `subservient_gpio` — same project, same RTL — emitted a complete harness
    with two construction-safe properties (`o_rdata == '0` and `o_gpio == '0`
    one cycle after reset, sync reset). The capability was there the whole time;
    only the walk could not reach it. Step 5 then failed, and steps 7, 8, 10 and
    11 went MISSING as blocked-by-upstream — one unreachable branch costing five
    canonical steps, on every hierarchical design whose top-level outputs are
    driven from more than one sub-module, which is essentially every SoC.

    So when the single-child descent ends empty, the hierarchy BELOW the
    declared top is scanned. Not the file set: a module nobody instantiates is
    not part of this design. The basis is returned and recorded, because a
    property proven on a sub-module is a WEAKER statement than one proven on the
    top, and a reader who cannot tell the two apart has been handed the same
    kind of answer this fix removes."""
    mtexts = _module_texts(rtl_files)
    if not mtexts:
        return None
    start = _resolve_top(rtl_files, top_name, project)
    if not start or start not in mtexts:
        # fall back to any single module we can prove
        start = next(iter(mtexts))
    known = list(mtexts.keys())
    visited = set()
    current = start
    descended = False
    for _ in range(len(mtexts) + 1):
        if current in visited or current not in mtexts:
            break
        visited.add(current)
        txt, f = mtexts[current]
        iface = parse_module(txt, current)
        if iface is None or not iface.ports:
            break
        analysis = _analyze(iface)
        if analysis is not None:
            return (iface, f, analysis, descended,
                    "descended_wrapper" if descended else "declared_top")
        # no property here — descend if this is a thin single-child wrapper
        children = [c for c in _child_modules(iface.body, known, current)
                    if c not in visited]
        if len(children) != 1:
            break
        current = children[0]
        descended = True

    # The descent covered ONE PATH. Before claiming the design has no provable
    # module, look at the rest of the hierarchy under the declared top — in
    # deterministic order, skipping what the walk already rejected.
    for name in _hierarchy_below(mtexts, known, start):
        if name in visited:
            continue
        visited.add(name)
        txt, f = mtexts[name]
        iface = parse_module(txt, name)
        if iface is None or not iface.ports:
            continue
        analysis = _analyze(iface)
        if analysis is not None:
            return (iface, f, analysis, True, "hierarchy_scan")
    return None


def generate(project: Optional[Path] = None, top: Optional[str] = None,
             rtl: Optional[List[Path]] = None,
             out: Optional[Path] = None) -> dict:
    """Author the deterministic floor and its declaration denominator.

    NOT_APPLICABLE is reserved for an explicit design declaration. An
    applicable design for which no safe property can be authored is
    INCOMPLETE and carries the exact expert-authoring request.
    """
    decl = declaration_obligations(project)
    if decl["applicability"] == "NOT_APPLICABLE":
        contract = {
            "program": "formal_harness_gen", "version": "2.0.0",
            "verdict": "NOT_APPLICABLE", "applicability": "NOT_APPLICABLE",
            "declaration": decl["declaration"], "property_denominator": 0,
            "authored_property_count": 0, "unresolved_obligations": [],
            "missing_declarations": [],
        }
        _write_property_contract(project, contract)
        return {"verdict": "NOT_APPLICABLE", "rc": 2,
                "reason": decl["declaration"]["reason"],
                "declaration": decl["declaration"],
                "property_denominator": 0}

    declared = list(decl["obligations"])
    for layer in decl["missing_declarations"]:
        declared.append({
            "id": f"{layer}.declaration_missing", "layer": layer,
            "source": None,
            "description": f"{layer} declaration is absent; applicability and property are unknown",
            "author": "formal-verify", "status": "DECLARATION_MISSING",
        })
    rtl_files = list(rtl) if rtl else (
        _discover_rtl(_pl.rtl_dir(project)) if (project and _pl) else [])
    if not rtl_files:
        if project is None:
            return {"verdict": "NOT_APPLICABLE", "rc": 2,
                    "reason": "no RTL sources found to derive a formal property from"}
        unresolved = declared or [{
            "id": "RTL.sources_missing", "layer": "RTL", "source": None,
            "description": "no RTL sources found to derive or bind a formal property",
            "author": "formal-verify", "status": "DECLARATION_MISSING"}]
        contract = {
            "program": "formal_harness_gen", "version": "2.0.0",
            "verdict": "INCOMPLETE", "applicability": "APPLICABLE",
            "property_denominator": len(unresolved),
            "authored_property_count": 0,
            "unresolved_obligations": unresolved,
            "missing_declarations": decl["missing_declarations"],
            "layer_not_applicable": decl["layer_not_applicable"],
        }
        _write_property_contract(project, contract)
        return {"verdict": "INCOMPLETE", "rc": 2,
                "reason": "no RTL sources found to derive or bind a formal property",
                "fallback_skill": "formal-verify",
                "property_denominator": len(unresolved),
                "unresolved_obligations": unresolved}

    picked = _pick_provable(rtl_files, top, project)
    if picked is None:
        # The claim names the scope it actually covered: the declared top and
        # every module instantiated under it. It used to say "no module" after
        # examining one chain of them.
        if project is None:
            reason = ("no module in the declared top's hierarchy has a "
                      "construction-safe reset-safety property (needs a clock, "
                      "a reset and a registered output with a literal reset "
                      "value; no inout)")
            return {"verdict": "NOT_APPLICABLE", "rc": 2, "reason": reason}
        unresolved = declared or [{
            "id": "RTL.sound_property_missing", "layer": "RTL", "source": None,
            "description": ("no construction-safe property could be bound in the "
                            "declared top hierarchy; needs a declared clock/reset "
                            "and a registered literal-reset output, or expert SVA"),
            "author": "formal-verify", "status": "UNAUTHORED"}]
        reason = ("no module in the declared top's hierarchy has a "
                  "construction-safe reset-safety property (needs a clock, a "
                  "reset and a registered output with a literal reset value; "
                  "no inout)")
        contract = {
            "program": "formal_harness_gen", "version": "2.0.0",
            "verdict": "INCOMPLETE", "applicability": "APPLICABLE",
            "property_denominator": len(unresolved),
            "authored_property_count": 0,
            "unresolved_obligations": unresolved,
            "missing_declarations": decl["missing_declarations"],
            "layer_not_applicable": decl["layer_not_applicable"],
        }
        _write_property_contract(project, contract)
        return {"verdict": "INCOMPLETE", "rc": 2, "reason": reason,
                "fallback_skill": "formal-verify",
                "property_denominator": len(unresolved),
                "unresolved_obligations": unresolved}
    iface, dut_file, analysis, descended, selection = picked
    dut_top = iface.name
    clock = analysis["clock"]
    reset_name = analysis["reset"]
    active_low = analysis["active_low"]
    props = analysis["props"]

    harness = emit_harness(iface, clock, reset_name, active_low, props)
    out_path = out or (
        (_pl.formal_dir(project) / f"formal_{dut_top}.sv")
        if (project and _pl) else Path(f"formal_{dut_top}.sv"))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(harness)
    generated = [{
        "id": f"RTL.reset_safety.{dut_top}.{p.output}",
        "layer": "RTL", "source": str(dut_file),
        "description": (f"after declared reset, {p.output} equals "
                        f"the RTL reset value {p.value}"),
        "property": f"p_reset_safety_{idx}", "status": "AUTHORED",
        "author": "formal_harness_gen",
    } for idx, p in enumerate(props, 1)]
    unresolved = declared
    contract = {
        "program": "formal_harness_gen", "version": "2.0.0",
        "verdict": "INCOMPLETE" if unresolved else "AUTHORED",
        "applicability": "APPLICABLE",
        "property_denominator": len(generated) + len(unresolved),
        "authored_property_count": len(generated),
        "covered_obligations": generated,
        "unresolved_obligations": unresolved,
        "missing_declarations": decl["missing_declarations"],
        "layer_not_applicable": decl["layer_not_applicable"],
        "fallback_skill": "formal-verify" if unresolved else None,
    }
    _write_property_contract(project, contract)
    return {
        "verdict": "EMITTED", "rc": 0,
        "top": dut_top,
        "declared_top": _resolve_top(rtl_files, top, project),
        "descended_to_leaf": descended,
        # HOW this module was reached. A property proven on a sub-module is a
        # weaker statement than one proven on the declared top, and a consumer
        # that cannot tell them apart is reading an adjacent measurement.
        "selection": selection,
        "proves_declared_top": selection == "declared_top",
        "harness_module": f"formal_{dut_top}",
        "harness_path": str(out_path),
        "dut_file": str(dut_file),
        "rtl_files": [str(f) for f in rtl_files],
        "clock": clock,
        "reset": reset_name,
        "reset_active_low": active_low,
        "properties": [
            {"output": p.output, "target": p.target, "reset_value": p.value,
             "reset_style": "async" if p.is_async else "sync"} for p in props],
        "property_denominator": contract["property_denominator"],
        "authored_property_count": contract["authored_property_count"],
        "unresolved_obligations": unresolved,
        "fallback_skill": "formal-verify" if unresolved else None,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("project_dir", type=Path, nargs="?", default=None)
    ap.add_argument("--top", default=None)
    ap.add_argument("--rtl", type=Path, nargs="*", default=None)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--json", default=None)
    args = ap.parse_args(argv)
    project = args.project_dir.resolve() if args.project_dir else None
    res = generate(project=project, top=args.top, rtl=args.rtl, out=args.out)
    rc = res.pop("rc", 0)
    out = json.dumps(res, indent=2, ensure_ascii=False)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(out)
    print(out)
    return rc


if __name__ == "__main__":
    sys.exit(main())
