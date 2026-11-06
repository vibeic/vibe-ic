"""Read OpenSTA's existing reports for the native flow selector."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

import librelane_prelayout as native


_SDC_READ = re.compile(r"^Reading design constraints file at '([^']+)'", re.M)


def _sdc_findings(log: str, configured: set[str]):
    sources = set(_SDC_READ.findall(log))
    if not sources or not sources <= configured:
        return None
    selected = {Path(source) for source in sources}
    names = {source.name for source in selected}
    lines = []
    for match in native._FILE_DIAG_RE.finditer(log):
        path = Path(match.group(3))
        if path in selected or (path.parent == Path(".") and path.name in names):
            lines.append(match.group(0))
    filtered = "\n".join(lines)
    return [item for name in sorted(names)
            for item in native.sdc_diagnostics(filtered, Path(name), calibrate=False)]


def read_sta_reports(directory: Path, config: dict, *, project: Path | None = None) -> dict:
    """Sum native corner diagnostics, omitting metrics whose reports are missing."""
    directory = Path(directory)
    reports, details = [], []
    ports, observations = {}, []
    if project is not None:
        path = Path(project) / "phase1/generated_docs/L9_INTEGRATION_SPEC.json"
        if path.is_file():
            reports.append(str(path))
            body = json.loads(path.read_text())
            hierarchy = body["fields"] if isinstance(body.get("fields"), dict) else {}
            rows = (body.get("top_ports") or hierarchy.get("top_ports")
                    or body.get("ports") or hierarchy.get("ports") or [])
            ports = {p["name"]: p for p in rows
                     if p.get("timing_class") in {"asynchronous", "unused"}
                     and p.get("timing_class_sources")}
    resolved = dict(config)
    state = {}
    output = {}
    metadata_complete = True
    for filename in ("config.json", "state_in.json", "state_out.json"):
        path = directory / filename
        if not path.is_file():
            continue
        reports.append(str(path))
        try:
            body = json.loads(path.read_text())
            if not isinstance(body, dict):
                raise ValueError("native metadata is not an object")
            if filename == "config.json":
                resolved.update(body)
            elif filename == "state_in.json":
                state = body
            else:
                output = body
        except (OSError, ValueError, TypeError) as exc:
            metadata_complete = False
            details.append(f"Native {filename} could not be read: {exc}")
    configured = {str(value) for value in (
        resolved.get("PNR_SDC_FILE"), resolved.get("SIGNOFF_SDC_FILE"),
        resolved.get("FALLBACK_SDC"), state.get("sdc")) if value}
    reported_corners = {key.split("__corner:", 1)[1] for key in output.get("metrics", {})
                        if key.startswith("timing__setup__ws__corner:")}
    population_known = metadata_complete and (bool(reported_corners) or not resolved.get("STA_CORNERS"))
    if not population_known:
        details.append("Native output has not reported its deduplicated timing-corner population.")
    corners = sorted({path.parent for pattern in ("*/checks.rpt", "*/sta.log")
                      for path in directory.glob(pattern)} | {directory / name for name in reported_corners})
    counts, diagnostics = [], []
    for corner in corners:
        texts = {}
        for filename in ("checks.rpt", "sta.log"):
            path = corner / filename
            if path.is_file():
                reports.append(str(path))
                texts[filename] = path.read_text(errors="replace")
        found = None
        for filename in ("checks.rpt", "sta.log"):
            if filename in texts:
                found = native.check_setup_counts(texts[filename], native.supply_names(resolved),
                                                  calibrate=False)
                if found is not None:
                    for kind, count, listed in native.check_setup_sections(texts[filename]):
                        if kind not in {"no_input_delay", "no_output_delay", "unconstrained_endpoints"}:
                            continue
                        removed = []
                        for name in listed:
                            base = re.fullmatch(r"([A-Za-z_]\w*)(?:\[-?\d+\])*", name)
                            port = ports.get(base[1]) if base else None
                            if port is not None and name not in native.supply_names(resolved):
                                removed.append(name)
                                observations.append({"kind": "documented_port_timing", "port": name,
                                    "timing_class": port["timing_class"], "sources": port["timing_class_sources"],
                                    "corner": corner.name, "finding": kind, "status": "NOT_APPLICABLE"})
                        found[kind] -= min(count, len(removed))
                    break
        if found is None:
            details.append(f"{corner.name}: native check_setup section is missing.")
        else:
            counts.append(found)
        findings = (_sdc_findings(texts["sta.log"], configured)
                    if "sta.log" in texts and metadata_complete else None)
        if findings is None or found is None:
            details.append(f"{corner.name}: complete diagnostics for the native SDC source are missing.")
        else:
            diagnostics.append(findings)
    metrics = {}
    if population_known and corners and len(counts) == len(corners):
        metrics["unconstrained_endpoints"] = sum(c.get("unconstrained_endpoints", 0) for c in counts)
        metrics["unconstrained_required_paths"] = sum(sum(c.values()) for c in counts)
    if population_known and corners and len(diagnostics) == len(corners):
        metrics["invalid_timing_exceptions"] = sum(map(len, diagnostics))
    if not corners:
        details.append("No native STA corner reports exist.")
    details.insert(0, f"Read {len(corners)} native STA corners; check_setup {len(counts)}/{len(corners)}, "
                      f"SDC diagnostics {len(diagnostics)}/{len(corners)}.")
    return {"metrics": metrics, "reports": reports, "detail": " ".join(details),
            "observations": observations}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--project", type=Path)
    args = parser.parse_args()
    result = read_sta_reports(args.directory, json.loads(args.config.read_text()) if args.config else {},
                              project=args.project)
    print(json.dumps(result, indent=2))
