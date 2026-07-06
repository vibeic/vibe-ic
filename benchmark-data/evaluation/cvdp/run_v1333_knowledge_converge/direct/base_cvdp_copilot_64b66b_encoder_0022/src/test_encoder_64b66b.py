import cocotb
from cocotb.triggers import RisingEdge, Timer
from cocotb.clock import Clock
import random

# Helper function to initialize DUT inputs
async def dut_initialization(dut):
    """ Initialize all inputs for DUT """
    dut.rst_in.value = 1
    dut.encoder_data_in.value = 0
    dut.encoder_control_in.value = 0
    await RisingEdge(dut.clk_in)  # Wait for one clock cycle

# Helper function to check the output with debug logging
async def check_output(dut, expected_sync, expected_data):
    await RisingEdge(dut.clk_in)
    actual_output = int(dut.encoder_data_out.value)
    expected_output = (expected_sync << 64) | expected_data

    # Log the actual and expected outputs
    dut._log.info(f"Checking output:\n"
                  f"  Actual encoder_data_out: {hex(actual_output)}\n"
                  f"  Expected encoder_data_out: {hex(expected_output)}\n")

    assert actual_output == expected_output, \
        f"Test failed: encoder_data_out={hex(actual_output)} (expected {hex(expected_output)})"

@cocotb.test()
async def reset_test(dut):
    """ Test the reset behavior of the encoder """
    # Start the clock
    clock = Clock(dut.clk_in, 10, unit="ns")  # 100 MHz
    cocotb.start_soon(clock.start())
    
    # Initialize DUT inputs
    await dut_initialization(dut)

    await Timer(20, unit="ns")  # hold reset for 20ns
    dut.rst_in.value = 0
    await RisingEdge(dut.clk_in)
    await RisingEdge(dut.clk_in)
    await RisingEdge(dut.clk_in)
    dut.rst_in.value = 1
    await RisingEdge(dut.clk_in)
    await RisingEdge(dut.clk_in)

    # Log the output after reset
    dut._log.info(f"Reset Test:\n  encoder_data_out: {hex(int(dut.encoder_data_out.value))}\n  Expected: 0")

    # Check that output is zero after reset
    assert int(dut.encoder_data_out.value) == 0, "Reset test failed: encoder_data_out should be zero after reset"

@cocotb.test()
async def data_encoding_test(dut):
    """ Test encoding when all data octets are pure data """
    clock = Clock(dut.clk_in, 10, unit="ns")  # 100 MHz
    cocotb.start_soon(clock.start())
    # Initialize DUT inputs
    await dut_initialization(dut)

    await Timer(20, unit="ns")  # hold reset for 20ns
    await RisingEdge(dut.clk_in)
    dut.rst_in.value = 0
    await RisingEdge(dut.clk_in)
    dut.encoder_data_in.value = 0xA5A5A5A5A5A5A5A5
    dut.encoder_control_in.value = 0x00  # All data

    await RisingEdge(dut.clk_in)
    # Log inputs for data encoding test
    dut._log.info(f"Data Encoding Test:\n"
                  f"  encoder_data_in: {hex(int(dut.encoder_data_in.value))}\n"
                  f"  encoder_control_in: {bin(int(dut.encoder_control_in.value))}")

    # Apply test and check output
    await check_output(dut, expected_sync=0b01, expected_data=0xA5A5A5A5A5A5A5A5)

@cocotb.test()
async def control_encoding_test(dut):
    """ Test encoding when control characters are in the last four octets """
    clock = Clock(dut.clk_in, 10, unit="ns")  # 100 MHz
    cocotb.start_soon(clock.start())
    # Initialize DUT inputs
    await dut_initialization(dut)
    
    await Timer(20, unit="ns")  # hold reset for 20ns
    await RisingEdge(dut.clk_in)
    dut.rst_in.value = 0
    await RisingEdge(dut.clk_in)
    # Set test inputs
    dut.encoder_data_in.value = 0xFFFFFFFFFFFFFFFF
    dut.encoder_control_in.value = 0x0F  # Control in last four octets

    await RisingEdge(dut.clk_in)
    # Log inputs for control encoding test
    dut._log.info(f"Control Encoding Test:\n"
                  f"  encoder_data_in: {hex(int(dut.encoder_data_in.value))}\n"
                  f"  encoder_control_in: {bin(int(dut.encoder_control_in.value))}")

    # Apply test and check output
    await check_output(dut, expected_sync=0b10, expected_data=0x0000000000000000)  # Expected data output is zero

