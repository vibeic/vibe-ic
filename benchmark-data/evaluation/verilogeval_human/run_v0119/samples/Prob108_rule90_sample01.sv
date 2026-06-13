module TopModule (
  input clk,
  input load,
  input [511:0] data,
  output reg [511:0] q = 512'b0
);
  // q[i]_next = q[i-1] ^ q[i+1], boundaries 0.
  // (q << 1) places q[i-1] at position i; (q >> 1) places q[i+1] at position i.
  always @(posedge clk) begin
    if (load)
      q <= data;
    else
      q <= (q << 1) ^ (q >> 1);
  end
endmodule
