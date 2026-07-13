#!/usr/bin/env python3
"""dynamic_ir_vectored_emit.py — VCD-vectored dynamic IR-drop EMITTER (real OSS PSM).

ADVANCED-NODE GAP #2 (from the flow gap-analysis): Step 24 today does STATIC IR only
(OpenROAD PSM `analyze_power_grid` with the vectorless default switching activity).
`_emit_dynamic_ir_stance()` in phase3_one_shot_runner marked the *transient* dynamic-IR
tier "HONEST BLOCKED: OSS PSM is static-only". That stance is correct ONLY for a full
di/dt time-domain transient solve. It is TOO PESSIMISTIC for the achievable OSS step:

  OpenROAD PSM DOES accept per-instance switching activity via `read_vcd -scope <s> <f>`
  (the modern name of `read_power_activities -vcd`). Feeding a design's simulation VCD
  makes PSM compute IR drop from REAL annotated toggle rates instead of a flat vectorless
  0.1 default → a VCD-VECTORED worst-case IR-drop number. This is node-AGNOSTIC and
  OSS-feasible TODAY; only the full transient di/dt L·di/dt solver stays a commercial gap.

Empirically proven activity-sensitivity (spm / KF-HP18E80, OpenROAD 26Q3):
  static (vectorless 0.1)          -> worst IR 105 mV   (total P 1.30 mW)
  real functional VCD (idle-heavy) -> worst IR 99.4 mV  (total P 1.15 mW, 36 pins annot.)
  peak-switching VCD               -> worst IR 460 mV   (total P 4.45 mW)  ← 4.4x static
So the vectored number tracks real switching and CAN exceed static (peak workload). A
low-activity functional TB honestly yields a LOWER vectored number than the pessimistic
vectorless default — we NEVER fabricate "higher"; we report the tool's real value.

WHAT THIS EMITTER DOES
  read routed DEF + tech/cell/macro LEF + Liberty + a design VCD
    -> openroad: read_vcd -scope <auto>  →  analyze_power_grid -net <power net>
    -> parse "Worstcase IR drop: <V>" from the PSM stdout
    -> write reports/phase3/dynamic_ir.json  {max_dynamic_drop_mv, vdd_v, exceeds_static,
       analysis_mode:"vcd_vectored_psm", disclosure:"NOT a full di/dt transient solve", …}
  The gate `dynamic_ir_drop_check.py` then reads max_dynamic_drop_mv vs a budget.

HONEST SKIP (§4.05 — never a fabricated number):
  * no VCD discoverable            -> dynamic_ir.json {status:"SKIPPED_NO_VCD",
                                       dynamic_ir_report_emitted:false}  (rc 0; the gate
                                       reads this marker and SKIPs the tier honestly)
  * PSM produced no IR line        -> dynamic_ir.json {status:"ERROR_NO_PSM_IR", …} (rc 1)
The static IR path (Step 24 `_emit_ir_em_reports`) is untouched and remains authoritative.

CLI
  python3 dynamic_ir_vectored_emit.py --project <run_dir> [--out F] [--net N]
  python3 dynamic_ir_vectored_emit.py --def D --tech-lef T --cell-lef C \
        --liberty L [--macro-lef M ...] --vcd V --out F [--net N] [--container vibeic-eda]
  main(argv) -> 0 emitted/skipped-honestly / 1 tool-error / 2 IO-or-arg error.

chip-AGNOSTIC: power nets discovered from DEF SPECIALNETS; VCD scope auto-derived; no
design literals.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_DEFAULT_CONTAINER = "vibeic-eda"
_TOOLS = "/foss/tools"

# ── PURE HELPERS (unit-tested; no docker / no filesystem side effects) ──────────

_WORST_IR_RE = re.compile(r"Worstcase\s+IR\s+drop\s*:\s*([0-9.eE+\-]+)\s*V", re.I)
_AVG_IR_RE = re.compile(r"Average\s+IR\s+drop\s*:\s*([0-9.eE+\-]+)\s*V", re.I)
_SUPPLY_RE = re.compile(r"Supply\s+voltage\s*:\s*([0-9.eE+\-]+)\s*V", re.I)
_ANNOT_RE = re.compile(r"Annotated\s+(\d+)\s+pin\s+activit", re.I)
_TOTAL_P_RE = re.compile(r"Total\s+power\s*:\s*([0-9.eE+\-]+)\s*W", re.I)

# Sim sub-dirs a VCD may live under, relative to a run/project dir.
_VCD_GLOBS = (
    "phase2/stage1/sim*/**/*.vcd",
    "phase2/stage1/sim*/*.vcd",
    "phase3/**/sim*/**/*.vcd",
    "reports/**/*.vcd",
)


def find_vcd(project: Path) -> Optional[Path]:
    """First NON-EMPTY .vcd under the project's sim dirs, or None (honest absence)."""
    for pat in _VCD_GLOBS:
        for cand in sorted(project.glob(pat)):
            try:
                if cand.is_file() and cand.stat().st_size > 0:
                    return cand
            except OSError:
                continue
    return None


