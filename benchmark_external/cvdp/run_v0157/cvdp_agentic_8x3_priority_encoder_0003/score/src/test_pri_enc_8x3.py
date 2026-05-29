import cocotb
from cocotb.triggers import Timer
import harness_library as hrs_lb
from math import ceil, log2

# ----------------------------------------
# - Tests
# ----------------------------------------

@cocotb.test()
async def test_penc(dut):
    # initialize the DUT and wait for a short time
    await hrs_lb.dut_init(dut)
    await Timer(10, unit="ns")

    for index in range(256):
        print("input value =", bin(index))
        dut._id("in", extended=False).value = index
        await Timer(10, unit="ns")
        msb_1_bit_num = hrs_lb.highbit_number(index, msb=True, length=8)

        # ----------------------------------------
        # - Check No Operation
        # ----------------------------------------
        assert (dut.out.value == msb_1_bit_num), f"encoder input = {index} and output is {dut.out.value} expecting {msb_1_bit_num}"