// Prob023_vector100r — reverse the bit order of a 100-bit vector.
// out[i] = in[99-i]. Combinational; out is a reg driven from always @(*).
module TopModule (
  input [99:0] in,
  output reg [99:0] out
);

  integer i;
  always @(*) begin
    for (i = 0; i < 100; i = i + 1)
      out[i] = in[99 - i];
  end

endmodule
