# Contributing a new device to `mcp-eda`

Welcome. This document is the on-ramp for adding a new lab instrument
(scope, FPGA, logic analyzer, signal generator, power supply, DMM, ...)
to the MCP server's auto-registered device pool.

You ship a single directory under `src/devices/<category>/<vendor-device>/`;
the framework picks it up at server start. There are no edits to core
code.

## 1. Required directory layout (v0.66 two-level)

```
src/devices/<category>/<vendor-device>/
    manifest.json           # required — declares 1+ MCP tools
    driver.py               # required — executable, JSON-IO contract
    README.md               # required — hardware setup, supported models
    udev/*.rules            # optional — redistributable USB rules
    tests/                  # recommended — mock-driven contract tests
```

The **`<category>`** name is the device class. Use one of the canonical
values already present in `device_class` manifest fields:

| category folder | IVI class | used for |
|-----------------|-----------|----------|
| `fpga/`           | (non-IVI) | FPGA dev boards, programmers |
| `scope/`          | `IviScope` | Oscilloscopes (any class — analog, digital, mixed-signal) |
| `tester/`         | (non-IVI) | IC acceptance / production-test boxes (e.g. USB-HID tester) |
| `camera/`         | (non-IVI) | Vision systems, beam profilers, die-inspection cams |
| `logic-analyzer/` | (non-IVI) | Saleae / Sigma-class multi-channel digital capture |
| `fgen/`           | `IviFgen` | Function / arbitrary waveform generators |
| `dcpwr/`          | `IviDCPwr` | Programmable DC / bench supplies |
| `acpwr/`          | `IviACPwr` | AC / mains simulators |
| `dmm/`            | `IviDmm` | Digital multimeters |
| `specan/`         | `IviSpecAn` | Spectrum analyzers |
| `rfsiggen/`       | `IviRFSigGen` | RF signal generators |
| `swtch/`          | `IviSwtch` | Switch / matrix modules |
| `pwrmeter/`       | `IviPwrMeter` | RF / optical power meters |
| `counter/`        | `IviCounter` | Frequency / time-interval counters |
| `mcu/`            | (non-IVI) | MCU dev boards, debug probes |
| `env/`            | (non-IVI) | Environmental / temperature chambers |

v0.67 prefers IVI-standard short names (`fgen`, `dcpwr`, `specan`, ...) over the older ad-hoc labels (`signal-generator`, `power-supply`, ...). When your device fits an IVI class, declare it via the top-level `ivi_class` manifest field (see below) so MCP clients can discover interchangeable devices.

If your device doesn't fit, pick a new lowercase-hyphen-separated name
and open a discussion first — we'll add it to the canonical list.

The **`<vendor-device>`** name must:
- start with a letter (no leading `_` — those are reserved for
  framework files like `_registry.js`);
- be all lowercase, hyphen-separated, including the model if it helps
  disambiguate (e.g. `keysight-scope`, `terasic-de10lite`,
  `usb-hid-tester`, `saleae-logic16`);
- match `manifest.json`'s `vendor`-`device_class` or `vendor`-`model`
  identity (loose convention, not enforced).

Manifest discovery walks **exactly two levels** — `<category>/<vendor>/manifest.json`.
Deeper nesting is ignored. Directories starting with `_` or `.` at
either level are skipped (e.g. `_disabled-siglent-legacy/` is invisible
to the registry — handy for archiving deprecated drivers without
deleting them).

Driver may be `.py`, `.sh`, or `.js` — but `_registry.js` currently
spawns it with `python3`, so use Python (or shell out from a thin
`driver.py` wrapper). See "Driver contract" below.

## 2. `manifest.json` schema (full reference)

Top level:

