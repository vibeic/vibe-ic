#!/usr/bin/env python3
"""
final_report_generate.py — generate canonical, chip-AGNOSTIC final
summary markdown from a Phase 2+3 project's artefacts.

Replaces the legacy BACKLOG-v10 P2.1 version. Output is now structured
around the canonical 54-entity flow yaml (Stage 1-4 + A1-A9 + M1-M4 +
P0 umbrella + Stage 5 manufacturing) and is fully driven by data files
the project already produces. Nothing in this file mentions a specific
IC, protocol, opcode, tester model, or analog block name — those live
in `reports/chip_specific_summary.md` (authored by the chip layer or
hand-written) and are linked from the tail of the generated report.

Reads:
  - flow/phase1_phase2_phase3.yaml          (canonical step definitions)
  - flow_compliance_check.py         (verdict per step, run as subproc)
  - synth/*.v + pnr/*.def            (cell-count breakdown)
  - reports/hw_test.json             (generic hardware-test verdict)
                                     OR fallback reports/example_tester_test.json
  - gds/*.gds                        (final GDS metadata)
  - reports/{drc_signoff,lvs,erc}*   (PV verdicts)
  - reports/test_cases.json          (test-vector count, NOT semantics)
  - analog/analog_block_list.json    (list of analog blocks)
  - analog/<block>/tuning_loop.json  (closed-loop convergence summary)
  - waivers.json                     (deferred steps)
  - generated_docs/L1_DATASHEET.json (ic_name only — for header)

Default output:
  <project>/reports/final_summary.md      (canonical name; overwrites)

For chip-specific detail (opcode tables, tester fixture semantics,
analog tuning-target voltages, etc.) author or generate
`reports/chip_specific_summary.md` separately. The generator detects
its presence and references it.

Usage:
  python3 final_report_generate.py <project_dir>
  python3 final_report_generate.py <project_dir> --out PATH
  python3 final_report_generate.py <project_dir> --no-audit  (skip subproc)

Exit codes:
   0 — generated successfully
   2 — IO/usage error
"""
from __future__ import annotations

import argparse
import collections
import datetime as _dt
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import _path_layout as _pl


PLUGIN_ROOT = Path(__file__).resolve().parent.parent
FLOW_YAML = PLUGIN_ROOT / "flow" / "phase1_phase2_phase3.yaml"
COMPLIANCE_TOOL = PLUGIN_ROOT / "programs" / "flow_compliance_check.py"

VERDICT_SYM = {
    "PASS": "✅",
    "WAIVED-DEFERRED": "⚠️",
    "SKIPPED-CONDITION": "⏭️",
    "VACUOUS-PASS": "🟦",
    "FAIL": "❌",
    "MISSING": "❓",
}
STAGE_TITLE = [
    ("stage1", "Stage 1 — RTL generation & verification"),
    ("stage2", "Stage 2 — Synthesis + DFT"),
    ("stage3", "Stage 3 — Physical Design"),
    ("stage_analog", "Analog Track A1-A9"),
    ("stage_mixed_signal", "Mixed-Signal M1-M4"),
    ("stage4", "Stage 4 — Sign-off"),
    ("stage5_manufacturing", "Stage 5 — Manufacturing (silicon-dependent)"),
]
# Compact stage labels for the Stage-breakdown overview table only —
# the per-stage detail headers stay full-length.
STAGE_SHORT = {
    "stage1": "Stage 1 (RTL)",
    "stage2": "Stage 2 (Synth/DFT)",
    "stage3": "Stage 3 (PD)",
    "stage_analog": "Analog (A1–A9)",
    "stage_mixed_signal": "Mixed-Signal (M1–M4)",
    "stage4": "Stage 4 (Sign-off)",
    "stage5_manufacturing": "Stage 5 (Mfg)",
}


# ─── helpers ─────────────────────────────────────────────────────────────

def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for ck in iter(lambda: f.read(1 << 20), b""):
            h.update(ck)
    return h.hexdigest()


# v1.6.34 — full canonical-artefact attestation table.
# These globs MUST stay in sync with the gate's `_CANONICAL_ARTEFACT_GLOBS`
# in agent_report_sha256_attestation_check.py. The 9-class set covers:
#   FPGA SOF, chip GDS, foundry GDS, synth netlist, PnR netlist,
#   foundry LEF, foundry Liberty, analog hardmacro LEF, analog hardmacro
#   Liberty.
_ATTESTATION_GLOBS: Tuple[Tuple[str, str], ...] = (
    ("FPGA SOF",        "phase2/stage1/fpga/output_files/*.sof"),
    ("chip GDS",        "phase3/stage4/gds/*.gds"),
    ("foundry GDS",     "phase3/stage4/foundry_handoff/**/*.gds"),
    ("synth netlist",   "phase2/stage2/synth/*.v"),
    ("PnR netlist",     "phase3/stage3/pnr/*.v"),
    ("foundry LEF",     "phase3/stage4/foundry_handoff/**/*.lef"),
    ("foundry Liberty", "phase3/stage4/foundry_handoff/**/*.lib"),
    # v1.6.607 — v2-rename cascade leftover (paired with same fix
    # in agent_report_sha256_attestation_check.py). Canonical analog
    # hardmacro location is phase3/analog/hardmacro/.
    ("analog LEF",      "phase3/analog/hardmacro/**/*.lef"),
    ("analog Liberty",  "phase3/analog/hardmacro/**/*.lib"),
)


def _gather_attestation_rows(project: Path
                             ) -> List[Tuple[str, str, int, str]]:
    """Return (kind, rel_path, size_bytes, sha256) tuples for every
    canonical artefact present on disk, in deterministic order. Used by
    the SHA-256 Attestation section so a tape-out reviewer can verify
    artefacts independently. Aligned with agent_report_sha256_attestation
    _check.py canonical glob set."""
    rows: List[Tuple[str, str, int, str]] = []
    for kind, pattern in _ATTESTATION_GLOBS:
        for p in sorted(project.glob(pattern)):
            if not p.is_file():
                continue
            try:
                size = p.stat().st_size
                digest = _sha256(p)
            except OSError:
                continue  # broken symlink / permission denied — gate
                          # reports as ARTEFACT_UNREADABLE
            rel = p.relative_to(project)
            rows.append((kind, str(rel), size, digest))
    return rows


