* delta_sigma quantizer — 1-bit clocked comparator (StrongARM-style: diff pair + cross-coupled
* regenerative latch + reset/equalize switches), sky130. Transient: two reset->evaluate cycles,
* one with vinp>vinn (expect oa wins) and one with vinp<vinn (expect ob wins) -> rail-to-rail.
.option scale=1u
.lib /foss/pdks/sky130A/libs.tech/ngspice/sky130.lib.spice tt

v_vdd vdd 0 1.2

* tail enable clock: low = reset (tail off), high = evaluate (tail on)
v_clk clk 0 pulse(0 1.2 0n 1n 1n 200n 500n)
* differential input: first eval window vinp=0.65/vinn=0.55 ; second flips
v_inp inp 0 pwl(0 0.65  490n 0.65  500n 0.55  1000n 0.55)
v_inn inn 0 pwl(0 0.55  490n 0.55  500n 0.65  1000n 0.65)

* tail switch gated by clk
xmt ntail clk 0 0 sky130_fd_pr__nfet_01v8 w=16 l=0.5

* NMOS input differential pair -> nodes oa / ob
xi1 oa inp ntail 0 sky130_fd_pr__nfet_01v8 w=16 l=0.5
xi2 ob inn ntail 0 sky130_fd_pr__nfet_01v8 w=16 l=0.5
* cross-coupled PMOS latch (regenerative load)
xl1 oa ob vdd vdd sky130_fd_pr__pfet_01v8 w=8 l=0.5
xl2 ob oa vdd vdd sky130_fd_pr__pfet_01v8 w=8 l=0.5
* reset/equalize PMOS pre-charge: when clk low, pull oa/ob to vdd (reset state)
xr1 oa clk vdd vdd sky130_fd_pr__pfet_01v8 w=4 l=0.5
xr2 ob clk vdd vdd sky130_fd_pr__pfet_01v8 w=4 l=0.5

.control
tran 1n 1000n
* sample the decision near the end of each evaluate window
meas tran oa_win1 find v(oa) at=480n
meas tran ob_win1 find v(ob) at=480n
meas tran oa_win2 find v(oa) at=980n
meas tran ob_win2 find v(ob) at=980n
echo "MEAS_CMP done"
wrdata /foss/designs/u_hawaii_adc_v0125_rerun/phase3/analog/delta_sigma/cmp_tran.dat v(oa) v(ob) v(clk)
.endc
.end
