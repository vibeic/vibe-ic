# IC Expert Agent Q-bank (K2)

Per-fact question library with variants at three user expertise levels plus
follow-up strategies. Organised by class then by layer.

## File layout

```
qbank/
├── README.md                    # this
├── any-ic_L1.yaml               # root-class facts (every IC has these)
├── any-ic_L2.yaml               # functional/performance requirements
├── any-ic_L5.yaml               # analog-digital interfaces + timing notes
├── any-ic_L6.yaml               # submodule control logic
├── any-ic_L7.yaml               # test modes + debug hooks
├── any-ic_L8.yaml               # reset timing
├── any-ic_L8R.yaml              # clock frequency
├── any-ic_L9.yaml               # DTOP + submodule wiring
├── protocol-ic_L3.yaml          # protocol framing + command set
├── protocol-ic_L4.yaml          # logical control-register map
├── protocol-ic_L8.yaml          # bit / wake / response timing
├── protocol-ic_L8R.yaml         # (derived) bit-period cycles, CRC mirror
├── cable-side-id-ic_L1.yaml     # electrical chars + pinout
├── cable-side-id-ic_L4.yaml     # 128x8 OTP map
├── cable-side-id-ic_L6.yaml     # MAC/RX/OTP/CC submodule FSMs
├── cable-side-id-ic_L7.yaml     # USB-HID tester test sequence
├── cable-side-id-ic_L8.yaml     # break + POR-to-wake-ready timing
├── apb-peripheral_L1.yaml       # APB spec/addr/data
├── apb-peripheral_L2.yaml       # clock/reset/wait states
├── bus-controller_L1.yaml       # protocol family + topology
├── bus-controller_L2.yaml       # widths, slave/master count
├── crypto-engine_L1.yaml        # algorithm + block/key/digest widths
├── crypto-engine_L2.yaml        # rounds, modes, padding
├── memory-controller_L1.yaml    # memory type + JEDEC standard
├── memory-controller_L2.yaml    # data/addr width, user/PHY interface
├── processor_L1.yaml            # ISA base + extensions + regfile
├── processor_L2.yaml            # pipeline depth + issue model
├── soc-harness_L1.yaml          # variant + PDK + license
├── soc-harness_L2.yaml          # pads + user-project wires + power rails
├── uart-peripheral_L1.yaml      # word length + framing + parity + flow
└── uart-peripheral_L2.yaml      # oversampling + baud + prescale style
```

## Entry schema

```yaml
fact: pinout.VBUS
levels:
  expert:
    - "VBUS pin role?"
  intermediate:
    - "How is the main supply wired to the chip?"
    - "Power pin description?"
  beginner:
    - "Where does the chip get its power from?"
follow_ups:
  - if_user_says: ["usb", "5v"]
    respond_with_default: "Supply in (2.6-6.8V)"
  - if_ambiguous: ["I don't know"]
    defer_to_default: true
```

## Rules

1. At least one expert and one intermediate variant per fact.
2. Beginner variant optional — if the fact is inherently technical,
   mark `beginner: []` and PM uses the default.
3. Every fact whose `provenance` is `defaulted_industry_std` or
   `defaulted_from_reference` can have `levels: {expert: [], intermediate: [], beginner: []}`
   — PM won't ask; IC Expert applies default silently.
4. Follow-up fragments must not leak jargon the user wouldn't understand at that level.

## Fallback rule (v0.74 — previously implicit)

When the IC Expert Agent looks up `<class>_<layer>.yaml` and the file doesn't
exist, walk the K1 template's `parent:` chain:

```
<class>.yaml `parent:` → <parent>_<layer>.yaml
                      → <grandparent>_<layer>.yaml
                      → ...
                      → any-ic_<layer>.yaml
                      → IC Expert applies K3 default silently
```

Example: for `cable-side-id-ic` at L2, PM looks up
`cable-side-id-ic_L2.yaml` (missing prior to v0.74, present v0.74+) →
falls back to `protocol-ic_L2.yaml` → then `digital-ic_L2.yaml`
(empty stub — no facts) → then `any-ic_L2.yaml` (present).

Chain continuity is verified by `tools/phase1_engine/qbank_coverage_check.py`.
Run that script any time you add / rename a K1 template's `parent:` to
catch dead-end (class, layer) combos early.

Some (class, layer) slots are **intentionally empty** — e.g., L3 for
analog-front-end / apb-peripheral / bus-controller / crypto-engine /
memory-controller / processor / soc-harness. These classes don't speak
a serial protocol, so no L3 qbank is needed at any level of the chain.
The coverage-check script will flag these as unreachable, which is
informational — not a bug. Use `--fail-on-unreachable` only in CI for
classes that should have full coverage.
