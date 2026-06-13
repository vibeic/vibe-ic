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
    1  FAIL (missing L8 / L9)
    2  IO / arg error
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import _path_layout as _pl
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
    ``phase2_one_shot_runner.detect_ic_class`` (e.g.
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


def _parse_module_ports(txt: str) -> List[Tuple[str, str, int]]:
    """Returns list of (name, dir, width) from a module's port list."""
    if "module " not in txt:
        return []
    after = txt.split("module ", 1)[1]
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


# ---------------------------------------------------------------------------
# Port classification
# ---------------------------------------------------------------------------
def _is_clock(name: str) -> bool:
    n = name.lower()
    return ("clk" in n) or ("clock" in n)


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
                gen_clocks: Optional[List[Tuple[str, str]]] = None) -> str:
    period_str = f"{period_ns:.3f}".rstrip("0").rstrip(".") or "20"
    lines: List[str] = []
    lines.append("# =========================================================================")
    lines.append("# Auto-generated by sdc_gen.py (Wave 72/73)")
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

    # Decide port set: prefer wrapper ports (board namespace) when wrapper
    # is the top entity, else fall back to L9.top_module_pins.
    inputs: List[str] = []
    outputs: List[str] = []
    async_ports: List[str] = []
    clock_port: Optional[str] = None
    dropped_pins: List[str] = []
    rtl_ports: set = set()  # union of synthesizable RTL ports (#619)

    if wrapper and top == wrapper[0]:
        ports = _parse_module_ports(wrapper[1])
        for name, direction, width in ports:
            sigs = ([name] if width == 1
                    else [f"{name}[{i}]" for i in range(width)])
            if _is_clock(name):
                clock_port = name if width == 1 else f"{name}[0]"
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
        rtl_ports = _collect_all_module_ports(rtl_files)  # union; may be empty
        for port in l9.get("top_module_pins", []):
            if not isinstance(port, dict):
                continue
            name = port.get("name", "")
            if rtl_ports and name and name not in rtl_ports:
                dropped_pins.append(name)
                continue
            mode = (port.get("mode") or "").lower()
            if _is_clock(name):
                clock_port = name
                continue
            if _is_reset(name) or "inout" in mode or _is_async_io(name):
                async_ports.append(name)
                continue
            if mode == "output":
                outputs.append(name)
            else:
                inputs.append(name)

    if not clock_port:
        # Fallback: take first 'clk*' from L9 that EXISTS on the synthesizable
        # surface (#619), else 'clk'.
        clock_port = "clk"
        for port in l9.get("top_module_pins", []):
            if not (isinstance(port, dict) and _is_clock(port.get("name", ""))):
                continue
            cand = port["name"]
            if rtl_ports and cand not in rtl_ports:
                continue  # #619: don't bind a clock absent from the RTL surface
            clock_port = cand
            break

    fpga_dir = _pl.fpga_early_dir(project)
    fpga_dir.mkdir(parents=True, exist_ok=True)
    out = fpga_dir / f"{top}.sdc"
    if out.exists() and not args.force:
        print(f"SKIP: {out} exists (use --force to overwrite)")
        return 0

    gen_clocks = _find_register_divided_clocks(rtl_files)
    text = _render_sdc(top, clock_port, period_ns, inputs, outputs,
                       async_ports, gen_clocks)
    out.write_text(text, encoding="utf-8")
    print(f"PASS sdc_gen: {out} "
          f"(clock={clock_port}@{clock_mhz}MHz period={period_ns:.2f}ns; "
          f"{len(inputs)} in / {len(outputs)} out / "
          f"{len(async_ports)} false_path / "
          f"{len(gen_clocks)} generated_clock"
          + (f"; dropped {len(dropped_pins)} L9 pin(s) absent from "
             f"synthesizable RTL surface: {sorted(dropped_pins)} (#619)"
             if dropped_pins else "")
          + ")")
    return 0


if __name__ == "__main__":
    sys.exit(main())
