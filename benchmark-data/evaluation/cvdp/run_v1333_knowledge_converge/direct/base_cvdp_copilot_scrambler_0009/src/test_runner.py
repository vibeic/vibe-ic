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

def runner(ROW_COL_WIDTH: int = 16, SUB_BLOCKS: int = 4, OUT_DATA_WIDTH: int = 16, WAIT_CYCLES: int = 4):
    # Simulation parameters
    parameter = {
        "ROW_COL_WIDTH": ROW_COL_WIDTH,
        "SUB_BLOCKS": SUB_BLOCKS,
        "OUT_DATA_WIDTH": OUT_DATA_WIDTH,
        "WAIT_CYCLES": WAIT_CYCLES
    }

    # Debug information
    print(f"[DEBUG] Running simulation with ROW_COL_WIDTH={ROW_COL_WIDTH}, SUB_BLOCKS={SUB_BLOCKS}, OUT_DATA_WIDTH={OUT_DATA_WIDTH}, WAIT_CYCLES={WAIT_CYCLES}")
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

# Generate parameter values
row_col_width_values = [16]  # Fixed values (following the prompt)
sub_blocks_values = [4]      # Fixed values (following the prompt)
out_data_width_values = [8, 16]  # Can be 8 or 16
wait_cycles_values = [4] + [random.randint(5,16) for _ in range(5)] # Minimum 4, maximum 16

# Parametrize test for different parameter combinations
@pytest.mark.parametrize("ROW_COL_WIDTH", row_col_width_values)
@pytest.mark.parametrize("SUB_BLOCKS", sub_blocks_values)
@pytest.mark.parametrize("OUT_DATA_WIDTH", out_data_width_values)
@pytest.mark.parametrize("WAIT_CYCLES", wait_cycles_values)
@pytest.mark.parametrize("test", range(3))
def test_data(ROW_COL_WIDTH, SUB_BLOCKS, OUT_DATA_WIDTH, WAIT_CYCLES, test):
    # Run the simulation with specified parameters
    runner(ROW_COL_WIDTH=ROW_COL_WIDTH, SUB_BLOCKS=SUB_BLOCKS, OUT_DATA_WIDTH=OUT_DATA_WIDTH, WAIT_CYCLES=WAIT_CYCLES)