@cocotb.test()
async def mixed_data_control_test(dut):
    """ Test encoding when control characters are mixed in the data """
    clock = Clock(dut.clk_in, 10, unit="ns")  # 100 MHz
    cocotb.start_soon(clock.start())

    # Initialize DUT inputs
    await dut_initialization(dut)

    await Timer(20, unit="ns")  # hold reset for 20ns
    await RisingEdge(dut.clk_in)
    dut.rst_in.value = 0
    await RisingEdge(dut.clk_in)

    # Set test inputs
    dut.encoder_data_in.value = 0x123456789ABCDEF0
    dut.encoder_control_in.value = 0x81  # Control in first and last octets

    await RisingEdge(dut.clk_in)
    # Log inputs for mixed data and control test
    dut._log.info(f"Mixed Data and Control Test:\n"
                  f"  encoder_data_in: {hex(int(dut.encoder_data_in.value))}\n"
                  f"  encoder_control_in: {bin(int(dut.encoder_control_in.value))}")

    # Apply test and check output
    await RisingEdge(dut.clk_in)
    await check_output(dut, expected_sync=0b10, expected_data=0x0000000000000000)  # Expected data output is zero

@cocotb.test()
async def all_control_symbols_test(dut):
    """ Test encoding when all characters are control """
    clock = Clock(dut.clk_in, 10, unit="ns")  # 100 MHz
    cocotb.start_soon(clock.start())

    # Initialize DUT inputs
    await dut_initialization(dut)

    await Timer(20, unit="ns")  # hold reset for 20ns
    await RisingEdge(dut.clk_in)
    dut.rst_in.value = 0
    await RisingEdge(dut.clk_in)

    # Set test inputs
    dut.encoder_data_in.value = 0xA5A5A5A5A5A5A5A5
    dut.encoder_control_in.value = 0xFF  # All control

    await RisingEdge(dut.clk_in)
    # Log inputs for all control symbols test
    dut._log.info(f"All Control Symbols Test:\n"
                  f"  encoder_data_in: {hex(int(dut.encoder_data_in.value))}\n"
                  f"  encoder_control_in: {bin(int(dut.encoder_control_in.value))}")

    # Apply test and check output
    await check_output(dut, expected_sync=0b10, expected_data=0x0000000000000000)  # Expected data output is zero

@cocotb.test()
async def random_data_control_test(dut):
    """ Test encoding with random data and control inputs """
    clock = Clock(dut.clk_in, 10, unit="ns")  # 100 MHz
    cocotb.start_soon(clock.start())

    # Initialize DUT inputs
    await dut_initialization(dut)
    
    await Timer(20, unit="ns")  # hold reset for 20ns
    await RisingEdge(dut.clk_in)
    dut.rst_in.value = 0
    await RisingEdge(dut.clk_in)

    for i in range(5):  # Run 5 random tests
        # Generate random data and control inputs
        random_data = random.getrandbits(64)
        random_control = random.getrandbits(8)

        dut.encoder_data_in.value = random_data
        dut.encoder_control_in.value = random_control

        # Determine expected sync word and data based on control input
        expected_sync = 0b01 if random_control == 0 else 0b10
        expected_data = random_data if random_control == 0 else 0x0000000000000000

        await RisingEdge(dut.clk_in)
        # Log inputs for each random test
        dut._log.info(f"Random Test {i+1}:\n"
                      f"  encoder_data_in: {hex(int(dut.encoder_data_in.value))}\n"
                      f"  encoder_control_in: {bin(int(dut.encoder_control_in.value))}")

        await check_output(dut, expected_sync=expected_sync, expected_data=expected_data)

        await Timer(10, unit="ns")  # Wait for next random test

    dut._log.info("Randomized tests completed successfully")

@cocotb.test()
async def random_data_only_test(dut):
    """ Test encoding with random data and control inputs """
    clock = Clock(dut.clk_in, 10, unit="ns")  # 100 MHz
    cocotb.start_soon(clock.start())

    # Initialize DUT inputs
    await dut_initialization(dut)
    
    await Timer(20, unit="ns")  # hold reset for 20ns
    await RisingEdge(dut.clk_in)
    dut.rst_in.value = 0
    dut.encoder_control_in.value = 0  # All data
    await RisingEdge(dut.clk_in)

    for i in range(5):  # Run 5 random tests
        # Generate random data
        random_data = random.getrandbits(64)
        dut.encoder_data_in.value = random_data

        # Determine expected sync word and data
        expected_sync = 0b01
        expected_data = random_data

        await RisingEdge(dut.clk_in)
        # Log inputs for each random test
        dut._log.info(f"Random Test {i+1}:\n"
                      f"  encoder_data_in: {hex(int(dut.encoder_data_in.value))}\n"
                      f"  encoder_control_in: {bin(int(dut.encoder_control_in.value))}")

        await check_output(dut, expected_sync=expected_sync, expected_data=expected_data)

        await Timer(10, unit="ns")  # Wait for next random test

    dut._log.info("Randomized tests completed successfully")

