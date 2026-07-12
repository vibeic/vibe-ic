#!/usr/bin/env python3
"""sdf_gate_sim.py — REAL SDF-annotated gate-level simulation (canonical Step 29).

Drives the *routed* (post-PnR) gate netlist through Icarus Verilog with
``$sdf_annotate`` back-annotation of the STA-generated SDF and a calibrated
functional self-check, then writes::

    phase3/stage3/sim_postlayout/results.log
    phase3/stage3/sim_postlayout/results.json

so that ``post_layout_sim_check.py`` promotes Step 29 from SKIPPED-CONDITION
to a real PASS.

What is genuinely back-annotated
--------------------------------
Icarus Verilog's ``$sdf_annotate`` on this SDF applies the **INTERCONNECT**
(net RC / routing-parasitic) delays derived from the extracted SPEF — the run
log records the count via ``-sdf-info`` ("Created a vpiInterModPath").  This is
real post-layout delay back-annotation of the routed netlist.

Honest residual (documented, not hidden)
----------------------------------------
* This Icarus build applies **INTERCONNECT** delays but not the SDF **IOPATH**
  cell arc delays (its ``$sdf_annotate`` emits 0 "Putting delay" for IOPATH and
  0 match-errors — a known Icarus limitation).  At-speed *cell* timing sign-off
  therefore remains STA's job (Step 23/28), which this program does not
  duplicate.
* ``-gspecify`` is intentionally *not* used: this PDK's sequential models drive
  their outputs through NOTIFIER-based ``$setuphold``/``$width`` timing checks
  that Icarus does not support ("Timing checks are not supported"), which injects
  X and breaks functional simulation.  Cells therefore simulate with their
  logical (zero-arc) behaviour while the SDF interconnect delays stay active —
  a functionally-correct gate-level sim of the routed netlist.

NEVER fabricates a results.log: the file is written only from the *captured*
simulator output, and a functional mismatch is surfaced as an ERROR line so the
gate FAILs (it never silently passes).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    import _path_layout as _pl
except Exception:                       # pragma: no cover - direct-script path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import _path_layout as _pl

DEFAULT_CONTAINER = os.environ.get("VIBEIC_EDA_CONTAINER", "vibeic-eda")
_TOOL_PATH = "export PATH=/foss/tools/bin:$PATH; "

# ---------------------------------------------------------------------------
# Pure helpers (unit-tested; no container / filesystem side effects)
# ---------------------------------------------------------------------------


def serial_golden(x: int, y: int, width: int) -> int:
    """Closed-form reference for the bit-serial multiplier: (x*y) mod 2**width.

    Unsigned and two's-complement share the low `width` bits of the product.
    """
    mask = (1 << width) - 1
    return (x * y) & mask


_ANNOT_RE = re.compile(r"Created a vpiInterModPath")
_RESULT_RE = re.compile(r"GATE_SIM_RESULT\s+(PASS|FAIL)\s+(\d+)/(\d+)")
_LOCK_RE = re.compile(r"locked:\s*order=(\w+)\s+latency=(\d+)")
_CALFAIL_RE = re.compile(r"CALIBRATION_FAIL")
# same contract post_layout_sim_check.py enforces: a results.log line that
# starts (after optional whitespace / "** ") with FATAL or ERROR fails the gate.
_FATAL_LINE_RE = re.compile(r"^\s*(\*\*\s*)?(FATAL|ERROR)\b", re.IGNORECASE | re.MULTILINE)


def parse_sim_stdout(text: str) -> Dict[str, object]:
    """Extract the annotated-delay count + functional verdict from vvp stdout."""
    annotated = len(_ANNOT_RE.findall(text))
    lock = _LOCK_RE.search(text)
    res = _RESULT_RE.search(text)
    out: Dict[str, object] = {
        "annotated_interconnect_delays": annotated,
        "calibrated": bool(lock),
        "bit_order": lock.group(1) if lock else None,
        "latency": int(lock.group(2)) if lock else None,
        "verdict": res.group(1) if res else ("FAIL" if _CALFAIL_RE.search(text) else None),
        "passed": int(res.group(2)) if res else 0,
        "total": int(res.group(3)) if res else 0,
    }
    return out


def _curate_transcript(sim_stdout: str) -> str:
    """Keep the SDF header + functional lines; drop the ~634 verbose per-net
    'Created a vpiInterModPath' / 'INTERCONNECT with' lines (the raw transcript
    is preserved verbatim in sim_stdout.log; the net-delay count is summarised
    above)."""
    keep: List[str] = []
    drop = re.compile(r"Created a vpiInterModPath|INTERCONNECT with port|"
                      r"Substituting vpiPort|Putting delay")
    for ln in sim_stdout.splitlines():
        if drop.search(ln):
            continue
        keep.append(ln)
    return "\n".join(keep).rstrip("\n")


def build_results_log(meta: Dict[str, object], sim_stdout: str) -> str:
    """Assemble the results.log text from captured simulator output.

    Guarantees (for the PASS path) that no line starts with FATAL/ERROR so the
    gate's ``_FATAL_RE`` does not trip; a functional FAIL is surfaced as an
    explicit ERROR line so the gate correctly FAILs.
    """
    v = meta.get("verdict")
    lines: List[str] = []
    lines.append("================================================================")
    lines.append(" SDF-annotated post-layout gate-level simulation (Step 29)")
    lines.append("================================================================")
    lines.append(f"design           : {meta.get('top')}")
    lines.append(f"netlist          : {meta.get('netlist')}  (post-PnR routed)")
    lines.append(f"cell library     : {meta.get('pdk_lib')}  (PDK timing model)")
    lines.append(f"sdf file         : {meta.get('sdf')}")
    lines.append(f"simulator        : {meta.get('simulator')}")
    lines.append(f"compile flags    : {meta.get('compile_flags')}")
    lines.append(f"runtime flags    : {meta.get('runtime_flags')}")
    lines.append("")
    lines.append("-- SDF back-annotation --")
    lines.append(f"$sdf_annotate(\"{meta.get('sdf')}\", {meta.get('top')}_dut)")
    lines.append(f"annotated INTERCONNECT (net RC) delays : "
                 f"{meta.get('annotated_interconnect_delays')}")
    lines.append("note: this Icarus build back-annotates SDF INTERCONNECT "
                 "delays; SDF IOPATH cell-arc delays are not applied by "
                 "iverilog (at-speed cell timing is signed off by STA).")
    lines.append("")
    lines.append("-- functional self-check (calibrated streaming scoreboard) --")
    lines.append(f"golden model     : p-stream == (x*y) mod 2^{meta.get('width')}")
    lines.append(f"bit_order/latency: order={meta.get('bit_order')} "
                 f"latency={meta.get('latency')}  (auto-calibrated)")
    lines.append(f"vectors          : {meta.get('passed')}/{meta.get('total')} matched")
    lines.append("")
    lines.append("-- simulator transcript (curated; full raw in sim_stdout.log) --")
    lines.append(_curate_transcript(sim_stdout))
    lines.append("")
    if v == "PASS":
        lines.append(f"VERDICT: PASS — real SDF-annotated gate-level sim, "
                     f"{meta.get('passed')}/{meta.get('total')} vectors matched golden.")
    else:
        # Surface a genuine failure so the gate FAILs (never a silent pass).
        lines.append(f"ERROR: gate-level SDF simulation did not pass "
                     f"({meta.get('passed')}/{meta.get('total')} vectors matched; "
                     f"verdict={v}).")
    text = "\n".join(lines) + "\n"
    if v == "PASS":
        assert not _FATAL_LINE_RE.search(text), (
            "internal error: PASS results.log unexpectedly contains a "
            "FATAL/ERROR-at-line-start")
    return text


# Verilog testbench template.  Markers @@NAME@@ are substituted (avoids
# str.format brace-escaping over the Verilog source).
_TB_TEMPLATE = r"""// GENERATED by sdf_gate_sim.py — SDF-annotated gate-level self-checking TB.
// Calibrated streaming scoreboard (reuses the professional cocotb TB model):
//   golden = (x*y) mod 2^WIDTH, auto-derived (bit_order, latency).
`timescale 1ns/1ps
`ifndef SDF_FILE
  `define SDF_FILE "@@SDF@@"
`endif
`ifndef HALF
  `define HALF 5
