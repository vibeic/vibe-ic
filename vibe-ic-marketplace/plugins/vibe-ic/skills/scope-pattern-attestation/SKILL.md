---
name: scope-pattern-attestation
description: Layer-3 hardware attestation — talk to an oscilloscope via SCPI to verify behavioral patterns (or absence of patterns) on real silicon IO. Use when sim and static RTL checkers can both pass but you need to confirm the actual hardware doesn't exhibit a forbidden timing pattern (e.g. periodic wake pulses that should have stopped after a state transition). Triggers when user says "scope check", "verify on hardware", "is the wake pulse really stopping", or hands you scope screenshots / SCPI traces.
---

# scope-pattern-attestation — Layer-3 hardware attestation

> **Doctrine (v0.1.50):** 把修法寫進工具，而非寫進 prompt.
> Programs run the pattern-match; AI is the backstop on waveform interpretation.

## Mandatory Deterministic Preflight

```bash
# 1. Capture the scope trace via MCP-EDA:
device_scope_capture({ channel: 1, duration_ms: 100 })

# 2. Then run the pattern-specific check:
python3 plugins/vibe-ic/programs/scope_periodic_pulse_check.py \
    --trace <trace.csv> --strict        # forbidden-pattern absence
python3 plugins/vibe-ic/programs/scope_reply_preamble_check.py \
    --trace <trace.csv> --strict        # required-pattern presence
python3 plugins/vibe-ic/programs/scope_response_byte_decode_check.py \
    --trace <trace.csv>
python3 plugins/vibe-ic/programs/scope_long_decode.py \
    --trace <trace.csv>                 # long-frame decode
```

The MCP captures the trace; the 4 programs decide pattern PASS / FAIL
deterministically. **Refuse to attest a pattern by visual inspection
of the scope screenshot** when the program can decide it.

---

This skill closes the third layer of the v0.65 three-layer defense. Sim
PASS and static-RTL PASS together are still not proof; the only proof
that an IC exhibits (or does not exhibit) a behavioral pattern in
silicon is to put a probe on the line and capture it.

## Why This Exists

A real bug, caught in v0.64, motivates this skill. The static analyser
`timer_freeze_after_state_check.py` flagged a wake-timer freeze defect
in `wake_ctrl.v`: after the bus had entered the awake state, a periodic
timer kept firing pulses on the IO line. A Keysight DSO-X 3014T probe
captured the offending IO line and saw 10 LOW pulses in a 50 ms window
— each ~26 µs wide, gaps 5.000-5.001 ms apart — exactly the buggy
waveform predicted from the static finding.

The static checker (v0.64) and the runtime scope checker (this v0.65
skill) are **complementary layers**, not duplicates:

| Layer | Catches | Misses |
|---|---|---|
| 1. Sim (testbench) | Logic bugs that the testbench stimulates | Anything not stimulated |
| 2. Static (timer_freeze_after_state_check, etc.) | RTL anti-patterns | Synthesis / mapping artefacts; analog issues |
| 3. **scope-pattern-attestation (this skill)** | **Real silicon behavior** | Anything you forgot to probe |

Use this skill whenever Layers 1 + 2 PASS but the consequence of being
wrong is shipping a defective IC.

## When To Use

* Sim + static both PASS, but you want hardware-level confirmation
  before tape-out / before committing a fix.
* A static checker has flagged a behavior that you need to confirm or
  refute on the actual board (positive or negative attestation).
* User explicitly asks: "scope check", "verify on hardware", "is the
  pulse really stopping", "attest on silicon".

## How To Use

### Hardware Setup

1. Probe the IO line of interest with a scope channel (passive 10:1
   probe, BW limit ON for digital lines).
2. The user must trigger the IC into the suspected-bad state BEFORE
   running the program — the script arms a single-shot capture; if the
   line never transitions, the trigger times out.
3. For USB scope access on Linux, install a udev rule so the user can
   talk to the device without root:

   ```
   # /etc/udev/rules.d/99-keysight.rules
   SUBSYSTEM=="usb", ATTRS{idVendor}=="2a8d", ATTRS{idProduct}=="1768", MODE="0666"
   ```

   Replace VID/PID for any other USBTMC scope.

### CLI

The deterministic implementation is
`plugins/vibe-ic/programs/scope_periodic_pulse_check.py`. Typical
hardware-side invocation:

