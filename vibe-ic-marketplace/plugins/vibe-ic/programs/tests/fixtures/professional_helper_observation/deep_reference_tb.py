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
    await Timer(20, units="ns")
    dut.rst_n.value = 1
    env = WireEnvironment(dut)
    env.start()
    for value in range(256):
        await env.write(value)
        actual = await block_value(env)
        expected = bytes([value ^ 0x3a]) * 2
        assert actual == expected
    print("PROFESSIONAL_TB PASS")