`endif
module @@TB@@;
  localparam integer N      = @@WIDTH@@;
  localparam integer MAXLAT = N + 4;
  localparam integer CAPLEN = N + MAXLAT;

  reg              clk = 1'b0;
  reg              rst = 1'b0;
  reg  [N-1:0]     xin = {N{1'b0}};
  reg              yin = 1'b0;
  wire             pout;

  @@TOP@@ @@TOP@@_dut (.@@CLK@@(clk), .@@RST@@(rst),
                       .@@XPORT@@(xin), .@@YPORT@@(yin), .@@PPORT@@(pout));

  initial $sdf_annotate(`SDF_FILE, @@TOP@@_dut);

  always #(`HALF) clk = ~clk;

  reg [CAPLEN-1:0] pstream;
  integer          lock_order, lock_lat, fails, total;

  task do_reset;
    integer k;
    begin
      rst = 1'b1; xin = {N{1'b0}}; yin = 1'b0;
      for (k = 0; k < 3; k = k + 1) @(posedge clk);
      rst = 1'b0;
      @(posedge clk);
    end
  endtask

  task drive_capture(input [N-1:0] xv, input [N-1:0] yv, input integer order_msb);
    integer i; reg ybit;
    begin
      xin = xv;
      for (i = 0; i < CAPLEN; i = i + 1) begin
        if (i < N) ybit = order_msb ? yv[N-1-i] : yv[i];
        else       ybit = 1'b0;
        yin = ybit;
        @(posedge clk);
        pstream[i] = pout;
      end
    end
  endtask

  function [N-1:0] reconstruct(input integer lat, input integer order_msb);
    integer j; reg [N-1:0] v;
    begin
      v = {N{1'b0}};
      for (j = 0; j < N; j = j + 1)
        if (order_msb) v[N-1-j] = pstream[lat + j];
        else           v[j]     = pstream[lat + j];
      reconstruct = v;
    end
  endfunction

  function [N-1:0] golden(input [N-1:0] xv, input [N-1:0] yv);
    golden = xv * yv;                 // low N bits of the product (mod 2^N)
  endfunction

  task try_calibrate(input [N-1:0] xv, input [N-1:0] yv, output integer done);
    integer ord, lat; reg [N-1:0] exp;
    begin
      done = 0;
      exp  = golden(xv, yv);
      for (ord = 0; ord <= 1 && !done; ord = ord + 1) begin
        do_reset;
        drive_capture(xv, yv, ord);
        for (lat = 0; lat <= MAXLAT && !done; lat = lat + 1)
          if (reconstruct(lat, ord) == exp) begin
            lock_order = ord; lock_lat = lat; done = 1;
          end
      end
    end
  endtask

  task check_vector(input [N-1:0] xv, input [N-1:0] yv);
    reg [N-1:0] exp, act;
    begin
      do_reset;
      drive_capture(xv, yv, lock_order);
      exp = golden(xv, yv);
      act = reconstruct(lock_lat, lock_order);
      total = total + 1;
      if (act !== exp) begin
        fails = fails + 1;
        $display("MISMATCH  x=%0d y=%0d exp=%0d got=%0d", xv, yv, exp, act);
      end else begin
        $display("ok  x=%0d y=%0d  p=%0d", xv, yv, act);
      end
    end
  endtask

  integer ci, done, seed;
  reg [N-1:0] rx, ry;
  initial begin
    lock_order = 0; lock_lat = 0; fails = 0; total = 0; seed = 32'hC0FFEE;
    $display("=== @@TOP@@ SDF-annotated gate-level simulation ===");
    $display("SDF back-annotation via $sdf_annotate(\"%s\")", `SDF_FILE);

    done = 0;
    try_calibrate(32'd3, 32'd3, done);
    if (!done) try_calibrate(32'd5, 32'd7, done);
    if (!done) try_calibrate({N{1'b1}}, {N{1'b1}}, done);
    if (!done) begin
      $display("CALIBRATION_FAIL: no (order,latency) reproduces (x*y) mod 2^N");
      $display("GATE_SIM_RESULT FAIL 0/0 vectors");
      $finish;
    end
    $display("streaming scoreboard locked: order=%s latency=%0d",
             lock_order ? "msb" : "lsb", lock_lat);

    check_vector(32'd0, 32'd0);
    check_vector(32'd0, {N{1'b1}});
    check_vector({N{1'b1}}, 32'd0);
    check_vector(32'd1, 32'd1);
    check_vector({N{1'b1}}, {N{1'b1}});
    check_vector(32'd2, {N{1'b1}});
    check_vector({N{1'b1}}, 32'd2);
    check_vector({1'b0, {(N-1){1'b1}}}, 32'd3);
    check_vector(32'd12345, 32'd6789);
    check_vector(32'hA5A5A5A5, 32'h5A5A5A5A);

    for (ci = 0; ci < 40; ci = ci + 1) begin
      rx = $random(seed);
      ry = $random(seed);
      check_vector(rx, ry);
    end

    if (fails == 0)
      $display("GATE_SIM_RESULT PASS %0d/%0d vectors, order=%s latency=%0d",
               total, total, lock_order ? "msb" : "lsb", lock_lat);
    else
      $display("GATE_SIM_RESULT FAIL %0d/%0d vectors mismatched", fails, total);
    $finish;
  end

  initial begin
    #5000000;
    $display("WATCHDOG_TIMEOUT");
    $finish;
  end
endmodule
"""


# ---------------------------------------------------------------------------
# Netlist / PDK / SDF resolution
# ---------------------------------------------------------------------------

_MODULE_RE = re.compile(r"^\s*module\s+([A-Za-z_][\w$]*)\s*[(;]", re.MULTILINE)
_INST_RE = re.compile(r"^\s*([A-Z][A-Za-z0-9_$]*)\s+([A-Za-z_][\w$]*)\s*\(",
                      re.MULTILINE)
# an instance line with an EMPTY port list, e.g. `FILL1 FILLER_0 ();`
_EMPTY_INST_RE = re.compile(r"^\s*([A-Z][A-Za-z0-9_$]*)\s+[A-Za-z_][\w$]*\s*\(\s*\)\s*;",
                           re.MULTILINE)


def find_netlist(project: Path, top: str) -> Optional[Path]:
    """Prefer the POST-PnR routed netlist (its instance names match the SDF)."""
    cands = [
        _pl.pnr_dir(project) / f"{top}_pnr.v",
        _pl.pnr_dir(project) / f"{top}.pnr.v",
    ]
    cands += sorted(_pl.pnr_dir(project).glob("*_pnr.v"))
    cands += [_pl.synth_dir(project) / f"{top}_synth.v"]
    cands += sorted(_pl.synth_dir(project).glob("*_synth.v"))
    for c in cands:
        if c.is_file():
            return c
    return None


def find_pdk_verilog(project: Path, used_cells: set) -> Optional[Path]:
    """Pick the PDK cell Verilog model that defines the used cells + specify."""
    root = project / "input/pdk/verilog"
    if not root.is_dir():
        return None
    best, best_score = None, -1
    for vf in sorted(root.rglob("*.v")):
        try:
            txt = vf.read_text(errors="replace")
        except OSError:
            continue
        defined = set(_MODULE_RE.findall(txt))
        score = len(used_cells & defined)
        # tie-break toward a model that actually carries timing (specify)
        if "specify" in txt:
            score += 1
        if score > best_score:
            best, best_score = vf, score
    return best if best_score > 0 else None


def find_sdf(project: Path, top: str) -> Optional[Path]:
    """Locate a REAL (non-stub) SDF in sim_postlayout/ or extracted/."""
    sim_dir = _pl.sim_postlayout_dir(project)
    cands = list(sim_dir.glob("*.sdf"))
    ext = _pl.extracted_dir(project)
    if ext.is_dir():
        cands += list(ext.glob("*.sdf"))
    for sf in cands:
        try:
            head = sf.read_text(errors="replace")[:1500]
        except OSError:
            continue
        if re.search(r"NOT a real SDF|\(fallback\)", head, re.IGNORECASE):
            continue
        return sf
    return None


def netlist_cells_and_ports(text: str, top: str) -> Tuple[set, Dict[str, object]]:
    """Return (used-cell-types, top-port-info)."""
    defined = set(_MODULE_RE.findall(text))
    used = set(m.group(1) for m in _INST_RE.finditer(text)) - defined - {"module"}
    # top port declarations: input/output/inout with optional [msb:lsb]
    ports: Dict[str, object] = {}
    mtop = re.search(r"module\s+" + re.escape(top) + r"\s*\(", text)
    if mtop:
        seg = text[mtop.start():]
        for pm in re.finditer(
                r"^\s*(input|output|inout)\s*(?:wire|reg)?\s*"
                r"(?:\[\s*(\d+)\s*:\s*(\d+)\s*\]\s*)?([A-Za-z_][\w$]*)\s*;",
                seg, re.MULTILINE):
            hi = pm.group(2)
            width = (abs(int(pm.group(2)) - int(pm.group(3))) + 1) if hi else 1
            ports[pm.group(4)] = {"dir": pm.group(1), "width": width}
            if pm.group(4) == "endmodule":
                break
    return used, ports


def missing_empty_cell_stubs(text: str, used: set, pdk_text: str) -> List[str]:
    """Cells instantiated with an EMPTY port list that the PDK does not model."""
    pdk_defined = set(_MODULE_RE.findall(pdk_text))
    empty_cells = set(m.group(1) for m in _EMPTY_INST_RE.finditer(text))
    return sorted((used & empty_cells) - pdk_defined)


# ---------------------------------------------------------------------------
# Container execution
# ---------------------------------------------------------------------------


def _docker(container: str, cmd: str, timeout: int = 600):
    return subprocess.run(
        ["docker", "exec", container, "bash", "-lc", _TOOL_PATH + cmd],
        capture_output=True, text=True, timeout=timeout)


def _detect_serial_mult(ports: Dict[str, object]) -> Optional[Dict[str, str]]:
    """Match the bit-serial multiplier contract; return the port mapping or None.

    Needs: a clock, a reset, exactly one multi-bit input (x), exactly one 1-bit
    input other than clk/rst (y, serial), and exactly one 1-bit output (p).
    """
    clk = next((n for n in ports if n.lower() in ("clk", "clock", "ck")), None)
    rst = next((n for n in ports
                if n.lower() in ("rst", "reset", "rstn", "rst_n", "resetn")), None)
    if not clk or not rst:
        return None
    ctrl = {clk, rst}
    ins = [n for n, i in ports.items() if i["dir"] == "input" and n not in ctrl]
    outs = [n for n, i in ports.items() if i["dir"] == "output"]
    multi_in = [n for n in ins if ports[n]["width"] > 1]
    one_in = [n for n in ins if ports[n]["width"] == 1]
    one_out = [n for n in outs if ports[n]["width"] == 1]
    if len(multi_in) == 1 and len(one_in) == 1 and len(one_out) == 1:
        return {"clk": clk, "rst": rst, "xport": multi_in[0],
                "yport": one_in[0], "pport": one_out[0],
                "width": ports[multi_in[0]]["width"]}
    return None


def run(project, top: str = "spm", container: str = DEFAULT_CONTAINER,
        notes: Optional[list] = None, half_period: int = 5) -> Dict[str, object]:
    """Runner-callable entry point.  Writes results.log/json on a real run.

    Returns a verdict dict.  On NOT_APPLICABLE (ports don't match the serial-
    multiplier contract) or a hard tool error it writes NOTHING (letting the
    runner emit its honest SKIPPED-CONDITION note).
    """
    project = Path(project)
    notes = notes if notes is not None else []
    sim_dir = _pl.sim_postlayout_dir(project)

    netlist = find_netlist(project, top)
    if not netlist:
        notes.append("sdf_gate_sim: no post-PnR/synth netlist found")
        return {"verdict": "NOT_APPLICABLE", "reason": "no netlist"}
    ntext = netlist.read_text(errors="replace")
    used, ports = netlist_cells_and_ports(ntext, top)
    portmap = _detect_serial_mult(ports)
    if not portmap:
        notes.append(f"sdf_gate_sim: {top} ports do not match the serial-"
                     f"multiplier contract ({sorted(ports)}) — skipping")
        return {"verdict": "NOT_APPLICABLE", "reason": "port shape"}

    sdf = find_sdf(project, top)
    if not sdf:
        notes.append("sdf_gate_sim: no real SDF found")
        return {"verdict": "NOT_APPLICABLE", "reason": "no sdf"}

    pdk_lib = find_pdk_verilog(project, used)
    if not pdk_lib:
        notes.append("sdf_gate_sim: no PDK cell Verilog model found")
        return {"verdict": "NOT_APPLICABLE", "reason": "no pdk lib"}

    width = int(portmap["width"])
    sim_dir.mkdir(parents=True, exist_ok=True)

    # emit physical-cell stubs (fillers with no PDK model, empty port list)
    stubs = missing_empty_cell_stubs(ntext, used, pdk_lib.read_text(errors="replace"))
    stub_path = sim_dir / "phys_cell_stubs.v"
    stub_body = ["// Auto-generated empty stubs for physical-only cells with no",
                 "// PDK Verilog model (instantiated with empty port lists).",
                 "`timescale 1ns/1ps"]
    stub_body += [f"module {c} (); endmodule" for c in stubs]
    stub_path.write_text("\n".join(stub_body) + "\n")

    # emit the testbench
    tb_name = f"tb_{top}_sdf"
    tb = (_TB_TEMPLATE
          .replace("@@TB@@", tb_name)
          .replace("@@TOP@@", top)
          .replace("@@CLK@@", portmap["clk"])
          .replace("@@RST@@", portmap["rst"])
          .replace("@@XPORT@@", portmap["xport"])
          .replace("@@YPORT@@", portmap["yport"])
          .replace("@@PPORT@@", portmap["pport"])
          .replace("@@SDF@@", str(sdf))
          .replace("@@WIDTH@@", str(width)))
    tb_path = sim_dir / f"{tb_name}.v"
    tb_path.write_text(tb)

    # compile + run inside the container.  -ginterconnect enables SDF net-delay
    # back-annotation; -gspecify is deliberately omitted (see module docstring).
    vvp = sim_dir / f"{top}_gatesim.vvp"
    compile_flags = "-g2012 -ginterconnect"
    runtime_flags = "-sdf-info"
    cc = (f"cd {sim_dir} && "
          f"iverilog {compile_flags} -DSDF_FILE='\"{sdf}\"' -DHALF={half_period} "
          f"-s {tb_name} -o {vvp.name} {tb_path.name} {netlist} "
          f"{stub_path.name} {pdk_lib} > compile.log 2>&1; echo RC=$?")
    try:
        cr = _docker(container, cc, timeout=600)
    except Exception as e:                              # pragma: no cover
        notes.append(f"sdf_gate_sim: compile invocation failed: {e}")
        return {"verdict": "ERROR", "reason": f"compile invoke: {e}"}
    if "RC=0" not in cr.stdout:
        notes.append("sdf_gate_sim: iverilog compile failed (see compile.log)")
        return {"verdict": "ERROR", "reason": "compile failed"}

    rr = (f"cd {sim_dir} && vvp {vvp.name} {runtime_flags} "
          f"> sim_stdout.log 2> sim_stderr.log; echo RC=$?")
    try:
        _docker(container, rr, timeout=600)
    except Exception as e:                              # pragma: no cover
        notes.append(f"sdf_gate_sim: sim invocation failed: {e}")
        return {"verdict": "ERROR", "reason": f"sim invoke: {e}"}

    sim_stdout = (sim_dir / "sim_stdout.log").read_text(errors="replace") \
        if (sim_dir / "sim_stdout.log").is_file() else ""
    parsed = parse_sim_stdout(sim_stdout)

    meta: Dict[str, object] = {
        "top": top, "width": width,
        "netlist": str(netlist), "pdk_lib": str(pdk_lib), "sdf": str(sdf),
        "simulator": "Icarus Verilog (iverilog/vvp) 14",
        "compile_flags": compile_flags, "runtime_flags": runtime_flags,
        **parsed,
    }
    log_text = build_results_log(meta, sim_stdout)
    (sim_dir / "results.log").write_text(log_text)
    (sim_dir / "results.json").write_text(json.dumps({
        "program": "sdf_gate_sim", "version": "1.0.0",
        "verdict": parsed["verdict"],
        "annotated_interconnect_delays": parsed["annotated_interconnect_delays"],
        "functional": {"passed": parsed["passed"], "total": parsed["total"],
                       "bit_order": parsed["bit_order"], "latency": parsed["latency"]},
        "artifacts": {"netlist": str(netlist), "pdk_lib": str(pdk_lib),
                      "sdf": str(sdf), "testbench": str(tb_path),
                      "phys_stubs": str(stub_path)},
    }, indent=2, ensure_ascii=False) + "\n")
    # a real results.log supersedes any prior honest SKIPPED-CONDITION note —
    # remove the stale sentinel so flow-compliance sees a single, consistent
    # signal (a real PASS, not "skipped").
    if parsed["verdict"] == "PASS":
        stale = sim_dir / "sdf_sim_skipped.json"
        if stale.is_file():
            try:
                stale.unlink()
            except OSError:
                pass
    notes.append(f"sdf_gate_sim: {parsed['verdict']} "
                 f"({parsed['passed']}/{parsed['total']} vectors, "
                 f"{parsed['annotated_interconnect_delays']} SDF net delays)")
    return {"verdict": parsed["verdict"], "meta": meta,
            "results_log": str(sim_dir / "results.log")}


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("project_dir")
    ap.add_argument("--top", default="spm")
    ap.add_argument("--container", default=DEFAULT_CONTAINER)
    ap.add_argument("--half-period", type=int, default=5,
                    help="clock half-period in ns (default 5 → 10ns period)")
    ap.add_argument("--json", default=None)
    args = ap.parse_args(argv)

    project = Path(args.project_dir)
    if not project.is_dir():
        print(f"ERROR: not a directory: {project}", file=sys.stderr)
        return 2
    notes: List[str] = []
    verdict = run(project, top=args.top, container=args.container,
                  notes=notes, half_period=args.half_period)
    for n in notes:
        print(n)
    out = json.dumps(verdict.get("meta", verdict), indent=2, ensure_ascii=False)
    if args.json:
        Path(args.json).write_text(out)
    print(f"VERDICT: {verdict.get('verdict')}")
    return 0 if verdict.get("verdict") == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
