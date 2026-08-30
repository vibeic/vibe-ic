#!/usr/bin/env python3
"""Validate the runner-produced Step-31 illegal-overlap record in place.

ENFORCEMENT: blocking.  The Phase-3 runner invokes this immediately after the
producer writes the JSON and lets every non-zero exit stop LVS.  Step 31 invokes
the same validator again before its independent audit, so missing, malformed,
skipped, red, undetermined, or non-zero record bytes cannot become evidence.
This program never rewrites the record.

The contract is chip- and PDK-agnostic; every expected field is owned by the
sibling checker that produced the record.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from magic_illegal_overlap_check import GATE, validate_record  # noqa: E402


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Validate the runner-produced Step-31 illegal-overlap JSON.")
    ap.add_argument("project_dir")
    ap.add_argument("--record", required=True,
                    help="project-relative runner-produced JSON record")
    args = ap.parse_args(argv)

    project = Path(args.project_dir).resolve()
    if not project.is_dir():
        print(f"[FAIL] {GATE} record: not a directory: {project}",
              file=sys.stderr)
        return 1
    passed, reason = validate_record(project, args.record)
    print(f"[{('PASS' if passed else 'FAIL')}] {GATE} record: {reason}",
          file=sys.stdout if passed else sys.stderr)
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
