#!/usr/bin/env python3
"""enhancement_emit.py — driver for the benchmark-enhancement-capture skill.

Takes a recoveries.json listing (design, before-RTL, after-RTL, ai-reasoning,
bucket) records and produces concrete artifacts:
  - markdown fragments to append to agents/ic-expert-agent.md (Bucket B)
  - python patch sketches for programs/rtl_hygiene_lint.py (Bucket A)
  - YAML backlog entries for community/backlogs/ (Bucket C)
  - a discard log for Bucket D entries

The actual program/skill modifications are NEVER applied automatically — this
script just emits candidates for human review (Bucket A) or direct append
(Bucket B / C). Bucket A patches require a corpus-sweep verification before
being merged, per the skill's honesty rule.

Usage:
    python3 enhancement_emit.py --records recoveries.json --out-dir candidates/
"""
from __future__ import annotations
import argparse, json, datetime
from pathlib import Path


def _slug(s: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in s.lower()).strip("-")[:80]


def emit_skill_section(rec: dict) -> str:
    name = rec.get("skill_title", _slug(rec.get("design", "unknown")))
    return (
        f"### Skill: {name}\n\n"
        f"**Pattern**: {rec.get('pattern', '')}\n\n"
        f"**When to apply**: {rec.get('when', '')}\n\n"
        f"**What to do**: {rec.get('what', '')}\n\n"
        f"**Worked example** (from {rec.get('design', '?')}): "
        f"{rec.get('example', '')}\n\n"
        f"**Why this is GENERAL**: {rec.get('generality', '')}\n\n"
        f"_Captured by benchmark-enhancement-capture {datetime.date.today().isoformat()}._\n"
    )


def emit_program_rule_sketch(rec: dict) -> str:
    rname = _slug(rec.get("rule_name", "todo")).replace("-", "_")
    return (
        f"# v0.1.34+ — auto-captured by benchmark-enhancement-capture\n"
        f"# Pattern: {rec.get('pattern', '')}\n"
        f"# Source: {rec.get('design', '?')} recovery {datetime.date.today()}\n"
        f"# CORPUS-SWEEP REQUIRED before merging: zero false-positives across\n"
        f"# the existing VerilogEval + RTLLM + benchmark_clean corpora.\n"
        f"\n"
        f"def rule_{rname}(sample_text, ports):\n"
        f"    \"\"\"{rec.get('docstring', '')}\"\"\"\n"
        f"    # Expected signal: {rec.get('expected_signal', 'WARN')}\n"
        f"    # Suggested fix action: {rec.get('fix_action', '')}\n"
        f"    return []  # list of findings — TODO implement\n"
    )


def emit_backlog(rec: dict, today: str):
    slug = _slug(rec.get("backlog_slug", rec.get("design", "todo")))
    fname = f"ORGANIC-{today.replace('-','')}-{slug}.yaml"
    indent = "  "
    pat = rec.get("pattern", "").replace("\n", "\n" + indent)
    fix = rec.get("suggested_fix", "").replace("\n", "\n" + indent)
    body = (
        f"type: {rec.get('backlog_type', 'enhancement')}\n"
        f"severity: {rec.get('severity', 'P2')}\n"
        f"component: {rec.get('component', '')}\n"
        f"plugin_version: \"{rec.get('plugin_version', '0.1.33')}\"\n\n"
        f"title: >-\n  {rec.get('title', '')}\n\n"
        f"pattern: |\n  {pat}\n\n"
        f"suggested_fix: |\n  {fix}\n\n"
        f"id: \"ORGANIC-{today.replace('-','')}-{slug}\"\n"
        f"submitted_at: \"{today}T00:00:00+08:00\"\n"
        f"session_context: >-\n  {rec.get('session_context', '')}\n"
    )
    return fname, body


def emit_discard_note(rec: dict) -> str:
    return f"- **{rec.get('design', '?')}**: {rec.get('why_discard', 'no reason given')}\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--records", required=True)
    ap.add_argument("--out-dir", required=True)
    a = ap.parse_args()

    recs = json.loads(Path(a.records).read_text())
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    today = datetime.date.today().isoformat()

    by_bucket = {"A": [], "B": [], "C": [], "D": []}
    for r in recs:
        b = (r.get("bucket") or "D").upper()
        by_bucket.setdefault(b, []).append(r)

    summary = {"date": today, "totals": {k: len(v) for k, v in by_bucket.items()}}

    if by_bucket["A"]:
        p = out / "bucket_A_program_rule_sketches.py"
        chunks = ["# Bucket A — program-rule sketches (corpus-sweep before merge)\n"]
        for r in by_bucket["A"]:
            chunks.append(emit_program_rule_sketch(r))
        p.write_text("\n".join(chunks))
        summary["bucket_A_file"] = str(p)

    if by_bucket["B"]:
        p = out / "bucket_B_ic_expert_skill_sections.md"
        chunks = ["# Bucket B — ic-expert-agent skill sections (append to agents/ic-expert-agent.md)\n"]
        for r in by_bucket["B"]:
            chunks.append(emit_skill_section(r))
        p.write_text("\n".join(chunks))
        summary["bucket_B_file"] = str(p)

    if by_bucket["C"]:
        d = out / "bucket_C_backlogs"
        d.mkdir(exist_ok=True)
        files = []
        for r in by_bucket["C"]:
            fname, body = emit_backlog(r, today)
            (d / fname).write_text(body)
            files.append(fname)
        summary["bucket_C_dir"] = str(d)
        summary["bucket_C_files"] = files

    if by_bucket["D"]:
        p = out / "bucket_D_discarded.md"
        chunks = [f"# Bucket D — discarded ({len(by_bucket['D'])} entries)\n"]
        for r in by_bucket["D"]:
            chunks.append(emit_discard_note(r))
        p.write_text("\n".join(chunks))
        summary["bucket_D_file"] = str(p)

    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
