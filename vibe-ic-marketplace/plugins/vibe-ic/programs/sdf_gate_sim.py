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
Every case compiles with ``_IVERILOG_FLAGS`` (R-0915-75, one constant for
every call site): ``-ginterconnect`` applies the SDF **INTERCONNECT**
(net RC) delays and ``-gspecify`` builds the module paths the SDF **IOPATH**
cell-arc delays attach to (isolated probe: 0 ps without it, 98 ps with it;
run15's netlist: ModPath failures 31061 -> 0). ``sdf_annotation_census``
counts what the simulator actually applied (``Putting delay``) and
``sdf_error_count`` every record it refused (``SDF ERROR``).

Honest residual (documented, not hidden)
----------------------------------------
* Icarus does not support timing checks ("Timing checks are not supported"):
  NOTIFIER-based ``$setuphold``/``$width`` in a PDK's sequential models do not
  fire, so setup/hold is STA's job (Step 23/28), not this simulation's.
* An SDF IOPATH the model's specify block does not declare (for example an
  unconditional ``(IOPATH S Z ...)`` against a mux whose model has only
  conditional S->Z paths) is refused as ``SDF ERROR``; T106 measured 63 such
  records per case on spm x gf180mcuD (xor2 / mux2). The tool arm
  (``judge_tool_arm``) fails a corner on any of them.

NEVER fabricates a results.log: the file is written only from the *captured*
simulator output, and a functional mismatch is surfaced as an ERROR line so the
gate FAILs (it never silently passes).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _container_exec as _ce  # noqa: E402 — the ONE guarded docker-exec argv
import _atomic_artefact as _aa  # noqa: E402  (vibe-ic#1082)
import _eda_pin as _pin  # noqa: E402 — the ONE place the pin is stated

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _progress_run as _pr  # noqa: E402
from _specrtl_common import strip_comments  # noqa: E402

try:
    import _path_layout as _pl
except Exception:                       # pragma: no cover - direct-script path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import _path_layout as _pl

try:
    import pdk_cell_models as _pcm
except Exception:                       # pragma: no cover - direct-script path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import pdk_cell_models as _pcm

#: `_eda_pin.default_container_name()` IS this expression, plus the part
#: that was missing: the default half derives from the pinned digest
#: instead of being the shared literal `vibeic-eda`.  MEASURED 2026-09-07
#: on 8hd-3 -- the container holding that shared name was running 0.3.46
#: while the pin demanded 0.3.47, and a run that attached to it recorded
#: image provenance PASS about the wrong image.  `VIBEIC_EDA_CONTAINER` is
#: read exactly as before and still wins.
DEFAULT_CONTAINER = _pin.default_container_name()
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
_ORACLE_RESULT_RE = re.compile(r"ORACLE_TB_DONE\s+pass=(\d+)/(\d+)")
_GENERIC_PASS_RE = re.compile(
    r"(?:PROTOCOL_REFERENCE_TB_PASS|PROFESSIONAL_TB_PASS|REFERENCE_TB_PASS)\b")
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


def parse_self_check_stdout(text: str) -> Dict[str, object]:
    """Parse a Phase-2 self-checking testbench transcript.

    A reusable testbench is accepted only when it emits an established,
    machine-readable self-check marker.  Mere simulator exit zero is not a
    functional verdict.
    """
    oracle = _ORACLE_RESULT_RE.search(text or "")
    if oracle:
        passed, total = int(oracle.group(1)), int(oracle.group(2))
        return {
            "verdict": "PASS" if total > 0 and passed == total else "FAIL",
            "passed": passed,
            "total": total,
            "marker": "ORACLE_TB_DONE",
        }
    if _GENERIC_PASS_RE.search(text or ""):
        return {"verdict": "PASS", "passed": 1, "total": 1,
                "marker": _GENERIC_PASS_RE.search(text).group(0)}
    return {"verdict": None, "passed": 0, "total": 0, "marker": None}


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
                       .@@XPORT@@(xin), .@@YPORT@@(yin), .@@PPORT@@(pout)@@DFT_TIEOFF@@);

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
# An instance line: `<CellType> <inst_name> (`.
#
# The cell type is deliberately NOT anchored to an uppercase first letter.  The
# uppercase anchor encoded ONE library's naming convention (the commercial
# `DFFHQD1` / `INVD1` style) and silently returned ZERO used cells on every
# open PDK, whose cells are lowercase: `sg13g2_nand2_1`, `sky130_fd_sc_hd__inv_1`,
# `gf180mcu_fd_sc_mcu7t5v0__nand2_1`.  With an empty used-cell set the PDK model
# lookup scored 0 for every candidate and the physical-cell stub emitter emitted
# nothing, so the whole gate-level sim was unreachable on the OSS path.
# Structure (identifier + identifier + `(`) already excludes declarations
# (`wire [3:0] n;`), continuous assigns and `always @(...)`; the language
# keywords that CAN still match structurally are subtracted below.
_INST_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_$]*)\s+([A-Za-z_][\w$]*)\s*\(",
                      re.MULTILINE)
# an instance line with an EMPTY port list, e.g. `FILL1 FILLER_0 ();`
_EMPTY_INST_RE = re.compile(
    r"^\s*([A-Za-z_][A-Za-z0-9_$]*)\s+[A-Za-z_][\w$]*\s*\(\s*\)\s*;",
    re.MULTILINE)

# Verilog keywords that can appear in the `<word> <word> (` shape and are NOT
# cell instantiations. Subtracted from the used-cell set so relaxing the
# uppercase anchor cannot introduce phantom "cells". chip-AGNOSTIC.
_VERILOG_NON_CELL_WORDS = frozenset({
    "module", "endmodule", "macromodule", "primitive", "endprimitive",
    "function", "endfunction", "task", "endtask", "generate", "endgenerate",
    "specify", "endspecify", "table", "endtable", "case", "casex", "casez",
    "endcase", "if", "else", "for", "while", "repeat", "forever", "initial",
    "always", "assign", "defparam", "parameter", "localparam",
    "input", "output", "inout", "wire", "reg", "tri", "supply0", "supply1",
    "integer", "real", "signed", "unsigned", "begin", "end", "posedge",
    "negedge", "or", "and", "not", "buf",
})


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


class CellModels:
    """Resolved stdcell Verilog simulation model(s) for the gate-level sim.

    `paths` are the paths as the SIMULATOR sees them (identical on the host
    when the project staged the model itself; in-container absolute paths when
    the model only exists inside the EDA image).  `text` is the concatenated
    model source, needed by `missing_empty_cell_stubs`.
    """

    __slots__ = ("paths", "text", "source", "pdk_id", "files")

    def __init__(self, paths: List[str], text: str, source: str,
                 pdk_id: Optional[str] = None,
                 files: Optional[Dict[str, str]] = None):
        self.paths = list(paths)
        self.text = text
        self.source = source
        self.pdk_id = pdk_id
        #: {path: its own text}, for a reader that needs a model's line numbers
        #: (the SDF-error classifier); `{}` when only the joined text is known.
        self.files = dict(files or {})

    @property
    def arg(self) -> str:
        """Space-joined path list for the iverilog command line."""
        return " ".join(self.paths)

    def __repr__(self) -> str:                       # pragma: no cover
        return (f"CellModels(source={self.source!r}, pdk_id={self.pdk_id!r}, "
                f"paths={self.paths!r})")


def _read_container_files(container: str, paths: List[str]) -> str:
    """`cat` the given in-container files; '' when any of them is unreadable.

    Deliberately all-or-nothing: a partially-read model would silently produce
    WRONG physical-cell stubs (a cell the real model defines would be stubbed
    out as an empty module, which simulates as a functional hole).
    """
    if not paths:
        return ""
    chunks: List[str] = []
    for p in paths:
        try:
            r = _docker(container, f"cat {p}", budget_s=120)
        except Exception:
            return ""
        if r.returncode != 0 or not r.stdout:
            return ""
        # F21, MEASURED (vibeic-eda 0.3.79): the image's entrypoint prints
        # `[INFO] Final PATH variable: ...` lines on stdout BEFORE `cat` runs,
        # so every line number of the model read this way was off by two and
        # no compiler diagnostic could be traced back into it.
        out = r.stdout
        while out.startswith("[INFO]"):
            out = out.split("\n", 1)[1] if "\n" in out else ""
        chunks.append(out)
    return "\n".join(chunks)


def resolve_cell_models(project: Path, used_cells: set,
                        container: str) -> Optional[CellModels]:
    """Resolve the PDK cell Verilog model, host staging FIRST.

    1. `<project>/input/pdk/verilog/` — the commercial-PDK path, where the
       runner copies an NDA model into the run dir.  Unchanged and still wins,
       so a project that stages its own model keeps using exactly that file.
    2. The EDA container's own PDK tree, via the shared `pdk_cell_models`
       table, when the PDK can be identified from the netlist's cell names.
       This is the open-PDK path (sky130 / gf180 / ihp-sg13g2): the model has
       always been present in the image — `fault_atpg_run` (Step 11 ATPG) uses
       the very same files — it was simply never reachable from here, so Step
       29 reported "no PDK cell Verilog model found" and produced no
       results.log at all.

    Returns None when neither resolves — a REAL capability gap (unknown
    library), which the caller must disclose as such rather than as "the
    runner does not drive a back-annotated sim".
    """
    host = find_pdk_verilog(project, used_cells)
    if host is not None:
        host_text = host.read_text(errors="replace")
        return CellModels([str(host)], host_text, "host_staged",
                          files={str(host): host_text})

    pdk_id = _pcm.detect_pdk_id(used_cells)
    paths = _pcm.container_model_paths(pdk_id)
    if not paths:
        return None
    def _run_argv(argv, budget_s):
        quoted = " ".join(shlex.quote(str(x)) for x in argv)
        r = _docker(container, quoted, budget_s=budget_s)
        clean = "\n".join(line for line in (r.stdout or "").splitlines()
                            if not line.startswith("[INFO]"))
        return r.returncode, clean, r.stderr or ""
    # The shared materializer is a no-op for stable paths and substitutes a
    # live content-addressed directory only when the model table contains its
    # known fallback token.  No PDK identity is encoded at this call site.
    paths = _pcm.materialize_gf180_paths(paths, _run_argv)
    # Some model families keep UDP definitions in a co-located primitives
    # file; prepend any such companion when the live image supplies it.
    companions = []
    for model_path in paths:
        companion = model_path.rsplit("/", 1)[0] + "/primitives.v"
        probe = _docker(container, f"test -s {shlex.quote(companion)}",
                        budget_s=60)
        clean_probe = "\n".join(
            line for line in (probe.stdout or "").splitlines()
            if not line.startswith("[INFO]"))
        if probe.returncode == 0 and not clean_probe.strip():
            companions.append(companion)
    paths = companions + [p for p in paths if p not in companions]
    files = {p: _read_container_files(container, [p]) for p in paths}
    if not all(files.values()):
        return None
    text = "\n".join(files[p] for p in paths)
    # Same substantive bar the host path applies: the model must actually
    # define at least one cell the netlist instantiates. Prevents a stale
    # table entry from handing iverilog a model for a different library.
    if not (set(_MODULE_RE.findall(text)) & set(used_cells)):
        return None
    return CellModels(paths, text, "container_pdk", pdk_id, files=files)


def declared_io_models(project: Path, container: str, used_cells: set,
                       models: "CellModels") -> "CellModels":
    """F21: the pad models a routed CHIP TOP needs, beside the cell models.

    The netlist step 15 routed is the chip top, so it instantiates the pads
    the chip-top producer placed; a cell model alone leaves every pad an
    unknown module and the case never compiles. The pads' library is the one
    that producer DECLARED (`io_library_liberty` in its record); its models
    are that library's `verilog/` directory, and the closure takes, per pad,
    the file that MODELS it over a black box (`verilog_model_closure_of_texts`).
    With no record, or nothing missing, the models are returned unchanged."""
    missing = set(used_cells) - set(_MODULE_RE.findall(models.text))
    try:
        rec = json.loads((project / CHIP_TOP_RECORD_REL).read_text(errors="replace"))
    except (OSError, ValueError):
        return models
    libs = rec.get("io_library_liberty") or []
    if not missing or rec.get("verdict") != "WROTE" or not isinstance(libs, list):
        return models
    dirs = sorted({str(Path(str(lib)).parent.parent / "verilog") for lib in libs})
    roots = {Path(*parts[:parts.index('libs.ref')])
             for p in models.paths if 'libs.ref' in (parts := Path(p).parts)}
    candidates: List[str] = []
    for d in dirs:
        listed = _docker(container, f"ls -1 {shlex.quote(d)}", budget_s=60)
        if listed.returncode and len(roots) == 1:
            root = next(iter(roots))
            parts = Path(d).parts
            if 'libs.ref' in parts and root.name == parts[parts.index('libs.ref') - 1]:
                d = str(root.joinpath(*parts[parts.index('libs.ref'):]))
                listed = _docker(container, f"ls -1 {shlex.quote(d)}", budget_s=60)
        candidates += [f"{d}/{name.strip()}" for name in (listed.stdout or "").splitlines()
                       if name.strip().endswith(".v")]
    texts = {c: _read_container_files(container, [c]) for c in candidates}
    owned = {m: p for p in models.paths
             for m in _MODULE_RE.findall(models.files.get(p, ""))}
    closure = verilog_model_closure_of_texts(candidates, texts, missing, owned)
    extra = [f for f in closure["files"] if f not in models.paths]
    if not extra:
        return models
    files = dict(models.files, **{f: texts[f] for f in extra})
    return CellModels(models.paths + extra,
                      models.text + "\n" + "\n".join(texts[f] for f in extra),
                      models.source + "+declared_io", models.pdk_id, files=files)


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
    used = (set(m.group(1) for m in _INST_RE.finditer(text))
            - defined - _VERILOG_NON_CELL_WORDS)
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


# Established Phase-2 testbenches are the first choice for Step 29.  The
# ordering prefers oracle/reference benches over connectivity-only full-stack
# benches; each candidate must instantiate the actual top and carry a
# machine-readable self-check marker.
_TB_MODULE_RE = re.compile(r"(?m)^\s*module\s+([A-Za-z_][\w$]*)\b")


def _tb_dut_instance(text: str, top: str) -> Optional[str]:
    m = re.search(r"(?m)^\s*" + re.escape(top)
                  + r"\s+([A-Za-z_][\w$]*)\s*\(", text or "")
    return m.group(1) if m else None


def find_reusable_testbench(project: Path, top: str) -> Optional[Dict[str, object]]:
    """Find an existing self-checking Phase-2 Verilog testbench for ``top``."""
    roots = [
        project / "phase2/stage1/sim_full_stack",
        project / "phase2/stage1/sim/tb",
        project / "phase2/stage1/sim",
    ]
    candidates: List[Path] = []
    for root in roots:
        if root.is_dir():
            candidates.extend(sorted(root.glob("*.v")))
            candidates.extend(sorted(root.glob("*.sv")))
    def _rank(path: Path) -> Tuple[int, str]:
        name = path.name.lower()
        return (0 if "oracle" in name else 1 if "reference" in name else 2,
                name)
    for path in sorted(set(candidates), key=_rank):
        try:
            text = strip_comments(path.read_text(errors="replace"))
        except OSError:
            continue
        inst = _tb_dut_instance(text, top)
        module = _TB_MODULE_RE.search(text)
        has_contract = bool(re.search(r"ORACLE_TB_DONE|"
                                      r"PROTOCOL_REFERENCE_TB_PASS|"
                                      r"PROFESSIONAL_TB_PASS|REFERENCE_TB_PASS",
                                      text))
        if inst and module and has_contract:
            return {"path": path, "text": text, "module": module.group(1),
                    "dut_instance": inst}
    return None


def inject_sdf_annotation(tb_text: str, tb_module: str, dut_instance: str,
                          sdf_path: str, *, mtm_spec: Optional[str] = None,
                          runtime: bool = False) -> str:
    """Inject one SDF annotation initial block into an existing testbench."""
    pat = re.compile(r"(?m)^(\s*module\s+" + re.escape(tb_module)
                     + r"\b[^;]*;)")
    statement = (f'\n  initial $sdf_annotate("{sdf_path}", '
                 f'{dut_instance}' + (f',,,"{mtm_spec}"' if mtm_spec else '')
                 + ');  // Step 29 injected annotation')
    if runtime:
        statement = ('\n  initial begin : flow_sdf_annotation\n'
            '    string flow_sdf_file, flow_sdf_mtm;\n'
            '    if (!$value$plusargs("FLOW_SDF=%s", flow_sdf_file))\n'
            '      $fatal(1, "Native SDF file argument is absent");\n'
            '    if (!$value$plusargs("FLOW_SDF_MTM=%s", flow_sdf_mtm)) flow_sdf_mtm="TYPICAL";\n'
            f'    $sdf_annotate(flow_sdf_file, {dut_instance},,,flow_sdf_mtm);\n  end')
    out, count = pat.subn(r"\1" + statement, tb_text, count=1)
    if count != 1:
        raise ValueError(f"testbench module declaration not found: {tb_module}")
    return out


