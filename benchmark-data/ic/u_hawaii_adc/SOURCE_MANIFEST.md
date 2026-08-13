# SOURCE_MANIFEST — u_hawaii_adc (UHEE628)

Per `benchmark_clean/METHODOLOGY.md` rule 3: every analog block tagged
`GENERATED` (topology + sizing authored from the L5 spec) or `REUSED-IP`.

**Input = ONLY the curated design docs** at `input/docs/{L1_DATASHEET,L5_ANALOG_SPEC,L9_CONSTRAINTS}.md`.
The upstream EE628 schematic / 3_Real_circuits / fabricated GDS were **NOT read as
input** — the fabricated UHEE628 is the golden oracle for the VERIFY stage ONLY.

## Analog blocks

| Block | Tag | Provenance |
|---|---|---|
| `delta_sigma` (×6) | **GENERATED** | Topology (2nd-order SC CIFB incremental DSM, 1-bit) SELECTED by the designer from L5 Block A (R3). OTA + comparator SPICE (`delta_sigma.sp`, SG13G2 LEVEL=1 standin) authored + SIZED (W/L, L=1u for gain margin) to clear the 48.2 dB incremental-DSM gain floor. Behavioral fixed-point loop + sinc² decimator (`cosim/ds_incremental.v`) authored from the incremental-DSM equations; coefficients (a1=a2=1/4, c1=2) found by closed-loop ENOB optimization. NO upstream netlist copied. |
| `ldo` (×1) | **GENERATED** | Topology (PMOS-pass + NMOS-input 5T OTA + R-divider + Miller) SELECTED by the designer from L5 Block B (R3). SPICE (`ldo.sp`, SG13G2 LEVEL=1 standin) authored + SIZED (pass W=400u, feedback R1=R2 for Vout=1.2 V) to meet Vout/dropout/PSRR/Iq. NO upstream netlist copied. |

**Reused external design IP: NONE (count = 0).** Aim of 100% GENERATED met — both
analog blocks' topology + sizing were authored from the L5 spec; no external
analog netlist/schematic was pulled in.

## Tooling / data (PDK, models)
- IHP SG13G2 PDK (open) — Magic tech + KLayout DRC/LVS decks used as the PROCESS
  KIT (not design IP): real Magic + KLayout SG13G2 sign-off DRC run on our layouts.
- SPICE device models = **DOCUMENTED LEVEL=1 STANDIN** (SG13G2 has no public ngspice
  corner lib) → MODELED, not silicon sign-off. Disclosed in every corner result.

## Digital RTL
- **NONE.** This is an analog-front-end IC: the L5 spec scopes only the analog
  blocks (modulator analog loop + LDO); the 1-bit serial bitstream is the chip
  output and the decimator is out of L5 scope. There is no synthesizable digital
  RTL → the pure-digital flow steps + Pillars 3/4 are honestly N/A.
