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
    steps, dropped, unmeasured = [], [], []
    known = native["steps"]
    for row in registry["rows"]:
        name = slug(row["name"])
        profiles, replaced_checks = [], []
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
            replacements = native.get("profile_tools", {}).get(name, {})
            if profile["select_when"] in replacements:
                replaced_checks.append({"when": profile["select_when"], "tool": tool})
                tool = replacements[profile["select_when"]]
            if profile["select_when"] == "otherwise":
                existing = {item["select_when"] for item in row["profiles"]}
                for condition, replacement in native.get("profile_tools", {}).get(name, {}).items():
                    if condition not in existing:
                        profiles.append({"when": condition, "tool": replacement})
                if name in native.get("report_rows", {}):
                    tool = {"kind": "native_report", "from": native["report_rows"][name]}
                    if name in native.get("report_scopes", {}):
                        tool["scope"] = native["report_scopes"][name]
                readers = native.get("report_check_readers", {}).get(name)
                if readers:
                    tool["check_readers"] = readers
            profiles.append({"when": profile["select_when"], "tool": tool})

        checks = []
        for profile in replaced_checks + profiles:
            for step in profile["tool"].get("steps", []):
                for check in native.get("checks", {}).get(step, []):
                    item = {**check, "when": profile["when"]}
                    if item not in checks:
                        checks.append(item)
        checks.extend(native.get("row_checks", {}).get(name, []))

        for obligation in row["obligations"]:
            metric = obligation["metric"]
            operator = obligation["expectation"]["operator"]
            reason = None
            if operator == "matches_adopted_reference":
                reason = "Adopted-reference comparison removed by the owner."
            elif metric in native.get("deleted_metrics", []):
                reason = native["deleted_metrics"][metric]
            if reason:
                dropped.append({"step": name, "metric": metric, "operator": operator, "reason": reason})
                continue
            if any(c["metric"] == metric for c in checks):
                continue
            expectation = obligation["expectation"]
            check = {"metric": metric, "operator": operator, "limit": None,
                     "when": obligation.get("when", row["when"]),
                     "source": native.get("operator_sources", {}).get(name + "." + metric,
                                                                           native.get("operator_source", {}))}
            if operator == "eq":
                check.update(operator="==", limit=expectation["value"], unit=expectation.get("unit"))
            elif operator == "covers_all":
                check["required_from"] = native.get("required_sets", {}).get(metric, {
                    "kind": "design_or_tool_population", "metric": metric})
            elif operator == "within_declared_bounds":
                check["limit_from"] = native.get("declared_bounds", {}).get(metric, {
                    "kind": "design_or_pdk", "metric": metric})
            checks.append(check)
        for check in checks:
            if check["limit"] is None:
                unmeasured.append({"step": name, "metric": check["metric"], "operator": check["operator"],
                                   "required_source": json.dumps(check.get("required_from", check.get("limit_from", {}))),
                                   "searched_sources": json.dumps(native.get("searched_sources", {}).get(name, []))})
        tool = profiles[0]["tool"] if len(profiles) == 1 else {"kind": "profiles", "profiles": profiles}
        item = {"name": name, "title": row["name"], "when": row["when"], "tool": tool,
                "checks": checks, "legacy_id": {"registry": row["id"],
                "native": list(dict.fromkeys(str(r["id"]) for r in row.get("legacy70", [])))}}
        steps.append(item)
    return {"predicates": registry["predicate_definitions"],
            "implications": registry["feature_implications"],
            "exclusions": registry["feature_exclusions"],
            "feature_defaults": native.get("feature_defaults", {}), "steps": steps}, dropped, unmeasured


