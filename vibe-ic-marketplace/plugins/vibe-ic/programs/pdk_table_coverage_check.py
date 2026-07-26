#!/usr/bin/env python3
"""pdk_table_coverage_check.py — registering a PDK in one table registers it
in none of the others, and nothing said so.

THIS GATE BLOCKS (rc=1) when a PDK gains a per-table gap that is not recorded.

WHY IT EXISTS (#410, and #389's shape in a second table)
--------------------------------------------------------
`pdk_registry.json` is not the only per-PDK table in this plugin. Three
programs carry their own, keyed independently:

    fault_atpg_run.PDK_CONFIG                 the ATPG cell model
    analog_pdk_deck_context._KNOWN_FAMILIES   the SPICE model library + corners
    analog_tb_supply_pdk_check.PDK_FLAVORS    the supply-voltage contract

Adding an entry to the registry adds it to none of them, and nothing reported
the gap. What that cost, measured end to end in #410: an IHP-mapped netlist
matched none of the ATPG sniff's three cell-name patterns, so the engine was
handed the SKY130A cell model while the artefact recorded `generic_unmapped` —
a substitution the deliverable did not disclose because nothing knew a
substitution had happened.

THE SPELLINGS DIFFER ON PURPOSE, and that is why the mapping is DECLARED
rather than guessed. The registry names a specific enablement (`sky130A`,
`gf180mcuD`); these tables are keyed by process FAMILY (`sky130`, `gf180`),
because the ATPG cell model and the SPICE corners are the same across the
enablements of one family. A checker that inferred `sky130A` -> `sky130` by
stripping a suffix would be a fourth hand-maintained rule, which is the
defect #409 is about. So each registry entry declares its own
`per_pdk_table_key`, and the registry stays the single source.

WHAT A GAP MEANS, and why most are not defects. A digital-only PDK has no
business in the analog SPICE tables; `nangate45` and `asap7` are not
manufacturable enablements and have no supply contract to state. The gate's
job is not to demand every PDK appear in every table — it is to make each
absence a RECORDED one, so that the next PDK added to the registry cannot
acquire three silent gaps the way `ihp-sg13g2` did.

Shrink-only: the recorded set may lose entries freely and may not gain one
without an explicit `--write-baseline`, which refuses to grow.
"""
from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_BASELINE = _HERE / "pdk_table_coverage_baseline.json"

# (module, attribute, human name). Imported rather than parsed: these are
# plain dict literals and an import failure is itself worth failing on — a
# table nobody can load is a table nobody can check.
_TABLES = (
    ("fault_atpg_run", "PDK_CONFIG", "ATPG cell model"),
    ("analog_pdk_deck_context", "_KNOWN_FAMILIES", "SPICE deck family"),
    ("analog_tb_supply_pdk_check", "PDK_FLAVORS", "supply contract"),
)


def _load_tables():
    sys.path.insert(0, str(_HERE))
    out, errs = {}, []
    for mod, attr, label in _TABLES:
        try:
            m = importlib.import_module(mod)
            t = getattr(m, attr)
            out[label] = set(t)
        except Exception as exc:                       # noqa: BLE001
            errs.append(f"{mod}.{attr}: {type(exc).__name__}: {exc}")
    return out, errs


def audit(registry: Path = None, baseline: Path = None) -> dict:
    registry = registry or (_HERE / "pdk_registry.json")
    baseline = baseline or _BASELINE
    reg = json.loads(registry.read_text())
    tables, errs = _load_tables()
    known = set()
    if baseline.is_file():
        known = set(json.loads(baseline.read_text()).get("known", []))

    gaps, undeclared = [], []
    for e in reg.get("pdks") or []:
        name = e.get("name")
        if not name or not e.get("container_path"):
            # The auto-detect sentinel declares no directory and is not a PDK.
            continue
        key = e.get("per_pdk_table_key")
        if key is None:
            undeclared.append(name)
            continue
        for label, keys in tables.items():
            if key not in keys:
                gaps.append(f"{name} ({key}) — {label}")

    new_gaps = sorted(set(gaps) - known)
    resolved = sorted(known - set(gaps)) if tables else []
    return {"program": "pdk_table_coverage_check", "tables": len(tables),
            "table_errors": errs, "gaps": sorted(set(gaps)),
            "new_gaps": new_gaps, "resolved": resolved,
            "undeclared": sorted(undeclared),
            "verdict": "FAIL" if (errs or new_gaps or undeclared) else "PASS"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--registry", default=None)
    ap.add_argument("--baseline", default=None)
    ap.add_argument("--write-baseline", action="store_true",
                    help="record the CURRENT gaps; it may only ever shrink")
    ap.add_argument("--json", dest="json_out")
    a = ap.parse_args(argv)
    reg = Path(a.registry) if a.registry else None
    bl = Path(a.baseline) if a.baseline else _BASELINE

    rep = audit(reg, bl)
    if a.json_out:
        Path(a.json_out).write_text(json.dumps(rep, indent=2) + "\n")

    if a.write_baseline:
        if not bl.is_file():
            # FIRST record. There is nothing to shrink from, and refusing here
            # would make the register impossible to create — the shrink-only
            # rule would have blocked its own bootstrap. Every later write is
            # judged against this one.
            bl.write_text(json.dumps({"known": rep["gaps"]}, indent=2) + "\n")
            print(f"wrote {bl} — INITIAL record of "
                  f"{len(rep['gaps'])} pre-existing gap(s); it may only "
                  f"shrink from here.")
            return 0
        prev = set(json.loads(bl.read_text()).get("known", []))
        if set(rep["gaps"]) - prev:
            print(f"[FAIL] refusing to GROW the recorded gap set "
                  f"({len(prev)} -> {len(rep['gaps'])}). A new gap is a new "
                  f"silent substitution; fix it or state why it is correct.")
            for g in sorted(set(rep["gaps"]) - prev):
                print(f"   + {g}")
            return 1
        bl.write_text(json.dumps({"known": rep["gaps"]}, indent=2) + "\n")
        print(f"wrote {bl} ({len(rep['gaps'])} recorded gap(s))")
        return 0

    if rep["table_errors"]:
        print("[FAIL] a per-PDK table could not be loaded — it cannot be "
              "checked, and an unchecked table is not a clean one:")
        for e in rep["table_errors"]:
            print(f"   {e}")
        return 1
    if rep["undeclared"]:
        print(f"[FAIL] {len(rep['undeclared'])} registry PDK(s) declare no "
              f"`per_pdk_table_key`, so nothing can say whether the per-PDK "
              f"tables cover them: {rep['undeclared']}")
        return 1
    if rep["new_gaps"]:
        print(f"[FAIL] {len(rep['new_gaps'])} NEW per-PDK table gap(s) — a "
              f"PDK the registry accepts that a table does not know. This is "
              f"how an IHP netlist got the SKY130A ATPG model (#410):")
        for g in rep["new_gaps"]:
            print(f"   {g}")
        return 1
    msg = (f"[PASS] pdk_table_coverage_check: {rep['tables']} per-PDK table(s) "
           f"vs the registry — no new gap.")
    if rep["gaps"]:
        msg += f" {len(rep['gaps'])} recorded gap(s) unchanged."
    if rep["resolved"]:
        msg += (f" {len(rep['resolved'])} recorded gap(s) now RESOLVE — "
                f"shrink the baseline: {rep['resolved']}")
    print(msg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