def _safe_json(p: Path) -> Optional[Any]:
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return None


# Subdirs of reports/ the generator probes (in priority order) when
# looking up a machine-readable artefact by basename. v1.6.25 added
# phase-aligned subfolders; auto-router goes there first.
REPORT_SUBDIRS = (
    "phase1", "phase2", "phase3", "analog",
    "audit", "orchestrator",
    "signoff", "hardware",
)


def _find_report(project: Path, name: str) -> Optional[Path]:
    """First try the auto-routed canonical location; if not found, scan
    the legacy/alternate subdirs in priority order."""
    routed = _pl.report_path(project, name)
    if routed.is_file():
        return routed
    base = project / "reports"
    for sd in REPORT_SUBDIRS:
        cand = base / sd / name
        if cand.is_file():
            return cand
    flat = base / name
    if flat.is_file():
        return flat
    return None


def _sweep_reports(project: Path) -> int:
    """Defensive sweep: any flat reports/<file> still at reports/ top level
    (because some legacy script slipped through the v1.6.25 writer
    refactor) gets moved into the phase subfolder its name maps to via
    `_pl.report_path()`. Subdirs and files that ARE the phase subfolders
    themselves are left alone.
    """
    base = project / "reports"
    if not base.is_dir():
        return 0
    moved = 0
    for entry in sorted(base.iterdir()):
        if entry.is_dir() or entry.is_symlink():
            continue
        if entry.name in _pl.REPORTS_VALID_SUBDIRS:
            continue
        dst = _pl.report_path(project, entry.name)
        if dst == entry:
            continue
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            if dst.exists():
                dst.unlink()
            entry.rename(dst)
            moved += 1
        except OSError:
            pass
    return moved


