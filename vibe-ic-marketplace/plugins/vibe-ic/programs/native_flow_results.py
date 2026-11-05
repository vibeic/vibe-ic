#!/usr/bin/env python3
"""Read one native LibreLane run through the shared CSV mapping, without rejudging metrics."""
from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from pathlib import Path

_NATIVE_ID = re.compile(r"\b(?:Checker|OpenROAD|Yosys|Verilator|Odb|Magic|KLayout|Netgen|Vibeic)\.[A-Za-z][A-Za-z0-9]*")


def collect(run_dir: Path, mapping: Path, *, returncode: int,
            accepted_ids=(), features=None) -> dict:
    run_dir = Path(run_dir)
    folders = sorted((p for p in run_dir.iterdir()
                      if p.is_dir() and re.match(r"\d+-", p.name)),
                     key=lambda p: int(p.name.split("-", 1)[0]))
    deferred_failures = set()
    current = None
    log_file = run_dir / "flow.log"
    for line in log_file.read_text(errors="replace").splitlines() if log_file.exists() else []:
        match = re.search(r"Running '([^']+)' at", line)
        if match:
            current = match[1]
        if " - deferred" in line and current:
            deferred_failures.add(current)
    operations = []
    case_name = None
    for folder in folders:
        config_file = folder / "config.json"
        if not config_file.is_file():
            continue
        config = json.loads(config_file.read_text())
        case_name = config.get("DESIGN_NAME", case_name)
        identity = config.get("meta", {}).get("step")
        if not identity:
            continue
        state_file = folder / "state_out.json"
        state = json.loads(state_file.read_text()) if state_file.is_file() else None
        operations.append({"native_step": identity, "folder": str(folder),
                           "status": ("FAIL" if identity in deferred_failures else
                                      "PASS" if state is not None else "NOT_RUN"),
                           "metrics": (state or {}).get("metrics", {}),
                           "config": str(config_file),
                           "scope": "Native step completion; native checkers own all thresholds."})
    # Missing State stays NOT_RUN except an attempted failure; rc0 supplies no PASS.
    incomplete = next((v for v in reversed(operations) if v["status"] == "NOT_RUN"), None)
    if returncode not in (0, 130, 137, 143) and incomplete is not None:
        incomplete["status"] = "FAIL"
    failed = next((v for v in operations if v["status"] == "FAIL"), None)
    by_id = {}
    for operation in operations:
        by_id.setdefault(operation["native_step"], []).append(operation)
    rows = []
    with Path(mapping).open(newline="", encoding="utf-8-sig") as stream:
        for mapped in csv.DictReader(stream):
            ids = list(dict.fromkeys(_NATIVE_ID.findall(mapped["native"])))
            sources = [item for identity in ids for item in by_id.get(identity, [])]
            missing = [identity for identity in ids if identity not in by_id]
            status = ("FAIL" if any(x["status"] == "FAIL" for x in sources)
                      else "PASS" if ids and not missing and sources
                      and all(x["status"] == "PASS" for x in sources)
                      else "NOT_RUN")
            applicable = None
            if features is not None:
                from flow_engine import predicate
                try:
                    applicable = predicate(mapped["when"], features)
                except (ValueError, KeyError, SyntaxError):
                    applicable = None
                if applicable is not True:
                    status = "NOT_RUN"
            rows.append({"applicable": applicable, "step": mapped["id"], "name": mapped["name"],
                         "case": case_name, "config": str(run_dir / "resolved.json"),
                         "log": str(log_file),
                         "metrics": {x["native_step"]: x["metrics"] for x in sources},
                         "status": status, "native_steps": ids,
                         "missing_native_steps": missing, "sources": sources,
                         "already_accepted": mapped["id"] in accepted_ids,
                         "scope": "Native sources in CSV only; required timing, final-geometry, and external obligations retain the mapping scope.",
                         "mapping_action": mapped["action"],
                         "global_acceptance_promoted": False})
    return {"run": str(run_dir), "returncode": returncode,
            "counts": dict(Counter(row["status"] for row in rows)),
            "native_operation_counts": dict(Counter(x["status"] for x in operations)),
            "first_native_failure": failed if failed and failed["status"] == "FAIL" else None,
            "new_ic_or_dxx_specific_adapter_lines": 0,
            "whole_ic_acceptance": "NOT_CLAIMED", "rows": rows}


def main():
    from _atomic_artefact import write_json
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("mapping", type=Path)
    parser.add_argument("--returncode", type=int, required=True)
    parser.add_argument("--accepted-ledger", type=Path)
    parser.add_argument("--selection", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--rows-dir", type=Path)
    args = parser.parse_args()
    ledger = json.loads(args.accepted_ledger.read_text()) if args.accepted_ledger else {}
    selection = json.loads(args.selection.read_text()) if args.selection else {}
    result = collect(args.run_dir, args.mapping, returncode=args.returncode,
                     accepted_ids=ledger.get("pass_ids", []),
                     features=selection.get("features") if args.selection else None)
    write_json(args.output, result, ensure_ascii=True)
    if args.rows_dir:
        args.rows_dir.mkdir(parents=True, exist_ok=True)
        for row in result["rows"]:
            write_json(args.rows_dir / (row["step"] + ".json"), row, ensure_ascii=True)
    print(json.dumps({key: result[key] for key in ("counts", "native_operation_counts")}))


if __name__ == "__main__":
    main()
