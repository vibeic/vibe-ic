import os
from cocotb_tools.runner import get_runner

# Get environment variables for Verilog sources, top-level language, and simulation options
verilog_sources = os.getenv("VERILOG_SOURCES").split()
toplevel_lang = os.getenv("TOPLEVEL_LANG")
sim = os.getenv("SIM", "icarus")
toplevel = os.getenv("TOPLEVEL")
module = os.getenv("MODULE")
wave = os.getenv("WAVE")

# Define WIDTH parameter from environment variable
WIDTH = os.getenv("WIDTH", "64")  # Default to 32 bits

def test_runner():
    # Set WIDTH in the environment for the testbench to access
    os.environ["WIDTH"] = WIDTH

    runner = get_runner(sim)
    
    # Build the design with dynamic parameter for WIDTH
    runner.build(
        sources=verilog_sources,
        hdl_toplevel=toplevel,
        always=True,
        clean=True,
        verbose=True,
        timescale=("1ns", "1ns"),
        log_file="build.log",
        # Pass WIDTH parameter dynamically to the simulator
        parameters={
            "WIDTH": WIDTH  # Add WIDTH parameter for dynamic configuration
        }
    )

    # Run the test
    runner.test(
        hdl_toplevel=toplevel,
        test_module=module,
        waves=True
    )

if __name__ == "__main__":
    test_runner()
