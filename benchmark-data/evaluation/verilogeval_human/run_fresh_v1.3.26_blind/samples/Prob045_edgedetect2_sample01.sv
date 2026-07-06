module TopModule (
  input clk,
  input [7:0] in,
  output reg [7:0] anyedge
);

  reg [7:0] d_last;

  always @(posedge clk) begin
    d_last <= in;
    anyedge <= in ^ d_last;
  end


  // power-up determinism (rtl_hygiene_lint --fix): reset-less registered
  // outputs default to 0 so they are not X at t=0.
  initial begin
    anyedge = 0;
    d_last = 0;
  end

endmodule
