module hamming_rx #(
  parameter int DATA_WIDTH = 4,
  parameter int PARITY_BIT = 3,
  // Total encoded width = parity + data + 1 redundant bit
  parameter int ENCODED_DATA = PARITY_BIT + DATA_WIDTH + 1,
  // Minimum number of bits needed to index ENCODED_DATA
  parameter int ENCODED_DATA_BIT = (ENCODED_DATA <= 1) ? 1 : $clog2(ENCODED_DATA)
) (
  input  logic [ENCODED_DATA-1:0] data_in,
  output logic [DATA_WIDTH-1:0]   data_out
);

  // Internal parity (syndrome) bits and corrected data
  logic [PARITY_BIT-1:0]   parity;
  logic [ENCODED_DATA-1:0] correct_data;

  integer n;
  integer i;
  integer idx;
  logic [ENCODED_DATA_BIT-1:0] err_pos;

  always @(*) begin
    // 1. Initialization
    parity       = '0;
    correct_data = '0;
    data_out     = '0;

    // 2. Error detection using even-parity (XOR) logic.
    //    parity[n] XORs all data_in bits whose index has bit n set.
    for (n = 0; n < PARITY_BIT; n = n + 1) begin
      parity[n] = 1'b0;
      for (i = 0; i < ENCODED_DATA; i = i + 1) begin
        if ((i >> n) & 1)
          parity[n] = parity[n] ^ data_in[i];
      end
    end

    // 3. Error correction.
    correct_data = data_in;
    if (parity != '0) begin
      err_pos = parity[ENCODED_DATA_BIT-1:0];
      // Redundant bit at position 0 is never inverted (syndrome != 0 here).
      correct_data[err_pos] = ~correct_data[err_pos];
    end

    // 4. Output assignment: data bits live at non-power-of-2 positions
    //    (excluding redundant position 0), taken LSB->MSB.
    idx = 0;
    for (i = 1; i < ENCODED_DATA; i = i + 1) begin
      // i is a power of two when (i & (i-1)) == 0
      if (((i & (i - 1)) != 0) && (idx < DATA_WIDTH)) begin
        data_out[idx] = correct_data[i];
        idx = idx + 1;
      end
    end
  end

endmodule
