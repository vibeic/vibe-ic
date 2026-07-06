import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer
import random
import harness_library as hrs_lb

@cocotb.test()
async def test_complex_scrambler(dut):
    """Test the Complex Scrambler module with random inputs and multiple modes."""

    # Start the clock
    cocotb.start_soon(Clock(dut.clk, 10, unit='ns').start())

    # Debug mode
    debug = 1

    # Retrieve parameters from the DUT
    DATA_WIDTH = int(dut.DATA_WIDTH.value)

    # Range for input values
    data_min = 0
    data_max = int(2**DATA_WIDTH - 1)
    data_in = 0
    # Number of random test iterations
    num_iterations = 4

    model = hrs_lb.ScramblerModel(data_width=DATA_WIDTH)

    # Test all modes
    for mode in range(9):  # Modes 0 to 8
        cocotb.log.info(f"\n [INFO] Testing Mode={mode}")
        await hrs_lb.dut_init(dut)
        #await hrs_lb.reset_dut(dut.rst_n)
        dut.rst_n.value = 0
        await Timer(10, unit="ns")

        model.initialize_lfsr()
        model_reset_value = model.update(mode, data_in)
        dut.mode.value = mode

        cocotb.log.info(f"dut   out reset = {hex(int(dut.data_out.value)) if dut.data_out.value.is_resolvable else 'X'}")
        cocotb.log.info(f"model out reset = {hex(model_reset_value)}")

        dut.rst_n.value = 1

        await Timer(10, unit="ns")

        await RisingEdge(dut.clk)

        for test_num in range(num_iterations-1):
            # Generate random input data
            data_in = random.randint(data_min, data_max)

            # Apply inputs to DUT
            dut.data_in.value = data_in

            exp_data = model.scramble(data_in, mode)
            # Wait for one clock cycle
            await RisingEdge(dut.clk)

            # Read outputs from DUT
            dut_data_out = int(dut.data_out.value)

            if debug:
                cocotb.log.info(f"[Test {test_num + 1}]")
                cocotb.log.info(f"Input data_in = {hex(data_in)}")
                cocotb.log.info(f"DUT   Feedback        = {dut.feedback.value}")
                cocotb.log.info(f"DUT   Output data_out = {hex(dut_data_out)}")
                cocotb.log.info(f"Model Output data_out = {hex(exp_data)}")
            
            assert dut_data_out == exp_data, f"Mismatch, expected data = {exp_data} vs dut data = {dut_data_out}"

    cocotb.log.info(f"All tests completed for modes 0 to 8.")