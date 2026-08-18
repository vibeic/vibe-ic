# `src/devices/` — vendor-extensible device plugin point

This directory is the MCP-server-side framework for **lab instruments** —
oscilloscopes, FPGAs, logic analyzers, signal generators, power supplies,
DMMs, and anything else that lives over USB / GPIB / ethernet on the
benchtop. The goal is a single integration point so AI agents (running
through MCP) can drive real hardware without each skill author having to
re-solve USB permissions, SCPI parsing, or vendor library installation.

## Auto-registration model

At server start, `src/index.js` calls `registerDevices(server)` from
[`_registry.js`](./_registry.js). The registry:

1. Scans `src/devices/*/manifest.json` (skips entries starting with `_`
   or `.`).
2. Validates each manifest's required keys (`vendor`, `device_class`,
   `tools[]` with `name` / `description` / `driver` / `schema`).
3. Converts each tool's JSON-Schema-lite into a real `zod` schema.
4. Registers each tool against the `McpServer` instance with a
   subprocess handler that:
   - spawns `python3 <vendor>/<driver>` with the validated args as JSON
     on stdin (and `--mode <mode>` if declared);
   - captures stdout, parses it as one JSON object;
   - returns `{ content: [{ type: "text", text: <stdout-json> }] }`;
   - sets `success: false` when the driver exits non-zero or when the
     subprocess hits the per-tool `timeout_ms` (default 60 000 ms).

Vendors only ship a directory; **no changes to core code** are required.
A broken manifest skips itself and prints the reason to stderr; it
cannot block server startup.

## Two-level directory layout (v0.66)

```
src/devices/
├── <category>/                      ← e.g. fpga/, scope/, tester/, camera/,
│                                      logic-analyzer/, signal-generator/, ...
│   └── <vendor-device>/             ← e.g. keysight-scope/, terasic-de10lite/
│       ├── manifest.json            ← required, declares 1+ MCP tools
│       ├── driver.{py,sh,js}        ← required, JSON-stdin → JSON-stdout
│       ├── README.md                ← required, hardware setup + models
│       ├── udev/*.rules             ← optional, redistributable USB rules
│       └── tests/                   ← recommended, mock-driven contract tests
```

The category layer (fpga / scope / tester / camera / logic-analyzer /
signal-generator / power-supply / dmm / ...) lets contributors and
readers see device classes at a glance and keeps multiple competing
vendors for the same class side-by-side (e.g. eventually
`scope/rigol-ds1054z/` alongside `scope/keysight-scope/`).

Manifest-discovery walks exactly two levels — `<category>/<vendor>/manifest.json`.
Deeper nesting is ignored. A directory name starting with `_` or `.` is
skipped (e.g. `_disabled-keysight-legacy/` is invisible to the registry).

## Currently shipped device drivers

