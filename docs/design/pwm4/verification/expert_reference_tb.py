"""PWM4 black-box checks derived from ../design_description.md.

Only top-level pins are observed. Waveform checks infer phase from an output
edge, then compare period and high time with the documented integer rule.
"""
import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, Timer

CLOCK_NS = 40
SPI_HALF_NS = 500


async def cycles(dut, count):
    for _ in range(count):
        await FallingEdge(dut.clk)
    await Timer(1, unit="ns")


async def reset(dut, start_clock=False):
    if start_clock:
        dut.clk.value = 0
        dut.rst_n.value = 1
        dut.spi_cs_n.value = 1
        dut.spi_sclk.value = 0
        dut.spi_mosi.value = 0
        await Timer(CLOCK_NS, unit="ns")
    dut.rst_n.value = 0
    await Timer(2 * CLOCK_NS, unit="ns")
    assert int(dut.pwm_out.value) == 0, "asserted asynchronous reset must settle low"
    assert int(dut.spi_miso.value) == 0, "MISO is tied low"
    dut.spi_cs_n.value = 1
    dut.spi_sclk.value = 0
    dut.spi_mosi.value = 0
    if start_clock:
        cocotb.start_soon(Clock(dut.clk, CLOCK_NS, unit="ns").start())
    await FallingEdge(dut.clk)
    await Timer(1, unit="ns")
    dut.rst_n.value = 1
    for _ in range(8):
        await cycles(dut, 1)
        assert int(dut.pwm_out.value) == 0, "outputs must remain low after reset release"


async def frame(dut, address, data, write=True, bit_count=24):
    word = ((0x80 if write else 0) | address) << 16 | data
    dut.spi_cs_n.value = 0
    await Timer(SPI_HALF_NS, unit="ns")
    bits = [(word >> bit) & 1 for bit in range(23, -1, -1)]
    bits = (bits + [1] * max(0, bit_count - 24))[:bit_count]
    for bit in bits:
        dut.spi_mosi.value = bit
        await Timer(SPI_HALF_NS, unit="ns")
        dut.spi_sclk.value = 1
        await Timer(SPI_HALF_NS, unit="ns")
        dut.spi_sclk.value = 0
    await Timer(SPI_HALF_NS, unit="ns")
    dut.spi_cs_n.value = 1
    await Timer(SPI_HALF_NS, unit="ns")


async def configure(dut, periods, duties, mask=15):
    for channel in range(4):
        await frame(dut, channel, periods[channel])
        await frame(dut, 4 + channel, duties[channel])
    await frame(dut, 8, mask)
    # A previous 16-bit period can still be running while new values wait.
    await cycles(dut, 65535 + 10)


async def waveforms(dut, periods, duties, mask=15, repetitions=2):
    previous = [None] * 4
    rising = [None] * 4
    observed_periods = [0] * 4
    observed_highs = [0] * 4
    for tick in range(max(periods + [1]) * (repetitions + 1) + 4):
        await FallingEdge(dut.clk)
        await Timer(1, unit="ns")
        sample = int(dut.pwm_out.value)
        assert int(dut.spi_miso.value) == 0, "MISO must remain zero"
        for channel, (period, duty) in enumerate(zip(periods, duties)):
            value = (sample >> channel) & 1
            enabled = bool(mask & (1 << channel))
            if not enabled or period == 0 or duty == 0:
                assert value == 0, f"channel {channel} must be low"
            elif duty >= period:
                assert value == 1, f"channel {channel} must be high"
            else:
                if previous[channel] == 0 and value == 1:
                    if rising[channel] is not None:
                        distance = tick - rising[channel]
                        assert distance == period, (channel, "period", distance, period)
                        observed_periods[channel] += 1
                    rising[channel] = tick
                if previous[channel] == 1 and value == 0:
                    if rising[channel] is not None:
                        width = tick - rising[channel]
                        assert width == duty, (channel, "high width", width, duty)
                        observed_highs[channel] += 1
            previous[channel] = value
        await Timer(14, unit="ns")
        assert int(dut.pwm_out.value) == sample, "PWM changed away from a clock edge"
    for channel, (period, duty) in enumerate(zip(periods, duties)):
        if mask & (1 << channel) and 0 < duty < period:
            assert observed_periods[channel] >= repetitions, (channel, "missing complete periods")
            assert observed_highs[channel] >= repetitions, (channel, "missing complete pulses")


