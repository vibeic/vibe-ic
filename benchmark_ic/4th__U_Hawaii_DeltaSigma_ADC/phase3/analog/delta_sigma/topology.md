# Delta-Sigma modulator topology — U_Hawaii_EE628

> Source: estimated topology for an incremental delta-sigma modulator
> (6 copies in the chip). The open-source EE 628 dataset ships a flat
> top-cell GDS + chip-level extracted netlist only; per-modulator
> sub-cells are not separately published. This records the *expected*
> incremental-DSM architecture for the block class.

## Topology selected
Second-order (CIFB — cascade of integrators, feedback) incremental
delta-sigma modulator with a 1-bit quantizer, followed by an off-chip
or on-chip digital decimation/counter for the incremental conversion.

## Stages
1. **Input sampling**: switched-capacitor input network sampling
   `IN[1:6]|PAD` against the `PAD|VHI` / `PAD|VLO` reference rails.
2. **Integrator 1**: SC integrator (op-amp + sampling/feedback caps).
3. **Integrator 2**: second SC integrator (2nd-order loop filter).
4. **Quantizer**: 1-bit comparator clocked by `CK4/CK5/CK6`.
5. **Feedback DAC**: 1-bit cap DAC steering VHI/VLO back to integrator 1.
6. **Decimation**: incremental counter accumulating the bitstream over
   OSR cycles; result emitted on `OUT[1:6]` / serial `dout`.

## Primitives (chip-AGNOSTIC vocabulary)
- switched-capacitor integrator (op-amp + sampling caps)
- 1-bit comparator / quantizer
- 1-bit feedback DAC (cap-steered)
- non-overlapping clock generator (CK4/5/6)
- digital decimation counter

## Reset / incremental behaviour
Incremental DSM resets its integrators each conversion and integrates
for a fixed OSR number of clocks, giving a deterministic, settled DC
conversion (well suited to instrumentation, the EE628 use-case).

## Evidence anchor
- `design_data/gds/UHEE628_S2024_extracted.cir` — `IN1..IN6|PAD` inputs,
  `OUT1..OUT6` outputs, `CK4/CK5/CK6` clocks, `PAD|VHI`/`PAD|VLO`
  reference, `dout` serial pin.
- `input/docs/README.md` — "six copies of an incremental delta-sigma
  modulator".
