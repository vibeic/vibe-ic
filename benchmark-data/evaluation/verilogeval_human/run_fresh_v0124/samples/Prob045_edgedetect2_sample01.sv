module TopModule (
  input clk,
  input [7:0] in,
  output reg [7:0] anyedge
);

  reg [7:0] in_prev;

  always @(posedge clk) begin
    anyedge <= in ^ in_prev;  // any bit that changed since last cycle
    in_prev <= in;
  end


  // power-up determinism (rtl_hygiene_lint --fix): reset-less registered
  // outputs default to 0 so they are not X at t=0.
  initial begin
    anyedge = 0;
  end

endmodule