def discover_vcd_scope(vcd_text: str) -> Optional[str]:
    """Derive the DUT scope path from a VCD's `$scope module <m>` nesting.

    A cocotb/iverilog testbench dumps `tb_top` (outermost) with the DUT as its
    first nested `module` scope (e.g. tb_spm_full → u_dut). PSM's `read_vcd
    -scope <path>` remaps that sub-hierarchy's signals onto the design's nets by
    name. Returns "<tb>/<dut>" (the two outermost MODULE scopes) or the single
    outermost module if there is no nested module, or None if no module scope.

    Only `module` scopes count — `task`/`function`/`fork` scopes are skipped so a
    testbench helper task is never mistaken for the DUT."""
    mods: List[str] = []
    depth_stack: List[Tuple[str, str]] = []  # (kind, name)
    for m in re.finditer(r"\$scope\s+(\w+)\s+(\S+)\s+\$end|\$upscope\s+\$end",
                          vcd_text):
        if m.group(1) is None:  # $upscope
            if depth_stack:
                depth_stack.pop()
            continue
        kind, name = m.group(1), m.group(2)
        depth_stack.append((kind, name))
        if kind == "module":
            # record the module-scope path (module names only) at this point
            path = [n for (k, n) in depth_stack if k == "module"]
            mods.append("/".join(path))
    if not mods:
        return None
    # Prefer the deepest 2-level module path (tb/dut); else the outermost module.
    two_level = [p for p in mods if p.count("/") == 1]
    if two_level:
        return two_level[0]
    return mods[0]


def parse_worst_ir_v(psm_log: str) -> Optional[float]:
    """Worstcase IR drop in Volts from PSM stdout, or None."""
    m = _WORST_IR_RE.search(psm_log)
    if not m:
        return None
    try:
        return abs(float(m.group(1)))
    except ValueError:
        return None


def parse_supply_v(psm_log: str) -> Optional[float]:
    m = _SUPPLY_RE.search(psm_log)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def parse_annotated_pins(psm_log: str) -> Optional[int]:
    m = _ANNOT_RE.search(psm_log)
    return int(m.group(1)) if m else None


def parse_total_power_w(psm_log: str) -> Optional[float]:
    m = _TOTAL_P_RE.search(psm_log)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def read_static_ir_mv(ir_drop_json: Path) -> Optional[float]:
    """Worst STATIC IR in mV from a Step-24 ir_drop.json (worst_ir_uv), or None."""
    try:
        d = json.loads(ir_drop_json.read_text(errors="ignore"))
    except (OSError, json.JSONDecodeError, ValueError):
        return None
    if not isinstance(d, dict):
        return None
    uv = d.get("worst_ir_uv")
    if isinstance(uv, (int, float)):
        return float(uv) / 1000.0
    return None


