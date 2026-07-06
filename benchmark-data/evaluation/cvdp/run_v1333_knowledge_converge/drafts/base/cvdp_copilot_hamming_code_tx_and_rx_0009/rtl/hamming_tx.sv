module hamming_tx #(
  parameter int DATA_WIDTH = 4,
  parameter int PARITY_BIT = 3,
  parameter int ENCODED_DATA = PARITY_BIT + DATA_WIDTH + 1,
  parameter int ENCODED_DATA_BIT = $clog2(ENCODED_DATA)
)(
  input  logic [DATA_WIDTH-1:0]   data_in,
  output logic [ENCODED_DATA-1:0] data_out
);

  // Return 1 if index i is a power of two (parity-bit position), else 0.
  function automatic bit is_power_of_two(input int i);
    is_power_of_two = (i > 0) && ((i & (i - 1)) == 0);
  endfunction

  always_comb begin
    logic [PARITY_BIT-1:0] parity;
    int data_idx;

    // Step 1: clear all internal registers.
    data_out = '0;
    parity   = '0;

    // Step 2: map data_in into non-parity, non-redundant positions (LSB first).
    data_idx = 0;
    for (int i = 1; i < ENCODED_DATA; i++) begin
      if (!is_power_of_two(i)) begin
        if (data_idx < DATA_WIDTH) begin
          data_out[i] = data_in[data_idx];
          data_idx++;
        end
      end
    end
    // data_out[0] is the redundant bit, always 1'b0 (already cleared).

    // Step 3: compute even parity bits.
    // parity[n] = XOR of all data_out[i] where bit n of index i is set.
    for (int n = 0; n < PARITY_BIT; n++) begin
      for (int i = 1; i < ENCODED_DATA; i++) begin
        if ((i >> n) & 1) begin
          parity[n] = parity[n] ^ data_out[i];
        end
      end
    end

    // Step 4: insert parity bits at power-of-two positions (2^n).
    for (int n = 0; n < PARITY_BIT; n++) begin
      if ((1 << n) < ENCODED_DATA) begin
        data_out[1 << n] = parity[n];
      end
    end
  end

endmodule
