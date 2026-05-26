# LDO layout plan — U_Hawaii_EE628 (IHP SG13G2)

> The verified physical layout already exists as a functional region of
> the flat top cell `UHEE628_S2024` (design_data/gds/UHEE628_S2024.gds,
> 171 cells, real KLayout-loadable, SG13G2-DRC/LVS clean upstream). This
> note records the analog-layout discipline expected for the block class;
> the hardmacro LEF (150x200um abstract) is derived for PnR integration.

## Matching / symmetry
- **Error-amplifier diff pair** (M_AMPIN_P / M_AMPIN_N): common-centroid,
  interdigitated A-B-B-A with dummy fingers at both ends so the input
  pair sees identical edge effects -> low input-referred offset.
- **NMOS current mirror** (M_MIRR_A / M_MIRR_B): interdigitated, shared
  centroid, ratioed by integer finger count to hold the mirror accuracy
  that sets the loop gain.
- **Feedback divider** (R_FB_TOP / R_FB_BOT): same-orientation series of
  unit resistors, common-centroid, dummies at the ends; the ratio (not
  absolute value) sets Vout so matching dominates.

## Pass device
- Series-pass PMOS laid out as many parallel fingers with a wide,
  low-Rg gate bus; the extracted .cir shows a W=756.8u hv device on
  IOVDD consistent with this. Multiple parallel fingers reduce on-
  resistance and electromigration on the IOVDD->CORE path.

## Guard rings & isolation
- Full guard ring (substrate ties) around the diff pair and mirror to
  pin local substrate potential and reject digital switching noise from
  the adjacent modulator core.
- Separate analog VSS ring; keep the regulated CORE output on a wide
  Metal4 rail to the modulator it powers.

## Compensation
- Miller cap (cmim) placed adjacent to the pass-gate node, short routing
  to minimise added parasitic pole.

## Evidence anchor
- design_data/gds/UHEE628_S2024.gds (flat verified layout).
- design_data/gds/UHEE628_S2024_extracted.cir (pass + bias devices).
