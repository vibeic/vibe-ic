module TopModule (
  input [7:0] in,
  output reg [2:0] pos
);

  integer i;
  always @(*) begin
    pos = 3'd0;
    for (i = 7; i >= 0; i = i - 1) begin
      if (in[i])
        pos = i[2:0];
    end
  end

endmodule