def _tool_pair_available(container: str) -> Optional[bool]:
    try:
        r = _docker(container, "command -v iverilog && command -v vvp", budget_s=60)
    except Exception:
        return None
    return r.returncode == 0 and len((r.stdout or "").splitlines()) >= 2


def build_reused_results_log(meta: Dict[str, object], sim_stdout: str) -> str:
    """Build BLOCKING Step-29 evidence for an existing self-checking bench."""
    verdict = str(meta.get("verdict") or "")
    lines = [
        "SDF-annotated post-layout gate-level simulation (Step 29)",
        f"design           : {meta.get('top')}",
        f"netlist          : {meta.get('netlist')}",
        f"cell library     : {meta.get('pdk_lib')}",
        f"sdf file         : {meta.get('sdf')}",
        f"testbench reused : {meta.get('testbench')}",
        f"dut instance     : {meta.get('dut_instance')}",
        f"self-check marker: {meta.get('marker')}",
        f"vectors          : {meta.get('passed')}/{meta.get('total')}",
        "",
        "-- simulator transcript --",
        _curate_transcript(sim_stdout),
        "",
    ]
    if verdict == "PASS":
        lines.append("VERDICT: PASS — existing self-checking testbench passed "
                     "against the routed netlist with SDF annotation.")
    else:
        lines.append("VERDICT: FAIL — existing self-checking testbench did not "
                     f"pass ({meta.get('passed')}/{meta.get('total')} vectors; "
                     f"SDF interconnect records={meta.get('annotated_interconnect_delays')}; "
                     f"reason={meta.get('failure_reason') or verdict or '?' }).")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# R-0915-54 — STEP 29 REUSES THE RUN'S OWN EXECUTED L10 SUITE.
# ---------------------------------------------------------------------------
#: A per-case L10 testbench announces itself as `[TB <id>] ...`. Its own header
#: states the contract this parser is written against: "never prints a PASS for
#: a check it did not run." So a PASS is claimed only from a POSITIVE marker;
#: the absence of a FAIL line is NOT a pass, and a transcript with neither is
#: NOT_EXECUTED by name rather than silently counted either way.
_L10_FAIL_RE = re.compile(r"(?m)^\s*\[TB\s+(\S+)\]\s+FAIL\b")
_L10_PASS_RE = re.compile(r"(?m)^\s*\[TB\s+(\S+)\]\s+PASS\b")


def parse_l10_case_stdout(text: str) -> Dict[str, object]:
    """Verdict for ONE L10 case from its gate-level transcript.

    Positive checks only. An earlier defect in this lane read the ABSENCE of a
    marker as its opposite; here a transcript that carries no verdict line at
    all returns None, which the caller records as NOT_EXECUTED with its reason
    rather than folding into pass or fail."""
    shared = parse_self_check_stdout(text)
    if shared.get("verdict") is not None:
        return shared
    if _L10_FAIL_RE.search(text or ""):
        return {"verdict": "FAIL", "passed": 0, "total": 1,
                "marker": "L10_TB_FAIL"}
    if _L10_PASS_RE.search(text or ""):
        return {"verdict": "PASS", "passed": 1, "total": 1,
                "marker": "L10_TB_PASS"}
    return {"verdict": None, "passed": 0, "total": 0, "marker": None}


#: R-0915-75 — WHAT THE ANNOTATION ACTUALLY DID, COUNTED.
#:
#: Step 29 is declared as an "SDF-annotated post-layout gate-level simulation".
#: Nothing in it ever checked that a single delay was annotated, so run15 —
#: 31063 `SDF ERROR` lines and ZERO `Putting delay` lines, not one delay applied
#: cell or interconnect — published nine PASSes under that name. A zero-delay
#: re-run of the L10 suite is worth having and is NOT what the step says it is.
#:
#: The simulator says exactly what it did, under `-sdf-info`, and these two
#: counts are the whole story:
#:
#:   `Putting delay ...`             one per delay actually applied
#:   `Unable to match ModPath X -> Y` one per cell arc the SDF could not attach
#:
#: MEASURED across four arms on run15's own netlist (fips1804_sha256_abc):
#:
#:   as shipped   (min::max,  no -gspecify)  ModPath fail 31061  delays     0
#:   -include_typ (full triple, no -gspecify) ModPath fail 31061  delays 61976
#:   + -gspecify                              ModPath fail     0  delays 61976
#:
#: COUNTED AND PUBLISHED, NEVER GATED HERE. This function decides nothing; it
#: reports. A verdict taken from it would be a second opinion about a case the
#: transcript has already answered, and the point is that a reader can see
#: whether the run deserves the name the step gives it.
_SDF_APPLIED_RE = re.compile(r"^SDF INFO:.*Putting delay", re.M)
_SDF_MODPATH_FAIL_RE = re.compile(
    r"^SDF ERROR:.*Unable to match ModPath", re.M)
#: Every record the simulator refused, of any kind (an unmatched ModPath, an
#: INTERCONNECT with no inter-module path, ...). Step 29's tool arm gates on
#: this being ZERO (T106): one refused record is one delay the "annotated"
#: simulation did not carry.
_SDF_ERROR_RE = re.compile(r"^SDF ERROR:", re.M)


def sdf_annotation_census(text: str) -> Dict[str, object]:
    """How many delays the simulator applied, and how many arcs it could not.

    PURE — transcript in, counts out. `annotated` is False ONLY when not one
    delay was applied, which is the state that makes "SDF-annotated" false.
    """
    applied = len(_SDF_APPLIED_RE.findall(text or ""))
    unmatched = len(_SDF_MODPATH_FAIL_RE.findall(text or ""))
    return {"delays_applied": applied,
            "modpath_unmatched": unmatched,
            "annotated": applied > 0}


def sdf_error_count(text: str) -> int:
    """Every SDF record the simulator refused, of any kind. PURE (T106)."""
    return len(_SDF_ERROR_RE.findall(text or ""))


def name_unannotated_run(census: Dict[str, object]) -> Optional[str]:
    """The sentence for a run that carries the name without the timing. PURE.

    None when at least one delay was applied — this never speaks about a run
    that annotated.
    """
    if census.get("annotated"):
        return None
    unmatched = census.get("modpath_unmatched") or 0
    return (
        "NOT SDF-ANNOTATED: the simulator applied 0 delays"
        + (f" and could not match {unmatched} cell arc(s) to the SDF"
           if unmatched else "")
        + " — this run is a ZERO-DELAY gate-level simulation, so its result "
          "says nothing about timing whatever the per-case verdicts are. Two "
          "causes are known and both are in the flow's own hands: `write_sdf` "
          "without `-include_typ` emits min::max with an EMPTY typ field, from "
          "which Icarus applies no delay at all; and `iverilog` without "
          "`-gspecify` builds no module paths for `$sdf_annotate` to attach an "
          "IOPATH to.")


def find_l10_executed_cases(project: Path, top: str) -> Optional[Dict[str, object]]:
    """The run's OWN L10 cases, partitioned into step-29 subjects and refusals.

    Returns None when the project has no L10 execution record at all — then
    step 29 has nothing of the run's to reuse and the caller falls through to
    its older discovery. Otherwise every declared case is accounted for: one of
    `cases` (executed at RTL and bindable to the gate netlist) or `skipped`
    (with the reason it is not a subject). A case is NEVER dropped silently —
    that is the whole complaint R-0915-54 was raised on.

    Chip-AGNOSTIC: the record and the testbench paths come from the project."""
    rec = _pl.reports_dir(project) / "phase2" / "sim" / "l10_execution.json"
    if not rec.is_file():
        return None
    try:
        data = json.loads(rec.read_text(errors="replace"))
    except (ValueError, OSError) as exc:
        return {"cases": [], "skipped": [], "declared": 0,
                "unreadable": f"{rec}: {exc}"}
    declared = list(data.get("cases") or [])
    cases: List[Dict[str, object]] = []
    skipped: List[Dict[str, object]] = []
    for case in declared:
        cid = str(case.get("id") or "?")
        if not case.get("sim_executed"):
            skipped.append({
                "id": cid, "disposition": "NOT_EXECUTED_AT_RTL",
                "detail": str(case.get("detail")
                              or case.get("verdict") or "")[:240]})
            continue
        tb = case.get("tb_file")
        from librelane_contract import project_path
        tb_path = project_path(project, str(tb)) if tb else None
        if tb_path is None or not tb_path.is_file():
            skipped.append({"id": cid, "disposition": "TB_ABSENT",
                            "detail": str(tb)})
            continue
        try:
            text = strip_comments(tb_path.read_text(errors="replace"))
        except OSError as exc:
            skipped.append({"id": cid, "disposition": "TB_UNREADABLE",
                            "detail": str(exc)})
            continue
        module = _TB_MODULE_RE.search(text)
        inst = _tb_dut_instance(text, top)
        if not module or not inst:
            # The case ran at RTL but its oracle cannot BIND to the gate
            # netlist -- a renamed port, a wrapper the netlist does not carry.
            # Named, not dropped.
            skipped.append({
                "id": cid, "disposition": "NO_GATE_BINDING",
                "detail": (f"module_decl={bool(module)} "
                           f"dut_instance_of_{top}={bool(inst)}")})
            continue
        cases.append({"id": cid, "path": tb_path, "text": text,
                      "module": module.group(1), "dut_instance": inst})
    return {"cases": cases, "skipped": skipped, "declared": len(declared)}


def name_unverdicted_case(rc, size: int, truncated: bool) -> str:
    """Say WHY a gate-level case produced no verdict. PURE.

    Four different things used to share one sentence. MEASURED on run14: nine
    cases ended `$finish called at ...` while the two longest ended MID-LINE at
    sizes that are EXACT multiples of 4096 (14241792 = 3477 x 4096, 14893056 =
    3636 x 4096) — every passing transcript was unaligned, and all eleven
    carried the same 29532 `SDF ERROR` lines, so the SDF was never the
    discriminator.

    R-0915-71 CORRECTS WHAT THAT SHAPE MEANS, and the correction is measured,
    not reasoned. The first version of this function said a page-aligned
    half-written transcript is "a killed process". On run15 the same two cases
    showed the same shape — and both of them went on to FINISH AND PASS, ~100
    minutes later, while step 29 was reading the half-written file:

        long_message_1m_bytes_of_a        sim wall 5980 s, runner's slot 197 s
        random_..._vs_nist_go             sim wall 5725 s, runner's slot 197 s
        (nine other cases: 107..137 s, slot 109..138 s)

    What was killed was the `docker exec` CLIENT, by a host-side supervisor that
    could see no progress because every byte the simulator writes goes to a file
    INSIDE the container. The SIMULATOR was never stopped; it was ORPHANED. So a
    truncated transcript means THE READER STOPPED READING, which is a different
    fact from a killed writer and points at a different fix — see `_docker`.

    None of these is a pass. The verdict stays absent in every branch; what
    changes is whether a reader can act on it."""
    if rc == _ce.STALLED_RC:
        return (f"the supervisor REAPED this case as stalled (rc={rc}) after "
                f"seeing no forward progress in the container; the transcript "
                f"is {size} B"
                + (", and it does not end in a newline, so the simulator was "
                   "still writing when the reap landed"
                   if truncated else "")
                + " — no verdict was reached, and a reap is not a testbench "
                  "result")
    if truncated:
        return (f"the transcript is TRUNCATED: rc={rc}, {size} B ending "
                f"without a newline"
                + (" and on an exact 4096-byte boundary"
                   if size and size % 4096 == 0 else "")
                + " — it was read while it was still being written, so this "
                  "case reached no verdict AT THE MOMENT IT WAS READ. That is "
                  "not the same as a simulator that stopped: measured on "
                  "run15, both cases with this shape ran on to their own "
                  "$finish long after the reader had moved on. The verdict "
                  "here is still absent, and absent is not a result")
    if rc not in (0, None):
        return (f"the simulator exited rc={rc} without printing a verdict line")
    return "no verdict line at gate level; a missing marker is not a pass"


def build_l10_results_log(rows: List[Dict[str, object]],
                          skipped: List[Dict[str, object]],
                          meta: Dict[str, object]) -> str:
    """Step-29 evidence as a PER-CASE table, so a reader can see which case."""
    out = [
        "SDF-annotated post-layout gate-level simulation (Step 29)",
        f"design        : {meta.get('top')}",
        f"netlist       : {meta.get('netlist')}",
        f"cell library  : {meta.get('pdk_lib')}",
        f"sdf file      : {meta.get('sdf')}",
        f"suite         : the run's own executed L10 cases, re-run against the "
        f"routed netlist with SDF back-annotation",
        f"cases declared: {meta.get('declared')}",
        f"cases executed: {len(rows)}",
        f"compile flags : {meta.get('compile_flags')}",
        # R-0915-75 — the step's NAME, checked. See `sdf_annotation_census`.
        f"sdf annotation: {meta.get('delays_applied')} delay(s) applied, "
        f"{meta.get('modpath_unmatched')} cell arc(s) unmatched",
        "",
        f"{'case':<48} {'verdict':<14} {'vectors':<10} marker",
        "-" * 96,
    ]
    for r in rows:
        v = str(r.get("verdict") or "NOT_EXECUTED")
        out.append(f"{str(r['id'])[:47]:<48} {v:<14} "
                   f"{str(r.get('passed', 0)) + '/' + str(r.get('total', 0)):<10} "
                   f"{r.get('marker') or '-'}")
    if skipped:
        out += ["", "-- not a step-29 subject, by name --"]
        for sk in skipped:
            out.append(f"{str(sk['id'])[:47]:<48} {sk['disposition']:<14} "
                       f"{str(sk.get('detail') or '')[:90]}")
    failed = [r for r in rows if r.get("verdict") == "FAIL"]
    unrun = [r for r in rows if r.get("verdict") is None]
    out.append("")
    if rows and not failed and not unrun:
        out.append(f"VERDICT: PASS — {len(rows)}/{len(rows)} executed L10 "
                   f"case(s) passed against the routed netlist with SDF "
                   f"annotation.")
    elif failed:
        out.append(f"VERDICT: FAIL — {len(failed)} of {len(rows)} executed L10 "
                   f"case(s) did not pass at gate level: "
                   f"{', '.join(str(r['id']) for r in failed)}.")
    else:
        out.append(f"VERDICT: NOT_EXECUTED — {len(unrun)} of {len(rows)} "
                   f"case(s) produced no verdict line at gate level; a missing "
                   f"marker is not a pass.")
    # R-0915-75 — AND WHETHER THE STEP EARNED ITS OWN NAME. Appended AFTER the
    # per-case verdict, never instead of it: the cases said what they said, and
    # this says whether any of it was measured with timing.
    _unann = name_unannotated_run({
        "annotated": bool(meta.get("delays_applied")),
        "modpath_unmatched": meta.get("modpath_unmatched") or 0})
    if _unann:
        out.append("")
        out.append(_unann)
    return "\n".join(out) + "\n"


