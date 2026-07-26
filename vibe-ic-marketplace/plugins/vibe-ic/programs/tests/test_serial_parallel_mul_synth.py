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

  WIDTH (repair — the first revision hardcoded 32):
    * the emitted parameter default equals the width the SPEC declares (16 /
      32 / 64, symbolic or integer), not a constant. These tests FAIL against
      the first-field-wins resolver that shipped in the capture.
    * an unresolvable or self-contradictory declared width DEFERs.

  RUNNER SEAM (repair — the capture's 59-line hook was pinned by nothing):
    * ``design_one_shot_runner.step_rtl_gen`` itself is driven. These tests
      FAIL when the runner hunk is reverted, and they pin the two behaviours
      the hook must NOT break: a pre-staged ``input/vendor_rtl/`` REUSED-IP
      WAIVE and an ip-catalog hit both still win, and the emitted tree is
      stamped in the provenance ledger.

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

_HAVE_IVERILOG = shutil.which("iverilog") is not None


def _mk_project(tmp: Path, *, ports, l2_text, top="spm") -> Path:
    root = tmp / top
    gd = root / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L2_FRS.json").write_text(json.dumps(
        {"ic_name": top, "frs_sections": [{"content": l2_text}]},
        ensure_ascii=False))
    (gd / "L9_INTEGRATION_SPEC.json").write_text(json.dumps(
        {"top_module": top, "top_ports": ports}, ensure_ascii=False))
    return root


def _x_port(width_field: str = "N-bit(`[size-1:0]`,parameter `size` 預設 32)"):
    """The parallel operand exactly as a real phase1 L9 lays it out: the
    parameter NAME lives in ``width_symbolic`` and the declared DEFAULT lives in
    the sibling ``width`` field. Resolving only the first field that carries the
    name is what made every emission 32 bits wide."""
    return {"name": "x", "direction": "input", "width": width_field,
            "width_symbolic": "size-1:0", "lsb": "0"}


_SPM_PORTS = [
    {"name": "clk", "direction": "input", "width": 1},
    {"name": "rst", "direction": "input", "width": 1},
    _x_port(),
    {"name": "y", "direction": "input", "width": 1},
    {"name": "p", "direction": "output", "width": 1},
]
_L2_MUL = "serial-parallel multiplier: p = (x * y) mod 2^N"


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
    assert spec["size_default"] == 32


def _run(cmd, cwd):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)


def _stream_matches_golden(work: Path, rtl_text: str, size: int = 8,
                           parameterized: bool = True) -> bool:
    """Compile <rtl> + an independent TB, drive LSB-first, and check the
    reassembled p-stream equals (x*y) mod 2^size at ONE calibrated latency."""
    (work / "dut.v").write_text(rtl_text)
    inst = "spm #(.size(size)) dut" if parameterized else "spm dut"
    (work / "tb.v").write_text(
        _TB.replace("__SIZE__", str(size)).replace("__INST__", inst))
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
  __INST__(.clk(clk),.rst(rst),.x(x),.y(y),.p(p));
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


# ── WIDTH: read from the spec, never defaulted ────────────────────────────────
# The capture's resolver looped over (width_symbolic, width, msb) and RETURNED
# on the first field carrying the parameter NAME. On the real phase1 L9 layout
# that is width_symbolic ("size-1:0"), which carries no default — so the
# 預設/default regex never saw the sibling `width` field and EVERY emission was
# 32 bits regardless of the spec. Nothing downstream catches it:
# l9_rtl_pin_consistency_check compares pin names + directions and discards
# widths. These tests FAIL against that resolver.

@pytest.mark.parametrize("declared", [8, 16, 32, 64])
def test_declared_symbolic_default_is_honoured(tmp_path, declared):
    ports = [p if p["name"] != "x" else
             _x_port(f"N-bit(`[size-1:0]`,parameter `size` 預設 {declared})")
             for p in _SPM_PORTS]
    proj = _mk_project(tmp_path, ports=ports, l2_text=_L2_MUL)
    spec, reason = spm.extract_serial_parallel_mul_spec(
        proj, "digital_arithmetic_primitive")
    assert spec is not None, reason
    assert spec["size_default"] == declared, (
        f"spec declares 預設 {declared} but the solver resolved "
        f"{spec['size_default']} — the declared width is being ignored")
    rtl = spm.emit_rtl(spec)
    assert f"parameter size = {declared}" in rtl, rtl[:900]


