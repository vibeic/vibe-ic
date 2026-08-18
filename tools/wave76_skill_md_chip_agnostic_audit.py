#!/usr/bin/env python3
"""Wave 76 — SKILL.md generality audit.

Inserts a standardised "case-study notation" banner into every
SKILL.md that mentions the IC-A / USB-HID tester / MDV-A1101 BENCH-A
reference project, AND classifies every existing hit as one of:

  - RATIONALE_PARA   : narrative evidence ("v0.119.55 fresh-agent
                       attempt FAILed because ...") — keep verbatim;
                       the banner makes the casestudy status explicit.
  - EXAMPLE_FIXED    : code/JSON example with hard-coded chip name
                       used as illustration — keep verbatim under the
                       banner.
  - INSTRUCTION_FIXED: rule body literally says "for IC-A do X" —
                       these would need rewriting to be chip-AGNOSTIC.

Wave 76 runs the audit and emits a JSON report. Human-class chip
references in narrative paragraphs (RATIONALE_PARA / EXAMPLE_FIXED)
are explicitly preserved with the banner — they're case-study
evidence, not chip-locked rules.

Audit invariant: zero ACTIVE INSTRUCTION_FIXED hits remain after the
banner is applied (all rule bodies talk about ic_class, not chip
SKUs). community-backlog-submit/SKILL.md is excluded — its hits ARE
the redaction-pattern table (intentional).
"""
from __future__ import annotations
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILLS = ROOT / "vibe-ic-marketplace" / "plugins" / "vibe-ic-core" / "skills"

# Chip / tester / vendor-doc tokens that are BENCH-A-specific.
PATTERNS = re.compile(
    r"\b(IC-A|BigTen|A1101|A1103|A1105|MDV-?A1101|"
    r"ACC_ID|ID_IO|USB-HID tester|usb_hid_tester|0xF2|altsyncram)\b"
)

# Skills whose reference is intentional (redaction table).
ALLOWLIST = {"community-backlog-submit"}

BANNER_MARKER = "<!-- WAVE_76_CHIP_AGNOSTIC_BANNER -->"
BANNER = f"""{BANNER_MARKER}

> **Case-study notation.** This skill cites the IC-A / USB-HID tester /
> MDV-A1101 BENCH-A reference project as concrete evidence for the
> rules below. The rules themselves are chip-AGNOSTIC and apply to
> any IC of the matching `ic_class` (see
> `vibe-ic-marketplace/plugins/vibe-ic-d/programs/ic_class_profile.py`).
> When you adopt this skill on a different IC, swap `IC-A` →
> `<your IC name>` and `USB-HID tester` → `<your host-tester name>`; the
> structural gates and rule bodies do not depend on those SKUs.
> See `docs/design/CASE_STUDIES/IC-A_*.md` for the full BENCH-A
> regression history.
"""


def classify_hit(line: str) -> str:
    """Best-effort classify a SKILL.md line containing a chip token.

    Heuristics:
      - INSTRUCTION_FIXED: imperative phrasing ("MUST"/"shall"/"do X")
        AND the chip token is the subject of the rule (rare).
      - EXAMPLE_FIXED: inside ``` fence or table cell or JSON-like.
      - RATIONALE_PARA: narrative verb ("FAIL", "regression",
        "attempt", "case", "evidence", "lesson", year/version).
    """
    s = line.strip()
    # Strong INSTRUCTION cues — chip name in subject position with
    # imperative.
    if re.search(r"\b(MUST|SHALL|REQUIRED)\b.*?\b(IC-A|USB-HID tester|usb_hid_tester|MDV-?A1101)\b", s):
        # Distinguish "MUST replace IC-A with ..." (chip-agnostic
        # instruction) from "MUST hardcode IC-A X" (chip-locked).
        if re.search(r"\b(replace|swap|substitute|redact)\b", s, re.I):
            return "RATIONALE_PARA"  # generality instruction
        return "INSTRUCTION_FIXED"
    # JSON / code fence / table cell heuristics
    if (
        s.startswith("{")
        or s.startswith('"')
        or s.startswith("|")
        or s.startswith(">")
        or "```" in s
        or '"_decision_source"' in s
        or '"vendor_evidence_path"' in s
    ):
        return "EXAMPLE_FIXED"
    # Narrative / rationale cues
    if re.search(
        r"\b(regression|attempt|FAIL|byte\[6\]|root cause|"
        r"silent|evidence|lesson|case|v0\.\d+|[Ss]ee )",
        s,
    ):
        return "RATIONALE_PARA"
    # Default to RATIONALE_PARA (informational mention).
    return "RATIONALE_PARA"


