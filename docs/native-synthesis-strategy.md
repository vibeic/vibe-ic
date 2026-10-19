# Declared native synthesis strategy

`phase3/librelane_switch.json` is the existing implementation namespace. Its
optional `synthesis_levers` object selects only `SYNTH_STRATEGY`, using the nine
native values already enumerated by `_ppa.synthesis.STRATEGIES`: AREA 0–3 and
DELAY 0–4. For example:

```json
{"synthesis_levers":{"SYNTH_STRATEGY":"DELAY 2"}}
```

`librelane_contract.emit_synthesis_config` carries that declaration and its
exact source into the normal config/provenance. The existing native loader,
Yosys/header/checkers, statistics, area, handoff, LEC and Step10/PnR consumers
remain the production path. Present declarations on direct/dual synthesis
refuse rather than being silently ignored. Invalid objects, unknown keys,
wrong value types and unsupported strategy values refuse; this is not an
arbitrary LIB, corner, clock or frontend overlay.

When absent, the emitter adds no strategy key and LibreLane retains its
existing effective default AREA 0. An explicit empty object also requests no
override, but its presence is retained. A present `AREA 0` declaration is an
explicit engineering choice even though it yields the same effective value.

The native invocation fingerprint and receipt record the exact raw
`synthesis_levers` object only when present. The existing
`synth_inputs.json.librelane_synthesis` binding copies that consumed authority
from the native receipt; it cannot backfill an unconsumed declaration. The receipt-covered native
`config.json.SYNTH_STRATEGY` separately records the effective value. The
ordinary handoff consumer checks both current raw presence/value and native
effective strategy: changing or removing a declaration invalidates the old
handoff, including explicit AREA 0 removal. Existing default-only receipts
with no declaration retain compatibility. Other unrelated switch keys are
not made part of this strategy declaration.

The post-map child retains its original Yosys parent and this same parent
binding. A strategy selection cannot publish an exploratory arm or bypass
the existing LEC, area, timing or currentness checks. Native config acceptance
and a changed ABC script are not timing improvement. Same-scope measured
timing and LEC remain required; SS still negative in the motivating AES
experiment. No timing exception or clock-period change is introduced.
