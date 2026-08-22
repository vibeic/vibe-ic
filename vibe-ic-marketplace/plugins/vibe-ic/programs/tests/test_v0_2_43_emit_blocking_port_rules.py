"""v0.2.43 emit-blocking port-rule regressions.

Pins the two ORGANIC-20260605 fixes:
  * port-missing-not-emit-blocking  (#409): the checker's existing ERROR-level
    'port-missing' finding now BLOCKS emit in gates_atomic.py — a module that
    drops a declared-but-unused port compiles standalone but fails the hidden
    testbench's port bind at scoring.
  * zero-output-module-not-emit-blocking (#408): NEW structural rule
    'zero-output-ports' in spec_conformance_check (ERROR) + emit-block wiring —
    a prompt port-direction typo produced a vacuous all-input module that
    matched the (typo'd) spec interface exactly, so every port-fidelity rule
    stayed silent; zero output-capable ports is the spec-typo-proof signature.

Corpus-sweep honesty (promotion precondition): both rules swept over ALL 312
emitted passing samples of the v0.2.42 two-track clean-room campaign AND 936
samples of the three prior campaigns (1248 total) with ZERO false fires
(2026-06-05).

chip-AGNOSTIC: fixtures use generic TopModule/clk/d/q shapes only.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import spec_conformance_check as scc  # noqa: E402
from _specrtl_common import extract_spec_contract, parse_rtl_ports, strip_comments  # noqa: E402

HARNESS = Path(__file__).resolve().parent.parent.parent / "benchmark"
GATES = HARNESS / "gates_atomic.py"

import pytest  # noqa: E402

#: These tests RUN `gates_atomic.py` and then read the `gates.json` it writes.
#: Without iverilog the gate refuses to run — correctly — and writes no report,
#: so the read dies with FileNotFoundError on a path that was never meant to
#: exist. A gate that REFUSED and a gate that produced a bad report are not the
#: same result, and a traceback cannot tell them apart. Every other test in this
#: file calls pure rule functions and needs no toolchain.
_HAS_IVERILOG = shutil.which("iverilog") is not None
_needs_gate = pytest.mark.skipif(
    not _HAS_IVERILOG,
    reason="runs gates_atomic.py and reads the gates.json it writes; without "
           "iverilog the gate refuses and writes nothing")



# ── unit: zero-output-ports rule in spec_conformance_check ───────────────

def _findings(spec_text: str, rtl: str, rule: str):
    spec = extract_spec_contract(spec_text, confirm=False)
    src = strip_comments(rtl)
    nm, ports = parse_rtl_ports(src, "TopModule")
    fs = scc.check(spec, nm, ports, scc.classify_rtl_resets(src),
                   scc._rtl_output_is_registered(src, ports), "t.sv", src,
                   spec_text=spec_text)
    return [f for f in fs if f.rule == rule]


# the prompt-direction-typo shape: a storage element's state pin bullet-listed
# as input; a literal-minded author emits the matching all-input vacuous module.
_TYPO_SPEC = ("Build a D storage element.\n\n"
              " - input  clk\n - input  d\n - input  q\n\n"
              "On every rising clock edge q follows d.\n")
_VACUOUS_RTL = "module TopModule(input clk, input d, input q);\nendmodule\n"
_FIXED_RTL = ("module TopModule(input clk, input d, output reg q);\n"
              "  initial q = 0;\n"
              "  always @(posedge clk) q <= d;\n"
              "endmodule\n")


def test_zero_output_rule_fires_on_vacuous_module():
    fs = _findings(_TYPO_SPEC, _VACUOUS_RTL, "zero-output-ports")
    assert [f.severity for f in fs] == ["ERROR"]
    assert fs[0].symbol == "TopModule"


def test_zero_output_rule_clean_with_an_output():
    assert _findings(_TYPO_SPEC, _FIXED_RTL, "zero-output-ports") == []


def test_zero_output_rule_inout_counts_as_output_capable():
    rtl = "module TopModule(input clk, inout sda);\nendmodule\n"
    assert _findings("A pad.\n\n - input clk\n - inout sda\n", rtl,
                     "zero-output-ports") == []


def test_zero_output_rule_silent_on_portless_parse():
    # no ports parsed (e.g. checker pointed at a snippet) → never fires
    spec = extract_spec_contract("just prose, no interface", confirm=False)
    fs = scc.check(spec, "", [], {}, None, "t.sv", "", spec_text="")
    assert [f for f in fs if f.rule == "zero-output-ports"] == []


# ── gates_atomic end-to-end ───────────────────────────────────────────────

def _stage(tmp_path, prompt_text, sample_body):
    ds = tmp_path / "ds"; ds.mkdir(exist_ok=True)
    (ds / "ProbP_prompt.txt").write_text(prompt_text)
    wd = tmp_path / "run" / "work" / "ProbP"
    wd.mkdir(parents=True, exist_ok=True)
    (wd / "spec.yaml").write_text("design:\n  name: TopModule\n")
    (wd / "sample.sv").write_text(sample_body)
    return ds, tmp_path / "run"


def _run_gate(ds, run):
    return subprocess.run(
        [sys.executable, str(GATES), "--prob", "ProbP",
         "--workdir", str(run / "work"), "--dataset", str(ds),
         "--prompt-suffix", "_prompt.txt", "--top-module", "TopModule"],
        capture_output=True, text=True, timeout=60)


def _block_rules(run):
    gates = json.loads((run / "work" / "ProbP" / "gates.json").read_text())
    blk = gates["steps"].get("structural_emit_block", {})
    return gates, {f["rule"] for f in blk.get("findings", [])}


# #408: zero-output module must BLOCK; restoring the output must emit.

@_needs_gate
def test_gate_blocks_vacuous_zero_output_module(tmp_path):
    ds, run = _stage(tmp_path, _TYPO_SPEC, _VACUOUS_RTL)
    r = _run_gate(ds, run)
    assert r.returncode == 1, r.stdout + r.stderr
    gates, rules = _block_rules(run)
    assert gates["hard_gates_pass"] is False
    assert "zero-output-ports" in rules
    assert not (run / "samples" / "ProbP_sample01.sv").exists()


@_needs_gate
def test_gate_emits_after_output_direction_restored(tmp_path):
    # the campaign's actual close-loop fix: flip the typo'd pin to an output
    # register. port-direction-mismatch (vs the typo'd spec) is NOT in the
    # blocking allow-list, so the corrected design emits.
    ds, run = _stage(tmp_path, _TYPO_SPEC, _FIXED_RTL)
    r = _run_gate(ds, run)
    assert r.returncode == 0, r.stdout + r.stderr
    gates, rules = _block_rules(run)
    assert gates["hard_gates_pass"] is True
    assert rules == set()
    assert (run / "samples" / "ProbP_sample01.sv").exists()


# #409: missing declared-but-unused port must BLOCK; re-adding it must emit.

_UNUSED_PORT_SPEC = ("Build a passthrough with an unused clock.\n\n"
                     " - input  clk\n - input  in\n - output out\n\n"
                     "out equals in combinationally; clk is present on the "
                     "interface but unused by the logic.\n")
_DROPPED_PORT_RTL = ("module TopModule(input in, output out);\n"
                     "  assign out = in;\nendmodule\n")
_FULL_PORT_RTL = ("module TopModule(input clk, input in, output out);\n"
                  "  assign out = in;\nendmodule\n")


@_needs_gate
def test_gate_blocks_missing_declared_port(tmp_path):
    ds, run = _stage(tmp_path, _UNUSED_PORT_SPEC, _DROPPED_PORT_RTL)
    r = _run_gate(ds, run)
    assert r.returncode == 1, r.stdout + r.stderr
    gates, rules = _block_rules(run)
    assert gates["hard_gates_pass"] is False
    assert "port-missing" in rules
    assert not (run / "samples" / "ProbP_sample01.sv").exists()


@_needs_gate
def test_gate_emits_with_all_declared_ports(tmp_path):
    ds, run = _stage(tmp_path, _UNUSED_PORT_SPEC, _FULL_PORT_RTL)
    r = _run_gate(ds, run)
    assert r.returncode == 0, r.stdout + r.stderr
    gates, rules = _block_rules(run)
    assert gates["hard_gates_pass"] is True
    assert rules == set()
    assert (run / "samples" / "ProbP_sample01.sv").exists()
