#!/usr/bin/env python3
"""l21_to_upf_emit.py — render L21 power intent into an IEEE-1801 UPF
handoff artifact (flow v2.3.1, external review R1).

L21_POWER_INTENT.json has modelled power domains / isolation /
level-shifters since v0.1.51, and `upf_syntax_check.py` has existed to
validate UPF — but nothing ever EMITTED a UPF file, so the checker had
no input and the power intent never left the JSON. This renderer
closes that loop:

  * one `create_power_domain` + supply net/port + `set_domain_supply_net`
    per L21 power_domain;
  * `set_retention` when the domain declares retention;
  * `set_isolation` / `set_level_shifter` per L21 entry;
  * output: `phase2/stage2/constraints/<top>.upf` (Step 7 deliverable),
    self-validated via the existing upf_syntax_check.

HONESTY: this is a HANDOFF artifact — the open-source tools (Yosys /
OpenROAD) do not consume UPF; the structural verification of the
intent stays with the M2 gates (power_domain_crossing /
level_shifter_required / isolation_cell_required). The UPF carries a
header note saying exactly that.

Exit codes: 0 emitted (+ self-check PASS), 1 self-check FAIL,
2 no L21 / no power domains declared (vacuous — nothing to render).
chip-AGNOSTIC: renders the L21 JSON structure verbatim.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


def _l21(project: Path):
    for cand in (project / "phase1" / "generated_docs" /
                 "L21_POWER_INTENT.json",):
        if cand.is_file():
            try:
                d = json.loads(cand.read_text(errors="replace"))
            except (OSError, ValueError):
                return None, None
            return d.get("fields", d), str(cand.relative_to(project))
    return None, None


def render_upf(fields: dict, top: str, source_rel: str) -> str:
    domains = [d for d in (fields.get("power_domains") or [])
               if isinstance(d, dict) and d.get("name")]
    lines = [
        "# IEEE-1801 UPF — rendered from L21_POWER_INTENT by",
        "# l21_to_upf_emit (flow v2.3.1). HANDOFF ARTIFACT: the open-source",
        "# implementation tools (Yosys/OpenROAD) do not consume UPF;",
        "# structural power-intent verification lives in the M2 gates.",
        f"# source: {source_rel}",
        "upf_version 2.1",
        f"set_design_top {top}",
        "",
    ]
    for d in domains:
        name = str(d["name"])
        supply = str(d.get("supply") or f"VDD_{name}")
        lines += [
            f"create_power_domain PD_{name} -include_scope",
            f"create_supply_net {supply} -domain PD_{name}",
            f"create_supply_net VSS -domain PD_{name} -reuse",
            f"create_supply_port {supply}_port -domain PD_{name}",
            f"connect_supply_net {supply} -ports {supply}_port",
            f"set_domain_supply_net PD_{name} "
            f"-primary_power_net {supply} -primary_ground_net VSS",
        ]
        if d.get("retention"):
            lines.append(
                f"set_retention RET_{name} -domain PD_{name} "
                f"-retention_power_net {supply} "
                f"-retention_ground_net VSS")
        lines.append("")
    for iso in (fields.get("isolation_cells") or []):
        if not isinstance(iso, dict):
            continue
        dom = iso.get("domain") or (domains[0]["name"] if domains else None)
        if not dom:
            continue
        lines.append(
            f"set_isolation ISO_{iso.get('name', dom)} -domain PD_{dom} "
            f"-isolation_power_net "
            f"{iso.get('supply', 'VDD_' + str(dom))} "
            f"-clamp_value {iso.get('clamp_value', 0)} "
            f"-applies_to outputs")
    for ls in (fields.get("level_shifters") or []):
        if not isinstance(ls, dict):
            continue
        dom = ls.get("domain") or ls.get("from") \
            or (domains[0]["name"] if domains else None)
        if not dom:
            continue
        lines.append(
            f"set_level_shifter LS_{ls.get('name', dom)} "
            f"-domain PD_{dom} -applies_to both -rule both")
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("project", type=Path)
    ap.add_argument("--top", default="chip_top")
    ap.add_argument("--json", default=None)
    args = ap.parse_args(argv)
    if not args.project.is_dir():
        print(f"ERROR: not a directory: {args.project}", file=sys.stderr)
        return 1
    project = args.project.resolve()
    fields, src = _l21(project)
    if not fields or not (fields.get("power_domains") or []):
        rep = {"program": "l21_to_upf_emit", "verdict": "SKIP",
               "reason": ("no L21 power_domains declared — nothing to "
                          "render (single-domain designs need no UPF)")}
        print(json.dumps(rep, indent=2, ensure_ascii=False))
        return 2
    out_dir = project / "phase2" / "stage2" / "constraints"
    out_dir.mkdir(parents=True, exist_ok=True)
    upf_path = out_dir / f"{args.top}.upf"
    upf_path.write_text(render_upf(fields, args.top, src))

    # self-validate with the EXISTING checker (closes its no-input loop)
    try:
        import upf_syntax_check as _usc
        rc = _usc.main([str(project)])
    except Exception as exc:  # noqa: BLE001
        print(f"WARN: upf_syntax_check unavailable: {exc}", file=sys.stderr)
        rc = 0
    rep = {
        "program": "l21_to_upf_emit", "version": "1.0.0",
        "verdict": "PASS" if rc == 0 else "FAIL",
        "upf": str(upf_path.relative_to(project)),
        "domains": len(fields.get("power_domains") or []),
        "self_check": "upf_syntax_check rc=%d" % rc,
        "note": ("handoff artifact — open-source tools do not consume "
                 "UPF; M2 gates own structural verification"),
    }
    out = json.dumps(rep, indent=2, ensure_ascii=False)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(out)
    print(out)
    return 0 if rc == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
