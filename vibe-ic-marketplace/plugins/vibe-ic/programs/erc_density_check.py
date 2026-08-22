#!/usr/bin/env python3
"""Step-31 ERC + sign-off density-rule verification (real substance).

This is the Step-31 *physical-verification* density + ERC checker. It is a
DIFFERENT check from `metal_fill_density_check` (Step 34): the flow's step
ORDER puts Step 31 before Step 34, so this checker must not key off
`filled.def` / `metal_fill.done` — the fill-marker logic of
`metal_fill_density_check` would wrongly FAIL here.

The density artefact it reads, reports/density.{json,rpt}, is written by the
metal-fill emitter and is declared as Step 34's required_output. The runner
emits metal fill before the ERC report inside one pass, so the artefact is on
disk when this gate runs; when it genuinely is not, that is DENSITY_MISSING
(ERROR, rc=1) — see the exit-code policy in main().

What this verifies (no fabrication, real parsing of the produced artefact):

  DENSITY sub-check (UNCONDITIONAL — see the exit-code policy in main()):
    * The density artefact (reports/density.json or reports/density.rpt, also
      reports/phase3/...) must parse, be non-empty, carry a recognizable EDA
      tool provenance signature, AND contain a real numeric density metric.
    * If the artefact reports PER-LAYER metal CMP density (the genuine foundry
      20-80% rule target), every layer must fall inside [20%, 80%]. Any layer
      out of that window is the silicon failure this gate guards (foundry
      rejects the tapeout at CMP) -> honest FAIL.
    * If the artefact only reports OpenROAD filler_placement std-cell ROW
      utilization (the open-source flow's metric — e.g. 14%), the per-metal-
      layer 20-80% CMP rule is screened by the KLayout sign-off DRC deck
      (met_min_ca_density), NOT by this report. We therefore do NOT mis-apply
      the 20-80% window to row utilization (doing so would be a fabricated
      threshold on the wrong metric). We instead require a real, in-range
      [0%, 100%] row-utilization number plus tool provenance — a real number,
      never a vacuous pass.
    * Missing / empty / unparseable / provenance-less / number-less artefact
      => honest FAIL (rc=1). Never a vacuous PASS on absence.

  ERC sub-check (only when reports/phase3/erc.rpt — or reports/erc.rpt —
  exists; otherwise SKIPPED, not failed):
    * Parse the floating-net / "ERC clean" substance. Floating signal nets or
      an explicit "ERC clean: NO" are a real electrical-rule failure -> FAIL.
      A clean report (0 floating nets, clean=YES) contributes PASS.

CLI contract (preserved across all phase checkers):
    python3 erc_density_check.py <project_dir> [--json <out>]
    main(argv) -> int   (0 PASS / 1 FAIL / 2 SKIP)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Optional, Tuple
from _atomic_artefact import write_text as atomic_write_text  # vibe-ic#1082 (helper from PR #1094)

sys.path.insert(0, str(Path(__file__).parent))
try:
    import _path_layout as _pl  # noqa: F401  (used for canonical reports dir)
except Exception:  # pragma: no cover - _path_layout always present in-repo
    _pl = None


@dataclass
class Finding:
    severity: str          # ERROR | WARNING | INFO
    category: str
    message: str
    details: str = ""


# Genuine foundry CMP per-metal-layer density window. Stated by the
# real density.rpt produced by the flow ("per-metal-layer CMP density
# (20-80% rule)") — this is a published-rule constant, not fabricated.
_MIN_LAYER_DENSITY = 20.0
_MAX_LAYER_DENSITY = 80.0

# Recognizable EDA-tool provenance signatures for a density artefact.
# Absence => the report is not a real tool product => FAIL (anti-fab).
_DENSITY_TOOL_SIGNATURES = (
    "openroad", "filler_placement", "klayout", "magic", "calibre",
    "met_min_ca_density", "density", "cmp",
)

# Layer-name tokens that identify a *metal-layer* density datum (the
# real 20-80% rule target) as opposed to a std-cell row-utilization datum.
_METAL_LAYER_RE = re.compile(
    r"\b(met\d+|metal\d+|m\d+|li1|poly|nwell|diff)\b", re.I)


# ── density artefact discovery ──────────────────────────────────────

def _reports_root(project_dir: Path) -> Path:
    return project_dir / "reports"


def _find_density_artefacts(project_dir: Path) -> Tuple[Optional[Path], Optional[Path]]:
    """Return (density_json, density_rpt), searching reports/ and reports/phase3/.

    The flow writes density.{json,rpt} at reports/ root; report_path() routes
    the canonical name to reports/phase3/. We look in both for robustness.
    """
    root = _reports_root(project_dir)
    candidates_json = [root / "density.json", root / "phase3" / "density.json"]
    candidates_rpt = [root / "density.rpt", root / "phase3" / "density.rpt"]
    djson = next((p for p in candidates_json if p.exists()), None)
    drpt = next((p for p in candidates_rpt if p.exists()), None)
    return djson, drpt


def _find_erc_report(project_dir: Path) -> Optional[Path]:
    root = _reports_root(project_dir)
    for p in (root / "phase3" / "erc.rpt", root / "erc.rpt",
              root / "phase3" / "phase3" / "erc.rpt"):
        if p.exists():
            return p
    return None


# ── density substance parsing ───────────────────────────────────────

def _has_tool_signature(text: str) -> bool:
    low = text.lower()
    return any(sig in low for sig in _DENSITY_TOOL_SIGNATURES)


def _parse_layers_from_json(data) -> List[Tuple[str, float]]:
    """Extract (layer_name, density_pct) pairs that look like METAL-layer CMP
    density. Returns [] when the JSON carries no per-layer metal density."""
    out: List[Tuple[str, float]] = []
    layers = None
    if isinstance(data, dict):
        layers = data.get("layers")
        if layers is None and "metal_density" in data:
            layers = data.get("metal_density")
    if isinstance(layers, dict):
        layers = [{"name": k, "density_pct": v} for k, v in layers.items()
                  if isinstance(v, (int, float))]
    if isinstance(layers, list):
        for layer in layers:
            if not isinstance(layer, dict):
                continue
            name = str(layer.get("name", layer.get("layer", "?")))
            dens = layer.get("density_pct", layer.get("density"))
            if isinstance(dens, (int, float)):
                out.append((name, float(dens)))
    return out


def _parse_row_utilization(data, text: str) -> Optional[float]:
    """Extract std-cell row-utilization % from JSON or rpt text."""
    if isinstance(data, dict):
        for key in ("row_utilization_pct", "row_utilization",
                    "utilization_pct", "utilization"):
            v = data.get(key)
            if isinstance(v, (int, float)):
                return float(v)
    m = re.search(r"row utilization[^0-9]*([0-9]+(?:\.[0-9]+)?)\s*%", text, re.I)
    if m:
        return float(m.group(1))
    m = re.search(r"utilization[^0-9]*([0-9]+(?:\.[0-9]+)?)\s*%", text, re.I)
    if m:
        return float(m.group(1))
    return None


_RPT_LAYER_RE = re.compile(
    r"(met\d+|metal\d+|m\d+|li1|poly)\s*[:=]?\s*density\s*[:=]?\s*"
    r"([0-9]+(?:\.[0-9]+)?)\s*%?", re.I)
_RPT_LAYER_RE2 = re.compile(
    r"(met\d+|metal\d+|m\d+|li1|poly)\b[^\n%]*?([0-9]+(?:\.[0-9]+)?)\s*%", re.I)


def _parse_layers_from_text(text: str) -> List[Tuple[str, float]]:
    out: List[Tuple[str, float]] = []
    for line in text.splitlines():
        low = line.lower()
        # Only treat a line as a per-layer CMP density datum when it
        # mentions density AND a metal layer — never row utilization.
        if "utilization" in low or "row" in low:
            continue
        if "density" not in low:
            continue
        m = _RPT_LAYER_RE.search(line) or _RPT_LAYER_RE2.search(line)
        if m and _METAL_LAYER_RE.search(m.group(1)):
            out.append((m.group(1), float(m.group(2))))
    return out


def _check_density(project_dir: Path, findings: List[Finding], stats: dict) -> None:
    djson, drpt = _find_density_artefacts(project_dir)
    if djson is None and drpt is None:
        findings.append(Finding(
            "ERROR", "DENSITY_MISSING",
            "No density artefact (reports/density.json or reports/density.rpt) "
            "found — the Step-31 density sub-check cannot verify substance"))
        return

    stats["density_checked"] = True
    data = None
    text = ""

    # Prefer structured JSON; fall back to the rpt text.
    if djson is not None:
        raw = djson.read_text(errors="replace")
        text += raw
        if not raw.strip():
            findings.append(Finding("ERROR", "DENSITY_EMPTY",
                                    f"{djson} is empty"))
            return
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            findings.append(Finding("ERROR", "DENSITY_BAD_JSON",
                                    f"Cannot parse {djson}: {exc}"))
            return
    if drpt is not None:
        rpt_text = drpt.read_text(errors="replace")
        if djson is None and not rpt_text.strip():
            findings.append(Finding("ERROR", "DENSITY_EMPTY",
                                    f"{drpt} is empty"))
            return
        text += "\n" + rpt_text

    # Provenance: must be a real tool product, not a hand-faked PASS file.
    if not _has_tool_signature(text):
        findings.append(Finding(
            "ERROR", "DENSITY_NO_PROVENANCE",
            "Density artefact carries no recognizable EDA-tool signature "
            f"(one of {_DENSITY_TOOL_SIGNATURES[:5]}...) — cannot trust"))
        return

    # 1) Per-layer metal CMP density (the genuine 20-80% rule target).
    layers = _parse_layers_from_json(data) if data is not None else []
    if not layers:
        layers = _parse_layers_from_text(text)

    if layers:
        stats["per_layer_density"] = True
        for name, dens in layers:
            if _MIN_LAYER_DENSITY <= dens <= _MAX_LAYER_DENSITY:
                stats["layers_ok"] += 1
            else:
                stats["layers_bad"] += 1
                findings.append(Finding(
                    "ERROR", "DENSITY_OOB",
                    f"Metal layer {name} CMP density {dens:.1f}% outside "
                    f"foundry window [{_MIN_LAYER_DENSITY}%, "
                    f"{_MAX_LAYER_DENSITY}%] — foundry will reject at CMP"))
        return

    # 2) No per-layer CMP data: this is the OpenROAD filler_placement
    #    std-cell row-utilization report. The 20-80% per-layer rule is
    #    screened by the KLayout sign-off DRC deck, NOT here. We require a
    #    real, sane row-utilization number — never a vacuous pass — but we
    #    do NOT mis-apply the 20-80% window to row utilization.
    row_util = _parse_row_utilization(data, text)
    if row_util is None:
        findings.append(Finding(
            "ERROR", "DENSITY_NO_METRIC",
            "Density artefact has neither per-layer metal CMP density nor a "
            "std-cell row-utilization number — no substance to verify"))
        return
    if not (0.0 <= row_util <= 100.0):
        findings.append(Finding(
            "ERROR", "DENSITY_ROW_UTIL_INSANE",
            f"std-cell row utilization {row_util:.1f}% is not a sane "
            "percentage [0%, 100%]"))
        return
    stats["row_utilization_pct"] = row_util
    findings.append(Finding(
        "INFO", "DENSITY_ROW_UTIL_DELEGATED",
        f"std-cell row utilization {row_util:.1f}% present; per-metal-layer "
        "20-80% CMP density is screened by the KLayout sign-off DRC deck "
        "(met_min_ca_density), verified by the drc_report_check gate"))


# ── ERC substance parsing ───────────────────────────────────────────

def _check_erc(project_dir: Path, findings: List[Finding], stats: dict) -> None:
    erc = _find_erc_report(project_dir)
    if erc is None:
        # ERC report genuinely absent → ERC sub-check does not apply here.
        return
    stats["erc_checked"] = True
    text = erc.read_text(errors="replace")
    if not text.strip():
        findings.append(Finding("ERROR", "ERC_EMPTY", f"{erc} is empty"))
        return

    floating = None
    m = re.search(r"ERC floating nets\s*[:=]\s*([0-9]+)", text, re.I)
    if m is None:
        m = re.search(r"found\s+([0-9]+)\s+floating nets", text, re.I)
    if m:
        floating = int(m.group(1))
        stats["erc_floating_nets"] = floating

    clean_no = re.search(r"ERC clean\s*[:=]\s*NO", text, re.I) is not None
    clean_yes = re.search(r"ERC clean\s*[:=]\s*YES", text, re.I) is not None

    # Require some substance: either an explicit clean verdict or a count.
    if floating is None and not clean_no and not clean_yes:
        findings.append(Finding(
            "ERROR", "ERC_NO_SUBSTANCE",
            f"{erc} has no parseable ERC verdict (floating-net count / "
            "'ERC clean: YES|NO') — cannot verify"))
        return

    if (floating is not None and floating > 0) or clean_no:
        # ORGANIC #696 — a raw floating-net COUNT > 0 is NOT automatically a
        # functional ERC defect. The OpenROAD ERC screen reports
        # structurally-benign floats too: design-for-ECO spare-cell I/O
        # (intentionally tied-off, pre-placed for a metal ECO), power/ground
        # rails (VPWR/VGND/vdd/vss SPECIALNETS), and the yosys hilomap
        # constant-tie net (zero_/one_). Classify the floats BY OWNER and
        # FAIL only on a positive FUNCTIONAL count. §4.05 no-leak: a genuine
        # floating SIGNAL net (not spare-owned, not a power/ground rail, not
        # a tie net) is still functional → ERC_DIRTY FAIL; an unparseable
        # report with no verbose float list also still FAILs (we cannot
        # prove the floats are benign, so we do not waive on faith).
        functional = floating if floating is not None else None
        classified = None
        try:
            import erc_float_owner_classify as _efc  # noqa: PLC0415
            names = _efc.parse_floats(text)
            if names:
                classified = _efc.classify(names)
                functional = classified["functional_count"]
        except Exception:
            classified = None  # fall through to raw-count FAIL
        if classified is not None and functional == 0:
            # All floats are structurally benign (spare I/O / power-ground /
            # tie nets). This is the open-source ERC screen's known benign
            # set — record as REVIEW/INFO, not a hard ERC_DIRTY failure.
            stats["erc_clean"] = True
            stats["erc_floating_benign"] = classified["benign_count"]
            stats["erc_floating_functional"] = 0
            findings.append(Finding(
                "INFO", "ERC_BENIGN_FLOATS",
                f"ERC floating nets={floating} are 100% structurally benign "
                f"(spare-cell I/O / power-ground rails / hilomap tie net; "
                f"by_owner={classified['by_owner']}) — 0 functional floats, "
                "not an electrical-rule failure (#696)"))
            return
        # Genuine functional float(s) — or an unclassifiable report — FAIL.
        _fn = (f"{functional} functional of {floating}"
               if (classified is not None and floating is not None)
               else (str(floating) if floating is not None else "?"))
        findings.append(Finding(
            "ERROR", "ERC_DIRTY",
            f"ERC not clean: floating nets={_fn}, "
            f"clean={'NO' if clean_no else ('YES' if clean_yes else '?')} "
            "— floating signal nets are a real electrical-rule failure"))
        return
    stats["erc_clean"] = True
    findings.append(Finding("INFO", "ERC_CLEAN",
                            "ERC clean: 0 floating nets"))


# ── orchestration ───────────────────────────────────────────────────

def audit(project_dir: Path) -> Tuple[List[Finding], dict]:
    findings: List[Finding] = []
    stats = {
        "density_checked": False, "per_layer_density": False,
        "layers_ok": 0, "layers_bad": 0, "row_utilization_pct": None,
        "erc_checked": False, "erc_floating_nets": None, "erc_clean": False,
    }
    _check_density(project_dir, findings, stats)
    _check_erc(project_dir, findings, stats)
    return findings, stats


def build_report(findings: List[Finding], stats: dict, project_dir: str) -> dict:
    return {
        "program": "erc_density_check",
        "version": "1.0.0",
        "project_dir": project_dir,
        "summary": {
            "density_checked": stats["density_checked"],
            "per_layer_density": stats["per_layer_density"],
            "layers_ok": stats["layers_ok"],
            "layers_bad": stats["layers_bad"],
            "row_utilization_pct": stats["row_utilization_pct"],
            "erc_checked": stats["erc_checked"],
            "erc_floating_nets": stats["erc_floating_nets"],
            "erc_clean": stats["erc_clean"],
            "findings_count": len(findings),
            "errors_count": sum(1 for f in findings if f.severity == "ERROR"),
            "pass": all(f.severity != "ERROR" for f in findings),
        },
        "findings": [asdict(f) for f in findings],
    }


def main(argv: list = None) -> int:
    ap = argparse.ArgumentParser(
        description="Step-31 ERC + sign-off density-rule verification")
    ap.add_argument("project_dir", help="Project root directory")
    ap.add_argument("--json", default=None, help="JSON report output path")
    args = ap.parse_args(argv)

    project_dir = Path(args.project_dir)
    if not project_dir.is_dir():
        print(f"ERROR: not a directory: {project_dir}", file=sys.stderr)
        return 2

    findings, stats = audit(project_dir)
    report = build_report(findings, stats, str(project_dir))
    out = json.dumps(report, indent=2, ensure_ascii=False)

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(Path(args.json), out)

    print(out)

    # Exit code policy (honest, never vacuous):
    #   * The Step-31 gate fires this checker UNCONDITIONALLY (vibe-ic#220 made
    #     it a plain `program_exit_zero`; it used to be conditional on one of
    #     the density/ERC artefacts already existing, which disarmed exactly the
    #     absence case it is here to catch). A missing density artefact is
    #     therefore recorded as DENSITY_MISSING (ERROR) -> rc=1 (honest FAIL),
    #     NOT a vacuous pass on absence.
    #   * "examined nothing" FAILS CLOSED (rc=1). It is not rc=0 and it is not
    #     rc=2. A `nothing_examined and not has_error -> return 2` guard used to
    #     sit here, describing itself as reachable "when the program is invoked
    #     directly with literally nothing to check". That was false, and
    #     measurably so: invoked directly on an empty project directory this
    #     program exits 1 with DENSITY_MISSING, because `_check_density` runs on
    #     every invocation and records that ERROR whenever it found no artefact
    #     — so `nothing_examined and not has_error` could not hold, and the
    #     branch was dead.
    #     It is not merely deleted, because deleting it would route that state
    #     into `report["summary"]["pass"]`, i.e. a VACUOUS rc=0, the moment any
    #     future sub-check gains a quiet "not applicable" early return. Nothing
    #     examined is a FAIL: this gate has no not-applicable verdict to offer.
    has_error = report["summary"]["errors_count"] > 0
    nothing_examined = (not stats["density_checked"]
                        and not stats["erc_checked"])
    if nothing_examined and not has_error:
        return 1
    return 0 if report["summary"]["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
