import cocotb
from cocotb.triggers import Timer
import os

def calculate_expected_gf_result(a, b, width):
    """ Calculate the expected result for Galois Field multiplication by simulating segment-wise XOR """
    segments = width // 8
    result = 0
    cocotb.log.info(f"Calculating expected GF multiplication result for WIDTH={width} (in 8-bit segments)")
    for i in range(segments):
        a_segment = (a >> (i * 8)) & 0xFF
        b_segment = (b >> (i * 8)) & 0xFF
        segment_result = gf_8bit_mult(a_segment, b_segment)
        cocotb.log.info(f"Segment {i+1}: a_segment={hex(a_segment)}, b_segment={hex(b_segment)}, "
                        f"segment_result={hex(segment_result)}")
        result ^= segment_result
        cocotb.log.info(f"After XORing segment {i+1}: intermediate result={hex(result)}")
    cocotb.log.info(f"Final calculated expected result: {hex(result)}")
    return result

def gf_8bit_mult(a, b):
    """ GF(2^8) multiplication using irreducible polynomial 0x11B """
    p = 0
    for i in range(8):
        if b & 1:
            p ^= a
        carry = a & 0x80
        a = (a << 1) & 0xFF
        if carry:
            a ^= 0x1B  # Irreducible polynomial for GF(2^8)
        b >>= 1
    return p

@cocotb.test()
async def test_gf_multiplier(dut):
    """ Test Galois Field Multiplier with calculated expected result for any 8-bit multiple width """
    
    # Retrieve WIDTH parameter from environment
    width = int(os.getenv("WIDTH", 32))
    if width % 8 != 0:
        raise ValueError(f"Invalid WIDTH={width}. WIDTH must be a multiple of 8.")
    
    # Generate random test values for a and b within the specified width
    max_val = (1 << width) - 1  # Maximum value for the given width
    a = int.from_bytes(os.urandom(width // 8), 'big') & max_val
    b = int.from_bytes(os.urandom(width // 8), 'big') & max_val
    
    # Calculate expected result using the helper method
    expected_result = calculate_expected_gf_result(a, b, width)
    dut._log.info(f"Testing GF multiplier with WIDTH={width}, A={hex(a)}, B={hex(b)}, Calculated Expected={hex(expected_result)}")

    # Apply inputs to DUT
    dut.a.value = a
    dut.b.value = b
    await Timer(10, unit="ns")  # Wait for combinational logic to settle

    # Check if the actual result matches the calculated expected result
    actual_result = int(dut.result.value)
    dut._log.info(f"Expected: {hex(expected_result)}, Actual: {hex(actual_result)}")
    assert actual_result == expected_result, \
        f"Test failed for WIDTH={width}: expected {hex(expected_result)}, got {hex(actual_result)}"

    dut._log.info(f"Test passed for WIDTH={width} with result: {hex(actual_result)}")

@cocotb.test()
async def test_all_zeros(dut):
    """ Test with all-zero input for A and B """
    width = int(os.getenv("WIDTH", 32))
    a = 0x0
    b = 0x0
    expected_result = calculate_expected_gf_result(a, b, width)
    dut._log.info(f"Testing all-zero input: A={hex(a)}, B={hex(b)}, Expected={hex(expected_result)}")
    dut.a.value = a
    dut.b.value = b
    await Timer(10, unit="ns")
    actual_result = int(dut.result.value)
    assert actual_result == expected_result, f"Expected {hex(expected_result)}, got {hex(actual_result)}"
    dut._log.info("All-zero test passed.")

@cocotb.test()
async def test_single_bit(dut):
    """ Test with single-bit set in A and B """
    width = int(os.getenv("WIDTH", 32))
    a = 1 << (width - 1)
    b = 1
    expected_result = calculate_expected_gf_result(a, b, width)
    dut._log.info(f"Testing single-bit input: A={hex(a)}, B={hex(b)}, Expected={hex(expected_result)}")
    dut.a.value = a
    dut.b.value = b
    await Timer(10, unit="ns")
    actual_result = int(dut.result.value)
    assert actual_result == expected_result, f"Expected {hex(expected_result)}, got {hex(actual_result)}"
    dut._log.info("Single-bit test passed.")

@cocotb.test()
async def test_alternating_bits(dut):
    """ Test with alternating bits pattern in A and B """
    width = int(os.getenv("WIDTH", 32))
    a = int('AA' * (width // 8), 16)  # e.g., 0xAAAAAAAA... for the given width
    b = int('55' * (width // 8), 16)  # e.g., 0x55555555... for the given width
    expected_result = calculate_expected_gf_result(a, b, width)
    dut._log.info(f"Testing alternating bits input: A={hex(a)}, B={hex(b)}, Expected={hex(expected_result)}")
    dut.a.value = a
    dut.b.value = b
    await Timer(10, unit="ns")
    actual_result = int(dut.result.value)
    assert actual_result == expected_result, f"Expected {hex(expected_result)}, got {hex(actual_result)}"
    dut._log.info("Alternating-bits test passed.")

@cocotb.test()
async def test_maximum_values(dut):
    """ Test with maximum values for A and B """
    width = int(os.getenv("WIDTH", 32))
    a = (1 << width) - 1  # Maximum possible value for given width
    b = (1 << width) - 1
    expected_result = calculate_expected_gf_result(a, b, width)
    dut._log.info(f"Testing maximum values input: A={hex(a)}, B={hex(b)}, Expected={hex(expected_result)}")
    dut.a.value = a
    dut.b.value = b
    await Timer(10, unit="ns")
    actual_result = int(dut.result.value)
    assert actual_result == expected_result, f"Expected {hex(expected_result)}, got {hex(actual_result)}"
    dut._log.info("Maximum values test passed.")
