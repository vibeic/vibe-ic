# MMIO timer / interrupt register set (real-world pipeline shape)

This fixture exercises a pipeline-order interaction that synthetic
minimal-case unit tests do NOT cover. Two distinct walker classes
touch the same register's `reset_value`:

1. An early walker captures `unspecified` from prose context
   (`_v1_6_482_prose_adjacency` / `_v1_6_503_inject_indexed_array_prose_seed`).
2. A late walker overwrites with the actual `0x0` reset value
   (`_v1_6_503_lift_scalar_reset_from_prose`).

A naive `reset_value_kind` back-fill that runs between (1) and (2)
will stamp `symbolic` (correct for the early value), then never
re-classify after (2) lands — leaving `rv=0x0, kind=symbolic`
inconsistency. This is the shape that broke #400 R1 (16/16 unit
tests PASS but 23/75 real entries had no kind tag + MSWI showed
the stale-kind inconsistency).

Use in an end-to-end test:

```
src = load_real_fixture("mmio_register_set_pipeline_late_overwrite.md")
# wire src into extracted, run gen_l4_regmap, assert L4.registers[*]
# carry consistent (rv, kind) pairs.
```

---

## Memory-mapped timer counter
**Address**: 0xBFF00000
**Reset value**: unspecified
**Description**: 64-bit free-running counter, increments at TCLK.
The counter's reset value is 0x0 at hardware reset.

## Memory-mapped timer compare
**Address**: 0xBFF00008
**Reset value**: 0x0
**Description**: Compare value for the timer interrupt.

## Software interrupt request
**Address**: 0xBFF00100
**Reset value**: 0x0
**Description**: Writing 0x1 raises the software interrupt to the hart.
The bit clears automatically when the trap handler returns.

## Port-input data register
**Address**: 0xC0001000
**Reset value**: 0x0
**Description**: Reads the live state of the N input pins. Read-only.

## Port-output data register
**Address**: 0xC0001004
**Reset value**: 0x0
**Description**: Drives the N output pins. Read/write.

## Port-direction control register
**Address**: 0xC0001008
**Reset value**: 0x0
**Description**: 1 = output, 0 = input. Reset to all-input.

## Interrupt-type configuration register
**Address**: 0xC0001100
**Reset value**: 0x0
**Description**: 1 = edge-triggered, 0 = level. Per-line setting.
