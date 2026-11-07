# PWM4 verification plan

- **Reset and release**: Assert reset with the system clock stopped, wait 40 ns and expect all outputs low. Release reset under the timing above, run the system clock and expect outputs to remain low without writes.
- **Four independent channels**: Configure distinct period/duty pairs through complete SPI frames, enable all channels and check each output's high count and period over repeated complete cycles.
- **Boundary adoption**: While a channel is running, change duty and period through SPI. Expect the old pulse and period to finish and the new configuration to start at a period boundary. Change enable in a running period and expect boundary adoption.
- **Register isolation and malformed transfers**: Write each channel independently. Issue read-bit-clear commands, unmapped addresses, short frames and overlong frames. Expect existing waveforms to remain unchanged.
- **Numeric boundaries**: Exercise period 0, 1, 2 and 65535; duty 0, 1, period-1, period and 65535; all enable masks; and deterministic varied 16-bit period/duty payloads. Check all four outputs against the specified count rule.
- **Reset during traffic**: Assert reset while PWM is active and during a partial SPI frame. Expect settled outputs low, no retained configuration after release and correct acceptance of the next complete frame.