@cocotb.test()
async def tc1_data_encoding_bug_test(dut):
    """ Test encoding when all data octets are pure data """
    clock = Clock(dut.clk_in, 10, unit="ns")  # 100 MHz
    cocotb.start_soon(clock.start())
    # Initialize DUT inputs
    await dut_initialization(dut)

    await Timer(20, unit="ns")  # hold reset for 20ns
    await RisingEdge(dut.clk_in)
    dut.rst_in.value = 0
    await RisingEdge(dut.clk_in)
    dut.encoder_data_in.value = 0xFEDCBA9876543210
    dut.encoder_control_in.value = 0x00  # All data

    await RisingEdge(dut.clk_in)
    # Log inputs for data encoding test
    dut._log.info(f"Data Encoding Test:\n"
                  f"  encoder_data_in: {hex(int(dut.encoder_data_in.value))}\n"
                  f"  encoder_control_in: {bin(int(dut.encoder_control_in.value))}")

    # Apply test and check output
    await check_output(dut, expected_sync=0b01, expected_data=0xFEDCBA9876543210)
    
    await RisingEdge(dut.clk_in)
    # Set test inputs
    dut.encoder_data_in.value = 0xA5A5A5A5A5A5A5A5
    dut.encoder_control_in.value = 0xFF  # All control

    await RisingEdge(dut.clk_in)
    # Log inputs for all control symbols test
    dut._log.info(f"All Control Symbols Test:\n"
                  f"  encoder_data_in: {hex(int(dut.encoder_data_in.value))}\n"
                  f"  encoder_control_in: {bin(int(dut.encoder_control_in.value))}")

    # Apply test and check output
    await check_output(dut, expected_sync=0b10, expected_data=0x0000000000000000)  # Expected data output is zero

@cocotb.test()
async def tc2_reset_bug_test(dut):
    """ Test encoding when all data octets are pure data """
    clock = Clock(dut.clk_in, 10, unit="ns")  # 100 MHz
    cocotb.start_soon(clock.start())
    # Initialize DUT inputs
    await dut_initialization(dut)

    await Timer(20, unit="ns")  # hold reset for 20ns
    await RisingEdge(dut.clk_in)
    await RisingEdge(dut.clk_in)
    dut.encoder_data_in.value = 0xA5A5A5A5A5A5A5A5
    dut.encoder_control_in.value = 0x00  # All data

    await RisingEdge(dut.clk_in)
    # Log inputs for data encoding test
    dut._log.info(f"Data Encoding Test:\n"
                  f"  encoder_data_in: {hex(int(dut.encoder_data_in.value))}\n"
                  f"  encoder_control_in: {bin(int(dut.encoder_control_in.value))}")

    # Apply test and check output
    await check_output(dut, expected_sync=0b00, expected_data=0x0000000000000000)

    await RisingEdge(dut.clk_in)
    dut.rst_in.value = 0
    await RisingEdge(dut.clk_in)
    dut.encoder_data_in.value = 0xA5A5A5A5A5A5A5A5
    dut.encoder_control_in.value = 0x00  # All data

    await RisingEdge(dut.clk_in)
    # Log inputs for data encoding test
    dut._log.info(f"Data Encoding Test:\n"
                  f"  encoder_data_in: {hex(int(dut.encoder_data_in.value))}\n"
                  f"  encoder_control_in: {bin(int(dut.encoder_control_in.value))}")

    # Apply test and check output
    await check_output(dut, expected_sync=0b01, expected_data=0xA5A5A5A5A5A5A5A5)

