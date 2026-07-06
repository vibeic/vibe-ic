import asyncio
import random
import cocotb
from cocotb.triggers import Timer
import math

class UpdatedHammingTX:
    def __init__(self, data_width=4, parity_bit=3):
        self.DATA_WIDTH = data_width
        self.PARITY_BIT = parity_bit
        self.ENCODED_DATA = self.PARITY_BIT + self.DATA_WIDTH + 1
        self.ENCODED_DATA_BIT = math.ceil(math.log2(self.ENCODED_DATA))
    
    def encode(self, data_in):
        data_out = [0] * self.ENCODED_DATA
        parity = [0] * self.ENCODED_DATA_BIT
        temp = [[0] * self.ENCODED_DATA_BIT for _ in range(self.ENCODED_DATA)]
        
        # Step 1: Clear all internal register
        count = 0
        
        # Step 2: Assign data_in to data_out with spaces for parity bits
        for i in range(self.ENCODED_DATA):
            if (i & (i - 1)) == 0 and i != 0:  # Check if i is a power of 2
                data_out[i] = data_out[i]
            elif i == 0:
                data_out[i] = 0  # Default value for data_out[0]
            else:
                data_out[i] = (data_in >> count) & 1
                count = (count + 1) % self.DATA_WIDTH

            temp[i] = i

        # Step 3: Calculate even parity for Hamming code
        for j in range(self.ENCODED_DATA_BIT):
            for k in range(self.ENCODED_DATA):
                if (temp[k] >> j) & 1:
                    parity[j] ^= data_out[k]
        
        count = 0
        
        # Step 4: Assign calculated parity bits to data_out
        for l in range(self.ENCODED_DATA):
            if (l & (l - 1)) == 0 and l != 0:
                data_out[l] = parity[count]
                count += 1

        # Convert data_out list to integer
        encoded_data = 0
        for i, bit in enumerate(data_out):
            encoded_data |= (bit << i)

        return encoded_data

@cocotb.test()
async def tx_test(dut): 

    # Retrieve data_width and parity_bit as integers
    data_width = int(dut.DATA_WIDTH.value)
    part_width = int(dut.PART_WIDTH.value)
    num_modules = int(dut.NUM_MODULES.value)
    parity_bit = int(dut.PARITY_BIT.value)
    encoded_data = int(dut.ENCODED_DATA.value)
    
    hamming_tx = UpdatedHammingTX(data_width=part_width, parity_bit=parity_bit)  
    
    total_encoded = int(dut.TOTAL_ENCODED.value)
    
    for i in range(10):
        # Generate a random data input based on data_width
        data_in = random.randint(0, (1 << data_width) - 1)  # Random integer within the allowed range
    
        # Convert data_in to a binary string, padded to the data_width
        data_in_bin = f"{data_in:0{data_width}b}"
        
        # Initialize the list to store encoded parts
        encoded_outputs = []
        
        # Loop through each split based on NUM_MODULES
        for i1 in range(num_modules):
            # Slice the input data to get the part for this module
            start_idx = i1 * part_width
            end_idx = (i1 + 1) * part_width
            part = data_in_bin[start_idx:end_idx]
    
            # Encode the part using the Hamming encoder (assuming golden_hamming_tx is a function)
            encoded_part = hamming_tx.encode(int(part, 2))  # Assuming this function exists and encodes the part
    
            # Append the encoded part to the outputs list
            encoded_outputs.append(f"{encoded_part:0{encoded_data}b}")

            # Concatenate the encoded parts into a single binary string
        concatenated_output = ''.join(encoded_outputs)

            # Print the final concatenated output (encoded)
        #print(f"Concatenated encoded output: {concatenated_output}")
        
        
        # Set the modified data to dut input
        dut.data_in.value = data_in_bin
        await Timer(10, unit="ns")
        
        # Convert concatenated_output from a binary string to an integer
        expected_data_out_int = int(concatenated_output, 2)

        # Retrieve DUT output as integer
        actual_data_out_int = int(dut.data_out.value)

        # Perform the assertion with integer values
        assert actual_data_out_int == expected_data_out_int, (
                   f"FAIL: Random Test {i+1}: Corrected data does not match expected: "
                   f"{actual_data_out_int:0{total_encoded}b} != {expected_data_out_int:0{total_encoded}b}"
                 )

        dut._log.info(
                f"PASS: Random Test {i+1} - Original data: {data_in}, "
                f"Actual: {actual_data_out_int:0{total_encoded}b}, "
                f"Expected: {concatenated_output}"
               )

        dut._log.info("-" * 40)

