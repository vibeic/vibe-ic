module TopModule (
  input  clk,
  input  reset,
  output reg [4:0] q
);
  // 5-bit Galois LFSR, shift right, taps at positions 5 and 3 (1-indexed)
  always @(posedge clk) begin
    if (reset)
      q <= 5'h1;
    else begin
      q <= q >> 1;
      q[4] <= q[0];
      q[2] <= q[3] ^ q[0];
    end
  end
endmodule
