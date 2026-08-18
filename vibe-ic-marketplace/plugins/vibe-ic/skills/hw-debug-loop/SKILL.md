---
name: hw-debug-loop
description: Closed-loop hardware debug methodology for half-duplex protocol ICs when BFM passes but real-silicon connect_test FAILs (Category B/C from the A/B/C extraction-gap analysis). Use after spec-to-rtl + flow_compliance_check have all PASSed, the SOF has been burned to FPGA, and the host-side acceptance test (e.g., <half-duplex-tester> byte[6]=0x02) is FAILing. The skill drives a deterministic bisect using scope capture + oracle bytewise dump + controlled wrapper-flip experiments until byte[6]=0xF2 PASS or until the failing item is recorded as an irreducible Category-B silicon discrepancy. Triggers on "byte[6]=0x02 FAIL", "BFM passes HW fails", "connect_test FAIL", "silicon-vs-spec mismatch", or "I have an oracle SOF and need to bisect".
---


<!-- WAVE_76_CHIP_AGNOSTIC_BANNER -->

> **Case-study notation.** This skill cites the <chip-class> / <half-duplex-tester> /
> MDV-A1101 <benchmark> reference project as concrete evidence for the
> rules below. The rules themselves are chip-AGNOSTIC and apply to
> any IC of the matching `ic_class` (see
> `vibe-ic-marketplace/plugins/vibe-ic/programs/ic_class_profile.py`).
> When you adopt this skill on a different IC, swap `<chip-class>` →
> `<your IC name>` and `<half-duplex-tester>` → `<your host-tester name>`; the
> structural gates and rule bodies do not depend on those SKUs.
> See `docs/design/CASE_STUDIES/AS3616_*.md` for the full <benchmark>
> regression history.

# Closed Hardware Debug Loop

Phase 2c, post-burn: the plugin's structural gates have all PASSed,
the project's BFM is 12/12 byte-exact, the SOF is burned, but the host
acceptance test (the project's `<host_tester>` verdict — e.g. byte[6]
on a half-duplex protocol IC, or the equivalent rig verdict for the
target IC class) FAILs. This skill is the methodology that drives the
fix without an indefinite trial-and-error loop.

## Why This Skill Exists

After v0.119.5–v0.119.11 the plugin captures Categories A and most of
C. Two classes of failure remain:

  - **Category B** — vendor doc disagrees with silicon (e.g. v099
    oracle returns 18 bytes for 0xE6 but the doc says 22). Plugin
    extractor cannot detect this from L1-L27 alone; the only ground
    truth is silicon.

  - **Category C residual** — sub-microsecond pad / FPGA-pad-inference
    details that surface only when a particular agent's RTL pattern
    interacts with a particular silicon's analog front-end. Each new
    instance becomes a new structural gate (LL-15/16/17/23 are these),
    but the next one is unknown until it appears.

The closed debug loop converts an indefinite "try-and-error until it
works" into a bounded sequence of named experiments, each producing a
named evidence file, each leading to a deterministic next step.

## When to Use

Trigger when ALL of:

  - `flow_compliance_check.py` reports `Overall: PASS`.
  - BFM `eda_simulate` shows `verdict: PASS opcodes=N fails=0`.
  - SOF burned successfully, FPGA JTAG verifies the device.
  - Host acceptance test (e.g. `device_tester_md905_connect_test`)
    returns `verdict: FAIL` with a non-canonical byte[6].

Do NOT trigger if:

  - Any `flow_compliance_check` gate FAILs — fix the gate first.
  - BFM is not yet at 12/12 — fix the byte-level model first.

## When NOT to Use

  - First fresh-agent run: gates may be FAILing for A/C reasons that
    must be fixed first; running this skill is wasteful.
  - User has not granted oracle reference: Category B requires
    comparing against a known-PASS SOF or oracle bytewise dump. Stop
    and ask the user.

## Inputs

1. A burned, FAILing chip SOF (verified against the project's
   `<host_tester>` rig — see `docs/design/CASE_STUDIES/` for
   <chip-class> + <half-duplex-tester> byte[6] reference setup).