```bash
python3 plugins/vibe-ic/programs/scope_periodic_pulse_check.py \
    --channel 4 \
    --span-ms 50 \
    --period-ms 5 --period-tol-ms 1 \
    --pulse-min-us 10 --pulse-max-us 100 \
    --trigger-slope NEGATIVE --trigger-level-v 1.5 \
    --save-csv capture.csv
```

For CI / regression without any USB hardware, feed a previously
captured waveform CSV:

```bash
python3 plugins/vibe-ic/programs/scope_periodic_pulse_check.py \
    --mock-samples-csv capture.csv \
    --period-ms 5 --period-tol-ms 1 \
    --pulse-min-us 10 --pulse-max-us 100
```

Exit codes: `0` PASS, `1` FAIL, `2` argument / scope / capture error.

### MCP alternative

When this skill is invoked through Claude Code with the
`mcp-eda` MCP server attached, prefer the equivalent MCP tool
**`device_scope_periodic_pulse_check`** over the bare CLI. The MCP
tool wraps the same program with permission scoping for the USB device
and returns a structured JSON verdict, which makes the result easy for
downstream skills to consume programmatically.

## Inputs

| Input | Source | Notes |
|---|---|---|
| Probe → IO line | hardware setup | one channel only |
| `--period-ms` | from the static-check finding or spec | the forbidden inter-pulse period |
| `--pulse-min-us` / `--pulse-max-us` | from the IC datasheet (typical pulse width band) | filters out noise / unrelated edges |
| `--low-threshold-v` / `--high-threshold-v` | from the IO logic family (TTL/CMOS) | hysteresis thresholds |
| `--mock-samples-csv` (alt) | a previously captured waveform | enables CI without USB |

## Outputs

| Artefact | Where | Consumer |
|---|---|---|
| stdout verdict line `VERDICT: PASS` / `FAIL` | terminal | the calling agent |
| Exit code (`0` / `1` / `2`) | shell | CI / orchestrator |
| `--save-csv` raw samples | disk | re-runnable in `--mock-samples-csv` mode |

## Handoff

* On **PASS** — the silicon does not exhibit the forbidden pattern;
  attach the captured CSV (and the verdict text) to the tape-out
  evidence pack.
* On **FAIL** — re-flash the FPGA / re-spin the chip with the corrected
  RTL and re-run.

## Limits

* **Single-channel only.** This skill checks one IO line at a time.
  Multi-line patterns require multiple invocations.
* **The pattern must already be happening.** The script arms a
  single-shot capture; if the IC was never put into the suspected-bad
  state, no trigger fires and the program returns exit code 2.
* **Vendor-specific SCPI.** Defaults match the Keysight DSO-X 3014T USB
  IDs; other USBTMC scopes need `--vid` / `--pid` overrides, and some
  vendors use slightly different SCPI dialects (e.g. `:WAVEFORM:DATA?`
  block-header conventions). Verify on a known-good capture before
  trusting a verdict.
* **No analog characterisation.** This skill is purely a digital
  pulse-pattern detector. Use ams-sim / em-check for analog issues.
* **Not a sim replacement.** Sim and static checkers run before silicon
  exists; this is an after-silicon attestation layer.

## Compliance gate (mandatory)

After producing your output, save it to a file and run:

```bash
python3 plugins/vibe-ic/_shared/skill_compliance_check.py \
    --requirements plugins/vibe-ic/skills/scope-pattern-attestation/compliance.yaml \
    <your_output_file>
```

Exit 0 = PASS, exit 1 = FAIL with specific missing elements listed.
`compliance.yaml` in the corresponding skill directory enumerates
every required element of your output: section headers, metadata fields,
handoff lines, tool invocations.

**Your task is not complete until the audit returns PASS.** Missing
elements are the single largest source of skill-execution non-determinism
across different agents.

## Summary

`scope-pattern-attestation` is the third layer of the v0.65 defense
stack. Layers 1 (sim) + 2 (static RTL) screen designs cheaply; this
layer attests the actual silicon behavior. The deterministic backend
generalises the v0.64 wake-pulse specimen into an IC-agnostic SCPI
program with a `--mock-samples-csv` mode for CI.

**STATUS**: PASS once the verdict line reads `VERDICT: PASS`.

Next: if FAIL, re-flash the FPGA with the fixed RTL and re-run.
