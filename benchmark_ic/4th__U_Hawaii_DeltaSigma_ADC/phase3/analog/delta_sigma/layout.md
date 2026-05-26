# Delta-Sigma modulator layout plan — U_Hawaii_EE628 (IHP SG13G2)

> Six identical modulator copies exist as functional regions of the flat
> verified top cell UHEE628_S2024 (SG13G2-DRC/LVS clean upstream). This
> note records the analog-layout discipline for the block class; the
> hardmacro LEF abstract is derived for mixed-signal floorplan.

## Matching / symmetry
- **OTA input pair** (M_IN_P / M_IN_N): common-centroid, interdigitated,
  dummy fingers -> low offset so the integrator virtual ground is clean.
- **Load mirror** (M_LOAD_A / M_LOAD_B): shared-centroid interdigitation
  for accurate current balance.
- **Sampling / integrating caps** (C_S / C_INT): unit-cap arrays with a
  common-centroid array layout; the SC transfer accuracy is set by the
  cap ratio, so ratio matching dominates. Dummy caps at array edges.

## Six-copy replication
- The six modulators are laid out as an array; each copy is identical so
  channel-to-channel gain/offset spread is minimised. One copy's CORE
  supply is fed from the LDO region.

## Guard rings & shielding
- Each modulator gets a substrate guard ring; the SC clock lines
  (CK4/CK5/CK6) are shielded from the sensitive integrator nodes.
- VHI/VLO reference rails routed as wide, well-decoupled buses; analog
  VSS kept separate from digital decimation logic.

## Clocking
- Non-overlapping clock generator placed centrally; matched routing to
  the six copies to equalise sampling-instant skew.

## Evidence anchor
- design_data/gds/UHEE628_S2024.gds (flat verified layout, 6 copies).
- design_data/gds/UHEE628_S2024_extracted.cir (IN/OUT/CK/VHI/VLO pins).
