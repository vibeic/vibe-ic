# Regulator

## Block B - a regulator that supplies the core
| Spec | Target | Range | Unit | Note |
|---|---|---|---|---|
| Vout | 1.2 | 1.1-1.3 | V | regulated output |
| Iout | 0.5 | 0.1-1.0 | mA | budget |
| Dropout | 0.5 | - | V | headroom (1.8 IOVDD - 1.2 CORE = 0.6 V available) |
| PSRR | 40 | - | dB | rejection |
| Iq | 50 | - | uA | quiescent |
| Load reg | best-effort | - | - | report |
| Line reg | best-effort | - | - | report |
