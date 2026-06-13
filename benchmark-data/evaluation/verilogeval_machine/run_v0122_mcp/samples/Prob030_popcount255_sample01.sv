// Prob030_popcount255 — count the set bits of a 255-bit vector.
// out = sum of in[0..254]; max 255 fits in 8 bits. Combinational.
module TopModule (
  input [254:0] in,
  output reg [7:0] out
);

  integer i;
  always @(*) begin
    out = 8'd0;
    for (i = 0; i < 255; i = i + 1)
      out = out + in[i];
  end

endmodule
