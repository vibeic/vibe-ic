module TopModule (
  input [2:0] in,
  output reg [1:0] out
);

  integer i;
  always @(*) begin
    out = 0;
    for (i = 0; i < 3; i = i + 1)
      out = out + in[i];
  end

endmodule
