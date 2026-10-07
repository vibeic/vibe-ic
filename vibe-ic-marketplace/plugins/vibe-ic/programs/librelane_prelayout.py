#!/usr/bin/env python3
"""Opt-in steps 7, 8 and 10 through LibreLane OpenROAD.CheckSDCFiles + STAPrePNR.

Step 10 (pre-layout multi-corner STA) is the tool's work: STAPrePNR times the
synthesis netlist at every deduplicated STA corner, in its own step directory,
so a pre-layout report can never be re-published as post-route and is re-timed
whenever the netlist it consumes changes (the contract fingerprints it).

What stays vibe-ic's is judging the tool's output:

* step 7 — the spec-derived SDC is still vibe-ic's deck, handed to the tool as
  PNR_SDC_FILE/SIGNOFF_SDC_FILE.  The PVT matrix is derived from the tool's
  own resolved STA_CORNERS, so there is one corner set.  For a design that
  stages no SDC, LibreLane's base.sdc rendered from the same declared clock and
  I/O-delay values is the second arm (`fallback_arm_config`).
* step 8 — OpenSTA's own read_sdc diagnostics (sta.log) and check_setup counts
  (checks.rpt), plus a refusal when the tool timed its FALLBACK_SDC instead of
  the design's deck.  A regex over SDC text cannot see what OpenSTA rejected.
* step 10 — OpenSTA links an absent cell master as a black box and exits 0 with
  the slack of the remaining logic; that slack is refused.  An absent or
  non-finite worst slack is NOT_MEASURED, never 0.

chip-AGNOSTIC: no design, PDK or corner literal selects a branch.  The regular
expressions are OpenSTA's own message grammars.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import math
import re
import sys
from pathlib import Path
from typing import Any, Callable, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _atomic_artefact import write_json  # noqa: E402
from librelane_contract import (Refusal, _load, digest, emit_config,  # noqa: E402
                                resolve_step_config, run_chain)
import instrument_calibration  # noqa: E402

STEPS = ("OpenROAD.CheckSDCFiles", "OpenROAD.STAPrePNR")

#: OpenSTA `link_design` on a master absent from every liberty (Warning 198).
_BLACK_BOX_RE = re.compile(
    r"^Warning \d+: .*?module (\S+) not found\. Creating black box for (\S+)\.\s*$",
    re.M)
#: OpenSTA diagnostics carrying a source file and line: `Warning 366: x.sdc
#: line 2, port 'p' not found.` / `Error 567: x.sdc line 2, ...`.
_FILE_DIAG_RE = re.compile(r"^(Warning|Error) (\d+): (\S+) line (\d+), (.+?)\s*$", re.M)
#: `check_setup` summary lines: `Warning: There are 34 input ports missing
#: set_input_delay.` / `Warning: There is 1 unconstrained endpoint.`
_CHECK_SETUP_RE = re.compile(r"^Warning: There (?:are|is) (\d+) (.+?)\.\s*$", re.M)
_CHECK_SETUP_HEADER_RE = re.compile(r"^check_setup\b.*$", re.M)

#: check_setup categories that leave part of the design untimed.
_CHECK_SETUP_KINDS = (("unconstrained endpoint", "unconstrained_endpoints"),
                      ("set_input_delay", "no_input_delay"),
                      ("set_output_delay", "no_output_delay"),
                      ("no clock", "no_clock"),
                      ("loop", "loops"),
                      ("multiple clock", "multiple_clock"),
                      ("generated clock", "generated_clocks"))

BASIS_NOTE = ("pre-layout basis (Step 10, LibreLane OpenROAD.STAPrePNR) — the "
              "synthesis netlist with NO parasitics and ideal clocks. This is a "
              "PRE-LAYOUT ESTIMATE, NOT post-route sign-off: a corner shown as "
              "MET here may VIOLATE on the routed design")


# ── instruments (each reads OpenSTA's own grammar) ─────────────────────────

def black_boxes(sta_log: str) -> list[dict[str, str]]:
    """Cells OpenSTA replaced by an empty black box while linking."""
    instrument_calibration.assert_calibrated("librelane_prelayout::black_boxes")
    return [{"module": m.group(1), "instance": m.group(2)}
            for m in _BLACK_BOX_RE.finditer(sta_log)]


def sdc_diagnostics(sta_log: str, sdc: Path) -> list[dict[str, Any]]:
    """OpenSTA diagnostics raised while reading THIS constraints file."""
    instrument_calibration.assert_calibrated("librelane_prelayout::sdc_diagnostics")
    found = []
    for m in _FILE_DIAG_RE.finditer(sta_log):
        if Path(m.group(3)).name != sdc.name:
            continue
        found.append({"severity": m.group(1), "id": int(m.group(2)),
                      "line": int(m.group(4)), "message": m.group(5)})
    return found


def check_setup_counts(checks_rpt: str,
                       exclude: frozenset = frozenset()) -> Optional[dict[str, int]]:
    """check_setup findings by kind; None when the section was never written.

    `exclude` names objects that are never timed (the design's supply ports,
    from the resolved VDD/GND declarations). They are subtracted only when the
    `-verbose` listing under the summary line names them; an unlisted count
    stands as reported.
    """
    instrument_calibration.assert_calibrated("librelane_prelayout::check_setup_counts")
    header = _CHECK_SETUP_HEADER_RE.search(checks_rpt)
    if header is None:
        return None
    counts: dict[str, int] = {}
    lines = checks_rpt[header.end():].splitlines()
    for index, line in enumerate(lines):
        m = _CHECK_SETUP_RE.match(line)
        if m is None:
            continue
        text = m.group(2)
        kind = next((name for token, name in _CHECK_SETUP_KINDS if token in text),
                    "other:" + text)
        listed = []
        for follow in lines[index + 1:]:
            if not follow.startswith("  ") or not follow.strip():
                break
            listed.append(follow.strip())
        dropped = sum(1 for name in listed if name in exclude)
        counts[kind] = counts.get(kind, 0) + max(0, int(m.group(1)) - dropped)
    return counts


def supply_names(resolved: dict) -> frozenset:
    """The design's supply ports as the resolved tool config declares them."""
    names = set()
    for key in ("VDD_NETS", "GND_NETS", "VDD_PIN", "GND_PIN"):
        value = resolved.get(key)
        for item in (value if isinstance(value, list) else [value]):
            if isinstance(item, str) and item:
                names.add(item)
    return frozenset(names)


