import cocotb
from cocotb.triggers import Timer
import random

def gf_8bit_mult(a, b):
    """Performs GF(2^8) multiplication using the irreducible polynomial 0x11B."""
    p = 0
    for _ in range(8):
        if b & 1:
            p ^= a
        carry = a & 0x80
        a = (a << 1) & 0xFF
        if carry:
            a ^= 0x1B  # Irreducible polynomial for GF(2^8)
        b >>= 1
    return p

def calculate_expected_gf_result(a, b, width):
    """Calculates the expected result by performing segment-wise GF(2^8) multiplication and XOR."""
    segments = width // 8
    result = 0
    for i in range(segments):
        a_segment = (a >> (i * 8)) & 0xFF
        b_segment = (b >> (i * 8)) & 0xFF
        segment_result = gf_8bit_mult(a_segment, b_segment)
        result ^= segment_result
    return result

async def run_test(dut, a_value, b_value):
    """Helper function to run a test case with specified a and b values."""

    # Retrieve WIDTH from the DUT
    width = int(dut.WIDTH.value)
    dut._log.info(f"Testing gf_mac with WIDTH={width}, A=0x{a_value:X}, B=0x{b_value:X}")

    # Apply inputs to the DUT
    dut.a.value = a_value
    dut.b.value = b_value
    await Timer(10, unit="ns")  # Wait for combinational logic to settle

    # Read outputs from the DUT
    error_flag = int(dut.error_flag.value)
    valid_result = int(dut.valid_result.value)

    if width % 8 != 0 or width == 0:
        # Expecting an error
        dut._log.info(f"Error flag value: {error_flag}, Valid result: {valid_result}")
        assert error_flag == 1, f"Error flag should be set for invalid WIDTH={width}"
        assert valid_result == 0, "Valid result should be 0 when error_flag is set"
        dut._log.info(f"Test passed for invalid WIDTH={width}: error_flag correctly set")
    else:
        # Valid WIDTH, check the result
        dut._log.info(f"Error flag value: {error_flag}, Valid result: {valid_result}")
        assert error_flag == 0, f"Error flag should not be set for valid WIDTH={width}"
        assert valid_result == 1, "Valid result should be 1 when error_flag is not set"

        # Calculate expected result using the helper function
        expected_result = calculate_expected_gf_result(a_value, b_value, width)

        # Retrieve the actual result from the DUT
        actual_result = int(dut.result.value)
        dut._log.info(f"Expected Result: 0x{expected_result:02X}, Actual Result: 0x{actual_result:02X}")

        # Check if the actual result matches the expected result
        assert actual_result == expected_result, (
            f"Test failed for WIDTH={width}: expected 0x{expected_result:02X}, got 0x{actual_result:02X}"
        )
        dut._log.info(f"Test passed for WIDTH={width} with result: 0x{actual_result:02X}")

@cocotb.test()
async def test_gf_mac(dut):
    """Test the gf_mac module with the WIDTH specified at build time."""

    # Retrieve WIDTH from the DUT
    width = int(dut.WIDTH.value)
    dut._log.info(f"Testing gf_mac with WIDTH={width}")

    # Generate test values for 'a' and 'b' within the specified width
    max_val = (1 << width) - 1 if width > 0 else 0

    # List of test input patterns
    test_inputs = [
        (0, 0),                            # Both inputs zero
        (max_val, max_val),                # Both inputs max value
        (0xAAAAAAAAAAAAAAAAAAAAAAAA, 0x55555555555555555555),  # Alternating bits
        (random.randint(0, max_val), random.randint(0, max_val)),  # Random values
    ]

    for a_value, b_value in test_inputs:
        # Ensure that values are within the valid range
        a_value &= max_val
        b_value &= max_val

        await run_test(dut, a_value, b_value)
