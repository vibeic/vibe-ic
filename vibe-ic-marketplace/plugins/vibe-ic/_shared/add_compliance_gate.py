#!/usr/bin/env python3
"""
Append the standard "Compliance gate" paragraph to every
vibe-ic SKILL.md that doesn't already have one.

`--skills-dir` retargets the walk at an arbitrary skills/ tree. It exists so a
test can exercise this tool against a COPY instead of the shipped tree: before
#1029 `test_add_gate_is_idempotent` ran the tool with no way to redirect it, so
a passing test run left `skills/fork-gatekeeper-loop/SKILL.md` modified and
`landing_worktree_is_clean_check.py` — which runs immediately after the tests in
`gatekeeper-land.sh` — went red on dirt the harness itself created. Default is
unchanged: the real skills/ tree.
"""
import argparse
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


def default_skills_dir():
    d_plugin = Path(__file__).resolve().parent.parent
    marketplace = d_plugin.parent.parent
    return marketplace / 'plugins' / 'vibe-ic' / 'skills'


def add_gate(core_skills):
    """Append the gate to every SKILL.md under `core_skills` that lacks one.

    Returns the number of files written.
    """
    base = core_skills.parent.parent.parent
    n = 0
    for md in sorted(core_skills.glob('*/SKILL.md')):
        content = md.read_text(errors='replace')
        if 'Compliance gate' in content:
            continue
        skill_name = md.parent.name
        new = content.rstrip() + '\n' + GATE.replace('{SKILL}', skill_name)
        md.write_text(new)
        n += 1
        try:
            shown = md.relative_to(base)
        except ValueError:
            shown = md
        print(f"UPDATED: {shown}")
    return n


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--skills-dir', default=None,
                    help='skills/ tree to walk (default: the shipped one). '
                         'Point this at a copy to exercise the tool without '
                         'writing into the checkout.')
    args = ap.parse_args(argv)
    core_skills = (Path(args.skills_dir).resolve() if args.skills_dir
                   else default_skills_dir())
    n = add_gate(core_skills)
    print(f"\nAdded Compliance gate to {n} SKILL.md files.")
    return 0


if __name__ == '__main__':
    sys.exit(main())