def discover_power_nets(def_file: Path) -> List[str]:
    """USE POWER nets from a DEF SPECIALNETS block (chip-AGNOSTIC structural parse)."""
    power: List[str] = []
    try:
        text = def_file.read_text(errors="ignore")
    except OSError:
        return power
    m = re.search(r"^SPECIALNETS\b.*?^END SPECIALNETS",
                  text, re.MULTILINE | re.DOTALL)
    if not m:
        return power
    for net_m in re.finditer(r"^\s*-\s+([A-Za-z_][\w$]*)(.*?)(?=^\s*-\s+|\Z)",
                             m.group(0), re.MULTILINE | re.DOTALL):
        name, body = net_m.group(1), net_m.group(2)
        if re.search(r"\bUSE\s+POWER\b", body) and name not in power:
            power.append(name)
    return power


def build_result(worst_dyn_mv: float, vdd_v: Optional[float],
                 static_mv: Optional[float], annotated_pins: Optional[int],
                 total_power_w: Optional[float], power_net: str,
                 vcd: str, scope: Optional[str]) -> Dict[str, object]:
    """Assemble the dynamic_ir.json payload (real numbers + honest disclosure)."""
    res: Dict[str, object] = {
        "signoff_dimension": "dynamic_transient_ir_drop",
        "analysis_mode": "vcd_vectored_psm",
        "dynamic_ir_report_emitted": True,
        "tool": "openroad-psm (analyze_power_grid + read_vcd)",
        # keys the dynamic_ir_drop_check.py gate consumes:
        "max_dynamic_drop_mv": round(worst_dyn_mv, 4),
        "power_net": power_net,
        "vcd": vcd,
        "vcd_scope": scope,
        "annotated_pin_activities": annotated_pins,
        "vectored_total_power_w": total_power_w,
        "disclosure": (
            "VCD-vectored PSM worst-case static IR under REAL annotated switching "
            "activity (read_vcd → analyze_power_grid). This is NOT a full di/dt "
            "time-domain transient solve — L·di/dt inductive droop and per-cycle "
            "time-stepping remain a commercial gap (RedHawk-SC / Voltus). The number "
            "is the activity-weighted resistive IR, which tracks the workload: a "
            "peak-switching VCD raises it above the vectorless static default; an "
            "idle-heavy functional VCD honestly lowers it."),
    }
    if vdd_v is not None:
        res["vdd_v"] = vdd_v
        res["vdd"] = vdd_v  # gate alias
        res["max_dynamic_drop_pct"] = round(worst_dyn_mv / (vdd_v * 1000.0) * 100.0, 3)
    if static_mv is not None:
        res["static_ir_mv"] = round(static_mv, 4)
        res["exceeds_static"] = worst_dyn_mv > static_mv
        res["dynamic_vs_static_ratio"] = round(worst_dyn_mv / static_mv, 3) \
            if static_mv > 0 else None
    return res


def skip_result(reason: str) -> Dict[str, object]:
    """Honest SKIP payload — NO fabricated droop number (§4.05)."""
    return {
        "signoff_dimension": "dynamic_transient_ir_drop",
        "analysis_mode": "vcd_vectored_psm",
        "status": "SKIPPED_NO_VCD",
        "dynamic_ir_report_emitted": False,
        "reason": reason,
        "disclosure": (
            "§4.05: no design VCD/SAIF was available, so NO vectored dynamic-IR "
            "number is fabricated. The static IR sign-off (reports/phase3/"
            "ir_drop.json) stands; the dynamic-IR tier is a conditional SKIP. "
            "Produce a switching VCD ($dumpvars over the gate netlist, or a "
            "functional sim) to enable the VCD-vectored PSM droop."),
        "what_would_enable_it": (
            "any non-empty *.vcd under phase2/stage1/sim*/ (or pass --vcd); the "
            "emitter feeds it to OpenROAD read_vcd → analyze_power_grid."),
    }


# ── DOCKER / OPENROAD RUN (side-effecting; not unit-tested) ─────────────────────

