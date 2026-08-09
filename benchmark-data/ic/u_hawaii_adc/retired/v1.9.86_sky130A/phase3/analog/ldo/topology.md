# Topology — ldo (u_hawaii_adc, IHP SG13G2)

GENERATED from L5 Block B spec (analog-topology-select). Authored to meet
Vout=1.2 V, Vin=1.8 V (IOVDD), dropout <= 0.5 V, PSRR >= 40 dB, Iq <= 50 uA,
Iout 0.1-1.0 mA. R3: topology is the designer's choice.

## Selected: PMOS-pass LDO — NMOS-input 5T OTA error amp + PMOS series pass + resistor feedback + Miller compensation

Rationale (vs the candidates below): with only 0.6 V of headroom
(1.8 IOVDD - 1.2 CORE) a **PMOS series-pass** device drops the least
(Vsd_sat ~ 0.1-0.2 V) so dropout <= 0.5 V is comfortably met — an NMOS
source-follower pass would need Vgs+Vov above the 1.8 V rail and fails the
headroom budget. The error amp uses an **NMOS-input differential pair** so its
input common mode sits comfortably around the 0.6 V feedback-divider node
(Vth_n ~ 0.42 V at SG13G2 lv nfet leaves enough Vov).

## Schematic (text)

```
            IOVDD(1.8) ──────┬───────────────┬──────── Mpass(PMOS, W large)
                             │               │            │
                   Mp3 ──────┤  Mp4          │            ├── Vout(1.2) ── CL, Iload
            (PMOS mirror load of OTA)        │            │
                   │          │              │           R1
        Mn1(NMOS)──┤      ├───Mn2(NMOS)   gate of Mpass   ├── Vfb ── (-) OTA input
        Vref(0.6)  │      │   Vfb          driven by OTA   R2
                   └──Mtail(NMOS, Ibias)── out             │
                             │                            VSS
                            VSS
   Cc (Miller) from Vout-node region to OTA output for stability.
```

## Device roles
| Device | Role | Key constraint |
|--------|------|----------------|
| Mn1,Mn2 | NMOS input diff pair | Vgs > Vth_n(~0.42) + Vov; CM ~ 0.6 V |
| Mp3,Mp4 | PMOS active-mirror load | sets OTA gain |
| Mtail   | NMOS tail current source | Ibias ~ few uA (keeps Iq <= 50 uA) |
| Mpass   | PMOS series pass | low Vsd dropout; sized for 1 mA Iout |
| R1,R2   | feedback divider | Vout = Vref*(1+R1/R2); Vref=0.6 -> Vout=1.2 |
| Cc      | Miller compensation cap | dominant-pole split for phase margin |

## Trade-off analysis
| Candidate | Pros | Cons | Verdict |
|-----------|------|------|---------|
| PMOS-pass + NMOS-input OTA | lowest dropout, meets 0.6 V headroom, good PSRR with cascoded mirror | needs Miller comp | **Selected** |
| NMOS source-follower pass | inherently good PSRR | Vgs+Vov > 0.6 V headroom -> dropout FAILS | Rejected |
| PMOS-input OTA | lower 1/f noise | input CM near 0.6 V too low for PMOS pair on 1.8 V | Rejected |

## PDK constraints applied (IHP SG13G2)
- Vth_n ~ 0.42 V, Vth_p ~ 0.47 V (lv devices); HV `sg13_hv_*` available for the
  1.8 V pass path if reliability margin needed.
- 130 nm BiCMOS — BJTs available but not required here.
- **Tool disclosure:** SG13G2 has NO public ngspice corner lib -> corner sims
  use documented LEVEL=1 standin MOS models = MODELED, not silicon sign-off.
