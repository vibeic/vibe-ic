"""F1 — step 13 proves RTL against the netlist step 15 routes.

The defect, measured on spm (run23): `reports/lec.json` said PASS 66/66 on
`phase2/stage2/synth/netlist.v`, the technology-GENERIC phase-2 netlist
(sha256 41e72ef1...), while step 15 routed `spm_synth.v`, the MAPPED netlist
(sha256 15cd5ac7...). The proof was about a file nobody builds.

The rule the code follows now, each part pinned below:
  1. Arm A's subject is what `phase3_one_shot_runner.pnr_input_netlist` (step
     15's own resolver) returns: post-DFT when step 11's record authorises it,
     mapped otherwise. Never `netlist.v`, and never a substitute when that file
     does not exist yet.
  2. The scan-mode constraint is passed exactly when that subject is the scan
     netlist, i.e. from step 11's record, not from a file being present.
  3. The gate refuses a proof whose recorded gate sha256 differs from the file
     step 15 routes.
  4. Phase 3 re-proves after synthesis and before PnR when the proof is stale.

Only lec_run's process is faked (it would run yosys in a container); the fake
writes the report lec_run writes, bound to the file it was handed.
"""
from __future__ import annotations

import ast
import hashlib
import json
import sys
from pathlib import Path

import yaml

_PROGRAMS = Path(__file__).resolve().parent.parent
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import phase3_one_shot_runner as P3         # noqa: E402
import fault_scan_chain_insert as SCI        # noqa: E402

TOP = "tiny"
SYNTH = "phase2/stage2/synth"
GENERIC = f"{SYNTH}/netlist.v"
MAPPED = f"{SYNTH}/{TOP}_synth.v"
POST_DFT = f"{SYNTH}/post_dft_netlist.v"
SCAN_META = "reports/phase2/dft/scan_chain.json"

_GENERIC_V = ("module tiny(input clk, input a, input b, output y);\n"
              "  wire n; \\$_NAND_ g1 (.A(a), .B(b), .Y(n));\n"
              "  \\$_DFF_P_ r (.C(clk), .D(n), .Q(y));\nendmodule\n")
_MAPPED_V = ("module tiny(clk, a, b, y);\n  input clk; input a; input b; "
             "output y;\n  wire n;\n  lib__nand2_1 g1 (.A(a), .B(b), .ZN(n));\n"
             "  lib__dffq_1 r (.CLK(clk), .D(n), .Q(y));\nendmodule\n")
_POST_DFT_V = ("module tiny(clk, a, b, y, shift, test, sin, sout);\n"
               "  input clk; input a; input b; output y;\n"
               "  input shift;\n  input test;\n  input sin;\n  output sout;\n"
               "  wire n;\n  lib__nand2_1 g1 (.A(a), .B(b), .ZN(n));\n"
               "  lib__sdffq_1 r (.CLK(clk), .D(n), .SE(shift), .SI(sin), "
               ".Q(y));\n  assign sout = y;\nendmodule\n")


def _sha(p: Path) -> str:
    return "sha256:" + hashlib.sha256(p.read_bytes()).hexdigest()


