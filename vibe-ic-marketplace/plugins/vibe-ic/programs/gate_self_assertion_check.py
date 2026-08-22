#!/usr/bin/env python3
"""gate_self_assertion_check.py — anti-fabrication gate-hole detector.

Captured v0.2.24 (benchmark-enhancement-capture, Bucket A) from the M1
remediation: several flow gates used to PASS on a self-produced JSON boolean
(``json_field_true`` over a file the SAME step writes) with no independent
deterministic checker behind it — the producing step effectively asserted its
own PASS. M1 hardened 8 such gates to ``program_exit_zero`` invoking a real
substance checker. THIS program makes that fix COMPOUND: it scans the canonical
flow YAML and FAILs if any gate reintroduces the hole, so a future step/gate
addition cannot silently re-add a self-asserted pass.

THE RULE (deterministic, no LLM): a gate is a self-assertion hole when it
carries a ``json_field_true`` predicate whose ``file`` is listed in the SAME
step's ``required_outputs`` (i.e. the step produces the very file it then
trusts) AND the gate has NO ``program_exit_zero`` predicate anywhere (so the
self-written boolean is the SOLE pass criterion, unbacked by a real checker).
A ``json_field_true`` that is PAIRED with a ``program_exit_zero`` in the same
gate is fine (e.g. Step 5 Formal: all_proved + bit_level_full_stack_tb_check;
Step 37 FPGA: all_scenarios_passed + fpga_on_board_attestation_check) — the
deterministic checker is the real gate; the boolean is belt-and-braces.

Usage:
    python3 gate_self_assertion_check.py [<flow_yaml>] [--json <out>]
    # default flow_yaml = <plugin>/flow/phase1_phase2_phase3.yaml

Exit: 0 = no holes (PASS) / 1 = self-assertion hole(s) found (FAIL) /
2 = flow YAML not found or unparseable (operational).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _walk_steps(doc) -> list:
    """Return the steps[] list wherever it lives in the flow doc."""
    if isinstance(doc, dict):
        s = doc.get("steps")
        if isinstance(s, list):
            return s
        for v in doc.values():
            r = _walk_steps(v)
            if r:
                return r
    return []


def _collect_predicates(gate) -> tuple[list, bool]:
    """Return (json_field_true_predicates, has_program_exit_zero) for a gate.

    Recurses through all_of / any_of / nested predicate lists.
    """
    jft: list = []
    has_pez = False

    def rec(node):
        nonlocal has_pez
        if isinstance(node, dict):
            for k, v in node.items():
                if k == "json_field_true" and isinstance(v, dict):
                    jft.append(v)
                elif k == "program_exit_zero":
                    has_pez = True
                elif k in ("optional_program_exit_zero",
                           "advisory_program_exit_zero"):
                    # Neither is a real backing checker: `optional` may never
                    # run, and `advisory` (#306) runs but cannot fail the step.
                    # A json_field_true that trusts an artifact's own PASS
                    # still needs a BLOCKING program behind it.
                    pass
                else:
                    rec(v)
        elif isinstance(node, list):
            for item in node:
                rec(item)

    rec(gate)
    return jft, has_pez


def find_self_assertion_holes(flow_yaml: Path) -> list[dict]:
    import yaml
    doc = yaml.safe_load(flow_yaml.read_text())
    steps = _walk_steps(doc)
    holes = []
    for st in steps:
        if not isinstance(st, dict):
            continue
        gate = st.get("gate")
        if not gate:
            continue
        jft, has_pez = _collect_predicates(gate)
        if not jft:
            continue
        req = st.get("required_outputs") or []
        req_files = {str(r) for r in req}
        for pred in jft:
            f = str(pred.get("file", ""))
            self_produced = f in req_files or any(
                f and (f in r or r in f) for r in req_files)
            if self_produced and not has_pez:
                holes.append({
                    "step": st.get("id"),
                    "name": st.get("name"),
                    "self_produced_file": f,
                    "field": pred.get("field"),
                    "reason": ("gate PASSes on a self-produced json_field_true "
                               "with NO program_exit_zero checker backing it "
                               "(anti-fabrication hole)"),
                })
    return holes


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("flow_yaml", nargs="?", default=None)
    ap.add_argument("--json", default=None)
    a = ap.parse_args(argv)

    # Accept a flow YAML path OR a PLUGIN DIRECTORY. `plugin_full_audit`
    # invokes this guard as `[python, gate_self_assertion_check.py, <plugin>]`,
    # and until vibe-ic#220 the directory form fell through to `Path(<plugin>)`,
    # which is not a file — so the guard exited 2 on EVERY audit run while
    # audit_d2 recorded a finding only on exit 1. The anti-fabrication guard was
    # therefore inert in the full audit, silently, for the same reason this
    # issue is about: a not-run result read as a clean one.
    _default = Path(__file__).resolve().parent.parent / "flow" / \
        "phase1_phase2_phase3.yaml"
    if a.flow_yaml:
        flow = Path(a.flow_yaml)
        if flow.is_dir():
            cand = flow / "flow" / "phase1_phase2_phase3.yaml"
            if not cand.is_file():
                for sub in flow.glob(
                        "plugins/*/flow/phase1_phase2_phase3.yaml"):
                    cand = sub
                    break
            flow = cand
    else:
        flow = _default

    if not flow.is_file():
        print(f"SKIP: flow YAML not found at {flow}", file=sys.stderr)
        return 2
    try:
        holes = find_self_assertion_holes(flow)
    except Exception as e:  # unparseable / yaml missing
        print(f"SKIP: cannot parse {flow}: {e}", file=sys.stderr)
        return 2

    verdict = "PASS" if not holes else "FAIL"
    report = {"gate": "gate_self_assertion_check", "verdict": verdict,
              "flow_yaml": str(flow), "holes": holes}
    if a.json:
        Path(a.json).parent.mkdir(parents=True, exist_ok=True)
        Path(a.json).write_text(json.dumps(report, indent=2) + "\n")

    if holes:
        print(f"FAIL: {len(holes)} anti-fabrication gate self-assertion "
              f"hole(s) in {flow.name}:")
        for h in holes:
            print(f"  - step {h['step']} ({h['name']}): "
                  f"json_field_true on self-produced {h['self_produced_file']} "
                  f"(field={h['field']}) with no program_exit_zero — wire a real "
                  f"checker via program_exit_zero.")
        return 1
    print(f"PASS: no self-asserted gate holes in {flow.name} "
          f"(every json_field_true is backed by a program_exit_zero checker).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
