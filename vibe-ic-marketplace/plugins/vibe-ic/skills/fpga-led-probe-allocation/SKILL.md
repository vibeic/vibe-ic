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

## Anti-patterns (run the lint — do NOT eyeball these)

> **Doctrine (user, 2026-05-29):** 把修法寫進工具，而非寫進 prompt.
>
> The four deterministic structural anti-patterns below are now enforced
> by **`programs/fpga_led_probe_lint.py`** (17 pytest cases pin each
> rule + every no-false-alert guard). Run the program on your emitted
> top BEFORE claiming the LED allocation is sound — the prose below is
> the rationale, not the rule applicator.

```bash
python3 plugins/vibe-ic/programs/fpga_led_probe_lint.py \
    <your_fpga_top.v> \
    [--qsf <board.qsf>] \
    [--json fpga_led_probe_lint.json]
```

Exit codes: `0` = PASS (ERROR-free; WARNINGs may still be reported);
`1` = ERROR anti-pattern found; `2` = **NOTHING EXAMINED** — no input file, or
no LED drive in any file that was read. `2` is the *disclosed-skip* tier, never
a pass: `flow_compliance_check` files it as VACUOUS_PASS. The JSON `findings[]`
carries `rule` / `file` / `line` / `detail` / `fix_hint` for each ERROR;
`warnings[]` carries the same shape for advisory hits; `unreadable[]` and
`led_drives_examined` disclose the lint's actual coverage.

**Where it runs automatically.** Flow step 6, as an `advisory_program_exit_zero`
leg guarded by `condition_files_exist: [phase2/stage1/fpga/*.qsf]`. It RECORDS,
it does not block. Over the 28 published run roots it executes on 1 and is
silent on 27 (no `.qsf`). Making it blocking needs a run where Quartus genuinely
built and more than one FPGA top to measure against.

The four rules it flags (and ONLY these — no false alerts):

- **`instantaneous-on-pulse`** — Using `instantaneous` mode
  (`assign LED[N] = sig;`) for a 1-cycle pulse → the camera will never
  catch it. Evidence is **two-tier**, because a name alone is not always
  enough:
  - **ERROR** — the structural set-1/set-0 pulse shape (evaluated *outside*
    reset branches, so a reset clear is not read as a pulse deassert), **or**
    an unambiguous pulse-token name (`*_pulse`, `*_strobe`, `*_stb`, `*_tick`,
    `*_edge`, `*_trig`, `*_fire`, `*_onehot`).
  - **WARNING** — a *handshake* token only (`*_done`, `*_valid`, `*_ack`,
    `*_req`, `*_start`, `*_stop`) with no structural pulse shape. These name a
    held level at least as often as a pulse; measured on a real FPGA top,
    `test_done` was asserted in one state and HELD in the terminal state, and
    calling that a pulse was wrong. Reported, never a red.
  - Names on the level deny-list (`*_en` / `*_busy` / `*_state` / `*_q` / …)
    are never a pulse, and a pulse fed through `pulse_stretch` is not flagged.
- **`mode-mix-without-table`** — Mixing ≥ 2 of {pulse, sticky, byte}
  modes without a commented probe table → reviewer cannot decode
  the photo. A single-mode top needs no table (not flagged).
  `instantaneous` is the BASELINE mode and is **not** a mix participant — a
  byte column plus one level probe is the recommended layout above, not an
  anti-pattern. The table is recognised either by the literal
  **`LED PROBE TABLE`** title *or* by a commented block that actually maps ≥ 2
  LED indices to signals: the rule fires on a missing TABLE, not a missing
  STRING.
- **`sticky-without-reset-clear`** — A sticky LED latch set to `1'b1` and
  driving an LED but never cleared on reset will be ON forever even if the
  test never stimulated the signal. The lint accepts both `if (!rst_n)
  reg <= 1'b0;` and group-clear `{a, b} <= 2'b00;`.
- **`shared-pin-vs-QSF`** — An LED bit driven in RTL with no matching
  `set_location_assignment ... -to LEDR[N]` in the supplied `.qsf` (some
  boards reuse LED pins for USB-Blaster / configuration). **Skipped
  entirely when no `--qsf` is supplied** — absence is never a false FAIL.

**AI judgment still required:** the lint enforces the *structural*
anti-patterns; YOU still choose the right mode per signal (is this signal
truly steady-state, a 1-cycle pulse, or an event flag?) and author a
PROBE TABLE whose human-readable "expected behaviour per test stage"
column actually matches the host capture sequence. The lint cannot judge
whether your mode *choice* matches the signal's real timing — only that
the code is internally consistent.

## Compliance

This skill emits a *template*. Validate with:

- `fpga_async_input_synchronizer_check` — ensure inputs are properly
  synchronised before driving FSMs that LEDs probe.
- `fpga_pullup_lint` — ensure tri-state pins have the correct pull-up
  declarations.

When camera capture is part of the verification flow, the LED probe
allocation should also be cited in `RESULTS.md` so a reviewer can map
the captured JPGs back to the design.

## Compliance gate (mandatory)

After producing your output, save it to a file and run:

```bash
python3 plugins/vibe-ic/_shared/skill_compliance_check.py \
    --requirements plugins/vibe-ic/skills/fpga-led-probe-allocation/compliance.yaml \
    <your_output_file>
```

Exit 0 = PASS, exit 1 = FAIL with specific missing elements listed.
`compliance.yaml` in the corresponding skill directory enumerates
every required element of your output: section headers, metadata fields,
handoff lines, tool invocations.

**Your task is not complete until the audit returns PASS.** Missing
elements are the single largest source of skill-execution non-determinism
across different agents.