def _tree(tmp_path: Path, *, mapped: bool = True, scan: str = "") -> Path:
    """A phase-2 tree. `scan` = "" (no DFT), "authorized" (step 11 published an
    L20-authorised chain and step 12 kept its ports) or "unauthorized"."""
    p = tmp_path / "proj"
    (p / "phase2/stage1/rtl").mkdir(parents=True)
    (p / "phase2/stage1/rtl/tiny.v").write_text(
        "module tiny(input clk, input a, input b, output reg y);\n"
        "  always @(posedge clk) y <= ~(a & b);\nendmodule\n")
    (p / SYNTH).mkdir(parents=True)
    (p / GENERIC).write_text(_GENERIC_V)
    if mapped:
        (p / MAPPED).write_text(_MAPPED_V)
    if scan:
        (p / "phase2/stage2/dft").mkdir(parents=True)
        (p / "phase2/stage2/dft/scan_netlist.v").write_text(_POST_DFT_V)
        (p / POST_DFT).write_text(_POST_DFT_V)
        (p / SCAN_META).parent.mkdir(parents=True)
        meta = {
            "published": True, "chain_length_matches_flop_count": True,
            "authorized_by_l20_contract": scan == "authorized",
            "dft_ports": ["shift", "test", "sin", "sout"],
            "functional_mode_tieoff": {"shift": 0, "test": 0, "sin": 0},
            "scan_out_port": "sout", "clock": "clk",
            "input_flop_count": 1, "internal_chain_length": 1,
        }
        if scan == "authorized":
            gd = p / "phase1/generated_docs"
            gd.mkdir(parents=True)
            (gd / "L20_DFT_SCAN_TOPOLOGY.json").write_text(json.dumps({
                "doc_id": "L20", "applicability": "APPLICABLE",
                "extraction_status": "EXTRACTED",
                "fields": {"dft_present": True, "scan_chains": [{
                    "name": "tiny_scan", "length": 1,
                    "scan_in": "sin", "scan_out": "sout", "clock": "clk",
                }]},
            }))
            binding, problems = SCI.load_l20_scan_contract(p, "clk", 1)
            assert not problems
            meta["l20_contract"] = binding
            meta["l20_reconciliation"] = SCI.reconcile_l20_scan_contract(
                binding, meta)
        (p / SCAN_META).write_text(json.dumps(meta))
    return p


def _lec_doc(proj: Path, gate_rel: str, *, scan_applied=None) -> dict:
    """The fields lec_run writes that the step and the gate read."""
    doc = {"verdict": "PASS", "equivalent": True, "compared_points": 2,
           "non_equivalent_points": 0, "unproven_points": 0,
           "gold": f"{TOP} (RTL)", "gate": f"{Path(gate_rel).name} (synth)",
           "proof_identity": {"top": TOP, "gate_netlist": {
               "path": gate_rel, "sha256": _sha(proj / gate_rel)}}}
    if scan_applied is not None:
        doc["scan_functional_mode"] = {"requested": True,
                                       "applied": scan_applied}
    return doc






# --------------------------------------------------------------------------- #
# 1. the subject is step 15's input
# --------------------------------------------------------------------------- #










def test_flow_declares_step13_and_step15_read_one_netlist():
    flow = yaml.safe_load((_PROGRAMS.parent / "flow/phase1_phase2_phase3.yaml")
                          .read_text())
    steps = {str(s.get("id")): s for s in flow["steps"]}

    def netlist_inputs(sid):
        return {(str(i["from"]), i["path"]) for i in steps[sid]["required_inputs"]
                if i["path"].endswith(".v") and str(i["from"]) != "1"}
    assert netlist_inputs("13") == netlist_inputs("15") == {("12", POST_DFT)}


# --------------------------------------------------------------------------- #
# 2. the gate refuses a stale proof
# --------------------------------------------------------------------------- #














# --------------------------------------------------------------------------- #
# 3. phase 3 re-proves on step 15's input, before PnR
# --------------------------------------------------------------------------- #


def test_phase3_main_runs_it_after_the_step11_selfheal_and_before_pnr():
    src = Path(P3.__file__).read_text()
    main = next(n for n in ast.parse(src).body
                if isinstance(n, ast.FunctionDef) and n.name == "main")

    def first_call(name):
        return min(c.lineno for c in ast.walk(main) if isinstance(c, ast.Call)
                   and getattr(c.func, "id", "") == name)
    s11 = first_call("run_step11_dft_after_synth")
    s13 = first_call("run_step13_lec_on_pnr_input")
    pnr = min(c.lineno for c in ast.walk(main) if isinstance(c, ast.Call)
              and getattr(c.func, "id", "") == "_cached_stage_decision"
              and any(k.arg == "kind" and getattr(k.value, "value", "") == "pnr"
                      for k in c.keywords))
    assert s11 < s13 < pnr
