import cocotb
from cocotb.clock import Clock
from cocotb.triggers import Timer
from wire_bfm import WireEnvironment

async def block_value(env):
    return await env.output()

@cocotb.test()
async def port_result(dut):
    cocotb.start_soon(Clock(dut.clk_i, 10, units="ns").start())
    dut.rst_n.value = 0
    dut.data_i.value = 0
    await Timer(20, units="ns")
    dut.rst_n.value = 1
    env = WireEnvironment(dut)
    for value in range(256):
        dut.data_i.value = value
        await Timer(10, units="ns")
        actual = await block_value(env)
        expected = value ^ 0x3a
        assert actual == expected
    print("PROFESSIONAL_TB PASS")
