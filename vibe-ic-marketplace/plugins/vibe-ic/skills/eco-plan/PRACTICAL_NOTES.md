# ECO Plan — Practical Notes

**Added**: 2026-04-07 from a digital pilot design review

## Pilot ECO Score: 3/10

AI-generated RTL is NOT ECO-friendly by default. The LLM focuses on functional correctness, not physical-design-aware provisions.

## Must-Add for Any Tapeout Design

1. **Spare cells** — 10-15% of gate count. Use `(* keep *)` attribute to prevent synthesis from removing them.
2. **Debug bus** — 16-bit minimum, routed to a test pad or multiplexed onto an existing pin.
3. **Physical block fences** — define in OpenROAD as placement regions to enable per-module ECO.

## Yosys Spare Cell Insertion

```
# After synthesis, before write_verilog:
# Yosys doesn't have native spare cell insertion.
# Workaround: instantiate spare cells in RTL with (* keep *) attribute
```

## OpenROAD Metal Reservation

```tcl
# In P&R script, limit signal routing to Metal1-4:
set_routing_layers -signal Metal1-Metal4
# Metal5 reserved for ECO
```
