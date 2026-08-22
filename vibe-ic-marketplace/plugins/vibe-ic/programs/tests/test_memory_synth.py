"""test_memory_synth.py — the CVDP parameterized-MEMORY deterministic solver
(synchronous FIFO / LIFO-stack / RAM / ROM / register-file).

memory_synth.solve(record) reads the module name from input.prompt/context (via
the bridge; never the OFF-LIMITS harness .env TOPLEVEL), reads the interface from
the PROMPT's own `### Input/Output Ports` markdown list (never the golden RTL),
PARSES the depth + width (+ read protocol / stated ROM contents / #read-#write
ports), and emits deterministic RTL named per the stated name — else SKIP (None)
on ANY unstated governing fact, async-CDC FIFO, composite or extra-feature design.

POSITIVES (each SOLVES + is FUNCTIONALLY correct against a directed iverilog TB that
exercises the STATED protocol — write a sequence, read it back, check full/empty;
host-verified when the iverilog binary is present):
  * a single-clock circular-buffer SYNC FIFO (wr/rd pointers, full/empty);
  * a synchronous LIFO/stack (push/pop, full/empty) — the real CVDP filo_0005 +
    sync_lifo_0001 records when the dataset is on this host, else faithful twins;
  * a single-port RAM (async combinational read, parsed depth/width);
  * a ROM with a stated contents table;
  * a 2-read/1-write register file (parsed #regs).

§4.05 / NO-CHEAT NEGATIVES (each MUST SKIP -> None):
  * a FIFO whose DEPTH is unstated;
  * an ASYNC / dual-clock / gray-pointer-CDC FIFO (CDC not fully pinned);
  * a memory that is one block inside a composite (AXI/cache/APB) controller;
  * an extra-feature variant (BIST / clock-gating / collision side-output);
  * a "modify the existing RTL" delta task (prior code in input.context);
  * a RAM whose read timing (sync vs async) is unstated.

CHIP-AGNOSTIC: the solver keys only on STRUCTURE words + role-conventional port
names, never on a design name. The SAME spec under different prompt-stated names
solves identically and the emitted module is named per the stated name.

The iverilog functional checks are GATED on the iverilog binary; the structural /
SKIP / agnostic assertions run anywhere. Real-dataset records are used when the CVDP
jsonl is present on this host; otherwise faithful synthetic records stand in.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parents[1]
if str(PROG) not in sys.path:
    sys.path.insert(0, str(PROG))

import memory_synth as S  # noqa: E402
from _hostpaths import corpus_path  # noqa: E402

_IVERILOG = shutil.which("iverilog") and shutil.which("vvp")

_DATASET = corpus_path("_extbench/cvdp_open_v110/"
                       "cvdp_v1.1.0_nonagentic_code_generation_no_commercial.jsonl")


# --------------------------------------------------------------------------- #
# record builder (faithful to CVDP v1.1.0 shape: input.prompt + input.context +
# output.context/response + harness.files src/.env TOPLEVEL).
# --------------------------------------------------------------------------- #
def _rec(top, prompt, *, input_context=None, rtl_path=None):
    # CVDP-COMPLIANT record: the module NAME must be recoverable from input.prompt
    # (the ONLY model-visible surface) WITHOUT the OFF-LIMITS harness — prepend a
    # canonical `module `<top>`` designation whenever `toplevel_name` cannot already
    # recover the name from the prompt+context. The interface already lives in the
    # prompt's own `### Input/Output Ports`. The harness `.env` TOPLEVEL is retained
    # for record-shape fidelity only; the refactored solver never reads it.
    import cvdp_atomic_bridge as _B
    if _B.toplevel_name({"input": {"prompt": prompt,
                                   "context": input_context or {}}}) != top:
        prompt = f"Design the Verilog module `{top}`.\n\n" + prompt
    rtl_path = rtl_path or f"rtl/{top}.sv"
    return {
        "id": f"test_{top}",
        "input": {"prompt": prompt, "context": input_context or {}},
        "output": {"response": "", "context": {rtl_path: ""}},
        "harness": {"files": {
            "src/.env": (
                "SIM             = icarus\n"
                "TOPLEVEL_LANG   = verilog\n"
                f"TOPLEVEL        = {top}\n"),
        }},
    }


def _dataset_record(rid):
    if not _DATASET.exists():
        return None
    for line in _DATASET.read_text().splitlines():
        r = json.loads(line)
        if r.get("id") == rid:
            return r
    return None


def _ensure_named(rec, top):
    """Re-state the module NAME — already present in the real CVDP prompt, but in a
    form the shipped bridge does not parse (e.g. `### Interface of the Module
    `sync_lifo``, `module name `FILO_RTL``, `### Module Name:`) — in a canonical,
    bridge-parseable `module `<top>`` designation, so `toplevel_name` recovers it
    from input.prompt WITHOUT the OFF-LIMITS harness. Purely relocates a
    model-visible fact the prompt already contains; a no-op when the name is already
    recoverable or when rec is None (dataset absent -> synthetic twin used)."""
    if rec is None:
        return None
    import cvdp_atomic_bridge as _B
    if _B.toplevel_name(rec) != top:
        rec = json.loads(json.dumps(rec))
        rec["input"]["prompt"] = (
            f"Design the Verilog module `{top}`.\n\n"
            + (rec.get("input") or {}).get("prompt", ""))
    return rec


def _run_iverilog(rtl, tb, name):
    if not _IVERILOG:
        pytest.skip("iverilog/vvp not installed")
    with tempfile.TemporaryDirectory() as d:
        rp, tp, vp = (Path(d) / f"{name}.sv", Path(d) / f"{name}_tb.sv",
                      Path(d) / f"{name}.vvp")
        rp.write_text(rtl)
        tp.write_text(tb)
        c = subprocess.run(["iverilog", "-g2012", "-o", str(vp), str(rp), str(tp)],
                           capture_output=True, text=True)
        assert c.returncode == 0, f"compile failed:\n{c.stderr}"
        r = subprocess.run(["vvp", str(vp)], capture_output=True, text=True)
        return r.stdout


# =========================================================================== #
# fixture prompts (faithful to the CVDP dataset interface-section shape)
# =========================================================================== #
_FIFO_PROMPT = """Design a **synchronous FIFO** (First-In-First-Out) buffer with
configurable depth and data width, operating on a single clock domain.

