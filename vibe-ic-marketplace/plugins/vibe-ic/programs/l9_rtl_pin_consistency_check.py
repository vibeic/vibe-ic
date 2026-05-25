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
_IMPLICIT_PINS = frozenset({"clk", "reset_n"})


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


def extract_l9_ports(l9: dict) -> list[dict]:
    """Return [{name, direction, open_drain}] from any of the
    accepted L9 schema variants."""
    raw_lists = []
    if isinstance(l9.get("top_level_ports"), list):
        raw_lists.append(l9["top_level_ports"])
    if isinstance(l9.get("top_module_pins"), list):
        raw_lists.append(l9["top_module_pins"])
    dtop = l9.get("dtop_top_level", {})
    if isinstance(dtop, dict) and isinstance(dtop.get("ports"), list):
        raw_lists.append(dtop["ports"])
    out: list[dict] = []
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
            d = _normalise_dir(direction) if direction else None
            out.append(
                {
                    "name": str(name),
                    "direction": d,
                    "open_drain": bool(entry.get("open_drain", False)),
                }
            )
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


def parse_rtl_top_ports(rtl_path: Path) -> list[dict]:
    """Parse `module <name>(...);` and emit [{name, direction}].

    Supports the SystemVerilog `module foo import pkg::*;
    (input wire clk, output id_tx_en, inout id_bus, ...)` shape.
    """
    text = _strip_comments(rtl_path.read_text(errors="ignore"))
    m = re.search(
        r"module\s+\w+\s*"
        r"(?:#\s*\([^)]*\)\s*)?"          # optional parameter port list
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

    # v1.6.85 (#17 Bug B) — strip implicit pins (clk / reset_n) from
    # BOTH sides of the diff before comparing. They're always required
    # but L9 sometimes doesn't enumerate them (relying on the
    # canonical-fallback in aid_class_rtl_gen). Without this, every
    # such project hits a false-FAIL "L9 declares pins missing from
    # RTL".
    l9_names = {n for n in l9_names if n not in _IMPLICIT_PINS}
    rtl_names = {n for n in rtl_names if n not in _IMPLICIT_PINS}

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