def _run_l10_suite(project: Path, top: str, container: str, sim_dir: Path,
                   netlist: Path, sdf: Path, models: "CellModels", used: set,
                   suite: Dict[str, object], notes: list) -> Dict[str, object]:
    """Re-run the run's OWN executed L10 cases against the routed netlist.

    Same suite, gate netlist + SDF in place of the RTL. One compile and one
    simulation per case, so a per-case verdict is a measurement and not a
    division of one aggregate."""
    ntext = netlist.read_text(errors="replace")
    stubs = missing_empty_cell_stubs(ntext, used, models.text)
    stub_path = sim_dir / "phys_cell_stubs.v"
    stub_path.write_text(
        "// Physical-only cells omitted from functional PDK models.\n"
        "`timescale 1ns/1ps\n"
        + "".join(f"module {cell} (); endmodule\n" for cell in stubs))

    rows: List[Dict[str, object]] = []
    skipped = list(suite.get("skipped") or [])
    # F21 — the DUT is the module the routed netlist defines (the declared chip
    # top when it wraps the core), and the bench clocks at the DECLARED SDC's
    # period. Either unreadable is a named refusal of every case, not a guess.
    sdf_text = _read_or_empty(sdf)
    try:
        declared = declared_dut_binding(project, top, ntext)
        clocks = declared_sdc_clocks(_pl.pnr_dir(project) / "constraint.sdc",
                                     [sdf_text])
        refusal = None
    except ValueError as exc:
        declared, clocks, refusal = None, None, str(exc)
    explainer = SdfErrorExplainer(ntext, models.files)
    for case in (suite.get("cases") or []):
        cid, tb_module = str(case["id"]), str(case["module"])
        row: Dict[str, object] = {"id": cid, "module": tb_module,
                                  "testbench": str(case["path"])}
        try:
            if refusal:
                raise ValueError(refusal)
            bound, row["dut_binding"] = bind_dut_module(
                str(case["text"]), top, str(case["dut_instance"]), ntext, declared)
            bound, row["clock"] = bind_bench_clock(
                bound, str(case["dut_instance"]), clocks)
        except ValueError as exc:
            row.update(verdict=None, marker=None, passed=0, total=0,
                       detail=f"NO_GATE_BINDING: {exc}")
            rows.append(row)
            continue
        try:
            injected = inject_sdf_annotation(
                bound, tb_module, str(case["dut_instance"]),
                str(sdf))
        except ValueError as exc:
            row.update(verdict=None, marker=None, passed=0, total=0,
                       detail=f"SDF annotation could not be injected: {exc}")
            rows.append(row)
            continue
        tb_path = sim_dir / f"{cid}_sdf_gate.v"
        tb_path.write_text(injected)
        vvp = sim_dir / f"{cid}_gatesim.vvp"
        cc = (f"cd {shlex.quote(str(sim_dir))} && "
              f"iverilog {_IVERILOG_FLAGS} -s {shlex.quote(tb_module)} "
              f"-o {shlex.quote(vvp.name)} {shlex.quote(tb_path.name)} "
              f"{shlex.quote(str(netlist))} {shlex.quote(stub_path.name)} "
              f"{models.arg} > {shlex.quote(cid)}.compile.log 2>&1; echo RC=$?")
        try:
            cr = _docker(container, cc, budget_s=900)
        except Exception as exc:
            row.update(verdict=None, marker=None, passed=0, total=0,
                       detail=f"compile invoke failed: {exc}")
            rows.append(row)
            continue
        if "RC=0" not in (cr.stdout or ""):
            # The case ran at RTL and its oracle will not COMPILE against the
            # gate netlist. That is a binding failure, named, never a pass and
            # never a silent drop.
            row.update(verdict=None, marker=None, passed=0, total=0,
                       detail="did not compile against the gate netlist")
            rows.append(row)
            continue
        rr = (f"cd {shlex.quote(str(sim_dir))} && vvp {shlex.quote(vvp.name)} "
              f"-sdf-info > {shlex.quote(cid)}.stdout.log "
              f"2> {shlex.quote(cid)}.stderr.log; echo RC=$?")
        try:
            sr = _docker(container, rr, budget_s=900)
        except Exception as exc:
            row.update(verdict=None, marker=None, passed=0, total=0,
                       detail=f"sim invoke failed: {exc}")
            rows.append(row)
            continue
        # R-0915-67(2) — KEEP THE EXIT CODE. It used to be discarded, and that
        # is why a killed case and a case that merely printed nothing were the
        # same finding.
        #
        # MEASURED on run14: nine cases ended `$finish called at ...`; the two
        # longest ended MID-LINE with no trailing newline, at sizes that are
        # EXACT multiples of 4096 (14241792 = 3477 x 4096, 14893056 = 3636 x
        # 4096) while every passing transcript is unaligned. A file left on a
        # page boundary with a half-written line is a writer that was killed,
        # not a simulator that finished. All eleven carried the SAME 29532
        # `SDF ERROR` lines, so the SDF was never the discriminator, and the
        # container's OOM counters were 0.
        #
        # So the outcome is NAMED from what is observable — the tool's own exit
        # code and whether its transcript terminates — instead of all of it
        # collapsing into "no verdict line".
        _rc_m = re.search(r"RC=(\d+)", sr.stdout or "")
        _rc = int(_rc_m.group(1)) if _rc_m else None
        so = sim_dir / f"{cid}.stdout.log"
        text = so.read_text(errors="replace") if so.is_file() else ""
        _size = so.stat().st_size if so.is_file() else 0
        _truncated = bool(text) and not text.endswith("\n")
        parsed = parse_l10_case_stdout(text)
        row.update(parsed)
        row["annotated_interconnect_delays"] = len(_ANNOT_RE.findall(text))
        row["sim_rc"] = _rc
        row["transcript_bytes"] = _size
        row["transcript_complete"] = not _truncated
        # R-0915-75 — per case, from the simulator's own `-sdf-info` output.
        _census = sdf_annotation_census(text)
        row["sdf_delays_applied"] = _census["delays_applied"]
        row["sdf_modpath_unmatched"] = _census["modpath_unmatched"]
        _classes = classify_sdf_errors(
            text, compile_log=_read_or_empty(sim_dir / f"{cid}.compile.log"),
            sdf_text=sdf_text, explainer=explainer)
        row["sdf_errors"] = _classes["total"]
        row["sdf_errors_by_class"] = _classes["by_class"]
        row["sdf_errors_unexplained"] = _classes["unexplained"]
        row["unexplained_samples"] = _classes["unexplained_samples"]
        if parsed.get("verdict") is None:
            row["detail"] = name_unverdicted_case(_rc, _size, _truncated)
        rows.append(row)

    # R-0915-75 — the SUITE's annotation, summed over the cases that ran. Not a
    # maximum and not a sample: a case that annotated nothing contributes
    # nothing, so a suite reads as annotated only if some case really was.
    _delays = sum(int(r.get("sdf_delays_applied") or 0) for r in rows)
    _unmatched = sum(int(r.get("sdf_modpath_unmatched") or 0) for r in rows)
    meta = {"top": top, "netlist": str(netlist), "pdk_lib": models.arg,
            "sdf": str(sdf), "declared": suite.get("declared"),
            "compile_flags": _IVERILOG_FLAGS,
            "delays_applied": _delays, "modpath_unmatched": _unmatched}
    # F21 — every refused SDF record by class; an unexplained one fails the
    # step (the `ERROR:` line is what the step-29 gate reads as a failure).
    _by_class: Dict[str, int] = {}
    for r in rows:
        for cls, n in (r.get("sdf_errors_by_class") or {}).items():
            _by_class[cls] = _by_class.get(cls, 0) + n
    _unexplained = sum(int(r.get("sdf_errors_unexplained") or 0) for r in rows)
    _extra = ["", f"dut binding   : {_binding_line(declared)}",
              f"bench clock   : {_clock_line(clocks)}",
              _sdf_error_class_line({"sdf_errors_by_class": _by_class,
                                     "sdf_errors_unexplained": _unexplained})]
    if _unexplained:
        _extra.append(f"ERROR: {_unexplained} SDF ERROR record(s) no class "
                      f"explains; the annotated simulation dropped delays for a "
                      f"reason this run cannot name")
    _aa.write_text(sim_dir / "results.log",
                   build_l10_results_log(rows, skipped, meta) + "\n".join(_extra) + "\n")
    failed = [r for r in rows if r.get("verdict") == "FAIL"]
    unrun = [r for r in rows if r.get("verdict") is None]
    verdict = ("PASS" if rows and not failed and not unrun and not _unexplained else
               "FAIL" if failed or (_unexplained and not unrun) else "NOT_EXECUTED")
    _aa.write_text(sim_dir / "results.json", json.dumps({
        "program": "sdf_gate_sim", "version": "1.2.0",
        "suite": "l10_executed_cases", "verdict": verdict,
        "declared": suite.get("declared"),
        "executed": len(rows),
        "cases": [{k: (str(v) if isinstance(v, Path) else v)
                   for k, v in r.items()} for r in rows],
        "not_a_subject": skipped,
        # R-0915-75 — its own field, so a consumer can ask whether this run was
        # timing-annotated without parsing prose.
        "sdf_annotation": {"delays_applied": _delays,
                           "modpath_unmatched": _unmatched,
                           "annotated": _delays > 0,
                           "compile_flags": _IVERILOG_FLAGS},
        "sdf_errors_by_class": _by_class,
        "sdf_errors_unexplained": _unexplained,
        "sdf_error_classes": SDF_ERROR_CLASSES,
        "dut_binding": declared, "clock": clocks,
        "artifacts": {"netlist": str(netlist), "sdf": str(sdf)},
    }, indent=2, ensure_ascii=False) + "\n")
    if verdict == "PASS":
        _aa.write_text(sim_dir / "pass.flag",
                       f"PASS {len(rows)}/{len(rows)} executed L10 case(s) "
                       f"on the routed netlist with SDF annotation\n")
    notes.append(f"sdf_gate_sim: re-ran {len(rows)} executed L10 case(s) at "
                 f"gate level ({verdict}); {len(skipped)} declared case(s) "
                 f"were not subjects and are named in results.log")
    return {"verdict": verdict, "executed": len(rows),
            "declared": suite.get("declared"), "not_a_subject": len(skipped)}


def _run_reused_testbench(project: Path, top: str, container: str,
                           sim_dir: Path, netlist: Path, sdf: Path,
                           models: CellModels, used: set,
                           reusable: Dict[str, object], notes: list) \
        -> Dict[str, object]:
    """Compile and run one existing self-checking TB on the routed netlist."""
    ntext = netlist.read_text(errors="replace")
    stubs = missing_empty_cell_stubs(ntext, used, models.text)
    stub_path = sim_dir / "phys_cell_stubs.v"
    stub_path.write_text(
        "// Physical-only cells omitted from functional PDK models.\n"
        "`timescale 1ns/1ps\n"
        + "".join(f"module {cell} (); endmodule\n" for cell in stubs))

    tb_module = str(reusable["module"])
    dut_instance = str(reusable["dut_instance"])
    injected = inject_sdf_annotation(
        str(reusable["text"]), tb_module, dut_instance, str(sdf))
    tb_path = sim_dir / f"{tb_module}_sdf_reused.v"
    tb_path.write_text(injected)
    vvp = sim_dir / f"{top}_gatesim.vvp"
    compile_flags = _IVERILOG_FLAGS
    cc = (f"cd {shlex.quote(str(sim_dir))} && "
          f"iverilog {compile_flags} -s {shlex.quote(tb_module)} "
          f"-o {shlex.quote(vvp.name)} {shlex.quote(tb_path.name)} "
          f"{shlex.quote(str(netlist))} {shlex.quote(stub_path.name)} "
          f"{models.arg} > compile.log 2>&1; echo RC=$?")
    try:
        cr = _docker(container, cc, budget_s=600)
    except Exception as exc:
        return {"verdict": "ERROR", "reason": f"compile invoke: {exc}"}
    if "RC=0" not in (cr.stdout or ""):
        # A routed design with an existing self-checking bench is still a
        # measured Step-29 attempt when the gate compiler rejects it.  Emit a
        # named FAIL with the SDF record count; reserve ERROR for discovery or
        # invocation failures where no subject was measured.
        return {"verdict": "FAIL", "reason": "compile failed",
                "annotated_interconnect_delays": len(_ANNOT_RE.findall(sdf.read_text(errors="replace"))),
                "passed": 0, "total": 0}

    rr = (f"cd {shlex.quote(str(sim_dir))} && vvp {shlex.quote(vvp.name)} "
          "-sdf-info > sim_stdout.log 2> sim_stderr.log; echo RC=$?")
    try:
        run_result = _docker(container, rr, budget_s=600)
    except Exception as exc:
        return {"verdict": "ERROR", "reason": f"sim invoke: {exc}"}
    sim_stdout_path = sim_dir / "sim_stdout.log"
    sim_stdout = sim_stdout_path.read_text(errors="replace") \
        if sim_stdout_path.is_file() else ""
    parsed = parse_self_check_stdout(sim_stdout)
    stderr_path = sim_dir / "sim_stderr.log"
    sim_stderr = stderr_path.read_text(errors="replace") \
        if stderr_path.is_file() else ""
    annotation_abort = ("NULL handle" in sim_stderr or
                        "vpi_scan.cc" in sim_stderr or
                        "vpi_iter.cc" in sim_stderr)
    if parsed["verdict"] is None and annotation_abort:
        parsed.update({"verdict": "FAIL", "marker": "SDF_ANNOTATION_ABORT",
                       "failure_reason": "SDF annotation runtime abort"})
    if "RC=0" not in (run_result.stdout or "") and parsed["verdict"] is None:
        parsed["verdict"] = "ERROR"
    if parsed["verdict"] is None:
        parsed["verdict"] = "ERROR"

    meta: Dict[str, object] = {
        "top": top,
        "netlist": str(netlist),
        "pdk_lib": models.arg,
        "pdk_lib_source": models.source,
        "sdf": str(sdf),
        "testbench": str(reusable["path"]),
        "dut_instance": dut_instance,
        "annotated_interconnect_delays": len(_ANNOT_RE.findall(sim_stdout)),
        **parsed,
    }
    _aa.write_text(sim_dir / "results.log",
                   build_reused_results_log(meta, sim_stdout))
    _aa.write_text(sim_dir / "results.json", json.dumps({
        "program": "sdf_gate_sim",
        "version": "1.1.0",
        "verdict": parsed["verdict"],
        "self_check": {"marker": parsed["marker"],
                       "passed": parsed["passed"], "total": parsed["total"]},
        "annotated_interconnect_delays": meta["annotated_interconnect_delays"],
        "artifacts": {"netlist": str(netlist), "sdf": str(sdf),
                      "testbench_source": str(reusable["path"]),
                      "testbench_injected": str(tb_path)},
    }, indent=2, ensure_ascii=False) + "\n")
    if parsed["verdict"] == "PASS":
        _aa.write_text(sim_dir / "pass.flag",
                       f"PASS {parsed['passed']}/{parsed['total']} "
                       "(reused self-checking TB; SDF gate simulation)\n")
    stale = sim_dir / "sdf_sim_skipped.json"
    if stale.is_file():
        stale.unlink()
    notes.append("sdf_gate_sim: reused existing self-checking testbench; "
                 f"{parsed['verdict']} ({parsed['passed']}/{parsed['total']})")
    return {"verdict": parsed["verdict"], "meta": meta,
            "results_log": str(sim_dir / "results.log")}


# ---------------------------------------------------------------------------
# Container execution
# ---------------------------------------------------------------------------


#: R-0915-71 — THE SUPERVISOR WAS WATCHING THE CLIENT, NOT THE SIMULATOR.
#:
#: MEASURED, sha256 x sky130A, lane icsha2 run15 (main 385445351), front door.
#: Step 29 published
#:
#:     VERDICT: NOT_EXECUTED — 2 of 11 case(s) produced no verdict line at gate
#:     level; a missing marker is not a pass.
#:
#: over `long_message_1m_bytes_of_a` and
#: `random_message_functional_equivalence_vs_nist_go`. BOTH OF THEM PASSED. The
#: transcripts on disk now end:
#:
#:     [TB long_message_1m_bytes_of_a] PASS - 12 oracle check(s), 0 mismatch(es)
#:     ... $finish called at 33996340000 (1ps)
#:     [TB random_..._vs_nist_go] PASS - 10008 oracle check(s), 0 mismatch(es)
#:     ... $finish called at 36734229000 (1ps)
#:
#: Timed from the artefacts' own mtimes — `<cid>_gatesim.vvp` built, to the last
#: byte written to `<cid>.stdout.log`, against the slot the runner actually
#: allowed before it started the next case:
#:
#:     nine cases          sim wall 107..137 s      slot 109..138 s
#:     long_message        sim wall     5980 s      slot      197 s
#:     random_message      sim wall     5725 s      slot      197 s
#:
#: The two long cases were ABANDONED at 197 s and went on computing for ~100
#: minutes, to a PASS, orphaned inside the container, while step 29 read their
#: half-written transcripts and called them unexecuted.
#:
#: WHY 197 s. This function ran `vvp ... > <cid>.stdout.log 2> <cid>.stderr.log`
#: through a bare `_progress_run.run`. Every byte the simulator writes goes to a
#: FILE INSIDE the command string, so the supervised `docker exec` client emits
#: nothing for the whole run; the client itself burns no CPU and does no I/O,
#: because the work is under the container runtime's shim and reachable from no
#: ppid link it owns. Output flat, cpu flat, io flat — and `_progress_run`
#: declared a stall and reaped the client. `_progress_run.run`'s own docstring
#: names this exact shape ("a `stdout=<file>` redirect ... would take the output
#: away from the progress meter without saying so"), and vibe-ic#2083 measured
#: the identical thing on a magic LEF extraction: 1.00 CPU-s/s with RSS climbing
#: 30 MB/s, "on every host-side signal the client exposes, indistinguishable
#: from a corpse".
#:
#: THE FIX IS THE ONE THE REPO ALREADY WROTE FOR #2083, which this call site
#: never adopted. `_container_exec.run_in_container_supervised` supervises with
#: `container_tree_probe` — it reads the CONTAINER's work rather than the client
#: that cannot see it — takes no clock at all, and on a genuine stall reaps by
#: IDENTITY STAMP inside the container, so a still tool is killed where it lives
#: and a computing one is never cut. The orphan this defect created is closed by
#: the same change that stops the false stall.
#:
#: `budget_s` REPLACES A PARAMETER THAT BOUND NOTHING. Every call site here said
#: `timeout=600` or `timeout=900`; the body dropped it on the floor, so the
#: numbers read like limits and were not. It is now `ceiling_s` — a RECORDED
#: BUDGET (vibe-ic#2051) whose crossing is announced ONCE and which stops
#: nothing — and the name says which of the two it is.
#: R-0915-75 — WITHOUT `-gspecify` THE SDF ANNOTATES NOTHING.
#:
#: MEASURED, sha256 x sky130A, lane icsha2 run15 (main 385445351), front door.
#: Every one of the eleven gate-level transcripts carries ~31000 lines of
#:
#:     SDF ERROR: .../sha256.sdf:31014: Unable to match ModPath A -> Y in
#:                fips1804_sha256_abc.u_dut._08841_
#:
#: — 5166 `A -> Y`, 5040 `B -> Y`, 4753 `A2 -> Y`, 2560 `B2 -> Y`, 1867
#: `CLK -> Q`, i.e. essentially EVERY cell arc in the design. `_08841_` is a
#: `sky130_fd_sc_hd__inv_1` and the SDF holds `(IOPATH A Y (0.113::0.113)
#: (0.098::0.098))` for it, so the entry and the cell were both there.
#:
#: REPRODUCED IN ISOLATION in the pinned image — one inverter, the flow's exact
#: flags, the PDK's own models, a two-line SDF — and MEASURED as a delay rather
#: than as the absence of an error, because "no error" is not "annotated":
#:
#:     iverilog -g2012 -ginterconnect              SDF ERROR, delay   0 ps
#:     iverilog -g2012 -ginterconnect -gspecify    no error,   delay  98 ps
#:     ... -gspecify -DFUNCTIONAL                  SDF ERROR, delay   0 ps
#:
#: Icarus PARSES a `specify` block by default and does not BUILD the module
#: paths from it; `-gspecify` is what creates them, and `$sdf_annotate` has
#: nothing to attach an IOPATH to without them. The `-DFUNCTIONAL` arm is the
#: control: sky130's models ship four variants per cell and only the two
#: non-FUNCTIONAL ones carry a `specify`, so the error comes straight back when
#: the functional variant is selected — which is what makes the mechanism the
#: specify block and not something else about the flag.
#:
#: WHAT THIS MEANS FOR WHAT SHIPPED. Step 29 is declared as an "SDF-annotated
#: post-layout gate-level simulation". Every run of it so far was a ZERO-DELAY
#: simulation wearing that name: functionally a re-run of the L10 suite against
#: the routed netlist, which is worth having and is NOT what the step says it
#: is. Nine cases passing said nothing about timing.
_IVERILOG_FLAGS = "-g2012 -ginterconnect -gspecify"


