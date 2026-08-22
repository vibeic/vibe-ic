#!/usr/bin/env python3
"""Emit one `vibeic.ppa.contract_declaration.v1` per arm, then build+check it
with the SHIPPED ppa_contract_build.py / ppa_contract_check.py.

The five identities, for a PnR search:
  problem        the SDC, the L19 spec and the RTL -- byte-identical in every arm
  implementation the routed DEF / gate netlist / GDS -- what the knobs moved
  analysis       the STA / power / DRC / LVS artefacts and the activity basis
  toolchain      the image digest and the tool versions
  agent_execution the deterministic runner; no agent judgement in the loop
"""
from __future__ import annotations
import json, subprocess, sys
from pathlib import Path

PLUGIN = Path("/home/reyerchu/_jppae2e/wt/vibe-ic-marketplace/plugins/vibe-ic")
PROGRAMS = PLUGIN / "programs"
DEFAULTS = {"die_um": "auto", "placement_density": "0.30",
            "spare_cell_density": "0.02"}
IMAGE = ("ghcr.io/vibeic/vibeic-eda@sha256:"
         "24b5074b686386084f87a03712b5f76e475201fbf2f2583b112d6e2c3eb55f3d")


def rel_exists(root: Path, rel: str) -> bool:
    return (root / rel).is_file()


def declaration(root: Path, label: str, knobs: dict) -> dict:
    def arte(role, rel):
        return {"role": role, "path": rel} if rel_exists(root, rel) else None

    problem = [arte("sdc", "phase2/stage2/constraints/spm.sdc"),
               arte("l19_spec", "phase1/generated_docs/L19_CONSTRAINTS_PDK.json"),
               arte("rtl_top", "phase2/stage1/rtl/spm.v")]
    # RESULT.md F-13: an artefact that VARIES WITH THE IMPLEMENTATION cannot sit
    # in the `analysis` identity, because the contract's own rule is that
    # analysis must MATCH across arms while implementation differs. The sign-off
    # reports are outputs of the implementation, so they are declared here --
    # every one is still hashed into the evidence manifest. `analysis` holds the
    # measurement CONFIGURATION: the corner/mode declaration and the RC stance.
    impl = [arte("routed_def", "phase3/stage3/pnr/spm.def"),
            arte("gate_netlist", "phase3/stage3/pnr/spm_pnr.v"),
            arte("gds", "phase3/stage4/gds/spm.gds"),
            arte("sta_signoff_multicorner", "phase3/stage3/sta/sta_spef_multicorner.rpt"),
            arte("sta_signoff_ocv", "phase3/stage3/sta/sta_mcorner_ocv.rpt"),
            arte("sta_single_corner", "phase3/stage3/sta/sta_spef_based.rpt"),
            arte("power", "reports/phase3/power.rpt"),
            arte("drc_signoff", "reports/phase3/drc_signoff.rpt"),
            arte("drc_vacuity", "reports/phase3/drc_vacuous.json"),
            arte("lvs", "reports/phase3/lvs.rpt"),
            arte("antenna", "reports/phase3/antenna.json")]
    analysis = [arte("corner_mode_declaration", "phase2/stage2/constraints/pvt_matrix.json"),
                arte("rc_corner_stance", "reports/phase3/multi_corner_spef_stance.json")]
    # RESULT.md F-14: reports/phase3/power_spm.tcl is the analysis CONFIGURATION
    # for the power axis and belongs in this identity, but the runner writes the
    # ABSOLUTE project path into it, so two runs of the same configuration hash
    # differently and PPA-C-012 refuses every comparison. It is left out of the
    # identity and named here rather than silently dropped.
    analysis_excluded = [{"role": "power_session_script",
                          "path": "reports/phase3/power_spm.tcl",
                          "why": "carries the absolute project path, so its "
                                 "digest is per-run and defeats identity "
                                 "matching (F-14)"}]
    missing = ([a for a in ("sdc", "l19_spec", "rtl_top") if not rel_exists(root, {
                    "sdc": "phase2/stage2/constraints/spm.sdc",
                    "l19_spec": "phase1/generated_docs/L19_CONSTRAINTS_PDK.json",
                    "rtl_top": "phase2/stage1/rtl/spm.v"}[a])])
    return {
        "schema": "vibeic.ppa.contract_declaration.v1",
        "run_label": label,
        "root_label": "project",
        "problem": {
            "artefacts": [a for a in problem if a],
            "facts": [
                {"key": "constraints.clk.period_ns", "value": 10.0,
                 "source": "sdc", "source_path": "phase2/stage2/constraints/spm.sdc"},
                {"key": "pdk.target", "value": "sky130",
                 "source": "l19_spec",
                 "source_path": "phase1/generated_docs/L19_CONSTRAINTS_PDK.json"},
            ],
        },
        "implementation": {
            "artefacts": [a for a in impl if a],
            "facts": [{"key": f"pnr.{k}", "value": v, "source": "runner_invocation"}
                      for k, v in sorted(knobs.items())],
        },
        "analysis": {
            "artefacts": [a for a in analysis if a],
            "facts": [
                {"key": "analysis.activity_basis", "value": "VECTORLESS",
                 "source": "runner"},
                {"key": "analysis.stage", "value": "post_route_extracted",
                 "source": "runner"},
            ],
        },
        "toolchain": {
            "images": [{"role": "eda", "ref": IMAGE, "verdict_bearing": True}],
            "tools": [
                {"name": "place_and_route", "status": "MEASURED",
                 "version": "26Q3-1535-g543c33894f"},
                {"name": "static_timing", "status": "MEASURED", "version": "2.7.0"},
                {"name": "synthesis", "status": "MEASURED", "version": "0.68+ 0048145dd"},
            ],
        },
        "agent_execution": {
            "facts": [{"key": "agent.autonomy", "value": "none", "source": "declared"},
                      {"key": "agent.role", "value": "deterministic_runner_only",
                       "source": "declared"}],
        },
        "policy": {
            "missing_power_basis": "REFUSE",
            "mutation_allow_list": ["pnr.*"],
            "mutation_forbidden": ["constraints.*", "pdk.*", "rtl.*"],
        },
        "candidate": {"mutations": [
            {"target": f"pnr.{k}", "from": DEFAULTS.get(k), "to": v}
            for k, v in sorted(knobs.items()) if DEFAULTS.get(k) != v]},
        "metrics": [],
        "analysis_identity_exclusions": analysis_excluded,
        "_missing_problem_artefacts": missing,
    }


