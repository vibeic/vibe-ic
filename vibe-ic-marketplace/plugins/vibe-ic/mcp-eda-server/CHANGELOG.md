## [0.114.0] - 2026-05-08

### Version-label catch-up (v0.101 → v0.114)

Closes a long-standing metadata drift: features for waves v0.108 / v0.110 / v0.113 / v0.114 actually landed in `src/index.js` but the `package.json` version stayed pinned at `0.101.0`. This entry retroactively records what was already shipped in code:

- **v0.108** — +5 analog/SPICE tools (`eda_xschem_netlist`, `eda_spice`, `eda_spice_corner`, `eda_extraction`, `eda_analog_layout`); open-sourced under MIT.
- **v0.110** — `+eda_phase23_completion_audit` — orchestrator wrapper over `flow_compliance_check.py --strict` returning the SOLE-ACCEPTANCE-CRITERION verdict tier.
- **v0.113** — `+mcp_server_health_check` — liveness probe for MCP server bring-up (P1.4).
- **v0.114** — `+eda_oracle_bytewise_dump` (BACKLOG-v6 D2): burn known-PASS oracle SOF onto the FPGA, capture host-tester byte stream, emit as ground-truth oracle for full-stack TB cross-checks.

Tool count (verified by grep): 37 `server.tool(...)` calls in `src/index.js` + 9 manifest-driven device tools (2 scope + 4 tester + 3 fpga) = **46 tools total**.

No code changes in this entry — purely a `package.json` version + CHANGELOG sync.

## [0.100.0] - 2026-05-05

### Wave 47-72 cumulative

**Driver enhancements**:
- keysight-scope/driver.py auto-probes 4 PIDs (3014T/3024G/3034T/generic) — Wave 51
- usb-hid-tester/driver.py + manifest `device_id_bus_force_low_pulse` mode — Wave 59

**Tool defaults moved out of /tmp** (Wave 57):
- eda_simulate output_vvp: /tmp/sim.vvp → ./sim/sim.vvp
- eda_spice output_file: /tmp/spice_out.txt → ./sim_spice/spice_out.txt
- eda_xschem_netlist / eda_spice_corner / eda_cocotb / eda_extraction defaults

**eda_spice_corner custom PDK** (Wave 48): pdk=custom + custom_corner_lib param removes gf180/sky130 hard rejection

# mcp-eda-server CHANGELOG

## v0.99.10 — 2026-05-03 (Wave 36)

**Track B of column-D behavioral test-case audit — id-bus opcode injection scaffold.**

Paired with vibe-ic-marketplace v0.119.68. Wave 36 audited the 7
column-D behavioral discrepancies in `2026_04_27_FPGA_and_IC_test_items.xlsx`
against v0.119.67 RTL (see `docs/design/COL_D_RTL_AUDIT_v0119.67.md`).
Hardware verification of the static FAIL/PARTIAL findings was blocked
by two tooling gaps in v0.99.9:

1. `device_tester_usb_hid_tester_send_raw` could not actually inject id-bus
   opcodes — the manifest description claimed
   `cmd_byte=0x20 + payload_hex='70'` would forward opcode 0x70 onto
   the id_bus, but the USB-HID tester firmware drops unrecognised cmd bytes
   (only 0x10 / 0x20 / 0xFF / 0xE0 are recognised).
2. `device_id_bus_force_low_pulse` schema is millisecond-precision,
   but id-bus bit cells are microseconds (BIT0 LOW = 7.1 µs).
   Constructing a bit-stream from userspace via repeated calls is
   impossible by 3 orders of magnitude.

### Fixes

* **New tool `device_id_bus_send_opcode`** — added via the usb-hid-tester
  manifest (`tool_mode: send_opcode_id_bus`). Takes `opcode` (8-bit) +
  optional `payload_hex` + `pre_wake` (boolean) + `force_extra_bit`
  (`none` / `first_byte_lsb` / `last_byte_msb`) + `collect_seconds`.
  Constructs the canonical id-bus bit-stream (BR + opcode bits
  LSB-first + payload bits + CRC8 with poly 0x8C reflected, init 0xFF,
  LSB-first) and tries delivery via the proposed firmware command
  `0x21 INJECT_ID_BUS_OPCODE`. If the connected USB-HID tester firmware
  predates 0x21 support (current shipping firmware does), returns
  `verdict: NEEDS_FIRMWARE_SUPPORT` with a structured `bit_stream`
  description so callers have an unambiguous tooling-not-yet-capable
  signal instead of a misleading PASS or silent failure. The
  `force_extra_bit` knob is the negative-test path for column-D R8/R9
  9-bit byte rejection (deliberately emit a 9th bit on first / last
  byte).
