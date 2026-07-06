import os
from cocotb_tools.runner import get_runner
import pytest

verilog_sources = os.getenv("VERILOG_SOURCES").split()
toplevel_lang   = os.getenv("TOPLEVEL_LANG")
sim             = os.getenv("SIM", "icarus")
toplevel        = os.getenv("TOPLEVEL")
module          = os.getenv("MODULE")
wave            = bool(os.getenv("WAVE"))

def runner(DATA_WIDTH,PARITY_BIT):
    runner = get_runner(sim)
    runner.build(
        sources=verilog_sources,
        hdl_toplevel=toplevel,
        parameters= {'DATA_WIDTH': DATA_WIDTH,'PARITY_BIT': PARITY_BIT },
        always=True,
        clean=True,
        verbose=False,
        timescale=("1ns", "1ns"),
        log_file="sim.log")
    runner.test(hdl_toplevel=toplevel, test_module=module, waves=wave)


def find_min_p(m):
    p = 0
    while 2 ** p < (p + m + 1):
        p += 1
    return p

def get_powers_of_two_pairs(iterations):
    value = 4
    pairs = []
    for _ in range(iterations):
        m = value
        p = find_min_p(m)
        pairs.append((m, p))
        value *= 2
    return pairs

# Test the function
pairs = get_powers_of_two_pairs(6)
#print(pairs)

# random test
@pytest.mark.parametrize("DATA_WIDTH, PARITY_BIT",pairs)
def test(DATA_WIDTH,PARITY_BIT):
    print(f'Running with: DATA_WIDTH = {DATA_WIDTH}, PARITY_BIT = {PARITY_BIT}')
    runner(DATA_WIDTH ,PARITY_BIT)
