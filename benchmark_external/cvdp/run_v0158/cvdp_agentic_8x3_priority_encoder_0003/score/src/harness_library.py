
from cocotb.triggers import FallingEdge, RisingEdge, Timer
from cocotb_tools.runner import get_runner
import random
import struct
import os
import subprocess
import re

def runner(module, toplevel, src:str, plusargs:list =[], args:tuple = (), parameter:dict={}, wave:bool = False, sim:str = "icarus"):
    runner = get_runner(sim)
    runner.build(
        sources=src,
        hdl_toplevel=toplevel,
        # Arguments
        parameters=parameter,
        # compiler args
        build_args=args,
        always=True,
        clean=True,
        verbose=True,
        timescale=("1ns", "1ns"),
        log_file="build.log")
    runner.test(hdl_toplevel=toplevel, test_module=module, waves=wave, plusargs=plusargs, log_file="sim.log")

def coverage_report(asrt_type:str):
    '''asrt_type: assertion, toggle, overall'''
    cmd = f"imc -load /code/rundir/sim_build/cov_work/scope/test -execcmd \"report -metrics {asrt_type} -all -aspect sim -assertionStatus -overwrite -text -out coverage.log\""
    assert(subprocess.run(cmd, shell=True)), "Coverage merge didn't ran correctly."

def covt_report_check():

    metrics = {}

    with open("/code/rundir/coverage.log") as f:
        lines = f.readlines()

    # ----------------------------------------
    # - Evaluate Report
    # ----------------------------------------
    column = re.split(r'\s{2,}', lines[0].strip())
    for line in lines[2:]:
        info = re.split(r'\s{2,}', line.strip())
        inst = info[0].lstrip('|-')
        metrics [inst] = {column[i]: info[i].split('%')[0] for i in range(1, len(column))}

    print("Metrics:")
    print(metrics)

    if "Overall Average" in metrics[os.getenv("TOPLEVEL")]:
        assert float(metrics[os.getenv("TOPLEVEL")]["Overall Average"]) >= float(os.getenv("TARGET")), "Didn't achieved the required coverage result."
    elif "Assertion" in metrics[os.getenv("TOPLEVEL")]:
        assert float(metrics[os.getenv("TOPLEVEL")]["Assertion"]) >= 100.00, "Didn't achieved the required coverage result."
    elif "Toggle" in metrics[os.getenv("TOPLEVEL")]:
        assert float(metrics[os.getenv("TOPLEVEL")]["Toggle"]) >= float(os.getenv("TARGET")), "Didn't achieved the required coverage result."
    elif "Block" in metrics[os.getenv("TOPLEVEL")]:
        assert float(metrics[os.getenv("TOPLEVEL")]["Block"]) >= float(os.getenv("TARGET")), "Didn't achieved the required coverage result."
    else:
        assert False, "Couldn't find the required coverage result."

def save_vcd(wave:bool, toplevel:str, new_name:str):
    if wave:
        os.makedirs("vcd", exist_ok=True)
        os.rename(f'./sim_build/{toplevel}.fst', f'./vcd/{new_name}.fst')

async def reset_dut(reset_n, duration_ns = 10, active:bool = False):
    # Restart Interface
    reset_n.value = 1 if active else 0
    await Timer(duration_ns, unit="ns")
    reset_n.value = 0 if active else 1
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
def ary_2_int(arry: list, ewdth: int=8) -> int:
    if arry is not None:
        ary = arry.copy()
        ary.reverse()
        ary_byt = int(''.join(format(num, f'0{ewdth}b') for num in ary), 2)
        return ary_byt
    else:
        raise ValueError
    
async def rnd_clk_dly (clock, low: int = 50, high: int = 100):
    for i in range(random.randint(50,100)):
            await RisingEdge(clock)

# converitng floating point number in scientific notation binary format
def float_to_binary(num: float):
    # Convert float to 32-bit binary representation
    packed_num = struct.pack('!f', num)  # Packs the float into 32 bits using IEEE 754
    binary_representation = ''.join(f'{byte:08b}' for byte in packed_num)

    sign = binary_representation[0]
    exponent = binary_representation[1:9]
    mantissa = binary_representation[9:]

    return sign, exponent, mantissa

def highbit_number(number: int, length=8,  msb=True) -> int:
    str_num = bin(number)[2:].zfill(length)
    print(str_num)
    if str_num.count('1') == 0:
        return 0
    elif msb:
        return length - str_num.index('1') - 1
    else:
        return str_num[::-1].index('1')