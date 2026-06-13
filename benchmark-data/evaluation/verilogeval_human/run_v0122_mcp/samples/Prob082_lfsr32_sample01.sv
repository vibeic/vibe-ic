// 32-bit Galois LFSR, shifts right, taps at bit positions 32,22,2,1 (1-indexed).
// q[0] is the feedback bit. It re-enters at the MSB (position 32) and is
// XORed into each tapped position; untapped positions just shift right.
// Bit index = position-1, so taps at indices 31,21,1,0.
module TopModule (
  input clk,
  input reset,
  output reg [31:0] q
);

  always @(posedge clk) begin
    if (reset)
      q <= 32'h1;
    else begin
      q[31] <= q[0];                 // position 32: feedback into MSB
      q[30:22] <= q[31:23];          // untapped
      q[21] <= q[22] ^ q[0];         // position 22 tap
      q[20:2] <= q[21:3];            // untapped
      q[1] <= q[2] ^ q[0];           // position 2 tap
      q[0] <= q[1] ^ q[0];           // position 1 tap
    end
  end

endmodule