| Key             | Type   | Required | Notes                                     |
|-----------------|--------|----------|-------------------------------------------|
| `vendor`        | string | **yes**  | URL-safe slug; used in directory name and MCP tool descriptions. e.g. `"keysight"`, `"terasic"`, `"vendor"` |
| `vendor_full_name` | string | no    | Display name (use this for proper capitalization, accents, marks). e.g. `"Keysight Technologies"`, `"Terasic Technologies"`, `"Vendor"`. If absent, the slug is used. |
| `vendor_homepage`  | string | no    | Vendor's official website. MUST be `http(s)://...` if present. Surfaces in the registered tool description as `[<class> · by <name> <url>]` so MCP clients can attribute the device. |
| `device_class`  | string | **yes**  | e.g. `"oscilloscope"`, `"fpga"`, `"tester"`, `"logic_analyzer"`, `"fgen"`, `"dcpwr"`, `"dmm"` |
| `ivi_class`     | string | no       | **v0.67** — IVI Foundation instrument-class name when the device fits a standard class: `"IviScope"`, `"IviDmm"`, `"IviFgen"`, `"IviDCPwr"`, `"IviACPwr"`, `"IviSpecAn"`, `"IviRFSigGen"`, `"IviSwtch"`, `"IviPwrMeter"`, `"IviCounter"`, `"IviDigitizer"`. Non-IVI devices (FPGAs, testers, cameras) simply omit this field. Unknown names log a warning but do not block registration. |
| `supported_platforms` | array of string | no | **v0.67** — which OS the driver works on. Values from Node.js `process.platform`: `"linux"`, `"darwin"`, `"win32"`. Default `["linux"]`. Drivers not matching the current platform are skipped at server start with a `[devices] SKIP ... (platform)` line. |
| `permissions`   | array of string | no  | **v0.67** — declarative preconditions: `"require_group:<name>"`, `"require_binary:<name>"`, `"require_env:<VAR>"`, `"require_file:<path>"`. Registry evaluates at start; unmet conditions log `[devices] NOTE ...` but do NOT block registration (the driver surfaces the real error at invocation time — this list is for MCP-client discoverability, not gatekeeping). |
| `version`       | string | no       | semver of the manifest itself             |
| `supported_models` | array of string | no | human-readable list for the README       |
| `tools`         | array  | **yes**  | ≥ 1 tool entry, see below                 |
| `resources`     | array  | no       | **v0.68** — ≥ 0 read-only state entries exposed as MCP resources. See "Resources vs tools" below. |

**Why we recommend filling vendor metadata even though it's optional**:
when the same scope or FPGA is sold under multiple OEM brands, the
`vendor_full_name` + `vendor_homepage` resolves attribution
ambiguity without us having to run a slug-to-company lookup table.
LLM agents using MCP also surface this attribution to end users
(`Tool: device_scope_capture — by Keysight Technologies <https://www.keysight.com/>`),
which builds trust in the tool's provenance.

Each entry of `tools[]`:

| Key            | Type   | Required | Notes                                                        |
|----------------|--------|----------|--------------------------------------------------------------|
| `name`         | string | yes      | MCP tool name (see naming convention below)                  |
| `description`  | string | yes      | one-paragraph; surfaces verbatim in the MCP tool list        |
| `driver`       | string | yes      | path to executable, **relative to the vendor directory**     |
| `tool_mode`    | string | no       | **v0.67** — driver-dispatch keyword passed as `--mode <value>` on the CLI. Lets one driver implement multiple MCP tools. Was called `mode` pre-v0.67. |
| `mode`         | string | no       | **v0.67** — one of `"hw"` / `"sim"` / `"mock"` (default `"hw"`). Declares whether the tool touches real hardware; unknown value fails manifest validation. |
| `timeout_sec`  | number | no       | **v0.67** — per-call wall-clock cap in seconds; default 60. Hard rename from the pre-v0.67 `timeout_ms` — the old key is rejected at validation so there is exactly one truth. |
| `schema`       | object | yes      | JSON-Schema-lite for the tool's args (may be `{}` for no-arg tools) |