# ── configuration ──────────────────────────────────────────────────────────

def _declared_io_delay_percent(project: Path) -> tuple[Optional[float], str]:
    import declared_clock_period as dcp
    rep = dcp.declared_io_delay_fraction(dcp.docs_in(project / "input" / "docs"))
    if not rep.get("fraction") or rep.get("ambiguous"):
        return None, ""
    return float(rep["percent"]), (f"input/docs I/O-delay declaration "
                                   f"{rep.get('source')}:{rep.get('line')}")


def emit_prelayout_config(project: Path, pdk: str, top: str, sdc: Optional[Path],
                          rtl: list[Path], output: Path,
                          std_cell_library: Optional[str] = None) -> dict:
    """Design fragment for CheckSDCFiles/STAPrePNR; every key carries a source.

    `sdc=None` builds the base.sdc arm: no PNR_SDC_FILE, and the declared I/O
    delay is mapped onto IO_DELAY_CONSTRAINT so the tool renders it.
    """
    config = emit_config(project, pdk, output)
    sources = _load(output.with_suffix(".provenance.json"))
    for key in [k for k in config if k.startswith("PAD_") or k in (
            "DIE_AREA", "CORE_AREA", "FP_SIZING", "VERILOG_FILES",
            "PNR_SDC_FILE", "SIGNOFF_SDC_FILE")]:
        config.pop(key)
        sources.pop(key, None)
    config["DESIGN_NAME"] = top
    sources["DESIGN_NAME"] = "phase3_one_shot_runner resolved ASIC top (synthesis netlist top)"
    config["PDK"] = pdk
    sources["PDK"] = "resolved PDK supplied by phase3_one_shot_runner"
    if std_cell_library:
        config["STD_CELL_LIBRARY"] = std_cell_library
        sources["STD_CELL_LIBRARY"] = "resolved liberty library supplied by phase3_one_shot_runner"
    config["VERILOG_FILES"] = [str(p.resolve()) for p in rtl]
    sources["VERILOG_FILES"] = "phase2/stage1/rtl design sources (config schema requirement; STA reads the state netlist)"
    if sdc is not None:
        for key in ("PNR_SDC_FILE", "SIGNOFF_SDC_FILE"):
            config[key] = str(sdc.resolve())
            sources[key] = "step 7 spec-derived SDC (phase3/stage3/pnr/constraint.sdc)"
    else:
        percent, where = _declared_io_delay_percent(project)
        if percent is not None:
            config["IO_DELAY_CONSTRAINT"] = percent
            sources["IO_DELAY_CONSTRAINT"] = where
    write_json(output, config)
    write_json(output.with_suffix(".provenance.json"), sources)
    return config