2. A known-PASS oracle SOF (or `eda_oracle_bytewise_dump` capture).
3. A scope reachable via `device_scope_capture` (Keysight DSO-X
   class — confirm with `eda_device_list category=scope`).

## Process — 7-Step Closed Loop

### Step 1 — Establish baseline FAIL with structured evidence

Run the host acceptance test, capture the verdict + frame bytes:

```bash
mcp__eda-tools__device_tester_md905_connect_test collect_seconds=8
```

Save the response under `evidence/baseline_fail.json`. Record:

  - `verdict`
  - byte[0..6] of every E0 frame
  - `connect_reply_hex` byte[12..63]

Also record `git rev-parse HEAD` of vibe-ic-marketplace and
`stat -c '%y'` of the burned SOF. Reproducibility matters for B
findings.

### Step 2 — Burn the oracle and confirm PASS on the rig

This rules out rig drift. Without a confirmed PASS oracle you cannot
distinguish "test broken" from "RTL broken".

```bash
mcp__eda-tools__eda_fpga_program tool=quartus sof_file=<oracle.sof>
mcp__eda-tools__device_tester_md905_connect_test
```

Save under `evidence/oracle_pass.json`. If the oracle does NOT PASS
on the rig, stop — rig is in unknown state, escalate.

### Step 3 — Scope-capture both versions

