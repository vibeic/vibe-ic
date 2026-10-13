#!/usr/bin/env python3
"""Bidirectional test for serial_parallel_mul_synth (repo-gatekeeper).

Pins the deterministic serial-parallel-multiplier RTL generator authored to
close the ``digital_arithmetic_primitive rtl_gen=null`` gap (spm x sky130A
capture). BIDIRECTIONAL — the fix must PASS and the defect must FAIL, so neither
half is a rubber stamp:

  POSITIVE (fix PASSES):
    * the solver FIRES on the serial-parallel multiplier SHAPE and returns a
      spec with operator '*', parallel/serial-in/serial-out roles resolved.
    * the emitted RTL COMPILES under iverilog and, driven LSB-first, reproduces
      (x * y) mod 2^N at a single self-calibrated latency for every vector
      (an independent Python golden — NOT the DUT's own claim).

  NEGATIVE (defect FAILS):
    * a MUTANT of the emitted RTL (product forced to 0) must FAIL the same
      golden check — proving the check is falsifiable.
    * the solver FAIL-CLOSES (DEFER) on shapes it must not synthesise: an
      adder (wrong operator), and a fully-parallel c=a*b core (no serial
      operand/result).

iverilog-dependent halves self-skip when iverilog is absent so the pure-Python
contract still runs in a bare CI.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import serial_parallel_mul_synth as spm  # noqa: E402
import design_one_shot_runner as runner  # noqa: E402

_HAVE_IVERILOG = shutil.which("iverilog") is not None


def _mk_project(tmp: Path, *, ports, l2_text, top="spm") -> Path:
    root = tmp / top
    gd = root / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    # The generator now requires the fixture to state its reset style. These
    # tests concern multiplication, declarations and transactional writes;
    # a separate CR-12 fixture checks that a silent input is refused.
    rst_name = next((p["name"] for p in ports
                     if p["name"] in ("rst", "rst_n", "reset", "reset_n")), "rst")
    polarity = "active-low" if rst_name.endswith("_n") else "active-high"
    l2_text += f"; synchronous {polarity} reset"
    (gd / "L2_FRS.json").write_text(json.dumps(
        {"ic_name": top, "frs_sections": [{"content": l2_text}]},
        ensure_ascii=False))
    (gd / "L9_INTEGRATION_SPEC.json").write_text(json.dumps(
        {"top_module": top, "top_ports": ports}, ensure_ascii=False))
    return root


_SPM_PORTS = [
    {"name": "clk", "direction": "input", "width": 1},
    {"name": "rst", "direction": "input", "width": 1},
    {"name": "x", "direction": "input", "width": "size-1:0",
     "width_symbolic": "size-1:0", "msb": "size-1", "lsb": "0"},
    {"name": "y", "direction": "input", "width": 1},
    {"name": "p", "direction": "output", "width": 1},
]


# ── POSITIVE: solver fires + spec is right ────────────────────────────────────
def test_solver_fires_on_serial_parallel_multiplier(tmp_path):
    proj = _mk_project(tmp_path, ports=_SPM_PORTS,
                       l2_text="serial-parallel multiplier: p = (x * y) mod 2^N")
    spec, reason = spm.extract_serial_parallel_mul_spec(
        proj, "digital_arithmetic_primitive")
    assert spec is not None, reason
    assert spec["topology"] == "serial_parallel"
    assert spec["operator"] == "*"
    assert spec["parallel"] == "x"
    assert spec["serial_in"] == "y"
    assert spec["serial_out"] == "p"
    assert spec["size_param"] == "size"


def _run(cmd, cwd):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)


def _stream_matches_golden(work: Path, rtl_text: str, size: int = 8) -> bool:
    """Compile <rtl> + an independent TB, drive LSB-first, and check the
    reassembled p-stream equals (x*y) mod 2^size at ONE calibrated latency."""
    (work / "dut.v").write_text(rtl_text)
    (work / "tb.v").write_text(_TB.replace("__SIZE__", str(size)))
    r = _run(["iverilog", "-g2012", "-o", "tb.vvp", "tb.v", "dut.v"], work)
    if r.returncode != 0:
        return False
    r = _run(["vvp", "tb.vvp"], work)
    vecs = []
    for line in r.stdout.splitlines():
        line = line.strip()
        if line.startswith("VEC "):
            _, x, y, P = line.split()
            vecs.append((int(x), int(y), P))
    if not vecs:
        return False

    def golden(x, y):
        v = (x * y) % (1 << size)
        return [(v >> i) & 1 for i in range(size)]

    for L in range(0, size + 3):
        if all(L + size <= len(P) and
               [int(ch) for ch in P][L:L + size] == golden(x, y)
               for x, y, P in vecs):
            return True
    return False


_TB = r"""
`timescale 1ns/1ps
module tb;
  parameter size = __SIZE__;
  reg clk=0, rst=1, y=0; reg [size-1:0] x=0; wire p;
  integer t, v; reg [size-1:0] xs[0:19]; reg [size-1:0] ys[0:19];
  spm #(.size(size)) dut(.clk(clk),.rst(rst),.x(x),.y(y),.p(p));
  always #5 clk=~clk;
  initial begin
    xs[0]=0; ys[0]=0; xs[1]={size{1'b1}}; ys[1]={size{1'b1}};
    xs[2]=1; ys[2]={size{1'b1}}; xs[3]={size{1'b1}}; ys[3]=1;
    for (v=4; v<20; v=v+1) begin xs[v]=(v*73+11); ys[v]=(v*151+29); end
    for (v=0; v<20; v=v+1) begin
      rst=1; y=0; x=0; @(posedge clk); @(posedge clk);
      rst=0; x=xs[v]; $write("VEC %0d %0d ", xs[v], ys[v]);
      for (t=0; t<2*size+4; t=t+1) begin
        if (t<size) y=ys[v][t]; else y=0; @(posedge clk); #1 $write("%b", p);
      end
      $write("\n");
    end
    $finish;
  end
endmodule
"""


@pytest.mark.skipif(not _HAVE_IVERILOG, reason="iverilog not installed")
def test_emitted_rtl_compiles_and_matches_golden(tmp_path):
    proj = _mk_project(tmp_path, ports=_SPM_PORTS,
                       l2_text="serial-parallel multiplier p = x * y mod 2^N")
    spec, _ = spm.extract_serial_parallel_mul_spec(
        proj, "digital_arithmetic_primitive")
    rtl = spm.emit_rtl(spec)
    assert _stream_matches_golden(tmp_path, rtl), \
        "emitted serial-parallel multiplier RTL failed the (x*y) mod 2^N golden"


@pytest.mark.skipif(not _HAVE_IVERILOG, reason="iverilog not installed")
def test_mutant_rtl_fails_golden(tmp_path):
    """Falsifiability: break the datapath and the SAME check must FAIL."""
    proj = _mk_project(tmp_path, ports=_SPM_PORTS,
                       l2_text="serial-parallel multiplier p = x * y mod 2^N")
    spec, _ = spm.extract_serial_parallel_mul_spec(
        proj, "digital_arithmetic_primitive")
    rtl = spm.emit_rtl(spec)
    mutant = rtl.replace("m  = x & {size{yr}}", "m  = x & {size{yr}} & {size{1'b0}}")
    assert mutant != rtl, "mutation did not apply"
    assert not _stream_matches_golden(tmp_path, mutant), \
        "a product-forced-to-0 mutant PASSED the golden — check is a rubber stamp"


# ── NEGATIVE: fail-closed on shapes this solver must not synthesise ────────────
def test_defer_on_adder(tmp_path):
    ports = [
        {"name": "clk", "direction": "input", "width": 1},
        {"name": "rst", "direction": "input", "width": 1},
        {"name": "a", "direction": "input", "width": "N-1:0",
         "width_symbolic": "N-1:0", "msb": "N-1"},
        {"name": "b", "direction": "input", "width": 1},
        {"name": "s", "direction": "output", "width": 1},
    ]
    proj = _mk_project(tmp_path, ports=ports, top="ser_adder",
                       l2_text="serial adder: s = a + b, an N-bit adder core")
    spec, reason = spm.extract_serial_parallel_mul_spec(
        proj, "digital_arithmetic_primitive")
    assert spec is None, f"solver must DEFER on an adder, got {spec}"


def test_defer_on_fully_parallel_multiplier(tmp_path):
    ports = [
        {"name": "clk", "direction": "input", "width": 1},
        {"name": "rst", "direction": "input", "width": 1},
        {"name": "a", "direction": "input", "width": 8, "msb": 7},
        {"name": "b", "direction": "input", "width": 8, "msb": 7},
        {"name": "c", "direction": "output", "width": 16, "msb": 15},
    ]
    proj = _mk_project(tmp_path, ports=ports, top="par_mul",
                       l2_text="parallel multiplier c = a * b mod 2^N")
    spec, reason = spm.extract_serial_parallel_mul_spec(
        proj, "digital_arithmetic_primitive")
    assert spec is None, \
        f"solver must DEFER when there is no 1-bit serial operand/result, got {spec}"


# ── L7 ## 7.0 declaration ──────────────────────────────────────────────────
# spm's own input/docs/L7_verification_plan.md #7.0: "Plugin, before starting
# RTL design, MUST declare {bit_order, reset_polarity, latency_cycles,
# integer_encoding} in plugin_output/declaration.json; the L7 comparison
# procedure reads this file to correctly pair reference outputs." Unwritten,
# this failed spec_required_artifact_check on every real spm run (measured
# 2026-08-06, all three published PDKs) — a genuine spec requirement the
# generator never fulfilled, not a fixture gap.
def test_emit_writes_the_l7_required_declaration(tmp_path):
    proj = _mk_project(tmp_path, ports=_SPM_PORTS,
                       l2_text="serial-parallel multiplier: p = (x * y) mod 2^N")
    rc = spm.main([str(proj), "--emit"])
    assert rc == 0
    decl_path = proj / "plugin_output" / "declaration.json"
    assert decl_path.is_file(), \
        "L7 #7.0 requires plugin_output/declaration.json and --emit must write it"
    decl = json.loads(decl_path.read_text())
    # Exactly L7's four required fields, exactly its stated allowed values.
    assert decl == {
        "bit_order": "LSB_first",
        "reset_polarity": "active_high",
        # R-0929-SPM-LATENCY: 2 register stages (yr, pr) on the emitted
        # serial path, as every oracle framing search measures; the pin said
        # 1, a false fact the ruling ordered corrected.
        "latency_cycles": 2,
        "latency_cycles_origin": "pre_nba_sample_offset",
        "integer_encoding": "unsigned",
    }


def test_declaration_reset_polarity_follows_the_designs_own_reset_name(tmp_path):
    """The one field that is NOT a fixed constant: reset polarity must read
    the design's OWN reset port, never assume active-high."""
    ports = [dict(p) for p in _SPM_PORTS]
    for p in ports:
        if p["name"] == "rst":
            p["name"] = "rst_n"
    proj = _mk_project(tmp_path, ports=ports, top="spm_n",
                       l2_text="serial-parallel multiplier: p = (x * y) mod 2^N")
    rc = spm.main([str(proj), "--emit"])
    assert rc == 0
    decl = json.loads((proj / "plugin_output" / "declaration.json").read_text())
    assert decl["reset_polarity"] == "active_low"
    # and the OTHER three fields must NOT have moved with it
    assert decl["bit_order"] == "LSB_first"
    assert decl["latency_cycles"] == 2   # R-0929-SPM-LATENCY (yr + pr)
    assert decl["integer_encoding"] == "unsigned"


def test_declaration_is_not_written_on_a_deferred_shape(tmp_path):
    """The over-correction this must NOT become: writing a declaration for a
    design the solver never actually generated RTL for."""
    ports = [
        {"name": "clk", "direction": "input", "width": 1},
        {"name": "rst", "direction": "input", "width": 1},
        {"name": "a", "direction": "input", "width": "N-1:0",
         "width_symbolic": "N-1:0", "msb": "N-1"},
        {"name": "b", "direction": "input", "width": 1},
        {"name": "s", "direction": "output", "width": 1},
    ]
    proj = _mk_project(tmp_path, ports=ports, top="ser_adder",
                       l2_text="serial adder: s = a + b, an N-bit adder core")
    rc = spm.main([str(proj), "--emit"])
    assert rc == 2
    assert not (proj / "plugin_output" / "declaration.json").exists()


def test_runner_serial_multifile_commit_rolls_back_as_one_transaction(
        tmp_path, monkeypatch):
    """RTL and the L7 declaration cannot become a torn two-root commit."""
    proj = _mk_project(
        tmp_path, ports=_SPM_PORTS,
        l2_text="serial-parallel multiplier: p = (x * y) mod 2^N")
    before_binding = runner._Phase1ProjectBinding.open(proj)
    try:
        before = runner._phase1_tree_manifest_fd(
            before_binding.project_fd, proj)
    finally:
        before_binding.close()
    generator_roots = []
    real_run = runner.subprocess.run

    def _observe_generator(cmd, *args, **kwargs):
        if (len(cmd) >= 3
                and Path(cmd[1]).name == "serial_parallel_mul_synth.py"):
            generator_roots.append(Path(cmd[2]))
        return real_run(cmd, *args, **kwargs)

    real_rename = runner._phase1_rename_noreplace
    injected = False

    def _fail_second_top(src_fd, src, dst_fd, dst):
        nonlocal injected
        if dst == "plugin_output" and not injected:
            injected = True
            raise OSError("injected declaration publication failure")
        return real_rename(src_fd, src, dst_fd, dst)

    # A module reaches a process through `subprocess`, through `_pr`
    # (`_progress_run`, the progress-supervised drop-in) or through both.
    # Substituting on only one leaves the real launcher answering the
    # question this test is asking about a fake one, and the test then
    # passes or fails for a reason that has nothing to do with its subject.
    for _launcher in (getattr(runner, "subprocess", None),
                      getattr(runner, "_pr", None)):
        if _launcher is not None:
            monkeypatch.setattr(_launcher, "run", _observe_generator)
    monkeypatch.setattr(runner, "_phase1_rename_noreplace", _fail_second_top)

    result = runner.step_rtl_gen(proj, "digital_arithmetic_primitive")

    assert result.status == "NOT_MEASURED"
    assert result.extras["output_refusal"]["reason"] == (
        "RTL_TRANSACTION_COMMIT_REFUSED")
    assert result.output_files == []
    assert injected and len(generator_roots) == 1
    assert generator_roots[0] != proj
    assert not (proj / "phase2").exists()
    assert not (proj / "plugin_output").exists()
    assert not any(p.name.startswith(".vibeic-rtl-txn.")
                   for p in proj.iterdir())
    binding = runner._Phase1ProjectBinding.open(proj)
    try:
        assert runner._phase1_tree_manifest_fd(
            binding.project_fd, proj) == before
    finally:
        binding.close()


def test_serial_native_commit_publishes_current_provenance(tmp_path):
    import rtl_provenance as provenance
    proj = _mk_project(tmp_path, ports=_SPM_PORTS, top="neutral_serial",
                       l2_text="serial-parallel multiplier: p = (x * y) mod 2^N")
    first = runner.step_rtl_gen(proj, "digital_arithmetic_primitive")
    assert first.status == "PASS", first.detail
    verdict, reason, evidence = provenance.classify(proj)
    assert verdict == provenance.GENERATED, (verdict, reason, evidence)
    ledger = json.loads(provenance.ledger_path(proj).read_text())
    assert ledger["generator"] == "serial_parallel_mul_synth"
    assert evidence["file_count"] == 1
    source = proj / "phase2/stage1/rtl/neutral_serial.v"
    original = source.read_bytes()
    runner._finalize_rtl_provenance()
    # A new process carries only the committed ledger, not a live claim.
    second = subprocess.run([
        sys.executable, "-c",
        "import sys; from pathlib import Path; "
        "import design_one_shot_runner as r; import rtl_provenance as p; "
        "q=Path(sys.argv[1]); x=r.step_rtl_gen(q,'digital_arithmetic_primitive'); "
        "print(x.status); print(p.classify(q)[0])", str(proj)],
        env={**__import__('os').environ, "PYTHONPATH": str(PROGRAMS)},
        capture_output=True, text=True, timeout=120)
    assert second.returncode == 0, second.stderr
    # This class has rtl_gen=null; the serial branch preserves an existing
    # tree, then the existing class handoff reports PASS_WITH_WAIVERS.
    assert second.stdout.strip().splitlines()[-2:] == ["PASS_WITH_WAIVERS", provenance.GENERATED]
    assert source.read_bytes() == original


_DECLARATION_CONTRACT = """# L7
The Plugin MUST declare `plugin_output/declaration.json` before authoring:

| Field | Required | Example |
|---|---|---|
| `bit_order` | Yes | `LSB_first`(primary) |
| `integer_encoding` | Yes | `unsigned`(primary) |
| `latency_cycles` | Yes | `2`(primary) |
| `latency_cycles_origin` | No | `pre_nba_sample_offset`(primary) |
| `reset_polarity` | Yes | `active_high`(primary) |
| `size_param` | Yes | `32`(primary) |
"""


def _serial_random_contract_project(tmp_path, *, predeclared):
    import phase1_doc_one_shot_runner as phase1
    import spec_declaration_emit as declaration
    proj = _mk_project(tmp_path, ports=_SPM_PORTS, top="neutral_serial",
                       l2_text="serial-parallel multiplier: p = (x * y) mod 2^N")
    docs = proj / "input/docs"
    docs.mkdir(parents=True)
    goal_text = ("layer: L7\n# Functional verification\n"
                 "| Test category | Pass criterion | Scope |\n|---|---|---|\n"
                 "| Random arithmetic functional equivalence | 100% PASS (binary) | "
                 "Random >= 64 operand pairs (x, y), all matching the independent modulo model |\n")
    (docs / "L7_verification_plan.md").write_text(_DECLARATION_CONTRACT + "\n" + goal_text)
    cases = phase1._harvest_test_cases_from_input_tables({"L7_verification_plan.md": goal_text})
    assert len(cases) == 1 and cases[0]["kind"] == "coverage_goal", cases
    gd = proj / "phase1/generated_docs"
    (gd / "L10_TEST_CASES.json").write_text(json.dumps({"test_cases": cases}))
    l9 = gd / "L9_INTEGRATION_SPEC.json"
    doc = json.loads(l9.read_text())
    doc.update(ic_class="digital_arithmetic_primitive",
               clocks=[{"name": "clk", "period_ns": 10}],
               reset_domains=[{"name": "rst", "polarity": "active_high", "sync": "sync"}])
    l9.write_text(json.dumps(doc))
    if predeclared:
        args = [str(proj)]
        for name, value in (("bit_order", "LSB_first"), ("integer_encoding", "unsigned"),
                            ("latency_cycles", "2"), ("reset_polarity", "active_high"),
                            ("size_param", "32")):
            args += ["--set", f"{name}={value}"]
        assert declaration.main(args) == 0
    return proj, cases[0]


@pytest.mark.parametrize("predeclared", [False, True])
def test_serial_declaration_is_complete_before_native_random_goal_binding(
        tmp_path, monkeypatch, predeclared):
    import os
    import professional_tb_gen as professional
    proj, goal = _serial_random_contract_project(tmp_path, predeclared=predeclared)
    generated = runner.step_rtl_gen(proj, "digital_arithmetic_primitive")
    assert generated.status == "PASS", generated.detail
    monkeypatch.setenv("PYTHONPATH", str(PROGRAMS) + os.pathsep + os.environ.get("PYTHONPATH", ""))
    monkeypatch.setenv("COCOTB_HDL_TIMEUNIT", "1ns")
    monkeypatch.setenv("COCOTB_HDL_TIMEPRECISION", "1ps")
    measured = runner.step_professional_tb_gen(proj, "neutral_serial", "")
    (proj / "native-professional-step.json").write_text(json.dumps(measured.__dict__, default=str))
    assert measured.status == "PASS", measured.detail
    before = (proj / "plugin_output/declaration.json").read_bytes()
    early = runner.declaration_before_step4(proj)
    assert early["emitted"] is True, early
    outcome = professional.random_pair_goal_measurement(proj, goal)
    (proj / "native-goal-consumer.json").write_text(json.dumps(outcome))
    assert outcome["verdict"] == "PASS", outcome
    assert (proj / "plugin_output/declaration.json").read_bytes() == before
    assert early["fields"]["size_param"] == 32
    repeated = runner.declaration_before_step4(proj)
    assert repeated["fields"] == early["fields"]
    assert (proj / "plugin_output/declaration.json").read_bytes() == before
    assert professional.random_pair_goal_measurement(proj, goal)["verdict"] == "PASS"
    # The existing stale-evidence guard must still reject an actual later choice change.
    # Keep the original native attempt current at terminal; mutate a separate
    # copy as the existing professional-TB mutation controls do.
    mutant = tmp_path / "changed-declaration"
    shutil.copytree(proj, mutant)
    changed = dict(early["fields"], size_param=16)
    (mutant / "plugin_output/declaration.json").write_text(json.dumps(changed))
    refusal = professional.random_pair_goal_measurement(mutant, goal)
    assert refusal["verdict"] == "NOT_MEASURED" and "stale" in refusal["why"], refusal
    runner._finalize_rtl_provenance()


@pytest.mark.parametrize("choice", [
    {"bit_order": "MSB_first"}, {"size_param": 16}, {"latency_cycles": True},
])
def test_serial_generator_preserves_a_conflicting_prior_choice(tmp_path, choice):
    proj = _mk_project(tmp_path, ports=_SPM_PORTS, top="neutral_serial",
                       l2_text="serial-parallel multiplier: p = (x * y) mod 2^N")
    path = proj / "plugin_output/declaration.json"
    path.parent.mkdir()
    original = json.dumps(choice).encode()
    path.write_bytes(original)
    assert spm.main([str(proj), "--emit"]) == 2
    assert path.read_bytes() == original
    assert not (proj / "phase2/stage1/rtl").exists()


@pytest.mark.parametrize("suffix", [".vh", ".svh", ".vhd", ".vhdl"])
def test_serial_native_dispatch_preserves_foreign_rtl_suffixes(tmp_path, suffix):
    import rtl_provenance as provenance
    proj = _mk_project(tmp_path, ports=_SPM_PORTS, top="neutral_serial",
                       l2_text="serial-parallel multiplier: p = (x * y) mod 2^N")
    rtl = proj / "phase2/stage1/rtl"
    rtl.mkdir(parents=True)
    foreign = rtl / ("foreign_authored" + suffix)
    original = b"-- independently authored RTL artifact\n"
    foreign.write_bytes(original)
    result = runner.step_rtl_gen(proj, "digital_arithmetic_primitive")
    assert result.status == "PASS_WITH_WAIVERS", result.detail
    verdict, reason, evidence = provenance.classify(proj)
    assert verdict == provenance.UNKNOWN, (verdict, reason, evidence)
    assert evidence["files"] == [foreign.name]
    assert foreign.read_bytes() == original
    assert not provenance.ledger_path(proj).exists()
