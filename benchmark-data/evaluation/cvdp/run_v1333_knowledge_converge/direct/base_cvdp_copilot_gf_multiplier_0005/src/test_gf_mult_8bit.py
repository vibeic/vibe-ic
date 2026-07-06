import cocotb
from cocotb.triggers import Timer
import random

# Function to perform GF(2^8) multiplication with polynomial reduction
def gf_mult(a, b):
    irreducible_poly = 0b100011011  # x^8 + x^4 + x^3 + x + 1 (100011011 in binary)
    result = 0

    print(f"Calculating GF(2^8) multiplication for A = {a:08b}, B = {b:08b}")
    
    # Perform multiplication using shift-and-add method
    for i in range(8):  # 8-bit multiplication
        if (b >> i) & 1:
            result ^= a << i  # Add shifted multiplicand
            print(f"  - Bit {i} of B is 1: result = result XOR (A << {i}) = {result:016b}")

    # Perform polynomial reduction if the result exceeds 8 bits
    print(f"  Before reduction: result = {result:016b}")
    for i in range(15, 7, -1):  # Start checking from bit 15 down to bit 8
        if result & (1 << i):  # If the bit is set
            result ^= irreducible_poly << (i - 8)  # XOR with irreducible polynomial
            print(f"  - Bit {i} of result is 1: result = result XOR (irreducible_poly << {i - 8}) = {result:016b}")

    final_result = result & 0xFF  # Return the final result (8 bits)
    print(f"  Final reduced result: {final_result:08b}\n")
    return final_result

# Test for GF(2^8) multiplier with known vectors
@cocotb.test()
async def gf_multiplier_basic_test(dut):
    """Test the GF(2^8) multiplier with known test vectors"""
    
    # Test vector: A = 0x57 (01010111), B = 0x83 (10000011)
    A = 0x57
    B = 0x83
    expected_result = gf_mult(A, B)
    dut.A.value = A
    dut.B.value = B
    await Timer(1, unit='ns')  # Small delay to allow propagation

    actual_result = int(dut.result.value)  # Convert LogicArray to integer
    cocotb.log.info(f"Basic Test: A = {A:02X}, B = {B:02X}, Expected = {expected_result:02X}, Actual = {actual_result:02X}")
    assert actual_result == expected_result, f"Test failed: {A:02X} * {B:02X} = {actual_result:02X}, expected {expected_result:02X}"

    # Additional tests with various known values
    # Test vector: A = 0xF0, B = 0x0F
    A = 0xF0
    B = 0x0F
    expected_result = gf_mult(A, B)
    dut.A.value = A
    dut.B.value = B
    await Timer(1, unit='ns')

    actual_result = int(dut.result.value)  # Convert LogicArray to integer
    cocotb.log.info(f"Basic Test: A = {A:02X}, B = {B:02X}, Expected = {expected_result:02X}, Actual = {actual_result:02X}")
    assert actual_result == expected_result, f"Test failed: {A:02X} * {B:02X} = {actual_result:02X}, expected {expected_result:02X}"

@cocotb.test()
async def gf_multiplier_random_test(dut):
    """Test the GF(2^8) multiplier with random values"""
    
    # Perform 20 random tests
    for i in range(20):
        A = random.randint(0, 255)  # Random 8-bit value
        B = random.randint(0, 255)  # Random 8-bit value
        print(f"Random Test {i + 1}: A = {A:08b}, B = {B:08b}")
        expected_result = gf_mult(A, B)  # Use the GF multiplication logic

        dut.A.value = A
        dut.B.value = B

        await Timer(1, unit='ns')  # Allow propagation delay

        actual_result = int(dut.result.value)  # Convert LogicArray to integer
        cocotb.log.info(f"Random Test {i + 1}: A = {A:02X}, B = {B:02X}, Expected = {expected_result:02X}, Actual = {actual_result:02X}")
        assert actual_result == expected_result, f"Random test failed: {A:02X} * {B:02X} = {actual_result:02X}, expected {expected_result:02X}"


@cocotb.test()
async def gf_multiplier_maximum_value_test(dut):
    """Test the GF(2^8) multiplier with known test vectors"""
    
    # Test vector: A = 0xFF (11111111), B = 0xFF (11111111)
    A = 0xFF
    B = 0xFF
    expected_result = gf_mult(A, B)
    dut.A.value = A
    dut.B.value = B
    await Timer(1, unit='ns')  # Small delay to allow propagation

    actual_result = int(dut.result.value)  # Convert LogicArray to integer
    cocotb.log.info(f"Basic Test: A = {A:02X}, B = {B:02X}, Expected = {expected_result:02X}, Actual = {actual_result:02X}")
    assert actual_result == expected_result, f"Test failed: {A:02X} * {B:02X} = {actual_result:02X}, expected {expected_result:02X}"


@cocotb.test()
async def gf_multiplier_zero_value_test(dut):
    """Test the GF(2^8) multiplier with known test vectors"""
    
    # Test vector: A = 0xFF (11111111), B = 0xFF (00000000)
    A = 0xFF
    B = 0x0
    expected_result = gf_mult(A, B)
    dut.A.value = A
    dut.B.value = B
    await Timer(1, unit='ns')  # Small delay to allow propagation

    actual_result = int(dut.result.value)  # Convert LogicArray to integer
    cocotb.log.info(f"Basic Test: A = {A:02X}, B = {B:02X}, Expected = {expected_result:02X}, Actual = {actual_result:02X}")
    assert actual_result == expected_result, f"Test failed: {A:02X} * {B:02X} = {actual_result:02X}, expected {expected_result:02X}"