* LDO Monte-Carlo (in-.control loop, reset re-samples agauss mismatch) — real MC demo
.option scale=1u
.param mc_mm_switch=1
.param mc_pr_switch=1
.lib /foss/pdks/sky130A/libs.tech/ngspice/sky130.lib.spice tt
.param m_pass=160
v_vdd vdd 0 1.8
v_vref vref 0 0.6
xmn_b nbias nbias 0 0 sky130_fd_pr__nfet_01v8 w=2 l=2
r_ibias vdd nbias 600k
xmp_pass vout vg vdd vdd sky130_fd_pr__pfet_01v8 w=5 l=0.5 m='m_pass'
xmn_tail ntail nbias 0 0 sky130_fd_pr__nfet_01v8 w=4 l=2
xmn1 nd1 vfb  ntail 0 sky130_fd_pr__nfet_01v8 w=8 l=1
xmn2 vg  vref ntail 0 sky130_fd_pr__nfet_01v8 w=8 l=1
xmp1 nd1 nd1 vdd vdd sky130_fd_pr__pfet_01v8 w=4 l=1
xmp2 vg  nd1 vdd vdd sky130_fd_pr__pfet_01v8 w=4 l=1
cc vg vout 5p
r1 vout vfb 8k
r2 vfb 0 8k
r_load vout 0 1k
.control
let mc_runs = 30
let run = 0
dowhile run < mc_runs
  reset
  op
  let vo = v(vout)
  echo "MCVOUT" $&run $&vo
  let run = run + 1
end
.endc
.end