def run_prelayout(project: Path, image: str, pdk: str, top: str, netlist: Path,
                  sdc: Optional[Path], rtl: list[Path], *, arm: str = "design_sdc",
                  std_cell_library: Optional[str] = None,
                  mounts: Optional[list[tuple[Path, str]]] = None,
                  pdk_root: str) -> Path:
    """Run CheckSDCFiles -> STAPrePNR on `netlist`; return the STAPrePNR folder."""
    if not netlist.is_file():
        raise Refusal("LL_PRELAYOUT_NETLIST_MISSING", f"no netlist file at {netlist}")
    if sdc is not None and not sdc.is_file():
        raise Refusal("LL_PRELAYOUT_SDC_MISSING", f"no SDC file at {sdc}")
    root = project / "phase3/librelane/prelayout-config" / arm
    root.mkdir(parents=True, exist_ok=True)
    config = emit_prelayout_config(project, pdk, top, sdc, rtl, root / "design.json",
                                   std_cell_library)
    resolved = {}
    for step_id in STEPS:
        raw = root / f"{step_id}.json"
        write_json(raw, {**config, "meta": {"step": step_id}})
        resolved[step_id] = resolve_step_config(
            project, image, raw, root / f"{step_id}.resolved.json",
            mounts=mounts, pdk_root=pdk_root)
    state = root / "state_in.json"
    write_json(state, {"nl": str(netlist.resolve())})
    folders = run_chain(project, image, [(s, resolved[s], state) for s in STEPS],
                        mounts=mounts, pdk_root=pdk_root, namespace=f"prelayout/{arm}")
    return folders[-1]


def _corners(folder: Path) -> list[Path]:
    return sorted(p for p in folder.iterdir() if p.is_dir() and (p / "sta.log").is_file())


# ── step 7: PVT matrix from the tool's own corner set ──────────────────────

def pvt_matrix_from_sta_corners(resolved: dict, folder: Optional[Path],
                                classify: Callable[[str], str]) -> dict:
    corners = resolved.get("STA_CORNERS") or []
    libs = resolved.get("CELL_LIBS") or resolved.get("LIB") or {}
    rows = []
    for name in corners:
        match = [lib for pattern, group in libs.items() if fnmatch.fnmatch(name, pattern)
                 for lib in (group if isinstance(group, list) else [group])]
        rows.append({"name": name, "label": classify(name),
                     "liberty": match[0] if len(match) == 1 else match})
    timed = [p.name for p in _corners(folder)] if folder else []
    return {"version": "1.0", "corners": rows, "modes": ["functional"],
            "primary_corner": resolved.get("DEFAULT_CORNER"),
            "corner_source": "LibreLane resolved STA_CORNERS/DEFAULT_CORNER (PDK config)",
            "prelayout_timed_corners": timed,
            "notes": ("Corner set is the tool's resolved STA_CORNERS; STAPrePNR "
                      "deduplicates corners that differ only in parasitics, so "
                      "pre-layout times prelayout_timed_corners.")}


# ── step 8: OpenSTA's verdict on the SDC ───────────────────────────────────

