module TopModule (
  input        clk,
  input        reset,
  output [4:0] q
);

  reg [4:0] state;

  // 5-bit Galois LFSR shifting right. Taps at bit positions 5 and 3
  // (1-indexed). q[0] is the feedback bit.
  always @(posedge clk) begin
    if (reset)
      state <= 5'h1;
    else begin
      state    <= state >> 1;
      state[4] <= state[0];            // feedback into MSB (tap 5)
      state[2] <= state[3] ^ state[0]; // tap 3
    end
  end

  assign q = state;

endmodule