@cocotb.test()
async def tc3_stuck_at_zero_bug_test(dut):
    """ Test encoding when all data octets are pure data """
    clock = Clock(dut.clk_in, 10, unit="ns")  # 100 MHz
    cocotb.start_soon(clock.start())
    # Initialize DUT inputs
    await dut_initialization(dut)

    await Timer(20, unit="ns")  # hold reset for 20ns
    await RisingEdge(dut.clk_in)
    dut.rst_in.value = 0
    await RisingEdge(dut.clk_in)
    dut.encoder_data_in.value = 0x123456789ABCDEF0
    dut.encoder_control_in.value = 0x00  # All data

    await RisingEdge(dut.clk_in)
    # Log inputs for data encoding test
    dut._log.info(f"Data Encoding Test:\n"
                  f"  encoder_data_in: {hex(int(dut.encoder_data_in.value))}\n"
                  f"  encoder_control_in: {bin(int(dut.encoder_control_in.value))}")

    # Apply test and check output
    await check_output(dut, expected_sync=0b01, expected_data=0x123456789ABCDEF0)
    
    await RisingEdge(dut.clk_in)
    # Set test inputs
    dut.encoder_data_in.value = 0xFEDCBA9876543210
    dut.encoder_control_in.value = 0xFF  # All control

    await RisingEdge(dut.clk_in)
    # Log inputs for all control symbols test
    dut._log.info(f"All Control Symbols Test:\n"
                  f"  encoder_data_in: {hex(int(dut.encoder_data_in.value))}\n"
                  f"  encoder_control_in: {bin(int(dut.encoder_control_in.value))}")

    # Apply test and check output
    await check_output(dut, expected_sync=0b10, expected_data=0x0000000000000000)  # Expected data output is zero


@cocotb.test()
async def test_encoder_all_control_combinations(dut):
    """Cocotb test for 64b/66b encoder with full test cases and expected outputs"""

    # Start the clock
    clock = Clock(dut.clk_in, 10, unit="ns")  # 100 MHz
    cocotb.start_soon(clock.start())
    # Initialize DUT inputs
    await dut_initialization(dut)

    await RisingEdge(dut.clk_in)
    await RisingEdge(dut.clk_in)
    dut.rst_in.value = 0
    await RisingEdge(dut.clk_in)

    # Test cases with expected values
    test_cases = [
        (0x0707070707070707, 0b11111111, 0x21e00000000000000),
        (0x070707070707FDAE, 0b11111110, 0x299000000000000ae),
        (0x0707070707FDA5A5, 0b11111100, 0x2aa0000000000a5a5),
        (0x07070707FDFEED55, 0b11111000, 0x2b400000000feed55),
        (0x070707FD99887766, 0b11110000, 0x2cc00000099887766),
        (0x0707FDAABBCCDDEE, 0b11100000, 0x2d20000aabbccddee),
        (0x07FDAAAAAA555555, 0b11000000, 0x2e100aaaaaa555555),
        (0xFD773388229911AA, 0b10000000, 0x2ff773388229911aa),
        (0xDDCCBBFB07070707, 0b00011111, 0x233ddccbb00000000),
        (0x0707079C0707079C, 0b00010001, 0x255070707ff070707),
        (0x3456789ABCDEF0FB, 0b00000001, 0x2783456789abcdef0),
        (0x777777FBDEEDDE9C, 0b00010001, 0x2667777770fdeedde),
        (0x07070707ABCDEF9C, 0b11110001, 0x24b0000000abcdeff),
        (0xAAAAAA9C07070707, 0b00011111, 0x22daaaaaaf0000000),
        (0xFEFEFEFEFEFEFEFE, 0b11111111, 0x21e3c78f1e3c78f1e),
        (0x07070707070707FD, 0b11111111, 0x28700000000000000),
    ]

    # Apply test cases and compare DUT output with expected values
    for idx, (data_in, control_in, expected_output) in enumerate(test_cases):
        # Apply inputs
        await RisingEdge(dut.clk_in)
        dut.encoder_data_in.value = data_in
        dut.encoder_control_in.value = control_in

        # Wait for a clock cycle
        await RisingEdge(dut.clk_in)
        await RisingEdge(dut.clk_in)

        # Get DUT output
        dut_output = int(dut.encoder_data_out.value)

        # Compare DUT output with expected output
        assert dut_output == expected_output, (
            f"Test case {idx+1} failed: "
            f"Data: {hex(data_in)}, Control: {bin(control_in)}, "
            f"Expected: {hex(expected_output)}, Got: {hex(dut_output)}"
        )

        dut._log.info(
            f"Test Case {idx + 1}:\n"
            f"  encoder_data_in: {hex(data_in)}\n"
            f"  encoder_control_in: {bin(control_in)}\n"
            f"  encoder_data_out (DUT): {hex(dut_output)}\n"
            f"  Expected: {hex(expected_output)}"
        )