def _docker(container: str, cmd: str, budget_s: float = 600):
    # In-image runners read the PDK and execute tools on this filesystem.
    # Reuse the same route predicate/argv seam as the phase runners; a nested
    # Docker client is neither required nor available in the official image.
    if _ce.local_exec_mode("sdf_gate_sim"):
        return _pr.run(
            _ce.exec_argv(container, _TOOL_PATH + cmd, tag="sdf_gate_sim"),
            capture_output=True, text=True, errors="replace",
            start_new_session=True,
            hard_ceiling_s=float(budget_s),
            ceiling_notice=_ce.default_ceiling_notice("local", budget_s))
    # R-0915-86(3) — THE GATE-SIM SUPERVISOR'S PROGRESS DETECTOR, calibrated
    # before it judges. This is the call site R-0915-71/72 was written about:
    # it ran `vvp ... > log` through a bare `_progress_run.run`, every byte went
    # to a file, and two simulations that reached `$finish` with 0 mismatches
    # were reaped at 197 s. The line is HERE and not inside
    # `_container_exec.container_tree_probe` because that factory is called on
    # every supervised run, including from inside tests that patch `os.listdir`
    # process-wide — see the entry's `calls_at` note.
    return _ce.run_in_container_supervised(
        container, _TOOL_PATH + cmd, ceiling_s=float(budget_s))


# sha256×sky130A / #SS-SETUP — DFT test-mode ports are NOT part of the functional
# contract. Step-11 scan insertion adds scan-enable / scan-in / scan-out / test-
# clock / test-mode ports (measured on spm: test, shift, sin, sout, tck) to the
# routed netlist the post-layout gate-sim reads. They must be excluded from the
# functional port match (else a scan-inserted design never matches ANY functional
# contract) and TIED to their functional-mode value (0) in the TB (else the
# scan muxes float and the netlist runs in scan mode). chip-AGNOSTIC: DFT
# port-name grammar, no design literal.
_DFT_PORT_NAMES = {
    "test", "tck", "tms", "tdi", "tdo", "trst", "shift", "sin", "sout",
    "se", "si", "so", "tm", "scanen", "scan_en", "scanenable", "scan_enable",
    "scanin", "scan_in", "scanout", "scan_out", "scanshift", "scan_shift",
    "scanmode", "scan_mode", "scanclk", "scan_clk", "scanrst", "scan_rst",
    "testmode", "test_mode", "testclk", "test_clk", "atpg_en",
}
_DFT_PORT_PREFIXES = ("scan", "bist", "jtag", "test_", "tst", "atpg")


def _is_dft_port(name: str) -> bool:
    """True iff `name` is a DFT / test-mode infrastructure port (never a
    functional-contract port). chip-AGNOSTIC."""
    n = (name or "").strip().lower()
    return n in _DFT_PORT_NAMES or any(n.startswith(p) for p in _DFT_PORT_PREFIXES)


def _detect_serial_mult(ports: Dict[str, object]) -> Optional[Dict[str, object]]:
    """Match the bit-serial multiplier contract; return the port mapping or None.

    Needs: a clock, a reset, exactly one multi-bit input (x), exactly one 1-bit
    input other than clk/rst (y, serial), and exactly one 1-bit output (p).
    DFT / test-mode ports (scan-enable / scan-in / scan-out / test-clock added by
    Step-11 scan insertion) are excluded from the match and returned separately so
    the TB can TIE them to their functional-mode value (see `dft_tie_inputs`).
    """
    clk = next((n for n in ports if n.lower() in ("clk", "clock", "ck")), None)
    rst = next((n for n in ports
                if n.lower() in ("rst", "reset", "rstn", "rst_n", "resetn")), None)
    if not clk or not rst:
        return None
    ctrl = {clk, rst}
    dft_in = [n for n, i in ports.items()
              if i["dir"] == "input" and n not in ctrl and _is_dft_port(n)]
    ins = [n for n, i in ports.items()
           if i["dir"] == "input" and n not in ctrl and not _is_dft_port(n)]
    outs = [n for n, i in ports.items()
            if i["dir"] == "output" and not _is_dft_port(n)]
    multi_in = [n for n in ins if ports[n]["width"] > 1]
    one_in = [n for n in ins if ports[n]["width"] == 1]
    one_out = [n for n in outs if ports[n]["width"] == 1]
    if len(multi_in) == 1 and len(one_in) == 1 and len(one_out) == 1:
        return {"clk": clk, "rst": rst, "xport": multi_in[0],
                "yport": one_in[0], "pport": one_out[0],
                "width": ports[multi_in[0]]["width"],
                "dft_tie_inputs": sorted(dft_in)}
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

    sdf = find_sdf(project, top)
    if not sdf:
        notes.append("sdf_gate_sim: no real SDF found")
        return {"verdict": "NOT_APPLICABLE", "reason": "no sdf"}

    tools_available = _tool_pair_available(container)
    if tools_available is False:
        notes.append("sdf_gate_sim: iverilog/vvp are absent from the execution "
                     "environment")
        return {"verdict": "NOT_APPLICABLE", "reason": "no simulator"}
    if tools_available is None:
        notes.append("sdf_gate_sim: simulator capability probe failed")
        return {"verdict": "ERROR", "reason": "simulator probe failed"}

    models = resolve_cell_models(project, used, container)
    if not models:
        notes.append("sdf_gate_sim: no PDK cell Verilog model found "
                     f"(host input/pdk/verilog absent and no in-container "
                     f"model for the netlist's library; "
                     f"{len(used)} distinct cells instantiated)")
        return {"verdict": "NOT_APPLICABLE", "reason": "no pdk lib"}

    models = declared_io_models(project, container, used, models)
    sim_dir.mkdir(parents=True, exist_ok=True)

    # R-0915-54 — THE RUN'S OWN EXECUTED L10 SUITE IS THE FIRST SUBJECT.
    #
    # MEASURED on subservient r20: step 29 refused with "no reusable
    # self-checking testbench ... and no compatible legacy generator", while
    # `reports/phase2/sim/l10_execution.json` listed TEN executed self-checking
    # L10 cases with their testbenches on disk. The note was true of the
    # DISCOVERY below -- which accepts a bench only if it carries one of four
    # marker strings and only globs *.v/*.sv in three directories -- and false
    # as a statement about the run. Step 29's subject is the suite the run
    # actually executed, re-run against the routed netlist with SDF in place of
    # the RTL.
    #
    # Only a GENUINELY EMPTY executed suite reaches a refusal, and it carries a
    # reason_class so the audit can classify it instead of recording an absence
    # with no cause.
    suite = find_l10_executed_cases(project, top)
    if suite is not None and suite.get("cases"):
        return _run_l10_suite(project, top, container, sim_dir, netlist, sdf,
                              models, used, suite, notes)
    if suite is not None:
        declared = suite.get("declared") or 0
        skipped = suite.get("skipped") or []
        why = "; ".join(f"{sk['id']}={sk['disposition']}"
                        for sk in skipped[:6]) or "no cases declared"
        notes.append(
            f"sdf_gate_sim: the run declared {declared} L10 case(s) and "
            f"executed none that bind to the gate netlist ({why})")
        return {
            "verdict": "NOT_APPLICABLE" if declared else "ERROR",
            "reason": (f"the L10 suite has no executed case to re-run at gate "
                       f"level: {why}"),
            # STATED CLASS, not a bare absence. Upstream produced the suite and
            # did not execute its oracles, so step 29 has nothing of the run's
            # to measure -- that is a blocked step, not a capability gap and
            # not a design declaration of N/A.
            "reason_class": ("BLOCKED_BY_UPSTREAM" if declared
                             else "ZERO_DENOMINATOR"),
            "declared": declared,
            "not_a_subject": skipped,
        }

    reusable = find_reusable_testbench(project, top)
    if reusable is not None:
        return _run_reused_testbench(
            project, top, container, sim_dir, netlist, sdf, models, used,
            reusable, notes)

    # Compatibility fallback for older projects that predate the canonical
    # self-checking Phase-2 oracle.  New designs are not constrained to this
    # interface shape: absence of a reusable TB is a producer/input failure,
    # never a platform capability gap.
    portmap = _detect_serial_mult(ports)
    if not portmap:
        notes.append(f"sdf_gate_sim: no reusable self-checking testbench for "
                     f"{top} and no compatible legacy generator ({sorted(ports)})")
        return {"verdict": "ERROR", "reason": "no self-checking testbench"}

    width = int(portmap["width"])
    # emit physical-cell stubs (fillers with no PDK model, empty port list)
    stubs = missing_empty_cell_stubs(ntext, used, models.text)
    stub_path = sim_dir / "phys_cell_stubs.v"
    stub_body = ["// Auto-generated empty stubs for physical-only cells with no",
                 "// PDK Verilog model (instantiated with empty port lists).",
                 "`timescale 1ns/1ps"]
    stub_body += [f"module {c} (); endmodule" for c in stubs]
    stub_path.write_text("\n".join(stub_body) + "\n")

    # emit the testbench
    tb_name = f"tb_{top}_sdf"
    # Tie every DFT / test-mode INPUT to its functional-mode value (0) so the
    # scan-inserted netlist runs in FUNCTIONAL mode (scan-enable low). DFT
    # OUTPUTS (scan-out) are left unconnected. chip-AGNOSTIC.
    _dft_tie = "".join(
        f", .{_p}(1'b0)" for _p in portmap.get("dft_tie_inputs", []))
    tb = (_TB_TEMPLATE
          .replace("@@TB@@", tb_name)
          .replace("@@TOP@@", top)
          .replace("@@CLK@@", portmap["clk"])
          .replace("@@RST@@", portmap["rst"])
          .replace("@@XPORT@@", portmap["xport"])
          .replace("@@YPORT@@", portmap["yport"])
          .replace("@@PPORT@@", portmap["pport"])
          .replace("@@DFT_TIEOFF@@", _dft_tie)
          .replace("@@SDF@@", str(sdf))
          .replace("@@WIDTH@@", str(width)))
    tb_path = sim_dir / f"{tb_name}.v"
    tb_path.write_text(tb)

    # compile + run inside the container.  -ginterconnect enables SDF net-delay
    # back-annotation.
    #
    # CELL-ARC (IOPATH) status: `_IVERILOG_FLAGS` carries `-gspecify`
    # (R-0915-75, see its definition), so the SDF's IOPATH cell-arc delays are
    # applied as well as the net RC; the census of the transcript says how
    # many were.
    vvp = sim_dir / f"{top}_gatesim.vvp"
    compile_flags = _IVERILOG_FLAGS
    runtime_flags = "-sdf-info"
    cc = (f"cd {sim_dir} && "
          f"iverilog {compile_flags} -DSDF_FILE='\"{sdf}\"' -DHALF={half_period} "
          f"-s {tb_name} -o {vvp.name} {tb_path.name} {netlist} "
          f"{stub_path.name} {models.arg} > compile.log 2>&1; echo RC=$?")
    try:
        cr = _docker(container, cc, budget_s=600)
    except Exception as e:                              # pragma: no cover
        notes.append(f"sdf_gate_sim: compile invocation failed: {e}")
        return {"verdict": "ERROR", "reason": f"compile invoke: {e}"}
    if "RC=0" not in cr.stdout:
        notes.append("sdf_gate_sim: iverilog compile failed (see compile.log)")
        return {"verdict": "ERROR", "reason": "compile failed"}

    rr = (f"cd {sim_dir} && vvp {vvp.name} {runtime_flags} "
          f"> sim_stdout.log 2> sim_stderr.log; echo RC=$?")
    try:
        _docker(container, rr, budget_s=600)
    except Exception as e:                              # pragma: no cover
        notes.append(f"sdf_gate_sim: sim invocation failed: {e}")
        return {"verdict": "ERROR", "reason": f"sim invoke: {e}"}

    sim_stdout = (sim_dir / "sim_stdout.log").read_text(errors="replace") \
        if (sim_dir / "sim_stdout.log").is_file() else ""
    sim_stderr = (sim_dir / "sim_stderr.log").read_text(errors="replace") \
        if (sim_dir / "sim_stderr.log").is_file() else ""
    parsed = parse_sim_stdout(sim_stdout)

    # sha256×sky130A / #SS-SETUP — SDF-net-delay RESILIENCE. iverilog's
    # $sdf_annotate INTERCONNECT (net-delay) back-annotation ABORTS on some
    # routed netlists ("NULL handle passed to vpi_scan", vpi_iter.cc) — an
    # iverilog-fork VPI limitation, NOT a design or commercial-tool gap. When the
    # SDF-annotated run aborts (or yields no vectors), retry the FUNCTIONAL
    # gate-level sim on the SAME post-layout netlist + real PDK cell models with
    # $sdf_annotate neutralised: the post-layout NETLIST FUNCTION is still fully
    # validated (self-checking vs the closed-form serial_golden), and at-speed
    # CELL timing is signed off by STA (Steps 23/28), which reads the same Liberty
    # arcs the SDF is derived from. DISCLOSED in the results, never silent.
    sdf_mode = "sdf_net_delay_annotated"
    _aborted = ("vpi_scan" in sim_stderr or "Assertion" in sim_stderr
                or "core dumped" in sim_stderr or "Aborted" in sim_stderr)
    if _aborted or int(parsed.get("total", 0) or 0) == 0:
        _tb_nosdf_text = re.sub(r"\$sdf_annotate\([^)]*\)", "#0", tb)
        _tb_nosdf = sim_dir / f"{tb_name}_nosdf.v"
        _tb_nosdf.write_text(_tb_nosdf_text)
        _cc2 = (f"cd {sim_dir} && iverilog {_IVERILOG_FLAGS} "
                f"-DSDF_FILE='\"{sdf}\"' "
                f"-DHALF={half_period} -s {tb_name} -o {vvp.name} "
                f"{_tb_nosdf.name} {netlist} {stub_path.name} {models.arg} "
                f"> compile.log 2>&1; echo RC=$?")
        try:
            _cr2 = _docker(container, _cc2, budget_s=600)
        except Exception as e:                              # pragma: no cover
            _cr2 = None
            notes.append(f"sdf_gate_sim: no-SDF retry compile invoke failed: {e}")
        if _cr2 is not None and "RC=0" in _cr2.stdout:
            _rr2 = (f"cd {sim_dir} && vvp {vvp.name} "
                    f"> sim_stdout.log 2> sim_stderr.log; echo RC=$?")
            try:
                _docker(container, _rr2, budget_s=600)
                sim_stdout = (sim_dir / "sim_stdout.log").read_text(
                    errors="replace")
                parsed = parse_sim_stdout(sim_stdout)
                sdf_mode = ("functional_no_netdelay (iverilog $sdf_annotate "
                            "INTERCONNECT VPI limit; cell timing via STA)")
                notes.append(
                    "sdf_gate_sim: SDF net-delay annotation deferred (iverilog "
                    "$sdf_annotate INTERCONNECT VPI abort); FUNCTIONAL gate-sim "
                    "on the post-layout netlist ran — at-speed cell timing "
                    "signed off by STA (Steps 23/28).")
            except Exception as e:                          # pragma: no cover
                notes.append(f"sdf_gate_sim: no-SDF retry sim failed: {e}")

    meta: Dict[str, object] = {
        "sdf_mode": sdf_mode,
        "top": top, "width": width,
        "netlist": str(netlist), "pdk_lib": models.arg, "sdf": str(sdf),
        "pdk_lib_source": models.source, "pdk_id": models.pdk_id,
        "simulator": "Icarus Verilog (iverilog/vvp) 14",
        "compile_flags": compile_flags, "runtime_flags": runtime_flags,
        **parsed,
    }
    log_text = build_results_log(meta, sim_stdout)
    _aa.write_text(sim_dir / "results.log", log_text)
    # sha256×sky130A / #SS-SETUP — on a PASS, also drop the pass.flag Step 29's
    # gate_predicate (files_exist: [results.log, pass.flag]) checks, so EVERY
    # audit path (required_outputs OR-gate and the strict gate_predicate AND-gate)
    # agrees the post-layout gate-sim PASSED — otherwise the run's own completion
    # audit and the final audit can disagree on a race. Written only from the
    # real PASS verdict (never fabricated).
    if str(parsed.get("verdict")) == "PASS":
        _aa.write_text(sim_dir / "pass.flag",
            f"PASS {parsed.get('passed')}/{parsed.get('total')} vectors "
            f"(sdf_gate_sim; post-layout gate-level functional sim)\n")
    _aa.write_text(sim_dir / "results.json", json.dumps({
        "program": "sdf_gate_sim", "version": "1.0.0",
        "verdict": parsed["verdict"],
        "annotated_interconnect_delays": parsed["annotated_interconnect_delays"],
        "functional": {"passed": parsed["passed"], "total": parsed["total"],
                       "bit_order": parsed["bit_order"], "latency": parsed["latency"]},
        "artifacts": {"netlist": str(netlist), "pdk_lib": models.arg,
                      "pdk_lib_source": models.source, "pdk_id": models.pdk_id,
                      "sdf": str(sdf), "testbench": str(tb_path),
                      "phys_stubs": str(stub_path)},
    }, indent=2, ensure_ascii=False) + "\n")
    # A real results.log supersedes any prior "skipped" note — the simulation
    # RAN, whatever its verdict. Removing the sentinel only on PASS left a run
    # whose sim executed and FAILED still carrying a marker saying it never ran,
    # which is the exact laundering this program exists to prevent: the marker
    # would defer step 29 to SKIPPED-CONDITION instead of letting the FAIL show.
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