While `connect_test` runs, capture a 10 ms scope window on the
chip-side bus pin (channel 1 unless project's QSF says otherwise).
Decode pulses by width into BIT0/BIT1/BR/WAKE classes.

```bash
mcp__eda-tools__device_scope_capture span_ms=10 trigger_slope=falling
```

Save `evidence/scope_oracle.csv` and `evidence/scope_chip.csv`. Diff
the pulse-train summary:

  - same WAKE width (within ±0.5 us tolerance)?
  - same WAKE interval (within ±50 us)?
  - any data-byte activity beyond the wake pulses?

### Step 4 — Decide A vs B vs C with the decision tree

```
Scope-pulse-trains identical (within tolerance)?
├── YES → Category C: pad-level / fan-out / inference difference.
│       Inspect Quartus *.fit.rpt for the bus pin:
│        - "Combinational Fan-Out" — must be 1 (LL-23)
│        - "Output Enable Source"  — should be a pin-local "*~N (inverted)"
│       Bisect by controlled wrapper-flip:
│         take the oracle RTL, swap ONLY the wrapper expression style
│         to your chip's style, recompile, test. The swap that flips
│         PASS→FAIL is the C root cause. Add a structural gate (see
│         the LL-23 template) and commit.
│
└── NO  → Category B: a byte stream mismatch.
        Run eda_oracle_bytewise_dump on the oracle SOF:
          mcp__eda-tools__eda_oracle_bytewise_dump
        Save under input/oracle/<name>_bytewise_dump.json.
        Diff vs L3.command_table.fields_tx for every opcode the
        rig exercises. For each delta:
          - patch L3 to match silicon
          - record in waivers.json["oracle_referenced_fix"]:
              {"opcode": "0xE6", "field": "tx_len",
               "spec": 22, "silicon": 18,
               "evidence": "input/oracle/...bytewise_dump.json"}
          - re-run spec-to-rtl
          - back to Step 1.
```

If the scope shows your chip drives NOTHING (only wake pulses) where
the oracle drives a 17-byte response, the chip is not entering the
expected response path. Inspect the chip's main FSM with a
`dbg_state_o` LED tap; the chip is probably stuck in S_IDLE or
S_RX waiting for a frame_end that never fires.

### Step 5 — Apply the fix and run the gate that catches it

Each fix has a corresponding plugin gate (or needs one created):

| Symptom | Likely fix | Gate that catches it post-fix |
|---|---|---|
| TX_IBT < 0.5×tSRS_min | bump IBT to MAX of L2 ibt_us range | LL-15 |
| `id_bus_oe = a \| b` in top wrapper | route everything through tx_phy | LL-16 |
| `oe ? 0 : 1'bz` wrapper | split into `(oe && !tx) ? 0 : 1'bz` | LL-17 |
| Pad fan-out > 1 | reduce internal taps on bus_oe | LL-23 |
| 0xE6 length 22→18 | patch L3.fields_tx + waiver | LL-22 |
| Symbolic VID / SN in fields_tx | resolve to OTP byte addresses in L11 | LL-19 |

If the symptom is new, write a structural gate for it BEFORE
declaring the fix complete. The gate is the regression guard.

### Step 6 — Re-burn, re-test, capture proof

```bash
mcp__eda-tools__eda_fpga_compile ...
mcp__eda-tools__eda_fpga_program ...
mcp__eda-tools__device_tester_md905_send_raw cmd_byte=255   # disconnect
mcp__eda-tools__device_tester_md905_connect_test
```

Save `evidence/iter_<N>_pass.json` if `verdict: PASS`. Record the
verdict, the frame bytes, the SOF sha256.

### Step 7 — Convergence audit

After byte[6]=0xF2 PASS:

```bash
python3 plugins/vibe-ic/programs/hw_acceptance_test_passed_check.py \
    <project_dir>
```

This gate verifies:

  - `evidence/baseline_fail.json` is committed.
  - `evidence/iter_N_pass.json` exists with byte[6] == 0xF2 and
    `total_frames >= 5`.
  - Every `oracle_referenced_fix` waiver has a corresponding
    artifact under `input/oracle/`.

Only when this gate PASSes is Phase 2c complete. Re-run
`flow_compliance_check.py --strict` to confirm overall verdict is
`PASS_WITH_WAIVERS` (the waivers being the Category-B oracle
references), and Phase 2+3 is closed.

## Output Files

| File | Content |
|------|---------|
| `evidence/baseline_fail.json` | First FAIL frames + SOF sha + git rev |
| `evidence/oracle_pass.json` | Oracle SOF PASS verification on this rig |
| `evidence/scope_oracle.csv` | Bus pulse train under oracle SOF |
| `evidence/scope_chip.csv` | Bus pulse train under chip SOF |
| `input/oracle/<name>_bytewise_dump.json` | Oracle byte stream (Category B) |
| `evidence/iter_<N>_pass.json` | Final PASS verification |
| `waivers.json` `oracle_referenced_fix` | Each B-class spec → silicon delta |

## Anti-patterns This Skill Prevents

1. **"Just try a few more things"** — the loop is bounded:
   each iteration produces named evidence and a named decision.
   If the same gate keeps FAILing across iterations, the methodology
   has been broken; stop and re-read.

2. **Silently copying oracle bytes** — every spec → silicon delta
   must land in `waivers.json` with a link to the dump file. The
   waiver IS the spec correction; the agent who reads the spec
   next must see why the L1-L27 → RTL flow needed a delta.

3. **Adding fixes without a structural gate** — every C-class fix
   must be accompanied by a structural gate (or an extension of an
   existing one). Otherwise the next fresh agent silently
   re-introduces the bug.

4. **Declaring PASS without re-running gates** — after every fix,
   re-run `flow_compliance_check.py --strict`. The gate that
   catches your fix should now PASS; gates that did not catch it
   should also still PASS.

## Compliance gate

After every Step-6 PASS, the convergence audit (Step 7) is
mandatory. The audit's gate is named
`hw_acceptance_test_passed_check.py` and is included in
`_STRUCTURAL_RTL_GATES`. Phase 2+3 is closed when that gate AND
`flow_compliance_check --strict` both PASS.

## Handoff

- After PASS: hand off to Phase 3 (silicon flow: synth → STA →
  DFT → PnR → DRC → LVS → GDS → tapeout). The validated chip
  RTL + waivers form the Phase-3 input.
- After FAIL with bounded retries exhausted: stop and report
  honestly. The silicon disagrees with the spec in ways the plugin
  cannot detect; either patch the spec from oracle, or accept that
  this IC class needs a different methodology (e.g., black-box
  copy of a known-good SOF).
