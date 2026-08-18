#!/usr/bin/env python3
"""sample_runner.py — replace with your deterministic runner.

Pattern (mirror plugins/vibe-ic/programs/phase*_one_shot_runner.py):
1. argparse <project>
2. emit reports/<your_phase>_one_shot.json with verdict
3. exit 0 PASS / PASS_WITH_WAIVERS, 1 FAIL, 2 IO error
"""
import sys, json, argparse
from pathlib import Path

def main():
    p = argparse.ArgumentParser()
    p.add_argument("project", type=Path)
    args = p.parse_args()
    project = args.project.resolve()
    if not project.is_dir():
        print(f"ERROR: not a directory: {project}", file=sys.stderr)
        return 2
    # Your work here.
    summary = {"phase": "sample", "project": str(project), "verdict": "PASS"}
    out = project / "reports" / "sample_one_shot.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2) + "\n")
    print(f"verdict: PASS")
    return 0

if __name__ == "__main__":
    sys.exit(main())
