#!/usr/bin/env python3
"""One-time migration of the old registry into the editable native step table."""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def slug(title):
    return re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")


def generate(registry, native):
    steps, dropped, unresolved = [], [], []
    known = native["steps"]
    for row in registry["rows"]:
        name = slug(row["name"])
        profiles = []
        for profile in row["profiles"]:
            dispatch = profile.get("dispatch", {})
            selected = [s for s in profile.get("native_steps", []) if s in known]
            overrides = native["runs"].get(name)
            if overrides:
                selected = overrides.get(profile["select_when"], selected)
            if selected:
                tool = {"kind": "librelane", "steps": selected}
            else:
                producer = dispatch.get("producer", "")
                parts = producer.split(":", 1)
                program = parts[0] if parts[0].endswith(".py") else next(
                    (s + ".py" for s in row.get("source_components", []) if (ROOT / "programs" / (s + ".py")).is_file()), None)
                tool = {"kind": "adapter", "program": program,
                        "function": parts[1] if len(parts) == 2 else None,
                        "gap": "Native invocation must be adapted without the old acceptance wrappers."}
                if name in native.get("adapters", {}):
                    tool = {"kind": "adapter", **native["adapters"][name]}
            if profile["select_when"] == "otherwise":
                for condition, replacement in native.get("profile_tools", {}).get(name, {}).items():
                    profiles.append({"when": condition, "tool": replacement})
                if name in native.get("report_rows", {}):
                    tool = {"kind": "native_report", "from": native["report_rows"][name]}
            profiles.append({"when": profile["select_when"], "tool": tool})

        checks = []
        for profile in profiles:
            for step in profile["tool"].get("steps", []):
                for check in native.get("checks", {}).get(step, []):
                    item = {**check, "when": profile["when"]}
                    if item not in checks:
                        checks.append(item)
        checks.extend(native.get("row_checks", {}).get(name, []))

        remaining = []
        for obligation in row["obligations"]:
            metric = obligation["metric"]
            operator = obligation["expectation"]["operator"]
            reason = None
            if operator == "matches_adopted_reference":
                reason = "Adopted-reference comparison removed by the owner."
            elif re.search(r"identity|binding|qualification|stale|adoption|approval", metric):
                reason = "Only identity, binding, adoption, or qualification content."
            elif metric in native.get("deleted_metrics", []):
                reason = native["deleted_metrics"][metric]
            if reason:
                dropped.append({"step": name, "metric": metric, "operator": operator, "reason": reason})
            else:
                remaining.append(metric)
        if not checks:
            checks = [{"metric": metric, "operator": None, "limit": None,
                       "source": None, "decision_request": "No numeric native limit found in the current implementation."}
                      for metric in remaining]
            if not checks:
                checks = [{"metric": "native_measurement", "operator": None, "limit": None,
                           "source": None, "decision_request": "This step has no numeric native limit."}]
            unresolved.extend({"step": name, "metric": c["metric"], "reason": c["decision_request"]} for c in checks)
        tool = profiles[0]["tool"] if len(profiles) == 1 else {"kind": "profiles", "profiles": profiles}
        item = {"name": name, "title": row["name"], "when": row["when"], "tool": tool,
                "checks": checks, "legacy_id": {"registry": row["id"],
                "native": list(dict.fromkeys(str(r["id"]) for r in row.get("legacy70", [])))}}
        steps.append(item)
    return {"predicates": registry["predicate_definitions"],
            "implications": registry["feature_implications"],
            "exclusions": registry["feature_exclusions"], "steps": steps}, dropped, unresolved


def write_tsv(path, rows, fields):
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fields, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=ROOT / "flow" / "flow109.json")
    parser.add_argument("--native", type=Path, default=ROOT / "flow" / "native_limits.json")
    parser.add_argument("--output", type=Path, default=ROOT / "flow" / "steps.json")
    parser.add_argument("--reports", type=Path)
    args = parser.parse_args()
    table, dropped, unresolved = generate(json.loads(args.registry.read_text()), json.loads(args.native.read_text()))
    args.output.write_text(json.dumps(table, indent=2) + "\n")
    if args.reports:
        args.reports.mkdir(parents=True, exist_ok=True)
        write_tsv(args.reports / "DROPPED.tsv", dropped, ["step", "metric", "operator", "reason"])
        write_tsv(args.reports / "DECISION_REQUESTS.tsv", unresolved, ["step", "metric", "reason"])
        rows = [{"step": s["name"], "metric": c["metric"], "operator": c["operator"],
                 "limit": json.dumps(c["limit"]), "source": json.dumps(c["source"])}
                for s in table["steps"] for c in s["checks"]]
        write_tsv(args.reports / "LIMITS.tsv", rows, ["step", "metric", "operator", "limit", "source"])
    print(f"Wrote {len(table['steps'])} steps; dropped {len(dropped)} wrapper obligations; {len(unresolved)} unresolved limits.")


if __name__ == "__main__":
    main()