@cocotb.test()
async def test_encoder_all_octets_control(dut):
    """Cocotb test for 64b/66b encoder with full test cases and expected outputs"""

    # Start the clock
    clock = Clock(dut.clk_in, 10, unit="ns")  # 100 MHz
    cocotb.start_soon(clock.start())
    # Initialize DUT inputs
    await dut_initialization(dut)

    await RisingEdge(dut.clk_in)
    await RisingEdge(dut.clk_in)
    dut.rst_in.value = 0
    await RisingEdge(dut.clk_in)

    # Test cases with expected values
    test_cases = [
        (0x0707070707070707, 0b11111111, 0x21e00000000000000),
        (0xFEFEFEFEFEFEFEFE, 0b11111111, 0x21e3c78f1e3c78f1e),
        (0x07070707070707FD, 0b11111111, 0x28700000000000000),
    ]

    # Apply test cases and compare DUT output with expected values
    for idx, (data_in, control_in, expected_output) in enumerate(test_cases):
        # Apply inputs
        await RisingEdge(dut.clk_in)
        dut.encoder_data_in.value = data_in
        dut.encoder_control_in.value = control_in

        # Wait for a clock cycle
        await RisingEdge(dut.clk_in)
        await RisingEdge(dut.clk_in)

        # Get DUT output
        dut_output = int(dut.encoder_data_out.value)

        # Compare DUT output with expected output
        assert dut_output == expected_output, (
            f"Test case {idx+1} failed: "
            f"Data: {hex(data_in)}, Control: {bin(control_in)}, "
            f"Expected: {hex(expected_output)}, Got: {hex(dut_output)}"
        )

        dut._log.info(
            f"Test Case {idx + 1}:\n"
            f"  encoder_data_in: {hex(data_in)}\n"
            f"  encoder_control_in: {bin(control_in)}\n"
            f"  encoder_data_out (DUT): {hex(dut_output)}\n"
            f"  Expected: {hex(expected_output)}"
        )

@cocotb.test()
async def test_encoder_mixed_data_control_octets(dut):
    """Cocotb test for 64b/66b encoder with full test cases and expected outputs"""

    # Start the clock
    clock = Clock(dut.clk_in, 10, unit="ns")  # 100 MHz
    cocotb.start_soon(clock.start())
    # Initialize DUT inputs
    await dut_initialization(dut)

    await RisingEdge(dut.clk_in)
    await RisingEdge(dut.clk_in)
    dut.rst_in.value = 0
    await RisingEdge(dut.clk_in)

    # Test cases with expected values
    test_cases = [
        (0x070707070707FDAE, 0b11111110, 0x299000000000000ae),
        (0x0707070707FDA5A5, 0b11111100, 0x2aa0000000000a5a5),
        (0x07070707FDFEED55, 0b11111000, 0x2b400000000feed55),
        (0x070707FD99887766, 0b11110000, 0x2cc00000099887766),
        (0x0707FDAABBCCDDEE, 0b11100000, 0x2d20000aabbccddee),
        (0x07FDAAAAAA555555, 0b11000000, 0x2e100aaaaaa555555),
        (0xFD773388229911AA, 0b10000000, 0x2ff773388229911aa),
        (0xDDCCBBFB07070707, 0b00011111, 0x233ddccbb00000000),
        (0x0707079C0707079C, 0b00010001, 0x255070707ff070707),
        (0x3456789ABCDEF0FB, 0b00000001, 0x2783456789abcdef0),
        (0x777777FBDEEDDE9C, 0b00010001, 0x2667777770fdeedde),
        (0x07070707ABCDEF9C, 0b11110001, 0x24b0000000abcdeff),
        (0xAAAAAA9C07070707, 0b00011111, 0x22daaaaaaf0000000),
    ]


    # Apply test cases and compare DUT output with expected values
    for idx, (data_in, control_in, expected_output) in enumerate(test_cases):
        # Apply inputs
        await RisingEdge(dut.clk_in)
        dut.encoder_data_in.value = data_in
        dut.encoder_control_in.value = control_in

        # Wait for a clock cycle
        await RisingEdge(dut.clk_in)
        await RisingEdge(dut.clk_in)

        # Get DUT output
        dut_output = int(dut.encoder_data_out.value)

        # Compare DUT output with expected output
        assert dut_output == expected_output, (
            f"Test case {idx+1} failed: "
            f"Data: {hex(data_in)}, Control: {bin(control_in)}, "
            f"Expected: {hex(expected_output)}, Got: {hex(dut_output)}"
        )

        dut._log.info(
            f"Test Case {idx + 1}:\n"
            f"  encoder_data_in: {hex(data_in)}\n"
            f"  encoder_control_in: {bin(control_in)}\n"
            f"  encoder_data_out (DUT): {hex(dut_output)}\n"
            f"  Expected: {hex(expected_output)}"
        )
    dut._log.info("All test cases passed!")
