#!/usr/bin/env python3
"""Does the INPUT state facts for a layer that the layer did not extract?

WHY (the measured defect, chip-AGNOSTIC)
----------------------------------------
Phase 1's coverage percentage is a LITERAL metric: each auto-discovered literal
is credited when it appears anywhere in ``l_text``, the concatenation of every
``generated_docs/*.json``. So the question it asks is

    "does this token appear ANYWHERE in the union of 28 layers?"

and never

    "did it land in the layer that CONSUMES it?"

Measured on a real mixed-signal cell, every one of these was true at once::

    overall.pct = 100.0%   status = PASS   input_documents_unread = 0
    per_l_doc: {"name": "L21_POWER_INTENT", "evidence_count": 0}
    literals 'IOVDD' / 'CORE' / '1.8 V' / '1.2 V' -- all IN the denominator,
      all credited HIT, all credited from L1_DATASHEET / L2_FRS / L5_ADI_SPEC
    L21_POWER_INTENT.json: {"power_domains": [], ...}

The design STATES its rails in a two-row table under a heading called
``## Supplies / levels``. They landed in three PROSE layers. The layer the back
end builds the PDN from got zero. Downstream that is not cosmetic: an empty L21
makes every hard-macro PG pin `undeclared`, which FAILs the l21 pre-route gate,
which means no DEF, no GDS, and a mixed-signal top with no digital half. The
coverage number could not tell those two outcomes apart, so it printed 100 %
over the exact miss that later blocked the back end.

WHAT THIS DOES ABOUT IT
-----------------------
It follows the remedy this file's own neighbour already established for the
same defect shape (v1.7.72 / #499, the unread-document census): **do not reshape
the percentage** -- a literal-coverage figure is a literal-coverage figure and
rebasing it only moves the dishonesty -- but carry the census beside it and
degrade ``overall.status`` rather than averaging the miss away.

A layer is DEMANDED when a deterministic probe can show, from the design's own
input documents, that the input states facts belonging to that layer. It is
SILENT-EMPTY when it is demanded and its structured fields hold nothing.

WHY A PROBE AND NOT "FLAG EVERY EMPTY LAYER"
--------------------------------------------
Most empty layers are correctly empty. On the same run, 14 of 28 layers had
``evidence_count == 0`` -- L3 has no opcodes because the IP has no command
protocol, and the run says so itself ("structurally correct for non-protocol
IPs"). Flagging those would be a false-positive machine and would train readers
to ignore the field. A probe fires only on POSITIVE evidence that the input
stated something, so silence stays silent and only a real miss speaks.

Registry, not a special case: each probe declares its layer, how to count what
the INPUT states, and how to count what the LAYER holds. Adding a probe for
another layer is a new entry, not a new mechanism.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

PROGRAM = "phase1_layer_demand_probe"
VERSION = "1.0.0"


# ── probes ───────────────────────────────────────────────────────────────────
def _l21_input_states(project: Path) -> Dict[str, Any]:
    """Supply rails the design's own documents STATE, via the shipped
    doc-table producer. Never invents: see `l21_doc_supply_rail_synth`."""
    try:
        from l21_doc_supply_rail_synth import derive as _derive
    except Exception:                                       # noqa: BLE001
        return {"count": 0, "unavailable": True, "items": []}
    try:
        res = _derive(project)
    except Exception:                                       # noqa: BLE001
        return {"count": 0, "unavailable": True, "items": []}
    rails = res.get("rails") or []
    return {
        "count": len(rails),
        "unavailable": False,
        "items": [{"name": r["rail"], "use": r["use"],
                   "voltage_v": r["voltage_v"],
                   "evidence": r["evidence"]} for r in rails],
    }


def _l21_layer_holds(doc: Dict[str, Any]) -> int:
    f = (doc or {}).get("fields") or {}
    n = 0
    for key in ("power_rails", "power_domains"):
        v = f.get(key)
        if isinstance(v, list):
            n += len(v)
    return n


PROBES: List[Dict[str, Any]] = [
    {
        "layer": "L21_POWER_INTENT",
        "fact": "supply rail",
        "consumer": ("hardmacro_supply_intent.declared_rails -> the l21 "
                     "pre-route gate -> PDN / detailed routing"),
        "input_states": _l21_input_states,
        "layer_holds": _l21_layer_holds,
    },
]


# ── evaluation ───────────────────────────────────────────────────────────────
def _read_layer(project: Path, layer: str) -> Optional[Dict[str, Any]]:
    p = project / "phase1" / "generated_docs" / f"{layer}.json"
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:                                       # noqa: BLE001
        return None


def evaluate(project: Path) -> Dict[str, Any]:
    """``{"silent_empty": [...], "layers": [...], "probes_run": N}``.

    ``silent_empty`` is the load-bearing list: a layer the INPUT demands and
    the OUTPUT left empty. Empty list = nothing to say, which is the ordinary
    case and must stay quiet.
    """
    layers: List[Dict[str, Any]] = []
    silent: List[str] = []
    for probe in PROBES:
        layer = probe["layer"]
        stated = probe["input_states"](project)
        doc = _read_layer(project, layer)
        if doc is None:
            layers.append({"layer": layer, "status": "LAYER_ABSENT",
                           "input_states": stated["count"], "layer_holds": 0})
            continue
        holds = probe["layer_holds"](doc)
        if stated.get("unavailable"):
            status = "PROBE_UNAVAILABLE"
        elif stated["count"] == 0:
            status = "NOT_DEMANDED"
        elif holds == 0:
            status = "SILENT_EMPTY"
            silent.append(layer)
        else:
            status = "SATISFIED"
        layers.append({
            "layer": layer,
            "status": status,
            "fact": probe["fact"],
            "consumer": probe["consumer"],
            "input_states": stated["count"],
            "layer_holds": holds,
            "stated_items": stated["items"],
        })
    return {"probes_run": len(PROBES), "layers": layers,
            "silent_empty": silent}


def summary_line(result: Dict[str, Any]) -> str:
    """One line for the runner SUMMARY, so a reader cannot see the percentage
    without also seeing this."""
    silent = result.get("silent_empty") or []
    if not silent:
        demanded = [l for l in result["layers"]
                    if l["status"] in ("SATISFIED", "SILENT_EMPTY")]
        return (f"Layer demand:        {len(demanded)} layer(s) demanded by "
                f"the input, 0 silently empty")
    return ("Layer demand:        **{n} LAYER(S) DEMANDED BY THE INPUT AND "
            "EMPTY**: {names}".format(n=len(silent), names=", ".join(silent)))


def main(argv: Optional[List[str]] = None) -> int:
    import argparse
    import sys
    ap = argparse.ArgumentParser(
        description="Report layers the input states facts for and the layer "
                    "left empty.")
    ap.add_argument("project")
    ap.add_argument("--json", help="write the result JSON here")
    args = ap.parse_args(argv)

    proj = Path(args.project).resolve()
    res = evaluate(proj)

    print(f"=== {PROGRAM} ===")
    for l in res["layers"]:
        print(f"  {l['layer']:22s} {l['status']:18s} "
              f"input_states={l['input_states']} layer_holds={l['layer_holds']}")
        if l["status"] == "SILENT_EMPTY":
            print(f"    the input states {l['input_states']} {l['fact']}(s) "
                  f"and this layer holds none.")
            print(f"    consumer: {l['consumer']}")
            for it in l.get("stated_items") or []:
                ev = it["evidence"]
                print(f"      - {it['name']} ({it['use']}, {it['voltage_v']} V) "
                      f"[{ev['file']}:{ev['line']}]")
    print(f"  silent_empty: {res['silent_empty'] or 'none'}")

    if args.json:
        Path(args.json).write_text(
            json.dumps(res, indent=2, ensure_ascii=False) + "\n")

    return 1 if res["silent_empty"] else 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
