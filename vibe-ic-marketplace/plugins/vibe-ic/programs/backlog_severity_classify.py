#!/usr/bin/env python3
"""
backlog_severity_classify.py — deterministic severity table-lookup for
phase1-coverage-loop ORGANIC backlog issues.

Extracted from skills/phase1-coverage-loop/SKILL.md Step 2:

    Set `severity: HIGH` if the missing tokens are in an L3/L4/L8/L9
    layer (structural-RTL-affecting), `MEDIUM` otherwise.

The L-layer -> severity assignment is a pure table lookup, not a
judgment: the *which layer should have caught this token* decision is
the LLM's job (Step 1 review), but once a backlog item names the
affected layer(s), the HIGH/MEDIUM verdict is mechanical.

Structural-RTL-affecting layers (HIGH):
    L3  interface / port contract
    L4  register / memory map
    L8  micro-architecture / datapath
    L9  RTL contract
Any other recognised layer (L1, L2, L5, L6, L7, L10, L11, L12, L13)
classifies MEDIUM.

If ANY affected layer is in the HIGH set, the item is HIGH (a backlog
issue spanning L2 + L4 is HIGH, because the L4 gap is structural).

Usage
-----
    python3 backlog_severity_classify.py --layers L4,L2 [--json <out>]
    python3 backlog_severity_classify.py --file <backlog.yaml> [--json <out>]

`--layers` takes a comma-separated list of L-ids (case-insensitive,
"L4" or "4" both accepted). `--file` reads a backlog YAML/JSON and
pulls its `affected_layers` (list) or `layer` (scalar) field.

Exit codes
----------
    0  classification succeeded (severity printed; HIGH and MEDIUM are
       both exit 0 — neither is an error)
    1  no recognisable layer id supplied (honest FAIL — we will not
       silently default to MEDIUM on garbage like "L99" or "banana";
       a backlog item with no decodable layer cannot be classified)
    2  usage error (neither --layers nor --file, missing file)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import List, Set

try:
    import yaml
    HAS_YAML = True
except ImportError:  # pragma: no cover - yaml usually present
    HAS_YAML = False


HIGH_LAYERS = {"L3", "L4", "L8", "L9"}
KNOWN_LAYERS = {f"L{i}" for i in range(1, 14)}  # L1..L13
_LAYER_RE = re.compile(r"^[Ll]?(\d{1,2})$")


def normalise_layer(tok: str) -> str | None:
    """Return canonical 'L<n>' for a recognised 1..13 layer, else None."""
    m = _LAYER_RE.match(tok.strip())
    if not m:
        return None
    canon = f"L{int(m.group(1))}"
    return canon if canon in KNOWN_LAYERS else None


def classify(layers: Set[str]) -> str:
    """HIGH if any layer in HIGH_LAYERS, else MEDIUM. Caller must pass
    only normalised, recognised layers."""
    return "HIGH" if (layers & HIGH_LAYERS) else "MEDIUM"


def _layers_from_file(path: Path) -> List[str]:
    text = path.read_text(errors="replace")
    data: dict = {}
    if HAS_YAML:
        loaded = yaml.safe_load(text)
        if isinstance(loaded, dict):
            data = loaded
    if not data:
        try:
            loaded = json.loads(text)
            if isinstance(loaded, dict):
                data = loaded
        except Exception:  # noqa: BLE001
            data = {}
    raw: List = []
    al = data.get("affected_layers")
    if isinstance(al, list):
        raw.extend(al)
    elif isinstance(al, str):
        raw.extend(re.split(r"[,\s]+", al))
    one = data.get("layer")
    if isinstance(one, str):
        raw.append(one)
    elif isinstance(one, (int, float)):
        raw.append(str(int(one)))
    return [str(x) for x in raw if str(x).strip()]


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Deterministic HIGH/MEDIUM severity classifier for "
                    "phase1-coverage-loop backlog issues.")
    parser.add_argument("--layers", default=None,
                        help="Comma-separated affected L-layer ids, "
                             "e.g. 'L4,L2'.")
    parser.add_argument("--file", default=None,
                        help="Backlog YAML/JSON with affected_layers / "
                             "layer field.")
    parser.add_argument("--json", default=None,
                        help="Write the JSON report here.")
    args = parser.parse_args(argv)

    raw_tokens: List[str] = []
    if args.layers:
        raw_tokens.extend(t for t in re.split(r"[,\s]+", args.layers) if t)
    if args.file:
        fp = Path(args.file)
        if not fp.is_file():
            print(f"ERROR — backlog file not found: {fp}")
            return 2
        raw_tokens.extend(_layers_from_file(fp))
    if not args.layers and not args.file:
        print("ERROR — supply --layers or --file.")
        return 2

    recognised: Set[str] = set()
    unrecognised: List[str] = []
    for tok in raw_tokens:
        canon = normalise_layer(tok)
        if canon:
            recognised.add(canon)
        else:
            unrecognised.append(tok)

    if not recognised:
        report = {
            "gate": "backlog_severity_classify",
            "verdict": "FAIL",
            "severity": None,
            "recognised_layers": [],
            "unrecognised_tokens": unrecognised,
            "reason": "no recognisable L1..L13 layer id supplied",
        }
        if args.json:
            Path(args.json).write_text(json.dumps(report, indent=2))
        print("FAIL — no recognisable L1..L13 layer id "
              f"(got: {raw_tokens}).")
        return 1

    severity = classify(recognised)
    report = {
        "gate": "backlog_severity_classify",
        "verdict": "PASS",
        "severity": severity,
        "recognised_layers": sorted(recognised),
        "high_layers_present": sorted(recognised & HIGH_LAYERS),
        "unrecognised_tokens": unrecognised,
    }
    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=2))
    print(f"{severity} — affected layers "
          f"{sorted(recognised)} "
          f"(HIGH set L3/L4/L8/L9 "
          f"{'hit' if (recognised & HIGH_LAYERS) else 'not hit'}).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
