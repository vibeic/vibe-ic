module TopModule (
  input         clk,
  input         load,
  input  [511:0] data,
  output [511:0] q
);
  reg [511:0] state;
  always @(posedge clk) begin
    if (load)
      state <= data;
    else begin
      state <= ({1'b0, state[511:1]}) ^ ({state[510:0], 1'b0});
    end
  end
  assign q = state;
endmodule