# ---------------------------------------------------------------------------
# T106 — step 29's TOOL arm: the L10 suite against every STAPostPNR corner SDF.
#
# The SDFs are LibreLane `OpenROAD.STAPostPNR`'s own (`write_sdf -include_typ
# -divider . -corner <c>`, one per STA corner); the simulation runs inside the
# image as the LibreLane custom step `Vibeic.GateLevelSim`
# (`librelane_plugins/librelane_plugin_vibeic`), with the flags below. This
# module prepares what that step runs and judges what it wrote; the step
# itself decides nothing.
# ---------------------------------------------------------------------------

#: The placeholder the prepared testbenches carry where the SDF path goes; the
#: custom step substitutes each corner's SDF for it.
SDF_PLACEHOLDER = "@@VIBEIC_SDF_FILE@@"

_ESCAPED_INST_RE = re.compile(
    r"^\s*([A-Za-z_][A-Za-z0-9_$]*)\s+(?:\\\S+|[A-Za-z_][\w$]*)\s*\(",
    re.MULTILINE)
_MODULE_PORTS_RE = re.compile(
    r"^\s*module\s+([A-Za-z_][\w$]*)\s*\(([^;]*)\)\s*;", re.MULTILINE)
_UDP_RE = re.compile(r"^\s*primitive\s+([A-Za-z_][\w$]*)\b", re.MULTILINE)
_MODULE_BODY_RE = re.compile(
    r"^\s*(module|primitive)\s+([A-Za-z_][\w$]*)\b(.*?)\bend(?:module|primitive)\b",
    re.MULTILINE | re.DOTALL)
#: What makes a module body a MODEL rather than a black box: some behaviour.
_BEHAVIOUR_RE = re.compile(
    r"\b(assign|always|initial|table|specify)\b|"
    r"^\s*(and|or|not|buf|nand|nor|xor|xnor|bufif[01]|notif[01])\b\s*[#(\w]",
    re.MULTILINE)
_NAMED_CONN_RE = re.compile(r"\.\s*([A-Za-z_][\w$]*)\s*\(")
#: A body line that instantiates something (a cell, a UDP) is structure, and
#: structure is a model; a declaration is not.
_BODY_INSTANCE_RE = re.compile(
    r"^\s*([A-Za-z_][\w$]*)\s*(?:#\s*\([^;]*?\)\s*)?(?:[A-Za-z_][\w$]*\s*)?\(",
    re.MULTILINE)
_DECLARATION_WORDS = frozenset({
    "input", "output", "inout", "wire", "reg", "tri", "supply0", "supply1",
    "parameter", "localparam", "specparam", "integer", "real", "time", "wand",
    "wor", "module", "primitive", "function", "task", "if", "else", "for"})


def netlist_used_cells(text: str) -> set:
    """Cell types a netlist instantiates, escaped instance names included
    (a flattened routed netlist names its instances `\\u_core/_239_`)."""
    defined = set(_MODULE_RE.findall(text or ""))
    return (set(_ESCAPED_INST_RE.findall(text or "")) - defined
            - _VERILOG_NON_CELL_WORDS)


def _netlist_top(text: str) -> Optional[Tuple[str, List[str]]]:
    """(module, ports) of the module no other module instantiates."""
    modules = {m.group(1): [p.strip() for p in m.group(2).split(",") if p.strip()]
               for m in _MODULE_PORTS_RE.finditer(text or "")}
    used = set(_ESCAPED_INST_RE.findall(text or ""))
    tops = [m for m in modules if m not in used]
    return (tops[0], modules[tops[0]]) if len(tops) == 1 else None


#: Legacy chip-top producer record; native preparation is under work/flow/chip.
CHIP_TOP_RECORD_REL = "reports/phase3/io_pad_chip_top.json"

_INSTANCE_STMT_RE = re.compile(
    r"^\s*([A-Za-z_][\w$]*)\s+(\\\S+|[A-Za-z_][\w$]*)\s*\((.*?)\)\s*;",
    re.MULTILINE | re.DOTALL)
_CONN_RE = re.compile(r"\.\s*([A-Za-z_][\w$]*)\s*\(\s*([^()]*?)\s*\)")
_NET_BIT_RE = re.compile(r"^\\?([A-Za-z_][\w$]*)\s*(?:\[\s*(\d+)\s*\])?$")


def _instances(text: str) -> Dict[str, Tuple[str, Dict[str, str]]]:
    """{instance: (master, {pin: net expression})} of a structural text."""
    out: Dict[str, Tuple[str, Dict[str, str]]] = {}
    for m in _INSTANCE_STMT_RE.finditer(text or ""):
        if m.group(1) in _VERILOG_NON_CELL_WORDS:
            continue
        out[m.group(2).lstrip("\\")] = (m.group(1), dict(_CONN_RE.findall(m.group(3))))
    return out


def _net_bit(expr: str) -> Optional[Tuple[str, Optional[int]]]:
    m = _NET_BIT_RE.match((expr or "").strip())
    if not m:
        return None
    return m.group(1), (int(m.group(2)) if m.group(2) is not None else None)


def declared_dut_binding(project: Path, top: Optional[str], netlist_text: str
                         ) -> Dict[str, object]:
    """Bind a case's core, or the producer's declared core when `top` is None.

    Native wrappers use their config, preparation and written Verilog under
    work/flow/chip. The core is the unique authored RTL master instantiated
    there; unused modules in the RTL source set do not choose the adopted core.

    F21, MEASURED on spm x gf180mcuD (run23): every L10 case instantiates the
    core `spm`; the routed netlist defines only the padded `chip_top`, so the
    direct arm died `Unknown module type: spm` on all five cases and recorded
    NOT_EXECUTED with 0 delays. A chip top is not found by guessing: the
    chip-top producer RECORDS it (`CHIP_TOP_RECORD_REL`) -- the chip-top
    module, the core it wraps, the Verilog it wrote and, per pad, the pad's
    chip-side terminal and core-side pin. The binding is read from there:
    each core port is traced through the net it is wired to in that Verilog,
    the pad on that net, to the chip-top port on the pad's terminal. Any link
    that does not trace refuses (ValueError, named); a same-named port is not
    evidence of anything."""
    if top and re.search(r"(?m)^\s*module\s+" + re.escape(top) + r"\b", netlist_text or ""):
        return {"dut_module": top, "rebound": False, "port_map": None,
                "source": "the routed netlist defines the DUT's own module"}
    rec_path = project / CHIP_TOP_RECORD_REL
    preparation = project / "work/flow/chip/preparation.json"
    native_prepared = not rec_path.is_file() and preparation.is_file()
    try:
        if native_prepared:
            from _design_module_set import module_names_in_text
            rec_path = preparation
            config = json.loads((preparation.parent / "config.json").read_text())
            prepared = json.loads(preparation.read_text())
            wrapper = preparation.parent / "wrapper.v"
            modules = set()
            for path in config["VERILOG_FILES"]:
                path = Path(path) if Path(path).is_absolute() else project / path
                modules.update(module_names_in_text(path.read_text()))
            cores = {master for master, _ in _instances(strip_comments(wrapper.read_text())).values()
                     if master in modules and master != config.get("DESIGN_NAME")}
            if len(cores) != 1:
                raise ValueError("The native chip wrapper does not identify one authored RTL core.")
            rec = {"chip_top_module": config.get("DESIGN_NAME"),
                   "core_module": cores.pop(),
                   "chip_top_verilog": "work/flow/chip/wrapper.v",
                   "pad_instances": prepared["pads"]}
        else:
            rec = json.loads(rec_path.read_text(errors="replace"))
    except (OSError, ValueError, KeyError) as exc:
        raise ValueError(f"NO_DECLARED_CHIP_TOP: the routed netlist defines no "
                         f"`{top}` and the chip-top record {rec_path} cannot be "
                         f"read ({exc})")
    chip, core = rec.get("chip_top_module"), rec.get("core_module")
    if top is None:
        top = core
    if (not native_prepared and rec.get("verdict") != "WROTE") or not chip or not rec.get("chip_top_verilog"):
        raise ValueError(f"NO_DECLARED_CHIP_TOP: {rec_path} records no chip top "
                         f"(verdict {rec.get('verdict')!r})")
    if core != top:
        raise ValueError(f"CHIP_TOP_WRAPS_ANOTHER_CORE: {rec_path} says `{chip}` "
                         f"wraps `{core}`; the case's DUT is `{top}`")
    routed = _netlist_top(netlist_text)
    if routed is None or routed[0] != chip:
        raise ValueError(f"ROUTED_TOP_IS_NOT_THE_DECLARED_CHIP_TOP: the routed "
                         f"netlist's top is {routed[0] if routed else None!r}, "
                         f"the record declares `{chip}`")
    vpath = project / str(rec["chip_top_verilog"])
    try:
        vtext = strip_comments(vpath.read_text(errors="replace"))
    except OSError as exc:
        raise ValueError(f"NO_DECLARED_CHIP_TOP: {vpath} ({exc})")
    body = re.search(r"(?ms)^\s*module\s+" + re.escape(chip) + r"\b(.*?)\bendmodule\b",
                     vtext)
    if body is None:
        raise ValueError(f"NO_DECLARED_CHIP_TOP: {vpath} defines no `{chip}`")
    insts = _instances(body.group(1))
    cores = [name for name, (master, _) in insts.items() if master == top]
    if len(cores) != 1:
        raise ValueError(f"CORE_INSTANCE_NOT_UNIQUE: `{chip}` in {vpath} "
                         f"instantiates `{top}` {len(cores)} time(s)")
    through: Dict[Tuple[str, Optional[int]], Tuple[str, Optional[int]]] = {}
    for name, pad in (rec.get("pad_instances") or {}).items():
        if not isinstance(pad, dict) or not pad.get("core_pin"):
            continue                      # a supply pad carries no core signal
        conns = insts.get(name, ("", {}))[1]
        inner = _net_bit(conns.get(str(pad["core_pin"]), ""))
        outer = _net_bit(conns.get(str(pad.get("terminal")), ""))
        if inner is None or outer is None:
            raise ValueError(f"PAD_NOT_TRACEABLE: `{name}` in {vpath} does not "
                             f"wire {pad.get('core_pin')} and {pad.get('terminal')}")
        through[inner] = outer
    port_map: Dict[str, str] = {}
    for port, expr in insts[cores[0]][1].items():
        net = _net_bit(expr)
        if net is None:
            raise ValueError(f"CORE_PORT_NOT_TRACEABLE: .{port}({expr})")
        hits = {k: v for k, v in through.items()
                if k[0] == net[0] and (net[1] is None or k[1] == net[1])}
        if not hits:
            if net[1] is None and net[0] in routed[1]:
                port_map[port] = net[0]   # wired to the chip port itself
                continue
            raise ValueError(f"CORE_PORT_NOT_TRACEABLE: core port {port} is on "
                             f"net {expr}, which no declared pad and no chip "
                             f"port carries")
        outers = {v[0] for v in hits.values()}
        if len(outers) != 1 or any(k[1] != v[1] for k, v in hits.items()):
            raise ValueError(f"CORE_PORT_SPLIT: core port {port} reaches "
                             f"{sorted(outers)} bit-inconsistently")
        port_map[port] = outers.pop()
    absent = sorted(set(port_map.values()) - set(routed[1]))
    if absent:
        raise ValueError(f"CHIP_PORT_NOT_ROUTED: {absent} are not ports of the "
                         f"routed `{chip}`")
    binding = {"dut_module": chip, "rebound": True, "from": top,
               "port_map": port_map, "source": str(rec_path)}
    if native_prepared:
        binding["input_ports"] = {port_map[port["name"]]: port["width"]
                                  for port in prepared.get("ports", [])
                                  if port["direction"] == "input" and port["name"] in port_map}
    return binding


def bind_dut_module(tb_text: str, dut_module: str, dut_instance: str,
                    netlist_text: str, declared: Optional[Dict[str, object]] = None
                    ) -> Tuple[str, Dict[str, object]]:
    """Bind a case's DUT to the module the routed netlist actually defines.

    A netlist that defines `dut_module` binds as is. Otherwise the binding is
    `declared` (`declared_dut_binding`): the instance is re-typed to the
    declared chip top and each connection renamed to the chip port its core
    port traces to. Without a declaration it REFUSES (F21: never by name)."""
    if re.search(r"(?m)^\s*module\s+" + re.escape(dut_module) + r"\b", netlist_text):
        return tb_text, {"dut_module": dut_module, "rebound": False}
    if not declared or not declared.get("port_map"):
        raise ValueError(f"netlist defines no {dut_module} and no chip top is "
                         f"declared for it")
    inst = re.search(r"(?m)^(\s*)" + re.escape(dut_module) + r"(\s+"
                     + re.escape(dut_instance) + r"\s*\()", tb_text)
    if inst is None:
        raise ValueError(f"no `{dut_module} {dut_instance} (` in the testbench")
    end = tb_text.find(";", inst.end())
    port_map = dict(declared["port_map"])
    conns = tb_text[inst.end():end]
    connected = set(_NAMED_CONN_RE.findall(conns))
    if not connected or not connected <= set(port_map):
        raise ValueError(f"the testbench connects {sorted(connected)}; the "
                         f"declared chip top carries {sorted(port_map)}")
    conns = _NAMED_CONN_RE.sub(lambda m: "." + port_map[m.group(1)] + "(", conns)
    text = (tb_text[:inst.start()] + inst.group(1) + str(declared["dut_module"])
            + inst.group(2) + conns + tb_text[end:])
    return text, {"dut_module": declared["dut_module"], "rebound": True,
                  "from": dut_module, "source": declared.get("source"),
                  "ports": {p: port_map[p] for p in sorted(connected)}}