def judge_sdc(folder: Path, resolved: dict, declared_sdc: Optional[Path],
              output: Path) -> dict:
    corners = _corners(folder)
    sdc_used = resolved.get("PNR_SDC_FILE")
    fallback = resolved.get("FALLBACK_SDC")
    findings: list[str] = []
    verdict = "PASS"
    per_corner: dict[str, Any] = {}
    if not corners:
        verdict = "NOT_MEASURED"
        findings.append("LL_STA_NO_CORNER: STAPrePNR wrote no corner directory")
    if declared_sdc is not None and (not sdc_used or Path(sdc_used).resolve()
                                     != declared_sdc.resolve()):
        verdict = "FAIL"
        findings.append(f"LL_SDC_NOT_DESIGN_DECK: timed {sdc_used or fallback!r}, "
                        f"not the design deck {declared_sdc}")
    if declared_sdc is None or not sdc_used:
        # The tool timed base.sdc.  That is the fallback arm's evidence, not a
        # sign-off deck for the design.
        findings.append(f"LL_SDC_FALLBACK: FALLBACK_SDC {fallback} was timed")
        if verdict == "PASS":
            verdict = "FAIL"
    deck = Path(sdc_used) if sdc_used else Path(str(fallback or "base.sdc"))
    for corner in corners:
        log = (corner / "sta.log").read_text(errors="replace")
        diags = sdc_diagnostics(log, deck)
        checks_path = corner / "checks.rpt"
        counts = (check_setup_counts(checks_path.read_text(errors="replace"),
                                     supply_names(resolved))
                  if checks_path.is_file() else None)
        per_corner[corner.name] = {"sdc_diagnostics": diags, "check_setup": counts}
        if counts is None:
            findings.append(f"{corner.name}: check_setup section absent — NOT_MEASURED")
            if verdict == "PASS":
                verdict = "NOT_MEASURED"
            continue
        if diags:
            verdict = "FAIL"
            findings.append(f"{corner.name}: {len(diags)} OpenSTA diagnostic(s) on "
                            f"{deck.name}: " + "; ".join(
                                f"{d['severity']} {d['id']} line {d['line']}: {d['message']}"
                                for d in diags[:3]))
        untimed = {k: v for k, v in counts.items() if v}
        if untimed:
            verdict = "FAIL"
            findings.append(f"{corner.name}: check_setup {untimed}")
    state = _load(folder / "state_out.json")
    netlist = Path(str(state.get("nl") or ""))
    report = {"step": "8", "program": "librelane_prelayout.judge_sdc",
              "netlist": str(netlist),
              "netlist_sha256": digest(netlist) if netlist.is_file() else None,
              "verdict": verdict, "sdc": str(deck),
              "excluded_supply_endpoints": sorted(supply_names(resolved)),
              "sdc_sha256": digest(deck) if deck.is_file() else None,
              "fallback_sdc": fallback, "corners": per_corner,
              "findings": findings, "source": str(folder / "state_out.json"),
              "state_out_sha256": digest(folder / "state_out.json")}
    write_json(output, report)
    return report


# ── step 10: slack only from a fully linked design ─────────────────────────

