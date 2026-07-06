import cocotb
import os
import pytest
import random
from cocotb_tools.runner import get_runner

# Environment configuration
verilog_sources = os.getenv("VERILOG_SOURCES").split()
toplevel_lang   = os.getenv("TOPLEVEL_LANG")
sim             = os.getenv("SIM", "icarus")
toplevel        = os.getenv("TOPLEVEL")
module          = os.getenv("MODULE")
wave            = bool(os.getenv("WAVE"))

def runner(DATA_WIDTH: int = 128):
    # Simulation parameters
    parameter = {
        "DATA_WIDTH": DATA_WIDTH
    }

    # Debug information
    print(f"[DEBUG] Running simulation with DATA_WIDTH={DATA_WIDTH}")
    print(f"[DEBUG] Parameters: {parameter}")

    # Configure and run the simulation
    sim_runner = get_runner(sim)
    sim_runner.build(
        sources=verilog_sources,
        hdl_toplevel=toplevel,
        parameters=parameter,
        always=True,
        clean=True,
        verbose=True,
        timescale=("1ns", "1ns"),
        log_file="sim.log"
    )

    # Run the test
    sim_runner.test(hdl_toplevel=toplevel, test_module=module, waves=True)

# Generate DATA_WIDTH values (default, minimum, and 3 random values)
random_data_width = [16,32]#[16, 128] + [random.randint(16, 256) for _ in range(3)]

# Parametrize test for different DATA_WIDTH values
@pytest.mark.parametrize("DATA_WIDTH", random_data_width)
@pytest.mark.parametrize("test", range(1))
def test_data(DATA_WIDTH, test):
    # Run the simulation with specified parameters
    runner(DATA_WIDTH=DATA_WIDTH)