### Parameters
- `DATA_WIDTH` (default = 8): width of the data bus.
- `DEPTH` (default = 4): number of elements the FIFO can store.

### Input Ports
- `clk` (1 bit): clock. All operations occur on the rising edge.
- `rst` (1 bit): synchronous active-high reset.
- `wr_en` (1 bit): write enable; data written when the FIFO is not full.
- `rd_en` (1 bit): read enable; data read when the FIFO is not empty.
- `data_in` (DATA_WIDTH bits): data to be written.

### Output Ports
- `data_out` (DATA_WIDTH bits): data read from the FIFO.
- `full` (1 bit): high when the FIFO is full.
- `empty` (1 bit): high when the FIFO is empty.
"""

_LIFO_PROMPT = """Design a **synchronous LIFO (Last-In, First-Out)** memory with
configurable data width and depth, operating on a single clock domain.

### Parameters
- `DATA_WIDTH` (default = 8): bit-width of the stored data.
- `DEPTH` (default = 8): number of entries the LIFO can hold.

### Input Ports
- `clock` (1 bit): clock. All operations on the rising edge.
- `reset` (1 bit): synchronous active-high reset.
- `write_en` (1 bit): write enable; pushes data when not full.
- `read_en` (1 bit): read enable; pops data when not empty.
- `data_in` (DATA_WIDTH bits): data to be pushed.

### Output Ports
- `empty` (1 bit): high when the LIFO is empty.
- `full` (1 bit): high when the LIFO is full.
- `data_out` (DATA_WIDTH bits): data popped from the top of the LIFO.
"""

_RAM_PROMPT = """Design a **single-port RAM** (random access memory) with
configurable depth and data width.

### Parameters
- `DATA_WIDTH` (default = 8)
- `DEPTH` (default = 16)

### Input Ports
- `clk` (1 bit): clock.
- `we` (1 bit): write enable.
- `addr` (4 bits): address.
- `data_in` (DATA_WIDTH bits): write data.

### Output Ports
- `data_out` (DATA_WIDTH bits): read data.

Read is asynchronous (combinational): data_out reflects mem[addr] immediately.
Write occurs on the rising clock edge when we is high.
"""

_ROM_PROMPT = """Design a **ROM** (read-only memory) with a 2-bit address and an
8-bit data output.

