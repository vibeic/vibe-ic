#!/usr/bin/env python3
"""name_reds.py — name every red CASE in a run, and REFUSE to call an absence
of evidence "no reds".

The contract this file exists for: `$HOME/.claude/fleet/rg_name_reds.py` was
named in the brief as the namer that refuses to report an empty directory as
"no reds". It is not present on either host (nor anywhere under ~/.claude), so
the contract is re-implemented here rather than assumed.

REFUSALS — each exits 2 with a named reason and NEVER prints a red list:
  * the junit directory is missing or holds no XML at all
  * a file the runner marked RECORDED has no junit XML behind it
  * a junit XML is unparseable
And, always reported and never folded into the red set:
  * every NORECORD / NOTRUN file, whose reds are UNKNOWN and not zero.

An empty red list is only ever printed together with the count of files that
actually produced evidence, so "0 reds" cannot be read without its denominator.
"""
import json, sys, xml.etree.ElementTree as ET
from pathlib import Path

run_dir = Path(sys.argv[1])
label = sys.argv[2] if len(sys.argv) > 2 else run_dir.name
run = json.loads((run_dir / "run.json").read_text())
jdir = run_dir / "junit"

if not jdir.is_dir() or not any(jdir.glob("*.xml")):
    print(f"[NOT DETERMINED] {label}: `{jdir}` holds no junit XML. "
          f"An empty directory is not evidence that nothing is red.", file=sys.stderr)
    sys.exit(2)

recorded = [r for r in run["rows"] if r["bucket"] == "RECORDED"]
missing = [r["file"] for r in recorded if not (r.get("junit") and Path(r["junit"]).is_file())]
if missing:
    print(f"[NOT DETERMINED] {label}: {len(missing)} file(s) marked RECORDED with no "
          f"junit behind them: {missing}", file=sys.stderr)
    sys.exit(2)

reds, cases, unparseable = [], 0, []
for r in recorded:
    try:
        root = ET.parse(r["junit"]).getroot()
    except Exception as exc:
        unparseable.append((r["file"], str(exc))); continue
    for tc in root.iter("testcase"):
        cases += 1
        bad = [c for c in tc if c.tag in ("failure", "error")]
        if not bad:
            continue
        cls = (tc.get("classname") or "").split(".")
        stem = Path(r["file"]).stem
        node = r["file"] + "::" + tc.get("name", "?") if (not cls or cls[-1] == stem) \
            else r["file"] + "::" + cls[-1] + "::" + tc.get("name", "?")
        reds.append({"node": node, "file": r["file"], "kind": bad[0].tag,
                     "message": (bad[0].get("message") or "").strip().splitlines()[:1]})
if unparseable:
    print(f"[NOT DETERMINED] {label}: unparseable junit: {unparseable}", file=sys.stderr)
    sys.exit(2)

blind = [r for r in run["rows"] if r["bucket"] != "RECORDED"]
reds.sort(key=lambda r: r["node"])
(run_dir / "reds.json").write_text(json.dumps(
    {"label": label, "head": run["head"], "files_with_evidence": len(recorded),
     "files_total": run["files"], "cases_seen": cases, "reds": reds,
     "blind": [{"file": b["file"], "bucket": b["bucket"], "reason": b["reason"]} for b in blind]},
    indent=1) + "\n")

print(f"== {label}  head={run['head'][:9]}")
print(f"   evidence from {len(recorded)}/{run['files']} file(s), {cases} case(s) seen")
print(f"   RED CASES: {len(reds)}")
for r in reds:
    print(f"     {r['kind'].upper():7s} {r['node']}")
if blind:
    print(f"   BLIND — reds UNKNOWN, not zero, for {len(blind)} file(s):")
    for b in blind:
        print(f"     {b['bucket']:8s} {b['file']} — {b['reason']}")