### JSON-Schema-lite (the supported subset)

For each field name → spec object. Supported spec keys:

| Spec key       | Allowed values                                  | Notes                                |
|----------------|-------------------------------------------------|--------------------------------------|
| `type`         | `"string"`, `"integer"`, `"number"`, `"boolean"` | required                             |
| `enum`         | array of strings                                 | only with `type: "string"`           |
| `default`      | any of the matching type                         | makes the field optional with default |
| `optional`     | `true`                                           | makes the field optional, no default |
| `description`  | string                                           | surfaces in tool docs                |

Anything outside this subset prints a warning and is treated as `string`.
(Don't try to express nested objects, arrays, oneOf, anyOf, regex, etc. —
keep tools flat. If you need structured input, encode it as a JSON string
and parse it inside the driver.)

### Resources vs tools (v0.68)

**Tools** are actions (side effects — arm a capture, program an FPGA, send a test packet). **Resources** are read-only state the MCP client can fetch any time via URI (current scope setup, last-programmed SOF hash, hidraw enumeration). Pick the right bucket: if the driver reads state and doesn't perturb the hardware, declare it under `resources[]`. If it changes anything, it's a tool.

Each entry of `resources[]`:

| Key           | Type   | Required | Notes                                                       |
|---------------|--------|----------|-------------------------------------------------------------|
| `name`        | string | yes      | short name (not the full MCP tool-naming convention — resources are URI-addressed) |
| `uri`         | string | yes      | must match `^[a-z][a-z0-9_-]*://[a-z0-9_-]+/[a-z0-9_-]+$` — convention `<category>://<vendor-device>/<resource-name>` |
| `description` | string | yes      | one paragraph; surfaces in the MCP resource list            |
| `driver`      | string | yes      | relative path to the executable (usually the same `driver.py` as the tools) |
| `tool_mode`   | string | yes      | dispatch keyword passed as `--mode <value>` to the driver — MUST match a mode branch the driver implements |
| `mime_type`   | string | no       | default `"application/json"` (structured state); may be `"text/csv"`, `"text/plain"`, etc. |
| `timeout_sec` | number | no       | default `10` (resources should be fast read-only ops)       |

Resources have no input schema — the URI is the address, not a form. If a read needs parameters, it's a tool.

Reference: [`scope/keysight-scope/`](./scope/keysight-scope/) declares `scope://keysight-dso-x-3014t/current_setup` → `driver.py --mode read_state`, which SCPI-queries the scope's current trigger / timebase / per-channel state without arming a capture.

## 3. Driver contract

The framework spawns:

```
python3 <vendor>/<driver> --mode <mode> --json-args -
```

with the validated args object piped to stdin as a single JSON document.

The driver MUST:

- Read JSON from `stdin` when `--json-args` is `-` (or absent), or from
  the value of `--json-args` directly.
- Emit **exactly one JSON object on stdout** (no progress logs, no
  banner, no trailing text). Progress / debug → stderr.
- Exit with:
  - `0` for success;
  - `1` for "ran cleanly but verdict is FAIL" (e.g. test detected a bug,
    or a recoverable runtime error: `timeout` / `protocol_error` /
    `device_busy`);
  - `2` for "couldn't run" (`invalid_argument` / `device_not_found` /
    `permission_denied` / `vendor_tool_not_found`).
- Respond to `--help` without crashing and without touching hardware
  (used by CI smoke tests).

### v0.67 DeviceError taxonomy (required)

Instead of returning ad-hoc `{"success": false, "error": "..."}` strings,
drivers MUST raise one of the seven standard exceptions in
[`_shared/errors.py`](./_shared/errors.py) and wrap `main()` with:

```python
from errors import (DeviceError, DeviceNotFoundError, PermissionError_,
                    DeviceTimeoutError, DeviceProtocolError,
                    VendorToolNotFoundError, DeviceBusyError,
                    InvalidArgumentError, EXIT_FOR_CODE)

try:
    rc, body = mode_xxx(params)
except DeviceError as e:
    body = e.as_json_body()
    body["mode"] = args.mode
    print(json.dumps(body))
    return EXIT_FOR_CODE[e.error_code]
```

Every error body is guaranteed to have all 5 canonical fields:

| Field | Type | Purpose |
|-------|------|---------|
| `success` | `false` | Constant for errors |
| `error_code` | stable machine tag | MCP clients branch on this — never parse the English message |
| `error` | human string | For logs / diagnostics |
| `recoverable` | boolean | Hint for AI agents: should they retry? |
| `last_seen_output` | string | Tail of subprocess stdout/stderr |
| `context` | object | Driver-specific extras (VID/PID, paths, exit_code, ...) |

Exception → error_code → exit-code mapping:

| Exception | `error_code` | Exit | Recoverable |
|-----------|--------------|------|-------------|
| `DeviceNotFoundError` | `device_not_found` | 2 | ✅ |
| `PermissionError_` | `permission_denied` | 2 | ✅ |
| `VendorToolNotFoundError` | `vendor_tool_not_found` | 2 | ✅ |
| `InvalidArgumentError` | `invalid_argument` | 2 | ❌ |
| `DeviceTimeoutError` | `timeout` | 1 | ✅ |
| `DeviceProtocolError` | `protocol_error` | 1 | ❌ |
| `DeviceBusyError` | `device_busy` | 1 | ✅ |

Success paths and "device ran but reports FAIL" paths continue to emit
the existing JSON shape (no breaking change for happy-path callers).

The framework will:

- Parse the stdout JSON and forward it to the MCP client unchanged.
- If parsing fails: synthesize an error body containing the raw stdout
  and stderr tails.
- If the process exits non-zero but the body looks OK: flip
  `success: false` and add `exit_code`.
- If the process is killed by timeout: add `success: false`,
  `timeout_ms`.

## 4. Tool naming convention

Use **`device_<class>_<vendor-or-board>_<action>`** in tool names.

Rationale: the `device_` prefix groups all hardware tools in MCP
discovery, the class lets agents filter by capability, and the
vendor/board + action keeps names unambiguous when multiple vendors ship
the same class. Examples from this repo:

- `device_scope_capture` — generic class `scope`, action `capture`.
- `device_scope_periodic_pulse_check` — `scope`, action `periodic_pulse_check`.
- `device_fpga_de10lite_program` — class `fpga`, board `de10lite`, action `program`.

Use the `<class>_<action>` short form (without vendor) only when the
action is portable across all vendors of that class (rare today; favor
the long form). Avoid camelCase, dashes, and dots.

## 5. Hardware setup expectations

Each vendor MUST ship:

- A `README.md` with:
  - supported models (verified vs likely-compatible);
  - cabling diagram or text description;
  - install instructions for any vendor SDK / Python packages;
  - troubleshooting table for common failure modes.
- A `udev/*.rules` file (when the device is USB-attached) that grants
  `plugdev` group r/w access. Document the install steps in the README.
- A statement of permission model in the README (user must be in
  `plugdev`, etc.).

Vendor SHOULD list the minimum vendor-tool version tested, not just "any
recent version".

## 6. Testing expectations

Each vendor SHOULD include a `tests/` directory with mock-driven tests
that exercise the JSON-IO contract without requiring real hardware.
Examples:

- `tests/test_args_validation.py` — feed invalid JSON, assert exit 2.
- `tests/test_help.py` — `--help` exits 0.
- `tests/test_mock_pulse_check.py` — monkeypatch the SCPI client, run
  `mode_pulse_check`, assert verdict for a synthetic pulse train.

The repo-wide smoke test
(`mcp-eda/test/test_devices_registry.sh`) already verifies:

