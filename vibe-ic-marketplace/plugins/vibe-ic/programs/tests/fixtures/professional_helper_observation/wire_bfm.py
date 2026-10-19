from cocotb.triggers import Timer
class WireEnvironment:
    def __init__(self, dut):
        self.dut = dut
    async def output(self):
        await Timer(1, units="ns")
        return int(self.dut.out_o.value)
