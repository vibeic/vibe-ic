#!/usr/bin/env python3
"""
provenance_check.py — Verify a file was produced by a logged tool run.

Pairs with provenance_logger.py. A flow gate asks:
    "does <project>/provenance.jsonl contain an entry that
     (a) names <tool> (in the allow-list),
     (b) exited 0,
     (c) declared <required_output> as one of its outputs, AND
     (d) whose logged hash still matches the file on disk?"

If yes → PASS. If no (no entry, wrong tool, hash mismatch, no file) → FAIL.

Usage
-----
    provenance_check.py <project_dir> \\
        --output pnr/routed.def --tool openroad,openroad-flow-scripts \\
        --output pnr/drc.rpt    --tool klayout,openroad

Each --output/--tool pair is checked independently; all must pass.

    provenance_check.py <project_dir> --require-entries 5
        — simply asserts the log has >= 5 exit-0 entries (coarse sanity).

Exit codes
----------
    0 = every declared output has a matching valid log entry
    1 = one or more failed
    2 = usage / io error
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Dict, List, Tuple


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    try:
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return "sha256:" + h.hexdigest()
    except OSError:
        return ""


def _load_log(project: Path) -> List[dict]:
    log = project / "provenance.jsonl"
    if not log.exists():
        return []
    entries: List[dict] = []
    with log.open() as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError as exc:
                print(f"provenance_check: malformed line {i}: {exc}",
                      file=sys.stderr)
    return entries


def _find_entry(entries: List[dict], out_rel: str,
                allowed_tools: set) -> Tuple[dict | None, List[str]]:
    """Return (matching_entry, reasons_if_none)."""
    reasons: List[str] = []
    matches = []
    for e in entries:
        if out_rel not in e.get("outputs", {}):
            continue
        if e.get("exit_code", -1) != 0:
            reasons.append(f"entry {e.get('timestamp','?')} "
                           f"for {out_rel} has exit_code="
                           f"{e.get('exit_code')}")
            continue
        if allowed_tools and e.get("tool") not in allowed_tools:
            reasons.append(f"entry {e.get('timestamp','?')} "
                           f"tool '{e.get('tool')}' not in allowed "
                           f"{sorted(allowed_tools)}")
            continue
        matches.append(e)
    if not matches:
        if not reasons:
            reasons.append(f"no entry in provenance.jsonl declares "
                           f"'{out_rel}' as an output")
        return None, reasons
    # pick the most recent matching entry
    matches.sort(key=lambda e: e.get("timestamp", ""), reverse=True)
    return matches[0], []


def main(argv: List[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    p.add_argument("project_dir")
    p.add_argument("--output", action="append", default=[],
                   help="Required output file path (relative to project). "
                        "Pair each with --tool (same index).")
    p.add_argument("--tool", action="append", default=[],
                   help="Comma-separated allowed tool names for the matching "
                        "--output at the same position.")
    p.add_argument("--require-entries", type=int, default=0,
                   help="Shortcut: pass if log has >= N exit-0 entries")
    p.add_argument("--json", help="Write JSON report to this path")
    args = p.parse_args(argv)

    project = Path(args.project_dir).resolve()
    if not project.is_dir():
        print(f"provenance_check: not a directory: {project}",
              file=sys.stderr)
        return 2

    entries = _load_log(project)

    report: Dict = {"project": str(project), "log_entries": len(entries),
                    "checks": []}

    # Coarse mode: just count exit-0 entries
    if args.require_entries > 0:
        exit0 = sum(1 for e in entries if e.get("exit_code") == 0)
        ok = exit0 >= args.require_entries
        report["require_entries"] = args.require_entries
        report["exit_zero_entries"] = exit0
        report["ok"] = ok
        if args.json:
            Path(args.json).parent.mkdir(parents=True, exist_ok=True)
            Path(args.json).write_text(json.dumps(report, indent=2))
        print(f"provenance_check: {exit0} / {args.require_entries} "
              f"exit-0 entries {'OK' if ok else 'FAIL'}")
        return 0 if ok else 1

    if len(args.output) != len(args.tool):
        print("provenance_check: --output and --tool counts must match "
              f"(got {len(args.output)} outputs, {len(args.tool)} tools)",
              file=sys.stderr)
        return 2

    if not args.output:
        print("provenance_check: nothing to check; pass --output/--tool "
              "or --require-entries", file=sys.stderr)
        return 2

    overall_ok = True

    for out_rel_pattern, tools_csv in zip(args.output, args.tool):
        allowed = {t.strip() for t in tools_csv.split(",") if t.strip()}

        # Glob expansion (chip-AGNOSTIC): flow steps reference outputs by
        # pattern (e.g. `phase3/stage3/extracted/*.spef`) because the top
        # cell name is not known at manifest-authoring time. Without
        # expansion the literal `*.spef` path "exists on disk" check fails
        # and Step 22 false-FAILs on every chip whose SPEF is registered
        # under its concrete name. Expand the pattern to the actual file(s);
        # a non-glob path resolves to itself.
        if any(ch in out_rel_pattern for ch in "*?[") :
            matches = sorted(
                str(p.relative_to(project))
                for p in project.glob(out_rel_pattern)
                if p.is_file()
            )
            if not matches:
                check = {"output": out_rel_pattern, "allowed_tools": tools_csv,
                         "status": "FAIL",
                         "reasons": [f"no file on disk matches pattern: "
                                     f"{out_rel_pattern}"]}
                report["checks"].append(check)
                overall_ok = False
                continue
            out_rels = matches
        else:
            out_rels = [out_rel_pattern]

        # Check each concrete output resolved from the pattern.
        for out_rel in out_rels:
            check: Dict = {"output": out_rel, "allowed_tools": tools_csv,
                           "status": "FAIL", "reasons": []}

            # The file must exist on disk
            abs_out = project / out_rel
            if not abs_out.exists():
                check["reasons"].append(f"file on disk missing: {out_rel}")
                report["checks"].append(check)
                overall_ok = False
                continue

            disk_hash = _sha256_file(abs_out)

            # Find a matching entry
            entry, reasons = _find_entry(entries, out_rel, allowed)
            if entry is None:
                check["reasons"].extend(reasons)
                report["checks"].append(check)
                overall_ok = False
                continue

            # Hash match
            logged_hash = entry["outputs"][out_rel]
            if logged_hash != disk_hash:
                check["reasons"].append(
                    f"hash mismatch: log={logged_hash[:18]}... disk={disk_hash[:18]}..."
                    " — file modified after tool run, or log is stale"
                )
                check["logged_hash"] = logged_hash
                check["disk_hash"] = disk_hash
                report["checks"].append(check)
                overall_ok = False
                continue

            check["status"] = "PASS"
            check["tool"] = entry.get("tool")
            check["timestamp"] = entry.get("timestamp")
            check["version"] = entry.get("version")
            report["checks"].append(check)

    report["ok"] = overall_ok

    # Print summary
    print(f"\n=== provenance_check ({project.name}) ===")
    print(f"  log entries: {len(entries)}")
    for c in report["checks"]:
        icon = "✓" if c["status"] == "PASS" else "✗"
        print(f"  {icon} [{c['status']:<4}] {c['output']}")
        if c["status"] == "PASS":
            print(f"         via {c.get('tool')} @ {c.get('timestamp')}")
        else:
            for r in c["reasons"]:
                print(f"         - {r}")

    print(f"\nOverall: {'PASS' if overall_ok else 'FAIL'}")

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(report, indent=2))

    return 0 if overall_ok else 1


if __name__ == "__main__":
    sys.exit(main())
