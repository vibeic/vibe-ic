# atpg-name-harmonize — Practical Notes

## Why this skill exists

Fault (open-source ATPG) inserts scan chains by creating intermediate netlist
nodes with Yosys-style escape identifiers like `\__uuf__._NNNN_.B`. These are
legal SystemVerilog escape-identifier names but:

1. **iverilog hierarchical probes fail on them** — `tb.u_dut.\__uuf__._0123_.B`
   returns an unresolved-reference error even though Yosys accepts the name.
2. **VCD waveform tools garble them** — GTKWave shows `_uuf___NNNN_.B` or
   similar without the backslash, making fault-injection debugging slow.
3. **Post-Fault LVS fails** — the escape identifiers don't match the DEF
   (which uses a subset of non-escape characters).

This skill rewrites the escape identifiers to plain alphanumeric
(`__uuf___NNNN__B`), emits a name-map JSON so fault-locations can be traced
back, and is idempotent.

## Gotchas

### Name-collision risk
The rewrite is purely mechanical: `\__uuf__._0123_.B` → `__uuf___0123__B`.
If the original netlist already has a signal named `__uuf___0123__B` (rare
but possible), the rewrite creates a collision. The script detects this at
write-time and exits with a collision report. Fix: pass `--prefix scan_`
to namespace the rewritten names.

### Name-map JSON
The `--name-map` output is required input to downstream probe-generation
tools. Ship it alongside the rewritten netlist. Format:

```json
{
  "\\__uuf__._0123_.B": "__uuf___0123__B",
  ...
}
```

### Yosys `yosys_flatten_scan.ys` companion pass
For more aggressive name cleanup, use the companion Yosys script:

```bash
yosys -s yosys_flatten_scan.ys
```

This flattens hierarchy and re-emits the netlist with `-pprefix ""`, which
avoids the escape-identifier generation in the first place. Slower (≈ 2x the
time of a pure rewrite) but produces the cleanest result.

### iverilog-specific behaviour
iverilog 10.x has a known bug where `$dumpvars(0, dut.\__uuf__._N_.B);`
segfaults. The workaround (prior to this skill) was to use array-of-wire
probes. After harmonize, the normal probe works.

### Fault tool versions
- **Fault 0.9 / 1.0**: produces escape-identifier names; this skill applies.
- **Fault 1.1+**: adds a `--no-escape` flag that avoids the problem upstream.
  If you're on 1.1+, use `--no-escape` and skip this skill.

## PDK-specific quirks

None. The rewrite is purely syntactic on netlist text; it does not inspect
cell libraries or the PDK.

## Provenance

Derived from an earlier pilot's `fix_fault_cut_names.py` during
the v0.63 ROADMAP packaging pass. The earlier release hardcoded the scan-cut
netlist path to a project-specific location; now reads from `--scan-cut`.