- every `manifest.json` parses;
- every declared `driver` exists and is executable;
- every driver's `--help` runs cleanly;
- every driver's `--mode <known> --json-args '{}'` produces a JSON body
  (success or structured error — must not crash).

## 7. Reference vendor drivers

We ship three paired references covering distinct device classes and
distinct driver shapes — read them before contributing:

| Path | Class | Why it's worth reading |
|------|-------|------------------------|
| [`scope/keysight-scope/`](./scope/keysight-scope/) | `oscilloscope` (signal acquisition) | SCPI over USB-TMC, two tools (low-level capture + high-level verdict), CSV-in-JSON sample export |
| [`fpga/terasic-de10lite/`](./fpga/terasic-de10lite/) | `fpga` (configuration / programming) | shells out to a vendor binary (`quartus_pgm`), search-path discipline for finding it, parsing vendor stdout for success markers; v0.66 adds pre-burn RTL gate + post-burn scope attestation wiring |
| [`tester/usb-hid-tester/`](./tester/usb-hid-tester/) | `tester` (acceptance verification) | raw `/dev/hidraw*` USB HID — no external Python lib dependency, async response collection windowed by time, canonical PASS/FAIL byte-fingerprint decoding |

Together they cover the three most common device-driver shapes:
**(a)** instrument-library client (Keysight: SCPI via `usbtmc`),
**(b)** vendor-binary wrapper (Terasic: orchestrate `quartus_pgm`), and
**(c)** raw-protocol stdlib client (Vendor: hidraw direct, no SDK).

If your device fits any of these three shapes, copy the closest
reference and adapt. If it doesn't (e.g. ethernet-attached rack
instrument, GPIB), open a discussion before opening a PR — the
auto-registry framework may need a small extension.

## 8. PR review checklist (for the maintainer)

- [ ] Directory under `src/devices/<category>/<vendor-device>/` exists; both names follow convention (lowercase, hyphen-separated, no leading `_`)
- [ ] `manifest.json` parses; required keys present; schema uses only the supported subset
- [ ] `driver.py` is executable, has `--help`, has `--mode` matching every manifest tool's `tool_mode`
- [ ] Driver respects JSON-IO contract: single JSON object on stdout, logs on stderr, correct exit codes
- [ ] Driver imports the v0.67 `_shared/errors.py` taxonomy and wraps `main()` with `try/except DeviceError`
- [ ] Error bodies have all 5 canonical fields (`success` / `error_code` / `error` / `recoverable` / `last_seen_output`)
- [ ] `supported_platforms` declared if the driver is not universal (default `["linux"]`)
- [ ] `permissions` declared for every precondition the driver needs (`require_group`, `require_binary`, `require_env`, `require_file`)
- [ ] `ivi_class` declared if the device fits a standard IVI Foundation class
- [ ] `timeout_sec` used (not the deprecated `timeout_ms`)
- [ ] If declaring `resources[]`, every URI matches `<category>://<vendor-device>/<resource-name>` and every `tool_mode` maps to a branch the driver actually implements (read-only, no side effects)
- [ ] `README.md` lists supported models, hardware setup, install, troubleshooting
- [ ] `udev/*.rules` shipped for USB devices; install command documented
- [ ] No imports from `vibe-ic-marketplace/` or any private project
- [ ] License declared and compatible with MIT (`MIT`, `BSD-2-Clause`, `BSD-3-Clause`, `Apache-2.0`)
- [ ] `test_devices_registry.sh` still passes (no manifest crashes the smoke test)
- [ ] Tool names use `device_*` prefix and the convention above

## 9. License

`mcp-eda` is Apache-2.0-licensed. Any vendor driver added here MUST be
under an Apache-2.0-compatible OSS license. Acceptable: MIT, BSD-2-Clause,
BSD-3-Clause, Apache-2.0. Reject GPL/LGPL drivers (they would re-license
the server). Add a `# License:` line at the top of `driver.py` when the
upstream license differs from Apache-2.0.
