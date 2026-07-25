# Capture: L1 parametric bus-width binding

Authored on 8HD-8 against **plugin v1.6.1** (the tree actually exercised).
`main` of this repo is **v1.5.60**, so the two files these hunks touch are
NOT at the same revision here — one of them
(`l1_pin_bus_width_actionable_check.py`) does not exist on `main` at all,
it is new in v1.6.1. That is why the two edits ship as patches beside the
new program rather than as direct edits: applying them to `main` would
either fail or silently land against the wrong code.

**The Gatekeeper should apply these to a v1.6.1-or-later base.**

## What the defect was

Phase 1 extracts BOTH halves of a parametric port width into its own
typed output and never joins them. Measured on `spm`, v1.6.1, doc mode:

```
L1_DATASHEET.pin_table[x]  = {"width": "N-bit(`[size-1:0]`,parameter `size` 預設 32)",
                              "width_symbolic": "size-1:0",
                              "msb": null, "lsb": null}
L8_RTL_CONSTANTS.parameters = [{"name": "size", "default": "32", ...}]
L9_INTEGRATION_SPEC.parameters = [{"name": "size", "default": "32", ...}]
```

`_parse_port_width` cannot do the join — it sees only the width CELL, and
at its call site the sibling docs do not exist yet. By the end of the run
they all do. Consequence: phase2 emits a 1-bit scalar `x` for a 32-bit
multiplicand bus, and `l1_pin_bus_width_actionable_check` blocks the run.

## Files

| file | role |
|---|---|
| `programs/l1_param_bus_width_resolve.py` | NEW. The deterministic join. Self-contained, applies to any base. |
| `programs/tests/test_l1_param_bus_width_resolve.py` | NEW. 33 tests, bidirectional. |
| `_capture_patches/01_gate_width_symbolic_against_v1.6.1.patch` | teach the gate about `width_symbolic` |
| `_capture_patches/02_runner_wiring_against_v1.6.1.patch` | run the resolver before the semantic gates |

## Why patch 01 is not optional

The repair destroys the gate's own evidence. `_self_declares_bus()`
inspected only `("width","msb","lsb")` for a prose bit-range; once the
resolver rewrites those to integers, a pin whose ONLY bus evidence was
that prose stops being bus-confirmed and the gate drops to
`VACUOUS_PASS` — silently ceasing to assert on the very pin just
repaired. Patch 01 makes it also consult `width_symbolic`, the one bus
marker that SURVIVES resolution.

Measured, with patch 01 reverted:
```
AssertionError: gate lost its grip on the repaired pin:
  {'bus_confirmed': 0, 'verdict': 'VACUOUS_PASS', ...}
```

## Bidirectional evidence

Both directions asserted on the same fixture, against the REAL gate:

| direction | result |
|---|---|
| defect (resolver not run) | gate `FAIL` rc 1, violation on the bus pin |
| fixed (resolver run) | gate `PASS` rc 0, `bus_confirmed 1`, no violations |
| patch 01 reverted | `test_resolution_does_not_blind_the_gate` FAILS |
| no parameter binding available | resolver refuses; gate stays `FAIL` |
| conflicting defaults across docs | resolver refuses; reports `ambiguous_bindings` |
| pin already has integer width | untouched in either direction |

End-to-end on the real design (`spm`, plugin v1.6.1, image
`vibeic-eda:0.2.29` = `sha256:45fd4d622fe1755f...`, host 8HD-8):

```
BEFORE  exit 1   FAIL: semantic layer gate(s) FAILed: l1_pin_bus_width_actionable_check
AFTER   exit 0   l1_param_bus_width_resolve: bound 4 parametric bus width(s)
                   from declared parameter defaults — x[31:0] (x4 mirrors)
                 l1_pin_bus_width_actionable_check: PASS: 1 bus-confirmed pin(s)
                   all resolve to an actionable integer bit width.
```

Test suites: 33 new pass; pre-existing `test_l1_pin_bus_width_actionable_check`
(16) and the three width-idiom regression suites (46) all still pass.

## Refusals are deliberate

The resolver never invents a width. Unbound parameter, ambiguous binding
across docs, non-arithmetic expression, or an already-resolved pin are
all left alone and reported. An unresolved width still trips the gate,
which is the correct outcome — a WRONG bus width propagates silently
into the netlist, an unresolved one does not.
