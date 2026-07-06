import cocotb
from cocotb.triggers import Timer
import random

# Define the Hamming Code transmitter function in Python
def hamming_code_tx(data_in):
    """Hamming code transmission function for 4-bit input data."""
    data_out = [0] * 8
    data_out[7] = 0  # Assuming the parity bit for the whole message is zero for now
    data_out[6] = data_in[3] ^ data_in[2] ^ data_in[0]
    data_out[5] = data_in[3] ^ data_in[1] ^ data_in[0]
    data_out[4] = data_in[3]
    data_out[3] = data_in[2] ^ data_in[1] ^ data_in[0]
    data_out[2] = data_in[2]
    data_out[1] = data_in[1]
    data_out[0] = data_in[0]
    
    return data_out

@cocotb.test()
async def test_hamming_code_receiver(dut):
    """Cocotb testbench for the Hamming code receiver, including corner cases and randomized data input."""
    
    # Define specific corner cases
    corner_cases = [
        0b0000,  # All zeros
        0b1111,  # All ones
        0b0001,  # Single bit set
        0b0010,  # Single bit set
        0b0100,  # Single bit set
        0b1000,  # Single bit set
        0b1100,  # Multiple bits set
        0b1010,  # Alternating bits
    ]

    # Test each corner case
    for i, data_in in enumerate(corner_cases, start=1):
        # Generate transmitted data using Hamming code
        data_out = hamming_code_tx([int(x) for x in f"{data_in:04b}"])

        await Timer(10, unit="ns")

        # Modify one bit randomly in the transmitted data
        modified_data = list(data_out)  # Make a copy of data_out
        bit_to_flip = random.randint(0, 7)
        modified_data[bit_to_flip] = 1 - modified_data[bit_to_flip]
        
        # Send modified data to the receiver
        dut.data_in.value = int("".join(map(str, modified_data)), 2)
        await Timer(10, unit="ns")

        # Capture receiver outputs
        correct_data = int(dut.data_out.value)

        # Debug Logging Before Assertion
        dut._log.info(f"Test {i} - Modified Data: {''.join(map(str, modified_data))}, Bit to Flip: {bit_to_flip}")
        #dut._log.info(f"Test {i} - Correct Data: {correct_data:08b} ({correct_data}), Expected Data: {''.join(map(str, data_out[:7]))}")

        # Determine expected result based on the bit flipped
        # Standard comparison when bit_to_flip is not 7
        expected_data = int("".join(map(str, data_out)), 2)
        assert correct_data == data_in, f"Corner Case Test {i}: Corrected data does not match expected: {correct_data:04b} != {data_in:04b}"
        
        dut._log.info(f"Corner Case Test {i} - Original data: {data_in:04b}, Transmitted: {''.join(map(str, data_out))}, Modified: {''.join(map(str, modified_data))}, Corrected data: {correct_data:04b}")
        dut._log.info("-" * 40)

    # Randomized testing for 10 iterations
    for i in range(10):
        data_in = random.randint(0, 15)  # Generate random 4-bit data
        data_out = hamming_code_tx([int(x) for x in f"{data_in:04b}"])

        await Timer(10, unit="ns")

        # Modify one bit randomly in the transmitted data
        modified_data = list(data_out)
        bit_to_flip = random.randint(0, 7)
        modified_data[bit_to_flip] = 1 - modified_data[bit_to_flip]
        
        # Send modified data to the receiver
        dut.data_in.value = int("".join(map(str, modified_data)), 2)
        await Timer(10, unit="ns")

        # Capture receiver outputs
        correct_data = int(dut.data_out.value)

        # Debug Logging Before Assertion
        dut._log.info(f"Random Test {i+1} - Modified Data: {''.join(map(str, modified_data))}, Bit to Flip: {bit_to_flip}")
        #dut._log.info(f"Random Test {i+1} - Correct Data: {correct_data:08b} ({correct_data}), Expected Data: {''.join(map(str, data_out[:7]))}")

        expected_data = int("".join(map(str, data_out)), 2)
        assert correct_data == data_in, f"Random Test {i+1}: Corrected data does not match expected: {correct_data:04b} != {data_in:04b}"

        
        dut._log.info(f"Random Test {i+1} - Original data: {data_in:04b}, Transmitted: {''.join(map(str, data_out))}, Modified: {''.join(map(str, modified_data))}, Corrected data: {correct_data:04b}")
        dut._log.info("-" * 40)
    
    
    
