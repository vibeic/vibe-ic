# Topology — adc (incremental-ΔΣ ADC analog front-end wrapper)

_AI-authored from L1_DATASHEET.md + L5_ANALOG_SPEC.md via `analog-topology-select`.
sky130A PDK; core 1.2 V from the LDO._

## Scope split (per L5)
The `adc` block is the **incremental-ADC channel wrapper**. Its analog content is the
modulator analog front-end; the **decimation counter / serial read-out is DIGITAL** and is
synthesised on the digital track (out of analog scope per L5). So the analog topology of
`adc` = the same SC ΔΣ front-end as `delta_sigma`, instanced once with the reference and
clocking brought to the channel boundary.

## Selected: SC ΔΣ analog front-end = SC integrator(s) + 1-bit comparator quantizer + 1-bit feedback DAC

```
   IN (diff, ±Vin) ─►[ SC sampler ]─►[ INTEGRATOR (OTA + Cs/Ci) ]─►[ COMPARATOR ]─► dout (1-bit)
                       φ1/φ2 switch                                       │
   VHI/VLO (±Vref) ─►[ 1-bit feedback DAC switches ]──────────────────────┘
                                                              │
                                              (digital decimation counter → OUTn — DIGITAL, out of scope)
```

## Device roles (transistor / primitive level)
| Device | Role | Key constraint |
|--------|------|----------------|
| M1,M2 (nfet_01v8) | front-end OTA **NMOS input differential pair** | wide CM at 1.2 V core |
| M3,M4 (pfet_01v8) | **PMOS current-mirror load** | integrator DC gain |
| M5 (nfet_01v8) | **tail current source / bias** | saturation |
| M6 (pfet_01v8) | **common-source output stage** | loop gain |
| Cc | **Miller compensation capacitor** | dominant pole / stability |
| Mc1..Mc4 + cross-coupled latch | **1-bit comparator** (quantizer) | rail-to-rail digital decision |
| Cs, Ci | sampling / integrating **capacitors** | coefficient = cap ratio |
| Sφ1,Sφ2,Sdac (nfet/pfet) | two-phase + feedback-DAC **switches** | low Ron, charge-injection control |

## Trade-off analysis
| Candidate | Pros | Cons | Verdict |
|-----------|------|------|---------|
| Reuse the 2nd-order SC ΔΣ modulator front-end | matches L1 ("array of incremental ΔΣ channels"); one validated core | none for this product | **Selected** |
| SAR front-end | fast | wrong converter class (spec says incremental ΔΣ) | Rejected |
| Pipelined | high throughput | area / wrong class | Rejected |

## PDK constraints applied
- Same as delta_sigma: NMOS-input OTA, 1.8 V devices at 1.2 V core, cap-ratio coefficients,
  no inductors.

## Verifiable-in-container vs system-level
- **Verifiable (A4, real ngspice):** front-end OTA op + open-loop gain, integrator step
  settling, comparator decision.
- **System-level (NOT closed here):** end-to-end ENOB ≥ 14 / SNDR with the digital
  decimation filter — needs mixed-signal cosim over a full conversion window.
  Documented unverified in corner_results.json.
