#!/usr/bin/env python3
"""wafer_map_pattern_classify.py — D3 program-first extraction of the
yield-diagnostic skill's spatial-signature -> root-cause LOOKUP TABLE.

Doctrine
--------
`skills/yield-diagnostic/SKILL.md` step "Random vs systematic" carried a
fixed signature->category table in prose:

    "Edge ring = process.  Clusters = defects.  Uniform = design marginality."

That mapping is a deterministic lookup — the same shape as
`ir_drop_triage_classify.py`'s cause->fix table — yet it lived only in skill
prose and was delegated to no program.  This program owns the table.

NO-FABRICATION SCOPE
--------------------
The skill spells out the *mapping* (signature -> root-cause class) but gives
NO numeric thresholds for deciding which spatial class a raw wafer map *is*
(e.g. "what edge-ring fraction counts as an edge ring").  Inventing such a
threshold would be fabrication, so this program does NOT auto-classify a raw
map into edge/cluster/uniform from invented cut-points.  Instead it:

  1. LOOKUP MODE (the deterministic spec table): given an already-determined
     `spatial_class` in {edge, cluster, uniform, random}, emit the spec's
     root-cause bucket {process, defects, design_marginality, indeterminate}.
     Zero invented values — pure table.
  2. FEATURE MODE (objective measurement, optional): from a real
     `wafer_map.csv` (x,y,bin; bin==1 == pass by convention, or an explicit
     pass-bin set), compute *objective* spatial fail-distribution metrics
     (edge_fail_fraction, interior_fail_fraction, fail_fraction, die counts).
     These are measurements, not classifications — the program reports them so
     a downstream vision/LLM step (or the caller) can pick `spatial_class`.
     The program never converts features into a class via an invented cut.

So the deterministic table is extracted; the genuinely-judgment step (raw map
-> spatial_class) stays out of the program (no fabricated threshold).

Verdicts
--------
* PASS    (rc=0) — a valid `spatial_class` was supplied (or read) and mapped
                   to its spec root-cause bucket; any wafer map supplied was
                   parsed and objective features reported.
* FAIL    (rc=1) — `spatial_class` is missing/garbage AND none can be read;
                   OR a supplied wafer map is empty/unparseable; OR a supplied
                   class string is not one of the four spec signatures.
                   Honest failure — never a vacuous PASS on missing data.
* SKIP    (rc=2) — input path/dir does not exist (operational, not silicon).

chip-AGNOSTIC.  No vendor / IC / tool-specific data hard-coded.

Usage
-----
    # Lookup the spec table directly:
    python3 wafer_map_pattern_classify.py --spatial-class edge [--json out.json]

    # Read class from a JSON artefact, optionally measure a wafer map:
    python3 wafer_map_pattern_classify.py <dir_or_json> [--json out.json]
    python3 wafer_map_pattern_classify.py <project_dir> [--json out.json]
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


_GATE_NAME = "wafer_map_pattern_classify"

# ---- The deterministic spec table (verbatim from the skill prose) ----------
# "Edge ring = process.  Clusters = defects.  Uniform = design marginality."
# A fourth signature, "random", is the explicit no-systematic case the skill's
# output format and "Do not conflate random defects with systematic failures"
# rule both name; it maps to no single root cause.
SPATIAL_CLASSES: Tuple[str, ...] = ("edge", "cluster", "uniform", "random")

CLASS_TO_ROOT_CAUSE: Dict[str, str] = {
    "edge":    "process",              # edge ring  -> process
    "cluster": "defects",              # clusters   -> defects
    "uniform": "design_marginality",   # uniform    -> design marginality
    "random":  "indeterminate",        # random     -> no single systematic cause
}

ROOT_CAUSE_DESC: Dict[str, str] = {
    "process":            "Process / fab issue (edge-ring spatial signature)",
    "defects":            "Random/particle defects (clustered spatial signature)",
    "design_marginality": "Design marginality e.g. setup/hold (uniform signature)",
    "indeterminate":      "No single systematic cause (random scatter)",
}

# Aliases callers may pass for the spatial class — normalised to the four
# canonical signatures.  These are SYNONYMS for the same spec signatures, not
# new categories, so no fabrication.
_CLASS_ALIASES: Dict[str, str] = {
    "edge": "edge", "edge_ring": "edge", "edge-ring": "edge", "ring": "edge",
    "cluster": "cluster", "clusters": "cluster", "clustered": "cluster",
    "uniform": "uniform", "uniformly": "uniform", "global": "uniform",
    "random": "random", "scatter": "random", "scattered": "random",
}

# Pass-bin convention for wafer_map.csv: bin==1 is "good die" (matches the
# existing fixture and SEMI-style maps).  Callers may override.
_DEFAULT_PASS_BINS = {"1"}


def normalize_class(raw: Optional[str]) -> Optional[str]:
    """Map a raw class string to one of the four spec signatures, else None."""
    if raw is None:
        return None
    key = str(raw).strip().lower().replace(" ", "_")
    return _CLASS_ALIASES.get(key)


def lookup_root_cause(spatial_class: str) -> Dict[str, Any]:
    """The deterministic spec lookup — class -> root cause.

    Raises KeyError only for a non-spec class (caller validates first)."""
    root = CLASS_TO_ROOT_CAUSE[spatial_class]
    return {
        "spatial_class": spatial_class,
        "root_cause": root,
        "root_cause_desc": ROOT_CAUSE_DESC[root],
    }


def _looks_numeric(cell: str) -> bool:
    try:
        float(cell.strip())
        return True
    except ValueError:
        return False


def measure_wafer_map(path: Path,
                      pass_bins=None) -> Dict[str, Any]:
    """Compute OBJECTIVE spatial fail-distribution metrics from a wafer map.

    These are measurements, NOT a classification (no invented threshold turns
    them into a spatial_class).  Returns die counts + edge/interior fail
    fractions so a downstream vision/LLM step can pick the spatial_class.

    Expects rows of (x, y, bin).  bin in `pass_bins` == good die.
    Raises ValueError on empty/garbage.
    """
    pass_bins = set(pass_bins) if pass_bins else set(_DEFAULT_PASS_BINS)
    with path.open(newline="") as fh:
        rows = [r for r in csv.reader(fh) if any(c.strip() for c in r)]
    if not rows:
        raise ValueError("wafer map contains no rows")

    # Header heuristic: first row has no purely-numeric cell.
    has_header = not any(_looks_numeric(c) for c in rows[0])
    data = rows[1:] if has_header else rows
    if not data:
        raise ValueError("wafer map contains no die-record rows")

    dies: List[Tuple[int, int, str]] = []
    for r in data:
        if len(r) < 3:
            raise ValueError(f"row has < 3 columns: {r!r}")
        try:
            x = int(float(r[0].strip()))
            y = int(float(r[1].strip()))
        except ValueError as e:
            raise ValueError(f"non-integer coordinate in row {r!r}: {e}")
        b = r[2].strip()
        dies.append((x, y, b))

    if not dies:
        raise ValueError("no parseable die records")

    xs = [d[0] for d in dies]
    ys = [d[1] for d in dies]
    xmin, xmax = min(xs), max(xs)
    ymin, ymax = min(ys), max(ys)

    total = len(dies)
    good = sum(1 for d in dies if d[2] in pass_bins)
    fails = [d for d in dies if d[2] not in pass_bins]
    n_fail = len(fails)

    # Edge die: on the bounding-box perimeter. Objective, geometric — no cut.
    def _is_edge(x: int, y: int) -> bool:
        return x in (xmin, xmax) or y in (ymin, ymax)

    edge_total = sum(1 for d in dies if _is_edge(d[0], d[1]))
    interior_total = total - edge_total
    edge_fail = sum(1 for d in fails if _is_edge(d[0], d[1]))
    interior_fail = n_fail - edge_fail

    return {
        "total_die": total,
        "good_die": good,
        "fail_die": n_fail,
        "fail_fraction": (round(n_fail / total, 6) if total else None),
        "edge_die": edge_total,
        "interior_die": interior_total,
        "edge_fail_die": edge_fail,
        "interior_fail_die": interior_fail,
        "edge_fail_fraction": (round(edge_fail / edge_total, 6)
                               if edge_total else None),
        "interior_fail_fraction": (round(interior_fail / interior_total, 6)
                                   if interior_total else None),
        "bbox": {"xmin": xmin, "xmax": xmax, "ymin": ymin, "ymax": ymax},
        "pass_bins": sorted(pass_bins),
        "note": ("objective measurements only — spatial_class is NOT inferred "
                 "from these (no spec threshold exists; that step is judgment)"),
    }


# Where to read a stated spatial_class from, if a project dir / JSON is given.
_CLASS_FIELDS = ("spatial_class", "wafer_spatial_class", "spatial_pattern",
                 "pattern_class", "spatial")
_DIAG_JSON_CANDIDATES = [
    "phase3/stage5_manufacturing/yield_diagnostic.json",
    "manufacturing/yield_diagnostic.json",
    "yield_diagnostic.json",
]
_WAFER_MAP_CANDIDATES = [
    "phase3/stage5_manufacturing/wafer_map.csv",
    "manufacturing/wafer_map.csv",
    "wafer_map.csv",
]


def _first_existing(base: Path, candidates) -> Tuple[Optional[str], Optional[Path]]:
    for rel in candidates:
        p = base / rel
        if p.is_file():
            return rel, p
    return None, None


def _read_class_from_json(doc: dict) -> Optional[str]:
    for f in _CLASS_FIELDS:
        if f in doc and doc[f] is not None:
            return str(doc[f])
    return None


def _emit(args, verdict, payload, findings):
    out = {
        "gate": _GATE_NAME,
        "verdict": verdict,
        **payload,
        "findings": findings,
    }
    if getattr(args, "json", None):
        op = Path(args.json)
        op.parent.mkdir(parents=True, exist_ok=True)
        op.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
    print(f"=== {_GATE_NAME} ===")
    print(f"  verdict: {verdict}")
    if payload.get("spatial_class"):
        print(f"  spatial_class: {payload['spatial_class']} -> "
              f"root_cause: {payload.get('root_cause')}")
    for f in findings:
        if f["severity"] in ("FAIL", "INFO"):
            print(f"  [{f['severity']}] {f['rule']}: {f['message']}")
    return out


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("input", nargs="?",
                   help="project dir OR a JSON artefact carrying spatial_class")
    p.add_argument("--spatial-class", default=None,
                   help="one of: edge / cluster / uniform / random (or alias)")
    p.add_argument("--pass-bins", default=None,
                   help="comma-separated bin codes counted as good (default '1')")
    p.add_argument("--json", default=None)
    args = p.parse_args(argv)

    pass_bins = (set(s.strip() for s in args.pass_bins.split(",") if s.strip())
                 if args.pass_bins else None)

    findings: List[Dict[str, str]] = []
    raw_class: Optional[str] = args.spatial_class
    map_path: Optional[Path] = None
    map_rel: Optional[str] = None

    # ---- Resolve input source -----------------------------------------
    if args.input is not None:
        ip = Path(args.input)
        if not ip.exists():
            print(f"[{_GATE_NAME}] input not found: {ip}", file=sys.stderr)
            return 2
        if ip.is_file():
            # treat as a JSON artefact
            try:
                doc = json.loads(ip.read_text())
                if not isinstance(doc, dict):
                    raise ValueError("top-level JSON is not an object")
            except Exception as e:  # noqa: BLE001
                findings.append({"severity": "FAIL", "rule": "JSON_UNPARSEABLE",
                                 "message": f"cannot parse {ip}: {e}"})
                _emit(args, "FAIL", {"spatial_class": None}, findings)
                return 1
            if raw_class is None:
                raw_class = _read_class_from_json(doc)
        else:
            # project dir: try diagnostic JSON for the class, wafer map for features
            if raw_class is None:
                drel, dpath = _first_existing(ip, _DIAG_JSON_CANDIDATES)
                if dpath is not None:
                    try:
                        doc = json.loads(dpath.read_text())
                        if isinstance(doc, dict):
                            raw_class = _read_class_from_json(doc)
                    except Exception:  # noqa: BLE001
                        pass
            map_rel, map_path = _first_existing(ip, _WAFER_MAP_CANDIDATES)

    # ---- Optional objective feature measurement ------------------------
    features = None
    if map_path is not None:
        try:
            features = measure_wafer_map(map_path, pass_bins=pass_bins)
            findings.append({
                "severity": "INFO", "rule": "WAFER_MAP_MEASURED",
                "message": f"{map_rel}: total_die={features['total_die']} "
                           f"fail_die={features['fail_die']} "
                           f"edge_fail_frac={features['edge_fail_fraction']}",
            })
        except Exception as e:  # noqa: BLE001
            findings.append({"severity": "FAIL", "rule": "WAFER_MAP_BAD",
                             "message": f"cannot measure {map_rel}: {e}"})
            _emit(args, "FAIL", {"spatial_class": None,
                                 "wafer_map_features": None}, findings)
            return 1

    # ---- The deterministic lookup --------------------------------------
    if raw_class is None:
        findings.append({
            "severity": "FAIL", "rule": "NO_SPATIAL_CLASS",
            "message": "no spatial_class supplied (--spatial-class) nor readable "
                       "from input; the raw-map->class step is judgment and is "
                       "not fabricated here — cannot perform the lookup",
        })
        _emit(args, "FAIL",
              {"spatial_class": None, "wafer_map_features": features}, findings)
        return 1

    norm = normalize_class(raw_class)
    if norm is None:
        findings.append({
            "severity": "FAIL", "rule": "BAD_SPATIAL_CLASS",
            "message": f"spatial_class {raw_class!r} is not one of "
                       f"{list(SPATIAL_CLASSES)} (nor a known alias)",
        })
        _emit(args, "FAIL",
              {"spatial_class": None, "wafer_map_features": features}, findings)
        return 1

    lk = lookup_root_cause(norm)
    findings.append({
        "severity": "INFO", "rule": "ROOT_CAUSE_LOOKUP",
        "message": f"{norm} -> {lk['root_cause']} ({lk['root_cause_desc']})",
    })

    _emit(args, "PASS", {**lk, "wafer_map_features": features}, findings)
    return 0


if __name__ == "__main__":
    sys.exit(main())
