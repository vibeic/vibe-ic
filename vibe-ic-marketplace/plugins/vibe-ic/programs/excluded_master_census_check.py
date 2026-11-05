#!/usr/bin/env python3
"""ADVISORY per-step census of masters excluded by the run's cell policy.

The rollout is advisory because existing published runs may contain cells
inserted before this policy reached CTS/hold. A missing policy or unreadable
tool DEF is NOT_MEASURED; zero hits is PASS only over a nonempty placed
population. The DEF grammar is read by tap_row_coverage_check, the existing
tool-output reader, rather than a second COMPONENTS parser.
"""
from __future__ import annotations

import os as _os
import sys as _sys
if _os.path.dirname(_os.path.abspath(__file__)) not in _sys.path:
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))

import argparse
import fnmatch
import hashlib
import json
from pathlib import Path
from typing import Any

from _atomic_artefact import write_json
from tap_row_coverage_check import read_def


def audit(config: Path, state: Path, step: str, *, policy_complete: bool = True
          ) -> dict[str, Any]:
    """Judge the master population the named tool step actually wrote."""
    base: dict[str, Any] = {"program": "excluded_master_census_check",
                            "step": step, "severity": "ADVISORY",
                            "config": str(config), "state": str(state)}
    if not policy_complete:
        return dict(base, verdict="NOT_MEASURED",
                    reason="EXCLUSION_POLICY_LIBERTY_UNREADABLE")
    try:
        cfg = json.loads(config.read_text())
        view = json.loads(state.read_text())
        policy = cfg.get("EXTRA_EXCLUDED_CELLS")
        if not isinstance(policy, list) or any(not isinstance(x, str) for x in policy):
            raise ValueError("EXCLUSION_POLICY_UNDECLARED_OR_INVALID")
        path = Path(view["def"])
        if not path.is_absolute():
            path = state.parent / path
        body = path.read_text(errors="replace")
        population = read_def(body)["components"]
        if not population:
            raise ValueError("PLACED_POPULATION_EMPTY")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return dict(base, verdict="NOT_MEASURED", reason=str(exc))
    hits = [{"instance": inst, "master": master}
            for inst, master, *_ in population
            if any(fnmatch.fnmatchcase(master, pattern) for pattern in policy)]
    return dict(base, verdict="FAIL" if hits else "PASS",
                finding="EXCLUDED_MASTER_INSERTED" if hits else None,
                policy=policy, population=len(population), excluded_count=len(hits),
                excluded_instances=hits,
                def_path=str(path), def_sha256=hashlib.sha256(body.encode()).hexdigest())


def write_audit(config: Path, state: Path, step: str, output: Path,
                *, policy_complete: bool = True
                ) -> dict[str, Any]:
    result = audit(config, state, step, policy_complete=policy_complete)
    write_json(output, result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--step", required=True)
    parser.add_argument("--json", type=Path, required=True)
    args = parser.parse_args(argv)
    result = write_audit(args.config, args.state, args.step, args.json)
    print(f"{result['verdict']}: excluded_master_census_check "
          f"{args.step} {result.get('excluded_count', 'unknown')}")
    return 0  # advisory during corpus sweep; the JSON carries the verdict


if __name__ == "__main__":
    raise SystemExit(main())
