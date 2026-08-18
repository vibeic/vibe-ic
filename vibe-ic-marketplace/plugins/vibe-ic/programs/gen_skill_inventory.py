#!/usr/bin/env python3
"""
gen_skill_inventory.py — single source of truth for the AI-skill count.

Same pattern as mcp-eda/tools/gen_mcp_tool_inventory.py, for the skills
shown on vibeic.ai/#skills. The site hand-maintained "55 AI Skills"; that number
drifts whenever a skill is added/removed (it is now 57 after benchmark-verify +
design-for-eco landed). This derives the count DIRECTLY from the skill folders so
it can never drift again.

Authoritative definition of a skill: a directory under
`<plugin>/skills/<name>/` that contains a `SKILL.md`. (`_classification.json`,
`.deprecated_skills/`, and any dir without SKILL.md are NOT skills.)

Writes SKILL_INVENTORY.json and prints total + per-tier breakdown. `--check`
exits 1 if the committed inventory is stale vs the folders (wire into CI).

Usage:
  python3 programs/gen_skill_inventory.py            # regenerate + print
  python3 programs/gen_skill_inventory.py --check    # verify committed == folders
"""
from __future__ import annotations
import argparse, json, re, sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent        # plugins/vibe-ic/
SKILLS = PLUGIN / "skills"
CLASS_JSON = SKILLS / "_classification.json"
OUT = PLUGIN / "SKILL_INVENTORY.json"


def _frontmatter_name(skill_md: Path) -> str:
    txt = skill_md.read_text(errors="ignore")
    m = re.search(r'^\s*name:\s*"?([A-Za-z0-9_:-]+)"?', txt, re.MULTILINE)
    return m.group(1) if m else skill_md.parent.name


def discover() -> dict:
    # tier lookup from _classification.json
    tier_of: dict[str, str] = {}
    deprecated: set[str] = set()
    if CLASS_JSON.exists():
        cj = json.loads(CLASS_JSON.read_text())
        for tier, info in cj.get("tiers", {}).items():
            for s in info.get("skills", []):
                tier_of[s] = tier
        deprecated = set(cj.get("deprecated_skills", []))

    skills = []
    for d in sorted(SKILLS.iterdir()):
        if not d.is_dir() or not (d / "SKILL.md").is_file():
            continue
        if d.name in deprecated:
            continue
        skills.append({"name": d.name,
                       "frontmatter_name": _frontmatter_name(d / "SKILL.md"),
                       "tier": tier_of.get(d.name, "unclassified")})

    by_tier: dict[str, int] = {}
    for s in skills:
        by_tier[s["tier"]] = by_tier.get(s["tier"], 0) + 1
    return {
        "schema_version": 1,
        "_comment": "AUTHORITATIVE AI-skill inventory — generated from the skills/ "
                    "folders by programs/gen_skill_inventory.py. Do NOT hand-edit; "
                    "the website skill count must read `total` from here.",
        "total": len(skills),
        "by_tier": dict(sorted(by_tier.items())),
        "skills": [s["name"] for s in skills],
        "detail": skills,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="exit 1 if committed SKILL_INVENTORY.json != folders")
    a = ap.parse_args()
    inv = discover()
    if a.check:
        if not OUT.exists():
            print(f"FAIL: {OUT.name} missing — run without --check to generate"); sys.exit(1)
        committed = json.loads(OUT.read_text())
        if committed.get("skills") != inv["skills"]:
            cset, iset = set(committed.get("skills", [])), set(inv["skills"])
            print(f"FAIL: skill inventory drift. committed total={committed.get('total')} "
                  f"folders={inv['total']}")
            if iset - cset: print(f"  on disk but not committed: {sorted(iset - cset)}")
            if cset - iset: print(f"  committed but not on disk: {sorted(cset - iset)}")
            sys.exit(1)
        print(f"OK: skill inventory matches folders — {inv['total']} skills "
              f"({inv['by_tier']})"); sys.exit(0)
    OUT.write_text(json.dumps(inv, indent=2) + "\n")
    print(f"wrote {OUT}")
    print(f"TOTAL AI SKILLS = {inv['total']}")
    print("by_tier:", inv["by_tier"])


if __name__ == "__main__":
    main()
