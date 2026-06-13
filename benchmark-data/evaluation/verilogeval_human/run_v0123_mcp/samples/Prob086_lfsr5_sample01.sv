module TopModule (
  input clk,
  input reset,
  output reg [4:0] q
);
  // Galois LFSR shift right, q[0] feedback. Taps 5,3 -> bits 4,2 receive XOR.
  always @(posedge clk) begin
    if (reset)
      q <= 5'h1;
    else begin
      q[4] <= q[0];           // tap 5
      q[3] <= q[4];
      q[2] <= q[3] ^ q[0];    // tap 3
      q[1] <= q[2];
      q[0] <= q[1];
    end
  end
endmodule