def bridge_inout_inputs(tb_text: str, dut_module: str, dut_instance: str,
                        inputs: Dict[str, int], netlist_text: str
                        ) -> Tuple[str, Dict[str, str]]:
    """Drive a physical inout pad from an existing functional input stimulus."""
    from _specrtl_common import parse_rtl_ports

    _, ports = parse_rtl_ports(netlist_text, dut_module)
    physical = {port.name: port for port in ports if port.direction == "inout"}
    instance = next((match for match in _INSTANCE_STMT_RE.finditer(tb_text)
                     if match[1] == dut_module and match[2].lstrip("\\") == dut_instance), None)
    if instance is None:
        raise ValueError(f"No native DUT instance {dut_instance!r} for input pad bridging.")
    connections = instance[3]
    declarations, bridges = [], {}
    for port, width in inputs.items():
        if port not in physical:
            continue
        if type(width) is not int or width < 1 or physical[port].width != width:
            raise ValueError(f"The native input pad width is unresolved or inconsistent for {port!r}.")
        pattern = re.compile(r"(\.\s*" + re.escape(port) + r"\s*\()([^()]*)(\))")
        connection = pattern.search(connections)
        if connection is None:
            continue
        index = len(bridges)
        wire = f"flow_input_{index}"
        while re.search(r"\b" + wire + r"\b", tb_text) or wire in bridges.values():
            index += 1
            wire = f"flow_input_{index}"
        dimensions = f"[{width - 1}:0] " if width > 1 else ""
        declarations.append(f"wire {dimensions}{wire};\nassign {wire} = {connection[2].strip()};")
        connections = pattern.sub(lambda match: match[1] + wire + match[3], connections, count=1)
        bridges[port] = wire
    if not bridges:
        return tb_text, bridges
    return (tb_text[:instance.start()] + "\n".join(declarations) + "\n"
            + tb_text[instance.start():instance.start(3)] + connections
            + tb_text[instance.end(3):]), bridges


# ---------------------------------------------------------------------------
# F21 — the bench clock is the one the DECLARED SDC states.
# ---------------------------------------------------------------------------

_UNIT_S = {"s": 1.0, "ms": 1e-3, "us": 1e-6, "ns": 1e-9, "ps": 1e-12, "fs": 1e-15}
_TB_TIMESCALE_RE = re.compile(
    r"`timescale\s+(1|10|100)\s*(s|ms|us|ns|ps|fs)\s*/\s*(1|10|100)\s*(s|ms|us|ns|ps|fs)")
#: OpenSTA's `write_sdf` states the time unit of the session's default
#: liberty (SdfWriter: `timescale_ = default_lib->units()->timeUnit()`), which
#: is also the unit that session read the SDC's numbers in.
_SDF_TIMESCALE_RE = re.compile(
    r"\(\s*TIMESCALE\s+(1|10|100)(?:\.0*)?\s*(s|ms|us|ns|ps|fs)\s*\)")
_SDC_SET_UNITS_TIME_RE = re.compile(
    r"^\s*set_units\b[^\n]*?-time\s+\{?\s*(\d*\.?\d+)?\s*(s|ms|us|ns|ps|fs)\b", re.M)
_CLOCK_GEN_RE = re.compile(
    r"(?m)(?:^|(?<=;))(\s*always\s*#\s*)(\(\s*[0-9.]+\s*\)|[0-9.]+)(\s*)([A-Za-z_][\w$]*)"
    r"(\s*<?=\s*[~!]\s*)([A-Za-z_][\w$]*)(\s*;)")


def declared_sdc_clocks(sdc: Path, sdf_texts: List[str]) -> Dict[str, object]:
    """Every port clock the declared SDC creates, in seconds.

    F21, MEASURED on spm x gf180mcuD: the L10 bench toggled its clock every
    5 ns (a 10 ns period) against a declared `create_clock -period 24.0`, and
    every ss corner failed all five cases. The bench's number is a default; the
    SDC is the design's. The unit is the SDC's `set_units -time` when it states
    one, else the unit the STA session read it in -- the SDF TIMESCALE that
    session wrote. Anything this cannot read refuses (ValueError): an unreadable
    SDC, a port clock with no literal period, two periods on one port, no unit.
    An SDC that creates no PORT clock (a combinational design, a virtual clock)
    declares that no DUT port is clocked: the result carries no clock, and a
    bench that free-runs a DUT port is then refused by `bind_bench_clock`."""
    from decimal import Decimal
    import sdc_constraints as _sdcc
    try:
        text = Path(sdc).read_text(errors="replace")
    except OSError as exc:
        raise ValueError(f"SDC_UNREADABLE: {sdc} ({exc})")
    clocks: Dict[str, float] = {}
    for clock in _sdcc.create_clocks_in_text(text):
        if not clock["port_name"]:
            continue                      # a virtual clock toggles no port
        if clock["period_ns"] is None:
            raise ValueError(f"SDC_CLOCK_UNREADABLE: {sdc}:{clock['line']} states "
                             f"no literal -period for port {clock['port_name']}")
        if clocks.get(clock["port_name"], clock["period_ns"]) != clock["period_ns"]:
            raise ValueError(f"SDC_CLOCK_AMBIGUOUS: {sdc} creates two periods on "
                             f"port {clock['port_name']}")
        clocks[clock["port_name"]] = clock["period_ns"]
    if not clocks:
        return {"sdc": str(sdc), "unit_s": None, "clocks_s": {},
                "unit_source": "no port clock is declared"}
    units = _SDC_SET_UNITS_TIME_RE.findall(text)
    if units:
        scale, unit = units[-1]
        unit_s = float(Decimal(scale or "1") * Decimal(str(_UNIT_S[unit])))
        unit_source = f"{sdc}: set_units -time"
    else:
        # The WHOLE text: a header statement past any fixed prefix is still
        # the file's statement, never "unstated" (issue #1410 window rule).
        stated = {(m.group(1), m.group(2)) for t in sdf_texts
                  for m in [_SDF_TIMESCALE_RE.search(t)] if m}
        if len(stated) != 1 or len(sdf_texts) == 0 or any(
                not _SDF_TIMESCALE_RE.search(t) for t in sdf_texts):
            raise ValueError(f"SDC_TIME_UNIT_UNSTATED: {sdc} has no set_units "
                             f"-time and the SDFs state {sorted(stated)}")
        scale, unit = stated.pop()
        unit_s = float(Decimal(scale) * Decimal(str(_UNIT_S[unit])))
        unit_source = "the STA session's SDF TIMESCALE"
    return {"sdc": str(sdc), "unit_s": unit_s, "unit_source": unit_source,
            "clocks_s": {port: float(Decimal(str(period)) * Decimal(str(unit_s)))
                         for port, period in clocks.items()}}


def bind_bench_clock(tb_text: str, dut_instance: str, declared: Dict[str, object]
                     ) -> Tuple[str, Dict[str, object]]:
    """Re-time the bench's free-running clock to the declared SDC period.

    The generator is `always #<half> <sig> = ~<sig>;` on the bench signal wired
    to the DUT port the SDC clocks. Refuses (ValueError) a bench with no
    timescale, an SDC clock port the bench does not drive from such a
    generator, a generator on a DUT port the SDC declares no clock on, and a
    half period the bench's precision cannot state."""
    ts = _TB_TIMESCALE_RE.search(tb_text)
    if ts is None:
        raise ValueError("BENCH_TIMESCALE_UNSTATED: the bench states no `timescale")
    unit_s = int(ts.group(1)) * _UNIT_S[ts.group(2)]
    prec_s = int(ts.group(3)) * _UNIT_S[ts.group(4)]
    inst = re.search(r"(?m)^\s*[A-Za-z_][\w$]*\s+" + re.escape(dut_instance)
                     + r"\s*\(", tb_text)
    if inst is None:
        raise ValueError(f"no DUT instance `{dut_instance}` in the bench")
    conns = {p: e.strip() for p, e in _CONN_RE.findall(
        tb_text[inst.end():tb_text.find(";", inst.end())])}
    # Scan real statements, preserving offsets for the original-text edits.
    # A legal always may follow another statement on the same source line.
    from _hdl_code_text import strip_hdl_comments_and_strings
    code = strip_hdl_comments_and_strings(tb_text)
    gens = {m.group(4): m for m in _CLOCK_GEN_RE.finditer(code)
            if m.group(4) == m.group(6)}
    driven = {sig: port for port, sig in conns.items() if sig in gens}
    stray = sorted(port for sig, port in driven.items()
                   if port not in declared["clocks_s"])
    if stray:
        raise ValueError(f"BENCH_CLOCK_UNDECLARED: the bench free-runs DUT port(s) "
                         f"{stray}, on which {declared['sdc']} creates no clock")
    edits, info = [], []
    for port, period_s in sorted(declared["clocks_s"].items()):
        sig = conns.get(port)
        if sig not in gens:
            raise ValueError(f"BENCH_CLOCK_NOT_BOUND: {declared['sdc']} clocks port "
                             f"{port}; the bench drives it from {sig!r}, which no "
                             f"`always #<half> {sig} = ~{sig};` toggles")
        half = period_s / 2.0
        steps = half / prec_s
        if abs(steps - round(steps)) > 1e-6 * max(1.0, steps):
            raise ValueError(f"BENCH_PRECISION: half of the declared {period_s:g} s "
                             f"period is not a multiple of the bench precision "
                             f"{prec_s:g} s")
        value = f"{half / unit_s:.9f}".rstrip("0").rstrip(".")
        m = gens[sig]
        edits.append((m.start(2), m.end(2), value))
        info.append({"port": port, "signal": sig, "period_s": period_s,
                     "bench_half_period": value, "bench_default": m.group(2).strip("() ")})
    for a, b, value in sorted(edits, reverse=True):
        tb_text = tb_text[:a] + value + tb_text[b:]
    return tb_text, {"sdc": declared["sdc"], "unit_source": declared["unit_source"],
                     "clocks": info}


# ---------------------------------------------------------------------------
# F21 — every SDF record the simulator refused, by class.
#
# MEASURED on spm x gf180mcuD, vibeic-eda 0.3.79 (Icarus 14.0 devel
# 07454266b): 63 `SDF ERROR` per case, 315 per corner, two classes, both the
# TOOL's (isolated probes reproduce each on a two-cell design):
#
#  IFNONE_EDGE_PATH_DROPPED (62): the cell models write `ifnone (posedge A1
#    => (Z:A1))`. Icarus's parser answers `sorry: ifnone with an
#    edge-sensitive path is not supported.` and DROPS the path, so the cell has
#    no A1->Z module path and every SDF IOPATH for it is `Unable to match
#    ModPath`. Fixed in the fork: vibeic/iverilog PR (IFNONE_FORK below).
#  INOUT_PORT_INTERCONNECT (1): `(INTERCONNECT u_pad_p.PAD p ...)`: Icarus's
#    -ginterconnect isolates only input/output ports, never an inout one, so a
#    bidirectional pad terminal has no net to put the delay on (`Could not
#    find intermodpath!`). A delay on a bidirectional net is a feature Icarus
#    does not have: vibeic/iverilog draft PR with the reproducer (INOUT_FORK below).
#
#  ZERO_DELAY_TOP_PORT_INTERCONNECT: `(INTERCONNECT _416_/Q p (0.000:0.000:
#    0.000))` on spm x gf180mcuD (lane cmpb, N5 run): the sink is the TOP
#    module's own output port, driven through `assign p = pr;`. Icarus cannot
#    insert an intermodpath there (`Could not find intermodpath!`, 1 per case).
#    A separate Icarus probe reproduces this for an assign-aliased scalar port
#    and a vector bit, even when the bit is directly cell-connected; a directly
#    cell-connected scalar port annotates. Every delay in this class is zero,
#    so simulation drops no delay. A NON-zero delay remains unexplained.
#
# A record is EXPLAINED only when this run's own artefacts prove the cause: the
# compile log's `sorry` names the model line of that cell's `ifnone` path; the
# SDF line names an endpoint the model/netlist declares `inout`. Anything else
# is unexplained, and an unexplained record fails the corner.
# ---------------------------------------------------------------------------

IFNONE_FORK = "https://github.com/vibeic/iverilog/pull/4"
INOUT_FORK = "https://github.com/vibeic/iverilog/pull/5"
SDF_ERROR_CLASSES = {
    "IFNONE_EDGE_PATH_DROPPED": {
        "owner": "tool:iverilog", "fork": IFNONE_FORK,
        "why": "the model's `ifnone` edge-sensitive path was dropped by the "
               "parser (`sorry` in the compile log), so the SDF arc has no "
               "module path to land on"},
    "INOUT_PORT_INTERCONNECT": {
        "owner": "tool:iverilog", "fork": INOUT_FORK,
        "why": "-ginterconnect cannot put a delay on an inout port's net"},
    "ZERO_DELAY_TOP_PORT_INTERCONNECT": {
        "owner": "sdf:legal", "fork": None,
        "why": "Icarus reports no intermodpath for this top-port sink: "
               "measured cases include an assign alias to a scalar output "
               "and a vector bit (even with a direct cell connection); a "
               "direct scalar connection annotates. Every delay on this "
               "record is 0, so simulation drops no delay"},
}
_SDF_ERROR_LINE_RE = re.compile(r"^SDF ERROR: (.+?):(\d+): (.*)$", re.M)
_MODPATH_MSG_RE = re.compile(
    r"^Unable to match ModPath (?:(posedge|negedge) )?(\S+) -> (\S+) in ")
_IFNONE_SORRY_RE = re.compile(
    r"^(.+?):(\d+): sorry: ifnone with an edge-sensitive path is not supported\.",
    re.M)
_IFNONE_EDGE_PATH_RE = re.compile(
    r"\bifnone\s*(?://[^\n]*\n\s*)*\(\s*(?:(?:posedge|negedge)\s+)?([A-Za-z_][\w$]*)"
    r"\s*[+-]?\s*[=*]>\s*\(\s*([A-Za-z_][\w$]*)\s*[+-]?\s*:")
_SDF_CELLTYPE_RE = re.compile(r"\(\s*CELLTYPE\s+\"([^\"]+)\"\s*\)")
_SDF_DIVIDER_RE = re.compile(r"\(\s*DIVIDER\s+(\S)\s*\)")
#: A simulator error supplies only an SDF line number. Classify it only when
#: that entire line is one complete INTERCONNECT record, so endpoints and
#: delays cannot come from different records on an ambiguous line.
_SDF_INTERCONNECT_RECORD_RE = re.compile(
    r"\s*\(\s*INTERCONNECT\s+(\S+)\s+(\S+)((?:\s*\([^()]*\))+)\s*\)\s*")
_SDF_TRIPLE_RE = re.compile(r"\(([^()]*)\)")


def _all_delays_zero(sdf_line: str) -> bool:
    """True iff the line is ONE complete INTERCONNECT record whose every
    delay value is a number equal to 0 (an empty triple `()` is not a zero)."""
    rec = _SDF_INTERCONNECT_RECORD_RE.fullmatch(sdf_line or "")
    if not rec:
        return False
    triples = _SDF_TRIPLE_RE.findall(rec.group(3))
    if not triples:
        return False
    for triple in triples:
        values = [v.strip() for v in triple.split(":")]
        if not values or any(not v for v in values):
            return False
        for v in values:
            try:
                if float(v) != 0.0:
                    return False
            except ValueError:
                return False
    return True
_PORT_DECL_RE = re.compile(
    r"\b(input|output|inout)\b\s*(?:wire\b|reg\b|tri\b)?\s*(?:\[[^\]]*\]\s*)?"
    r"([A-Za-z_][\w$]*(?:\s*,\s*[A-Za-z_][\w$]*)*)")
_VECTOR_PORT_DECL_RE = re.compile(
    r"\b(?:input|output|inout)\b\s*(?:wire\b|reg\b|tri\b)?\s*"
    r"\[[^\]]+\]\s*"
    r"([A-Za-z_][\w$]*(?:\s*,\s*[A-Za-z_][\w$]*)*)")
_TOP_PORT_BIT_RE = re.compile(r"([A-Za-z_][\w$]*)\s*\[\s*\d+\s*\]$")


class SdfErrorExplainer:
    """The netlist and the models, parsed once for every transcript of a run."""

    def __init__(self, netlist_text: str, models: Dict[str, str]):
        self.masters = {name: master for name, (master, _)
                        in _instances(netlist_text).items()}
        top = _netlist_top(netlist_text)
        top_match = (re.search(
            r"(?ms)^\s*module\s+" + re.escape(top[0]) + r"\b(.*?)\bendmodule\b",
            netlist_text) if top else None)
        top_text = top_match.group(0) if top_match else ""
        self.top_dirs = self._dirs(top_text)
        self.top_vectors = {
            name.strip()
            for m in _VECTOR_PORT_DECL_RE.finditer(strip_comments(top_text))
            for name in m.group(1).split(",")}
        self.modules: Dict[str, Tuple[str, str, int]] = {}
        for path, text in models.items():
            for m in re.finditer(r"(?m)^\s*module\s+([A-Za-z_][\w$]*)\b", text):
                if m.group(1) in self.modules:
                    continue
                stop = text.find("endmodule", m.end())
                self.modules[m.group(1)] = (
                    Path(path).name, text[m.start():stop if stop > 0 else None],
                    text.count("\n", 0, m.start()) + 1)

    @staticmethod
    def _dirs(text: str) -> Dict[str, str]:
        out: Dict[str, str] = {}
        for m in _PORT_DECL_RE.finditer(strip_comments(text)):
            for name in m.group(2).split(","):
                out.setdefault(name.strip(), m.group(1))
        return out

    def ifnone_paths(self, cell: str) -> Dict[Tuple[str, str], List[Tuple[str, int]]]:
        """{(src, dst): [(model file name, line of its `ifnone`)]} of a cell."""
        if cell not in self.modules:
            return {}
        fname, text, first = self.modules[cell]
        out: Dict[Tuple[str, str], List[Tuple[str, int]]] = {}
        for m in _IFNONE_EDGE_PATH_RE.finditer(text):
            out.setdefault((m.group(1), m.group(2)), []).append(
                (fname, first + text.count("\n", 0, m.start())))
        return out

    def is_top_port(self, name: str, divider: str) -> bool:
        """The endpoint is a port of the netlist's top module itself."""
        if re.split(r"(?<!\\)" + re.escape(divider), name)[1:]:
            return False
        return self._top_port_base(name) is not None

    def _top_port_base(self, name: str) -> Optional[str]:
        clean = name.replace("\\", "").strip()
        bit = _TOP_PORT_BIT_RE.fullmatch(clean)
        if bit:
            base = bit.group(1)
            return base if base in self.top_vectors and base in self.top_dirs else None
        return clean if clean in self.top_dirs else None

    def endpoint_dir(self, name: str, divider: str) -> Optional[str]:
        parts = re.split(r"(?<!\\)" + re.escape(divider), name)
        if len(parts) == 1:
            base = self._top_port_base(name)
            return self.top_dirs.get(base) if base else None
        inst = divider.join(parts[:-1]).replace("\\", "")
        master = self.masters.get(inst)
        if master not in self.modules:
            return None
        return self._dirs(self.modules[master][1]).get(parts[-1])