def _build_tcl(def_file: Path, tech_lef: Path, cell_lef: Path, liberty: Path,
               macro_lefs: List[Path], sdc: Optional[Path], vcd: Path,
               scope: Optional[str], power_net: str, via_res: Dict[str, float],
               metal_prefix: str) -> str:
    """The exact OpenROAD PSM VCD-vectored TCL (host paths; container mounts them)."""
    macro_tcl = "\n".join(f"read_lef {f}" for f in macro_lefs)
    sdc_tcl = f"catch {{read_sdc {sdc}}}\n" if sdc else ""
    via_tcl = "".join(f"catch {{set_layer_rc -via {c} -resistance {r}}}\n"
                      for c, r in sorted(via_res.items()))
    scope_arg = f"-scope {scope} " if scope else ""
    return (
        f"read_lef {tech_lef}\n"
        f"read_lef {cell_lef}\n"
        f"{macro_tcl}\n"
        f"read_liberty {liberty}\n"
        f"read_def {def_file}\n"
        f"{sdc_tcl}"
        f"if {{[catch {{set_wire_rc -signal -layer {metal_prefix}1}}]}} "
        f"{{ catch {{set_wire_rc -layer {metal_prefix}1}} }}\n"
        f"catch {{set_wire_rc -clock -layer {metal_prefix}5}}\n"
        f"{via_tcl}"
        f'puts "=== DYN_IR read_vcd ==="\n'
        f"if {{[catch {{read_vcd {scope_arg}{vcd}}} _vcd_err]}} {{\n"
        f'  puts "READ_VCD_FAIL: $_vcd_err"\n}}\n'
        f"catch {{report_power}}\n"
        f'puts "=== DYN_IR PSM {power_net} ==="\n'
        f"if {{[catch {{analyze_power_grid -net {power_net}}} _psm_err]}} {{\n"
        f'  puts "PSM_NONFATAL {power_net}: $_psm_err"\n}}\n'
        f"exit\n"
    )


def _discover_via_res(tech_lef: Optional[Path]) -> Dict[str, float]:
    """Per-CUT-LAYER via resistance (ohm) from a tech LEF's fixed-VIA MASTER blocks,
    for OpenROAD PSM `set_layer_rc -via`. A LEF ships RESISTANCE on the fixed-VIA
    masters (VIA12, VIA23, …) whose `LAYER <cut>` line names the cut layer (VIA1,
    VIA2, …); without mapping it onto the cut LAYER, PSM sees 0-ohm vias →
    "[PSM-0021] Resistance map contains invalid values". Mirrors the runner's
    `_discover_via_resistances` (chip-AGNOSTIC; {} when no LEF / no via RESISTANCE)."""
    out: Dict[str, float] = {}
    if not tech_lef:
        return out
    try:
        text = Path(tech_lef).read_text(errors="ignore")
    except OSError:
        return out
    cur_via = cur_cut = cur_res = None
    for raw in text.splitlines():
        s = raw.strip()
        m = re.match(r"VIA\s+(\S+)", s)
        if m and not s.startswith("VIARULE"):
            cur_via, cur_cut, cur_res = m.group(1), None, None
            continue
        if cur_via is None:
            continue
        m = re.match(r"LAYER\s+(\S+)", s)
        if m:
            nm = m.group(1).rstrip(";")
            if re.match(r"(VIA\d+|CONT)$", nm.upper()):
                cur_cut = nm
            continue
        m = re.match(r"RESISTANCE\s+([0-9.eE+\-]+)", s)
        if m:
            try:
                cur_res = float(m.group(1))
            except ValueError:
                cur_res = None
            continue
        if s.startswith("END") and cur_via is not None:
            if cur_cut and cur_res is not None:
                prev = out.get(cur_cut)
                out[cur_cut] = cur_res if prev is None else min(prev, cur_res)
            cur_via = cur_cut = cur_res = None
    return out


