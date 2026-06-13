module TopModule (
  input  clk,
  input  reset,
  output reg [31:0] q
);
  // Galois LFSR, shift right, taps at positions 32,22,2,1 (1-indexed)
  always @(posedge clk) begin
    if (reset)
      q <= 32'h1;
    else begin
      q <= q >> 1;
      q[31] <= q[0];
      q[21] <= q[22] ^ q[0];
      q[1]  <= q[2]  ^ q[0];
      q[0]  <= q[1]  ^ q[0];
    end
  end
endmodule
