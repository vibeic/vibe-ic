---
name: atpg-name-harmonize
description: Rewrite Fault ATPG scan-cut netlists with Yosys-style escaped identifiers (e.g. `\\__uuf__._NNNN_.B`) into plain alphanumeric names so iverilog hierarchical probes can find them. Required for any Yosys → Fault ATPG flow — otherwise the generated testbench fails with "Could not find variable". Handles UUF boundary cuts, scan-register nodes (SRN_*), boundary-scan registers (BSR_*), bus-indexed escapes, and a catch-all for generic dotted escape IDs. Optionally also runs a Yosys `flatten + rename -enumerate` pass for cleaner internal names.
---

# atpg-name-harmonize

Harmonize escape identifiers in a Fault-ATPG scan-cut netlist so
iverilog-based ATPG testbenches can probe hierarchical signals.

## When to use

- You ran Yosys → Fault ATPG and the generated testbench reports
  `Could not find variable uut.__uuf__._NNNN_.d`.
- Your scan-inserted netlist contains backslash-escaped identifiers
  with embedded dots, spaces, or bus indices (a common Yosys idiom).
- You want to clean a scan netlist *before* sending it to iverilog
  for sim-based fault grading.

## Inputs

### Python rewrite (`fix_fault_cut_names.py`)

| Flag | Required | Description |
|------|----------|-------------|
| `--scan-cut` | yes | Input scan-cut Verilog netlist (Fault output) |
| `--out` | yes | Output flattened Verilog path |
| `--name-map` | no | JSON path to record rewrite counters (before/after `__uuf__`, remaining backslashes) |

### Optional Yosys pass (`yosys_flatten_scan.ys`)

Driven via environment variables:

| Var | Description |
|-----|-------------|
| `LIBERTY` | Liberty file for the std-cell library |
| `SCAN_NETLIST` | Scan-inserted Verilog netlist to clean |
| `FLAT_OUT` | Output path for the flattened, renamed netlist |
| `TOP` | Top module name |

## Outputs

- `<out>.v` — scan netlist with all escape identifiers rewritten to
  plain alphanumeric names.
- `<name-map>.json` (optional) — counters showing how many escapes of
  each kind remained after rewrite (targets: 0 for `__uuf__`,
  backslash-SRN-d, backslash-BSR; plus total remaining backslash IDs).
- `<FLAT_OUT>.v` (when using the Yosys pass) — a fully flattened and
  renamed netlist using `rename -enumerate`.

## CLI invocation

```bash
# Option A — Python rewrite only (fast, no Yosys dependency)
python3 plugins/vibe-ic-core/skills/atpg-name-harmonize/fix_fault_cut_names.py \
    --scan-cut reports/atpg/mydesign_scan_cut.v \
    --out      reports/atpg/mydesign_scan_cut.flat.v \
    --name-map reports/atpg/name_map.json

# Option B — Yosys flatten + rename (more aggressive)
LIBERTY=pdk/lib/stdcells_typ.lib \
SCAN_NETLIST=reports/atpg/mydesign_scan.v \
FLAT_OUT=reports/atpg/mydesign_scan_flat.v \
TOP=mydesign \
yosys -c plugins/vibe-ic-core/skills/atpg-name-harmonize/yosys_flatten_scan.ys
```

Typical pipeline: run Option A first to keep the Fault-emitted cut
names traceable, and only fall back to Option B when the Python pass
leaves residual backslashes.

## Limitations

1. **Pattern set is Fault-specific** — the regexes target Fault v0.6
   output idioms. Other ATPG tools (Tessent, TestMAX) emit different
   escape patterns and will need the rule set extended.
2. **Not a formal-equivalent rewrite** — the renamed names are *not*
   automatically mapped back to the original diagnostic output. Keep
   `--name-map` counters so you can spot orphan escapes.
3. **Does not re-synth** — if your flow relies on the escape names
   cross-referencing a scan-chain order file, you must regenerate the
   order file against the renamed netlist.
4. **Yosys pass requires matching Liberty** — the Liberty supplied to
   `yosys_flatten_scan.ys` must be the same one used during scan
   insertion, otherwise `flatten` will introduce mismatches.
5. **Catch-all rule flattens brackets** — `[3]` bus indices inside
   escape identifiers become `_3` suffixes. Declarative bus width is
   *not* preserved; downstream parsers that need `wire [N:0] foo;`
   declarations must be re-derived.

## Output / Handoff

## Summary

- Rewrite counters (before/after) printed to stdout and optionally written to `name_map.json`.
- Target: `remaining_backslash_id == 0` after the Python pass.

Next: run `/atpg` again (or re-invoke `fault test` / `iverilog` on the harmonized netlist) to confirm the hierarchical probes now resolve.

## Compliance gate (vibe-ic-d — mandatory when deterministic edition is installed)

```bash
python3 plugins/vibe-ic-d/_shared/skill_compliance_check.py \
    --requirements plugins/vibe-ic-d/skills/atpg-name-harmonize/compliance.yaml \
    <your_output_file>
```

Exit 0 = PASS, exit 1 = FAIL.