* **`device_tester_usb_hid_tester_send_raw` manifest description corrected** —
  removes the false claim about id-bus opcode forwarding, points
  agents to the new `device_id_bus_send_opcode` tool. The `cmd_byte`
  field description now states which 4 commands the USB-HID tester firmware
  actually recognises.
* **Driver helpers** — `_crc8_reflected_init_ff(data)` and
  `_frame_to_bit_stream(opcode, payload, force_extra_bit)` factored
  out so the bit-stream description is identical for the firmware-
  supported and NEEDS_FIRMWARE_SUPPORT paths.

### Tests

* `test/test_usb_hid_tester_send_opcode_id_bus.py` (12 tests):
  * 3 `_crc8_reflected_init_ff` reference-vector tests including
    column-D R5 expected reply CRC (`73 C0 00 F8 00 → 0x3C`) and
    sanity of the v0.119.67 hardcoded `0xDC`.
  * 5 `_frame_to_bit_stream` tests covering BR + LSB-first bit order,
    canonical bit count, and the 9th-bit `force_extra_bit` knob.
  * 4 CLI argument-validation tests (missing `opcode`,
    out-of-range `opcode`, bad `force_extra_bit`, invalid
    `payload_hex`).
* All 41 `test/test_devices_registry.sh` device-registry smoke tests
  remain green.

### Test counts

* 45 pytest passed + 2 skipped (was 33 + 2 in v0.99.9).
* 41 device-registry smoke checks (unchanged).

## v0.99.9 — 2026-05-04 (Wave 33)

**eda_fpga_program back-door close + CI sentinel + burn provenance.**

Paired with vibe-ic-marketplace v0.119.65. Forensic
`docs/design/WAVE32_DUAL_GOVERNANCE_HOLE.md` proved that the v0.119.64
36th-attempt fresh-agent benchmark FAIL (USB-HID tester byte[6]=0x02 across
5/5 runs) was enabled by a back door in this server: `eda_fpga_program`
exposed a direct `execSync("quartus_pgm -c X -m JTAG -o P;<sof>")`
call with NO pre-burn flow_compliance / RTL precheck guard. The agent
routed a known-FAIL SOF through this path instead of the Wave 30
guarded `device_fpga_de10lite_program`.

### Fixes

* **`eda_fpga_program` is now a thin wrapper.** The Quartus/SOF path
  delegates to the `device_fpga_de10lite_program` driver via
  `spawnSync("python3 driver.py --mode program --json-args -")`.
  `bypass_pre_burn_check` is hard-coded `false` AND removed from the
  wrapper's zod schema, so callers cannot reach the override knob
  through this tool.
* **CI sentinel** `tools/check_no_unguarded_burn.sh` fails when any
  `*.js` / `*.ts` / `*.py` file under `src/` invokes
  `execSync("...quartus_pgm... -o \"P;...\"")` /
  `spawn*("...quartus_pgm... -o \"P;...\"")` /
  `execSync("...openocd... program ...")` outside guarded contexts
  (driver.py, `_run_flow_compliance_pre_burn`, `guarded_burn`
  comment markers, `test_*` filenames).
* **`burn_provenance.json`** — both `device_fpga_de10lite_program`
  driver and the new `eda_fpga_program` wrapper write
  `<project>/reports/burn_provenance.json` on successful burn:
  `{burn_at, sof_path, sof_sha256, audit_json_path, audit_sha256,
   audit_verdict, guard_invoked, tool, session_id}`. Forensic
  timeline analysis is now trivial.

### Tests

* `test/test_eda_fpga_program_wrapper.py` (3 tests):
    - `test_eda_fpga_program_no_direct_execsync_quartus_pgm` —
      regex-checks `index.js` to assert no direct burn execSync
      remains in the wrapper block.
    - `test_driver_blocks_burn_on_audit_verdict_fail` — end-to-end
      simulation of an audit JSON with verdict=FAIL → driver returns
      `error_code` starting with `burn_blocked`.
    - `test_wrapper_does_not_expose_bypass_in_schema` — verifies the
      wrapper handler signature does not accept
      `bypass_pre_burn_check` from the caller.
* `test/test_no_unguarded_burn_sentinel.py` (3 tests):
    - `test_current_tree_passes_sentinel`
    - `test_planted_violation_caught` — plants a synthetic
      `_wave33_planted_violation.js` with an unguarded burn and
      verifies the sentinel exits 1 with the expected marker.
    - `test_test_fixture_violation_ignored` — plants the same
      violation under a `test_*.js` filename and verifies the
      sentinel exempts test fixtures.

Test totals: 33 PASS, 2 SKIPPED (yosys-equiv tests need real
iverilog/yosys binaries).

## v0.99.8 — 2026-05-03 (Wave 30 / 32)

Wave 30 fail-closed pre-burn audit + canonical
phase23_completion_audit.json artifact.

(See vibe-ic-marketplace plugin CHANGELOG for full detail.)