### Input Ports
- `addr` (2 bits): address.

### Output Ports
- `data_out` (8 bits): the data at the addressed location.

The ROM contents are: mem[0] = 8'hA1, mem[1] = 8'hB2, mem[2] = 8'hC3,
mem[3] = 8'hD4. The read is combinational.
"""

_RF_PROMPT = """Design a **register file** with 8 registers, 2 read ports and 1
write port.

### Parameters
- `DATA_WIDTH` (default = 8)
- `DEPTH` (default = 8): number of registers.

### Input Ports
- `clk` (1 bit): clock.
- `rst` (1 bit): active-high synchronous reset.
- `wen` (1 bit): write enable.
- `waddr` (3 bits): write address.
- `wdata` (DATA_WIDTH bits): write data.
- `raddr1` (3 bits): read address 1.
- `raddr2` (3 bits): read address 2.

### Output Ports
- `rdata1` (DATA_WIDTH bits): read data 1.
- `rdata2` (DATA_WIDTH bits): read data 2.

Write on the rising edge when wen. Reads are combinational.
"""


# =========================================================================== #
# POSITIVE — synchronous FIFO (circular buffer, full/empty)
# =========================================================================== #
def test_fifo_solves_and_named_per_toplevel():
    rec = _rec("my_fifo", _FIFO_PROMPT)
    rtl = S.solve(rec)
    assert rtl is not None
    assert "module my_fifo" in rtl
    assert S.family_of(rec) == "sync_fifo"
    # circular-buffer structure: separate wr/rd pointers + occupancy count.
    assert "wr_ptr" in rtl and "rd_ptr" in rtl and "count" in rtl


def test_fifo_functionally_correct():
    rtl = S.solve(_rec("my_fifo", _FIFO_PROMPT))
    tb = """
module tb; reg clk=0,rst,wr_en,rd_en; reg [7:0] data_in; wire [7:0] data_out;
 wire full,empty; integer i,errors=0; reg [7:0] v[0:3];
 my_fifo dut(.clk(clk),.rst(rst),.wr_en(wr_en),.rd_en(rd_en),.data_in(data_in),
   .data_out(data_out),.full(full),.empty(empty));
 always #5 clk=~clk;
 initial begin rst=1;wr_en=0;rd_en=0;data_in=0; @(posedge clk);#1;
  if(empty!==1)begin errors=errors+1;$display("FAIL empty-rst");end
  @(negedge clk);rst=0;
  for(i=0;i<4;i=i+1)begin v[i]=8'h20+i; @(negedge clk);wr_en=1;rd_en=0;data_in=v[i];@(posedge clk);end
  @(negedge clk);wr_en=0;#1;
  if(full!==1)begin errors=errors+1;$display("FAIL not-full");end
  for(i=0;i<4;i=i+1)begin @(negedge clk);rd_en=1;wr_en=0;@(posedge clk);@(negedge clk);rd_en=0;#1;
    if(data_out!==v[i])begin errors=errors+1;$display("FAIL rd[%0d] exp=%h got=%h",i,v[i],data_out);end end
  #1; if(empty!==1)begin errors=errors+1;$display("FAIL not-empty");end
  if(errors==0)$display("ALL_PASS");else $display("ERRORS %0d",errors); $finish; end
endmodule
"""
    out = _run_iverilog(rtl, tb, "fifo")
    assert "ALL_PASS" in out, out


# =========================================================================== #
# POSITIVE — synchronous LIFO/stack (real CVDP records when present)
# =========================================================================== #
def test_lifo_solves_and_named_per_toplevel():
    rec = _ensure_named(_dataset_record("cvdp_copilot_sync_lifo_0001"), "sync_lifo") or \
        _rec("sync_lifo", _LIFO_PROMPT)
    rtl = S.solve(rec)
    assert rtl is not None
    top = S._toplevel(rec)
    assert f"module {top}" in rtl
    assert S.family_of(rec) == "lifo_stack"
    assert "mem" in rtl and "sp" in rtl  # stack array + stack pointer


def _lifo_func_tb(top, depth, clk, rst, push, pop):
    """Directed LIFO TB: push DEPTH distinct values, pop them, expect LIFO order;
    full after DEPTH pushes, empty after DEPTH pops. The pop read is registered
    (data_out valid one cycle after asserting pop)."""
    return f"""