def test_declared_english_default_is_honoured(tmp_path):
    """Same field layout, English prose."""
    ports = [p if p["name"] != "x" else
             _x_port("N-bit [WIDTH-1:0], parameter WIDTH default 24")
             for p in _SPM_PORTS]
    ports = [dict(p, width_symbolic="WIDTH-1:0") if p["name"] == "x" else p
             for p in ports]
    proj = _mk_project(tmp_path, ports=ports, l2_text=_L2_MUL)
    spec, reason = spm.extract_serial_parallel_mul_spec(
        proj, "digital_arithmetic_primitive")
    assert spec is not None, reason
    assert (spec["size_param"], spec["size_default"]) == ("WIDTH", 24)


def test_integer_width_l9_emits_that_width(tmp_path):
    """An L9 that states a plain integer width must produce THAT width — and no
    invented parameter symbol the spec never declared."""
    ports = [p if p["name"] != "x" else
             {"name": "x", "direction": "input", "width": 12, "msb": 11,
              "lsb": 0}
             for p in _SPM_PORTS]
    proj = _mk_project(tmp_path, ports=ports, l2_text=_L2_MUL)
    spec, reason = spm.extract_serial_parallel_mul_spec(
        proj, "digital_arithmetic_primitive")
    assert spec is not None, reason
    assert spec["size_default"] == 12
    assert spec["size_param"] is None
    rtl = spm.emit_rtl(spec)
    assert "input  wire [12-1:0] x" in rtl, rtl[:900]
    assert "parameter" not in rtl, "no parameter may be invented for a fixed width"


def test_defer_when_parametric_width_has_no_declared_default(tmp_path):
    """FAIL-CLOSED: a parameter with no resolvable default must DEFER to
    spec-to-rtl, NOT silently become 32."""
    ports = [p if p["name"] != "x" else
             {"name": "x", "direction": "input", "width": "size-1:0",
              "width_symbolic": "size-1:0", "msb": "size-1", "lsb": "0",
              "description": "parallel multiplicand"}
             for p in _SPM_PORTS]
    proj = _mk_project(tmp_path, ports=ports, l2_text=_L2_MUL)
    spec, reason = spm.extract_serial_parallel_mul_spec(
        proj, "digital_arithmetic_primitive")
    assert spec is None, f"must DEFER on an unresolvable width, got {spec}"
    assert "width" in reason.lower()


def test_defer_when_declared_widths_conflict(tmp_path):
    """msb says 16 bits, the prose says 32 — the spec contradicts itself, so
    the solver must refuse rather than pick one."""
    ports = [p if p["name"] != "x" else
             dict(_x_port(), msb=15)
             for p in _SPM_PORTS]
    proj = _mk_project(tmp_path, ports=ports, l2_text=_L2_MUL)
    spec, reason = spm.extract_serial_parallel_mul_spec(
        proj, "digital_arithmetic_primitive")
    assert spec is None, f"must DEFER on conflicting widths, got {spec}"
    assert "conflict" in reason.lower()


def test_defer_on_bidirectional_port(tmp_path):
    """``inout`` starts with "in"; classifying it as an input would emit a
    module whose port list silently disagrees with L9."""
    ports = _SPM_PORTS + [{"name": "sda", "direction": "inout", "width": 1}]
    proj = _mk_project(tmp_path, ports=ports, l2_text=_L2_MUL)
    spec, reason = spm.extract_serial_parallel_mul_spec(
        proj, "digital_arithmetic_primitive")
    assert spec is None, f"must DEFER on a bidirectional port, got {spec}"
    assert "bidirectional" in reason


def test_defer_on_port_with_unrecognised_direction(tmp_path):
    """A declared top port the solver cannot classify used to be collected and
    IGNORED — the emitted module simply omitted it."""
    ports = _SPM_PORTS + [{"name": "vdd", "width": 1}]
    proj = _mk_project(tmp_path, ports=ports, l2_text=_L2_MUL)
    spec, reason = spm.extract_serial_parallel_mul_spec(
        proj, "digital_arithmetic_primitive")
    assert spec is None, f"must DEFER on an unclassifiable port, got {spec}"
    assert "unrecognised direction" in reason


