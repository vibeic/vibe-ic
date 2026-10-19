from cocotb.triggers import Timer
class WireEnvironment:
    def __init__(self, dut):
        self.dut = dut
    async def background(self):
        await Timer(1, units="ns")
    def start(self):
        self.background()
    async def write(self, value):
        d = self.dut
        d.data_i.value = value
        await Timer(10, units="ns")
    async def transfer(self):
        d = self.dut
        for _ in range(3):
            await Timer(1, units="ns")
            observed = int(d.out_o.value)
            if observed >= 0:
                break
        return observed & 255
    async def read(self):
        return await self.transfer()
    async def wait_status(self, limit=3):
        for _ in range(limit):
            status = await self.read()
            if status >= 0:
                return status
        raise AssertionError("no response")
    async def output(self):
        await self.wait_status()
        result = b""
        for _ in range(2):
            result += (await self.read()).to_bytes(1, "little")
        return result
