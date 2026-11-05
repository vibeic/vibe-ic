"""Invoke the existing diagnostic injection producer and read its measurements."""
import json
import time
from types import SimpleNamespace


def injection(project, directory, tool):
    from flow_native_adapters import Commands
    import _fmeda_mechanisms as mechanisms
    import fmeda_fault_injection_coverage as producer

    manifest = project / mechanisms.MANIFEST
    if not manifest.is_file():
        return Commands(directory).result(detail="No produced FMEDA engineering mechanism input; diagnostic injection is unmeasured.")
    data = json.loads(manifest.read_text())
    options = SimpleNamespace(asil=tool.get("asil", data.get("asil", "D")),
        min_dc=tool.get("min_dc", data.get("min_dc")), max_vectors=tool.get("max_vectors", 64),
        enc_module=None, dec_module=None)
    started = time.perf_counter()
    code, report = producer.run(project, options)
    output = directory / "fmeda_coverage.json"
    canonical = producer._report_path(project, None)
    for path in (output, canonical):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2) + "\n")
    metrics = {}
    rows = report.get("mechanisms", [])
    if len(rows) == 1 and rows[0].get("measured"):
        metrics = {key: rows[0][key] for key in ("injected_faults", "detected_faults",
                   "diagnostic_coverage_pct", "baseline_valid", "per_site_total", "per_site_covered")}
    elif rows:
        metrics["mechanisms"] = rows
    reports = [str(output), str(canonical), *report.get("native_hierarchy", {}).get("reports", [])]
    reports.extend(str(project / row["raw_evidence"]["path"]) for row in rows)
    status = report["verdict"]
    return {"ran": True, "exit_code": code, "metrics": metrics, "reports": reports,
            "tool_seconds": time.perf_counter() - started,
            "native_steps": [{"name": "fmeda_fault_injection_coverage", "ran": True,
                              "exit_code": code, "status": status}],
            "detail": report.get("reason", "") + " Whole required-fault population and diagnostic latency have no native measurement."}