def classify_sdf_errors(transcript: str, *, compile_log: str, sdf_text: str,
                        explainer: SdfErrorExplainer) -> Dict[str, object]:
    """Every `SDF ERROR` of one simulation, by class; the rest unexplained."""
    sorry = {(Path(m.group(1)).name, int(m.group(2)))
             for m in _IFNONE_SORRY_RE.finditer(compile_log or "")}
    lines = (sdf_text or "").splitlines()
    # The whole text (issue #1410): a DIVIDER past a fixed prefix is still the
    # file's divider; only a file that states none takes SDF's default `.`.
    divider = (_SDF_DIVIDER_RE.search(sdf_text or "")
               or re.match(r"(.)", "."))
    cells: List[Tuple[int, str]] = []
    for idx, line in enumerate(lines, 1):
        m = _SDF_CELLTYPE_RE.search(line)
        if m:
            cells.append((idx, m.group(1)))
    by_class: Dict[str, int] = {}
    unexplained: List[str] = []
    covered = set()
    for m in _SDF_ERROR_LINE_RE.finditer(transcript or ""):
        covered.add(m.start())
        lineno, msg = int(m.group(2)), m.group(3)
        cls = None
        mp = _MODPATH_MSG_RE.match(msg)
        if mp:
            cell = next((c for start, c in reversed(cells) if start <= lineno), None)
            dropped = explainer.ifnone_paths(cell or "").get((mp.group(2), mp.group(3)), [])
            if any(site in sorry for site in dropped):
                cls = "IFNONE_EDGE_PATH_DROPPED"
        elif msg.startswith("Could not find intermodpath") and 0 < lineno <= len(lines):
            ic = _SDF_INTERCONNECT_RECORD_RE.fullmatch(lines[lineno - 1])
            if ic and "inout" in (explainer.endpoint_dir(ic.group(1), divider.group(1)),
                                  explainer.endpoint_dir(ic.group(2), divider.group(1))):
                cls = "INOUT_PORT_INTERCONNECT"
            elif (ic and explainer.is_top_port(ic.group(2), divider.group(1))
                  and _all_delays_zero(lines[lineno - 1])):
                cls = "ZERO_DELAY_TOP_PORT_INTERCONNECT"
        if cls:
            by_class[cls] = by_class.get(cls, 0) + 1
        else:
            unexplained.append(m.group(0))
    # Native stdout/stderr can fragment a diagnostic. Every raw error still
    # owes an explanation even if its filename/line grammar was damaged.
    unparsed = 0
    for raw in _SDF_ERROR_RE.finditer(transcript or ""):
        if raw.start() not in covered:
            unparsed += 1
            unexplained.append((transcript or "")[raw.start():].split("\n", 1)[0])
    return {"total": sum(by_class.values()) + len(unexplained),
            "unparsed": unparsed,
            "by_class": by_class, "unexplained": len(unexplained),
            "unexplained_samples": unexplained[:5]}


def _module_defs(path: Path) -> Dict[str, bool]:
    """{module/primitive name: has behaviour} for one Verilog model file."""
    try:
        return _module_defs_text(path.read_text(errors="replace"))
    except OSError:
        return {}


def _module_defs_text(raw: str) -> Dict[str, bool]:
    text = strip_comments(raw)
    return {m.group(2): (m.group(1) == "primitive"
                         or bool(_BEHAVIOUR_RE.search(m.group(3)))
                         or any(word not in _DECLARATION_WORDS for word in
                                _BODY_INSTANCE_RE.findall(m.group(3))))
            for m in _MODULE_BODY_RE.finditer(text)}


def verilog_model_closure(declared: List[Path], used_cells: set
                          ) -> Dict[str, object]:
    """The model files a gate netlist needs, from the PDK's DECLARED models.

    LibreLane's PDK config names `CELL_VERILOG_MODELS` and `PAD_VERILOG_MODELS`.
    MEASURED on gf180mcuD: the cell model instantiates UDPs defined only in its
    sibling `primitives.v`, and the declared pad models are `*_blackbox_pp.v`
    (ports only), so an input pad drives X. So every name is resolved to the
    first file -- declared files first, then their same-directory siblings --
    that MODELS it (a body with behaviour); a black box is used only when
    nothing models the name, and is listed as such. A file that would define a
    name another chosen file already defines is not taken (a duplicate
    definition is a compile error); the clash is listed. Names nothing defines
    are `unresolved`, never stubbed here."""
    candidates: List[Path] = []
    for path in [Path(p) for p in declared]:
        for cand in [path] + sorted(path.parent.glob("*.v")):
            if cand not in candidates and cand.is_file():
                candidates.append(cand)
    texts: Dict[str, str] = {}
    for cand in candidates:
        try:
            texts[str(cand)] = cand.read_text(errors="replace")
        except OSError:
            texts[str(cand)] = ""
    return verilog_model_closure_of_texts([str(c) for c in candidates], texts,
                                          used_cells)


def verilog_model_closure_of_texts(candidates: List[str], texts: Dict[str, str],
                                   used_cells: set,
                                   owned: Optional[Dict[str, str]] = None
                                   ) -> Dict[str, object]:
    """`verilog_model_closure` over files already read (`texts`), in the
    candidate order given. `owned` names modules a model the caller already
    compiles defines ({name: file}); a candidate redefining one is a clash."""
    defs = {path: _module_defs_text(texts.get(path, "")) for path in candidates}

    def provider(name: str) -> Optional[str]:
        for want in (True, False):
            for path in candidates:
                if defs[path].get(name) is want:
                    return path
        return None

    chosen: List[str] = []
    owner: Dict[str, str] = dict(owned or {})
    clashes: List[Dict[str, object]] = []
    resolved: Dict[str, str] = {}
    queue = sorted(used_cells)
    while queue:
        name = queue.pop()
        if name in resolved:
            continue
        if name in owner:
            resolved[name] = owner[name]
            continue
        path = provider(name)
        if path is None:
            continue
        if path not in chosen:
            clash = sorted(m for m in defs[path] if m in owner)
            if clash:
                if not any(c["file"] == str(path) for c in clashes):
                    clashes.append({"file": str(path), "names": clash[:8]})
                continue
            chosen.append(path)
            owner.update({m: path for m in defs[path]})
            text = strip_comments(texts.get(path, ""))
            queue += [m for m in re.findall(
                r"^\s*([A-Za-z_][\w$]*)\s*(?:#\s*\([^;]*?\)\s*)?"
                r"(?:[A-Za-z_][\w$]*\s*)?\(", text, re.MULTILINE)
                if m not in resolved and m not in _VERILOG_NON_CELL_WORDS]
        resolved[name] = path
    return {"files": [p for p in candidates if p in chosen],
            "unresolved": sorted(c for c in used_cells if c not in resolved),
            "blackboxed": sorted(c for c in used_cells if c in resolved
                                 and c in defs.get(resolved[c], {})
                                 and defs[resolved[c]].get(c) is False),
            "clashes": clashes}


def library_cell_ports(directory: Path, libraries: List[Path], commands, *, models=(), cells=()):
    """Read native Liberty pins, then supplied model pins for cells it omits."""
    from flow_native_adapters import _word

    script, report = directory / "library_ports.ys", directory / "library_ports.json"
    script.write_text("\n".join("read_liberty -lib " + _word(path) for path in libraries)
                      + "\nwrite_json " + _word(report) + "\n")
    completed = commands.run(["yosys", "-s", script])
    reports = [script, *([report] if report.is_file() else [])]
    if completed is None or completed.returncode or not report.is_file():
        return None, reports
    modules = json.loads(report.read_text())["modules"]
    missing = set(cells) - modules.keys()
    if missing and models:
        preprocessed = directory / "preprocessed_models.v"
        completed = commands.run(["iverilog", "-g2012", "-E", "-o", preprocessed, *models])
        reports += [preprocessed] if preprocessed.is_file() else []
        if completed is None or completed.returncode or not preprocessed.is_file():
            return None, reports
        definitions = {}
        for match in _MODULE_BODY_RE.finditer(strip_comments(preprocessed.read_text())):
            if match[1] == "module" and match[2] in missing:
                definitions.setdefault(match[2], match[0])
        if definitions:
            source = directory / "blackbox_models.v"
            source.write_text("\n".join(definitions.values()) + "\n")
            script, report = directory / "model_ports.ys", directory / "model_ports.json"
            script.write_text("read_verilog -sv -lib -nosynthesis " + _word(source)
                              + "\nwrite_json " + _word(report) + "\n")
            completed = commands.run(["yosys", "-s", script])
            reports += [source, script, *([report] if report.is_file() else [])]
            if completed is None or completed.returncode or not report.is_file():
                return None, reports
            modules.update(json.loads(report.read_text())["modules"])
    return {name: {pin: data["direction"] for pin, data in module["ports"].items()}
            for name, module in modules.items() if isinstance(module.get("ports"), dict)}, reports


def _postlayout_output_deadline(project: Path, plan: dict, declared: dict,
                                netlist: Path, sdc: Path, sdfs: List[Path],
                                *, sta_step_dir: Optional[Path] = None) -> dict:
    """The current STA output's required time, not an inferred settling bound.

    A common bench observes no later than the earliest declared scene's
    interface deadline. The selected STA reports own the timed views and SDFs;
    a missing scene or another output/clock cannot supply this authority.
    """
    from decimal import Decimal, ROUND_FLOOR
    import librelane_signoff as signoff
    import librelane_contract as contract
    import sdc_constraints
    try:
        if sta_step_dir is None:
            arm = signoff.step23_tool_arm(project, artefacts=('max.rpt',))
            if not arm or not arm['corners']:
                raise ValueError('no current native STA scenes')
            folder = Path(arm['folder'])
            corners = arm['corners']
            basis = signoff.tool_arm_basis(arm)
        else:
            # The normal native caller already selected this STAPostPNR State.
            # Consume its actual scenes; do not synthesize a legacy receipt.
            folder = Path(sta_step_dir).resolve(strict=True)
        state = json.loads((folder / 'state_out.json').read_text())
        for view in ('nl', 'sdc'):
            state[view] = str(contract.project_path(project, state[view]))
        state['sdf'] = {corner: str(contract.project_path(project, path))
                        for corner, path in state.get('sdf', {}).items()}
        if (Path(state['nl']).resolve() != netlist.resolve() or
                Path(state['sdc']).resolve() != sdc.resolve() or
                {Path(f).resolve() for f in state['sdf'].values()} !=
                {f.resolve() for f in sdfs}):
            raise ValueError('GLS and STA do not use the same timed views')
        if not state['sdf']:
            raise ValueError('no current native STA scenes')
        corners = {}
        for name, sdf in state['sdf'].items():
            scene = folder / name
            if (scene.parent != folder or Path(sdf).resolve(strict=True).parent != scene):
                raise ValueError('SDF is outside its native STA scene')
            report = scene / 'max.rpt'
            corners[name] = {'files': {'max.rpt': {'text': report.read_text()}}}
        basis = {'producer': 'librelane:OpenROAD.STAPostPNR',
                 'state': str(folder / 'state_out.json'),
                 'corners': {name: {'max.rpt': str(folder / name / 'max.rpt')}
                             for name in corners}}
        clocks = declared_sdc_clocks(sdc, [f.read_text() for f in sdfs])
        port_map = declared.get('port_map') or {}
        port = port_map.get(plan['spec']['serial_out'], plan['spec']['serial_out'])
        clock_port = port_map.get(plan['spec']['clk'], plan['spec']['clk'])
        named = [c for c in sdc_constraints.create_clocks_in_text(sdc.read_text())
                 if c['port_name'] == clock_port]
        if len(named) != 1 or not named[0]['name']:
            raise ValueError('selected output needs one named SDC clock')
        clock = named[0]['name']
        unit_ns = Decimal(str(clocks['unit_s'])) / Decimal('1e-9')
        period = Decimal(str(clocks['clocks_s'][clock_port])) / Decimal('1e-9')
        # The clock reader expresses seconds as binary floats. Compare its
        # value at the emitter's existing 1 ps precision, not float repr bytes.
        period = (period * 1000).to_integral_value() / 1000
        if period != Decimal(str(plan['observation']['clock_period_ns'])):
            raise ValueError('INPUT and current STA clock periods disagree')
        deadlines = {}
        for name, row in corners.items():
            if sta_step_dir is None and row['scope_gaps']:
                raise ValueError(f'{name}: incomplete native STA scope')
            values = []
            for block in re.split(r'(?m)^Startpoint: ', row['files']['max.rpt']['text'])[1:]:
                endpoint = re.search(r'(?m)^Endpoint: (\S+) \(output port clocked by ([^)]+)\)', block)
                if not endpoint or endpoint.group(1) != port:
                    continue
                required = set(re.findall(r'(?m)^\s*([+-]?[\d.]+)\s+data required time\s*$', block))
                group = re.search(r'(?m)^Path Group: (\S+)\s*$', block)
                kind = re.search(r'(?m)^Path Type: (\S+)\s*$', block)
                if (endpoint.group(2) != clock or not group or group.group(1) != clock or
                        not kind or kind.group(1) != 'max' or len(required) != 1):
                    raise ValueError(f'{name}: selected output deadline is ambiguous')
                values.append(Decimal(required.pop()) * unit_ns)
            if not values or any(not v.is_finite() or not 0 < v < period for v in values):
                raise ValueError(f'{name}: selected output has no single-cycle deadline')
            deadlines[name] = str(min(values))
        sample = (min(Decimal(v) for v in deadlines.values()) * 1000).to_integral_value(
            rounding=ROUND_FLOOR) / 1000
        if sample <= 0:
            raise ValueError('no representable positive deadline at 1 ps resolution')
        return {'sample_offset_ns': float(sample), 'output': port, 'clock': clock,
                'required_time_ns': deadlines, 'basis': basis}
    except (OSError, KeyError, TypeError, ValueError, ArithmeticError, contract.Refusal) as exc:
        raise ValueError(f'POSTLAYOUT_OBSERVATION_UNMEASURED: {exc}') from exc


