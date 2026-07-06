import asyncio 
import random
import cocotb
from cocotb.triggers import Timer

def calculate_data_out(data_in):
    # Convert data_in from string to binary list
    temp = [int(bit) for bit in data_in]
    
    # Initialize data_out as a list with default values
    data_out = [0] * 8
    data_out[7] = 0
    data_out[6] = temp[3] ^ temp[2] ^ temp[0]
    data_out[5] = temp[3] ^ temp[1] ^ temp[0]
    data_out[4] = temp[3]
    data_out[3] = temp[2] ^ temp[1] ^ temp[0]
    data_out[2] = temp[2]
    data_out[1] = temp[1]
    data_out[0] = temp[0]
    
    return data_out

@cocotb.test()
async def tx_test(dut): 
    # Corner cases
    corner_cases = ["0000", "1111", "1010", "0101"]

    for data_in in corner_cases:
        dut.data_in.value = int(data_in, 2)
        expected_data_out = calculate_data_out(data_in)

        await Timer(5, unit="ns")

        expected_data_out_int = int(''.join(map(str, expected_data_out)), 2)
        actual_data_out_int = int(dut.data_out.value)

        # Assert to check if the output matches the expected result
        assert actual_data_out_int == expected_data_out_int, f"Corner Case - data_in={data_in}: expected={expected_data_out_int} got={actual_data_out_int}"

        dut._log.info(f'PASS: Corner Case - data_in={data_in} expected_data_out={expected_data_out} actual_data_out={dut.data_out.value}')

    # Randomized tests
    for _ in range(10):
        data_in = ''.join(str(random.randint(0, 1)) for _ in range(4))
        
        dut.data_in.value = int(data_in, 2)
        expected_data_out = calculate_data_out(data_in)

        await Timer(5, unit="ns")

        expected_data_out_int = int(''.join(map(str, expected_data_out)), 2)
        actual_data_out_int = int(dut.data_out.value)

        # Assert to check if the output matches the expected result
        assert actual_data_out_int == expected_data_out_int, f"Random Test - data_in={data_in}: expected={expected_data_out_int} got={actual_data_out_int}"

        dut._log.info(f'PASS: Random Test - data_in={data_in} expected_data_out={expected_data_out} actual_data_out={dut.data_out.value}')
            