async def boundary_check(dut):
    period, duty = 2048, 1500
    await configure(dut, [period] * 4, [duty] * 4)
    previous = int(dut.pwm_out.value) & 1
    while True:
        await cycles(dut, 1)
        current = int(dut.pwm_out.value) & 1
        if current and not previous:
            break
        previous = current

    # A 25.5 us SPI frame fits inside the 60 us old high pulse.
    async def record():
        samples = []
        for _ in range(3 * period):
            await cycles(dut, 1)
            samples.append(int(dut.pwm_out.value) & 1)
        return samples

    monitor = cocotb.start_soon(record())
    await frame(dut, 4, 350)
    samples = [1] + await monitor
    transitions = [(index, value) for index, value in enumerate(samples[1:], 1)
                   if value != samples[index - 1]]
    assert transitions[:4] == [(duty, 0), (period, 1), (period + 350, 0), (2 * period, 1)], transitions[:4]
    await waveforms(dut, [period] * 4, [350, duty, duty, duty])

    previous = int(dut.pwm_out.value) & 1
    while True:
        await cycles(dut, 1)
        current = int(dut.pwm_out.value) & 1
        if current and not previous:
            break
        previous = current
    monitor = cocotb.start_soon(record())
    await frame(dut, 0, 1024)
    samples = [1] + await monitor
    starts = [i for i in range(1, len(samples)) if samples[i] and not samples[i - 1]]
    assert starts[:3] == [period, period + 1024, period + 2048], starts[:3]
    await cycles(dut, period + 10)
    await waveforms(dut, [1024, period, period, period], [350, duty, duty, duty])

    previous = int(dut.pwm_out.value) & 1
    while True:
        await cycles(dut, 1)
        current = int(dut.pwm_out.value) & 1
        if current and not previous:
            break
        previous = current
    monitor = cocotb.start_soon(record())
    await frame(dut, 8, 14)
    samples = [1] + await monitor
    assert samples[:350] == [1] * 350, "disable truncated the current high pulse"
    assert not any(samples[350:]), "disabled channel restarted at a later boundary"


@cocotb.test()
async def pwm4_contract(dut):
    await reset(dut, start_clock=True)
    assert int(dut.pwm_out.value) == 0, "outputs remain low after reset release"
    periods, duties = [7, 11, 13, 17], [1, 5, 12, 8]
    await configure(dut, periods, duties)
    await waveforms(dut, periods, duties)

    for mask in range(16):
        await frame(dut, 8, 0xFFF0 | mask)
        await cycles(dut, max(periods) + 10)
        await waveforms(dut, periods, duties, mask)
    await frame(dut, 8, 15)
    await cycles(dut, 30)

    for address, data, write, length in [(0, 2, False, 24), (0x7F, 0xFFFF, True, 24),
                                          (4, 0, True, 23), (4, 0, True, 25),
                                          (0, 0, True, 0), (4, 0, True, 31)]:
        await frame(dut, address, data, write, length)
        await cycles(dut, 30)
        await waveforms(dut, periods, duties)

    await boundary_check(dut)
    await reset(dut)
    for periods, duties in [([0, 1, 2, 2], [65535, 1, 0, 1]),
                            ([2, 3, 5, 7], [2, 65535, 1, 6]),
                            ([65535] * 4, [0, 1, 32768, 65534])]:
        await configure(dut, periods, duties)
        await waveforms(dut, periods, duties, repetitions=2)

    rng = random.Random(0x504D5734)
    for _ in range(8):
        periods = [rng.randrange(1, 65536) for _ in range(4)]
        duties = [rng.randrange(65536) for _ in range(4)]
        await configure(dut, periods, duties)
        await waveforms(dut, periods, duties, repetitions=1)

    dut.spi_cs_n.value = 0
    dut.spi_mosi.value = 1
    await Timer(SPI_HALF_NS, unit="ns")
    dut.spi_sclk.value = 1
    await Timer(SPI_HALF_NS, unit="ns")
    await reset(dut)
    await configure(dut, [3, 5, 7, 9], [1, 2, 3, 4])
    await waveforms(dut, [3, 5, 7, 9], [1, 2, 3, 4])
    print("PROFESSIONAL_TB PASS PWM4 contract: reset release, SPI, four channels, boundaries, malformed frames and numeric limits")