def _safe_yaml(p: Path) -> Optional[Any]:
    if not p.is_file():
        return None
    try:
        import yaml  # type: ignore
        return yaml.safe_load(p.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return None


# ─── audit / verdicts ────────────────────────────────────────────────────

def _run_audit(project: Path) -> Tuple[str, str]:
    if not COMPLIANCE_TOOL.is_file():
        return "(flow_compliance_check.py unavailable)", "UNKNOWN"
    try:
        cp = subprocess.run(
            [sys.executable, str(COMPLIANCE_TOOL), str(project), "--strict"],
            capture_output=True, text=True, timeout=180,
        )
        text = cp.stdout
    except Exception as exc:
        return f"(audit failed: {exc})", "UNKNOWN"
    overall = "UNKNOWN"
    for ln in text.splitlines():
        if ln.startswith("Overall:"):
            overall = ln.split(":", 1)[1].strip().split()[0]
            break
    return text, overall


def _parse_verdicts(audit_text: str) -> Dict[str, str]:
    pat = re.compile(r"\[\s*([A-Z][A-Z_-]+?)\s*\]\s*Step\s+([0-9]+|[AM][0-9]+|P0)\s*:")
    return {m.group(2): m.group(1).strip() for m in pat.finditer(audit_text)}


# ─── step tables ─────────────────────────────────────────────────────────

def _trim_step_name(name: str, max_len: int = 50) -> str:
    name = name.replace("🔁 ", "").replace("🔁", "").strip()
    name = re.sub(r"\s*\([^()]*\)\s*$", "", name).strip()
    if len(name) > max_len:
        name = name[:max_len - 1].rstrip() + "…"
    return name


def _compact_id_range(ids: List[str]) -> str:
    """Group consecutive same-prefix IDs into ranges.
      [1,2,3,4,5,6,7]               → '1–7'
      ['A1','A2','A3','A4','A5']    → 'A1–A5'
      [1,2,3,4,5,6,'P0']            → '1–6, P0' (mixed: list each group)
    """
    if len(ids) <= 3:
        return ", ".join(ids)
    # Split into prefix groups
    groups: Dict[str, List[int]] = {}
    for sid in ids:
        m = re.match(r"^([A-Za-z]*)(\d+)$", sid)
        if not m:
            groups.setdefault("__misc__", []).append(0)
            continue
        prefix = m.group(1)
        num = int(m.group(2))
        groups.setdefault(prefix, []).append(num)
    parts = []
    for prefix, nums in groups.items():
        nums = sorted(nums)
        if len(nums) >= 4:
            parts.append(f"{prefix}{nums[0]}–{prefix}{nums[-1]}")
        else:
            parts.extend(f"{prefix}{n}" for n in nums)
    return f"{', '.join(parts)} ({len(ids)})"


def _compact_outputs(outs: List[str]) -> str:
    if not outs:
        return "—"
    first = outs[0].replace(" OR ", " / ")
    if len(outs) > 1:
        return f"`{first}` _(+{len(outs)-1})_"
    return f"`{first}`"


def _compact_inputs(blocks_on: List[Any]) -> str:
    if not blocks_on:
        return "raw `input/`"
    if len(blocks_on) > 4:
        # Long input list → contract to first–last + count
        return f"{blocks_on[0]}–{blocks_on[-1]} ({len(blocks_on)})"
    return ", ".join(str(b) for b in blocks_on)


def _step_sort_key(s: Dict[str, Any]) -> Tuple[int, str, int]:
    sid = s["id"]
    if isinstance(sid, str):
        m = re.match(r"([AMP])(\d+|0)", sid)
        if m:
            return (0 if m.group(1) == "P" else 1, m.group(1), int(m.group(2)))
    return (0, "", int(sid))


def _render_step_tables(flow: Dict[str, Any], verdicts: Dict[str, str]) -> str:
    """Per-stage step listing as compact 5-col markdown tables.

    Width-hardened: step name trimmed to 35 chars, inputs use compact
    range form, output column shows only the first artefact path (no
    `OR`/`|` alternation, no `_(+N)_` suffix). Result: every per-stage
    table fits within ~75 chars, renders cleanly in glow at any terminal
    ≥ 80 cols.
    """
    by_stage: Dict[str, List[Dict[str, Any]]] = {}
    for s in flow.get("steps", []):
        if s.get("id") == "P0":
            continue
        by_stage.setdefault(s["stage"], []).append(s)

    def _first_output(outs: List[str], max_len: int = 28) -> str:
        if not outs:
            return "—"
        first = outs[0].split(" OR ", 1)[0].strip()
        if len(first) > max_len:
            first = first[:max_len - 1].rstrip("/") + "…"
        return f"`{first}`"

    out: List[str] = []
    p0v = VERDICT_SYM.get(verdicts.get("P0", "?"), verdicts.get("P0", "?"))
    out.append("### P0 — Structural-RTL umbrella (chip-agnostic checkers)\n")
    out.append("| ID | Coverage | V |")
    out.append("|---|---|:---:|")
    out.append(f"| **P0** | CDC/RDC + CRC oracle + L9-conformance + protocol audits | {p0v} |\n")
    for stage_id, _full in STAGE_TITLE:
        rows = sorted(by_stage.get(stage_id, []), key=_step_sort_key)
        if not rows:
            continue
        out.append(f"### {_full}\n")
        out.append("| ID | Step | ← | Output | V |")
        out.append("|---:|---|:---:|---|:---:|")
        for s in rows:
            sid = str(s["id"])
            v = VERDICT_SYM.get(verdicts.get(sid, "?"), verdicts.get(sid, "?"))
            name = _trim_step_name(s["name"], max_len=25)
            inputs = _compact_inputs(s.get("blocks_on") or [])
            if inputs == "raw `input/`":
                inputs = "—"
            output = _first_output(s.get("required_outputs") or [], max_len=22)
            out.append(f"| {sid} | {name} | {inputs} | {output} | {v} |")
        out.append("")
    return "\n".join(out)


def _verdict_rollup(flow: Dict[str, Any], verdicts: Dict[str, str]) -> Tuple[Dict[str, int], int]:
    counts = collections.Counter()
    total = 0
    for s in flow.get("steps", []):
        sid = str(s["id"])
        v = verdicts.get(sid, "MISSING")
        counts[v] += 1
        total += 1
    return dict(counts), total


# ─── artefact gathering ──────────────────────────────────────────────────

def _gather_cell_count(project: Path) -> Dict[str, Any]:
    out: Dict[str, Any] = {"total_synth": None, "top": [], "def_components": None,
                           "netlist_path": None, "def_path": None}
    sd = _pl.synth_dir(project)
    netlist = None
    if sd.is_dir():
        for fn in ("chip_top_asic_synth.v", "netlist.v"):
            cand = sd / fn
            if cand.is_file():
                netlist = cand
                break
        if netlist is None:
            cands = list(sd.glob("*synth*.v"))
            if cands:
                netlist = cands[0]
    if netlist is not None:
        out["netlist_path"] = str(netlist.relative_to(project))
        text = netlist.read_text(errors="replace")
        cells = collections.Counter(
            re.findall(r"^\s*([A-Z][A-Z0-9_]+)\s+\\?[\w\.\[\]]+\s*\(", text, re.M)
        )
        out["total_synth"] = sum(cells.values())
        out["top"] = cells.most_common(15)
    pd = _pl.pnr_dir(project)
    if pd.is_dir():
        for fn in ("routed.def", "post_hold.def", "post_cts.def",
                   "placed.def", "floorplan.def"):
            cand = pd / fn
            if cand.is_file():
                try:
                    for line in cand.read_text(errors="replace").splitlines():
                        if line.startswith("COMPONENTS "):
                            out["def_components"] = int(line.split()[1])
                            out["def_path"] = str(cand.relative_to(project))
                            break
                except Exception:
                    pass
                if out["def_components"] is not None:
                    break
    return out


def _gather_hardware_test(project: Path) -> Dict[str, Any]:
    """Generic hw-test schema: {tester, board, verdict, criterion, iterations,
    passed_iterations, evidence}. Reads reports/hw_test.json (canonical)."""
    p = _find_report(project, "hw_test.json")
    d = _safe_json(p) if p else None
    if isinstance(d, dict):
        return {**d, "_source": str(p.relative_to(project))}
    return {}


def _gather_sof(project: Path) -> Optional[Dict[str, Any]]:
    fpga = _pl.fpga_early_dir(project)
    for d in (fpga, fpga / "output_files", fpga / "final"):
        if not d.is_dir():
            continue
        sofs = list(d.glob("*.sof"))
        if sofs:
            f = sofs[0]
            return {"path": str(f.relative_to(project)),
                    "size": f.stat().st_size,
                    "sha256": _sha256(f)}
    return None


def _gather_gds(project: Path) -> Optional[Dict[str, Any]]:
    d = _pl.gds_dir(project)
    if not d.is_dir():
        return None
    gds_files = list(d.glob("*.gds"))
    if not gds_files:
        return None
    f = gds_files[0]
    pv = {}
    for kind in ("drc_signoff", "lvs", "erc"):
        cand = _find_report(project, f"{kind}.json")
        j = _safe_json(cand) if cand else None
        if isinstance(j, dict):
            pv[kind] = j.get("verdict") or j.get("status") or "?"
        else:
            pv[kind] = "(report missing)"
    # Auxiliary signoff reports (IR / EM / antenna / SI / power / STA)
    aux: List[str] = []
    for stem in ("ir_drop", "em", "antenna", "si_crosstalk", "power",
                 "sta/post_route_summary"):
        # sta/ has a nested-path stem; the rest are simple file names.
        if "/" in stem:
            for ext in (".json", ".rpt"):
                p = _pl.report_path(project, f"{stem}{ext}")
                if p.is_file():
                    aux.append(str(p.relative_to(project)))
                    break
            continue
        for ext in (".json", ".rpt"):
            p = _find_report(project, f"{stem}{ext}")
            if p is not None:
                aux.append(str(p.relative_to(project)))
                break
    fpga_signoff = _find_report(project, "fpga_signoff.json")
    return {"path": str(f.relative_to(project)),
            "size": f.stat().st_size,
            "sha256": _sha256(f),
            "pv": pv,
            "aux_reports": aux,
            "fpga_signoff": str(fpga_signoff.relative_to(project)) if fpga_signoff else None}


def _gather_test_evidence(project: Path) -> Dict[str, Any]:
    """Generic test-pattern evidence: reference TB log + sim_full_stack +
    extra count fields. Chip-agnostic — no opcode list."""
    out: Dict[str, Any] = {"ref_tb_logs": [], "sim_full_stack": None,
                           "vectors_total": None, "vectors_passed": None,
                           "distinct_non_padding_bytes": None,
                           "opcodes_tested": None, "all_proved": None,
                           "vectors_csv": None}
    refdir = _pl.sim_dir(project) / "reference_tb"
    if refdir.is_dir():
        out["ref_tb_logs"] = [str(p.relative_to(project))
                              for p in sorted(refdir.glob("*.log"))]
    sfs = _pl.sim_full_stack_dir(project) / "results.json"
    d = _safe_json(sfs)
    if isinstance(d, dict):
        out["sim_full_stack"] = str(sfs.relative_to(project))
        for k in ("vectors_total", "vectors_passed",
                 "distinct_non_padding_bytes", "opcodes_tested", "all_proved"):
            if k in d:
                out[k] = d[k]
    tb = _pl.tb_dir(project)
    if tb.is_dir():
        csvs = list(tb.glob("*test_vectors.csv")) + list(tb.glob("*.csv"))
        if csvs:
            out["vectors_csv"] = str(csvs[0].relative_to(project))
    return out


def _gather_analog_evidence(project: Path) -> Dict[str, Any]:
    """For each declared analog block, check which A1-A9 artefacts exist
    and what mixed-signal / HW evidence is on disk. Chip-agnostic."""
    bl = _safe_json(_pl.analog_dir(project) / "analog_block_list.json")
    if not bl:
        return {}
    blocks_raw = bl.get("blocks") if isinstance(bl, dict) else bl
    block_names: List[str] = []
    for b in blocks_raw or []:
        if isinstance(b, dict):
            n = b.get("name")
            if n:
                block_names.append(n)
        elif isinstance(b, str):
            block_names.append(b)
    # Per-A-step artefact presence is checked against the canonical
    # v2 layout (A1 lives under phase1/analog/<b>/, A2-A4 under
    # phase2/analog/<b>/, A5-A9 under phase3/analog/<b>/) PLUS legacy
    # v1 root-level fallbacks (`analog/<b>/`) so older project trees
    # are still recognised. v1.6.607 — the prior version only listed
    # the v1 fallbacks, which produced an all-MISSING block grid on
    # every v2-canonical project.
    #
    # The locator strategy is: ask the canonical resolver first, then
    # fall back to legacy v1 globs. Resolved paths can be either
    # concrete or contain a `*` (in which case we glob).
    def _safe_glob(d: Path, pattern: str) -> List[Path]:
        """Return d.glob(pattern) as list when d is a dir, else []."""
        return list(d.glob(pattern)) if d.is_dir() else []

    def _a_step_candidates(b: str) -> Dict[str, List[Path]]:
        p1 = _pl.phase1_analog_block_dir(project, b)
        p2 = _pl.phase2_analog_block_dir(project, b)
        p3 = _pl.phase3_analog_block_dir(project, b)
        p3_hm = _pl.phase3_hardmacro_dir(project) / b
        legacy = project / "analog" / b
        legacy_hm = project / "hardmacro" / b
        return {
            "A1": [p1 / "spec.json",
                   legacy / "spec.json"],
            "A2": [p2 / "topology.md",
                   legacy / "topology.md"],
            "A3": ([p2 / f"{b}.sp"]
                   + _safe_glob(p2, "*.sp")
                   + [legacy / f"{b}.sp"]
                   + _safe_glob(legacy, "*.sp")),
            "A4": [p2 / "corner_results.json",
                   legacy / "corner_results.json"],
            "A5": [p3 / "layout.mag",
                   p3 / f"{b}.gds",
                   legacy / "layout.mag",
                   legacy / f"{b}.gds"],
            "A6": [p3 / "drc_clean.flag",
                   legacy / "drc_clean.flag"],
            "A7": [p3 / "pre_vs_post.json",
                   legacy / "pre_vs_post.json"],
            "A8": (_safe_glob(p3_hm, "*.lef")
                   + _safe_glob(legacy_hm, "*.lef")
                   + _safe_glob(legacy / "hardmacro", "*.lef")),
            "A9": ([project / "cosim" / f"{b}_cosim_results.json"]
                   + _safe_glob(legacy, "*cosim*.json")),
        }
    block_grid: Dict[str, Dict[str, bool]] = {}
    for name in block_names:
        candidates = _a_step_candidates(name)
        block_grid[name] = {
            step: any(p.exists() for p in paths if p is not None)
            for step, paths in candidates.items()
        }
    # HW measurements present?
    hw_present = any((_pl.analog_dir(project) / n / "hw_measurements.json").is_file()
                     for n in block_names)
    # Mixed-signal references
    mixed_paths: List[str] = []
    for f in ("mixed_signal/top_merged.gds",
              "reports/mixed_signal/merge.json",
              "reports/mixed_signal/power_domain.json",
              "reports/mixed_signal/level_shifter.json",
              "reports/mixed_signal/isolation.json",
              "reports/mixed_signal/interface_si.json",
              "reports/mixed_signal/signoff.json",
              "cosim/mixed_signal_results.json"):
        if (project / f).is_file():
            mixed_paths.append(f)
    return {"block_names": block_names,
            "block_grid": block_grid,
            "hw_tuning_invoked": hw_present,
            "mixed_paths": mixed_paths}


def _gather_test_patterns(project: Path) -> Dict[str, Any]:
    """Chip-agnostic count summary: total cases, passed, distinct stimulus
    bytes (parsed from JSON text). Does NOT enumerate opcodes — those belong
    in chip_specific_summary.md."""
    p = _find_report(project, "test_cases.json")
    d = _safe_json(p) if p else None
    if not isinstance(d, dict):
        return {}
    cases = d.get("test_cases") or d.get("cases") or []
    total = d.get("total") or len(cases) if isinstance(cases, list) else None
    passed = d.get("passed")
    if passed is None and isinstance(cases, list):
        passed = sum(1 for c in cases if isinstance(c, dict)
                     and (c.get("verdict") or c.get("pass")) in ("PASS", True))
    raw = json.dumps(d)
    distinct_hex = sorted(set(re.findall(r"0x[0-9A-Fa-f]{2}", raw)))
    return {"total": total, "passed": passed,
            "distinct_stimulus_bytes": len(distinct_hex)}


def _gather_analog(project: Path) -> Dict[str, Any]:
    bl_path = _pl.analog_dir(project) / "analog_block_list.json"
    bl = _safe_json(bl_path)
    if not bl:
        return {}
    blocks_raw = bl.get("blocks") if isinstance(bl, dict) else bl
    block_names: List[str] = []
    for b in blocks_raw or []:
        if isinstance(b, dict):
            n = b.get("name")
            if n:
                block_names.append(n)
        elif isinstance(b, str):
            block_names.append(b)
    tuning_summary: List[Dict[str, Any]] = []
    for name in block_names:
        tj = _safe_json(_pl.analog_dir(project) / name / "tuning_loop.json")
        if not isinstance(tj, dict):
            continue
        iters = tj.get("iterations") or []
        if isinstance(iters, list):
            iter_count = len(iters)
            converged = bool(iters) and bool(iters[-1].get("all_corners_pass"))
        else:
            iter_count, converged = None, None
        tuning_summary.append({"block": name,
                               "iterations": iter_count,
                               "converged": converged})
    return {"blocks": block_names, "tuning": tuning_summary}


def _gather_waivers(project: Path) -> Dict[str, Any]:
    """Return both per-step waivers and top-level *_unavailable_reason
    annotations (PDK / EDA gaps). Both are needed for an honest report."""
    d = _safe_json(project / "waivers.json")
    if isinstance(d, dict):
        steps = d.get("waived_steps") or d.get("waivers") or []
        gaps = {k: v for k, v in d.items()
                if k.endswith("_unavailable_reason") and isinstance(v, str)}
        return {"steps": steps, "gaps": gaps}
    if isinstance(d, list):
        return {"steps": d, "gaps": {}}
    return {"steps": [], "gaps": {}}


def _gather_ic_name(project: Path) -> Optional[str]:
    for cand in ("generated_docs/L1_DATASHEET.json",
                 "generated_docs/L2_FRS.json"):
        d = _safe_json(project / cand)
        if isinstance(d, dict):
            n = d.get("ic_name") or d.get("part_number")
            if n:
                return str(n)
    return None


# ─── rendering ───────────────────────────────────────────────────────────

def _render(project: Path, run_audit: bool = True) -> str:
    flow = _safe_yaml(FLOW_YAML) or {}
    audit_text, overall = _run_audit(project) if run_audit else ("(audit skipped)", "UNKNOWN")
    verdicts = _parse_verdicts(audit_text)

    cells = _gather_cell_count(project)
    hw = _gather_hardware_test(project)
    sof = _gather_sof(project)
    gds = _gather_gds(project)
    tp = _gather_test_patterns(project)
    tp_ev = _gather_test_evidence(project)
    analog = _gather_analog(project)
    analog_ev = _gather_analog_evidence(project)
    waivers_pkg = _gather_waivers(project)
    waivers = waivers_pkg["steps"]
    pdk_gaps = waivers_pkg["gaps"]
    ic_name = _gather_ic_name(project) or "(unknown — fill in via L1_DATASHEET.json[ic_name])"
    rollup, total_steps = _verdict_rollup(flow, verdicts)
    chip_addendum = (_pl.report_path(project, "chip_specific_summary.md")).is_file()

    now = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    md: List[str] = []
    md.append(f"# Phase 2+3 Final Summary — {project.name}")
    md.append(f"")
    md.append(f"_Auto-generated chip-AGNOSTIC summary by_ "
              f"`final_report_generate.py` _at {now} (UTC)._")
    md.append(f"")
    md.append(f"- **IC**: `{ic_name}`")
    md.append(f"- **Project root**: `{project}`")
    md.append(f"")
    md.append(f"## Verdict")
    md.append(f"")
    md.append(f"**`Overall: {overall}`**")
    md.append(f"")
    md.append("```")
    audit_lines = audit_text.strip().splitlines()
    # First 5 lines of the audit are the header + Steps + tally
    for ln in audit_lines[:5]:
        md.append(ln)
    md.append("```")
    md.append("")
    pass_n = rollup.get("PASS", 0)
    waived_n = rollup.get("WAIVED-DEFERRED", 0)
    skipped_n = rollup.get("SKIPPED-CONDITION", 0)
    vacuous_n = rollup.get("VACUOUS-PASS", 0)
    fail_n = rollup.get("FAIL", 0)
    md.append(f"- PASS={pass_n} — every executed canonical step passed deterministically.")
    if waived_n:
        md.append(f"- WAIVED-DEFERRED={waived_n} — deferred via documented waiver "
                  "(human review required before tapeout).")
    if skipped_n:
        md.append(f"- SKIPPED-CONDITION={skipped_n} — gate predicate not yet met "
                  "(e.g., manufacturing steps awaiting silicon).")
    if vacuous_n:
        md.append(f"- VACUOUS-PASS={vacuous_n} — gate accepts the present project "
                  "shape; check whether it should be a real PASS for your flow.")
    if fail_n:
        md.append(f"- **FAIL={fail_n}** — blocking; do not claim PASS.")
    md.append("")
    md.append(f"Per the SOLE ACCEPTANCE CRITERION: `executed PASS = "
              f"{pass_n}/{pass_n+waived_n}, deferred = {waived_n} pending foundry sign-off`. "
              f"Engineering Phase 2+3 "
              + ("complete." if overall in ("PASS", "PASS_WITH_WAIVERS") else "INCOMPLETE — fix FAILs before claiming."))
    md.append("")

    # Stage-level summary
    md.append("## Stage breakdown")
    md.append("")
    md.append("| Stage | Steps | PASS | Other |")
    md.append("|---|---|---:|---|")
    by_stage: Dict[str, List[Dict[str, Any]]] = {}
    for s in flow.get("steps", []):
        by_stage.setdefault(s.get("stage", "?"), []).append(s)
    for stage_id, _full_title in STAGE_TITLE:
        rows = by_stage.get(stage_id, [])
        if not rows:
            continue
        title = STAGE_SHORT.get(stage_id, _full_title)
        def _id_sort(sid: str) -> Tuple[int, str, int]:
            m = re.match(r"^([AMP])(\d+|0)$", sid)
            if m:
                return (1, m.group(1), int(m.group(2)))
            try:
                return (0, "", int(sid))
            except ValueError:
                return (2, sid, 0)
        ids = sorted([str(s["id"]) for s in rows], key=_id_sort)
        per_v = collections.Counter(verdicts.get(str(s["id"]), "MISSING") for s in rows)
        npass = per_v.get("PASS", 0) + per_v.get("VACUOUS-PASS", 0)
        other_bits = []
        for k in ("WAIVED-DEFERRED", "SKIPPED-CONDITION", "VACUOUS-PASS",
                 "FAIL", "MISSING"):
            if per_v.get(k):
                # Compact: WAIVED-DEFERRED → ⚠️=1, SKIPPED-CONDITION → ⏭=N, etc.
                short = {"WAIVED-DEFERRED": "⚠️",
                         "SKIPPED-CONDITION": "⏭️",
                         "VACUOUS-PASS": "🟦",
                         "FAIL": "❌",
                         "MISSING": "❓"}[k]
                other_bits.append(f"{short}={per_v[k]}")
        md.append(f"| {title} | {_compact_id_range(ids)} | {npass} / {len(rows)} | "
                  f"{' '.join(other_bits) if other_bits else '—'} |")
    md.append("")

    # 4 generic mandatory outputs
    md.append("## Output #1 — Hardware verification (generic)")
    md.append("")
    if hw:
        md.append(f"- **Verdict**: `{hw.get('verdict','?')}`")
        if hw.get("tester"):
            md.append(f"- **Tester**: `{hw['tester']}`")
        if hw.get("board"):
            md.append(f"- **Board**: `{hw['board']}`")
        if hw.get("criterion"):
            md.append(f"- **Acceptance criterion**: `{hw['criterion']}`")
        if hw.get("iterations") is not None:
            pi = hw.get("passed_iterations")
            md.append(f"- **Iterations**: "
                      f"{pi if pi is not None else hw['iterations']} / {hw['iterations']}")
        ev = hw.get("evidence")
        if isinstance(ev, list) and ev:
            md.append(f"- **Evidence**: {', '.join(f'`{e}`' for e in ev[:5])}"
                      + (f" _(+{len(ev)-5} more)_" if len(ev) > 5 else ""))
        if hw.get("_source"):
            md.append(f"- _Source_: `{hw['_source']}`")
    else:
        md.append("_No `reports/hw_test.json` or legacy `reports/example_tester_test.json` found._")
    if sof:
        md.append(f"- **Bitstream**: `{sof['path']}` ({sof['size']:,} B)")
        md.append(f"- **Bitstream SHA-256**: `{sof['sha256']}`")
    md.append("")

    md.append("## Output #2 — FPGA-verified GDS")
    md.append("")
    if gds:
        md.append(f"- **GDS**: `{gds['path']}` ({gds['size']:,} B)")
        md.append(f"- **GDS SHA-256**: `{gds['sha256']}`")
        # Flatten PV verdicts (glow strips nested-list indent)
        pv_summary = ", ".join(f"{k}=`{v}`" for k, v in gds["pv"].items())
        md.append(f"- **Physical verification**: {pv_summary}")
        if gds.get("aux_reports"):
            paths_inline = ", ".join(f"`{p}`" for p in gds["aux_reports"])
            md.append(f"- **Auxiliary signoff reports** "
                      f"({len(gds['aux_reports'])}): {paths_inline}")
        if gds.get("fpga_signoff"):
            md.append(f"- **FPGA recompile + on-board re-test**: `{gds['fpga_signoff']}`")
    else:
        md.append("_No `gds/*.gds` present._")
    md.append("")

    md.append("## Output #3 — Test patterns (count summary)")
    md.append("")
    if tp:
        md.append(f"- **Test cases**: {tp.get('passed','?')} / {tp.get('total','?')} PASS")
        md.append(f"- **Distinct stimulus bytes** (counted from JSON): "
                  f"{tp.get('distinct_stimulus_bytes')}")
    else:
        md.append("- _No `reports/test_cases.json` found._")
    if tp_ev.get("vectors_total") is not None:
        md.append(f"- **sim_full_stack vectors**: {tp_ev.get('vectors_passed','?')} / "
                  f"{tp_ev['vectors_total']} PASS"
                  + (f" (all_proved={tp_ev.get('all_proved')})" if tp_ev.get("all_proved") is not None else ""))
        ot = tp_ev.get("opcodes_tested")
        if ot is not None:
            # Could be int (count) or list (chip-specific); always render count only.
            count = len(ot) if isinstance(ot, list) else ot
            md.append(f"- **Distinct opcodes / commands exercised**: {count}")
        if tp_ev.get("distinct_non_padding_bytes") is not None:
            md.append(f"- **Distinct non-padding bytes**: {tp_ev['distinct_non_padding_bytes']}")
    if tp_ev.get("sim_full_stack"):
        md.append(f"- _sim_full_stack source_: `{tp_ev['sim_full_stack']}`")
    if tp_ev.get("ref_tb_logs"):
        md.append(f"- **Reference TB logs** ({len(tp_ev['ref_tb_logs'])}): "
                  + ", ".join(f"`{p}`" for p in tp_ev["ref_tb_logs"][:3])
                  + (f" _(+{len(tp_ev['ref_tb_logs'])-3} more)_" if len(tp_ev["ref_tb_logs"]) > 3 else ""))
    if tp_ev.get("vectors_csv"):
        md.append(f"- **Vector CSV**: `{tp_ev['vectors_csv']}`")
    md.append("")
    md.append("_Per-opcode / per-mode coverage detail belongs in_ "
              "`reports/chip_specific_summary.md` _(this section stays chip-agnostic)._")
    md.append("")

    md.append("## Output #4 — Analog convergence (tuning loops)")
    md.append("")
    if analog:
        md.append(f"- **Declared analog blocks** ({len(analog.get('blocks',[]))}): "
                  + ", ".join(f"`{b}`" for b in analog.get("blocks", [])))
        if analog.get("tuning"):
            md.append("")
            md.append("| Block | Iterations | Converged |")
            md.append("|---|---:|:---:|")
            for t in analog["tuning"]:
                conv = "✅" if t.get("converged") else ("❌" if t.get("converged") is False else "—")
                md.append(f"| `{t['block']}` | {t.get('iterations','—')} | {conv} |")
        else:
            md.append("- _No `tuning_loop.json` files found under `analog/<block>/`._")
        # Per-block A1-A9 evidence grid
        if analog_ev.get("block_grid"):
            md.append("")
            md.append("**Per-block A1-A9 artefact presence:**")
            md.append("")
            steps_hdr = ["A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "A9"]
            md.append("| Block | " + " | ".join(steps_hdr) + " |")
            md.append("|---|" + "|".join([":---:"] * len(steps_hdr)) + "|")
            for name, grid in analog_ev["block_grid"].items():
                cells_md = " | ".join("✅" if grid.get(s) else "—" for s in steps_hdr)
                md.append(f"| `{name}` | {cells_md} |")
        # Mixed-signal references — inline list (avoid nested bullets)
        if analog_ev.get("mixed_paths"):
            md.append("")
            paths_inline = ", ".join(f"`{p}`" for p in analog_ev["mixed_paths"])
            md.append(f"- **Mixed-signal artefacts** ({len(analog_ev['mixed_paths'])}): "
                      f"{paths_inline}")
        # HW-tuning loop status
        md.append("")
        if analog_ev.get("hw_tuning_invoked"):
            md.append("**Hardware-in-the-loop tuning**: invoked "
                      "(see `analog/<block>/hw_measurements.json`).")
        else:
            md.append("**Hardware-in-the-loop tuning**: NOT invoked — analog-block "
                      "silicon unavailable; SPICE-only convergence preserved.")
    else:
        md.append("_No `analog/analog_block_list.json` found — pure-digital project, "
                  "or analog track not run._")
    md.append("")

    # Cell count
    md.append("## Cell count (synth + PnR)")
    md.append("")
    md.append("| Stage | Count | Source |")
    md.append("|---|---:|---|")
    if cells["netlist_path"]:
        md.append(f"| Yosys post-synth | "
                  f"{cells['total_synth'] if cells['total_synth'] is not None else '—'}"
                  f" | `{cells['netlist_path']}` |")
    else:
        md.append("| Yosys post-synth | — | _(no netlist found)_ |")
    if cells["def_components"] is not None:
        md.append(f"| PnR DEF (COMPONENTS) | {cells['def_components']} | `{cells['def_path']}` |")
    else:
        md.append("| PnR DEF (COMPONENTS) | — | _(no DEF found)_ |")
    if cells["top"]:
        md.append("")
        md.append("### Top-15 cell-type histogram")
        md.append("")
        md.append("| Cell | Count |")
        md.append("|---|---:|")
        for name, n in cells["top"]:
            md.append(f"| `{name}` | {n} |")
    md.append("")

    # 54-step canonical breakdown
    md.append(f"## Canonical step input/output ({total_steps} entities)")
    md.append("")
    md.append(f"_Per_ `flow/phase1_phase2_phase3.yaml` _v{flow.get('version','?')}._")
    md.append("")
    md.append(_render_step_tables(flow, verdicts))
    md.append("### Verdict roll-up")
    md.append("")
    md.append("| Verdict | Count |")
    md.append("|---|---:|")
    for v in ("PASS", "VACUOUS-PASS", "WAIVED-DEFERRED", "SKIPPED-CONDITION", "FAIL", "MISSING"):
        if rollup.get(v):
            md.append(f"| {VERDICT_SYM.get(v, v)} {v} | {rollup[v]} |")
    md.append(f"| **Total** | **{total_steps}** |")
    md.append("")

    # Waivers — full text (no truncation)
    md.append("## Waivers (must be human-reviewed before tapeout)")
    md.append("")
    if waivers:
        for w in waivers[:20]:
            md.append(f"### Step {w.get('id','?')} — `{w.get('ticket','—')}`")
            md.append("")
            md.append(f"- **Approver**: `{w.get('approver','—')}`  "
                      f"  **review_required**: "
                      f"{'✅' if w.get('review_required') else '❌ NO (suspicious)'}")
            if w.get("approved_at"):
                md.append(f"- **Approved at**: `{w['approved_at']}`")
            if w.get("evidence"):
                md.append(f"- **Evidence**: `{w['evidence']}`")
            if w.get("cascades_to"):
                md.append(f"- **Cascades to**: {w['cascades_to']}")
            reason = w.get("reason") or "(no reason given — waiver is INVALID)"
            md.append("")
            md.append("```")
            for ln in str(reason).splitlines():
                md.append(ln)
            md.append("```")
            md.append("")
        if len(waivers) > 20:
            md.append(f"_+{len(waivers)-20} additional waivers omitted; see `waivers.json` directly._")
            md.append("")
    else:
        md.append("_No waivers — every executed step verified deterministically._")
        md.append("")
    # Top-level PDK / EDA tooling gaps (also tracked in waivers.json).
    # Render as a 2-col table — Reason column is truncated to keep table
    # width ≤ ~80c so glow / mdcat render it cleanly.
    if pdk_gaps:
        md.append("### PDK / EDA tooling gaps (waivers.json top-level)")
        md.append("")
        md.append("These are NOT design FAILs — they document where the project "
                  "fell back to a placeholder because the open-source PDK or EDA "
                  "tool lacked characterised data needed for full sign-off. "
                  "Production tapeout requires re-running on a foundry-grade flow.")
        md.append("")
        md.append("| Gap | Reason (summary) |")
        md.append("|---|---|")
        for k, v in sorted(pdk_gaps.items()):
            label = k.replace("_unavailable_reason", "").replace("_", " ")
            # Strip newlines + collapse whitespace + truncate to first sentence
            # (or 90 chars max). Full reasons remain in waivers.json.
            v_clean = re.sub(r"\s+", " ", v.replace("|", "/")).strip()
            first_period = v_clean.find(". ")
            if 0 < first_period < 90:
                summary = v_clean[:first_period + 1]
            elif len(v_clean) > 90:
                summary = v_clean[:87].rstrip() + "…"
            else:
                summary = v_clean
            md.append(f"| `{label}` | {summary} |")
        md.append("")
        md.append("_Full reason text per gap available in_ `waivers.json`.")
        md.append("")

    # Resource log — derived from rollup
    md.append("## Resource log")
    md.append("")
    if cells.get("total_synth"):
        md.append(f"- Standard-cell count post-synth: **{cells['total_synth']}** "
                  f"(from `{cells['netlist_path']}`)")
    if cells.get("def_components"):
        md.append(f"- DEF COMPONENTS post-PnR: **{cells['def_components']}**")
    if analog_ev.get("block_names"):
        n = len(analog_ev["block_names"])
        a_total = sum(sum(g.values()) for g in analog_ev["block_grid"].values())
        md.append(f"- Analog blocks: {n} × 9 stages "
                  f"= {n*9} per-block step-runs (artefacts present: {a_total}/{n*9})")
        if analog and analog.get("tuning"):
            for t in analog["tuning"]:
                md.append(f"- Closed-loop tuning ({t['block']}): "
                          f"{t.get('iterations','?')} iterations, "
                          f"converged={'yes' if t.get('converged') else 'no'}")
    md.append(f"- Canonical step PASS: "
              f"**{rollup.get('PASS', 0)}/{total_steps - rollup.get('SKIPPED-CONDITION', 0)}** "
              f"(deferred via waiver: {rollup.get('WAIVED-DEFERRED', 0)}, "
              f"vacuous-pass: {rollup.get('VACUOUS-PASS', 0)}, "
              f"manufacturing-skipped: {rollup.get('SKIPPED-CONDITION', 0)})")
    md.append("")

    # SHA-256 Attestation table — v1.6.34 closes doctrine rule #5
    # producer-consumer mismatch (gate ships in v1.6.33 but producer
    # only emitted SOF + GDS hashes inline; gate expects the full
    # 9-class set and looks for them in either AGENT_REPORT.md or
    # reports/final_summary.md).
    md.append("## SHA-256 Attestation")
    md.append("")
    md.append("Independent reviewers can verify any artefact by re-")
    md.append("computing `sha256sum <path>` and comparing against the")
    md.append("table below. Every canonical artefact present on disk")
    md.append("is listed; mismatches or omissions are caught by")
    md.append("`agent_report_sha256_attestation_check.py`.")
    md.append("")
    rows = _gather_attestation_rows(project)
    if rows:
        md.append("| Artefact | Path | Size (B) | SHA-256 |")
        md.append("|---|---|---:|---|")
        for kind, rel, size, digest in rows:
            md.append(f"| {kind} | `{rel}` | {size:,} | `sha256:{digest}` |")
    else:
        md.append("_No canonical artefacts present on disk yet._")
    md.append("")

    # Self-attestation
    md.append("## Self-attestation")
    md.append("")
    md.append("```bash")
    md.append(f"python3 {COMPLIANCE_TOOL} \\")
    md.append(f"    {project} --strict")
    md.append("```")
    md.append("")

    # Chip-specific addendum link
    md.append("## Chip-specific addendum")
    md.append("")
    if chip_addendum:
        md.append("See [`reports/chip_specific_summary.md`](chip_specific_summary.md) "
                  "for IC-specific opcode coverage, tester fixture semantics, "
                  "analog tuning targets, and any chip-known issues.")
    else:
        md.append("_No `reports/chip_specific_summary.md` present. Author it by hand "
                  "(or via a chip-specific Phase-2a skill) to document IC-specific "
                  "test interpretations, opcode tables, tuning-target values, etc. "
                  "This generator deliberately keeps the canonical summary "
                  "chip-agnostic._")
    md.append("")

    return "\n".join(md) + "\n"


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=(
        "Generate canonical chip-AGNOSTIC final_summary.md from Phase 2+3 artefacts."
    ))
    ap.add_argument("project_dir")
    ap.add_argument("--out", default=None,
                    help="Output path (default: <project>/reports/final_summary.md)")
    ap.add_argument("--no-audit", action="store_true",
                    help="Skip running flow_compliance_check.py (verdicts will be UNKNOWN).")
    args = ap.parse_args(argv)

    project = Path(args.project_dir).resolve()
    if not project.is_dir():
        print(f"[ERROR] project_dir not found: {project}", file=sys.stderr)
        return 2
    out_path = Path(args.out) if args.out else _pl.report_path(project, "final_summary.md")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    md = _render(project, run_audit=not args.no_audit)
    out_path.write_text(md, encoding="utf-8")
    # NOTE: legacy plugin gate writers still write to reports/<flat>
    # paths. Auto-sweep was disabled because it conflicts with legacy
    # readers + symlink resolution. To keep reports/ visually clean,
    # use a separate one-shot reorganiser script after phase23.
    print(f"[OK] final summary → {out_path}  ({len(md)} bytes, "
          f"{md.count(chr(10))} lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
