# 20 candidate benchmark ICs (corpus expansion, sourced 2026-06-01)

Sourced by a 6-agent research workflow; adversarially verified. Deduped vs the 11 corpus families.

**Verify verdict:** NEEDS_FIX — all 20 repos are real and permissive, but gemmini (#12) ships zero RTL (Chisel/Scala only) and the SAR-ADC (#20) provenance is misattributed to efabless.

**Class distribution:** digital_arithmetic_primitive: 8 (poly1305, modexp, Vyges FFT, dawsonjon FPU, PULP div/sqrt, thasti FFT, R2FFT, Gemmini); digital_cmd_driven: 5 (aes, sha3, chacha, prince, apb_adv_timer); serial_peripheral_protocol: 4 (verilog-uart, verilog-i2c, usb_cdc, CTU CAN FD); bus_interconnect_protocol: 2 (verilog-ethernet, wb2axip); analog_mixed_signal: 1 (SKY130 SAR-ADC); processor_cpu: 0. Total = 20. RISC-V/CPU = 0 (well under the <=4 cap; corpus is already CPU-heavy so this batch is 100% crypto/DSP/protocol/mixed-signal).

| # | IC | ic_class | license | TB | source |
|---|---|---|---|---|---|
| 1 | secworks/aes (AES-128/256 block cipher) | digital_cmd_driven | BSD-2-Clause | yes | github.com/secworks/aes |
| 2 | freecores/sha3 (SHA-3 / Keccak hash) | digital_cmd_driven | Apache-2.0 | partial | github.com/freecores/sha3 (OpenCores origin) |
| 3 | secworks/chacha (ChaCha20 stream cipher) | digital_cmd_driven | BSD-2-Clause | yes | github.com/secworks/chacha |
| 4 | secworks/poly1305 (Poly1305 MAC) | digital_arithmetic_primitive | BSD-2-Clause | yes | github.com/secworks/poly1305 |
| 5 | secworks/modexp (RSA / DH modular exponentiation) | digital_arithmetic_primitive | BSD-2-Clause | yes | github.com/secworks/modexp |
| 6 | secworks/prince (PRINCE lightweight block cipher) | digital_cmd_driven | BSD-2-Clause | yes | github.com/secworks/prince |
| 7 | Vyges FFT IP (fast-fourier-transform-ip) | digital_arithmetic_primitive | Apache-2.0 | yes | github.com/vyges/fast-fourier-transform-ip |
| 8 | dawsonjon FPU (IEEE-754 add/mul/div + convert) | digital_arithmetic_primitive | MIT | yes | github.com/dawsonjon/fpu |
| 9 | PULP fpu_div_sqrt_mvp (FP divide / square-root unit) | digital_arithmetic_primitive | Solderpad HL v0.51 (Apache-based, permissive) | partial | github.com/pulp-platform/fpu_div_sqrt_mvp |
| 10 | thasti FFT (R2SDF pipelined FFT) | digital_arithmetic_primitive | Solderpad HL v2.0 (Apache-derived, permissive) | yes | github.com/thasti/fft |
| 11 | R2FFT (synthesizable radix-2 FFT/IFFT) | digital_arithmetic_primitive | BSD-3-Clause | yes | github.com/yoonisi/R2FFT |
| 12 | Gemmini (systolic-array GEMM accelerator) | digital_arithmetic_primitive | BSD-3-Clause | yes | github.com/ucb-bar/gemmini |
| 13 | alexforencich/verilog-uart (UART <-> AXI-Stream) | serial_peripheral_protocol | MIT | yes | github.com/alexforencich/verilog-uart |
| 14 | alexforencich/verilog-i2c (I2C master + slave) | serial_peripheral_protocol | MIT | yes | github.com/alexforencich/verilog-i2c |
| 15 | verilog-ethernet (1G/10G Ethernet MAC + UDP/IP) | bus_interconnect_protocol | MIT | yes | github.com/alexforencich/verilog-ethernet |
| 16 | ZipCPU/wb2axip (AXI-lite/AXI/Wishbone crossbar) | bus_interconnect_protocol | Apache-2.0 | yes | github.com/ZipCPU/wb2axip |
| 17 | usb_cdc (Full-Speed USB CDC-ACM device) | serial_peripheral_protocol | MIT | yes | github.com/ulixxe/usb_cdc |
| 18 | CTU CAN FD IP Core | serial_peripheral_protocol | MIT (RTL core) | yes | github.com/antmicro/ctucanfd_ip_core (mirror of Blebowski/CTU-CAN-FD) |
| 19 | apb_adv_timer (Advanced PWM/Timer, APB) | digital_cmd_driven | Solderpad HL v0.51 (Apache-treatable) | no (TB must be generated) | github.com/pulp-platform/apb_adv_timer |
| 20 | iic-jku/SKY130_SAR-ADC1 (12-bit async SAR ADC, sky130) | analog_mixed_signal | Apache-2.0 | partial | github.com/iic-jku/SKY130_SAR-ADC1 (mirror efabless/SKY130_SAR-ADC1) |

## Adversarial verify issues
- #12 Gemmini: NO REAL RTL as-shipped. GitHub search/code returns 0 Verilog/SystemVerilog files; repo is 100% Scala/Chisel (languages = Scala 681KB + Shell, no verilog/ dir, src/ is Scala). Requires Chisel elaboration + RoCC decoupling before any RTL exists. Fails the 'real, buildable RTL design' requirement as-shipped. License is fine (UC Regents BSD-3-style, permissive).
- #20 SKY130_SAR-ADC1: WRONG/FABRICATED source attribution. List says 'mirror efabless/SKY130_SAR-ADC1' but the actual GitHub fork parent (and source) is w32agobot/SKY130_SAR-ADC — efabless appears nowhere in the fork chain. The repo itself is REAL and valid (Apache-2.0, ships verilog/rtl with adc_core_digital.v etc., plus spice/xschem/gds/openlane), so it survives, but the provenance claim must be corrected to iic-jku fork-of-w32agobot.
- DIVERSITY (soft): digital_arithmetic_primitive has 8 entries but 3 are FFTs (Vyges/thasti/R2FFT) and 2 are FPUs (dawsonjon/PULP div-sqrt) — heavy intra-class clustering. Not a CPU-cap violation (CPU count = 0, well under <=4) and not disqualifying, but the arithmetic class is over-weighted toward FFT/FP redundancy.
- MINOR (not disqualifying): GitHub auto-detector flagged secworks/modexp, ZipCPU/wb2axip, pulp fpu_div_sqrt_mvp, thasti/fft, apb_adv_timer as NOASSERTION/null/Other — manual inspection confirms ALL are permissive (modexp=verbatim BSD-2 with non-standard header; wb2axip=Apache-2.0 per README + per-file headers; pulp div-sqrt + apb_adv_timer = Solderpad HL v0.51 Apache-based; thasti = Solderpad HL v2.0 Apache-wraparound). No actual license problem; the list's license claims are accurate.
- MINOR: ctucanfd license confirmed MIT (verbatim MIT body under a custom CTU copyright header); Bosch CAN patent caveat correctly disclosed. dawsonjon/fpu COPYING.txt confirmed verbatim MIT (not GPL despite the COPYING filename). No issue.
