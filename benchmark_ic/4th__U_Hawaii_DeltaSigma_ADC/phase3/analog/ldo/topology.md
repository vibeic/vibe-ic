# LDO topology — U_Hawaii_EE628 (block-class: low-dropout regulator)

> Source: estimated topology consistent with an IHP SG13G2 1.8V (IOVDD)
> -> ~1.2V (CORE) LDO serving one of the six delta-sigma modulator
> copies. The open-source EE 628 dataset ships only a flat top-cell GDS
> + KLayout-extracted chip-level netlist; the LDO sub-block is not
> separately published, so this records the *expected* architecture
> for the block class rather than a reverse-engineered schematic.

## Topology selected
Series-pass PMOS (low-dropout) regulator with a single-stage error
amplifier and Miller compensation.

## Stages
1. **Reference**: bandgap-derived `vref ~ 1.0 V` (shared with the
   modulator VREF pad — `PAD|VREF` is a real top pin).
2. **Error amplifier**: single-stage differential pair (PMOS input
   pair, NMOS current-mirror load) driving the gate of the pass device.
3. **Pass device**: PMOS common-source pass transistor from IOVDD
   (1.8 V) to the regulated CORE node (~1.2 V). The extracted .cir
   shows a wide `sg13_hv_nmos W=756.8u` device on IOVDD consistent
   with a pass-class transistor.
4. **Feedback**: resistor divider from VOUT back to the inverting input;
   sets `Vout = Vref * (1 + R1/R2)`.
5. **Compensation**: Miller capacitor across the pass transistor.
6. **Bias**: NMOS current mirror providing tail current to the diff pair.

## Primitives (chip-AGNOSTIC vocabulary)
- pmos pass transistor (common-source)
- pmos differential pair (op-amp input stage)
- nmos current mirror (tail bias + load mirror)
- mim/cmim capacitor (Miller compensation)
- resistor divider feedback network
- single-stage open-loop amplifier, closed-loop with feedback

## Open-loop / closed-loop
Error-amplifier open-loop gain sets the dominant pole; closed loop sets
DC Vout. Phase-margin design target >= 60 deg with the load capacitor
seen by the modulator.

## Evidence anchor
- `design_data/gds/UHEE628_S2024_extracted.cir` — `PAD|VLDO`, `PAD|VREF`,
  `IOVDD` pins and a W=756.8u hv pass-class device.
- `input/docs/README.md` — "one of them is powered by an an LDO".
