import os
from cocotb_tools.runner import get_runner
import pytest

verilog_sources = os.getenv("VERILOG_SOURCES").split()
toplevel_lang   = os.getenv("TOPLEVEL_LANG")
sim             = os.getenv("SIM", "icarus")
toplevel        = os.getenv("TOPLEVEL")
module          = os.getenv("MODULE")
wave            = bool(os.getenv("WAVE"))

def runner():
    runner = get_runner(sim)
    runner.build(
        sources=verilog_sources,
        hdl_toplevel=toplevel,
        #parameters= {'REVERSE': REVERSE },
        always=True,
        clean=True,
        verbose=False,
        timescale=("1ns", "1ns"),
        log_file="sim.log")
    runner.test(hdl_toplevel=toplevel, test_module=module, waves=wave)

# random test
@pytest.mark.parametrize("test", range(1))
def test(test):
    runner()
    
