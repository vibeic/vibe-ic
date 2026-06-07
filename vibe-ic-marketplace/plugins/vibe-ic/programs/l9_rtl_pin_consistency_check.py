#!/usr/bin/env python3
"""l9_rtl_pin_consistency_check.py — Wave 79 cross-layer integrity gate.

Verifies that the L9 integration spec's `top_level_ports[]` and the
RTL top-module port list agree on:

  - Pin-set membership (every L9 pin appears in RTL top, and vice versa).
  - Direction (`input` / `output` / `inout`) matches per pin.

Why this gate exists
====================
Wave 47-49 fresh-agent runs repeatedly produced an L9 declaring N
top-level pins, then generated RTL whose top module either dropped a
pin (e.g., `bor_trip` declared in L9 but missing from the top module)
or had its direction mismatched (e.g., `id_bus_tx_en` declared `output`
in L9 but `inout` in RTL because the agent chose to merge tristate).

Mid-flow consequences:
  - QSF/SDC generators (`aid_class_qsf_gen` / `aid_class_sdc_gen`) read
    L9 and emit pin assignments for pins that don't exist in synth →
    Quartus warns, agent ignores, hardware silently floats.
  - Reverse case: an RTL port not in L9 means no pin assignment → the
    pin gets defaulted to a random FPGA pin → demonstrably random
    bench failures.

This gate runs ONLY when both L9 + RTL are present. It SKIPs cleanly
when either is missing — that's a different gate's job (e.g. L9
presence is checked by L9_INTEGRATION_SPEC presence gates; RTL
existence is checked by Phase 2 structural gates).

Open-drain handling
===================
When L9 marks a pin `open_drain: true`, this gate does NOT inspect
the QSF/SDC; that contract is owned by `aid_class_qsf_gen.py`. We
only verify the L9 schema field is well-formed (boolean) so the
downstream generator has the data it needs.

Detection (chip-AGNOSTIC)
=========================
1. Find L9_*.json under <project>/generated_docs/. SKIP when none.
2. Extract top_level_ports[] (also accept legacy keys
   `top_module_pins`, `dtop_top_level.ports`).
3. Find the RTL top module file under phase2/stage1/rtl/. Heuristics
   (in order, first match wins):
     - L9.top_module / L9.top / L9.dtop  (schema v2 canonical)
     - L9.dtop_top_level.module_name (schema v1)
     - L9.dtop_module_name (schema v1)
     - <ic_name>_dtop.sv / <ic_name>.sv (best-effort name guess)
     - content scan: any rtl/*.sv|.v containing `module <top>`
   SKIP when no rtl file matches.
4. Parse the RTL top module's port list (via the same regex
   `extract_top_ports` style as `fpga_top_pin_completeness_check.py`,
   but capturing direction tokens too).
5. Cross-check membership both ways + direction agreement.

Honors waiver `l9_rtl_pin_consistency_intentional` (≥40 chars).

Exit codes
==========
0  — PASS / SKIP / PASS_WITH_WAIVER
1  — FAIL
2  — usage error
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Optional
import _path_layout as _pl

WAIVER_KEY = "l9_rtl_pin_consistency_intentional"
WAIVER_MIN_LEN = 40

_DIR_NORMALIZE = {
    "input": "input",
    "in": "input",
    "i": "input",
    "output": "output",
    "out": "output",
    "o": "output",
    "inout": "inout",
    "io": "inout",
    "bidir": "inout",
}


# Wave 82 Fix G — debug / scan / testbench-only port allowlist.
# When a port name matches one of these patterns, the port is treated
# as RTL-only (it is a debug or test hook that legitimately should NOT
# appear in the L9 production pin contract). Any port NOT matching one
# of these patterns must still appear in L9, otherwise it is a real
# pin-set discrepancy.
_DEBUG_PORT_PATTERNS = tuple(
    re.compile(p, re.IGNORECASE) for p in [
        r"^debug_",
        r"_debug$",
        r"_dbg_",
        r"_dbg$",
        r"^dbg_",
        r"^scan_",
        r"_scan$",
        r"^tb_",
        r"_tb$",
        r"^test_",
        r"^observation_",
        r"^probe_",
    ]
)


def _is_debug_port(name: str) -> bool:
    """Return True when the port name matches a debug/scan/tb-only
    naming pattern and may legitimately be omitted from L9."""
    return any(p.search(name) for p in _DEBUG_PORT_PATTERNS)


# v1.6.85 (#17 Bug B) — implicit pins that every chip carries by
# convention but L9 frequently doesn't enumerate (because they're
# obvious / always-required infrastructure ports). Whitelisting them
# from BOTH sides of the diff prevents false-FAIL when L9 omits clk
# / reset_n while RTL declares them, or vice-versa. Chip-AGNOSTIC.
#
# ORGANIC-20260606 #491 (b) — widened from an EXACT-name set to a
# NAME-PATTERN set. The exact set `{"clk", "reset_n"}` only stripped
# those two literal spellings, so when L9 carries `i_clk`/`rst_n` but
# the RTL emitter (or the AID-class canonical-pin augment) declares the
# OTHER conventional spelling (`clk`/`reset`), the asymmetric pair
# survived the strip and produced a false "RTL has ports not in L9" /
# "L9 declares pins missing from RTL" FAIL. The pattern set now covers
# the common infra-port spellings on BOTH the clock and reset families:
#
#   clock:  clk, i_clk, o_clk, clk_i, clock, sys_clk, core_clk, …
#           (a `clk`/`clock` segment, with an optional i_/o_ direction
#            prefix, an optional `_i`/`_o` suffix, and optional descriptive
#            qualifier segments — `sys_clk`, `core_clk`, `clk_i`)
#   reset:  rst, i_rst, rst_n, reset, reset_n, i_reset_n, por_rst_n, …
#           (a `rst`/`reset`/`por` segment, optional i_/o_ prefix,
#            optional active-low `_n`/`n` suffix, optional qualifiers)
#
# GPIO is DELIBERATELY NOT whitelisted here — per the issue, GPIO must
# come from the L3 pin table (the promoter already extracts every
# direction-bearing table row, verified end-to-end), not from a gate-side
# convenience whitelist that would mask a genuinely-dropped GPIO pin.
# Chip-AGNOSTIC: pure naming-convention SHAPE; no chip/vendor literal.
_IMPLICIT_PIN_PATTERNS = tuple(
    re.compile(p, re.IGNORECASE) for p in [
        # clock family: optional i_/o_ prefix, a clk/clock segment
        # (optionally qualified, e.g. sys_clk / core_clk), optional
        # _i/_o direction suffix, optional trailing digits.
        r"^(?:[io]_)?(?:[a-z][a-z0-9]*_)*"
        r"(?:clk|clock)(?:_[io])?\d*$",
        # reset family: optional i_/o_ prefix, a rst/reset/por segment
        # (optionally qualified, e.g. por_rst / soft_reset), optional
        # active-low _n / n suffix, optional _i/_o direction suffix.
        r"^(?:[io]_)?(?:[a-z][a-z0-9]*_)*"
        r"(?:rst|reset|por)(?:_?n)?(?:_[io])?\d*$",
    ]
)


def _is_implicit_pin(name: str) -> bool:
    """ORGANIC #491 (b) — True iff `name` matches a conventional
    implicit infra-port (clock / reset) spelling that L9 frequently
    does not enumerate. Pattern-on-SHAPE, chip-AGNOSTIC."""
    if not isinstance(name, str) or not name:
        return False
    return any(p.match(name) for p in _IMPLICIT_PIN_PATTERNS)


# ─── L9 ingestion ─────────────────────────────────────────────────
def find_l9(project: Path) -> Optional[Path]:
    gd = _pl.generated_docs_dir(project)
    if not gd.is_dir():
        return None
    for p in sorted(gd.glob("L9_*.json")):
        return p
    return None


def _normalise_dir(raw: str) -> Optional[str]:
    if not isinstance(raw, str):
        return None
    return _DIR_NORMALIZE.get(raw.lower().strip())


# ORGANIC-20260606 #490 — L9 port-key fragmentation. The L9 schema has
# accreted THREE port-list keys over its history:
#   - `top_ports`        — the CANONICAL key the promoter writes (also
#                          read by the RTL emitter, the SDC/QSF/clock
#                          generators, and most post-emit hooks);
#   - `ports`            — the alias gen_l9 emits alongside `top_ports`;
#   - `top_level_ports`  — the original Wave-79 schema-v1 key this gate
#                          was first written against;
#   - `top_module_pins`  — the legacy compat name;
#   - `dtop_top_level.ports` — schema-v1 nested form.
# `full_stack_tb_gen` + the L9 promoter populate `top_ports`, but this
# gate historically read ONLY `top_level_ports` / `top_module_pins` /
# `dtop_top_level.ports`. A correct RTL top therefore got NO verification
# (silent SKIP) when the promoted port set landed in `top_ports`/`ports`
# — and a field run had to write the same pins into BOTH keys to clear
# the gate. Fix: read the UNION of every known key (deduped by name, so
# the dual-write that field runs used is harmless and the order-of-
# precedence between aliases no longer matters). The promoter side
# (gen_l9_integration_spec) writes the canonical `top_ports` AND mirrors
# into whatever legacy keys it finds populated, so no consumer is
# orphaned regardless of which key it reads.
_L9_PORT_KEYS = (
    "top_ports",          # canonical (promoter + TB-gen + emitters)
    "ports",              # promoter alias
    "top_level_ports",    # original Wave-79 schema-v1 key
    "top_module_pins",    # legacy compat alias
)


def extract_l9_ports(l9: dict) -> list[dict]:
    """Return [{name, direction, open_drain}] from the UNION of every
    accepted L9 schema port-key variant (#490).

    The union is deduped by name (first occurrence wins, but a later
    occurrence that carries a direction backfills a missing one) so a
    dual-written L9 (the same pins under both `top_ports` and
    `top_module_pins`) yields the same single port set as a singly-keyed
    L9. This is what makes the gate read ports that landed in ANY one
    key without requiring producers to mirror into every key."""
    raw_lists: list[list] = []
    for key in _L9_PORT_KEYS:
        v = l9.get(key)
        if isinstance(v, list):
            raw_lists.append(v)
    dtop = l9.get("dtop_top_level", {})
    if isinstance(dtop, dict) and isinstance(dtop.get("ports"), list):
        raw_lists.append(dtop["ports"])
    out: list[dict] = []
    by_name: dict[str, dict] = {}
    for lst in raw_lists:
        for entry in lst:
            if not isinstance(entry, dict):
                continue
            name = entry.get("name") or entry.get("port") or entry.get("pin")
            direction = (
                entry.get("direction")
                or entry.get("dir")
                or entry.get("io")
            )
            if not name:
                continue
            name = str(name)
            d = _normalise_dir(direction) if direction else None
            prev = by_name.get(name)
            if prev is None:
                rec = {
                    "name": name,
                    "direction": d,
                    "open_drain": bool(entry.get("open_drain", False)),
                }
                by_name[name] = rec
                out.append(rec)
            else:
                # Same pin under another key: backfill a missing
                # direction / open_drain so a dual-write where only one
                # copy carries the direction still yields it.
                if prev.get("direction") is None and d is not None:
                    prev["direction"] = d
                if entry.get("open_drain"):
                    prev["open_drain"] = True
    return out


# ─── RTL top extraction ────────────────────────────────────────────
def find_rtl_top(project: Path, l9: dict) -> Optional[Path]:
    rtl = _pl.rtl_dir(project)
    if not rtl.is_dir():
        return None
    candidates: list[str] = []
    # Schema v2 canonical field — added v1.6.19. Honoured before legacy
    # dtop_* keys so v2 projects (which carry top_module="chip_top" but
    # no dtop_module_name) stop being silently SKIPped by this gate.
    top_v2 = l9.get("top_module") or l9.get("top") or l9.get("dtop")
    if isinstance(top_v2, str) and top_v2:
        candidates.extend([f"{top_v2}.sv", f"{top_v2}.v"])
    dtop = l9.get("dtop_top_level", {})
    if isinstance(dtop, dict):
        m = dtop.get("module_name")
        if isinstance(m, str) and m:
            candidates.extend([f"{m}.sv", f"{m}.v"])
    m = l9.get("dtop_module_name")
    if isinstance(m, str) and m:
        candidates.extend([f"{m}.sv", f"{m}.v"])
    ic = l9.get("ic_name")
    if isinstance(ic, str) and ic:
        ic_l = ic.lower()
        candidates.extend(
            [f"{ic_l}_dtop.sv", f"{ic_l}_dtop.v",
             f"{ic_l}.sv", f"{ic_l}.v"]
        )
    # v1.6.84 (#16 Bug B): fallback to AID-class canonical 'chip_top'
    # when L9.top_module is null/empty. Without this, a project with a
    # null L9.top_module silently SKIPs even though the deterministic
    # generator emitted rtl/chip_top.sv — a silent quality loss.
    candidates.extend(["chip_top.sv", "chip_top.v"])

    for c in candidates:
        p = rtl / c
        if p.is_file():
            return p
    # Content-scan (v1.6.19+): when schema v2 declares
    # top_module="X" but the file isn't named "X.sv", grep every
    # rtl/*.sv|.v for `module X` and return the first match. Catches
    # projects where the top is bundled inside a multi-module file.
    if isinstance(top_v2, str) and top_v2:
        pat = re.compile(rf"\bmodule\s+{re.escape(top_v2)}\b")
        for p in sorted(rtl.glob("*.sv")) + sorted(rtl.glob("*.v")):
            try:
                if pat.search(p.read_text(encoding="utf-8", errors="replace")):
                    return p
            except OSError:
                continue
    return None


def _strip_comments(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)
    src = re.sub(r"//[^\n]*", "", src)
    return src


def _strip_param_block(src: str) -> str:
    """Remove the optional `#( ... )` parameter port list that follows a
    `module <name>` header, using a balanced-paren depth counter so a
    parameter default containing a function call (e.g.
    `parameter aw = $clog2(memsize)`) — or arbitrarily nested calls —
    does NOT terminate the strip at an INNER `)`.

    Without this, the old `#\\s*\\([^)]*\\)` regex closed the parameter
    block at the first inner `)` of `$clog2(memsize)`, leaving the real
    port list unmatched and parse_rtl_top_ports returning zero ports
    (GitHub #474). The scanner walks every `module <name>` occurrence and
    splices out only the matched `#(...)` span, preserving the rest of
    the text (including the port-list parens) verbatim.
    """
    out: list[str] = []
    pos = 0
    # Iterate header-by-header: `module <name>` then optional whitespace.
    for hm in re.finditer(r"\bmodule\s+\w+\s*", src):
        # Emit everything up to and including the header we just matched.
        out.append(src[pos:hm.end()])
        pos = hm.end()
        # A parameter block must begin with `#` then `(` (whitespace ok).
        pm = re.match(r"#\s*\(", src[pos:])
        if not pm:
            continue
        # Walk from the opening paren with a depth counter.
        i = pos + pm.end() - 1   # index of the `(` itself
        depth = 0
        end = None
        while i < len(src):
            ch = src[i]
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
            i += 1
        if end is None:
            # Unbalanced — bail out without stripping; leave text as-is so
            # the downstream regex can still try (and fail loudly).
            continue
        # Skip the entire `#(...)` span (replace with a single space so
        # tokens on either side don't accidentally merge).
        out.append(" ")
        pos = end
    out.append(src[pos:])
    return "".join(out)


def parse_rtl_top_ports(rtl_path: Path) -> list[dict]:
    """Parse `module <name>(...);` and emit [{name, direction}].

    Supports the SystemVerilog `module foo import pkg::*;
    (input wire clk, output id_tx_en, inout id_bus, ...)` shape.
    """
    text = _strip_comments(rtl_path.read_text(errors="ignore"))
    # Strip the optional `#( ... )` parameter block with a balanced-paren
    # scanner BEFORE the port-list regex runs, so function-call defaults
    # like `$clog2(memsize)` (and nested calls) can't truncate the match
    # at an inner `)` and yield zero ports (#474).
    text = _strip_param_block(text)
    m = re.search(
        r"module\s+\w+\s*"
        r"(?:import\s+[\w:\*\s,]+;\s*)*"  # SV imports
        r"\(([^;]+?)\)\s*;",
        text,
        flags=re.DOTALL,
    )
    if not m:
        return []
    body = m.group(1)
    out: list[dict] = []
    cur_dir: Optional[str] = None
    for line in body.split(","):
        toks = line.split()
        if not toks:
            continue
        # Detect direction token; carry forward when omitted (Verilog
        # `input a, b, c` shape).
        if toks[0].lower() in _DIR_NORMALIZE:
            cur_dir = _DIR_NORMALIZE[toks[0].lower()]
            toks = toks[1:]
        # Drop type / width tokens; the LAST token is the port name.
        if not toks:
            continue
        name = toks[-1].strip("[]()")
        # Skip pure type-only tokens (rare).
        if not re.match(r"^[A-Za-z_]\w*$", name):
            continue
        out.append({"name": name, "direction": cur_dir})
    return out


# ─── waiver ────────────────────────────────────────────────────────
def waived(project: Path) -> tuple[bool, str]:
    waivers = project / "waivers.json"
    if not waivers.is_file():
        return False, ""
    try:
        d = json.loads(waivers.read_text())
    except Exception:
        return False, ""
    raw = d.get(WAIVER_KEY)
    if not isinstance(raw, dict):
        return False, ""
    rationale = raw.get("rationale") or raw.get("reason") or ""
    if isinstance(rationale, str) and \
       len(rationale.strip()) >= WAIVER_MIN_LEN:
        return True, rationale.strip()
    return False, ""


# ─── main ─────────────────────────────────────────────────────────
def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("Usage: l9_rtl_pin_consistency_check.py <project_dir>")
        return 2
    project = Path(argv[1]).resolve()
    if not project.is_dir():
        print(f"FAIL — project dir not found: {project}")
        return 1

    l9_path = find_l9(project)
    if l9_path is None:
        print("SKIP — no L9 doc")
        return 0
    try:
        l9 = json.loads(l9_path.read_text())
    except Exception as e:
        print(f"FAIL — cannot parse L9 ({l9_path.name}): {e}")
        return 1

    l9_ports = extract_l9_ports(l9)
    if not l9_ports:
        print(
            "SKIP — L9 declares no top_level_ports[] / top_module_pins[]"
        )
        return 0

    rtl_top = find_rtl_top(project, l9)
    if rtl_top is None:
        print(
            "SKIP — no RTL top file (gate active only when both L9 and "
            "RTL exist)"
        )
        return 0

    rtl_ports = parse_rtl_top_ports(rtl_top)
    if not rtl_ports:
        print(
            f"FAIL — RTL top {rtl_top.name} parsed zero ports — "
            f"either the module declaration is malformed or the regex "
            f"failed; investigate."
        )
        return 1

    l9_names = {p["name"] for p in l9_ports}
    rtl_names = {p["name"] for p in rtl_ports}

    # v1.6.85 (#17 Bug B) — strip implicit pins (clk / reset family) from
    # BOTH sides of the diff before comparing. They're always required
    # but L9 sometimes doesn't enumerate them (relying on the
    # canonical-fallback in aid_class_rtl_gen). Without this, every
    # such project hits a false-FAIL "L9 declares pins missing from
    # RTL".
    # ORGANIC-20260606 #491 (b) — the strip now matches a NAME-PATTERN
    # (clk/i_clk/clock/clk_i + rst/rst_n/reset/reset_n/por…) so an
    # asymmetric spelling pair (L9=`i_clk`, RTL=`clk`) no longer survives
    # the strip and false-FAILs.
    l9_names = {n for n in l9_names if not _is_implicit_pin(n)}
    rtl_names = {n for n in rtl_names if not _is_implicit_pin(n)}

    only_l9 = sorted(l9_names - rtl_names)
    only_rtl_all = sorted(rtl_names - l9_names)

    # Wave 82 Fix G — split RTL-only ports into debug-allowed vs real.
    # debug_*/scan_*/tb_*/_dbg* / probe_* / etc. are test hooks that
    # legitimately do NOT belong in the L9 production pin contract.
    only_rtl_debug = [n for n in only_rtl_all if _is_debug_port(n)]
    only_rtl = [n for n in only_rtl_all if not _is_debug_port(n)]

    # Direction-mismatch list (only for pins in BOTH).
    dir_mismatch: list[str] = []
    rtl_dir_map = {p["name"]: p["direction"] for p in rtl_ports}
    for p in l9_ports:
        if p["name"] not in rtl_names:
            continue
        l9d = p["direction"]
        rtld = rtl_dir_map.get(p["name"])
        if l9d and rtld and l9d != rtld:
            dir_mismatch.append(
                f"{p['name']}: L9={l9d} vs RTL={rtld}"
            )

    findings: list[str] = []
    if only_l9:
        findings.append(
            f"L9 declares pins missing from RTL top "
            f"({rtl_top.name}): {only_l9}"
        )
    if only_rtl:
        findings.append(
            f"RTL top ({rtl_top.name}) has ports not in L9: {only_rtl}"
        )
    if dir_mismatch:
        findings.append(
            f"direction mismatches: {dir_mismatch}"
        )

    if not findings:
        msg = (
            f"PASS — L9 ↔ RTL top ({rtl_top.name}) pin set + "
            f"direction agree on {len(l9_names)} pins"
        )
        if only_rtl_debug:
            msg += (
                f" (RTL has {len(only_rtl_all)} extra port(s); "
                f"{len(only_rtl_debug)} are debug/scan/tb-only and "
                f"ignored: {only_rtl_debug})"
            )
        print(msg)
        return 0

    is_waived, rationale = waived(project)
    if is_waived:
        print(
            f"PASS_WITH_WAIVER — {len(findings)} finding(s) waived: "
            f"{rationale[:80]}"
        )
        for f in findings:
            print(f"  · {f}")
        return 0

    print(
        f"FAIL — L9 ↔ RTL top pin/direction mismatch "
        f"({rtl_top.name}): {len(findings)} finding(s)"
    )
    for f in findings:
        print(f"  · {f}")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
