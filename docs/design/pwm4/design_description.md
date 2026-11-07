# PWM4 controller

A four-channel PWM controller chip in gf180mcuD. Each channel has a 16-bit period and a 16-bit duty value. Configuration goes through an SPI slave, mode 0, with a simple register map for period, duty and channel enable. New period and duty values take effect at the end of the current period, so outputs never glitch. One 25 MHz clock input and an active-low asynchronous reset. Four PWM outputs. Outputs are low after reset.

The following interface and corner-case choices complete the design input. They are design decisions for this revision, not values inferred from an RTL decoder.

## Integration interface

Top module: `chip_top`.

| Signal | Direction | Width | Description |
|---|---|---|---|
| clk | input | 1 | Primary 25 MHz system clock, 40 ns period. |
| rst_n | input | 1 | Active-low asynchronous reset. |
| spi_sclk | input | 1 | SPI mode 0 serial clock, idle low. Sampled as data in the clk domain. |
| spi_cs_n | input | 1 | Active-low chip select. Sampled as data in the clk domain. |
| spi_mosi | input | 1 | SPI serial configuration input, most significant bit first. |
| spi_miso | output | 1 | Always zero; configuration has no readback. |
| pwm_out | output | 4 | Independent channel outputs; bit n is channel n. |

## SPI transactions

Each CS-low transaction contains exactly 24 rising SCLK edges. The first eight bits are the command and the remaining sixteen bits are data. MOSI is sampled on rising SCLK edges and changes on falling edges. Command bit 7 is write enable. Command bits 6:0 are the register address. A write command is `0x80 | address`; data is sent bit 15 first. A command with bit 7 clear has no effect. CS rising commits a complete frame. Incomplete frames and frames longer than 24 bits have no effect. Unmapped addresses have no effect. A reset during a transaction cancels it. The next transaction starts with a new CS falling edge.

Payload format: a 16-bit unsigned register value, high byte first, following the 8-bit command. There is no response payload.

### Command table

| Opcode | Command | Payload | Description |
|---|---|---|---|
| 0x80 | WRITE_PERIOD0 | 16-bit unsigned value | Write channel 0 pending period. |
| 0x81 | WRITE_PERIOD1 | 16-bit unsigned value | Write channel 1 pending period. |
| 0x82 | WRITE_PERIOD2 | 16-bit unsigned value | Write channel 2 pending period. |
| 0x83 | WRITE_PERIOD3 | 16-bit unsigned value | Write channel 3 pending period. |
| 0x84 | WRITE_DUTY0 | 16-bit unsigned value | Write channel 0 pending duty. |
| 0x85 | WRITE_DUTY1 | 16-bit unsigned value | Write channel 1 pending duty. |
| 0x86 | WRITE_DUTY2 | 16-bit unsigned value | Write channel 2 pending duty. |
| 0x87 | WRITE_DUTY3 | 16-bit unsigned value | Write channel 3 pending duty. |
| 0x88 | WRITE_ENABLE | bits 3:0 channel enables | Write pending enables; ignore bits 15:4. |

| Address | Register | Width | Access | Reset | Meaning |
|---|---|---|---|---|---|
| 0x00 | period0 | 16 | write | 0 | Channel 0 period in clk cycles. |
| 0x01 | period1 | 16 | write | 0 | Channel 1 period in clk cycles. |
| 0x02 | period2 | 16 | write | 0 | Channel 2 period in clk cycles. |
| 0x03 | period3 | 16 | write | 0 | Channel 3 period in clk cycles. |
| 0x04 | duty0 | 16 | write | 0 | Channel 0 high time in clk cycles. |
| 0x05 | duty1 | 16 | write | 0 | Channel 1 high time in clk cycles. |
| 0x06 | duty2 | 16 | write | 0 | Channel 2 high time in clk cycles. |
| 0x07 | duty3 | 16 | write | 0 | Channel 3 high time in clk cycles. |
| 0x08 | enable | 4 | write | 0 | Bits 3:0 enable channels 3:0; bits 15:4 are ignored. |

## Clock and external timing

All sequential state, including the SPI receiver, is clocked by `clk`. Two-stage input synchronizers sample SCLK, CS and MOSI before edge detection. Neither SCLK nor CS is a register clock. The external SPI master runs at at most 1 MHz, with SCLK high and low each at least 500 ns. MOSI setup and hold relative to a rising SCLK edge are each at least 200 ns. CS must be low at least 500 ns before the first rising SCLK edge, remain low at least 500 ns after the last falling edge, and remain high at least 500 ns between transactions. MOSI stays stable through the final hold interval. A valid frame reaches the pending configuration within eight system clock cycles after CS rises. The SPI pins are asynchronous inputs sampled in the system domain; this is not a phase-related generated SPI clock.

For chip timing, the external source has a 10 ns transition on `rst_n`, `spi_sclk`, `spi_cs_n` and `spi_mosi`. This is a design interface assumption. Reset assertion lasts at least two system clock periods. Reset release occurs with CS high and SCLK low, at least 200 ns before any SPI transaction. Reset release is stable at least 10 ns before and after a rising system clock edge.

## PWM and reset behaviour

For a nonzero period P, each channel counts 0 through P-1. Its output is high exactly when enabled and the count is less than duty D. Period zero stops the channel and holds its output low. Duty zero produces constant low. Duty greater than or equal to a nonzero period produces constant high while enabled. Disabling a channel holds its output low after boundary adoption. Counters and active and pending registers reset to zero, including enable.

Writes update pending fields. At a channel's next period boundary, all written fields for that channel are adopted together and its count starts at zero. An unwritten field retains its active value. A later write to the same field before adoption replaces the pending value. A stopped channel adopts pending fields on its next system clock. A write already delivered to pending configuration before a boundary is applied at that boundary; no cross-register atomic transaction is promised. Enable changes use the same boundary rule. Running channels continue counting while disabled. Outside reset, output changes occur only following system clock edges, with normal propagation delay; no SPI edge directly changes a PWM output.

During asserted asynchronous reset, outputs settle low without a system clock edge. Reset assertions are checked after a complete 40 ns system clock period of settling, not after an invented 1 ns deadline. Outputs remain low after reset release until enabled with nonzero period and duty. Steady-state waveform checks sample halfway between system clock edges so annotated gate delays can settle.

## Verification plan

- **Reset and release**. Assert reset with the system clock stopped, wait 40 ns and expect all outputs low. Release reset under the timing above, run the system clock and expect outputs to remain low without writes.
- **Four independent channels**. Configure distinct period/duty pairs through complete SPI frames, enable all channels and check each output's high count and period over repeated complete cycles.
- **Boundary adoption**. While a channel is running, change duty and period through SPI. Expect the old pulse and period to finish and the new configuration to start at a period boundary. Change enable in a running period and expect boundary adoption.
- **Register isolation and malformed transfers**. Write each channel independently. Issue read-bit-clear commands, unmapped addresses, short frames and overlong frames. Expect existing waveforms to remain unchanged.
- **Numeric boundaries**. Exercise period 0, 1, 2 and 65535; duty 0, 1, period-1, period and 65535; all enable masks; and deterministic varied 16-bit period/duty payloads. Check all four outputs against the specified count rule.
- **Reset during traffic**. Assert reset while PWM is active and during a partial SPI frame. Expect settled outputs low, no retained configuration after release and correct acceptance of the next complete frame.
