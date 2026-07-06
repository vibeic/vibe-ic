import os
from cocotb_tools.runner import get_runner

# Get environment variables for Verilog sources, top-level language, and simulation options
verilog_sources = os.getenv("VERILOG_SOURCES").split()
toplevel_lang = os.getenv("TOPLEVEL_LANG")
sim = os.getenv("SIM", "icarus")
toplevel = os.getenv("TOPLEVEL")
module = os.getenv("MODULE")
wave = os.getenv("WAVE")

# List of WIDTH values to test
# If WIDTH is set in the environment, use that value; otherwise, use default values
env_width = os.getenv("WIDTH")
if env_width:
    width_values = [int(env_width)]
else:
    width_values = [24, 32, 64, 66]  # Add or remove widths as needed

def test_runner():
    runner = get_runner(sim)

    for WIDTH in width_values:
        print(f"Running test for WIDTH={WIDTH}")
        # Set WIDTH in the environment for the build process
        os.environ["WIDTH"] = str(WIDTH)

        # Build the design with the current WIDTH
        runner.build(
            sources=verilog_sources,
            hdl_toplevel=toplevel,
            always=True,
            clean=True,
            verbose=True,
            timescale=("1ns", "1ns"),
            log_file=f"build_{WIDTH}.log",
            parameters={
                "WIDTH": WIDTH  # Pass WIDTH parameter for dynamic configuration
            }
        )

        # Run the test
        runner.test(
            hdl_toplevel=toplevel,
            test_module=module,
            waves=True,
            gui=False
        )

if __name__ == "__main__":
    test_runner()