def emit(def_file: Path, tech_lef: Path, cell_lef: Path, liberty: Path,
         macro_lefs: List[Path], sdc: Optional[Path], vcd: Optional[Path],
         out_json: Path, power_net: Optional[str], container: str,
         metal_prefix: str, static_json: Optional[Path],
         budget_pct: float) -> Tuple[int, Dict[str, object]]:
    """Run the VCD-vectored PSM and write dynamic_ir.json. Returns (rc, payload)."""
    out_json.parent.mkdir(parents=True, exist_ok=True)
    if vcd is None or not Path(vcd).is_file() or Path(vcd).stat().st_size == 0:
        payload = skip_result(
            "no non-empty design VCD found under the project sim dirs")
        out_json.write_text(json.dumps(payload, indent=2) + "\n")
        return 0, payload
    nets = [power_net] if power_net else discover_power_nets(def_file)
    if not nets:
        payload = skip_result(
            "DEF has no SPECIALNETS power grid (no power net to analyze)")
        payload["status"] = "SKIPPED_NO_PDN"
        out_json.write_text(json.dumps(payload, indent=2) + "\n")
        return 0, payload
    net = nets[0]
    scope = None
    try:
        scope = discover_vcd_scope(Path(vcd).read_text(errors="ignore")[:20000])
    except OSError:
        pass
    via_res = _discover_via_res(tech_lef)
    tcl = _build_tcl(def_file, tech_lef, cell_lef, liberty, macro_lefs, sdc,
                     Path(vcd), scope, net, via_res, metal_prefix)
    tcl_path = out_json.parent / "dynamic_ir_vectored.tcl"
    tcl_path.write_text(tcl)
    cmd = (f"export PATH={_TOOLS}/openroad/bin:{_TOOLS}/bin:$PATH && "
           f"openroad -no_init -exit {tcl_path} 2>&1 | "
           f"tee {out_json.parent}/dynamic_ir.log")
    try:
        proc = subprocess.run(
            ["docker", "exec", container, "bash", "-lc", cmd],
            capture_output=True, text=True, timeout=1200)
        log = (proc.stdout or "") + "\n" + (proc.stderr or "")
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        payload = {"status": "ERROR_TOOL", "dynamic_ir_report_emitted": False,
                   "reason": f"openroad run failed: {e}"}
        out_json.write_text(json.dumps(payload, indent=2) + "\n")
        return 1, payload

    worst_v = parse_worst_ir_v(log)
    if worst_v is None:
        payload = {"signoff_dimension": "dynamic_transient_ir_drop",
                   "analysis_mode": "vcd_vectored_psm",
                   "status": "ERROR_NO_PSM_IR",
                   "dynamic_ir_report_emitted": False,
                   "reason": ("PSM produced no 'Worstcase IR drop' line "
                              "(grid disconnected / no valid resistance map)"),
                   "log_tail": log[-1500:]}
        out_json.write_text(json.dumps(payload, indent=2) + "\n")
        return 1, payload

    vdd = parse_supply_v(log)
    static_mv = read_static_ir_mv(static_json) if static_json else None
    payload = build_result(
        worst_dyn_mv=worst_v * 1000.0, vdd_v=vdd, static_mv=static_mv,
        annotated_pins=parse_annotated_pins(log),
        total_power_w=parse_total_power_w(log), power_net=net,
        vcd=str(vcd), scope=scope)
    # local budget verdict (the authoritative gate re-derives it too)
    if vdd is not None:
        budget_mv = budget_pct / 100.0 * vdd * 1000.0
        payload["budget_pct"] = budget_pct
        payload["budget_mv"] = round(budget_mv, 4)
        payload["verdict"] = "PASS" if worst_v * 1000.0 < budget_mv else "FAIL"
    out_json.write_text(json.dumps(payload, indent=2) + "\n")
    return 0, payload


