#!/usr/bin/env python3
"""sdc_gen.py — auto-generate Synopsys Design Constraints (SDC).

Wave 72 deliverable. Wave 73 (v0.128) renamed from aid_class_sdc_gen.py
to reflect that the generator is class-AGNOSTIC. A backwards-compat
shim at the old path forwards calls until v0.130.

Pairs with qsf_gen.py to close the last manual-prep gap. Chip-AGNOSTIC:
clock period comes from L8.clock_mhz, port roles come from
L9.top_module_pins. No chip-specific constants.

Inputs (read from <project_dir>):
    generated_docs/L8_RTL_CONSTANTS.json
        - clock_mhz                 → period_ns = 1000 / clock_mhz (default 50)
        - clock_domains[*]          → optional richer clock spec
    generated_docs/L9_INTEGRATION_SPEC.json
        - top_module                → guides ports default
        - top_module_pins[]         → infer clock / reset / async / IO ports

Optional rtl wrapper (board namespace) — detected by scanning rtl/ for a
module with CLOCK_50/KEY/GPIO_0 ports. If present, we emit constraints
against board signal names (CLOCK_50/KEY[*]/GPIO_0[*]) so the SDC matches
what Quartus sees post-elaboration. Otherwise we emit against IC-namespace
ports (clk/reset_n/id_bus).

Output:
    <project_dir>/fpga/<top>.sdc

CLI:
    python3 sdc_gen.py <project_dir> [--board de10lite]
                                      [--top-name chip_top]
                                      [--force]

Exit codes:
    0  PASS
    1  FAIL (missing L8 / L9; or, when the top module is resolvable in rtl/,
       a deck that references a port the top does not have, a deck with no
       create_clock on a real top port, or a deck whose I/O role split walked
       a surface NARROWER than the design — see BOUNDARY COVERAGE in main())
    2  IO / arg error

Every PASS line discloses the boundary-coverage denominator, including
`NOT ASSERTED` when there is no resolvable top to compare the deck against,
so a coverage claim is never confused with an unrun check.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import _path_layout as _pl
# ONE reader for L9's top-level port contract. This generator used to read the
# single legacy alias `top_module_pins`; on a layer written with the canonical
# `top_ports` it therefore saw NO ports and emitted an SDC with no I/O delays
# at all, while the sibling gate that certifies the same layer
# (`l9_rtl_pin_consistency_check`) read the union and reported PASS.
from l_doc_consumer_contract import l9_port_direction, l9_top_ports
import sdc_constraints as _sdc


def _load_json(p: Path) -> Optional[dict]:
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _clock_mhz_from_l8_domains(l8: dict) -> Optional[float]:
    """ORGANIC #579 — resolve the clock frequency from the layer-8
    ``clock_domains[]`` records the staged-SDC ingest (#554) emits
    (top-level ``clock_mhz`` stays null on that path). Prefers the
    primary/master record; accepts ``freq_mhz`` → ``period_ns`` →
    ``freq_hz`` per record. Returns MHz or None. Chip-AGNOSTIC:
    schema keys only."""
    domains = l8.get("clock_domains")
    if not isinstance(domains, list):
        return None

    def _mhz(rec) -> Optional[float]:
        if not isinstance(rec, dict):
            return None
        for key, conv in (("freq_mhz", lambda v: float(v)),
                          ("period_ns", lambda v: 1000.0 / float(v)),
                          ("freq_hz", lambda v: float(v) / 1e6)):
            v = rec.get(key)
            if v is None:
                continue
            try:
                f = conv(v)
            except (TypeError, ValueError, ZeroDivisionError):
                continue
            if f > 0:
                return f
        return None

    primary = [r for r in domains if isinstance(r, dict)
               and (r.get("domain_kind") == "primary"
                    or r.get("role") == "master")]
    rest = [r for r in domains
            if isinstance(r, dict) and not any(r is p for p in primary)]
    for rec in primary + rest:
        f = _mhz(rec)
        if f is not None:
            return f
    return None


# v1.6.94 (issue #25 Bug 5) — AID-class half-duplex single-wire protocols
# don't need 50 MHz at the bit level (already tens of cycles per byte). On
# de10lite_top the 50 MHz default produced negative slack on the byte-
# assembler / main_fsm decode arm. 25 MHz (40 ns) is the field-agent's
# recommended fix path (b) — trivially closes timing without an RTL
# pipeline insertion. Non-AID classes (SPI / parallel-bus / etc.) keep
# the 50 MHz default.
_AID_CLASS_DEFAULT_MHZ_DE10LITE: float = 25.0
_DEFAULT_MHZ: float = 50.0

_AID_CLASS_TOKENS: tuple[str, ...] = (
    "aid",
    "apple id bus",
    "apple_id_bus",
    "single_wire_half_duplex",
    "single-wire half-duplex",
    "half_duplex_single_wire",
    "half-duplex single-wire",
    "id_bus",
    "open_drain_single_wire",
    "cable-side-id",
    "cable_side_id",
)


def _is_aid_class(project: Path, l9: dict,
                  ic_class_arg: Optional[str] = None) -> bool:
    """Return True iff the project's L9 (or sibling L1 / L2) class field
    indicates an AID-class half-duplex single-wire protocol.

    Chip-AGNOSTIC: matches on the L9 ``class_path`` / ``class`` /
    ``interface`` / ``protocol_type`` field tokens. No specific chip /
    pin / opcode hard-coded.

    v1.6.96 (issue #28 Bug 1) — also consult the ``--ic-class`` CLI arg
    first. The arg is the verdict from
    ``design_one_shot_runner.detect_ic_class`` (e.g.
    ``aid_class_half_duplex``); when present it short-circuits the
    L-doc scan, which was DEAD CODE on benchmark projects whose
    phase1 never propagated the verdict into any L doc.
    """
    if isinstance(ic_class_arg, str) and ic_class_arg:
        low = ic_class_arg.lower()
        if any(tok in low for tok in _AID_CLASS_TOKENS):
            return True
    blob_parts: list[str] = []
    for k in ("class_path", "class", "interface", "protocol_type",
              "protocol", "interface_type"):
        v = l9.get(k)
        if isinstance(v, str):
            blob_parts.append(v.lower())
    # Also check L1 + L2 if present — some flows put class on L1, protocol
    # on L2.
    gd = _pl.generated_docs_dir(project)
    for pat in ("L1*.json", "L2*.json"):
        for cand in sorted(gd.glob(pat)) if gd.is_dir() else []:
            try:
                j = json.loads(cand.read_text(encoding="utf-8",
                                              errors="ignore"))
            except Exception:
                continue
            for k in ("class_path", "class", "interface", "protocol_type",
                      "protocol", "interface_type"):
                v = j.get(k)
                if isinstance(v, str):
                    blob_parts.append(v.lower())
            # Nested: physical_layer.interface, frs_doc.protocol_type
            for outer in ("physical_layer", "frs_doc"):
                inner = j.get(outer)
                if isinstance(inner, dict):
                    for k in ("interface", "protocol_type"):
                        v = inner.get(k)
                        if isinstance(v, str):
                            blob_parts.append(v.lower())
    blob = " ".join(blob_parts)
    return any(tok in blob for tok in _AID_CLASS_TOKENS)


def _list_rtl(project: Path) -> List[Path]:
    r = _pl.rtl_dir(project)
    if not r.is_dir():
        return []
    return (sorted(r.glob("*.sv")) + sorted(r.glob("*.v")))


def _strip_v_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.DOTALL)
    text = re.sub(r"//[^\n]*", " ", text)
    return text


def _find_register_divided_clocks(
        rtl_files: List[Path]) -> List[Tuple[str, str]]:
    """Detect register-divided clocks so we can emit a matching
    ``create_generated_clock`` (otherwise STA reports zero-slack on every
    path crossing into the divider's domain and CTS will not balance the
    divider's tree).  Chip-AGNOSTIC — mirrors the detection used by
    derived_clock_sdc_required_check.py:

        Form A — combinational toggle:
            always @(posedge SRC) DIV <= ~DIV;
        Form B — counter divide:
            always @(posedge SRC) if (cnt == N-1) DIV <= ~DIV;

    Returns a de-duplicated list of (src_clk, div_clk) tuples.
    """
    found: "Dict[str, str]" = {}
    blk_re = re.compile(
        r"always\s*@\s*\(\s*posedge\s+([A-Za-z_]\w*)[^)]*\)(.*?)"
        r"(?=always\s*@|endmodule|\Z)",
        flags=re.DOTALL)
    for f in rtl_files:
        try:
            txt = _strip_v_comments(f.read_text(encoding="utf-8",
                                                errors="ignore"))
        except Exception:
            continue
        for m in blk_re.finditer(txt):
            src = m.group(1)
            body = m.group(2)
            for tm in re.finditer(
                    r"\b([A-Za-z_]\w*)\s*<=\s*~\s*\1\b", body):
                div = tm.group(1)
                if div == src:
                    continue
                found.setdefault(div, src)
    return [(src, div) for div, src in found.items()]


def _detect_board_wrapper(rtl_files: List[Path], board: str
                          ) -> Optional[Tuple[str, str]]:
    """Returns (module_name, port_signature_blob) if a board wrapper exists."""
    for f in rtl_files:
        if board.replace("-", "").lower() not in f.name.lower():
            continue
        try:
            txt = f.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        if "CLOCK_50" in txt or "GPIO_0" in txt:
            for line in txt.splitlines():
                line = line.strip()
                if line.startswith("module "):
                    name = line.split()[1].split("(")[0].strip()
                    return (name, txt)
    return None


def _skip_param_block(after: str) -> str:
    """ORGANIC #730 — given the text immediately AFTER `module ` (i.e. starting
    at the module name), return the text positioned at the port-list opening
    `(`, having skipped an optional leading `#(...)` parameter block.

    A parameterized ANSI header is `module <name> #(<params>) (<ports>)`. The
    naive `.split("(", 1)` lands on the parameter `(` and captures PARAMETER
    names as ports while dropping every real port. We therefore scan from the
    module name: the FIRST `(` that is reached without first seeing a `#` is the
    port list; if a `#` is seen first, the `(` that follows it opens the
    parameter block, which we consume with a BALANCED-paren scan, then continue
    to the port-list `(`. Non-parameterized headers (no `#`) are returned
    unchanged — the first `(` is already the port list. Chip-AGNOSTIC: pure
    Verilog/SV token structure, no chip names."""
    i = 0
    n = len(after)
    while i < n:
        c = after[i]
        if c == "#":
            # Skip whitespace/newlines between '#' and its '('.
            j = i + 1
            while j < n and after[j] in " \t\r\n":
                j += 1
            if j < n and after[j] == "(":
                # Balanced-paren consume the entire #(...) parameter block.
                depth = 0
                k = j
                while k < n:
                    if after[k] == "(":
                        depth += 1
                    elif after[k] == ")":
                        depth -= 1
                        if depth == 0:
                            k += 1
                            break
                    k += 1
                i = k  # positioned just after the closing ')' of #(...)
                continue
            # A bare '#' not opening a paren block — advance past it.
            i += 1
            continue
        if c == "(":
            # First '(' reached without a pending param block: the port list.
            return after[i:]
        i += 1
    return ""


def _parse_module_ports(txt: str) -> List[Tuple[str, str, int]]:
    """Returns list of (name, dir, width) from a module's port list."""
    if "module " not in txt:
        return []
    after = txt.split("module ", 1)[1]
    # ORGANIC #730 — skip an optional leading `#(parameter...)` block so the
    # port-list '(' is taken, NOT the parameter '(' (which would capture
    # parameter names as ports and drop every real port).
    after = _skip_param_block(after)
    if "(" not in after:
        return []
    body_after_paren = after.split("(", 1)[1]
    depth = 1
    chars: List[str] = []
    for c in body_after_paren:
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                break
        chars.append(c)
    body = "".join(chars)
    out: List[Tuple[str, str, int]] = []
    for raw in body.split(","):
        line = raw.strip().split("//")[0].strip()
        if not line:
            continue
        toks = line.replace(",", " ").split()
        direction = "input"
        for t in toks:
            if t in ("input", "output", "inout"):
                direction = t
                break
        width = 1
        for t in toks:
            if t.startswith("[") and ":" in t and "]" in t:
                inner = t.strip("[]")
                try:
                    hi, lo = inner.split(":")
                    width = abs(int(hi) - int(lo)) + 1
                except Exception:
                    pass
                break
        ident = None
        for t in toks:
            if t.isidentifier() and t not in (
                "input", "output", "inout", "wire", "reg", "logic"
            ):
                ident = t  # last identifier
        if ident:
            out.append((ident, direction, width))
    return out


_EDGE_EVENT_RE = re.compile(
    r"@\s*\(([^)]*)\)|@\s*(posedge|negedge)\s+([A-Za-z_]\w*)")
_EDGE_SIG_RE = re.compile(r"\b(?:posedge|negedge)\s+([A-Za-z_]\w*)")


def _clock_ports_from_rtl(rtl_files: List[Path], surface: set) -> List[str]:
    """Clock ports derived from the RTL's OWN edge-sensitive event controls.

    ORGANIC — `_is_clock()` is a NAME heuristic (`clk`/`clock`). A design whose
    datasheet names its clocks otherwise has NO matching port, the selection
    falls through to the bare "clk" literal, that port does not exist, and the
    emitted SDC is VACUOUS — no create_clock lands and STA has no clock at all.
    Measured on a converter whose own L1 pin table names the modulator clocks
    `CK4/CK5/CK6`: zero ports matched and sdc_gen failed
    `vacuous SDC — 1 SDC port(s) do not exist on top: ['clk']`.

    A signal appearing after `posedge`/`negedge` in an event control IS a clock
    by the definition of the language — a PROPERTY of the design, not a guess
    about its naming convention. Intersected with the synthesizable port
    surface so an internal generated clock is never emitted as a `get_ports`.

    Returned in first-appearance order (deterministic). Empty when the RTL is
    unreadable/unparseable — the caller then keeps its existing behaviour."""
    seen: List[str] = []
    for f in rtl_files:
        try:
            txt = f.read_text(errors="ignore")
        except Exception:
            continue
        for sig in _EDGE_SIG_RE.findall(txt):
            if surface and sig not in surface:
                continue
            if sig in _async_reset_signals(txt):
                # An asynchronous reset is edge-sensitive and is NOT a clock.
                #
                # The caller takes `_derived[0]`, so ORDER inside the event
                # control decided the answer:
                #   always @(posedge CK4 or negedge rst_n)  -> CK4    correct
                #   always @(negedge rst_n or posedge CK4)  -> rst_n  WRONG
                # Both spellings are legal and both are common, so the SDC got
                # a create_clock on the reset whenever the reset happened to be
                # written first — and a create_clock on a reset is worse than
                # the vacuous SDC this derivation exists to prevent.
                #
                # Recognised STRUCTURALLY, not by name: a signal that shares an
                # event control with at least one other edge-sensitive signal
                # AND is not the one the always-block's body is clocked on is
                # the async set/reset by the shape of the construct. Naming
                # (`rst`/`reset`) is the proxy this whole derivation replaced.
                continue
            if sig not in seen:
                seen.append(sig)
    return seen


def _async_reset_signals(txt: str) -> set:
    """Edge-sensitive signals that the block's own body TESTS — the async reset.

    In a multi-edge event control exactly one signal is the clock and the rest
    are async set/reset, and the body says which:

        always @(posedge CK4 or negedge rst_n)
          if (!rst_n) q <= 0; else q <= ~q;     <- rst_n is TESTED, CK4 is not

    The reset is the signal the reset branch is conditioned on. The clock never
    appears in that condition, because a clocked block does not ask whether its
    clock is high.

    POSITION IS NOT THE DISCRIMINATOR, which is what my first version used.
    `always @(negedge rst_n or posedge CK4)` is legal and common, and there the
    reset is written FIRST — a position rule picks the reset as the clock in
    exactly the case that motivated this fix.

    A single-edge control contributes nothing: there is no reset to identify.
    `negedge` alone is not it either — `always @(negedge clk)` is a legitimate
    falling-edge clock and must keep clk.
    """
    out: set = set()
    for m in re.finditer(r"@\s*\(([^)]*)\)([^;]*)", txt):
        edges = re.findall(r"\b(?:posedge|negedge)\s+([A-Za-z_]\w*)", m.group(1))
        if len(edges) < 2:
            continue
        # The first `if (...)` after the event control is the reset branch.
        cond = re.search(r"\bif\s*\(([^)]*)\)", m.group(2))
        tested = set(re.findall(r"[A-Za-z_]\w*", cond.group(1))) if cond else set()
        for e in edges:
            if e in tested:
                out.add(e)
    return out


def _collect_all_module_ports(rtl_files: List[Path]) -> set:
    """ORGANIC #619 — return the UNION of every port NAME declared by any
    module in the synthesizable RTL (rtl/). This is the design's actual
    synthesizable port surface: a name absent from it does not exist on the
    elaborated netlist, so an SDC `get_ports <name>` on it would error in
    STA/PnR.

    The UNION (across the top wrapper AND its inner/sub-modules) is used
    deliberately rather than only the top module's ports: the reset/clock
    alias wrapper (#518/#618) renames the top's clock/reset port while the
    inner `*__rcvar_inner` keeps the original spelling, so the union holds
    BOTH spellings — filtering against it never drops a legitimately-present
    port merely because of an alias rename. Returns an empty set when rtl/ is
    absent or unparseable (callers then DO NOT filter — pure-L9 fallback).
    Chip-AGNOSTIC: pure Verilog module-header parsing, no chip names."""
    names: set = set()
    mod_hdr = re.compile(r"\bmodule\s+[A-Za-z_]\w*")
    for f in rtl_files:
        try:
            txt = _strip_v_comments(f.read_text(encoding="utf-8",
                                                errors="ignore"))
        except Exception:
            continue
        # Parse each module's port list independently (a file may declare
        # several modules — e.g. chip_top + chip_top__rcvar_inner).
        for m in mod_hdr.finditer(txt):
            for name, _dir, _w in _parse_module_ports(txt[m.start():]):
                if name:
                    names.add(name)
    return names


def _named_module_ports(rtl_files: List[Path], top_name: str) -> Optional[set]:
    """#207 — the port NAMES declared by the TOP module `top_name`, or None
    when that module is not found/parseable in rtl/.

    This is the AUTHORITATIVE surface that STA will constrain: the netlist top's
    OWN ports, narrower and more precise than the all-modules union (#619). The
    union admits a name that lives only on an INNER module (e.g. an alias
    wrapper's `*__rcvar_inner` keeps `clk_i` while the top exposes the renamed
    `clk`) — but an SDC `[get_ports clk_i]` on such an internal net makes STA
    error, which is exactly the vacuous-SDC failure #207 reports. When the top
    module is resolvable we select AND validate against these ports; when it is
    not (no rtl/, or the top module absent), the caller falls back to the union
    (pure-L9 behaviour preserved). Chip-AGNOSTIC: Verilog header parsing only."""
    pat = re.compile(r"\bmodule\s+" + re.escape(top_name) + r"\b")
    for f in rtl_files:
        try:
            txt = _strip_v_comments(f.read_text(encoding="utf-8",
                                                errors="ignore"))
        except Exception:
            continue
        m = pat.search(txt)
        if not m:
            continue
        names = {name for name, _d, _w in _parse_module_ports(txt[m.start():])
                 if name}
        return names or None
    return None


def _named_module_port_records(
        rtl_files: List[Path],
        top_name: str) -> Optional[List[Tuple[str, str, int]]]:
    """The FULL (name, direction, width) records declared by the TOP module
    `top_name`, or None when that module is not found/parseable in rtl/.

    `_named_module_ports` returns only the NAMES, because #207/#619 use the
    surface as a FILTER. This returns the same surface with the RTL's own
    declared DIRECTION attached, so the surface can also be used as a SOURCE
    when the L9 pin list under-covers it (see the residue pass in main()).
    Same resolution order and same parser as `_named_module_ports`, so the two
    can never disagree about which module is the top. Chip-AGNOSTIC: Verilog
    module-header parsing only, no chip / PDK / vendor names."""
    pat = re.compile(r"\bmodule\s+" + re.escape(top_name) + r"\b")
    for f in rtl_files:
        try:
            txt = _strip_v_comments(f.read_text(encoding="utf-8",
                                                errors="ignore"))
        except Exception:
            continue
        m = pat.search(txt)
        if not m:
            continue
        recs = [(name, direction, width)
                for name, direction, width in _parse_module_ports(
                    txt[m.start():]) if name]
        return recs or None
    return None


def _sdc_port_refs(text: str) -> Tuple[List[str], List[str]]:
    """#207 — (clock_refs, all_refs): the base port NAMES referenced by
    `[get_ports {...}]` in the SDC, bus index stripped. `clock_refs` are those
    on a `create_clock` line (the clock targets); `all_refs` is every get_ports
    reference. `get_pins` (internal register pins on create_generated_clock) is
    deliberately excluded — those are not top ports."""
    clock_refs: List[str] = []
    all_refs: List[str] = []
    for line in text.splitlines():
        is_clock_line = line.lstrip().startswith("create_clock")
        for m in re.finditer(r"get_ports\s*\{([^}]*)\}", line):
            for tok in m.group(1).split():
                base = re.sub(r"\[.*$", "", tok).strip()
                if not base:
                    continue
                all_refs.append(base)
                if is_clock_line:
                    clock_refs.append(base)
    return clock_refs, all_refs


# ---------------------------------------------------------------------------
# Port classification
# ---------------------------------------------------------------------------
def _is_clock(name: str) -> bool:
    n = name.lower()
    return ("clk" in n) or ("clock" in n)


def _l8_declared_clocks(l8: dict) -> List[Tuple[str, Optional[float]]]:
    """Clocks L8 DECLARES, as ``[(canonical_name, period_ns|None), ...]``.

    C4/2026-07-31 — measured defect. ``_is_clock`` is a NAME-SHAPE GUESS
    (``"clk" in n or "clock" in n``). On a design whose clock ports are
    ``CK4/CK5/CK6`` it matches nothing, so all three were classified as
    synchronous DATA inputs, ``clock_port`` fell back to the literal
    ``"clk"`` — a port the design does not have — and the emitted SDC
    constrained a non-existent port while leaving every real clock
    unconstrained. Step 8's ``sdc_validator_check`` caught it exactly:
    *"L8 declares clock 'CK4' but no SDC constrains it"*.

    L8 is not a guess: it is the layer that DECLARES the design's clock
    contract, with extraction evidence. When it names a clock, that
    declaration outranks a substring test on the port name. This helper is
    the property; ``_is_clock`` stays as the fallback for designs whose L8
    declares nothing.

    Purely ADDITIVE: returns ``[]`` when L8 declares no clock record, and
    every call site below is guarded on a non-empty result, so a design
    that constrains correctly today cannot change.
    """
    out: List[Tuple[str, Optional[float]]] = []
    seen: set = set()
    if not isinstance(l8, dict):
        return out
    for key in ("clock_domains", "clocks"):
        for rec in (l8.get(key) or []):
            if not isinstance(rec, dict):
                continue
            name = (rec.get("name") or rec.get("source_pin") or "").strip()
            if not name or name.lower() in seen:
                continue
            seen.add(name.lower())
            period: Optional[float] = None
            for k, conv in (("period_ns", lambda v: float(v)),
                            ("freq_mhz", lambda v: 1000.0 / float(v)),
                            ("freq_hz", lambda v: 1.0e9 / float(v))):
                v = rec.get(k)
                if v in (None, "", 0):
                    continue
                try:
                    cand = conv(v)
                except (TypeError, ValueError, ZeroDivisionError):
                    continue
                if cand > 0:
                    period = cand
                    break
            out.append((name, period))
    return out


def _is_reset(name: str) -> bool:
    n = name.lower()
    return ("reset" in n) or ("rst" in n)


def _is_async_io(name: str) -> bool:
    n = name.lower()
    # Only hard-async tokens: physical switches/keys, GPIO, id_bus.
    # "data" and "io" removed (#555): they match sync bus signals such as
    # instr_rdata_i / data_addr_o and produce false_path instead of timed I/O.
    return any(tok in n for tok in ("key", "sw", "switch", "gpio", "id_bus"))


def _is_output(name: str, direction: str) -> bool:
    if direction == "output":
        return True
    n = name.lower()
    return any(tok in n for tok in ("led", "hex", "out"))


# ---------------------------------------------------------------------------
# SDC rendering
# ---------------------------------------------------------------------------
def _render_sdc(top: str, clock_port: str, period_ns: float,
                inputs: List[str], outputs: List[str],
                async_ports: List[str],
                gen_clocks: Optional[List[Tuple[str, str]]] = None,
                l8_clocks: Optional[
                    List[Tuple[str, str, float]]] = None) -> str:
    period_str = f"{period_ns:.3f}".rstrip("0").rstrip(".") or "20"
    lines: List[str] = []
    lines.append("# =========================================================================")
    # The banner is the SHARED emitter/checker constant, not a local literal:
    # `sdc_validator_check` proves a deck on disk is THIS generator's output by
    # looking for it, and a second spelling here would make the checker stop
    # recognising what this function writes.
    lines.append(f"# {_sdc.GENERATED_BANNER} (Wave 72/73)")
    lines.append(f"# Top entity: {top}")
    lines.append(f"# Clock: {clock_port} period={period_str} ns")
    lines.append("# DO NOT hand-edit; regenerate via sdc_gen.py.")
    lines.append("# =========================================================================")
    lines.append("")
    # Pick a short user-friendly clock name
    clock_label = "clk_main"
    if "50" in clock_port:
        clock_label = "clk_50"
    elif "100" in clock_port:
        clock_label = "clk_100"
    if l8_clocks:
        # C4/2026-07-31 — L8 DECLARES this design's clocks by name. Emit one
        # create_clock per declared clock, named as L8 names it, on the port
        # L8 binds it to, at the period L8 carries. The former single
        # create_clock left every additional declared clock unconstrained,
        # which is exactly what Step 8 reports. The first declared clock
        # supplies the label the I/O delays reference, so a design with one
        # clock renders as before apart from that clock's real name.
        lines.append("# Clocks DECLARED by L8 (name + port + period from the "
                     "design's own layer, not from a port-name guess)")
        for c_name, c_port, c_period in l8_clocks:
            p_str = f"{c_period:.3f}".rstrip("0").rstrip(".") or period_str
            lines.append(f"create_clock -name {c_name} -period {p_str} "
                         f"[get_ports {{{c_port}}}]")
        clock_label = l8_clocks[0][0]
    else:
        lines.append(f"create_clock -name {clock_label} -period {period_str} "
                     f"[get_ports {{{clock_port}}}]")
    lines.append("derive_pll_clocks")
    lines.append("derive_clock_uncertainty")
    lines.append("")
    # Register-divided clocks (e.g. an MDC management clock toggled by an
    # internal FSM counter): each needs a create_generated_clock so STA
    # propagates a clock onto the divider's domain and CTS balances its
    # tree. Divide ratio is left at 2 (the toggle factor) — the deterministic
    # generator cannot know the runtime counter modulus; the actual ratio is
    # parameterised in RTL and refined at PnR if needed.
    if gen_clocks:
        lines.append("# Register-divided (generated) clocks")
        for src, div in gen_clocks:
            lines.append(
                f"create_generated_clock -name {div} -divide_by 2 "
                f"-source [get_ports {{{src}}}] [get_pins {{{div}_reg/Q}}]")
        lines.append("")
    if inputs:
        lines.append("# Synchronous data inputs (moderate setup/hold)")
        for sig in inputs:
            lines.append(f"set_input_delay  -clock {clock_label} -max 4.0 "
                         f"[get_ports {{{sig}}}]")
            lines.append(f"set_input_delay  -clock {clock_label} -min 0.0 "
                         f"[get_ports {{{sig}}}]")
        lines.append("")
    if outputs:
        lines.append("# Outputs")
        for sig in outputs:
            lines.append(f"set_output_delay -clock {clock_label} -max 4.0 "
                         f"[get_ports {{{sig}}}]")
            lines.append(f"set_output_delay -clock {clock_label} -min 0.0 "
                         f"[get_ports {{{sig}}}]")
        lines.append("")
    if async_ports:
        lines.append("# Async inputs / open-drain shared bus → false_path")
        # collapse to wildcard groups when names share a base
        base_groups: Dict[str, bool] = {}
        for s in async_ports:
            m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\[", s)
            base = m.group(1) + "[*]" if m else s
            base_groups[base] = True
        for s in base_groups:
            lines.append(f"set_false_path -from [get_ports {{{s}}}] "
                         f"-to [all_clocks]")
            lines.append(f"set_false_path -from [all_clocks] "
                         f"-to [get_ports {{{s}}}]")
        lines.append("")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------
def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("project", type=Path)
    p.add_argument("--board", default="de10lite", choices=["de10lite"])
    p.add_argument("--top-name", default=None)
    p.add_argument("--force", action="store_true")
    # v1.6.96 (issue #28 Bug 1) — explicit IC class hint from the
    # phase2 runner's detect_ic_class step. Short-circuits the L-doc
    # scan so the AID-class default fires even on projects whose
    # phase1 never propagated the verdict into L9.interface_type /
    # L1.class_path.
    p.add_argument("--ic-class", default=None,
                   help="IC class verdict from detect_ic_class "
                        "(e.g. aid_class_half_duplex)")
    args = p.parse_args(argv)

    project = args.project.resolve()
    if not project.is_dir():
        print(f"ERROR: not a directory: {project}", file=sys.stderr)
        return 2

    l8 = _load_json(_pl.generated_docs_dir(project) / "L8_RTL_CONSTANTS.json")
    l9 = _load_json(_pl.generated_docs_dir(project) / "L9_INTEGRATION_SPEC.json")
    if l8 is None or l9 is None:
        print("FAIL: missing L8 or L9", file=sys.stderr)
        return 1

    # v1.6.94 (issue #25 Bug 5) — AID-class half-duplex single-wire on
    # de10lite_top relaxes to 25 MHz (40 ns); other classes / boards keep
    # the L8.clock_mhz value (default 50 MHz). Only relax when L8 hasn't
    # been pinned to an explicit non-default — explicit `clock_mhz` always
    # wins over the per-class default.
    # ORGANIC #579 — the staged-SDC ingest (#554) records the project's
    # clock contract as L8.clock_domains[] (freq_mhz/period_ns) with the
    # top-level clock_mhz left null; consult it (then the staged SDC files
    # via the shared sdc_constraints module, #556 r2 precedent) BEFORE
    # falling back to the 50 MHz default — otherwise the generator emits a
    # wrong-period SDC while the sibling checker reads the real period and
    # the structural gate can never pass on the staged-SDC path.
    explicit_clock = l8.get("clock_mhz")
    if explicit_clock is not None:
        try:
            clock_mhz = float(explicit_clock)
        except Exception:
            clock_mhz = _DEFAULT_MHZ
    else:
        domains_mhz = _clock_mhz_from_l8_domains(l8)
        staged = None
        if domains_mhz is None:
            staged = _sdc.primary_clock(project)
        if domains_mhz is not None:
            clock_mhz = domains_mhz
        elif staged is not None and staged.get("period_ns"):
            clock_mhz = 1000.0 / float(staged["period_ns"])
        else:
            clock_mhz = _DEFAULT_MHZ
            if args.board == "de10lite" and _is_aid_class(
                    project, l9, getattr(args, "ic_class", None)):
                clock_mhz = _AID_CLASS_DEFAULT_MHZ_DE10LITE
    period_ns = 1000.0 / clock_mhz

    rtl_files = _list_rtl(project)
    wrapper = _detect_board_wrapper(rtl_files, args.board)

    # Decide top
    if args.top_name:
        top = args.top_name
    elif wrapper:
        top = wrapper[0]
    else:
        top = l9.get("top_module") or "chip_top"

    # #207 — the AUTHORITATIVE surface STA constrains is the TOP module's OWN
    # ports. Resolve them; fall back to the all-modules union (#619) only when
    # the top module is not resolvable in rtl/. Selecting AND validating against
    # the top's ports is what stops a create_clock landing on an inner-module net
    # (e.g. alias-wrapper `clk_i`) that does not exist on chip_top.
    top_ports = _named_module_ports(rtl_files, top)

    # Decide port set: prefer wrapper ports (board namespace) when wrapper
    # is the top entity, else fall back to L9.top_module_pins.
    inputs: List[str] = []
    outputs: List[str] = []
    async_ports: List[str] = []
    clock_port: Optional[str] = None
    dropped_pins: List[str] = []
    residue_pins: List[str] = []  # top-surface ports L9 never covered
    rtl_ports: set = set()  # synthesizable RTL surface used to filter (#619/#207)
    # THE SURFACE THE ROLE SPLIT ACTUALLY WALKED. Every branch below records
    # the top-surface port names it LOOKED AT here, whatever it then decided.
    # This is what makes the coverage assertion at the end of main() able to
    # separate "the split saw this port and routed it" from "the split never
    # reached this port at all" — the second is the surface being narrower
    # than the design, which is the defect the assertion exists for. An L9
    # pin dropped by the #619/#207 surface filter is NOT recorded: that name
    # is not on the top, so the top port it failed to describe stays unseen.
    examined: set = set()

    # C4/2026-07-31 — L8's DECLARED clock contract. Ports named here are
    # clocks by DECLARATION, not by a substring test on their name; see
    # _l8_declared_clocks. Empty for a design whose L8 declares nothing,
    # in which case every use below is inert.
    # Both L8 docs carry the clock contract — the runner's own
    # `_CLOCK_CONTRACT_DOCS = ("L8_RTL_CONSTANTS", "L8_TIMING_WAVEFORM")`
    # says so, and the Phase-1 `clocks[]` seeder writes the TIMING_WAVEFORM
    # one. Reading only RTL_CONSTANTS is why a declared clock could be
    # invisible here while a sibling gate saw it.
    _l8_wave = _load_json(
        _pl.generated_docs_dir(project) / "L8_TIMING_WAVEFORM.json") or {}
    _l8_clocks = _l8_declared_clocks(l8)
    _seen_l8 = {n.lower() for n, _ in _l8_clocks}
    for _n, _p in _l8_declared_clocks(_l8_wave):
        if _n.lower() not in _seen_l8:
            _seen_l8.add(_n.lower())
            _l8_clocks.append((_n, _p))
    _l8_clock_names = {n.lower() for n, _ in _l8_clocks}
    _l8_period_by_name = {n.lower(): p for n, p in _l8_clocks}
    _l8_canonical = {n.lower(): n for n, _ in _l8_clocks}
    _l8_clock_ports: List[str] = []

    def _port_is_clock(nm: str) -> bool:
        if nm and nm.lower() in _l8_clock_names:
            return True
        return _is_clock(nm)

    if wrapper and top == wrapper[0]:
        ports = _parse_module_ports(wrapper[1])
        for name, direction, width in ports:
            examined.add(name)
            sigs = ([name] if width == 1
                    else [f"{name}[{i}]" for i in range(width)])
            if _port_is_clock(name):
                clock_port = name if width == 1 else f"{name}[0]"
                if name.lower() in _l8_clock_names:
                    _l8_clock_ports.append(name)
                continue
            if _is_reset(name) or _is_async_io(name):
                async_ports.extend(sigs)
                continue
            if _is_output(name, direction):
                outputs.extend(sigs)
            else:
                inputs.extend(sigs)
    else:
        # L9 namespace. ORGANIC #619 — the L9 doc top_module_pins describe the
        # FULL upstream IP surface (all config-gated security/ECC/lockstep/
        # debug ports), but for a config-reduced-wrapper / REUSED-IP design the
        # synthesizable RTL top exposes only the enabled subset. Emitting
        # set_input/output_delay [get_ports <name>] for an L9 pin that is NOT
        # on the synthesizable surface makes STA/PnR error out on that
        # constraint. So intersect the L9 pin list with the actual RTL port
        # surface (union of all rtl/ module ports). When rtl/ is absent /
        # unparseable, rtl_ports is empty and NO filtering happens (pure-L9
        # fallback preserved). Chip-AGNOSTIC: set membership on parsed ports.
        # #207 — filter against the TOP module's OWN ports when resolvable (so
        # an L9 pin that lives only on an inner module is dropped, not emitted
        # as an STA-invalid get_ports). Fall back to the all-modules union
        # (#619) only when the top module is unresolvable; empty ⇒ no filtering.
        rtl_ports = (top_ports if top_ports is not None
                     else _collect_all_module_ports(rtl_files))
        for port in l9_top_ports(l9):
            if not isinstance(port, dict):
                continue
            name = port.get("name", "")
            if rtl_ports and name and name not in rtl_ports:
                dropped_pins.append(name)
                continue
            if name:
                examined.add(name)
            # Direction via the shared accessor: the promoter writes `dir`,
            # older writers wrote `mode`. Testing one spelling read a missing
            # key and sent EVERY port — outputs included — down the `inputs`
            # branch, so every output port got a `set_input_delay`.
            _dir = l9_port_direction(port)
            if _port_is_clock(name):
                clock_port = name
                if name.lower() in _l8_clock_names:
                    _l8_clock_ports.append(name)
                continue
            if _is_reset(name) or _dir == "inout" or _is_async_io(name):
                async_ports.append(name)
                continue
            if _dir == "out":
                outputs.append(name)
            else:
                inputs.append(name)

        # ---- SURFACE RESIDUE -------------------------------------------
        # The loop above filters the L9 pin list AGAINST the synthesizable top
        # surface (#619/#207) but never reads that surface as a SOURCE. When
        # L9 spells a pin differently from the RTL that implements it, the pin
        # is DROPPED and the port it describes is left with no I/O constraint
        # at all — an untimed path that STA reports nothing about and no gate
        # sees, because an SDC missing a whole direction is still syntactically
        # valid. In the limit every input is dropped and the deck carries no
        # `set_input_delay` whatsoever.
        #
        # So: after L9 has had its say, constrain the RESIDUE — the top
        # module's own ports that nothing above classified — using the RTL's
        # OWN declared direction. The residue is empty whenever L9 covers the
        # surface, so a design that constrains correctly today renders
        # byte-identically. Ports come from the same parse #207 already trusts
        # to VALIDATE the deck, so this can only ever name a port that exists.
        # Chip-AGNOSTIC: set difference on parsed Verilog headers.
        _recs = (_named_module_port_records(rtl_files, top)
                 if top_ports is not None else None)
        # `_parse_module_ports` DEFAULTS an undirected port to "input" — which
        # is what a NON-ANSI header (`module m(a,b); input a; output b;`) parses
        # as, every port included. Classifying that residue would put a
        # `set_input_delay` on an output and make STA error. So the residue is
        # only trusted when the header actually declares direction in-line, i.e.
        # at least one output/inout token was parsed. A non-ANSI top renders
        # exactly as it does today.
        if _recs and not any((d or "").lower() in ("output", "inout")
                             for _n, d, _w in _recs):
            _recs = None
        if _recs:
            _claimed = {clock_port} | set(inputs) | set(outputs) \
                | set(async_ports) | set(_l8_clock_ports)
            for _name, _dir, _w in _recs:
                if not _name or _name in _claimed:
                    continue
                _claimed.add(_name)
                examined.add(_name)
                if _port_is_clock(_name):
                    # A clock the L9 pin list never mentioned. Record it so the
                    # clock-resolution fallback below can bind it; do NOT give
                    # it an I/O delay.
                    if _name.lower() in _l8_clock_names:
                        _l8_clock_ports.append(_name)
                    continue
                if _is_reset(_name) or "inout" in (_dir or "").lower() \
                        or _is_async_io(_name):
                    async_ports.append(_name)
                    residue_pins.append(_name)
                    continue
                if _is_output(_name, _dir or ""):
                    outputs.append(_name)
                else:
                    inputs.append(_name)
                residue_pins.append(_name)

    if not clock_port:
        # Fallback: take first 'clk*' from L9 that EXISTS on the synthesizable
        # surface (#619), else a clock-like TOP port (#207 — never a default
        # guess that isn't actually a port), else 'clk'.
        clock_port = "clk"
        for port in l9_top_ports(l9):
            if not (isinstance(port, dict) and _is_clock(port.get("name", ""))):
                continue
            cand = port["name"]
            if rtl_ports and cand not in rtl_ports:
                continue  # #619: don't bind a clock absent from the RTL surface
            clock_port = cand
            break
        else:
            # No L9 clock pin survived the surface filter. #207 — prefer an
            # actual clock-like port ON the top interface over the bare "clk"
            # guess, so the alias-wrapper top (`clk_i`→`clk`) is constrained on
            # its REAL port and STA gets a live clock.
            if top_ports and clock_port not in top_ports:
                for pname in sorted(top_ports):
                    if _is_clock(pname):
                        clock_port = pname
                        break

    # Last resort BEFORE emitting a vacuous SDC: if everything above settled on
    # a port that does not exist on the design's surface, derive the clock from
    # the RTL's own `posedge`/`negedge` event controls (a PROPERTY, not a naming
    # convention). Purely ADDITIVE — it can only fire in the case that currently
    # produces `vacuous SDC ... do not exist on top`, i.e. a FAIL, so no design
    # that constrains correctly today can change.
    _surface = rtl_ports or (top_ports or set())
    if _surface and clock_port not in _surface:
        _derived = _clock_ports_from_rtl(rtl_files, _surface)
        if _derived:
            clock_port = _derived[0]
            print(f"NOTE: clock port derived from RTL edge-sensitive event "
                  f"controls: {_derived} -> using '{clock_port}' "
                  f"(no name-matched clock port on the top surface)")

    fpga_dir = _pl.fpga_early_dir(project)
    fpga_dir.mkdir(parents=True, exist_ok=True)
    out = fpga_dir / f"{top}.sdc"
    if out.exists() and not args.force:
        print(f"SKIP: {out} exists (use --force to overwrite)")
        return 0

    gen_clocks = _find_register_divided_clocks(rtl_files)

    # C4/2026-07-31 — assemble the per-clock create_clock set from L8's own
    # declaration. Each entry is (name-as-L8-spells-it, port-as-the-design
    # -spells-it, period_ns). A clock whose period L8 does not carry falls
    # back to the period resolved above rather than being dropped, so a
    # partially-specified L8 still constrains every port it declares.
    # `_l8_clock_ports` is only ever appended to for a port that is BOTH on
    # the design's surface AND named by L8, so this cannot constrain a port
    # that does not exist.
    l8_clock_set: List[Tuple[str, str, float]] = []
    for _p in _l8_clock_ports:
        _key = _p.lower()
        _per = _l8_period_by_name.get(_key) or period_ns
        l8_clock_set.append((_l8_canonical.get(_key, _p), _p, _per))
    if l8_clock_set:
        clock_port = l8_clock_set[0][1]
        period_ns = l8_clock_set[0][2]
        print("NOTE: clock port(s) taken from L8's DECLARED clock contract: "
              + ", ".join(f"{n}@{p:g}ns on '{pt}'"
                          for n, pt, p in l8_clock_set))

    # DEGRADE LOUDLY. `_render_sdc` emits the `set_input_delay` block only
    # `if inputs:` and the `set_output_delay` block only `if outputs:`, so an
    # empty role split renders a syntactically fine SDC in which every I/O
    # path is UNCONSTRAINED — and the old code printed nothing about it. The
    # generator is the one place that knows the port roles came out empty
    # while the layer it read was non-empty; say so here rather than leaving
    # Step 8's validator to report `missing set_input_delay` several steps
    # later with no indication of why.
    if not inputs and not outputs:
        _declared = len(l9_top_ports(l9))
        print("NOTE: no I/O ports classified — the emitted SDC constrains NO "
              "input or output path. L9 declares %d top-level port record(s); "
              "%d were dropped as absent from the synthesizable surface. "
              "Every remaining port was consumed as a clock/reset/async pin."
              % (_declared, len(dropped_pins)))

    text = _render_sdc(top, clock_port, period_ns, inputs, outputs,
                       async_ports, gen_clocks, l8_clock_set or None)
    out.write_text(text, encoding="utf-8")

    # #207 — VALIDATE the generated SDC against the netlist it constrains. A
    # create_clock (or any get_ports) targeting a port that does NOT exist on
    # the top is an ERROR, not a warning: STA runs with no clock in effect and
    # reports meaningless slack while the step vacuously PASSes. When the top
    # module's own ports are resolvable, refuse to emit a vacuous PASS:
    #   (1) every get_ports name must exist on the top interface, and
    #   (2) at least one clock must be created on a REAL top port.
    # Evidence (resolved ports, unresolved names, the netlist resolved against)
    # is written so the verdict can be cross-checked from the gate's own output.
    # When the top is unresolvable (no rtl/), validation is skipped (pure-L9
    # fallback preserved) — there is no netlist to resolve names against.
    validation: Dict[str, object] = {
        "top": top,
        "resolved_against": (str(out.parent) + f"::module {top} (rtl/)"
                             if top_ports is not None else None),
        "top_ports": (sorted(top_ports) if top_ports is not None else None),
        "dropped_l9_pins": sorted(dropped_pins),
        "residue_pins_constrained": sorted(residue_pins),
    }
    # Denominator of the coverage assertion, for the PASS line below. Stays at
    # NOT ASSERTED unless there is a declared port list to assert against, so
    # "no gap reported" can never be read as "no gap".
    _cov_note = (f"; boundary coverage NOT ASSERTED — top '{top}' is not "
                 f"resolvable in rtl/, so the deck was not compared against "
                 f"any declared port list")
    if top_ports is not None:
        clock_refs, all_refs = _sdc_port_refs(text)
        unresolved = sorted({r for r in all_refs if r not in top_ports})
        live_clocks = [c for c in clock_refs if c in top_ports]
        # ---- BOUNDARY COVERAGE (the mirror of `unresolved`) --------------
        # `unresolved` asks "does every name the deck REFERENCES exist on the
        # design?" — the deck's claims resolved against the netlist. It is
        # blind to the question a sign-off deck is actually judged on: does
        # the deck REACH every port the design declares?
        #
        # The role split above walks the L9 pin list plus whatever residue the
        # RTL header yields. BOTH of those can be NARROWER than the interface
        # the design declares — e.g. a NON-ANSI top header (`module m(a,b);
        # input a; output b;`) parses with no in-line direction, so the
        # residue pass is deliberately disarmed and every port L9 missed is
        # classified by nobody. The deck is still emitted, is still
        # syntactically valid, and says nothing: "constrained the whole
        # boundary" and "constrained part of it" were the same observable,
        # exit code included.
        #
        # So compute the coverage and NAME the gap. A port referenced by ANY
        # constraint counts as covered — create_clock, set_input_delay,
        # set_output_delay or set_false_path — so this measures REACH, and
        # never second-guesses a role the split legitimately chose.
        #
        # WHAT THE ASSERTION FAILS ON is narrower than what it NAMES, on
        # purpose. The captured defect is a split walking a surface narrower
        # than the design, so the gate fires on `unreached`: a declared port
        # that no branch ever looked at AND that carries no constraint. A port
        # the split DID examine and route (`examined`) is accounted for — if
        # it still ends up unconstrained the cause is downstream of the split
        # (the single `clock_port` slot being overwritten by a later
        # clock-named port is the measured one), which is a different defect
        # with a different fix, and failing sign-off on it here would be this
        # rule taking credit for a hole it does not repair. Both sets are
        # written to the gate JSON and both are printed, so neither is silent.
        #
        # The gate also stands down when the split produced NO I/O role at
        # all: that tier already has its own diagnostic and its own
        # deliberate exit-0 (#744, below) — "a layer that declares no ports is
        # the design's problem, not this generator's". This rule is about the
        # PARTIAL split, which had no diagnostic at all.
        #
        # Chip-AGNOSTIC: set arithmetic over the parsed top header and the
        # deck's own get_ports references; no design, PDK or vendor literal.
        _ref_set = set(all_refs)
        uncovered = sorted(p for p in top_ports if p not in _ref_set)
        unreached = [p for p in uncovered if p not in examined]
        _assert_coverage = bool(inputs or outputs)
        validation.update(unresolved_ports=unresolved,
                          clock_ports=clock_refs,
                          live_clocks=live_clocks,
                          constrained_ports=sorted(top_ports & _ref_set),
                          uncovered_ports=uncovered,
                          uncovered_ports_never_examined=unreached,
                          role_split_examined_ports=sorted(
                              top_ports & examined),
                          coverage_asserted=_assert_coverage,
                          boundary_coverage=(
                              f"{len(top_ports) - len(uncovered)}/"
                              f"{len(top_ports)}"))
        try:
            gate_json = _pl.report_path(project, "phase2/gates/sdc_gen.json")
            gate_json.parent.mkdir(parents=True, exist_ok=True)
            gate_json.write_text(json.dumps(validation, indent=2),
                                 encoding="utf-8")
        except Exception:
            pass
        _cov_note = (f"; boundary coverage "
                     f"{len(top_ports) - len(uncovered)}/{len(top_ports)} "
                     f"declared port(s) of top '{top}' constrained"
                     + (f", {len(uncovered)} unconstrained: {uncovered}"
                        if uncovered else "")
                     + ("" if _assert_coverage else
                        " (gate stood down: the role split produced no I/O "
                        "role at all — see the #744 tier below)"))
        # NAME THE GAP WHETHER OR NOT IT FAILS. Silence is what this rule was
        # captured for; the exit code is only the sharpest end of it.
        if uncovered:
            print(f"NOTE sdc_gen: boundary coverage "
                  f"{len(top_ports) - len(uncovered)}/{len(top_ports)} — "
                  f"{len(uncovered)} port(s) declared by top '{top}' are "
                  f"referenced by NO constraint in the emitted deck, so every "
                  f"path through them is UNCONSTRAINED and STA will report "
                  f"nothing about it: {uncovered}"
                  + (f" (of which {unreached} the I/O role split never "
                     f"examined)" if unreached else
                     " (all of them were examined by the role split and lost "
                     "downstream of it, e.g. to the single clock-port slot)"),
                  file=sys.stderr)
        if unresolved or not live_clocks or (unreached and _assert_coverage):
            reasons = []
            if unresolved:
                reasons.append(
                    f"{len(unresolved)} SDC port(s) do not exist on top "
                    f"'{top}': {unresolved}")
            if not live_clocks:
                reasons.append(
                    f"no create_clock landed on a real port of top '{top}' "
                    f"(clock target(s)={clock_refs or ['<none>']}); STA would "
                    f"run with NO clock in effect")
            if unreached and _assert_coverage:
                _covered_n = len(top_ports) - len(uncovered)
                reasons.append(
                    f"the I/O role split covered {_covered_n} of the "
                    f"{len(top_ports)} port(s) top '{top}' declares and never "
                    f"examined {len(unreached)} of them, which carry no "
                    f"constraint of any kind: {unreached}")
            # Keep the existing label verbatim for the existing two verdicts;
            # under-coverage is a different defect and gets its own name.
            _label = ("vacuous SDC" if (unresolved or not live_clocks)
                      else "under-constrained boundary surface")
            print(f"FAIL sdc_gen: {_label} — " + "; ".join(reasons)
                  + f"  (top interface: {sorted(top_ports)})", file=sys.stderr)
            return 1

    print(f"PASS sdc_gen: {out} "
          f"(clock={clock_port}@{clock_mhz}MHz period={period_ns:.2f}ns; "
          f"{len(inputs)} in / {len(outputs)} out / "
          f"{len(async_ports)} false_path / "
          f"{len(gen_clocks)} generated_clock"
          + (f"; dropped {len(dropped_pins)} L9 pin(s) absent from "
             f"synthesizable RTL surface: {sorted(dropped_pins)} (#619)"
             if dropped_pins else "")
          + (f"; constrained {len(residue_pins)} top-surface port(s) the L9 "
             f"pin list did not cover: {sorted(residue_pins)}"
             if residue_pins else "")
          # DISCLOSE THE DENOMINATOR OF THE COVERAGE ASSERTION — including
          # when it did not run. A PASS with no top interface to compare
          # against says NOT ASSERTED, so "no gap reported" cannot be read
          # as "no gap".
          + _cov_note
          + ")")
    # AN SDC THAT CONSTRAINS NO I/O PATH IS NOT A CONSTRAINED DESIGN (#744).
    #
    # The file is still emitted — a layer that declares no ports is the design's
    # problem, not this generator's, and refusing to write would strand the
    # flow. But emitting it SILENTLY makes "constrained" and "constrained
    # nothing" the same observable, which is the shape this whole batch is
    # about. #744 shipped a test asserting this diagnostic and no code that
    # prints it; the test was right and the gap was real.
    if not inputs and not outputs:
        print(f"NOTE sdc_gen: {out} constrains NO input or output path — the "
              f"clock is constrained and every data path is unconstrained. "
              f"L9 declared no ports and none were recovered from the RTL "
              f"surface.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