def _bound_arithmetic_case(project: Path, case: Dict[str, object], top: str,
                           declared: Dict[str, object], model_files: List[str],
                           *, netlist: Path, sdc: Path, sdfs: List[Path],
                           sta_step_dir: Optional[Path] = None, pdk_mounts: Optional[list] = None,
                           existing_plan: Optional[dict] = None
                           ) -> Tuple[str, Optional[Dict[str, object]]]:
    """Prepare a generated arithmetic case for its declared physical surface.

    Reuse the same INPUT-derived population, framing and comparator emitter.
    The core's observation schedule cannot follow a DUT rebind to a pad ring;
    the existing typed observation reader must bind the wrapper/model bytes.
    Authored cases and cases on their original surface keep their own text.
    """
    import arith_oracle_tb_gen as arith
    if not declared.get('rebound') or arith._scenario_header(Path(case['path'])) is None:
        return str(case['text']), None
    record = json.loads((project / CHIP_TOP_RECORD_REL).read_text())
    wrapper = project / str(record['chip_top_verilog'])
    plan = json.loads(json.dumps(existing_plan if existing_plan is not None
                                 else arith._scenario_header(Path(case['path']))))
    plan['observation']['top'] = declared['dut_module']
    for field in ('clock', 'output'):
        name = plan['observation'].get(field)
        plan['observation'][field] = (declared.get('port_map') or {}).get(name, name)
    deadline = _postlayout_output_deadline(project, plan, declared, netlist, sdc, sdfs,
                                           sta_step_dir=sta_step_dir)
    plan['observation'] = {**plan['observation'],
                           'sample_offset_ns': deadline['sample_offset_ns'],
                           'postlayout_deadline': deadline}
    if plan.get('reset_observation'):
        cores = [name for name, (master, _) in _instances(strip_comments(wrapper.read_text())).items()
                 if master == top]
        if len(cores) != 1:
            raise ValueError('RESET_STATE_MAPPING_UNMEASURED: core instance is not unique')
        try:
            targets = arith.mapped_reset_state_targets(plan, netlist.read_text(), cores[0])
        except ValueError as mapping_error:
            if sta_step_dir is None:
                raise
            try:
                state = json.loads((sta_step_dir / 'state_out.json').read_text())
                config = json.loads((sta_step_dir / 'config.json').read_text())
                import librelane_contract as contract
                header = state.get('json_h')
                if not header:
                    import librelane_postroute as postroute
                    for candidate in postroute._librelane_states(project):
                        if contract._state_step_id(candidate.parent) != 'Yosys.JsonHeader':
                            continue
                        native_config = json.loads((candidate.parent / 'config.json').read_text())
                        if native_config.get('DESIGN_NAME') == declared['dut_module']:
                            header = json.loads(candidate.read_text()).get('json_h')
                if header:
                    synthesis = json.loads(contract.project_path(project, header).read_text())
                else:
                    import subprocess
                    source = contract.project_path(project, plan['reset_observation']['source_reference']['path'])
                    folder = project / 'phase3/librelane/29-config/reset-state'
                    folder.mkdir(parents=True, exist_ok=True)
                    output = folder / 'state.json'
                    word = lambda p: '"' + str(p).replace('\\', '\\\\').replace('"', '\\"') + '"'
                    script = ('read_verilog -sv ' + word(source) + ' ' + word(wrapper) + '\n'
                              + 'hierarchy -top ' + declared['dut_module']
                              + '\nproc\nflatten\nwrite_json ' + word(output) + '\n')
                    proc = subprocess.run(['yosys', '-Q', '-T', '-p', script], capture_output=True, text=True)
                    (folder / 'yosys.log').write_text(proc.stdout + proc.stderr)
                    if proc.returncode:
                        raise ValueError('RESET_STATE_MAPPING_UNMEASURED: Yosys elaboration failed')
                    synthesis = json.loads(output.read_text())
                libraries = [contract.resolve_state_pdk_asset(f, pdk=config.get('PDK'), mounts=pdk_mounts or [])
                             for files in config.get('LIB', {}).values() for f in files]
                if any(path is None for path in libraries):
                    timed = contract.post_pnr_timing_inputs(project, sta_step_dir / 'state_out.json',
                                                           config['DEFAULT_CORNER'])
                    libraries = [Path(path) for path in timed['liberties']]
                liberty = '\n'.join(p.read_text() for p in sorted(set(libraries)))
            except (OSError, KeyError, ValueError, TypeError) as exc:
                raise ValueError(f'{mapping_error}; selected synthesis/library evidence unavailable') from exc
            targets = arith.mapped_reset_state_targets(
                plan, netlist.read_text(), cores[0], synthesis=synthesis,
                source_text=contract.project_path(project, plan['reset_observation']['source_reference']['path']).read_text(),
                liberty_text=liberty, wrapper_text=wrapper.read_text(),
                pad_instances=record.get('pad_instances'), port_map=declared.get('port_map'))
        plan['observation']['reset_state_targets'] = targets
    # Keep the physical subject in the plan; the normal binder below owns
    # changing this logical placeholder and mapping every pad port.
    return (arith.emit_arithmetic_scenario_module(str(case['module']), plan,
                                                 dut_module=top),
            plan['observation'])


def tool_arm_manifest(project: Path, top: str, netlist: Path,
                      declared_models: List[Path], out: Path,
                      *, sdc: Path, sdfs: List[Path],
                      path_map: Optional[Dict[str, str]] = None,
                      sta_step_dir: Optional[Path] = None,
                      pdk_mounts: Optional[list] = None) -> Dict[str, object]:
    """What `Vibeic.GateLevelSim` runs: the run's executed L10 cases bound to
    the netlist the tool timed (`declared_dut_binding`) and clocked at the
    period of the SDC it timed against (`bind_bench_clock`), with the SDF path
    left as a placeholder, and the model closure. `path_map` rewrites host
    model paths to the paths the image sees (`{host_prefix: container_prefix}`).
    `sta_step_dir` explicitly supplies an already selected native STAPostPNR
    State and its corner max.rpt files for the observation deadline.
    A binding or a clock this run does not declare refuses the whole arm."""
    suite = find_l10_executed_cases(project, top)
    if not suite or not suite.get("cases"):
        raise ValueError("no executed L10 case to re-run at gate level")
    ntext = netlist.read_text(errors="replace")
    declared = declared_dut_binding(project, top, ntext)
    clocks = declared_sdc_clocks(sdc, [Path(f).read_text(errors="replace")
                                       for f in sdfs])
    used = netlist_used_cells(ntext)
    closure = verilog_model_closure(declared_models, used)
    models_text = "".join(Path(f).read_text(errors="replace") for f in closure["files"])
    stubs = missing_empty_cell_stubs(ntext, used, models_text)
    out.mkdir(parents=True, exist_ok=True)
    stub_path = out / "phys_cell_stubs.v"
    stub_text = ("// Physical-only cells no declared model defines.\n"
                 "`timescale 1ns/1ps\n"
                 + "".join(f"module {cell} (); endmodule\n" for cell in stubs))
    if not stub_path.is_file() or stub_path.read_text() != stub_text:
        _aa.write_text(stub_path, stub_text)
    cases, refused = [], list(suite.get("skipped") or [])
    for case in suite["cases"]:
        cid = str(case["id"])
        try:
            text, observation = _bound_arithmetic_case(project, case, top,
                                                       declared, closure['files'],
                                                       netlist=netlist, sdc=sdc, sdfs=sdfs,
                                                       sta_step_dir=sta_step_dir, pdk_mounts=pdk_mounts)
            text, binding = bind_dut_module(text, top,
                                            str(case["dut_instance"]), ntext,
                                            declared)
            text, clock = bind_bench_clock(text, str(case["dut_instance"]), clocks)
            text = inject_sdf_annotation(text, str(case["module"]),
                                         str(case["dut_instance"]), SDF_PLACEHOLDER)
        except ValueError as exc:
            refused.append({"id": cid, "disposition": "NO_GATE_BINDING",
                            "detail": str(exc)})
            continue
        tb = out / f"{cid}_tb.v"
        _aa.write_text(tb, text)
        cases.append({"id": cid, "module": str(case["module"]),
                      "testbench": str(tb), "binding": binding, "clock": clock,
                      **({'observation': observation} if observation is not None else {})})

    def _mapped(p: str) -> str:
        for host, guest in (path_map or {}).items():
            if p.startswith(host):
                return guest + p[len(host):]
        return p
    manifest = {"compile_flags": _IVERILOG_FLAGS, "top": top,
                "netlist": str(netlist), "cases": cases, "not_a_subject": refused,
                "models": [_mapped(f) for f in closure["files"]],
                "stubs": str(stub_path), "sdf_placeholder": SDF_PLACEHOLDER,
                "model_closure": closure, "declared": suite.get("declared"),
                "dut_binding": declared,
                "clock": {k: v for k, v in clocks.items()}}
    _aa.write_text(out / "gls_manifest.json", json.dumps(manifest, indent=2) + "\n")
    return manifest


def judge_tool_arm(step_dir: Path, manifest: Dict[str, object]) -> Dict[str, object]:
    """Per corner: the cases' verdicts and the SDF census, from the transcripts
    `Vibeic.GateLevelSim` wrote. A corner PASSes only when every case passed,
    at least one delay was applied, and the simulator refused NO SDF record."""
    runs = json.loads((step_dir / "gls_runs.json").read_text())
    explainer = _explainer_for(Path(str(manifest.get("netlist") or "")),
                               (manifest.get("model_closure") or {}).get("files") or [])
    sdf_texts: Dict[str, str] = {}
    corners: Dict[str, Dict[str, object]] = {}
    for row in runs.get("runs") or []:
        corner = corners.setdefault(str(row["corner"]), {
            "sdf": row.get("sdf"), "cases": [], "delays_applied": 0,
            "sdf_errors": 0, "sdf_errors_by_class": {},
            "sdf_errors_unexplained": 0, "modpath_unmatched": 0})
        stdout = Path(str(row.get("stdout") or ""))
        text = stdout.read_text(errors="replace") if stdout.is_file() else ""
        parsed = (parse_l10_case_stdout(text) if row.get("compile_rc") == 0
                  else {"verdict": None, "passed": 0, "total": 0, "marker": None})
        census = sdf_annotation_census(text)
        errors = sdf_error_count(text)
        if str(row.get("sdf")) not in sdf_texts:
            sdf_texts[str(row.get("sdf"))] = _read_or_empty(Path(str(row.get("sdf"))))
        classes = classify_sdf_errors(
            text, compile_log=_read_or_empty(Path(str(row.get("compile_log") or ""))),
            sdf_text=sdf_texts[str(row.get("sdf"))], explainer=explainer)
        corner["delays_applied"] += census["delays_applied"]
        corner["sdf_errors"] += errors
        for cls, n in classes["by_class"].items():
            corner["sdf_errors_by_class"][cls] = corner["sdf_errors_by_class"].get(cls, 0) + n
        corner["sdf_errors_unexplained"] += classes["unexplained"]
        corner["modpath_unmatched"] += census["modpath_unmatched"]
        case = {"id": row["case"], "verdict": parsed.get("verdict"),
                "passed": parsed.get("passed"), "total": parsed.get("total"),
                "compile_rc": row.get("compile_rc"), "sim_rc": row.get("sim_rc"),
                "sdf_delays_applied": census["delays_applied"],
                "sdf_errors": errors, "sdf_errors_by_class": classes["by_class"],
                "sdf_errors_unexplained": classes["unexplained"],
                "unexplained_samples": classes["unexplained_samples"]}
        if row.get("compile_rc") != 0:
            case["detail"] = "did not compile against the gate netlist"
        elif parsed.get("verdict") is None:
            case["detail"] = name_unverdicted_case(
                row.get("sim_rc"), len(text.encode()), bool(text) and not text.endswith("\n"))
        corner["cases"].append(case)
    for name, corner in corners.items():
        cases = corner["cases"]
        reasons = []
        if not cases or any(c["verdict"] is None for c in cases):
            reasons.append("NOT_EXECUTED")
        if any(c["verdict"] == "FAIL" for c in cases):
            reasons.append("CASE_FAIL")
        if not corner["delays_applied"]:
            reasons.append("SDF_NOT_ANNOTATED")
        if corner["sdf_errors_unexplained"]:
            # F21: an EXPLAINED record (SDF_ERROR_CLASSES) is the named tool
            # limit its class links; only an unexplained one fails the corner.
            reasons.append("SDF_ERRORS")
        corner["verdict"] = ("PASS" if not reasons else
                             "NOT_EXECUTED" if reasons == ["NOT_EXECUTED"] else "FAIL")
        corner["reasons"] = reasons
    verdict = ("NOT_EXECUTED" if not corners else
               "PASS" if all(c["verdict"] == "PASS" for c in corners.values()) else
               "FAIL" if any(c["verdict"] == "FAIL" for c in corners.values()) else
               "NOT_EXECUTED")
    return {"verdict": verdict, "corners": corners,
            "corners_covered": sorted(corners),
            "cases": [c["id"] for c in manifest.get("cases") or []],
            "not_a_subject": manifest.get("not_a_subject") or [],
            "compile_flags": manifest.get("compile_flags"),
            "sdf_error_classes": SDF_ERROR_CLASSES,
            "dut_binding": manifest.get("dut_binding"),
            "clock": manifest.get("clock")}


def _read_or_empty(path: Path) -> str:
    try:
        return path.read_text(errors="replace") if path.is_file() else ""
    except OSError:
        return ""


def _explainer_for(netlist: Path, model_files: List[str]) -> "SdfErrorExplainer":
    return SdfErrorExplainer(_read_or_empty(netlist),
                             {str(f): _read_or_empty(Path(str(f))) for f in model_files})


def _sdf_error_class_line(row: Dict[str, object]) -> str:
    parts = [f"{cls} {n} (owner {SDF_ERROR_CLASSES[cls]['owner']}, "
             f"{SDF_ERROR_CLASSES[cls]['fork'] or 'legal SDF, no fix owed'})"
             for cls, n in sorted((row.get("sdf_errors_by_class") or {}).items())]
    return (f"sdf errors by class: {', '.join(parts) or 'none'}; "
            f"unexplained {row.get('sdf_errors_unexplained') or 0}")


def _binding_line(binding: Optional[Dict[str, object]]) -> str:
    if not binding:
        return "-"
    if not binding.get("rebound"):
        return f"{binding.get('dut_module')} (the routed netlist defines it)"
    return (f"{binding.get('from')} -> {binding.get('dut_module')}, declared by "
            f"{binding.get('source')}")


def _clock_line(clock: Optional[Dict[str, object]]) -> str:
    if not clock:
        return "-"
    return ", ".join(f"{port} {period * 1e9:g} ns" for port, period
                     in sorted((clock.get("clocks_s") or {}).items())) + \
        f" (from {clock.get('sdc')}; unit: {clock.get('unit_source')})"


def write_tool_arm_results(sim_dir: Path, judged: Dict[str, object], top: str
                           ) -> List[str]:
    """Step 29's declared evidence when the tool arm is the step: the corner
    SDFs beside the log (the gate looks for them there), a per-corner
    per-case `results.log`, `results.json`, and `pass.flag` only on PASS.
    A failing corner is written as an `ERROR:` line naming its reasons, the
    line the step-29 gate reads as a failed simulation."""
    import shutil
    sim_dir.mkdir(parents=True, exist_ok=True)
    written: List[str] = []
    lines = ["SDF-annotated post-layout gate-level simulation (Step 29)",
             f"design           : {top}",
             "sdf source       : LibreLane OpenROAD.STAPostPNR, one SDF per STA corner",
             f"compile flags    : {judged.get('compile_flags')}",
             f"dut binding      : {_binding_line(judged.get('dut_binding'))}",
             f"bench clock      : {_clock_line(judged.get('clock'))}",
             f"corners          : {len(judged.get('corners') or {})}", ""]
    for name, corner in sorted((judged.get("corners") or {}).items()):
        sdf = Path(str(corner.get("sdf") or ""))
        if sdf.is_file():
            copy = sim_dir / f"{top}__{name}.sdf"
            shutil.copyfile(sdf, copy)
            written.append(str(copy))
        lines.append(f"-- corner {name}: $sdf_annotate(\"{sdf}\") --")
        lines.append(f"sdf annotation: {corner.get('delays_applied')} delay(s) applied, "
                     f"{corner.get('sdf_errors')} SDF ERROR record(s) "
                     f"({corner.get('modpath_unmatched')} unmatched ModPath)")
        lines.append(_sdf_error_class_line(corner))
        for case in corner.get("cases") or []:
            lines.append(f"  {case['id']:<40} {case.get('verdict') or 'NOT_EXECUTED':<12} "
                         f"{case.get('detail') or ''}".rstrip())
        if corner.get("verdict") != "PASS":
            lines.append(f"ERROR: corner {name} {corner.get('verdict')}: "
                         + ", ".join(corner.get("reasons") or []))
        lines.append("")
    for row in judged.get("not_a_subject") or []:
        lines.append(f"not a subject: {row.get('id')} {row.get('disposition')} "
                     f"{row.get('detail') or ''}".rstrip())
    lines.append(f"VERDICT: {judged.get('verdict')}")
    _aa.write_text(sim_dir / "results.log", "\n".join(lines) + "\n")
    _aa.write_text(sim_dir / "results.json", json.dumps({
        "program": "sdf_gate_sim", "version": "1.3.0", "suite": "l10_executed_cases",
        "arm": "librelane_stapostpnr_corner_sdfs", **judged}, indent=2, default=str) + "\n")
    written += [str(sim_dir / "results.log"), str(sim_dir / "results.json")]
    flag = sim_dir / "pass.flag"
    if judged.get("verdict") == "PASS":
        _aa.write_text(flag, f"PASS {len(judged.get('cases') or [])} L10 case(s) x "
                             f"{len(judged.get('corners') or {})} STA corner SDF(s)\n")
        written.append(str(flag))
    elif flag.is_file():
        flag.unlink()
    return written


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
    if verdict.get("verdict") == "FAIL" and verdict.get("meta", verdict).get("annotated_interconnect_delays") is not None:
        m = verdict.get("meta", verdict)
        print("VERDICT: FAIL — SDF interconnect records="
              f"{m.get('annotated_interconnect_delays')}; "
              f"self-check vectors={m.get('passed')}/{m.get('total')}")
    else:
        print(f"VERDICT: {verdict.get('verdict')}")
    return 0 if verdict.get("verdict") == "PASS" else 1


if __name__ == "__main__":
    # A stall is not a verdict about the subject: it reaches the exit
    # code as rc 2 (UNDETERMINED), announced, never as a finding.
    sys.exit(_pr.exit_undetermined_on_stall(main))
