# Delta-Sigma Topology — 2nd-order Incremental DSM (CIFB switched-cap)

Source: bmurmann/EE628, `5_Design/3_Real_circuits` (`template_idsm2`) and the
transistorized `5_Design/4_Layout/Team 2` (`IDSM2_Transistorized_T2`, DRC+LVS clean).
PDK: IHP SG13G2 (low-voltage devices + sg13g2 stdcells for digital glue).

## Architecture
Incremental delta-sigma modulator, 2nd order, reset every N=110 clock cycles:

```
        +-----------+      +-----------+      +-------------+
 vin -->| Stage 1   |----->| Stage 2   |----->| Comparator  |--> dout (bitstream)
        | SC integ. |      | SC integ. |      | regenerative|
        +-----------+      +-----------+      +-------------+
              ^                  ^                   |
            p1/p2 (2-phase non-overlap clk)  <-------+ feedback (vhi/vlo DAC)
                     |
              +-------------+
              | ClockGen    |  template_clkgen: NAND/INV non-overlap generator
              +-------------+
```

- **template_clkgen**: 2-phase non-overlapping clock + early phases (p1/p1e/p2/p2e)
  built from sg13g2 stdcell INV/NAND.
- **template_stage x2**: switched-capacitor integrators (sampling + integrating caps,
  bottom-plate sampling switches), 1-bit feedback DAC selecting `vhi`(0.9V)/`vlo`(0.3V).
- **template_comp**: regenerative latched comparator producing the 1-bit `dout`.

## Operating point (real ngspice PSP103 sim, tb_idsm2.spice, N=110, fclk=50 MHz)
- Vdd_ana = 1.2 V, Vin sweep 0.35–0.85 V (11 points).
- Measured supply currents: Iavg_ana ≈ 69.6 uA, Iavg_dig ≈ 254 uA.
- Integrator outputs vout1/vout2 ramp within rails; dout density tracks Vin
  (e.g. high-input sweep → dout high-fraction ≈ 0.95).

## Why incremental
Incremental (reset-per-conversion) DSM gives absolute, offset-free conversion for
instrumentation — appropriate for a multi-channel sensor front-end. 2nd order +
OSR=110 trades modest clock rate for resolution without a high-order loop filter.
