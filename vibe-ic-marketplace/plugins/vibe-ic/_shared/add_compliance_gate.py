#!/usr/bin/env python3
"""
Append the standard "Compliance gate" paragraph to every
vibe-ic SKILL.md that doesn't already have one.
"""
from pathlib import Path
import sys

GATE = """\

## Compliance gate (mandatory)

After producing your output, save it to a file and run:

```bash
python3 plugins/vibe-ic/_shared/skill_compliance_check.py \\
    --requirements plugins/vibe-ic/skills/{SKILL}/compliance.yaml \\
    <your_output_file>
```

Exit 0 = PASS, exit 1 = FAIL with specific missing elements listed.
`compliance.yaml` in the corresponding skill directory enumerates
every required element of your output: section headers, metadata fields,
handoff lines, tool invocations.

**Your task is not complete until the audit returns PASS.** Missing
elements are the single largest source of skill-execution non-determinism
across different agents.
"""


def main():
    d_plugin = Path(__file__).resolve().parent.parent
    marketplace = d_plugin.parent.parent
    core_skills = marketplace / 'plugins' / 'vibe-ic' / 'skills'
    n = 0
    for md in core_skills.glob('*/SKILL.md'):
        content = md.read_text(errors='replace')
        if 'Compliance gate' in content:
            continue
        skill_name = md.parent.name
        new = content.rstrip() + '\n' + GATE.replace('{SKILL}', skill_name)
        md.write_text(new)
        n += 1
        print(f"UPDATED: {md.relative_to(marketplace)}")
    print(f"\nAdded Compliance gate to {n} SKILL.md files.")
    return 0


if __name__ == '__main__':
    sys.exit(main())