| Category | Path | Vendor | Homepage | Tools | Status |
|----------|------|--------|----------|-------|--------|
| `scope` | [`scope/keysight-scope/`](./scope/keysight-scope/) | Keysight Technologies | <https://www.keysight.com/> | `device_scope_capture`, `device_scope_periodic_pulse_check` | Verified on DSO-X 3014T |
| `fpga` | [`fpga/terasic-de10lite/`](./fpga/terasic-de10lite/) | Terasic Technologies | <https://www.terasic.com.tw/> | `device_fpga_de10lite_program`, `device_fpga_de10lite_detect` | Verified on DE10-Lite (MAX10); v0.66 adds pre-burn `rtl_precheck_gate` + post-burn scope attestation wiring |
| `tester` | [`tester/usb-hid-tester/`](./tester/usb-hid-tester/) | Vendor | TBD | `device_tester_usb_hid_tester_connect_test`, `device_tester_usb_hid_tester_send_raw` | Verified on USB-HID tester (Nuvoton USB HID 0316:403e) — caught reference IC byte[6]=0xF2 PASS live |
| `camera` | _camera/_ | TBD | TBD | — | future contribution (non-IVI) |
| `logic-analyzer` | _logic-analyzer/_ | TBD | TBD | — | future contribution (IVI doesn't cover this class; keep custom) |
| `fgen` | _fgen/_ | TBD | TBD | — | future contribution (`IviFgen` — function / arbitrary waveform generators) |
| `dcpwr` | _dcpwr/_ | TBD | TBD | — | future contribution (`IviDCPwr` — programmable DC supplies) |
| `acpwr` | _acpwr/_ | TBD | TBD | — | future contribution (`IviACPwr` — AC / mains simulators) |
| `dmm` | _dmm/_ | TBD | TBD | — | future contribution (`IviDmm` — digital multimeters) |
| `specan` | _specan/_ | TBD | TBD | — | future contribution (`IviSpecAn` — spectrum analyzers) |
| `rfsiggen` | _rfsiggen/_ | TBD | TBD | — | future contribution (`IviRFSigGen` — RF signal generators) |
| `swtch` | _swtch/_ | TBD | TBD | — | future contribution (`IviSwtch` — switch / matrix modules) |
| `pwrmeter` | _pwrmeter/_ | TBD | TBD | — | future contribution (`IviPwrMeter` — RF/optical power meters) |
| `counter` | _counter/_ | TBD | TBD | — | future contribution (`IviCounter` — frequency / time-interval counters) |
| `mcu` | _mcu/_ | TBD | TBD | — | future contribution (non-IVI — MCU dev boards, debug probes) |
| `env` | _env/_ | TBD | TBD | — | future contribution (non-IVI — environmental / temperature chambers) |

**Vendor attribution surfaces in MCP tool descriptions.** When `manifest.json` declares `vendor_full_name` + `vendor_homepage` (both optional but recommended), the registry composes the registered tool description as `[<class> · by <vendor_full_name> <vendor_homepage>] <original description>`. Example: `[oscilloscope · by Keysight Technologies <https://www.keysight.com/>] Arm a Keysight InfiniiVision-class scope, capture a single window…`. LLM agents see the attribution alongside the tool, which improves provenance trust.

## v0.67 manifest extensions

Five optional top-level / per-tool fields join the schema:

| Field | Level | Values / example | Purpose |
|-------|-------|------------------|---------|
| `ivi_class` | top-level | `"IviScope"`, `"IviDmm"`, `"IviFgen"`, `"IviDCPwr"`, `"IviACPwr"`, `"IviSpecAn"`, `"IviRFSigGen"`, `"IviSwtch"`, `"IviPwrMeter"`, `"IviCounter"`, `"IviDigitizer"` — or omit for non-IVI devices (FPGAs, testers, cameras) | Tags the instrument with its IVI Foundation class so MCP clients can discover interchangeable devices. Unknown names log a warning but do not block registration. |
| `supported_platforms` | top-level | array of `"linux"` / `"darwin"` / `"win32"` (default `["linux"]`) | Filter at server start time — drivers not matching current platform are skipped with `[devices] SKIP ... (platform)` and never registered. |
| `permissions` | top-level | `"require_group:plugdev"`, `"require_binary:quartus_pgm"`, `"require_env:QUARTUS_ROOTDIR"`, `"require_file:/etc/udev/rules.d/foo.rules"` | Declarative preconditions. Registry evaluates at start; unmet conditions log `[devices] NOTE ...` but do NOT block registration (driver surfaces the real error at invocation). For MCP-client discoverability, not gatekeeping. |
| `mode` | per-tool | `"hw"` / `"sim"` / `"mock"` (default `"hw"`) | Declares whether the tool touches real hardware. Lets one vendor-device ship `<tool>_hw` + `<tool>_sim` variants (e.g. pre-recorded CSV playback). Unknown value = manifest validation error. |
| `timeout_sec` | per-tool | positive number (default `60`) | Per-call wall-clock cap in seconds. v0.67 is a hard rename — the old `timeout_ms` is rejected at validation so there is exactly one truth for timeouts. |
| `resources` | top-level | array of resource entries (each has `name` / `uri` / `description` / `driver` / `tool_mode`; optional `mime_type` / `timeout_sec`) | **v0.68** — read-only state surfaced as MCP resources (URI-fetchable, no input schema). Mirrors `tools[]`; see "Resources vs tools" below. |

The pre-v0.67 per-tool `mode` field (which carried the driver-dispatch keyword) has been renamed to **`tool_mode`** to free the `mode` name for the hw/sim/mock semantic. Drivers continue to receive the dispatch value as `--mode <value>` on the command line; only the manifest-side key name changed.

## v0.67 DeviceError taxonomy

Every shipped driver (`scope/keysight-scope/driver.py`, `fpga/terasic-de10lite/driver.py`, `tester/usb-hid-tester/driver.py`) now raises one of seven standard exceptions defined in [`_shared/errors.py`](./_shared/errors.py) instead of ad-hoc `{"success": false, "error": "..."}` strings. The 5-field canonical error body is:

```json
{
  "success": false,
  "error_code": "device_not_found",   // stable machine tag
  "error": "no hidraw node for VID=0x0001 PID=0x0002",
  "recoverable": true,                // AI hint: should it retry?
  "last_seen_output": "",             // tail of subprocess stdout/stderr
  "context": {"vid": 1, "pid": 2}     // driver-specific extras
}
```

Error codes and default exit-code mapping:

| `error_code` | Exit | Recoverable? | When |
|--------------|------|--------------|------|
| `device_not_found` | 2 | ✅ | USB device / hidraw node not present — user re-plugs |
| `permission_denied` | 2 | ✅ | udev / group permission denied — user fixes rules |
| `vendor_tool_not_found` | 2 | ✅ | Required binary (e.g. `quartus_pgm`) not on PATH |
| `invalid_argument` | 2 | ❌ | Caller-supplied args failed validation — not recoverable by retry |
| `timeout` | 1 | ✅ | Operation exceeded per-tool timeout |
| `protocol_error` | 1 | ❌ | Device returned malformed / unexpected data — firmware mismatch |
| `device_busy` | 1 | ✅ | Another process holds the device |

MCP clients should branch on `error_code`, not the English `error` message.

## v0.68 resources (read-only state) vs tools (actions)

**Tools** are actions with side effects: arm a scope capture, program an FPGA, send a test packet. **Resources** are read-only state the MCP client can fetch any time via a URI: current scope setup, last-programmed SOF hash, whether the USB-HID tester is enumerated right now. Tools clutter the agent's callable surface when used for pure "what is the current state?" queries — that belongs in resources. MCP clients fetch resources by URI (`scope://keysight-dso-x-3014t/current_setup`) and never have to guess an argument schema.

Declaring a resource mirrors declaring a tool: add a top-level optional `resources[]` array in `manifest.json` (each entry has `name`, `uri`, `description`, `driver`, `tool_mode`, and optional `mime_type` / `timeout_sec`). The URI must match `<category>://<vendor-device>/<resource-name>` (lowercase ASCII / digits / `_` / `-`). The registry routes resource reads to the same driver executable, invoked with `--mode <tool_mode>`, so one `driver.py` can serve both tool actions and resource reads.

Reference resource: `scope/keysight-scope/` ships `scope://keysight-dso-x-3014t/current_setup` backed by `driver.py --mode read_state`. It returns live trigger / timebase / per-channel probe & coupling state via SCPI queries — no acquisition armed, scope run-state untouched.

## Contributing a new device

See [`CONTRIBUTING.md`](./CONTRIBUTING.md) for the full vendor on-ramp
(manifest schema, driver contract, tool naming convention, hardware setup
checklist, testing expectations, license rules).
