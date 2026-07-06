import cocotb
from cocotb.triggers import Timer
import random

# Function to perform GF(2^4) multiplication with polynomial reduction
def gf_mult(a, b):
    irreducible_poly = 0b10011  # x^4 + x + 1 (10011 in binary)
    result = 0

    print(f"Calculating GF(2^4) multiplication for A = {a:04b}, B = {b:04b}")
    
    # Perform multiplication using shift-and-add method
    for i in range(4):  # 4-bit multiplication
        if (b >> i) & 1:
            result ^= a << i  # Add shifted multiplicand
            print(f"  - Bit {i} of B is 1: result = result XOR (A << {i}) = {result:08b}")

    # Perform polynomial reduction if the result exceeds 4 bits
    print(f"  Before reduction: result = {result:08b}")
    for i in range(7, 3, -1):  # Start checking from bit 7 down to bit 4
        if result & (1 << i):  # If the bit is set
            result ^= irreducible_poly << (i - 4)  # XOR with irreducible polynomial
            print(f"  - Bit {i} of result is 1: result = result XOR (irreducible_poly << {i - 4}) = {result:08b}")

    final_result = result & 0b1111  # Return the final result (4 bits)
    print(f"  Final reduced result: {final_result:04b}\n")
    return final_result

# Test for GF(2^4) multiplier with known vectors
@cocotb.test()
async def gf_multiplier_basic_test(dut):
    """Test the GF multiplier with known test vectors"""
    
    # Test vector: A = 3 (0011), B = 1 (0001)
    A = 3
    B = 1
    expected_result = gf_mult(A, B)
    dut.A.value = A
    dut.B.value = B
    await Timer(1, unit='ns')  # Small delay to allow propagation

    actual_result = dut.result.value
    cocotb.log.info(f"Basic Test: A = {A}, B = {B}, Expected = {expected_result}, Actual = {actual_result}")
    assert actual_result == expected_result, f"Test failed: {A} * {B} = {actual_result}, expected {expected_result}"

    # Test vector: A = 3 (0011), B = 7 (0111)
    A = 3
    B = 7
    expected_result = gf_mult(A, B)
    dut.A.value = A
    dut.B.value = B
    await Timer(1, unit='ns')

    actual_result = dut.result.value
    cocotb.log.info(f"Basic Test: A = {A}, B = {B}, Expected = {expected_result}, Actual = {actual_result}")
    assert actual_result == expected_result, f"Test failed: {A} * {B} = {actual_result}, expected {expected_result}"

    # Test vector: A = 15 (1111), B = 15 (1111)
    A = 15
    B = 15
    expected_result = gf_mult(A, B)
    dut.A.value = A
    dut.B.value = B
    await Timer(1, unit='ns')

    actual_result = dut.result.value
    cocotb.log.info(f"Basic Test: A = {A}, B = {B}, Expected = {expected_result}, Actual = {actual_result}")
    assert actual_result == expected_result, f"Test failed: {A} * {B} = {actual_result}, expected {expected_result}"

@cocotb.test()
async def gf_multiplier_random_test(dut):
    """Test the GF multiplier with random values"""
    
    # Perform 20 random tests
    for i in range(20):
        A = random.randint(0, 15)  # Random 4-bit value
        B = random.randint(0, 15)  # Random 4-bit value
        print(f"Random Test {i + 1}: A = {A:04b}, B = {B:04b}")
        expected_result = gf_mult(A, B)  # Use the GF multiplication logic

        dut.A.value = A
        dut.B.value = B

        await Timer(1, unit='ns')  # Allow propagation delay

        actual_result = dut.result.value
        cocotb.log.info(f"Random Test {i + 1}: A = {A}, B = {B}, Expected = {expected_result}, Actual = {actual_result}")
        assert actual_result == expected_result, f"Random test failed: {A} * {B} = {actual_result}, expected {expected_result}"
