#!/usr/bin/env python3
"""Emit one `vibeic.ppa.contract_declaration.v1` per arm, then build and check
it with the SHIPPED ppa_contract_build.py / ppa_contract_check.py.

THE ONE DECLARATION CHANGE A CROSS-LAYER SEARCH REQUIRES, STATED OUT LOUD
=========================================================================
The published PnR-only run declared `phase2/stage1/rtl/spm.v` in the PROBLEM
identity, and for a PnR-only search that is right: the RTL is an input that no
knob touches, so putting it in `problem` makes "same problem" checkable by hash.

A cross-layer search REWRITES that file.  Left in `problem`, every cross-layer
arm would differ from the baseline in the problem identity and
`ppa_problem_integrity_check` would refuse the comparison — not because the two
runs solve different problems, but because the declaration confused the
SPECIFICATION with one implementation of it.

So this lane declares:

    problem         the design's own input documents (input/docs/*.md), the
                    SDC, and the L19 PDK spec — what the chip has to be
    implementation  the RTL, the synthesis netlist, the routed DEF, the gate
                    netlist and the GDS — how this arm chose to be it

and the LICENCE for that move is not an assertion, it is a proof: every arm
whose RTL differs from the baseline's carries a
`crosslayer_rewrite_equivalence` verdict, and an arm without a PASS verdict is
published as NOT ADMITTED rather than as a win.  Without that gate this
re-declaration would be exactly the cheat the whole lane exists not to be.

Everything else is the published lane's declaration unchanged.
"""
from __future__ import annotations
import json, os, subprocess, sys
from pathlib import Path

ROOT = Path("/home/reyerchu/_jxlayer")
PLUGIN = Path(os.environ.get(
    "JXLAYER_PLUGIN",
    "/home/reyerchu/vibe-ic-wt-jxlayer/vibe-ic-marketplace/plugins/vibe-ic"))
PROGRAMS = PLUGIN / "programs"
PY_ = sys.executable
IMAGE = ("ghcr.io/vibeic/vibeic-eda@sha256:"
         "24b5074b686386084f87a03712b5f76e475201fbf2f2583b112d6e2c3eb55f3d")

DEFAULT_KNOBS = {"die_um": "auto", "placement_density": "0.30",
                 "spare_cell_density": "0.02"}
DEFAULT_LEVERS = {"rtl_variant": "base", "synthesis_strategy": "none"}

SPEC_DOCS = [f"input/docs/{n}.md" for n in (
    "L1_product_metadata", "L2_architecture", "L3_external_interface",
    "L4_command_protocol", "L5_register_map", "L6_calibration",
    "L7_verification_plan", "L8_submodule_integration",
    "L9_constraints_floorplan")]


