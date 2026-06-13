#!/usr/bin/env python3
"""
Bootstrap compliance.yaml for every compliance-tracked skill.

Layout (vibe-ic marketplace):
    vibe-ic/skills/<skill>/SKILL.md        - the skill definition
    vibe-ic/skills/<skill>/compliance.yaml    - THIS tool writes these
    vibe-ic/skills/<skill>/tests/test_compliance.py  - (gen_compliance_tests.py writes)

For every vibe-ic skill we emit a starter compliance.yaml in the
plugin tree. Each file is a starting point - human review
(or /rtl-review compliance-spec pass) is expected to refine patterns.
"""
from __future__ import annotations
import re
import sys
from pathlib import Path


COMMON_REQS = [
    ("R_next_step",
     "At least one 'Next:' handoff line",
     r"Next:\s*(?:run\s+)?/\w"),
    ("R_status_or_summary",
     "Has a Summary or STATUS block",
     r"(##\s+Summary|\*\*STATUS\*\*:)"),
]


def detect_skill_patterns(skill_md: str):
    reqs = []
    for m in re.finditer(r'`(Next:\s*(?:run\s+)?/\S+[^`]*)`', skill_md):
        line = m.group(1)
        slug = re.sub(r'[^a-z0-9]+', '_', line.lower())[:40]
        if '/' in line:
            tok = re.escape(line.split('/', 1)[1].split()[0])
            reqs.append((f"R_handoff_{slug}",
                         f"Handoff: {line}",
                         r"Next:\s*(?:run\s+)?" + tok))
    if re.search(r'##\s+Output\s+(format|schema)', skill_md, re.IGNORECASE):
        reqs.append(("R_has_output_section",
                     "Output format/schema section present",
                     r"(##\s+(?:Output|Findings|Result|Report))"))
    if re.search(r'##\s+Next\s+step', skill_md, re.IGNORECASE):
        reqs.append(("R_next_step_section",
                     "Next step section",
                     r"##\s+Next\s+step"))
    return reqs


def gen_yaml(skill_name, detected):
    all_reqs = detected + COMMON_REQS
    seen, uniq = set(), []
    for r in all_reqs:
        if r[0] in seen: continue
        seen.add(r[0]); uniq.append(r)
    lines = [
        f"# Auto-generated compliance spec for skill '{skill_name}'",
        f"# Refines vibe-ic/skills/{skill_name}/SKILL.md output requirements.",
        f"skill: {skill_name}",
        "",
        "requirements:",
    ]
    for rid, desc, pat in uniq:
        safe = pat.replace("'", "''")
        lines.append(f"  - id: {rid}")
        lines.append(f"    description: \"{desc}\"")
        lines.append(f"    pattern: '{safe}'")
        lines.append(f"    skill_section: 'Output/Handoff'")
    lines.append("")
    lines.append("cross_checks: []")
    lines.append("")
    return '\n'.join(lines)


def main():
    # Wave 82: the former second plugin merged into vibe-ic. Try the
    # merged-plugin layout first, fall back to legacy split for older
    # checkouts.
    d_plugin = Path(__file__).resolve().parent.parent
    marketplace = d_plugin.parent.parent
    legacy_core = marketplace / 'plugins' / 'vibe-ic' / 'skills'
    if legacy_core.is_dir():
        core_skills = legacy_core
    else:
        core_skills = d_plugin / 'skills'
    d_skills = d_plugin / 'skills'
    made = 0
    for skill_md in core_skills.glob('*/SKILL.md'):
        name = skill_md.parent.name
        target_dir = d_skills / name
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / 'compliance.yaml'
        if target.exists():
            print(f"SKIP (exists): skills/{name}/compliance.yaml")
            continue
        detected = detect_skill_patterns(skill_md.read_text(errors='replace'))
        target.write_text(gen_yaml(name, detected))
        made += 1
        print(f"WROTE: skills/{name}/compliance.yaml")
    print(f"\nCreated {made} compliance.yaml files.")
    return 0


if __name__ == '__main__':
    sys.exit(main())