@pytest.mark.skipif(not _HAVE_IVERILOG, reason="iverilog not installed")
def test_fixed_width_rtl_matches_golden(tmp_path):
    """The no-parameter emission is still a correct multiplier — the width
    repair must not have broken the datapath."""
    ports = [p if p["name"] != "x" else
             {"name": "x", "direction": "input", "width": 8, "msb": 7, "lsb": 0}
             for p in _SPM_PORTS]
    proj = _mk_project(tmp_path, ports=ports, l2_text=_L2_MUL)
    spec, reason = spm.extract_serial_parallel_mul_spec(
        proj, "digital_arithmetic_primitive")
    assert spec is not None, reason
    assert spec["size_param"] is None
    assert _stream_matches_golden(tmp_path, spm.emit_rtl(spec), size=8,
                                  parameterized=False), \
        "fixed-width serial-parallel multiplier RTL failed the (x*y) mod 2^N golden"


# ── RUNNER SEAM: design_one_shot_runner.step_rtl_gen itself ───────────────────
# The capture shipped a 59-line hook in design_one_shot_runner.py that NO test
# imported: reverting only that hunk still left the suite green. Everything
# below drives step_rtl_gen for real, so the hook is pinned — and so are the
# two deliberate existing routes it must never preempt.

@pytest.fixture
def runner():
    """design_one_shot_runner with its RTL-session globals isolated.

    step_rtl_gen takes process-wide ownership of rtl/ on a successful
    generation; leaving that set would make the next test skip the guard and
    would leave an atexit stamp pointing at a deleted tmp_path."""
    import design_one_shot_runner as dosr
    dosr._RTL_SESSION_OWNED, dosr._RTL_SESSION_PROJECT = False, None
    try:
        yield dosr
    finally:
        # Left FALSE, not restored: the atexit finalizer early-returns on
        # False, so a deleted tmp_path is never re-stamped at process exit.
        dosr._RTL_SESSION_OWNED, dosr._RTL_SESSION_PROJECT = False, None


def _rtl_files(proj: Path):
    d = proj / "phase2" / "stage1" / "rtl"
    return sorted(p.name for p in d.glob("*.v")) if d.is_dir() else []


def test_runner_emits_serial_parallel_multiplier(tmp_path, runner):
    """THE hook test. Reverting the design_one_shot_runner.py hunk makes this
    FAIL (the class WAIVEs to spec-to-rtl with an empty rtl/)."""
    ports = [p if p["name"] != "x" else
             _x_port("N-bit(`[size-1:0]`,parameter `size` 預設 16)")
             for p in _SPM_PORTS]
    proj = _mk_project(tmp_path, ports=ports, l2_text=_L2_MUL)
    res = runner.step_rtl_gen(proj, "digital_arithmetic_primitive")
    assert res.status == "PASS", f"{res.status} | {res.detail}"
    assert "serial-parallel multiplier" in str(res.detail)
    assert _rtl_files(proj) == ["spm.v"]
    # the runner must ship the width the SPEC declared, end to end
    body = (proj / "phase2" / "stage1" / "rtl" / "spm.v").read_text()
    assert "parameter size = 16" in body, body[:900]


def test_runner_resolves_class_synonyms(tmp_path, runner):
    """The registry declares digital_datapath / arithmetic_primitive /
    pure_datapath as SYNONYMS of digital_arithmetic_primitive; the hook must
    key off the resolved registry entry, not a hand-copied name list."""
    proj = _mk_project(tmp_path, ports=_SPM_PORTS, l2_text=_L2_MUL)
    res = runner.step_rtl_gen(proj, "pure_datapath")
    assert res.status == "PASS", f"{res.status} | {res.detail}"


def test_runner_stamps_rtl_provenance(tmp_path, runner):
    """Without the stamp rtl_provenance.classify() calls generator output
    'unknown → treated as authored', permanently mislabelling it and making the
    NEXT run refuse to regenerate a tree the runner fully owns."""
    import rtl_provenance as prov
    proj = _mk_project(tmp_path, ports=_SPM_PORTS, l2_text=_L2_MUL)
    res = runner.step_rtl_gen(proj, "digital_arithmetic_primitive")
    assert res.status == "PASS", f"{res.status} | {res.detail}"
    verdict, why, _ev = prov.classify(proj)
    assert verdict not in prov.PRESERVE_VERDICTS, (
        f"emitted RTL classified {verdict!r} ({why}) — the generator's own "
        f"output is being reported as hand-authored")
    ledger = prov.load_ledger(proj)
    assert ledger and ledger.get("generator") == "serial_parallel_mul_synth.py"