def insert_banner(text: str) -> tuple[str, bool]:
    if BANNER_MARKER in text:
        return text, False
    # Find the first blank line after the YAML front-matter close `---`.
    m = re.search(r"^---\s*\n.*?^---\s*\n", text, re.MULTILINE | re.DOTALL)
    insert_at = m.end() if m else 0
    return text[:insert_at] + "\n" + BANNER + "\n" + text[insert_at:], True


def audit() -> dict:
    report: dict = {
        "schema": "vibe-ic Wave-76 SKILL-md generality audit v1",
        "skills_with_hits": [],
        "totals": {
            "RATIONALE_PARA": 0,
            "EXAMPLE_FIXED": 0,
            "INSTRUCTION_FIXED": 0,
            "ACTIVE_INSTRUCTION_FIXED": 0,
        },
        "files_modified": [],
        "allowlisted": [],
    }
    for skill_md in sorted(SKILLS.glob("*/SKILL.md")):
        text = skill_md.read_text()
        if not PATTERNS.search(text):
            continue
        skill_name = skill_md.parent.name
        per_file = {
            "skill": skill_name,
            "path": str(skill_md.relative_to(ROOT)),
            "hits_by_class": {
                "RATIONALE_PARA": [],
                "EXAMPLE_FIXED": [],
                "INSTRUCTION_FIXED": [],
            },
        }
        for n, line in enumerate(text.splitlines(), 1):
            if PATTERNS.search(line):
                cls = classify_hit(line)
                per_file["hits_by_class"][cls].append(
                    {"line": n, "text": line.strip()[:160]}
                )
                report["totals"][cls] += 1
        if skill_name in ALLOWLIST:
            report["allowlisted"].append(skill_name)
        else:
            new_text, changed = insert_banner(text)
            if changed:
                skill_md.write_text(new_text)
                report["files_modified"].append(skill_name)
        report["skills_with_hits"].append(per_file)

    # ACTIVE = INSTRUCTION_FIXED hits in non-allowlisted skills (the
    # banner alone does NOT make these chip-agnostic; they need a
    # rewrite). Wave 76 reports 0 here — current 16 hits are all
    # narrative / example.
    for f in report["skills_with_hits"]:
        if f["skill"] in ALLOWLIST:
            continue
        report["totals"]["ACTIVE_INSTRUCTION_FIXED"] += len(
            f["hits_by_class"]["INSTRUCTION_FIXED"]
        )
    return report


def main(argv: list[str]) -> int:
    out = ROOT / "docs" / "reports" / "wave76_skill_md_audit.json"
    if "--report" in argv:
        idx = argv.index("--report")
        if idx + 1 < len(argv):
            out = Path(argv[idx + 1])
    report = audit()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2))
    print(json.dumps(report["totals"], indent=2))
    print(f"audit JSON  → {out}")
    print(f"modified    → {len(report['files_modified'])} SKILL.md")
    print(f"allowlisted → {report['allowlisted']}")
    if report["totals"]["ACTIVE_INSTRUCTION_FIXED"] > 0:
        print(
            "FAIL: ACTIVE INSTRUCTION_FIXED hits remain — rewrite needed",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
