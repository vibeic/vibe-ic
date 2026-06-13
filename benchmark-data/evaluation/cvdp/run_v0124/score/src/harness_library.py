from cocotb.triggers import FallingEdge, RisingEdge, Timer
import random
async def reset_dut(reset_n, duration_ns = 2, active:bool = False):
    # Restart Interface
    reset_n.value = 0 if active else 1
    await Timer(duration_ns, unit="ns")
    reset_n.value = 1 if active else 0
    await Timer(duration_ns, unit='ns')
    reset_n._log.debug("Reset complete")

async def duty_cycle(pwm_signal, clock, period):
    # 0-> time_period, 1-> high_time, 2-> low_time = full_time = high_time
    pwm = {"time_period": period, "on_time": 0, "off_time": 0}
    pwm_signal._log.debug("Pulse started")
    for i in range(period):
        if pwm_signal.value == 1:
            pwm["on_time"] += 1
        await RisingEdge(clock)

    pwm["off_time"] = pwm["time_period"] - pwm["on_time"]
    pwm_signal._log.debug("Time period completed")
    return pwm

async def dut_init(dut):
    # iterate all the input signals and initialize with 0
    for signal in dut:
        try:
            signal.value = 0
        except Exception:
            pass

# all the element of array dump in to one verable
def ary_2_int(arry: list) -> int:
    if arry is not None:
        ary = arry.copy()
        ary.reverse()
        ary_byt = int(''.join(format(num, '08b') for num in ary), 2)
        return ary_byt
    else:
        raise ValueError
    
async def rnd_clk_dly (clock, low: int = 50, high: int = 100):
    for i in range(random.randint(50,100)):
            await RisingEdge(clock)