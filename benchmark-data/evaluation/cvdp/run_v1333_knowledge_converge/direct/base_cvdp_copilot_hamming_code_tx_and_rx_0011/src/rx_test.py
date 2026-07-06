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
async def rx_test(dut): 

    # Retrieve data_width and parity_bit as integers
    data_width = int(dut.DATA_WIDTH.value)
    parity_bit = int(dut.PARITY_BIT.value)
    hamming_tx = UpdatedHammingTX(data_width=data_width, parity_bit=parity_bit)  
    
    for i in range(10):
        # Generate a random binary string for data_in based on data_width
        data_in = ''.join(str(random.randint(0, 1)) for _ in range(data_width))
        
        # Convert data_in to integer for processing
        data_in_int = int(data_in, 2)
        
        # Encode data_in using the Hamming TX encoder
        encoded_output = hamming_tx.encode(data_in_int)
        
        # Convert encoded_output to a binary list for manipulation
        encoded_output_list = list(f"{encoded_output:0{hamming_tx.ENCODED_DATA}b}")
        
        # Modify one bit
        bit_to_flip = random.randint(0, int(dut.ENCODED_DATA.value) - 1)
        encoded_output_list[bit_to_flip] = str(1 - int(encoded_output_list[bit_to_flip]))
        
        # Convert modified data back to integer
        modified_data = int("".join(encoded_output_list), 2)
        
        # Set the modified data to dut input
        dut.data_in.value = modified_data
        await Timer(5, unit="ns")
        
        # Expected output for comparison
        expected_data_out_int = data_in_int  # Use data_in_int instead of data_in string
        
        # Retrieve dut output as integer
        actual_data_out_int = int(dut.data_out.value)
        
        # Perform the assertion with integer values
        assert actual_data_out_int == expected_data_out_int, (
                f"Random Test {i+1}: Corrected data does not match expected: "
                f"{actual_data_out_int:0{data_width}b} != {expected_data_out_int:0{data_width}b}"
            )
        
        dut._log.info(
            f"Random Test {i+1} - Original data: {data_in_int:0{data_width}b}, Transmitted: {encoded_output:0{hamming_tx.ENCODED_DATA}b}, "
            f"Modified: {modified_data:0{hamming_tx.ENCODED_DATA}b}, Corrected data: {actual_data_out_int:0{data_width}b}"
        )

        dut._log.info("-" * 40)