def declaration(root: Path, label: str, knobs: dict, levers: dict) -> dict:
    def arte(role, rel):
        return {"role": role, "path": rel} if (root / rel).is_file() else None

    problem = [arte("sdc", "phase2/stage2/constraints/spm.sdc"),
               arte("l19_spec", "phase1/generated_docs/L19_CONSTRAINTS_PDK.json")]
    problem += [arte(f"spec_doc_{Path(d).stem}", d) for d in SPEC_DOCS]
    impl = [arte("rtl_top", "phase2/stage1/rtl/spm.v"),
            arte("synth_netlist", "phase2/stage2/synth/spm_synth.v"),
            arte("routed_def", "phase3/stage3/pnr/spm.def"),
            arte("gate_netlist", "phase3/stage3/pnr/spm_pnr.v"),
            arte("gds", "phase3/stage4/gds/spm.gds"),
            arte("sta_signoff_multicorner",
                 "phase3/stage3/sta/sta_spef_multicorner.rpt"),
            arte("sta_signoff_ocv", "phase3/stage3/sta/sta_mcorner_ocv.rpt"),
            arte("power", "reports/phase3/power.rpt"),
            arte("drc_signoff", "reports/phase3/drc_signoff.rpt"),
            arte("drc_vacuity", "reports/phase3/drc_vacuous.json"),
            arte("lvs", "reports/phase3/lvs.rpt"),
            arte("antenna", "reports/phase3/antenna.json")]
    analysis = [arte("corner_mode_declaration",
                     "phase2/stage2/constraints/pvt_matrix.json"),
                arte("rc_corner_stance",
                     "reports/phase3/multi_corner_spef_stance.json")]
    return {
        "schema": "vibeic.ppa.contract_declaration.v1",
        "run_label": label,
        "root_label": "project",
        "problem": {
            "artefacts": [a for a in problem if a],
            "facts": [
                {"key": "constraints.clk.period_ns", "value": 10.0,
                 "source": "sdc",
                 "source_path": "phase2/stage2/constraints/spm.sdc"},
                {"key": "pdk.target", "value": "sky130", "source": "l19_spec",
                 "source_path":
                     "phase1/generated_docs/L19_CONSTRAINTS_PDK.json"},
            ],
        },
        "implementation": {
            "artefacts": [a for a in impl if a],
            "facts": ([{"key": f"pnr.{k}", "value": v,
                        "source": "runner_invocation"}
                       for k, v in sorted(knobs.items())]
                      + [{"key": f"crosslayer.{k}", "value": v,
                          "source": "search_lever"}
                         for k, v in sorted(levers.items())]),
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
                {"name": "static_timing", "status": "MEASURED",
                 "version": "2.7.0"},
                {"name": "synthesis", "status": "MEASURED",
                 "version": "0.68+ 0048145dd"},
            ],
        },
        "agent_execution": {
            "facts": [
                {"key": "agent.autonomy", "value": "candidate_authoring_only",
                 "source": "declared"},
                {"key": "agent.role",
                 "value": "authored the candidate RTL; every measurement is the "
                          "deterministic runner's",
                 "source": "declared"},
            ],
        },
        "policy": {
            "missing_power_basis": "REFUSE",
            # rtl.* is allowed to move ONLY because every arm that moves it
            # carries a crosslayer_rewrite_equivalence verdict.
            "mutation_allow_list": ["pnr.*", "crosslayer.*"],
            "mutation_forbidden": ["constraints.*", "pdk.*", "spec.*"],
        },
        "candidate": {"mutations": (
            [{"target": f"pnr.{k}", "from": DEFAULT_KNOBS.get(k), "to": v}
             for k, v in sorted(knobs.items()) if DEFAULT_KNOBS.get(k) != v]
            + [{"target": f"crosslayer.{k}", "from": DEFAULT_LEVERS.get(k),
                "to": v} for k, v in sorted(levers.items())
               if DEFAULT_LEVERS.get(k) != v])},
        "metrics": [],
    }


def build(trial: str) -> int:
    proj = ROOT / "run" / "trials" / trial
    out = ROOT / "records" / "trials" / trial
    run = json.loads((out / "run.json").read_text())
    d = declaration(proj, trial, run["pnr_knobs"], run["levers"])
    (out / "declaration.json").write_text(
        json.dumps(d, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    r = subprocess.run(
        [PY_, str(PROGRAMS / "ppa_contract_build.py"),
         "--declaration", str(out / "declaration.json"),
         "--root", str(proj), "--out", str(out / "contract.json")],
        capture_output=True, text=True, cwd=str(PROGRAMS), timeout=900)
    print(f"[gen_declaration] {trial}: contract_build rc={r.returncode} "
          f"{r.stdout.strip().splitlines()[-1] if r.stdout.strip() else r.stderr.strip()[:200]}")
    if r.returncode not in (0,):
        return r.returncode
    # PPA-C-010: `ppa_contract_check` needs jsonschema >= 4 and this host
    # carries 3.2.0, so the check correctly returns rc=2 "[CANNOT CHECK]"
    # rather than a false pass.  The PINNED EDA image ships jsonschema 4.26.0,
    # so the check is run THERE — same program, same contract, a dependency
    # that exists.  Nothing about the check is relaxed; it is given what it
    # says it needs.  (This is the published lane's REQUEST #11.)
    c = subprocess.run(
        ["docker", "run", "--rm", "--user", "1000",
         "-v", "/home/reyerchu:/home/reyerchu", IMAGE, "--skip",
         "python3", str(PROGRAMS / "ppa_contract_check.py"),
         "--contract", str(out / "contract.json"),
         "--json", str(out / "contract_check.json")],
        capture_output=True, text=True, cwd=str(PROGRAMS), timeout=900)
    print(f"[gen_declaration] {trial}: contract_check rc={c.returncode} "
          f"{c.stdout.strip().splitlines()[-1] if c.stdout.strip() else c.stderr.strip()[:200]}")
    # PROPAGATE THIS ONE TOO. `contract_build`'s rc is propagated sixteen lines
    # up and `contract_check`'s was discarded with `return 0` -- an asymmetry
    # inside one function, and the discarded half is the half that JUDGES the
    # contract rather than producing it. The comment above goes to real trouble
    # to give the check the jsonschema version it needs so that it is not a
    # false pass; having done that, throwing its answer away undoes the whole
    # point of the exercise.
    return c.returncode


if __name__ == "__main__":
    rc = 0
    for t in sys.argv[1:]:
        rc = max(rc, build(t))
    raise SystemExit(rc)
