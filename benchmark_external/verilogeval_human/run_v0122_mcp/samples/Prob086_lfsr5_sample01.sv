// 5-bit Galois LFSR, shifts right, taps at positions 5 and 3 (1-indexed).
// q[0] is the feedback bit: re-enters at MSB (pos 5) and XORs into pos 3.
// Bit index = position-1, so feedback to q[4], tap at q[2].
module TopModule (
  input clk,
  input reset,
  output reg [4:0] q
);

  always @(posedge clk) begin
    if (reset)
      q <= 5'b00001;
    else begin
      q[4] <= q[0];          // position 5: feedback into MSB
      q[3] <= q[4];          // untapped
      q[2] <= q[3] ^ q[0];   // position 3 tap
      q[1] <= q[2];          // untapped
      q[0] <= q[1];          // untapped
    end
  end

endmodule
