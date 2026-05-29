---
name: fpga-led-probe-allocation
description: Codify FPGA LED probe allocation patterns (instantaneous / pulse-stretched / sticky / byte-display) and produce an FPGA-top template with comment-table mapping (LED → signal → expected behaviour per test stage). Use when a fresh agent has to verify a chip on a DE10-Lite-class board with no scope and only the on-board LEDs as visibility, and you want to allocate the LEDs systematically rather than guessing.
---

# FPGA LED probe allocation

## When to use

- The host machine has no oscilloscope / SignalTap on the rig.
- The user has a DE10-Lite, DE10-Nano, or similar board with a row of
  LEDs as the only on-board observability.
- A USB webcam (or phone) will be used to capture LED states for
  before/after diff via `device_camera_capture` /
  `device_camera_led_diff` (mcp-eda v0.99+).

## The four probe modes

Picking the right mode for each signal is the difference between an
LED that flashes too fast for a 30 fps webcam to catch and one that
holds long enough for diff-capture but doesn't lie about the system
state.

| Mode | Visible duration | Use when | Pattern |
|------|------------------|----------|---------|
| **instantaneous** | 1 cycle | signal is steady-state (FSM in IDLE, register holds value) | `assign LED[N] = signal;` |
| **pulse-stretched** | ≥ 5 ms | signal is a 1-cycle pulse you want to *see* | `pulse_stretch #(50000) u_st(.clk(clk_50m), .pulse_in(signal), .led_out(LED[N]));` |
| **sticky** | latched until reset / next event | signal is a "did this event ever happen?" flag | `always_ff @(posedge clk_50m) if (rst_n & signal) seen_q <= 1; assign LED[N] = seen_q;` |
| **byte-display** | a multi-LED column showing 8 bits of a byte | byte register snapshot | `assign LED[7:0] = byte_q;` (consumes 8 LEDs) |

## How to allocate

For a 10-LED board (DE10-Lite has LEDR[9:0]):

| LED | Mode | Signal | What it tells you |
|-----|------|--------|-------------------|
| LEDR[9] | sticky | `tx_done_q` | "RTL ever finished a TX packet" |
| LEDR[8] | sticky | `cmd_decoded_q` | "RTL ever decoded a cmd opcode" |
| LEDR[7:0] | byte-display | `last_response_byte` | most recent response byte the device sent |

That layout consumes all 10 LEDs and gives you (a) a "did anything
happen?" signal at LEDR[9:8], (b) the exact byte at LEDR[7:0]. For a
host-driven test you can sequence:

  1. Hold reset, capture (everything LOW = baseline).
  2. Release reset, send cmd 0x70.
  3. Capture again; LEDR[9:8] tell you the FSM at least executed a TX
     and decoded a cmd; LEDR[7:0] should show the response byte.

## Top-template (DE10-Lite)

The FPGA top should explicitly comment the LED table so a reviewer
glancing at any photo of the board can decode the state.

```verilog
//-----------------------------------------------------------------
// LED PROBE TABLE  (kept in sync with host capture script)
//
// LEDR[9]    sticky      tx_done_q          packet TX completed at least once
// LEDR[8]    sticky      cmd_decoded_q      RTL ever decoded a CMD
// LEDR[7:0]  byte-disp   last_response_byte most recent response byte
//-----------------------------------------------------------------
module fpga_top(
    input  CLK_50M,
    input  KEY_n_reset,
    inout  ID_BUS_PIN,
    output [9:0] LEDR
);
    // ... 2-FF synchronisers (see fpga_async_input_synchronizer_check) ...
    // ... DUT instantiation ...
    wire tx_done_pulse, cmd_decoded_pulse;
    wire [7:0] last_response_byte;

    reg tx_done_q, cmd_decoded_q;
    always @(posedge CLK_50M or negedge KEY_n_reset) begin
        if (!KEY_n_reset) {tx_done_q, cmd_decoded_q} <= 2'b00;
        else begin
            if (tx_done_pulse)     tx_done_q     <= 1'b1;
            if (cmd_decoded_pulse) cmd_decoded_q <= 1'b1;
        end
    end

    assign LEDR[9]   = tx_done_q;
    assign LEDR[8]   = cmd_decoded_q;
    assign LEDR[7:0] = last_response_byte;
endmodule
```

## Companion mcp-eda tools

| Tool | Use |
|------|-----|
| `mcp__eda-tools__device_camera_capture` | Snapshot LEDs to JPG with auto-exposure |
| `mcp__eda-tools__device_camera_led_diff` | Compare two captures, output per-LED state diff |

Capture once at reset (baseline) and again after the test stimulus;
diff to confirm the expected LEDs lit up.

## Anti-patterns

- **One-LED-per-signal mismatch.** Using `instantaneous` mode for a
  1-cycle pulse → the camera will never catch it.
- **All signals on the same mode.** Mixing pulse + sticky + byte
  modes without commenting which is which → reviewer cannot decode
  the photo.
- **Sticky without a reset path.** A sticky LED will be ON forever
  even if the test never stimulated the signal — make sure the reset
  clears it before each test stage.
- **Placement on shared LED pins.** Some boards reuse LED pins for
  other functions (USB-Blaster, configuration). Check the QSF before
  allocating LEDR[N].

## Compliance

This skill emits a *template*. Validate with:

- `fpga_async_input_synchronizer_check` — ensure inputs are properly
  synchronised before driving FSMs that LEDs probe.
- `fpga_pullup_lint` — ensure tri-state pins have the correct pull-up
  declarations.

When camera capture is part of the verification flow, the LED probe
allocation should also be cited in `RESULTS.md` so a reviewer can map
the captured JPGs back to the design.

## Compliance gate (vibe-ic-d - mandatory when deterministic edition is installed)

If you have the `vibe-ic-d` plugin installed alongside `vibe-ic`,
after producing your output, save it to a file and run:

```bash
python3 plugins/vibe-ic-d/_shared/skill_compliance_check.py \
    --requirements plugins/vibe-ic-d/skills/fpga-led-probe-allocation/compliance.yaml \
    <your_output_file>
```

Exit 0 = PASS, exit 1 = FAIL with specific missing elements listed.
`compliance.yaml` in the corresponding vibe-ic-d skill directory enumerates
every required element of your output: section headers, metadata fields,
handoff lines, tool invocations.

**Your task is not complete until the audit returns PASS.** Missing
elements are the single largest source of skill-execution non-determinism
across different agents.