def write_tsv(path, rows, fields):
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fields, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def classify_checks(table, native):
    """Apply the owner-reviewed migration facts to the complete generated table."""
    mapping, dropped, work = [], [], []
    for row in table["steps"]:
        facts = native["check_classifications"][row["name"]]
        checks = row["checks"]
        if [c["metric"] for c in checks] != [f["old_name"] for f in facts]:
            raise ValueError(f"Reclassify the changed checks in {row['name']}")
        retained, observations = [], []
        for check, fact in zip(checks, facts):
            if fact.get("when"):
                check = {**check, "when": fact["when"]}
            category = fact["class"]
            if category not in {"N", "X", "D", "T", "R", "P"}:
                raise ValueError(f"Unknown check class {category}")
            names = fact.get("native_metrics", [])
            entry = {"step": row["name"], "old_name": check["metric"], "class": category,
                     "new_native_name_or_reason": ", ".join(names) or fact["reason"],
                     "limit": json.dumps(check["limit"]), "source": json.dumps(check["source"])}
            mapping.append(entry)
            if category == "N":
                if not names:
                    raise ValueError(f"Native metric missing for {row['name']}.{check['metric']}")
                item = dict(check)
                if check["operator"] == "covers_all":
                    if not fact.get("native_population"):
                        raise ValueError(f"Native population report missing for {row['name']}.{check['metric']}")
                    item["required_from"] = {"kind": "native_tool_population",
                                             "tool": fact["native_population"]}
                retained.extend({**item, "metric": name} for name in names)
            elif category == "T":
                retained.append({**check, "tool_gap": fact["reason"]})
                if check["operator"] == "covers_all":
                    if not fact.get("native_population"):
                        raise ValueError(f"Native population report missing for {row['name']}.{check['metric']}")
                    retained[-1]["required_from"] = {"kind": "native_tool_population",
                                                     "tool": fact["native_population"]}
                work.append({"step": row["name"], "old_name": check["metric"],
                             "tool_and_work": fact["reason"]})
            elif category == "R":
                observations.append({"metric": check["metric"], "native_metrics": names,
                                     "source": check["source"], "reason": fact["reason"],
                                     "declared_limit_from": check.get("limit_from", {})})
                for key in ("operator", "limit", "limit_config", "when"):
                    if key in check:
                        observations[-1][key] = check[key]
                if fact.get("native_report_numbers"):
                    observations[-1]["native_report_numbers"] = fact["native_report_numbers"]
            elif category == "P":
                dropped.append({"step": row["name"], "old_name": check["metric"],
                                "class": category, "what_still_protects": fact["reason"]})
        row["checks"] = retained
        if row["name"] in native.get("tool_overrides", {}):
            row["tool"] = native["tool_overrides"][row["name"]]
        if observations:
            row["observations"] = observations
        if row["name"] in native.get("row_applicability", {}):
            selection = native["row_applicability"][row["name"]]
            row["when"] = selection["when"]
            row["applicability_reason"] = selection["reason"]
            if "merged_into" in selection:
                row["merged_into"] = selection["merged_into"]
    steps = table["steps"]
    for row in reversed(steps.copy()):
        source = native.get("report_rows", {}).get(row["name"])
        if source:
            producer = next(item for item in steps if item["name"] == source)
            if steps.index(row) < steps.index(producer):
                steps.remove(row)
                steps.insert(steps.index(producer) + 1, row)
    return mapping, dropped, work


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=ROOT / "flow" / "flow109.json")
    parser.add_argument("--native", type=Path, default=ROOT / "flow" / "native_limits.json")
    parser.add_argument("--output", type=Path, default=ROOT / "flow" / "steps.json")
    parser.add_argument("--reports", type=Path)
    args = parser.parse_args()
    raw = args.registry.read_text()
    registry, native = json.loads(raw), json.loads(args.native.read_text())
    native["operator_sources"] = {}
    for row in registry["rows"]:
        start = raw.find('"name": ' + json.dumps(row["name"]))
        for item in row["obligations"]:
            position = raw.find('"metric": ' + json.dumps(item["metric"]), start)
            position = raw.find('"operator":', position)
            if item["expectation"]["operator"] == "eq":
                position = raw.find('"value":', position)
            native["operator_sources"][slug(row["name"]) + "." + item["metric"]] = {
                "file": str(args.registry.relative_to(ROOT)) if args.registry.is_relative_to(ROOT) else str(args.registry),
                "line": raw.count("\n", 0, position) + 1}
    table, dropped, unmeasured = generate(registry, native)
    classifications = []
    if "check_classifications" in native:
        classifications, paper, work = classify_checks(table, native)
        dropped = [{"step": r["step"], "old_name": r["metric"], "class": "P",
                    "what_still_protects": r["reason"]} for r in dropped] + paper
        unmeasured = [{"step": row["name"], "metric": c["metric"], "operator": c["operator"],
                       "required_source": json.dumps(c.get("required_from", c.get("limit_from", {}))),
                       "searched_sources": json.dumps(native.get("searched_sources", {}).get(row["name"], []))}
                      for row in table["steps"] for c in row["checks"] if c["limit"] is None]
    args.output.write_text(json.dumps(table, indent=2) + "\n")
    if args.reports:
        args.reports.mkdir(parents=True, exist_ok=True)
        if classifications:
            write_tsv(args.reports / "CHECK_MAP.tsv", classifications,
                      ["step", "old_name", "class", "new_native_name_or_reason", "limit", "source"])
            write_tsv(args.reports / "DROPPED.tsv", dropped,
                      ["step", "old_name", "class", "what_still_protects"])
            write_tsv(args.reports / "REAL_WORK.tsv", work, ["step", "old_name", "tool_and_work"])
            requests = [r for r in classifications if r["class"] in {"R", "P"}]
            fields = ["step", "old_name", "class", "new_native_name_or_reason"]
            decision = native.get("classification_decision")
            if decision and decision["unresolved"]:
                (args.reports / "DECISION-REQUEST.md").write_text(
                    f"# Ruling {decision['ruling']} classification decisions\n\n"
                    + decision["resolved"] + "\n\n"
                    + "\n\n".join(decision["conditions"]) + "\n\n"
                    + "\n\n".join("UNRESOLVED: " + item for item in decision["unresolved"]) + "\n")
            elif decision:
                (args.reports / "DECISION-REQUEST.md").unlink(missing_ok=True)
            else:
                (args.reports / "DECISION-REQUEST.md").write_text(
                    "# Ruling 207 R/P classification for owner review\n\n"
                    "Provisional R/P classifications across every table row. Numeric signoff limits remain unchanged. "
                    "R observations do not block without a declared bound. P entries are removed paper obligations. "
                    "N/X/D/T work continues.\n\n```tsv\n" + "\t".join(fields) + "\n"
                    + "".join("\t".join(r[k] for k in fields) + "\n" for r in requests) + "```\n")
        else:
            write_tsv(args.reports / "DROPPED.tsv", dropped, ["step", "metric", "operator", "reason"])
        write_tsv(args.reports / "UNMEASURED_METRICS.tsv", unmeasured,
                  ["step", "metric", "operator", "required_source", "searched_sources"])
        rows = [{"step": s["name"], "metric": c["metric"], "operator": c["operator"],
                 "limit": json.dumps(c["limit"]), "source": json.dumps(c["source"])}
                for s in table["steps"] for c in s["checks"]]
        write_tsv(args.reports / "LIMITS.tsv", rows, ["step", "metric", "operator", "limit", "source"])
    print(f"Wrote {len(table['steps'])} steps; dropped {len(dropped)} wrapper obligations; preserved numeric limits.")


if __name__ == "__main__":
    main()
