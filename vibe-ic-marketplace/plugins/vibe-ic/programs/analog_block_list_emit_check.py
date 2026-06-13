#!/usr/bin/env python3
"""analog_block_list_emit_check.py — master block-list schema gate.

Extracts the master-list emission rule embedded in the
`analog-spec-extract` skill:

    analog/analog_block_list.json:
      {
        "blocks": [
          {"name": "ldo_1v8", "type": "LDO",
           "spec_file": "analog/ldo_1v8/spec.json"},
          ...
        ],
        "block_count": <int>
      }

This is fixed-schema aggregation/serialization — deterministic, no
inference. The check validates that, IF a master block list exists, it
conforms to the schema and is internally consistent:

  * top level is an object with a `blocks` list and an int `block_count`
  * `block_count` == len(blocks)               (consistency)
  * every block entry has a non-empty `name` and a non-empty `type`
  * every block entry has a `spec_file` string ending in `spec.json`
  * (optional, --project) every `spec_file` actually resolves to a file
    on disk relative to the project root

When `analog/analog_block_list.json` is ABSENT the gate is VACUOUS_PASS
(digital-only / pre-A1) — never a vacuous true PASS: a present-but-broken
list FAILs, an absent list is an honest SKIP, and a present-but-garbage
(unparsable) list FAILs.

Usage:
    python3 analog_block_list_emit_check.py <path_or_project> [--project] [--json out.json]

    With --project, the positional arg is the project root and the gate
    looks for analog/analog_block_list.json (and phase3/analog/...) under
    it AND resolves each spec_file relative to the root. Without
    --project, the positional arg is the block-list JSON file itself
    (spec_file existence is NOT checked).

Exit codes:
    0  PASS / VACUOUS_PASS (no list to validate)
    1  FAIL (list present but malformed / inconsistent / missing spec)
    2  IO / usage error

chip-AGNOSTIC. No vendor / chip / block-name hardcoded.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional, Tuple


_PROJECT_GLOBS = (
    "analog/analog_block_list.json",
    "phase3/analog/analog_block_list.json",
    "**/analog_block_list.json",
)


def _locate(arg: Path, project_mode: bool) -> Tuple[Optional[Path], Optional[Path]]:
    """Return (block_list_path, project_root).

    project_root is non-None only in --project mode (for spec_file
    resolution). block_list_path is None when no list exists.
    """
    if project_mode:
        if not arg.is_dir():
            return None, None
        for pat in _PROJECT_GLOBS:
            for h in sorted(arg.glob(pat)):
                if h.is_file():
                    return h, arg
        return None, arg
    # File mode.
    if arg.is_file():
        return arg, None
    return None, None


def _validate(path: Path, project_root: Optional[Path]) -> Tuple[int, dict]:
    findings: List[str] = []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return 1, {"status": "FAIL",
                   "detail": f"block list present but unparsable: {exc}",
                   "findings": ["UNPARSABLE_JSON"]}

    if not isinstance(data, dict):
        return 1, {"status": "FAIL",
                   "detail": "top level is not a JSON object",
                   "findings": ["NOT_AN_OBJECT"]}

    blocks = data.get("blocks")
    if not isinstance(blocks, list):
        return 1, {"status": "FAIL",
                   "detail": "missing or non-list `blocks`",
                   "findings": ["MISSING_BLOCKS_LIST"]}

    count = data.get("block_count")
    if not isinstance(count, int):
        findings.append("BLOCK_COUNT_NOT_INT")
    elif count != len(blocks):
        findings.append(
            f"BLOCK_COUNT_MISMATCH (block_count={count} != "
            f"len(blocks)={len(blocks)})")

    for i, entry in enumerate(blocks):
        if not isinstance(entry, dict):
            findings.append(f"blocks[{i}]: not an object")
            continue
        name = entry.get("name")
        if not (isinstance(name, str) and name.strip()):
            findings.append(f"blocks[{i}]: missing/empty `name`")
        btype = entry.get("type")
        if not (isinstance(btype, str) and btype.strip()):
            findings.append(f"blocks[{i}] ({name}): missing/empty `type`")
        spec_file = entry.get("spec_file")
        if not (isinstance(spec_file, str) and spec_file.strip()):
            findings.append(f"blocks[{i}] ({name}): missing/empty `spec_file`")
        elif not spec_file.endswith("spec.json"):
            findings.append(
                f"blocks[{i}] ({name}): spec_file {spec_file!r} does not "
                f"end in 'spec.json'")
        elif project_root is not None:
            # Resolve spec_file relative to project root; accept either a
            # path already rooted at analog/ or one needing the prefix.
            cand = (project_root / spec_file)
            if not cand.is_file():
                # Try phase3/ prefix as the runner nests analog under it.
                alt = project_root / "phase3" / spec_file
                if not alt.is_file():
                    findings.append(
                        f"blocks[{i}] ({name}): spec_file {spec_file!r} "
                        f"does not resolve to a file on disk")

    if findings:
        return 1, {
            "status": "FAIL",
            "detail": f"{len(findings)} schema/consistency issue(s)",
            "block_count_declared": count,
            "blocks_len": len(blocks),
            "findings": findings,
        }
    return 0, {
        "status": "PASS",
        "block_count": len(blocks),
        "findings": [],
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog="analog_block_list_emit_check",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("path", type=Path,
                    help="block list JSON file (default) or project root "
                         "(with --project)")
    ap.add_argument("--project", action="store_true",
                    help="treat `path` as project root; locate "
                         "analog/analog_block_list.json under it and "
                         "resolve each spec_file on disk")
    ap.add_argument("--json", default=None, help="write JSON report")
    args = ap.parse_args(argv)

    arg = args.path.resolve()

    if args.project and not arg.is_dir():
        print(f"error: --project given but not a directory: {arg}",
              file=sys.stderr)
        return 2
    if not args.project and not arg.exists():
        print(f"error: path not found: {arg}", file=sys.stderr)
        return 2

    bl_path, project_root = _locate(arg, args.project)

    if bl_path is None:
        report = {"status": "VACUOUS_PASS",
                  "detail": "analog_block_list.json absent; "
                            "digital-only / pre-A1; gate inapplicable"}
        rc = 0
        print("[PASS] analog_block_list_emit_check: VACUOUS_PASS "
              "(no analog_block_list.json)")
    else:
        rc, report = _validate(bl_path, project_root)
        report["block_list"] = str(bl_path)
        if rc == 0:
            print(f"[PASS] analog_block_list_emit_check: "
                  f"{report['block_count']} block(s), schema + "
                  f"consistency OK")
        else:
            for f in report["findings"][:10]:
                print(f"  - {f}")
            print(f"[FAIL] analog_block_list_emit_check: {report['detail']}")

    if args.json:
        try:
            outp = Path(args.json)
            outp.parent.mkdir(parents=True, exist_ok=True)
            outp.write_text(json.dumps(report, indent=2,
                                       ensure_ascii=False) + "\n")
        except OSError as exc:
            print(f"error writing --json: {exc}", file=sys.stderr)
            return 2

    return rc


if __name__ == "__main__":
    sys.exit(main())