def main(argv=None) -> int:
    a = argv if argv is not None else sys.argv[1:]
    if len(a) < 3:
        print("usage: gen_declaration.py <project> <out-dir> <label> [k=v ...]",
              file=sys.stderr)
        return 3
    root, out, label = Path(a[0]).resolve(), Path(a[1]).resolve(), a[2]
    knobs = dict(kv.split("=", 1) for kv in a[3:])
    out.mkdir(parents=True, exist_ok=True)
    decl = declaration(root, label, knobs)
    missing = decl.pop("_missing_problem_artefacts")
    dp = out / "declaration.json"
    dp.write_text(json.dumps(decl, indent=2) + "\n")
    if missing:
        print(f"[CANNOT CHECK] {label}: problem artefact(s) absent: {missing}",
              file=sys.stderr)
        return 2
    b = subprocess.run([sys.executable, str(PROGRAMS / "ppa_contract_build.py"),
                        "--declaration", str(dp), "--root", str(root),
                        "--out", str(out / "contract.json"),
                        "--json", str(out / "contract_build.json"),
                        "--no-image-labels"],
                       capture_output=True, text=True, timeout=300, cwd=str(PROGRAMS))
    print(f"[{label}] build rc={b.returncode}")
    if b.returncode != 0:
        print(b.stdout[-2500:]); print(b.stderr[-2500:], file=sys.stderr); return b.returncode
    c = subprocess.run([sys.executable, str(PROGRAMS / "ppa_contract_check.py"),
                        "--contract", str(out / "contract.json"),
                        "--json", str(out / "contract_check.json")],
                       capture_output=True, text=True, timeout=300, cwd=str(PROGRAMS))
    print(f"[{label}] check rc={c.returncode}")
    if c.returncode != 0:
        print(c.stdout[-2500:]); print(c.stderr[-2500:], file=sys.stderr)
    return c.returncode


if __name__ == "__main__":
    raise SystemExit(main())
