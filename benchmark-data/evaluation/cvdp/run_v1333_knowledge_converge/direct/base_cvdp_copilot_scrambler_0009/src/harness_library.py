import cocotb
from cocotb.triggers import FallingEdge, RisingEdge, Timer

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
        #return out_data_int
        return in_data

class DataProcessor:
    def __init__(self, sub_blocks, intra_block_class, data_width=256, out_data_width = 16, chunk_size=8, nbw_counter_output=2, wait_cycles=4):
        self.sub_blocks = sub_blocks
        self.counter_sub_blocks = 0

        self.n_cycles = int(data_width*sub_blocks/out_data_width)
        self.counter_sub_out = 0#(1 << nbw_counter_output) - 1
        self.counter_output  = 0#(1 << self.n_cycles) - 1

        self.intra_blocks = [intra_block_class() for _ in range(sub_blocks)]
        self.in_data_reg = [0 for _ in range(sub_blocks)]
        self.out_data_intra_block_reg = [0 for _ in range(sub_blocks)]
        self.out_data_aux = [0 for _ in range(sub_blocks)]
        self.data_width = data_width
        self.out_data_width = out_data_width
        self.chunk_size = chunk_size
        self.out_data = 0
        self.wait_cycles = wait_cycles + 5
        self.start_intra = [0] * (self.wait_cycles)
        self.offset = 0

    def process_data(self, rst_n, i_valid, in_data):
        if not rst_n:
            # Reset logic
            self.counter_sub_blocks = 0
            self.start_intra = [0] * (self.wait_cycles)
            self.in_data_reg = [0 for _ in range(self.sub_blocks)]
        else:
            if i_valid:
                # Register input data
                self.in_data_reg[self.counter_sub_blocks] = in_data

                if self.counter_sub_blocks == self.sub_blocks - 1:
                    self.counter_sub_blocks = 0
                    self.start_intra[0] = True
                else:
                    self.counter_sub_blocks += 1
                    self.start_intra[0] = False

        # Process data through intra_block modules
        for k in range(self.sub_blocks):
            self.out_data_intra_block_reg[k] = self.intra_blocks[k].rearrange_data(self.in_data_reg[k])

    def update_output_data(self, rst_n):
        if not rst_n:
            # Reset logic
            self.counter_sub_out = 0#3  # Set all bits to 1
            self.counter_output  = 0#(1 << self.n_cycles) - 1
            self.out_data = 0
            self.out_data_aux = [0 for _ in range(self.sub_blocks)]
        elif self.start_intra[self.wait_cycles-1] or self.counter_output > 0:# ((1 << self.n_cycles) - 1):
            # Update auxiliary and final output data
            for i in range(32):
                chunk_start = (i + 1) * self.chunk_size - self.chunk_size
                block_index = i % self.sub_blocks
                self.out_data_aux[0] |= ((self.out_data_intra_block_reg[block_index] >> chunk_start) & ((1 << self.chunk_size) - 1)) << chunk_start
                self.out_data_aux[1] |= ((self.out_data_intra_block_reg[block_index] >> (((i + 1) % 32 + 1) * self.chunk_size - self.chunk_size)) & ((1 << self.chunk_size) - 1)) << chunk_start
                self.out_data_aux[2] |= ((self.out_data_intra_block_reg[block_index] >> (((i + 2) % 32 + 1) * self.chunk_size - self.chunk_size)) & ((1 << self.chunk_size) - 1)) << chunk_start
                self.out_data_aux[3] |= ((self.out_data_intra_block_reg[block_index] >> (((i + 3) % 32 + 1) * self.chunk_size - self.chunk_size)) & ((1 << self.chunk_size) - 1)) << chunk_start


            # Update out_data based on counter values
            offset        = (((self.counter_output) % self.n_cycles) * self.out_data_width) % self.data_width
            self.offset   = offset
            chunk_mask    = (1 << self.out_data_width) - 1
            self.out_data = (self.out_data_aux[self.counter_sub_out] >> offset) & chunk_mask

            self.counter_sub_out = (self.counter_sub_out + 1) % self.sub_blocks
            self.counter_output = (self.counter_output + 1) % self.n_cycles
            #self.out_data = self.out_data_aux[self.counter_sub_out]
        for i in range(self.wait_cycles-1, 0, -1):
            self.start_intra[i] = self.start_intra[i - 1]        

    def get_output_data(self):
        return self.out_data
