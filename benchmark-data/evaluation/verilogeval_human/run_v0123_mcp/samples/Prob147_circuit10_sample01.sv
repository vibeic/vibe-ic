module TopModule (
  input clk,
  input a,
  input b,
  output q,
  output state
);

  reg s;

  always @(posedge clk) begin
    if (a & b)
      s <= 1'b1;        // set
    else if (~a & ~b)
      s <= 1'b0;        // reset
    // else hold
  end

  assign state = s;
  assign q     = s ? ~(a ^ b) : (a ^ b);

endmodule
