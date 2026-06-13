module TopModule (
  input  [2:0]  a,
  output [15:0] q
);
  reg [15:0] r;
  always @(*) begin
    case (a)
      3'd0: r = 16'h1232;
      3'd1: r = 16'haee0;
      3'd2: r = 16'h27d4;
      3'd3: r = 16'h5a0e;
      3'd4: r = 16'h2066;
      3'd5: r = 16'h64ce;
      3'd6: r = 16'hc526;
      3'd7: r = 16'h2f19;
      default: r = 16'h0000;
    endcase
  end
  assign q = r;
endmodule
