---
name: tapeout-checklist
description: Review native DRC, LVS, STA, IR-drop, EM, antenna, ERC, LEC, DFT coverage and release evidence against original requirements before an authorized GDS handoff.
---

# Tapeout Checklist

Review every applicable native tool result before a GDS handoff. Read
`<project>/reports/flow_engine.json` produced by the normal public runner;
`flow/steps.json` supplies the current row positions and names. The Router's
selected window runs through the sole engine path. Do not introduce another
execution or approval layer.

For each selected row, open the native files named in `reports` and inspect
`tool_ran`, `native_steps`, `native_metrics`, and the value/operator/original
limit in `metrics`. Confirm the intended design, corner and tool actually ran.
AI review each native result for physical plausibility, missing coverage and
engineering risk, retaining the existing per-row review and its measured
duration. Missing native data or an absent original limit is `NOT_MEASURED`;
it cannot be turned into PASS by an archive, report format or summary.

Keep spec, PDK and owner limits unchanged. Failed, deferred or unmeasured work
remains open. Record any owner-accepted engineering exception with its actual
scope and risk; an exception does not make the unexecuted measurement pass.

## Portable design-release archive

The existing packaging producer writes `release_manifest.json`, `SHA256SUMS`
and a relative `archive/` tree. The manifest separates final-GDS design
material, retained internal STA/SDC/SPEF and logic/electrical closure, external
PDK/tool dependencies, and the provider upload subset. A file's presence does
not qualify its signoff: existing producer readers must measure the selected
final-GDS subject, and incomplete or failed measurements remain incomplete.
Manufacturing-service `PENDING_FOUNDRY_*` fields are not seven universal gates.

For a new version without changing the source project:

```bash
python3 programs/foundry_handoff_pack_gen.py <project> --out-dir <new-version-dir>
python3 programs/foundry_handoff_package_check.py <new-version-dir> \
  --package-dir <new-version-dir> --json <check-output.json>
```

`--out-dir` must not already exist; old versions are retained. A provider die
assembly is selected only through its producer-owned `--release-record` and
`die_finishing_gen.read_admitted_release`, never an arbitrary GDS override.
Use the packaging checker's existing `--design-release` mode when checking
technical release completion; its compatibility mode reports `LEGACY_SKELETON`.
A relocated check validates the retained archive; it does not
rerun EDA or claim provider submission/order acceptance. Slot, CoB and IDs
must come from the actual selected provider inputs and current precheck.

## Read the actual measurements

Use the selected native tool results for SPEF parasitic extraction, post-route
MCMM STA, IR/EM/antenna/SI, post-layout gate simulation, SPICE correlation,
ECO, metal fill, FPGA final recompile, and analog work when applicable. A
smaller subset of successful reports cannot establish completion of those
obligations. For static IR-drop, keep the actual declared budget; the existing
budget reader can inspect the native report without moving that budget:

```bash
python3 plugins/vibe-ic/programs/ir_drop_budget_check.py \
    <ir_report_or_dir> --vdd <V> --budget-pct 10
```

The command's 10 percent budget applies only when it is the actual original
requirement; it does not replace a stricter spec or PDK limit. Use each run's
native report paths and disclose every selected `FAIL` or `NOT_MEASURED` item
in the final report, along with any deferred obligation and its real risk.

## When to use

- Final 1–2 weeks before GDS release
- After the final ECO
- As a nightly regression item for any design in the "tapeout window"

## Review the required engineering results

- Functional simulation and required code/functional/assertion coverage meet
  their original targets. Formal results disclose the proved property,
  assumptions and any bounded depth. Native equivalence reports compare the
  required RTL and netlist with actual comparison points.
- Native STA covers the required setup, hold, recovery/removal, pulse-width,
  transition and capacitance checks at the original MCMM corners.
- Native IR-drop and EM values meet the actual spec and library budgets.
  Review the current density, power grid and switching-activity basis.
- Native DRC, LVS, antenna, metal-density and ERC results meet the actual PDK
  rules. An absent report or an unexamined layout remains `NOT_MEASURED`.
- DFT/ATPG, scan, BIST and test-access results meet the original foundry or
  owner requirements. Missing DFT data does not establish completion.
- Package, pad, release and manufacturing inputs match the selected provider's
  actual requirements and the measured design scope.

Read the actual native report for each obligation and review its engineering
meaning. Retain original numeric limits and explicit owner exceptions. Do not
substitute file presence, a signature or an archive hash for a measurement.

## Handoff

- Any red item routes back to its owning skill (`/sta-review`, `/drc-fix`, etc.)
- After applicable native measurements meet their original limits, follow the owner's authorized GDS release workflow.