def _finite(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def judge_slack(folder: Path, output: Path) -> dict:
    state = _load(folder / "state_out.json")
    metrics = state.get("metrics", {})
    corners = _corners(folder)
    rows: dict[str, Any] = {}
    verdict = "PASS" if corners else "NOT_MEASURED"
    findings = [] if corners else ["LL_STA_NO_CORNER: STAPrePNR wrote no corner directory"]
    for corner in corners:
        boxes = black_boxes((corner / "sta.log").read_text(errors="replace"))
        row: dict[str, Any] = {"black_boxes": boxes}
        for check in ("setup", "hold"):
            raw = metrics.get(f"timing__{check}__ws__corner:{corner.name}")
            value = _finite(raw)
            row[f"{check}_ws"] = ({"status": "MEASURED", "value": value}
                                  if value is not None else
                                  {"status": "NOT_MEASURED", "raw": repr(raw)})
            if value is None and verdict == "PASS":
                verdict = "NOT_MEASURED"
                findings.append(f"{corner.name}: {check} worst slack {raw!r} — NOT_MEASURED, not 0")
        if boxes:
            verdict = "FAIL"
            findings.append(f"LL_STA_BLACK_BOX: {corner.name} linked {len(boxes)} "
                            f"black box(es) ({boxes[0]['module']} for {boxes[0]['instance']}); "
                            "its slack omits that logic")
        rows[corner.name] = row
    report = {"step": "10", "program": "librelane_prelayout.judge_slack",
              "verdict": verdict, "basis": "PRE_LAYOUT_ESTIMATE", "corners": rows,
              "findings": findings, "source": str(folder / "state_out.json"),
              "state_out_sha256": digest(folder / "state_out.json")}
    write_json(output, report)
    return report


def compose_corner_reports(folder: Path, out_dir: Path,
                           classify: Callable[[str], str]) -> dict[str, Path]:
    """Publish STAPrePNR corner reports under the step-10 per-corner names.

    The body is the tool's own path tables; the summary lines transcribe its
    metrics; the basis is stamped PRE_LAYOUT so sta_report_check scopes it.
    """
    state = _load(folder / "state_out.json")
    metrics = state.get("metrics", {})
    resolved = _load(folder / "config.json") if (folder / "config.json").is_file() else {}
    libs = resolved.get("CELL_LIBS") or resolved.get("LIB") or {}
    out_dir.mkdir(parents=True, exist_ok=True)
    chosen: dict[str, Path] = {}
    for corner in _corners(folder):
        label = classify(corner.name)
        if label in chosen and not corner.name.startswith("nom"):
            continue
        chosen[label] = corner
    written = {}
    for label, corner in chosen.items():
        parts = []
        for name in ("max.rpt", "min.rpt"):
            if (corner / name).is_file():
                parts.append((corner / name).read_text(errors="replace"))
        summary = []
        for sense, check in (("max", "setup"), ("min", "hold")):
            tns = metrics.get(f"timing__{check}__tns__corner:{corner.name}")
            wns = metrics.get(f"timing__{check}__wns__corner:{corner.name}")
            ws = metrics.get(f"timing__{check}__ws__corner:{corner.name}")
            if _finite(tns) is not None:
                summary.append(f"tns {sense} {tns:.2f}")
            if _finite(wns) is not None:
                summary.append(f"wns {sense} {wns:.2f}")
            if _finite(ws) is not None:
                summary.append(f"worst slack {sense} {ws:.2f}")
        liberty = [lib for pattern, group in libs.items()
                   if fnmatch.fnmatch(corner.name, pattern)
                   for lib in (group if isinstance(group, list) else [group])]
        if len(liberty) == 1:
            summary.append(f"STA_BASIS_LIBERTY: {liberty[0]}")
        if state.get("nl"):
            summary.append(f"STA_BASIS_NETLIST: {state['nl']}")
        path = out_dir / f"sta_{label}.rpt"
        path.write_text("\n".join(parts) + "\n" + "\n".join(summary) + "\n"
                        "STA_BASIS: PRE_LAYOUT_ESTIMATE\n"
                        f"STA_BASIS_NOTE: {BASIS_NOTE}\n"
                        f"STA_SOURCE: LibreLane OpenROAD.STAPrePNR {corner}\n")
        written[label] = path
    return written


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("judge-sdc", "judge-slack"):
        cmd = sub.add_parser(name)
        cmd.add_argument("folder", type=Path, help="STAPrePNR step directory")
        cmd.add_argument("--json", type=Path, required=True)
        if name == "judge-sdc":
            cmd.add_argument("--resolved", type=Path, required=True)
            cmd.add_argument("--sdc", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "judge-sdc":
            report = judge_sdc(args.folder, _load(args.resolved), args.sdc, args.json)
        else:
            report = judge_slack(args.folder, args.json)
    except (Refusal, OSError, ValueError) as exc:
        print(f"[NOT_MEASURED] {exc}")
        return 2
    print(f"[{report['verdict']}] " + "; ".join(report["findings"][:4]))
    return {"PASS": 0, "FAIL": 1}.get(report["verdict"], 2)


if __name__ == "__main__":
    sys.exit(main())
