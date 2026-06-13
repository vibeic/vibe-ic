module TopModule (
  input         clk,
  input         reset,
  output [31:0] q
);

  reg [31:0] state;

  // Galois LFSR shifting right. Taps at bit positions 32, 22, 2, 1
  // (1-indexed). The LSB q[0] is the feedback bit; tapped positions are
  // XORed with q[0] as they receive the incoming bit.
  always @(posedge clk) begin
    if (reset)
      state <= 32'h1;
    else begin
      state    <= state >> 1;          // default shift right
      state[31] <= state[0];           // feedback into MSB (tap 32)
      state[21] <= state[22] ^ state[0]; // tap 22
      state[1]  <= state[2]  ^ state[0]; // tap 2
      state[0]  <= state[1]  ^ state[0]; // tap 1
    end
  end

  assign q = state;

endmodule