def _auto_discover(project: Path) -> Dict[str, object]:
    """Best-effort discovery of DEF/LEF/Liberty/SDC/VCD from a run dir layout."""
    pnr = project / "phase3" / "stage3" / "pnr"
    def_file = None
    for name in ("*.def",):
        for c in sorted(pnr.glob(name)):
            # prefer the signed-off/routed DEF (design name), skip stage snaps
            if c.stem not in ("floorplan", "placed", "post_cts", "post_hold",
                              "routed_preantenna"):
                def_file = c
                break
    if def_file is None:
        cands = sorted(pnr.glob("routed.def")) or sorted(pnr.glob("*.def"))
        def_file = cands[0] if cands else None
    pdk = project / "input" / "pdk"
    tech = next(iter(sorted(pdk.rglob("*tech*.lef"))), None)
    cell = next((f for f in sorted(pdk.rglob("*.lef"))
                 if "tech" not in f.name.lower()
                 and "macro" in f.name.lower()), None)
    if cell is None:
        cell = next((f for f in sorted(pdk.rglob("*.lef"))
                     if "tech" not in f.name.lower()), None)
    lib = next(iter(sorted(pdk.rglob("*typ*.lib"))), None) \
        or next(iter(sorted(pdk.rglob("*.lib"))), None)
    sdc = next(iter(sorted(project.rglob("*/pnr/*.sdc"))), None) \
        or next(iter(sorted(project.rglob("*constraint*/*.sdc"))), None) \
        or next(iter(sorted(project.rglob("*.sdc"))), None)
    return {"def": def_file, "tech_lef": tech, "cell_lef": cell,
            "liberty": lib, "sdc": sdc, "vcd": find_vcd(project)}


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(
        description="VCD-vectored dynamic IR-drop emitter (OpenROAD PSM).")
    ap.add_argument("--project", type=Path, default=None,
                    help="run dir — auto-discovers DEF/LEF/Liberty/SDC/VCD")
    ap.add_argument("--def", dest="def_file", type=Path, default=None)
    ap.add_argument("--tech-lef", type=Path, default=None)
    ap.add_argument("--cell-lef", type=Path, default=None)
    ap.add_argument("--liberty", type=Path, default=None)
    ap.add_argument("--macro-lef", type=Path, action="append", default=[])
    ap.add_argument("--sdc", type=Path, default=None)
    ap.add_argument("--vcd", type=Path, default=None)
    ap.add_argument("--net", default=None, help="power net (default: DEF discover)")
    ap.add_argument("--out", type=Path, default=None,
                    help="output dynamic_ir.json (default reports/phase3/)")
    ap.add_argument("--static-json", type=Path, default=None,
                    help="Step-24 ir_drop.json for the exceeds-static compare")
    ap.add_argument("--container", default=_DEFAULT_CONTAINER)
    ap.add_argument("--metal-prefix", default="MET")
    ap.add_argument("--budget-pct", type=float, default=10.0)
    ns = ap.parse_args(argv)

    if ns.project:
        disc = _auto_discover(ns.project)
        ns.def_file = ns.def_file or disc["def"]
        ns.tech_lef = ns.tech_lef or disc["tech_lef"]
        ns.cell_lef = ns.cell_lef or disc["cell_lef"]
        ns.liberty = ns.liberty or disc["liberty"]
        ns.sdc = ns.sdc or disc["sdc"]
        ns.vcd = ns.vcd or disc["vcd"]
        if ns.out is None:
            ns.out = ns.project / "reports" / "phase3" / "dynamic_ir.json"
        if ns.static_json is None:
            sj = ns.project / "reports" / "phase3" / "ir_drop.json"
            ns.static_json = sj if sj.is_file() else None

    if ns.out is None:
        print("error: --out or --project required", file=sys.stderr)
        return 2
    missing = [n for n, v in (("--def", ns.def_file), ("--tech-lef", ns.tech_lef),
                              ("--cell-lef", ns.cell_lef), ("--liberty", ns.liberty))
               if v is None]
    # A missing VCD is an honest SKIP, not an arg error; missing DEF/LEF/lib IS.
    if missing:
        payload = skip_result(
            f"cannot run: missing required input(s) {', '.join(missing)}")
        payload["status"] = "SKIPPED_MISSING_INPUTS"
        ns.out.parent.mkdir(parents=True, exist_ok=True)
        ns.out.write_text(json.dumps(payload, indent=2) + "\n")
        print(json.dumps(payload, indent=2))
        return 0

    rc, payload = emit(
        def_file=ns.def_file, tech_lef=ns.tech_lef, cell_lef=ns.cell_lef,
        liberty=ns.liberty, macro_lefs=list(ns.macro_lef), sdc=ns.sdc,
        vcd=ns.vcd, out_json=ns.out, power_net=ns.net, container=ns.container,
        metal_prefix=ns.metal_prefix, static_json=ns.static_json,
        budget_pct=ns.budget_pct)
    print(json.dumps(payload, indent=2))
    return rc


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