module tb;
  reg {clk}=0, {rst}, {push}, {pop}; reg [7:0] data_in;
  wire [7:0] data_out; wire full, empty; integer i, errors=0;
  reg [7:0] vals [0:{depth-1}];
  {top} dut(.{clk}({clk}),.{rst}({rst}),.{push}({push}),.{pop}({pop}),
    .data_in(data_in),.data_out(data_out),.full(full),.empty(empty));
  always #5 {clk}=~{clk};
  initial begin
    {rst}=1; {push}=0; {pop}=0; data_in=0;
    @(posedge {clk}); @(posedge {clk}); #1;
    if (empty!==1'b1) begin errors=errors+1; $display("FAIL empty-after-reset"); end
    if (full!==1'b0) begin errors=errors+1; $display("FAIL full-after-reset"); end
    @(negedge {clk}); {rst}=0;
    for (i=0;i<{depth};i=i+1) begin
      vals[i]=8'h10+i;
      @(negedge {clk}); {push}=1; {pop}=0; data_in=vals[i]; @(posedge {clk});
    end
    @(negedge {clk}); {push}=0; #1;
    if (full!==1'b1) begin errors=errors+1; $display("FAIL not-full"); end
    for (i={depth-1};i>=0;i=i-1) begin
      @(negedge {clk}); {pop}=1; {push}=0; @(posedge {clk});
      @(negedge {clk}); {pop}=0; #1;
      if (data_out!==vals[i]) begin errors=errors+1;
        $display("FAIL pop[%0d] exp=%h got=%h",i,vals[i],data_out); end
    end
    #1; if (empty!==1'b1) begin errors=errors+1; $display("FAIL not-empty"); end
    if (errors==0) $display("ALL_PASS"); else $display("ERRORS %0d",errors);
    $finish;
  end
endmodule
"""


def test_lifo_functionally_correct_sync_lifo():
    rec = _ensure_named(_dataset_record("cvdp_copilot_sync_lifo_0001"), "sync_lifo") or \
        _rec("sync_lifo", _LIFO_PROMPT)
    rtl = S.solve(rec)
    assert rtl is not None
    top = S._toplevel(rec)
    # sync_lifo ports: clock/reset/write_en/read_en, DEPTH = 2^ADDR_WIDTH = 8.
    tb = _lifo_func_tb(top, 8, "clock", "reset", "write_en", "read_en")
    out = _run_iverilog(rtl, tb, "synclifo")
    assert "ALL_PASS" in out, out


def test_lifo_functionally_correct_filo():
    rec = _ensure_named(_dataset_record("cvdp_copilot_filo_0005"), "FILO_RTL")
    if rec is None:
        pytest.skip("filo_0005 dataset record not present on this host")
    rtl = S.solve(rec)
    assert rtl is not None
    # FILO_RTL ports: clk/reset/push/pop, DEPTH = 16.
    tb = _lifo_func_tb("FILO_RTL", 16, "clk", "reset", "push", "pop")
    out = _run_iverilog(rtl, tb, "filo")
    assert "ALL_PASS" in out, out


def _mem_indices(rtl):
    """Every index expression the emit uses to address `mem`, bracket-matched so a
    nested part-select (`mem[sp[AW-1:0]]`) comes back whole. The array DECLARATION
    (`mem [0:DEPTH-1]`) is not an index and is excluded."""
    out, i = [], 0
    while True:
        j = rtl.find("mem[", i)
        if j < 0:
            return out
        k, depth = j + 3, 0
        while k < len(rtl):
            if rtl[k] == "[":
                depth += 1
            elif rtl[k] == "]":
                depth -= 1
                if depth == 0:
                    break
            k += 1
        idx = rtl[j + 4:k].strip()
        if not idx.startswith("0:"):        # the array declaration, not an index
            out.append(idx)
        i = k + 1


def test_lifo_top_of_stack_index_decrements_before_it_truncates():
    """A FULL stack holds `sp == DEPTH == 1<<AW`, whose low AW bits are all ZERO, so
    `mem[sp[AW-1:0] - 1'b1]` reaches the top entry only if that subtraction wraps
    inside AW bits. An array index is a SELF-DETERMINED expression, so how wide it is
    evaluated is the simulator's call: Icarus 11 evaluates it wider, computes -1, and
    the first pop off a full stack reads `mem[-1]` as X (#1415) — Icarus 13/14 wrap
    and pass. Assert the emit subtracts at sp's OWN [AW:0] width and narrows AFTER,
    so the index means one thing on every simulator.

    Runs WITHOUT a simulator deliberately. `test_lifo_functionally_correct_sync_lifo`
    catches the same defect, but it SKIPs wherever iverilog is absent and passes
    wherever iverilog is new enough — between the two, the regression had nowhere it
    was reliably visible, which is how it survived.
    """
    rec = _ensure_named(_dataset_record("cvdp_copilot_sync_lifo_0001"), "sync_lifo") or \
        _rec("sync_lifo", _LIFO_PROMPT)
    rtl = S.solve(rec)
    assert rtl is not None

    # The top-of-stack address is a NARROWING net driven by a decrement of the
    # full-width sp: in an assignment the context width spans the LHS and sp's
    # [AW:0], so `DEPTH-1` is computed before the narrowing, not after.
    m = re.search(r"wire\s*\[\s*AW\s*-\s*1\s*:\s*0\s*\]\s*(\w+)\s*=\s*sp\s*-\s*1(?:'b1)?\s*;",
                  rtl)
    assert m, ("the LIFO emit has no narrowing full-width top-of-stack decrement "
               f"(`wire [AW-1:0] <name> = sp - 1'b1;`):\n{rtl}")
    top_idx = m.group(1)

    # `mem` may be addressed only by the PUSH index — sp itself, and push is gated
    # on !full so sp <= DEPTH-1 and the narrowing is lossless — or by that net.
    # Anything else (notably `sp[AW-1:0] - 1'b1`) truncates before it adjusts.
    idxs = set(_mem_indices(rtl))
    assert idxs <= {"sp[AW-1:0]", top_idx}, (
        f"LIFO addresses mem with {sorted(idxs - {'sp[AW-1:0]', top_idx})}, which "
        f"truncates sp before adjusting it; use `{top_idx}`\n{rtl}")
    assert top_idx in idxs, (
        f"`{top_idx}` is declared but mem is never addressed with it\n{rtl}")


# =========================================================================== #
# POSITIVE — single-port RAM (async combinational read)
# =========================================================================== #
def test_ram_solves_async_read():
    rec = _rec("my_ram", _RAM_PROMPT)
    rtl = S.solve(rec)
    assert rtl is not None
    assert "module my_ram" in rtl
    assert S.family_of(rec) == "ram"
    assert "assign data_out = mem[addr]" in rtl  # combinational read


def test_ram_functionally_correct():
    rtl = S.solve(_rec("my_ram", _RAM_PROMPT))
    tb = """
module tb; reg clk=0,we; reg [3:0] addr; reg [7:0] data_in; wire [7:0] data_out;
 integer i,errors=0;
 my_ram dut(.clk(clk),.we(we),.addr(addr),.data_in(data_in),.data_out(data_out));
 always #5 clk=~clk;
 initial begin we=0;addr=0;data_in=0;
  for(i=0;i<8;i=i+1)begin @(negedge clk);we=1;addr=i;data_in=8'h50+i;@(posedge clk);end
  @(negedge clk);we=0;
  for(i=0;i<8;i=i+1)begin addr=i;#1;
    if(data_out!==(8'h50+i))begin errors=errors+1;$display("FAIL rd[%0d] got=%h",i,data_out);end end
  if(errors==0)$display("ALL_PASS");else $display("ERRORS %0d",errors); $finish; end
endmodule
"""
    out = _run_iverilog(rtl, tb, "ram")
    assert "ALL_PASS" in out, out


# =========================================================================== #
# POSITIVE — ROM (stated contents table)
# =========================================================================== #
def test_rom_solves_with_stated_contents():
    rec = _rec("my_rom", _ROM_PROMPT)
    rtl = S.solve(rec)
    assert rtl is not None
    assert "module my_rom" in rtl
    assert S.family_of(rec) == "rom"
    # the stated contents land in the init, never fabricated.
    for v in ("8'hA1", "8'hB2", "8'hC3", "8'hD4"):
        assert v in rtl


def test_rom_functionally_correct():
    rtl = S.solve(_rec("my_rom", _ROM_PROMPT))
    tb = """
module tb; reg [1:0] addr; wire [7:0] data_out; integer errors=0;
 my_rom dut(.addr(addr),.data_out(data_out));
 reg [7:0] exp[0:3];
 initial begin exp[0]=8'hA1;exp[1]=8'hB2;exp[2]=8'hC3;exp[3]=8'hD4;
  addr=0;#1; if(data_out!==exp[0])errors=errors+1;
  addr=1;#1; if(data_out!==exp[1])errors=errors+1;
  addr=2;#1; if(data_out!==exp[2])errors=errors+1;
  addr=3;#1; if(data_out!==exp[3])errors=errors+1;
  if(errors==0)$display("ALL_PASS");else $display("ERRORS %0d",errors); $finish; end
endmodule
"""
    out = _run_iverilog(rtl, tb, "rom")
    assert "ALL_PASS" in out, out


# =========================================================================== #
# POSITIVE — register file (2-read / 1-write, combinational read)
# =========================================================================== #
def test_regfile_solves():
    rec = _rec("my_rf", _RF_PROMPT)
    rtl = S.solve(rec)
    assert rtl is not None
    assert "module my_rf" in rtl
    assert S.family_of(rec) == "register_file"
    assert "assign rdata1 = rf[raddr1]" in rtl
    assert "assign rdata2 = rf[raddr2]" in rtl


def test_regfile_functionally_correct():
    rtl = S.solve(_rec("my_rf", _RF_PROMPT))
    tb = """
module tb; reg clk=0,rst,wen; reg [2:0] waddr,raddr1,raddr2; reg [7:0] wdata;
 wire [7:0] rdata1,rdata2; integer i,errors=0;
 my_rf dut(.clk(clk),.rst(rst),.wen(wen),.waddr(waddr),.wdata(wdata),
   .raddr1(raddr1),.raddr2(raddr2),.rdata1(rdata1),.rdata2(rdata2));
 always #5 clk=~clk;
 initial begin rst=1;wen=0;waddr=0;wdata=0;raddr1=0;raddr2=0;@(posedge clk);@(negedge clk);rst=0;
  for(i=0;i<8;i=i+1)begin @(negedge clk);wen=1;waddr=i;wdata=8'h70+i;@(posedge clk);end
  @(negedge clk);wen=0;
  for(i=0;i<8;i=i+1)begin raddr1=i;raddr2=7-i;#1;
    if(rdata1!==(8'h70+i))begin errors=errors+1;$display("FAIL rd1[%0d] got=%h",i,rdata1);end
    if(rdata2!==(8'h70+(7-i)))begin errors=errors+1;$display("FAIL rd2[%0d] got=%h",i,rdata2);end end
  if(errors==0)$display("ALL_PASS");else $display("ERRORS %0d",errors); $finish; end
endmodule
"""
    out = _run_iverilog(rtl, tb, "rf")
    assert "ALL_PASS" in out, out


# =========================================================================== #
# §4.05 NEGATIVES — each MUST SKIP (return None)
# =========================================================================== #
def test_skip_fifo_unstated_depth():
    p = """Design a synchronous FIFO.
### Parameters
- `DATA_WIDTH` (default = 8)
### Input Ports
- `clk` (1 bit): clock.
- `rst` (1 bit): reset.
- `wr_en` (1 bit): write enable.
- `rd_en` (1 bit): read enable.
- `data_in` (DATA_WIDTH bits): data.
### Output Ports
- `data_out` (DATA_WIDTH bits): data out.
- `full` (1 bit)
- `empty` (1 bit)
"""
    assert S.solve(_rec("f", p)) is None


def test_skip_async_cdc_fifo():
    p = """Design an asynchronous FIFO with a separate write clock and read clock
for crossing two clock domains.
### Parameters
- `DATA_WIDTH` (default = 8)
- `DEPTH` (default = 8)
### Input Ports
- `w_clk` (1 bit): write clock.
- `r_clk` (1 bit): read clock.
- `w_rst` (1 bit): write reset.
- `r_rst` (1 bit): read reset.
- `w_inc` (1 bit): write enable.
- `r_inc` (1 bit): read enable.
- `w_data` (DATA_WIDTH bits): data.
### Output Ports
- `r_data` (DATA_WIDTH bits): data out.
- `w_full` (1 bit)
- `r_empty` (1 bit)
"""
    assert S.solve(_rec("af", p)) is None


def test_skip_async_filo_dataset_record():
    # the real CVDP async FILO (dual-clock) MUST skip.
    rec = _dataset_record("cvdp_copilot_async_filo_0001")
    if rec is None:
        pytest.skip("async_filo dataset record not present")
    assert S.solve(rec) is None


def test_skip_async_fifo_dataset_record():
    rec = _dataset_record("cvdp_copilot_fifo_async_0001")
    if rec is None:
        pytest.skip("fifo_async dataset record not present")
    assert S.solve(rec) is None


def test_skip_composite_axi_fifo():
    p = """Design an AXI-Stream to FIFO bridge with depth 16 and width 8.
### Input Ports
- `clk` (1 bit)
- `rst` (1 bit)
- `wr_en` (1 bit)
- `rd_en` (1 bit)
- `data_in` (8 bits)
### Output Ports
- `data_out` (8 bits)
- `full` (1 bit)
- `empty` (1 bit)
"""
    assert S.solve(_rec("axi_fifo", p)) is None


def test_skip_extra_feature_bist_regfile():
    p = """Design a register file with 8 registers and a Built-In Self-Test (BIST)
feature for fault detection.
### Parameters
- `DATA_WIDTH` (default = 8)
- `DEPTH` (default = 8)
### Input Ports
- `clk` (1 bit)
- `rst` (1 bit)
- `wen` (1 bit)
- `waddr` (3 bits)
- `wdata` (DATA_WIDTH bits)
- `raddr1` (3 bits)
### Output Ports
- `rdata1` (DATA_WIDTH bits)
"""
    assert S.solve(_rec("rf_bist", p)) is None


def test_skip_ram_unstated_read_timing():
    # neither "synchronous read" nor "asynchronous/combinational read" stated.
    p = """Design a single-port RAM.
### Parameters
- `DATA_WIDTH` (default = 8)
- `DEPTH` (default = 16)
### Input Ports
- `clk` (1 bit)
- `we` (1 bit)
- `addr` (4 bits)
- `data_in` (DATA_WIDTH bits)
### Output Ports
- `data_out` (DATA_WIDTH bits)
"""
    assert S.solve(_rec("ram", p)) is None


def test_skip_rom_unenumerated_contents():
    p = """Design a ROM with a 4-bit address and 8-bit data output. The contents are
defined by the application.
### Input Ports
- `addr` (4 bits)
### Output Ports
- `data_out` (8 bits)
"""
    assert S.solve(_rec("rom", p)) is None


def test_skip_modify_existing_delta_task():
    rec = _rec("my_fifo", _FIFO_PROMPT,
               input_context={"rtl/my_fifo.sv": "module my_fifo(); endmodule"})
    assert S.solve(rec) is None


def test_skip_non_member_design():
    p = """Design a 4-bit ripple-carry adder.
### Input Ports
- `a` (4 bits)
- `b` (4 bits)
### Output Ports
- `sum` (5 bits)
"""
    assert S.solve(_rec("adder", p)) is None


# =========================================================================== #
# NO-LEAK — the solver never reads the golden/reference RTL body
# =========================================================================== #
def test_never_reads_golden_rtl_body():
    rec = _rec("my_fifo", _FIFO_PROMPT)
    rec["output"]["context"]["rtl/my_fifo.sv"] = (
        "module my_fifo; assign data_out = 8'hAB; endmodule")
    rec["output"]["response"] = "module my_fifo; assign full = 1'hC; endmodule"
    rtl = S.solve(rec)
    assert rtl is not None
    assert "8'hAB" not in rtl and "1'hC" not in rtl
    assert "wr_ptr" in rtl  # the real parsed circular buffer, not planted logic


# =========================================================================== #
# CHIP-AGNOSTIC — same prompt, different TOPLEVEL => named per TOPLEVEL
# =========================================================================== #
@pytest.mark.parametrize("top", ["FOO_999", "zztop", "my_block", "WIDGET"])
def test_chip_agnostic_module_named_per_toplevel(top):
    rtl = S.solve(_rec(top, _FIFO_PROMPT))
    assert rtl is not None
    assert f"module {top}" in rtl


def test_chip_agnostic_solves_independent_of_design_name():
    a = S.solve(_rec("alpha", _LIFO_PROMPT))
    b = S.solve(_rec("omega_block", _LIFO_PROMPT))
    assert a and b
    assert a.replace("alpha", "X") == b.replace("omega_block", "X")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
