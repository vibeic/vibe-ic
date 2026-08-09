* u_hawaii_adc -- LDO (IHP SG13G2) -- GENERATED from L5 Block B spec
* Topology: PMOS series-pass + NMOS-input 5T OTA + resistor fb + Miller comp
* HONEST TOOL DISCLOSURE: IHP SG13G2 has NO public ngspice corner library.
*   The MOS models below are DOCUMENTED LEVEL=1 STANDIN models (MOS1) whose
*   VTO/KP/GAMMA/LAMBDA are set to SG13G2-typical 130nm values. This is
*   MODELED, NOT silicon sign-off. Corner = scale VTO/KP per TT/SS/FF.
*
* Subckt only here; testbench + .param corner knobs injected by the sweep deck.

.subckt ldo IOVDD VSS VREF VOUT
* --- error-amp OTA (NMOS input diff pair, PMOS mirror load) ---
* tail current source
Mtail ntail nbias VSS VSS nmos_sg13 W=4u  L=0.5u
Vbias_int nbias VSS DC 0.6
* input diff pair (polarity for PMOS-pass negative feedback):
*   VFB drives the diode-side device (drain nd1); VREF drives the
*   mirror-output side (drain ndo = pass gate). Vout up -> VFB up ->
*   nd1 down -> ndo up -> PMOS pass off -> Vout down (neg feedback).
Mn1 nd1 VFB   ntail VSS nmos_sg13 W=8u L=0.5u
Mn2 ndo VREF  ntail VSS nmos_sg13 W=8u L=0.5u
* PMOS active-mirror load
Mp3 nd1 nd1 IOVDD IOVDD pmos_sg13 W=8u L=0.5u
Mp4 ndo nd1 IOVDD IOVDD pmos_sg13 W=8u L=0.5u
* --- PMOS series pass device, gate = OTA output (ndo) ---
Mpass VOUT ndo IOVDD IOVDD pmos_sg13 W=400u L=0.35u
* Miller compensation
Cc ndo VOUT 2p
* feedback divider: Vout=Vref*(1+R1/R2); Vref=0.6 -> Vout=1.2 (R1=R2)
R1 VOUT VFB 100k
R2 VFB  VSS 100k
* output load cap
Cl VOUT VSS 10p
.ends ldo

* ===== SG13G2 LEVEL=1 STANDIN MODELS (MODELED, not silicon sign-off) =====
* Corner knobs: dvt (Vth shift), kpf (KP factor). Injected via .param.
.param dvt=0 kpf=1.0
.model nmos_sg13 nmos (LEVEL=1 VTO={0.42+dvt} KP={70u*kpf} GAMMA=0.45
+ LAMBDA=0.06 PHI=0.65 TOX=2.7n CGSO=2e-10 CGDO=2e-10)
.model pmos_sg13 pmos (LEVEL=1 VTO={-0.47-dvt} KP={28u*kpf} GAMMA=0.40
+ LAMBDA=0.08 PHI=0.65 TOX=2.7n CGSO=2e-10 CGDO=2e-10)
