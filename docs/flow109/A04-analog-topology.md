# A04 source-authorized analog topology component

`--entry-step A04 --exit-step A04` runs the existing
`analog_a2_topology_emit` and its retained topology reader. The deterministic
library is a renderer, not an approval oracle. `input/flow109/A04.json` must
bind an independently approved analog-design declaration, positive gain,
noise and power budgets, typed model/corner scope, structured per-block specs,
and a current passing A02 component receipt. Missing or stale inputs refuse
before production.

The approved block row names the exact circuit class, selected topology and
required device-role population. The adapter rejects any mismatch with the
emitted IR, any honest library gap, a pre-existing topology not freshly
emitted by the retained producer, or a retained-checker failure. A successful
component freezes the exact topology artifacts under
`adopted/analog_topology/topology_freeze.json`.

This is a bounded A04 component result. Performance, statistical/PVT
coverage, G1-G9, full Flow 109 qualification and benchmark PASS remain
`NOT_MEASURED`.

## Structured allocations

`blocks[].budgets` may be a nonempty tree keyed by budget, sub-circuit and
condition. Labels are opaque: the reader does not assume amplifier names,
temperature labels, delay selections or a fixed set of budget categories.
Every leaf is exactly `{"status":"BOUND","limit":50.0,"unit":"dB"}`:
the allocation is a finite, positive number, not a measured performance value.
An absent binding, empty subtree, mixed leaf/subtree, boolean, nonfinite number
or missing unit refuses as `A04_BUDGET_UNBOUND`. The metric consumer treats
this refusal as FAIL. Existing scalar gain/noise/power leaves still work.

For example, `budgets.gain.amplifier_a.D=0` and
`budgets.gain.amplifier_a.D=1` are separate leaves. Neither condition is
silently selected or discarded. The approved requirement document's
`limits.<block>` and `units.<block>` must have the same complete leaf paths;
limits end in `{min, max}` bounds and units end in strings. Each leaf is
compared independently with the existing `within_declared_bounds` operator.
Missing/extra bound paths cannot PASS; a measured violation remains FAIL.

## Declared loop structure in topology IR

The fact reader consumes `topology.json.loop_declaration` (schema 1), the
producer contract documented in `docs/analog-ciff.md`, as an explicit IR
declaration. It does not interpret the topology description, circuit class,
device/net names, inferred stage names or an approved requirement as evidence.
These fields are the consumer contract when a producer supplies loop IR:

```json
{
  "loop_declaration": {
    "schema": 1,
    "family": "CIFF",
    "order": 3,
    "paths": [
      {"kind":"feedforward","source":"node_u","destination":"node_z","gain":1.0,"capacitor":"cap_a"},
      {"kind":"dac","source":"node_z","destination":"node_v","gain":-1.0,"capacitor":"cap_b","destination_stage":1,"delay_clocks":0}
    ],
    "dac_stages": [1],
    "quantizer_levels": 2,
    "D": 0,
    "k0_path": null
  }
}
```

This excerpt contains only the fields this reader uses; the full producer IR
also contains coefficient vectors, state-space data and normalization.
`family` yields `loop_family`; positive integer `order` yields `loop_order`.
`paths` objects have explicit `kind`, nonblank `source`/`destination` IDs,
`capacitor` ID and finite numeric `gain`. The reader classifies the declared
`feedforward`/`input_feedforward` kinds as feed-forward paths, and
`dac`/`k0`/`zero_feedback` kinds as feedback paths. It never classifies a path
from its source, destination or capacitor name.

DAC paths require `destination_stage` within the declared order and
nonnegative integer `delay_clocks`. A `k0` path requires integer
`delay_clocks=1`. A valid explicit `k0_path` is included once, even when the
producer also lists it in `paths`. Numeric `k0`, `a/b/c` or family names do
not substitute for a missing path declaration.

The resulting kinds are `feedforward_paths`/`feedback_paths` plus one
`feedforward_path`/`feedback_path` per object. Values are compact JSON with
sorted object keys; list order remains as declared. An explicitly empty path
list records declared absence; an absent field does not.

`dac_stages` contains unique one-based integers within the declared order. It
yield sorted compact-JSON `dac_injection_stages` and individual
`dac_injection_stage` facts. `quantizer_levels` is an integer count of at least
two. A power-of-two count additionally yields `quantizer_bits`.
`D` is a nonnegative integer
and yields `timing_D` (for example `"0"`) and `feedback_delay` (`"D=0"`).
Integer fields do not accept booleans.

Missing or malformed fields emit no corresponding facts. Required items that
cannot be shown remain `NOT_OBSERVED` in `topology_constraints.observations`
and fail required coverage. Coefficients, capacitor values, decoder behavior,
bench amplitude and conditional alternatives are not invented from these
fields. This change provides a consumer contract, not a loop producer or native
qualification. Until the producer emits the declared fields, their constraints
remain unobserved.
