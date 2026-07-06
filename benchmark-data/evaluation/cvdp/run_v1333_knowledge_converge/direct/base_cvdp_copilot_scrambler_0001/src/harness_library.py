import cocotb
from cocotb.triggers import FallingEdge, RisingEdge, Timer
import random

async def dut_init(dut):
    # iterate all the input signals and initialize with 0
    for signal in dut:
        try:
            signal.value = 0
        except Exception:
            pass

# Reset the DUT (design under test)
async def reset_dut(reset_n, duration_ns=10):
    reset_n.value = 0
    await Timer(duration_ns, unit="ns")
    reset_n.value = 1
    await Timer(duration_ns, unit='ns')
    reset_n._log.debug("Reset complete")   

class ScramblerModel:
    def __init__(self, data_width=128, lfsr_width=16):
        self.data_width = data_width
        self.lfsr_width = lfsr_width
        self.lfsr = self.initialize_lfsr()
        self.mode = 0
        self.feedback = 0

    def initialize_lfsr(self):
        """Initialize the LFSR to 0100000000000000 (LFSR_INIT)."""
        lfsr = [0] * self.lfsr_width
        lfsr[14] = 1  # Set the second-to-last bit to 1
        self.lfsr = [0] * self.lfsr_width
        self.lfsr[14] = 1  # Set the second-to-last bit to 1        
        return lfsr

    def calculate_feedback(self, mode):
        """Calculate feedback bit based on the selected polynomial mode."""
        self.mode = mode 

        if self.mode == 0:  # x^LFSR_WIDTH + x^(LFSR_WIDTH-1) + 1
            feedback = self.lfsr[-1] ^ self.lfsr[-2]
        elif self.mode == 1:  # x^LFSR_WIDTH + x^(LFSR_WIDTH-2) + 1
            feedback = self.lfsr[-1] ^ self.lfsr[-3]
        elif self.mode == 2:  # x^LFSR_WIDTH + x^(LFSR_WIDTH/2) + x + 1
            feedback = self.lfsr[-1] ^ self.lfsr[self.lfsr_width // 2 - 1] ^ self.lfsr[0]
        elif self.mode == 3:  # x^LFSR_WIDTH + x^(LFSR_WIDTH/2) + 1
            feedback = self.lfsr[-1] ^ self.lfsr[self.lfsr_width // 2 - 1]
        elif self.mode == 4:  # x^LFSR_WIDTH + x^(LFSR_WIDTH-3) + x^2 + 1
            feedback = self.lfsr[-1] ^ self.lfsr[-4] ^ self.lfsr[1]
        elif self.mode == 5:  # x^LFSR_WIDTH + x^(LFSR_WIDTH-4) + 1
            feedback = self.lfsr[-1] ^ self.lfsr[-5]
        elif self.mode == 6:  # x^LFSR_WIDTH + x^3 + x + 1
            feedback = self.lfsr[-1] ^ self.lfsr[2] ^ self.lfsr[0]
        elif self.mode == 7:  # x^LFSR_WIDTH + x^(LFSR_WIDTH-5) + x^4 + 1
            feedback = self.lfsr[-1] ^ self.lfsr[-6] ^ self.lfsr[3]
        elif self.mode == 8:  # x^LFSR_WIDTH + x + 1
            feedback = self.lfsr[-1] ^ self.lfsr[0]
        else:  # Default: x^LFSR_WIDTH + 1
            feedback = self.lfsr[-1]
        return feedback


    def shift_lfsr(self):
        """Shift the LFSR to the right and insert the feedback at MSB."""
        self.lfsr = [self.feedback] + self.lfsr[:-1]

    def update(self, mode, data_in):
        scrambled_data = 0
        for i in range(self.data_width):
            # Get LFSR bit for the current position
            lfsr_bit = self.lfsr[i % self.lfsr_width]
            
            # Combine LFSR bit with input data bit
            data_bit = (data_in >> i) & 1
            scrambled_data |= (lfsr_bit) << i        

        self.feedback = self.calculate_feedback(mode)
        self.shift_lfsr()

        return scrambled_data

    def scramble(self, data_in, mode):
        """Scramble the input data using the LFSR."""
        scrambled_data = 0
        self.update(mode, data_in)

        for i in range(self.data_width):
            # Get LFSR bit for the current position
            lfsr_bit = self.lfsr[i % self.lfsr_width]
            
            # Combine LFSR bit with input data bit
            data_bit = (data_in >> i) & 1
            scrambled_data |= (lfsr_bit ^data_bit) << i
            #scrambled_data |= (lfsr_bit) << i


        return scrambled_data