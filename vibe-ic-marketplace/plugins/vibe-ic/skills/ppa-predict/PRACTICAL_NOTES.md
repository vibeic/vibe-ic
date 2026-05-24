# PPA Predict — Practical Notes from GF180MCU Synthesis

**Added**: 2026-04-07 from actual Yosys + OpenROAD runs

## GF180MCU 180nm Reference Numbers

Use these as calibration points for PPA prediction on GF180:

### SN74HC163 (4-bit synchronous counter)
- **Cells**: 25 (4 FFs + 21 comb)
- **Area**: 604 µm²
- **Die**: 45 × 45 µm
- **Fmax**: >50 MHz (slack +196ns @ 5MHz)
- **Utilization**: 56%

### ~2.7k-cell digital pilot (bus protocol controller)
- **Cells**: 2,693 (95 FFs in cmd_processor alone)
- **Area**: 89,176 µm²
- **Die**: 492 × 492 µm
- **Fmax**: >50 MHz (slack +184ns @ 5MHz)
- **Utilization**: 40%
- **Dominant module**: OTP controller (64% of area — 47 bytes stored as FFs)

## Rules of Thumb for GF180 Area Estimation

- 1 DFF (dfrtp_1): ~25 µm²
- 1 basic gate (nand2, nor2): ~7-10 µm²
- 1 complex gate (a21oi, a31o): ~6-9 µm²
- 1 byte of register storage: ~200 µm² (8 FFs)
- 1 byte of OTP as FFs: ~200 µm² (should use IP macro in production)

## Area Estimation Formula

```
Area ≈ (N_ff × 25 + N_comb × 8) µm²
Die_side ≈ sqrt(Area / utilization) µm
```

Where `utilization` is typically 0.4-0.6 for GF180.

## Key Insight: OTP/Memory Dominates

In the pilot, the OTP controller used 64% of area because 47 bytes of OTP were modeled as flip-flops. In real silicon:
- Actual OTP IP: ~10-20× smaller
- SRAM macro: ~50× smaller per bit than FF
- Always flag memory arrays as the dominant PPA factor