def test_runner_still_waives_to_catalog_glue_for_staged_vendor_rtl(
        tmp_path, runner):
    """ORGANIC #542. Design-provided IP pre-staged in input/vendor_rtl/ is a
    DELIBERATE reuse route. The capture ran its hook BEFORE this branch and
    silently discarded the staged IP in favour of generated RTL; this test
    FAILS against that ordering."""
    proj = _mk_project(tmp_path, ports=_SPM_PORTS, l2_text=_L2_MUL)
    vendor = proj / "input" / "vendor_rtl"
    vendor.mkdir(parents=True)
    (vendor / "spmv_vendor.v").write_text("module spmv(); endmodule\n")
    res = runner.step_rtl_gen(proj, "digital_arithmetic_primitive")
    assert res.status == "WAIVED", f"{res.status} | {res.detail}"
    assert "catalog-glue-author" in str(res.detail)
    assert _rtl_files(proj) == [], (
        "the pre-staged vendor IP was silently replaced by generated RTL")


def test_runner_still_waives_when_ip_catalog_matches(tmp_path, runner,
                                                     monkeypatch):
    """Same principle for a pre-validated catalog IP: a confident match routes
    to catalog-glue-author, and the generator must not override it."""
    import ip_catalog_query

    class _M:
        category, ip_name, version = "arithmetic", "serial_mul", "1.0"
        license, confidence = "Apache-2.0", 0.9
        matched_pattern, manifest_path = "serial multiplier", "x/manifest.json"

    monkeypatch.setattr(ip_catalog_query, "query_catalog",
                        lambda *a, **k: [_M()], raising=True)
    proj = _mk_project(tmp_path, ports=_SPM_PORTS, l2_text=_L2_MUL)
    res = runner.step_rtl_gen(proj, "digital_arithmetic_primitive")
    assert res.status == "WAIVED", f"{res.status} | {res.detail}"
    assert "catalog-glue-author" in str(res.detail)
    assert _rtl_files(proj) == []


def test_runner_never_overwrites_existing_rtl(tmp_path, runner):
    """Author guard: RTL already in the tree is left byte-identical."""
    proj = _mk_project(tmp_path, ports=_SPM_PORTS, l2_text=_L2_MUL)
    rtl_dir = proj / "phase2" / "stage1" / "rtl"
    rtl_dir.mkdir(parents=True)
    authored = rtl_dir / "spm.v"
    authored.write_text("// hand authored\nmodule spm(); endmodule\n")
    res = runner.step_rtl_gen(proj, "digital_arithmetic_primitive")
    assert res.status == "WAIVED", f"{res.status} | {res.detail}"
    assert authored.read_text() == "// hand authored\nmodule spm(); endmodule\n"


def test_runner_waives_when_width_unresolvable(tmp_path, runner):
    """The solver's FAIL-CLOSED width verdict must reach the runner as the
    UNCHANGED spec-to-rtl WAIVE — not as a PASS holding an invented width."""
    ports = [p if p["name"] != "x" else
             {"name": "x", "direction": "input", "width": "size-1:0",
              "width_symbolic": "size-1:0", "msb": "size-1"}
             for p in _SPM_PORTS]
    proj = _mk_project(tmp_path, ports=ports, l2_text=_L2_MUL)
    res = runner.step_rtl_gen(proj, "digital_arithmetic_primitive")
    assert res.status == "WAIVED", f"{res.status} | {res.detail}"
    assert "spec-to-rtl" in str(res.detail)
    assert _rtl_files(proj) == []


def test_runner_unchanged_for_non_arithmetic_class(tmp_path, runner):
    """No other class may be pulled into this generator."""
    proj = _mk_project(tmp_path, ports=_SPM_PORTS, l2_text=_L2_MUL)
    res = runner.step_rtl_gen(proj, "processor_cpu")
    assert res.status == "WAIVED", f"{res.status} | {res.detail}"
    assert _rtl_files(proj) == []


def test_runner_waives_for_adder_shape(tmp_path, runner):
    """Shape fail-close reaches the runner too."""
    ports = [
        {"name": "clk", "direction": "input", "width": 1},
        {"name": "rst", "direction": "input", "width": 1},
        {"name": "a", "direction": "input",
         "width": "N-bit(`[N-1:0]`,parameter `N` 預設 16)",
         "width_symbolic": "N-1:0"},
        {"name": "b", "direction": "input", "width": 1},
        {"name": "s", "direction": "output", "width": 1},
    ]
    proj = _mk_project(tmp_path, ports=ports, top="ser_adder",
                       l2_text="serial adder: s = a + b, an N-bit adder core")
    res = runner.step_rtl_gen(proj, "digital_arithmetic_primitive")
    assert res.status == "WAIVED", f"{res.status} | {res.detail}"
    assert _rtl_files(proj) == []
