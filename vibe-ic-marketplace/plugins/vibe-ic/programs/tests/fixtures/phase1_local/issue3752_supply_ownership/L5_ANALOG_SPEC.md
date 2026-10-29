| Vin (diff) | 1.0 | 0–1.2 | V | input range vs VHI/VLO |
| Vref | 1.0 | 0.8–1.2 | V | reference (VHI−VLO) |
| Vdd (core) | 1.2 | 1.1–1.3 | V | core supply (one copy from the LDO) |
| fclk | 1.0 | 0.1–10 | MHz | modulator clock (CK4/5/6) (est) |
| output | 1-bit serial (OUTn / dout) | — | — | digital bitstream per channel |

R3: SC or CT, single-loop or otherwise — designer's choice, as long as ENOB/OSR/range met.

## Block B — `ldo` : low-dropout regulator (×1, supplies one modulator core)
| Spec | Target | Range | Unit | Note |
|---|---|---|---|---|
| Vout | 1.2 | 1.1–1.3 | V | regulated CORE for the LDO-fed modulator copy |
| Iout | 0.5 | 0.1–1.0 | mA | modulator quiescent + dynamic budget (est) |
| Vin | 1.8 | 1.6–2.0 | V | IOVDD (confirmed top pin) |
| Dropout | ≤ 0.5 | — | V | headroom (1.8 IOVDD − 1.2 CORE = 0.6 V available) |
