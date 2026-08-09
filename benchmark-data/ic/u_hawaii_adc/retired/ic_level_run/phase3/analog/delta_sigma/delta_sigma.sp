* u_hawaii_adc -- delta_sigma modulator CORE (IHP SG13G2) -- GENERATED from L5 Block A
* SC 2nd-order CIFB incremental DSM. This deck holds the transistor-level
* analog CORE that A4 sizes/verifies across PVT:
*   - integrator OTA (telescopic-ish single-stage, NMOS input) : DC gain + bias
*   - regenerative-latch comparator front transconductor : trip behaviour
* The SC switches/caps + decimation are discrete-time / digital and are verified
* by the behavioral mixed-signal cosim (A8/A9), not this DC/AC deck.
*
* HONEST DISCLOSURE: IHP SG13G2 has NO public ngspice corner lib. Models are
* DOCUMENTED LEVEL=1 STANDIN (MOS1) at 130nm-typical params = MODELED, not
* silicon sign-off. Corner = scale VTO/KP (TT/SS/FF) + .temp.

.subckt ds_ota VDD VSS VINP VINN VOUTA VBIAS
* NMOS-input diff pair, PMOS mirror load, NMOS tail current source
* Longer L on input + load devices -> higher ro -> higher DC gain with margin
* over the 48.2 dB incremental-DSM gain floor across SS corner.
Mtail nt VBIAS VSS VSS nmos_sg13 W=8u  L=1.0u
Mn1   nd1 VINP nt VSS nmos_sg13 W=40u L=1.0u
Mn2   VOUTA VINN nt VSS nmos_sg13 W=40u L=1.0u
Mp1   nd1 nd1 VDD VDD pmos_sg13 W=40u L=1.0u
Mp2   VOUTA nd1 VDD VDD pmos_sg13 W=40u L=1.0u
Cload VOUTA VSS 0.5p
.ends ds_ota

* regenerative comparator input transconductor (decision-quality proxy):
* NMOS diff pair into resistive loads -> measures input-referred gain at trip
.subckt ds_comp VDD VSS CINP CINN COUT VBIAS
Mct nct VBIAS VSS VSS nmos_sg13 W=4u L=0.5u
Mc1 ncm CINP nct VSS nmos_sg13 W=10u L=0.35u
Mc2 COUT CINN nct VSS nmos_sg13 W=10u L=0.35u
Rl1 VDD ncm  20k
Rl2 VDD COUT 20k
.ends ds_comp

* ===== SG13G2 LEVEL=1 STANDIN MODELS (MODELED, not silicon sign-off) =====
* LAMBDA set to long-channel-typical (the OTA devices use L=1u; channel-length
* modulation is weaker at longer L). SG13G2-typical 130nm standin values.
.param dvt=0 kpf=1.0
.model nmos_sg13 nmos (LEVEL=1 VTO={0.42+dvt} KP={70u*kpf} GAMMA=0.45
+ LAMBDA=0.03 PHI=0.65 TOX=2.7n CGSO=2e-10 CGDO=2e-10)
.model pmos_sg13 pmos (LEVEL=1 VTO={-0.47-dvt} KP={28u*kpf} GAMMA=0.40
+ LAMBDA=0.04 PHI=0.65 TOX=2.7n CGSO=2e-10 CGDO=2e-10)
