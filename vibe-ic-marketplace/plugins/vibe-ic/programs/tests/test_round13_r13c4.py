"""Round-13 R13C4 regression — iface_conformance_v2 unpacked-array internal reg.

CLUSTER R13C4: `iface_conformance_v2.py --strict` emitted block-eligible
MISSING-PORT (rc=1) for `effective_priority` and `wait_counters`, which the
prompt's OWN given-code skeleton declares as INTERNAL unpacked-array regs
(`reg [3:0] wait_counters [0:9];`, `reg [4:0] effective_priority [0:9];`) and
which appear ONLY in a "Register Summary Table" (source=table, no Direction
column) — never in the port table. The author's RTL correctly keeps them
internal, yet the gate hard-blocked it.

ROOT CAUSE: `given_code_internal_names()`'s `_GIVEN_INTERNAL_RE` required the
`;`/`=` terminator to IMMEDIATELY follow the declared name, so an unpacked-array
decl (` [0:9]` between the name and `;`) was never harvested. Those names were
therefore absent from `given_internal`, the never-mask guard did not suppress
them, and their STRUCTURAL "table" source made them block-eligible → rc=1.

FIX: `_GIVEN_INTERNAL_RE` tolerates zero-or-more trailing unpacked dimensions
before the terminator, so a skeleton-declared unpacked-array internal reg is
harvested and the never-mask guard suppresses the spurious MISSING-PORT.

This test asserts:
  (a) POSITIVE — a direction-less "Register Summary Table" name the skeleton
      declares as an unpacked-array internal reg, and which the RTL keeps
      internal, NO LONGER hard-blocks under --strict (rc 0).
  (b) §4.05 NO-LEAK — a genuine table-declared PORT (carrying a Direction) the
      RTL OMITS still hard-blocks under --strict (rc 1), EVEN when the skeleton
      also declares a like-named unpacked-array reg: a direction-ful table entry
      is never masked by the internal-net exclusion.

Self-contained: inline fixtures; resolves the repo programs/ dir via
Path(__file__).resolve().parent.parent so it runs in CI.
"""
import subprocess
import sys
from pathlib import Path

import pytest

import os
_DEFAULT_PROGRAMS = Path(__file__).resolve().parent.parent
PROGRAMS = Path(os.environ.get("VIBE_PROGRAMS", _DEFAULT_PROGRAMS))
GATE = PROGRAMS / "iface_conformance_v2.py"


# ── inline fixtures ──────────────────────────────────────────────────────────
# POSITIVE: the R13C4 shape — a Register Summary Table (no Direction column)
# naming two regs the skeleton declares as INTERNAL unpacked-array regs; the
# author's RTL correctly keeps them internal. Must be CONFORMANT.
_POS_PROMPT = """# Priority-Based Interrupt Controller

### Interrupt Controller Ports

| Port Name | Direction | Width | Description |
|-----------|-----------|-------|-------------|
| `clk` | Input | 1 bit | Clock signal. |
| `rst_n` | Input | 1 bit | Active-low reset. |
| `interrupt_id` | Output | 4 bits | Index of the interrupt being serviced. |

### Register Summary Table

| Register Name | Functionality |
|---------------|---------------|
| `pending_interrupts` | Holds the currently pending interrupts. |
| `wait_counters` | Tracks the wait time for each interrupt. |
| `effective_priority` | Computed priority for each interrupt. |

```verilog
module interrupt_controller (
    input  wire       clk,
    input  wire       rst_n,
    output reg  [3:0] interrupt_id
);
    reg [9:0] pending_interrupts;
    reg [3:0] wait_counters [0:9];
    reg [4:0] effective_priority [0:9];
    // Insert the logic here
endmodule
```
"""

_POS_RTL = """module interrupt_controller (
    input  wire       clk,
    input  wire       rst_n,
    output reg  [3:0] interrupt_id
);
    reg [9:0] pending_interrupts;
    reg [3:0] wait_counters [0:9];
    reg [4:0] effective_priority [0:9];
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) interrupt_id <= 4'b0;
        else        interrupt_id <= wait_counters[0] + effective_priority[0][3:0];
    end
endmodule
"""

# §4.05 NEGATIVE: a genuine table-declared PORT (`status_array`, carrying a
# Direction = Output) the RTL OMITS. The skeleton ALSO declares a like-named
# unpacked-array reg — but a direction-ful table entry is never masked by the
# internal-net exclusion, so this MUST still hard-block.
_NEG_PROMPT = """# Widget

### Ports

| Port Name | Direction | Width | Description |
|-----------|-----------|-------|-------------|
| `clk` | Input | 1 bit | Clock. |
| `status_array` | Output | 4 bits | A real OUTPUT port the RTL omits. |

```verilog
module widget (
    input wire clk
);
    reg [3:0] status_array [0:9];
endmodule
```
"""

_NEG_RTL = """module widget (
    input wire clk
);
    reg [3:0] status_array [0:9];
endmodule
"""


def _run_gate(tmp_path, prompt, rtl, rid):
    pp = tmp_path / "prompt.md"
    rp = tmp_path / "design.sv"
    pp.write_text(prompt)
    rp.write_text(rtl)
    return subprocess.run(
        [sys.executable, str(GATE), "--id", rid,
         "--prompt", str(pp), "--rtl", str(rp), "--strict"],
        capture_output=True, text=True)


def test_gate_exists():
    assert GATE.is_file(), f"gate not found at {GATE}"


def test_positive_unpacked_internal_reg_not_a_missing_port(tmp_path):
    """R13C4 POSITIVE — a Register-Summary-Table name the skeleton declares as
    an unpacked-array INTERNAL reg, kept internal by the RTL, no longer
    hard-blocks under --strict."""
    r = _run_gate(tmp_path, _POS_PROMPT, _POS_RTL,
                  "cvdp_copilot_interrupt_controller_0017")
    assert r.returncode == 0, (
        "expected conformant rc=0, got "
        f"rc={r.returncode}\nstdout={r.stdout}\nstderr={r.stderr}")
    # the two unpacked-array regs must NOT be charged as MISSING-PORT
    assert "effective_priority" not in r.stdout
    assert "wait_counters" not in r.stdout


def test_no_leak_real_table_port_still_hard_blocks(tmp_path):
    """§4.05 NO-LEAK — a genuine table-declared PORT (with a Direction) the RTL
    omits still hard-blocks, even when the skeleton declares a like-named
    unpacked-array reg (a direction-ful table entry is never masked)."""
    r = _run_gate(tmp_path, _NEG_PROMPT, _NEG_RTL, "cvdp_copilot_widget_0001")
    assert r.returncode == 1, (
        "expected §4.05 hard-block rc=1, got "
        f"rc={r.returncode}\nstdout={r.stdout}\nstderr={r.stderr}")
    assert "MISSING-PORT" in r.stdout
    assert "status_array" in r.stdout


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
