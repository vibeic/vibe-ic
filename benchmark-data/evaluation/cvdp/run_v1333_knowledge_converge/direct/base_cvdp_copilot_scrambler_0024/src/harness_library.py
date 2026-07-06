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

class IntraBlock:
    def __init__(self, row_col_width=16):
        """
        Initialize the IntraBlock class with configurable ROW_COL_WIDTH.

        :param row_col_width: Width and height of the square matrix (default: 16).
        """
        self.row_col_width = row_col_width
        self.data_width = row_col_width * row_col_width  # Total bits in the input/output data

    def rearrange_data(self, in_data):
        """
        Rearrange the input data based on row and column transformations.

        :param in_data: Input data as an integer representing the binary value (length: data_width bits).
        :return: Rearranged output data as an integer.
        """
        if not (0 <= in_data < (1 << self.data_width)):
            raise ValueError(f"Input data must be an integer with up to {self.data_width} bits.")

        # Temporary storage for intermediate calculations
        r_prime = [0] * self.data_width  # Row index for each bit
        c_prime = [0] * self.data_width  # Column index for each bit
        output_index = [0] * self.data_width
        out_data = [0] * self.data_width

        # Extract bits from in_data
        in_bits = [(in_data >> i) & 1 for i in range(self.data_width)]

        # Calculate r_prime and c_prime for each bit
        for i in range(self.data_width):
            if i < self.data_width // 2:
                r_prime[i] = (i - 2 * (i // self.row_col_width)) % self.row_col_width
                c_prime[i] = (i - (i // self.row_col_width)) % self.row_col_width
            else:
                r_prime[i] = (i - 2 * (i // self.row_col_width) - 1) % self.row_col_width
                c_prime[i] = (i - (i // self.row_col_width) - 1) % self.row_col_width

        # Calculate output indices and rearrange data
        for j in range(self.data_width):
            output_index[j] = r_prime[j] * self.row_col_width + c_prime[j]
            out_data[j] = in_bits[output_index[j]]

        # Convert the output data list to an integer
        out_data_int = sum(bit << i for i, bit in enumerate(out_data))
        return out_data_int